"""
build_tools.py — Build-advice helpers on top of LookupService.

`verify_build` checks every gem / passive name of a draft build against the local data and
returns the real facts plus a numbered, code-rendered source list. `supports_for` lists the
support gems that can support a skill, `reference_builds` summarises the poe.ninja ladder
snapshot without character names, `export_pob` turns a verified build into a Path of Building
code. The MCP server calls these functions; nothing here calls an LLM or the network.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from src.catalog.entity_index import PASSIVE_TYPE_TO_KIND, make_aliases
from src.catalog.spec import GEM_KINDS, ITEM_KINDS
from src.scrapers.common import clean_text
from src.tools.items import ITEM_KIND_NAMES, AmbiguousItem, ItemLookup, item_fact_lines
from src.tools.lookup import (
    BadArgument,
    LookupFailed,
    LookupService,
    TREE_DATA_LABEL,
    NotFound,
    ServiceUnavailable,
    _cap,
    _gem_matches,
    _lang,
    _limit,
    _require,
    _sources,
    is_cjk,
)
from src.tools.pathing import PassivePathfinder
from src.tools.pob_export import (
    ATTRIBUTES,
    GEM_LEVEL,
    GEM_QUALITY,
    PobBuild,
    PobGem,
    PobItem,
    PobSkillGroup,
    build_xml,
    encode_code,
    pob_level,
    upper_value,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_NAMES = 40
DETAIL_LEVELS = ("full", "brief")
# brief: enough to know what passed and how to cite it, for a caller that already holds the records
BRIEF_KEYS = ("input", "slug", "id", "kind", "type", "name", "name_zh_tw", "item_class", "affix", "family", "cite")
MAX_AFFIXES = 60     # ten gear slots (two rings) with 3 prefixes + 3 suffixes each, in one call
MAX_NAME_LEN = 120
MAX_SUGGESTIONS = 3
MAX_PER_AFFIX = 3    # a rare item holds at most 3 prefixes and 3 suffixes
AFFIX_SEPARATOR = re.compile(r"\s*[:：]\s*")
MAX_ECHO_LEN = 80
COMMON_TOP = 10
MAX_STAT_LINES = 6     # stat lines of a gem kept in a verified fact
MAX_TEXT_STATS = 40    # rule-like stat lines listed for a route
START_NODE_TYPE = "ClassStart"
START_REASON = "this is a class or ascendancy start node, not a passive to allocate"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
PASSIVE_KINDS = tuple(PASSIVE_TYPE_TO_KIND.values())
BUILDS_FILE = Path("data") / "community_builds" / "poe_ninja_builds.jsonl"
POE_NINJA_URL = "https://poe.ninja/poe2/builds"
POE2DB_LABEL = "poe2db"
GEM_FACT_FIELDS = ("slug", "kind", "name", "tier", "tags", "cost", "main_stat", "requires_weapons", "description",
                   "quality_effects")
BUILD_FIELDS = ("class", "main_skill", "rank", "level", "skill_gems", "keystones")  # never character_name
MAX_SKILL_GROUPS = 12
MAX_SUPPORTS = 5          # supports per skill group
MAX_GROUP_LEN = 400       # one "skill: support, support" entry
MAX_TITLE_LEN = 80
SUPPORT_SEPARATOR = re.compile(r"\s*[,，、]\s*")
NO_GAME_ID = "the local record has no game id, so Path of Building could not load this gem"
ATTRIBUTE_TYPE = "Attribute"     # passive type of the "+5 to any Attribute" nodes
ATTRIBUTE_PASSIVE_VALUE = 5
ATTRIBUTE_COLUMNS = {"Str": "str", "Dex": "dex", "Int": "int"}   # level table columns and requires_stats
ATTRIBUTE_FAMILIES = {   # stat families of fixed attribute lines on passives
    "strength": ("str",), "dexterity": ("dex",), "intelligence": ("int",), "all attributes": ("str", "dex", "int"),
    "strength and dexterity": ("str", "dex"), "strength and intelligence": ("str", "int"),
    "dexterity and intelligence": ("dex", "int"),
}
SUPPORT_NEED = re.compile(r"\+(\d+)\s+(Str|Dex|Int)\b")
MAX_CHARACTER_LEVEL = 100
MAX_EVIDENCE = 3            # pieces of evidence kept per configuration option
MAX_EVIDENCE_LEN = 160
LEVEL_TABLE_COLUMNS = {"Level", "Requires Level", "Str", "Dex", "Int", "Mana", "Cost", "Base Damage", "Life", "Spirit",
                       "Cooldown", "Uses", "Damage Effectiveness"}
MAX_GEAR = 16             # gear entries in one export
MAX_GEAR_LEN = 600        # one "slot: item; modifier; modifier" entry
GEAR_SEPARATOR = re.compile(r"\s*[;；]\s*")
RARE_NAME = "POBG {slot}"  # a rare's name is random in the game and unused by PoB: a plain label, not a fake name
# Hands as Path of Building's ItemsTab:IsItemValidForSlot has them (without Giant's Blood and the
# other keystones that widen the off-hand). Spears, wands and sceptres are one-handed but only a
# sceptre of those goes in the off-hand; a quiver only behind a bow; nothing behind a two-hander.
OFFHAND_WEAPONS = ("One Hand Maces", "One Hand Axes", "One Hand Swords", "Claws", "Daggers", "Flails")
ONE_HANDED = (*OFFHAND_WEAPONS, "Spears", "Wands", "Sceptres")
TWO_HANDED = ("Bows", "Crossbows", "Quarterstaves", "Staves", "Two Hand Maces", "Two Hand Axes", "Two Hand Swords",
              "Talismans", "Traps")
OFFHAND_ONLY = ("Shields", "Bucklers", "Foci", "Sceptres")
NO_WEAPON_OFFHAND = ("Wands", "Sceptres")     # main hands that take no weapon in the off-hand
SLOT_CLASSES = {   # PoB slot -> item classes that go there
    "Weapon 1": (*ONE_HANDED, *TWO_HANDED),
    "Weapon 2": (*OFFHAND_ONLY, "Quivers", *OFFHAND_WEAPONS),
    "Helmet": ("Helmets",), "Body Armour": ("Body Armours",), "Gloves": ("Gloves",), "Boots": ("Boots",),
    "Amulet": ("Amulets",), "Ring 1": ("Rings",), "Ring 2": ("Rings",), "Belt": ("Belts",),
    "Charm 1": ("Charms",), "Charm 2": ("Charms",), "Charm 3": ("Charms",),
    "Flask 1": ("Life Flasks",), "Flask 2": ("Mana Flasks",),
}
SLOT_ALIASES = {
    **{slot.casefold(): slot for slot in SLOT_CLASSES},
    "weapon": "Weapon 1", "main hand": "Weapon 1", "off hand": "Weapon 2", "offhand": "Weapon 2",
    "body": "Body Armour", "ring": "Ring", "charm": "Charm", "life flask": "Flask 1", "mana flask": "Flask 2",
    "武器": "Weapon 1", "主手": "Weapon 1", "副手": "Weapon 2", "頭盔": "Helmet", "頭部": "Helmet", "胸甲": "Body Armour",
    "手套": "Gloves", "鞋子": "Boots", "項鍊": "Amulet", "戒指": "Ring", "戒指 1": "Ring 1", "戒指 2": "Ring 2",
    "戒指1": "Ring 1", "戒指2": "Ring 2", "腰帶": "Belt", "護符": "Charm", "護符 1": "Charm 1", "護符 2": "Charm 2",
    "護符 3": "Charm 3", "護符1": "Charm 1", "護符2": "Charm 2", "護符3": "Charm 3", "生命藥劑": "Flask 1",
    "魔力藥劑": "Flask 2", "藥劑 1": "Flask 1", "藥劑 2": "Flask 2", "藥劑1": "Flask 1", "藥劑2": "Flask 2",
}
NUMBERED_SLOTS = {"Ring": ("Ring 1", "Ring 2"), "Charm": ("Charm 1", "Charm 2", "Charm 3")}   # "ring" = the next free one
NO_GEAR_FACT, NO_WEAPON_FACT = 1, 2     # positions in TEXT[lang]["pob_facts"]
HIDDEN_LINE = "(Hidden)"      # unique lines the game does not show; PoB cannot read them
SPIRIT_COST = re.compile(r"^(\d+) Spirit\b")                           # a spirit gem's `cost`
SPIRIT_RANGE = re.compile(r"\)\s*Spirit\b")                            # "(90 — 30) Spirit": by gem level, not per level here
SPIRIT_MULTIPLIER = re.compile(r"Reservation Multiplier: (\d+)%")
SPIRIT_TO_LIFE = re.compile(r"Reserve Life instead of Spirit", re.I)
BASE_SPIRIT = re.compile(r"^Spirit: (\d+)$")                             # a sceptre's base property
SPIRIT_EXTRA = re.compile(r"Additional Reservation: (\d+) Spirit\b")    # a support's `main_stat`
SPIRIT_LINE = re.compile(r"^\+(\d+) to Spirit$")                        # a fixed Spirit line on gear
SPIRIT_FAMILY = "spirit"                                               # the passive stat family "+# to Spirit"
# -- PoB configuration: an option is switched on only with evidence in this build's own text -----------
CHARGE_OPTIONS = {"power": "usePowerCharges", "frenzy": "useFrenzyCharges", "endurance": "useEnduranceCharges"}
STATE_OPTIONS = {   # PoB option -> words that inflict the state
    "conditionEnemyShocked": "shock|shocks", "conditionEnemyIgnited": "ignite|ignites",
    "conditionEnemyChilled": "chill|chills", "conditionEnemyFrozen": "freeze|freezes",
    "conditionEnemyBleeding": "bleeding|bleed|bleeds", "conditionEnemyPoisoned": "poison|poisons",
    "conditionEnemyBlinded": "blind|blinds", "conditionEnemyDazed": "daze|dazes",
}
EXPOSURE_OPTIONS = {"lightning": "conditionEnemyLightningExposure", "cold": "conditionEnemyColdExposure",
                    "fire": "conditionEnemyFireExposure"}
ELEMENT_OPTIONS = {   # glossary: hits of this element can inflict the state ("Lightning damage from Hits ...")
    "lightning": ("conditionEnemyShocked", "Shock"), "cold": ("conditionEnemyChilled", "Chill"),
    "fire": ("conditionEnemyIgnited", "Ignite"),
}
CRIT_RECENTLY = "conditionCritRecently"
CONFIG_ORDER = (*CHARGE_OPTIONS.values(), CRIT_RECENTLY, *STATE_OPTIONS, *EXPOSURE_OPTIONS.values())
NINJA_OPTIONS = ("conditionCritRecently", "conditionEnemyBleeding", "conditionEnemyBlinded", "conditionEnemyChilled",
                 "conditionEnemyColdExposure", "conditionEnemyDazed", "conditionEnemyIgnited",
                 "conditionEnemyLightningExposure")   # what poe.ninja's PoB exports switch on for every character
NOT_EVIDENCE = re.compile(r"\b(cannot|can't|unable to|never|immune|instead|would gain|if you have at least|haven't|"
                          r"have not|is calculated)\b", re.I)
CHARGE_GAIN = r"\b(gain|gains|grant|grants|generate|generates)\b[^.;]*?\b{kind} charges?\b"
CHARGE_TRIGGERED = (r"\b(when|whenever|if|on) (you |supported skills? )?(gain|generat)|\bconsum\w* (all |your |\w+ )?{kind} charge"
                    r"|\bper {kind} charge|\b{kind} charges? consumed|\bmaximum {kind} charges")
STATE_CAUSE = (r"\b(inflicts?|inflicting|causes?|causing|applies|apply)\s+(?:\w+\s+){{0,2}}?(?:{w})\b"
               r"|\bchance to (?:inflict |cause |apply )?(?:{w})\b"
               r"|(?:^|, but )(?:always )?(?:supported skills |minions from supported skills |minions |this skill "
               r"|companions )?(?:{w})s? (?:enemies|the target|targets|them|on hit|on critical|when hitting)\b"
               r"|\band (?:{w})(?:s|ing)? (?:enemies|them)\b")
STATE_BENEFIT = (r"\b(?:against|vs\.?|on) (?:\w+ ){{0,2}}(?:{w})\w* (?:enemies|enemy|targets?)"
                 r"|\b(?:increased|reduced|more|less) chance to (?:inflict |cause |apply )?(?:{w})|\baggravat"
                 r"|\byou inflict (?:{w})|(?:{w})\w* enemies you (?:kill|hit)"
                 r"|(?:{w})\w* (?:enemies|enemy) (?:take|have|are|deal)|\bwhile (?:\w+ )?(?:{w})|\bto be (?:{w})"
                 r"|(?:{w})\w* (?:you inflict|inflicted|caused by|it inflicts|it applies|applied to you)"
                 r"|\bconsum\w* (?:the |their |your |\w+ )?(?:{w})"
                 r"|\b(?:inflicted|its|their|refresh\w*|it) (?:{w})|\b(?:when|by|on) (?:it )?inflict\w*|\bto you\b")
EXPOSURE_CAUSE = re.compile(r"\b(inflicts?|inflicting|applies|apply)\s+(?:(lightning|cold|fire|elemental)\s+)?exposure\b", re.I)
CRIT_RECENT = re.compile(r"(if you've|if you have) dealt a critical hit recently|critically hit recently|crit recently", re.I)
DAMAGE_TAGS = {"attack", "spell", "projectile", "minion", "melee", "strike", "slam", "grenade", "trap", "totem"}
NON_HIT_TAGS = {"curse", "buff", "aura", "herald", "persistent", "mark"}   # spell-tagged but they do not hit themselves
NOT_A_BLOCK = re.compile(r"\bcannot (?:support|consume|be)\b", re.I)   # rules about the support, not the skill
CANNOT = re.compile(r"\b(cannot|can't)\b", re.I)
GEAR_ELEMENT = re.compile(r"\badds \d+ to \d+ (lightning|cold|fire) damage", re.I)
INTERNAL_LINE = re.compile(r"^[a-z]")   # untranslated stat ids ("local weapon implicit hidden …"): game text never starts lower-case
GEAR_ATTRIBUTE = re.compile(r"^\+(\d+) to (Strength|Dexterity|Intelligence|all Attributes|Strength and Dexterity|"
                            r"Strength and Intelligence|Dexterity and Intelligence)$")
ATTRIBUTE_ALIASES = {"str": "str", "strength": "str", "力量": "str", "dex": "dex", "dexterity": "dex",
                     "敏捷": "dex", "int": "int", "intelligence": "int", "智慧": "int"}
TEXT = {
    "en": {
        "header": "## Sources",
        "fetched": "{label}, fetched {date}",
        "no_page": "passive nodes without a poe2db page",
        "zh_text": "Traditional Chinese names and stat lines of those nodes",
        "path_note": ("Approximate route: it connects every target from the class start but is not guaranteed "
                      "to use the fewest points. points_alone is each target's cost on its own; added_points is "
                      "what only that target needs. Weapon-set passive points and jewels are not modelled."),
        "removed": "Not found in local data (removed): {names}",
        "replaced": "{name} (replaced by {other})",
        "reference": "Reference builds: [{label}]({url}) — ladder snapshot {date}",
        "matched": ", {total} characters matched",
        "ninja": "poe.ninja PoE2 builds",
        "pob_title": "{name} (POBG)",
        "pob_notes": ("Generated by POBG from poe2db and PathOfBuilding-PoE2 data (passive tree {tree}) on {date}.\n"
                      "{gear}\n"
                      "Character level {level}; skill gems at the highest level it can use (at most {max}), quality "
                      "{quality}."),
        "pob_notes_no_gear": "No gear: the numbers PoB shows come from the passive tree and gems only; attack "
                             "skills need a weapon added in Items.",
        "pob_notes_gear": "Gear modifiers are at the upper end of their best tier: an ideal, real items roll lower. "
                          "Edit them in Items.",
        "pob_facts": [
            "Character level {level}. Each skill gem is set to the highest level (at most {max}) a level-{level} "
            "character can use, from its level table, quality {quality}; support gems have no level.",
            "The code has no gear, so PoB's damage and defence figures reflect the passive tree and gems only.",
            "Attack skills that need a weapon show as disabled until a weapon is added in PoB's Items tab.",
            "Passive tree version {tree}. Update Path of Building to its latest release first: an older one "
            "skips passives and gems it does not know, and may refuse a tree version or ascendancy it lacks.",
        ],
        "pob_over": "The route uses {used} passive points, more than the {limit} available.",
        "pob_over_asc": "The route uses {used} ascendancy points, more than the {limit} available.",
        "pob_attribute": "{count} attribute passives on the route are set to cover the gems' requirements "
                         "first: {parts}. Change any of them in PoB's tree.",
        "pob_attribute_asked": "{count} attribute passives on the route are set as asked: {parts}.",
        "pob_gear": ("Gear modifiers are written at the upper end of their best tier: an ideal, not what an item "
                     "will roll (modifiers are random); edit the values in PoB's Items tab. Quality, runes and "
                     "soul cores, sockets and jewels are not included, and a base or line PoB does not know is "
                     "skipped or marked unsupported there. Flasks and charms are switched on; charms 2 and 3 "
                     "need a belt with enough charm slots."),
        "pob_item_level": "{item} requires level {needed}, above the character level {level}.",
        "pob_short": "{attribute}: {have} of the {need} the gems and gear require; the missing {gap} must come "
                     "from gear or more passives. Only fixed attributes are counted, not % increases or reduced "
                     "requirements.",
        "pob_spirit": "Spirit: the persistent skills and their supports reserve {need}, the character has {have}; "
                      "{gap} short. Drop a persistent skill or a support that reserves Spirit, or get Spirit "
                      "from gear. Quest rewards, a sceptre's Spirit and fixed Spirit are counted, not % increases.",
        "pob_config_on": "PoB Configuration switched on, each from this build's own gems, passives or gear: {names}. "
                         "PoB's damage figures assume these states.",
        "pob_config_none": "No PoB Configuration option has evidence in this build: the damage is with no states.",
        "pob_config_off": "PoB Configuration left empty as asked: the damage is with no states.",
        "pob_config_charges": "Charges are counted at their maximum; set a lower count in PoB's Configuration tab.",
        "pob_config_ladder": "poe.ninja's ladder exports switch these on for every character, but this build has no "
                             "source for them, so they are off here: {names}. Compare ladder damage with that in mind.",
        "config_labels": {
            "usePowerCharges": "Power Charges", "useFrenzyCharges": "Frenzy Charges",
            "useEnduranceCharges": "Endurance Charges", "conditionCritRecently": "Crit Recently",
            "conditionEnemyShocked": "enemy Shocked", "conditionEnemyIgnited": "enemy Ignited",
            "conditionEnemyChilled": "enemy Chilled", "conditionEnemyFrozen": "enemy Frozen",
            "conditionEnemyBleeding": "enemy Bleeding", "conditionEnemyPoisoned": "enemy Poisoned",
            "conditionEnemyBlinded": "enemy Blinded", "conditionEnemyDazed": "enemy Dazed",
            "conditionEnemyLightningExposure": "Lightning Exposure", "conditionEnemyColdExposure": "Cold Exposure",
            "conditionEnemyFireExposure": "Fire Exposure"},
        "pob_spirit_unknown": "Spirit reserved by {names} is not counted: the data gives it as a range over gem "
                              "levels (minion skills) or not at all. Check Spirit in PoB.",
        "pob_spirit_quests": "Spirit counts every Spirit quest reward, as PoB does by default; in the game they come "
                             "at area levels {levels}.",
        "pob_level_low": "The route spends {points} passive points, which needs level {needed}; the code is set to "
                         "level {level} as asked.",
        "pob_no_attribute": "{count} attribute passives on the route give nothing until an attribute is "
                            "chosen for each in PoB's tree (no skill gem named one; pass `attribute`).",
        "pob_unchecked": "Support compatibility was not checked for {names}: the knowledge graph has no data "
                         "for it. Check the supports in PoB.",
        "attribute_names": {"str": "Strength", "dex": "Dexterity", "int": "Intelligence"},
        "pob_level_unknown": ("The code says level 1 because the local data has no PoB act table (update the "
                              "passive data). PoB then sets the level from the points but shows level-1 numbers "
                              "until it recalculates: change the level once."),
        "pob_how": ("In Path of Building (PoE2): Import/Export Build → paste the code into "
                    "\"To import a build, enter URL or code here\" → Import."),
    },
    "zh-tw": {
        "header": "## 資料來源",
        "fetched": "{label}，擷取於 {date}",
        "no_page": "沒有 poe2db 頁面的天賦點",
        "zh_text": "這些天賦點的繁體中文名稱與屬性文字",
        "path_note": ("這是近似路線：從職業起點連到每個目標，但不保證點數最少。points_alone 是單獨點該目標的成本，"
                      "added_points 是只有該目標才需要的點數。武器組天賦點與珠寶不在計算內。"),
        "removed": "本地資料查無（已移除）：{names}",
        "replaced": "{name}（改用 {other}）",
        "reference": "參考流派：[{label}]({url})，天梯快照 {date}",
        "matched": "，符合 {total} 個角色",
        "ninja": "poe.ninja PoE2 流派",
        "pob_title": "{name}（POBG）",
        "pob_notes": ("由 POBG 依 poe2db 與 PathOfBuilding-PoE2 資料產生（天賦樹 {tree}），{date}。\n"
                      "{gear}\n"
                      "角色等級 {level}；技能寶石為該等級可用的最高級（上限 {max}）、品質 {quality}。"),
        "pob_notes_no_gear": "不含裝備：PoB 顯示的數字只反映天賦與寶石；攻擊技能需在物品頁加入武器。",
        "pob_notes_gear": "裝備詞綴為最高階的上限，是理想值，實際裝備通常較低，可在物品頁修改。",
        "pob_facts": [
            "角色等級 {level}。每顆技能寶石依其等級表設為 {level} 級角色用得了的最高級（上限 {max}）、品質 {quality}；"
            "輔助寶石沒有等級。",
            "匯入碼不含裝備，PoB 顯示的傷害與防禦只反映天賦與寶石。",
            "需要武器的攻擊技能，在 PoB 的物品頁加入武器之前會顯示為停用。",
            "天賦樹版本 {tree}。請先把 Path of Building 更新到最新版：較舊的版本會略過它不認得的天賦與寶石，"
            "也可能拒絕它沒有的天賦樹版本或昇華。",
        ],
        "pob_over": "這條路線用了 {used} 點天賦，超過可用的 {limit} 點。",
        "pob_over_asc": "這條路線用了 {used} 點昇華天賦，超過可用的 {limit} 點。",
        "pob_attribute": "路線上的 {count} 個屬性天賦點優先補足寶石的屬性需求：{parts}。可在 PoB 的天賦樹上個別更改。",
        "pob_attribute_asked": "路線上的 {count} 個屬性天賦點依指定設為：{parts}。",
        "pob_gear": ("裝備詞綴以最高階的上限寫入：這是理想值，不是實際會出現的數值（詞綴是隨機的），可在 PoB 的物品頁修改。"
                     "不含品質、符文與靈魂核心、插槽與珠寶；PoB 不認得的基底或詞綴，會在 PoB 中被略過或標示為不支援。"
                     "藥劑與護符已設為啟用；護符 2、3 需要腰帶有足夠的護符欄位。"),
        "pob_item_level": "{item} 需要 {needed} 級，高於角色等級 {level}。",
        "pob_short": ("{attribute}：寶石與裝備需要 {need}，目前 {have}；還差 {gap}，要靠裝備或更多天賦補足。"
                      "只計入固定屬性，不含百分比增加與需求降低。"),
        "pob_spirit": "精魂：常駐技能與其輔助寶石共保留 {need}，角色只有 {have}，還差 {gap}。請拿掉一個常駐技能或會保留精魂的"
                      "輔助寶石，或從裝備取得精魂。計入任務獎勵、權杖的精魂與固定精魂，不含百分比增加。",
        "pob_config_on": "PoB 配置已開啟（每一項都依本流派自己的寶石、天賦或裝備）：{names}。PoB 的傷害以這些狀態計算。",
        "pob_config_none": "本流派沒有任何 PoB 配置項目的依據：傷害以無任何狀態計算。",
        "pob_config_off": "依指定不寫入 PoB 配置：傷害以無任何狀態計算。",
        "pob_config_charges": "球類以最大顆數計算，可在 PoB 配置頁改成較少的顆數。",
        "pob_config_ladder": "poe.ninja 的天梯匯出對每個角色都開啟這些項目，但本流派沒有來源，所以這裡沒開：{names}。"
                             "和天梯傷害比較時請考慮這點。",
        "config_labels": {
            "usePowerCharges": "暴擊球", "useFrenzyCharges": "狂怒球", "useEnduranceCharges": "耐力球",
            "conditionCritRecently": "近期暴擊", "conditionEnemyShocked": "敵人感電", "conditionEnemyIgnited": "敵人點燃",
            "conditionEnemyChilled": "敵人冰緩", "conditionEnemyFrozen": "敵人冰凍", "conditionEnemyBleeding": "敵人流血",
            "conditionEnemyPoisoned": "敵人中毒", "conditionEnemyBlinded": "敵人致盲", "conditionEnemyDazed": "敵人暈眩",
            "conditionEnemyLightningExposure": "閃電曝曬", "conditionEnemyColdExposure": "冰冷曝曬",
            "conditionEnemyFireExposure": "火焰曝曬"},
        "pob_spirit_unknown": "{names} 保留的精魂未計入：資料中是隨寶石等級變化的範圍（召喚物技能）或沒有記載。請在 PoB 確認精魂。",
        "pob_spirit_quests": "精魂已計入所有精魂任務獎勵（與 PoB 預設相同）；遊戲中它們分別在區域等級 {levels} 取得。",
        "pob_level_low": "這條路線用了 {points} 點天賦，需要 {needed} 級；匯入碼依指定設為 {level} 級。",
        "pob_no_attribute": "路線上的 {count} 個屬性天賦點在 PoB 中選定屬性前不提供任何屬性（技能寶石沒有指出屬性；"
                            "可傳入 `attribute`）。",
        "pob_unchecked": "{names} 的輔助寶石相容性未檢查：知識圖譜沒有它的資料，請在 PoB 中確認。",
        "attribute_names": {"str": "力量", "dex": "敏捷", "int": "智慧"},
        "pob_level_unknown": ("本機資料沒有 PoB 的章節表（請更新天賦資料），所以匯入碼寫的是 1 級。PoB 會依點數改成正確等級，"
                              "但在重新計算前顯示的是 1 級的數字：請手動改一次等級。"),
        "pob_how": "在 Path of Building（PoE2）：匯入/匯出 → 把匯入碼貼到「輸入網址或代碼」欄 → 匯入。",
    },
}

# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------


class BuildTools:
    """Verification, support listing and ladder summaries for build advice."""

    def __init__(self, lookup: LookupService, builds_path: Path | None = None) -> None:
        self.lookup = lookup
        self.builds_path = builds_path or lookup.base_dir / BUILDS_FILE
        self._builds: tuple[list[dict], int] | None = None
        self._builds_date: str | None = None   # date of the snapshot file, read with the rows
        self._builds_lock = threading.Lock()
        self._finder: PassivePathfinder | None = None
        self.items = ItemLookup(lookup)
        self._stats_by_node: dict[str, list[dict]] | None = None

    # -- verification ---------------------------------------------------------

    def verify_build(self, gems: list[str] | None = None, passives: list[str] | None = None,
                     lang: str | None = None, items: list[str] | None = None,
                     affixes: list[str] | None = None, detail: str = "full") -> dict:
        """Facts and sources for every name that matches local data exactly; the rest is
        reported in `unverified` with close names as suggestions. `affixes` are "item: modifier"
        strings, checked against what that item class can roll."""
        if detail not in DETAIL_LEVELS:
            raise BadArgument(f"detail must be one of {DETAIL_LEVELS}")
        gems, passives = _names(gems, "gems"), _names(passives, "passives")
        items, affixes = _names(items, "items"), _names(affixes, "affixes", MAX_AFFIXES)
        if not (gems or passives or items or affixes):
            raise BadArgument("give at least one gem, passive, item or affix")
        lang = _lang(lang) or ("zh-tw" if any(is_cjk(n) for n in gems + passives + items + affixes) else "en")
        verified_gems, verified_passives, unverified, seen = [], [], [], set()
        for name in gems:
            fact = self.gem_fact(name)
            key = ("gem", fact["slug"]) if fact else ("unknown gem", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self.unverified_entry(name, "gem"))
            else:
                verified_gems.append(fact)
        for name in passives:
            fact = self.passive_fact(name)
            key = ("passive", fact["id"]) if fact else ("unknown passive", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self.unverified_entry(name, "passive"))
            else:
                verified_passives.append(fact)
        verified_items, verified_affixes = self._verify_gear(items, affixes, unverified, seen)
        sources = number_sources(verified_gems + verified_passives + verified_items + verified_affixes)
        verified_affixes = [_compact_affix(fact, lang) for fact in verified_affixes]
        verified = {"gems": verified_gems, "passives": verified_passives}
        if items or affixes:
            verified.update(items=verified_items, affixes=verified_affixes)
        verified = {kind: [_returned_fact(fact, detail) for fact in facts] for kind, facts in verified.items()}
        return {
            "lang": lang,
            "verified": verified,
            "unverified": unverified,
            "sources": sources,
            "sources_markdown": render_sources(sources, unverified, lang),
        }

    def _verify_gear(self, items: list[str], affixes: list[str], unverified: list[dict], seen: set) -> tuple[list, list]:
        verified_items, verified_affixes = [], []
        for name in items:
            try:
                fact = self.item_fact(name)
            except AmbiguousItem as exc:
                unverified.append({"input": name, "expected": "item", "reason": str(exc),
                                   "suggestions": [{"slug": option} for option in exc.options]})
                continue
            key = ("item", fact["slug"]) if fact else ("unknown item", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self._unknown_item(name))
            else:
                verified_items.append(fact)
        for entry in affixes:
            fact = self.affix_fact(entry)
            if fact.get("expected") == "affix":
                unverified.append(fact)
            else:
                problem = _affix_conflict(fact, verified_affixes)
                if problem:
                    unverified.append({"input": entry, "expected": "affix", "reason": problem, "suggestions": []})
                elif not any(_same_modifier(fact, kept) for kept in verified_affixes):
                    verified_affixes.append(fact)
        return verified_items, verified_affixes

    def _unknown_item(self, name: str) -> dict:
        """An item name with no match; an item class given as an item gets the reason spelled out."""
        entry = self.unverified_entry(name, "item")
        try:
            self.items.resolve_page(name)
        except (NotFound, BadArgument):
            return entry
        return {**entry, "reason": "this is an item class, not an item: `items` takes base or unique names; "
                                   "a class goes before the colon in `affixes`"}

    def item_fact(self, name: str) -> dict | None:
        """Trimmed record of one base or unique item, or None when the name has no local match."""
        try:
            kind, record = self.items._resolve(name)
        except NotFound:
            return None
        return {"input": name, "slug": record["slug"], "kind": ITEM_KIND_NAMES[kind], "name": record["name"],
                "name_zh_tw": record.get("name_zh_tw"), "item_class": record.get("item_class"),
                "base": record.get("base"), "requires_level": record.get("requires_level"),
                "lines": item_fact_lines(kind, record),
                "sources": _sources(record.get("url_en"), record.get("url_zh_tw"), record.get("fetched_at"))}

    def affix_fact(self, entry: str) -> dict:
        """A verified target modifier for an item class, or an `unverified` entry (expected: affix)."""
        parts = AFFIX_SEPARATOR.split(entry, maxsplit=1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise BadArgument(f"an affix must be written as 'item: modifier', e.g. 'Rings: +#% to Fire Resistance'; got {entry!r}")
        item, text = parts
        try:
            check = self.items.check_affix(item, text)
        except AmbiguousItem as exc:
            return {"input": entry, "expected": "affix", "reason": str(exc),
                    "suggestions": [{"item": option} for option in exc.options]}
        except NotFound as exc:
            return {"input": entry, "expected": "affix", "reason": str(exc), "suggestions": []}
        if not check["matched"]:
            return {"input": entry, "expected": "affix", "reason": check["reason"], "suggestions": check["suggestions"]}
        family, page = check["family"], check["item_class"]
        best, lowest = family["tiers"][0], family["tiers"][-1]
        return {"input": entry, "item": clean_text(item), "item_class": page["slug"], "family": family["family"],
                "group": family["group"], "affix": family["affix"], "modifier": family["template"],
                "tiers": len(family["tiers"]),
                "best": {k: best[k] for k in ("text", "text_zh_tw", "level")},
                "lowest": {k: lowest[k] for k in ("text", "text_zh_tw", "level")},
                "name": f"{page['label']} modifiers",
                "name_zh_tw": f"{page['label_zh_tw']}詞綴" if page.get("label_zh_tw") else None,
                "sources": check["sources"]}

    def gem_fact(self, name_or_slug: str) -> dict | None:
        """Trimmed record of one gem, or None when the name has no exact local match."""
        try:
            entity = self.lookup._resolve(name_or_slug, GEM_KINDS)
            record = self.lookup._gem_record(entity["kind"], entity["slug"])
        except NotFound:
            return None
        fact = {"input": name_or_slug, **{k: record.get(k) for k in GEM_FACT_FIELDS}}
        fact["stats"] = _strings(record.get("extra_properties"))[:MAX_STAT_LINES]
        fact["name_zh_tw"] = entity.get("name_zh_tw")
        fact["sources"] = _sources(record.get("source_url"), record.get("url_zh_tw"), record.get("fetched_at"))
        return fact

    def passive_fact(self, name_or_id: str) -> dict | None:
        """Trimmed record of one passive node (by name, slug or tree id), or None. Class and
        ascendancy start nodes are not passives a build allocates, so they do not verify."""
        try:
            node = self.lookup.get_passive(name_or_id)["passive"]
        except NotFound:
            return None
        if _is_start(node):
            return None
        return {
            "input": name_or_id, "id": node["id"], "slug": node.get("slug"), "name": node.get("name"),
            "name_zh_tw": node.get("name_zh_tw"), "type": node.get("type"), "ascendancy": node.get("ascendancy"),
            "stats": node.get("stats") or [], "stats_zh_tw": node.get("stats_zh_tw") or [],
            "sources": self.lookup._passive_sources(node),
        }

    def unverified_entry(self, name: str, expected: str) -> dict:
        kinds = {"gem": GEM_KINDS, "passive": PASSIVE_KINDS, "item": ITEM_KINDS}[expected]
        hits = self.lookup.index.find(clean_text(name), limit=20)
        other = next((h for h in hits if h["match_type"] == "exact" and h["kind"] not in kinds), None)
        reason = (f"this name is a {other['kind']}, not a {expected}" if other
                  else "no exact match in local data")
        if expected == "passive" and self._is_start_node(name):
            reason = START_REASON
        keep = ("slug", "kind", "name_en", "name_zh_tw", "match_type")
        suggestions = [{k: h.get(k) for k in keep} for h in hits if h["kind"] in kinds][:MAX_SUGGESTIONS]
        return {"input": name, "expected": expected, "reason": reason, "suggestions": suggestions}

    def _is_start_node(self, name: str) -> bool:
        try:
            return _is_start(self.lookup.get_passive(name)["passive"])
        except LookupFailed:
            return False

    # -- supports -------------------------------------------------------------

    def supports_for(self, skill: str, tag: str | None = None, limit: int = 50) -> dict:
        """Every support gem with a SUPPORTS edge to the skill, lowest tier first."""
        _cap(tag, "tag")
        entity = self.lookup._resolve(skill, GEM_KINDS)
        if entity["kind"] == "support_gem":
            raise BadArgument(f"{entity['name_en']} is a support gem; use get_gem to see the skills it supports")
        limit = _limit(limit)
        graph = self.lookup.graph
        if graph is None:
            raise ServiceUnavailable("supports need the knowledge graph; run python -m src.kg.build_graph")
        node_id = f"gem:{entity['slug']}"
        edges = graph.in_edges(node_id, data=True) if node_id in graph else []
        slugs = [graph.nodes[u].get("slug") for u, _, d in edges if d.get("type") == "SUPPORTS"]
        records = [self.lookup.gems["support_gem"][s] for s in dict.fromkeys(slugs)
                   if s in self.lookup.gems["support_gem"]]
        records = [r for r in records if _gem_matches(r, tag, None, None)]
        records.sort(key=lambda r: (r.get("tier") is None, r.get("tier") or 0, r.get("name") or ""))
        record = self.lookup._gem_record(entity["kind"], entity["slug"])
        return {
            "skill": {k: entity.get(k) for k in ("slug", "kind", "name_en", "name_zh_tw")},
            "tag": tag,
            "total": len(records),
            "supports": [self._support_row(r) for r in records[:limit]],
            "sources": _sources(record.get("source_url"), record.get("url_zh_tw"), record.get("fetched_at")),
        }

    def _support_row(self, record: dict) -> dict:
        entity = self.lookup.index.get(record["slug"], kind="support_gem")
        return {"slug": record["slug"], "name": record.get("name"),
                "name_zh_tw": entity.name_zh_tw if entity else None, "tier": record.get("tier"),
                "tags": record.get("tags"), "url_en": record.get("source_url"), "url_zh_tw": record.get("url_zh_tw")}

    # -- ladder reference -------------------------------------------------------

    def reference_builds(self, class_name: str | None = None, main_skill: str | None = None,
                         limit: int = 5, lang: str | None = None) -> dict:
        """What ladder characters run, from the local poe.ninja snapshot. No character names."""
        limit = _limit(limit)
        _cap(class_name, "class_name")
        _cap(main_skill, "main_skill")
        class_name = clean_text(class_name) or None if class_name else None   # blank = no filter
        main_skill = clean_text(main_skill) or None if main_skill else None
        lang = _lang(lang) or ("zh-tw" if is_cjk(f"{class_name or ''}{main_skill or ''}") else "en")
        rows, skipped = self._load_builds()
        wanted_class = self.lookup.canonical_class(class_name).lower() if class_name else None
        wanted_skill = self._canonical_skill(main_skill).lower() if main_skill else None
        hits = [r for r in rows
                if (wanted_class is None or str(r.get("class") or "").lower() == wanted_class)
                and (wanted_skill is None or str(r.get("main_skill") or "").lower() == wanted_skill)]
        hits.sort(key=lambda r: (not isinstance(r.get("rank"), int), r.get("rank") if isinstance(r.get("rank"), int) else 0))
        source = self.ladder_source(lang)
        result = {
            "filters": {"class_name": class_name, "main_skill": main_skill},
            "total_matching": len(hits),
            "league": source["league"],
            "builds": [{k: r.get(k) for k in BUILD_FIELDS} for r in hits[:limit]],
            "common": {
                "main_skills": _most_common(r.get("main_skill") for r in hits),
                "other_gems": _most_common(g for r in hits for g in _others(r)),
                "keystones": _most_common(k for r in hits for k in _strings(r.get("keystones"))),
            },
            "source": {k: source[k] for k in ("label", "url", "fetched_at")},
            "source_markdown": render_ladder_source(source, lang, total=len(hits)),
            "skipped_lines": skipped,
        }
        if not hits:
            result["available_classes"] = _most_common((r.get("class") for r in rows), 50)
        return result

    # -- passive pathing ------------------------------------------------------------

    def path_to(self, class_name: str, targets: list[str], ascendancy: str | None = None,
                lang: str | None = None) -> dict:
        """Which passives to allocate, in order, to reach `targets` from a class start, with the
        point cost and what the whole route gives. The route is a good approximation, not a
        guaranteed minimum."""
        names = _names(targets, "targets")
        if not names:
            raise BadArgument("give at least one target passive")
        _require(class_name, "class_name")
        _cap(class_name, "class_name")
        _cap(ascendancy, "ascendancy")
        lang = _lang(lang) or ("zh-tw" if is_cjk("".join([class_name, ascendancy or "", *names])) else "en")
        cls, chosen = self._class_and_ascendancy(class_name, ascendancy)
        facts, unverified = self._path_targets(names)
        nodes = self.lookup.passives
        chosen, inferred = self._settle_ascendancy(cls, chosen, facts, unverified)
        own = [f for f in facts if nodes[f["id"]].get("ascendancy")]
        main = [f for f in facts if not nodes[f["id"]].get("ascendancy")]

        finder = self._pathfinder()
        # other classes' start nodes cannot be passed through (in the game or in PoB)
        main_allowed = {i for i, n in nodes.items() if not n.get("ascendancy") and not n.get("timeless")
                        and n.get("type") != START_NODE_TYPE and n.get("unlock_ascendancy") in (None, chosen)}
        main_route = finder.route(self._class_start(cls), [f["id"] for f in main], main_allowed)
        asc_route = None
        if own:
            asc_allowed = {i for i, n in nodes.items() if n.get("ascendancy") == chosen}
            asc_route = finder.route(self._ascendancy_start(chosen), [f["id"] for f in own], asc_allowed)

        routes = [r for r in (main_route, asc_route) if r is not None]
        gone = {t for r in routes for t in r.unreachable}
        reached = [f for f in facts if f["id"] not in gone]
        allocated = [i for r in routes for i in r.order]
        limits = (self.lookup.classes_doc or {}).get("points") or {}
        totals, text_stats = self._stat_totals(allocated, lang)
        sources = number_sources([*reached, {"sources": [self.lookup._passive_sources({"pob2_tree_version":
                                  self.lookup.spec.source("pob2_tree")["version"]})[0]]}] if allocated else reached)
        return {
            "class": cls, "ascendancy": chosen, "ascendancy_inferred": inferred, "lang": lang,
            "points": {"passive": _budget(self._points(main_route), limits.get("passive")),
                       "ascendancy": _budget(self._points(asc_route), limits.get("ascendancy"))},
            "targets": [self._target_row(f, routes) for f in reached],
            "path": self._path_rows(main_route, {f["id"] for f in main}, lang),
            "ascendancy_path": self._path_rows(asc_route, {f["id"] for f in own}, lang) if asc_route else [],
            "stat_totals": totals, "text_stats": text_stats,
            "unverified": unverified,
            "unreachable": [self._unreachable_row(f, chosen) for f in facts if f["id"] in gone],
            "approximate": True, "note": TEXT[lang]["path_note"],
            "sources": sources, "sources_markdown": render_sources(sources, unverified, lang),
        }

    def _points(self, route) -> int:
        """Points a route spends: nodes that are allocated for free do not count."""
        return sum(1 for i in route.order if not self.lookup.passives[i].get("no_point")) if route else 0

    def _class_and_ascendancy(self, class_name: str, ascendancy: str | None) -> tuple[str, str | None]:
        if self.lookup.classes_doc is None:
            raise ServiceUnavailable("class data missing; run python -m src.scrapers.collect_passives")
        info = self.lookup.class_info(class_name)
        if info is None or info["class"] not in self._class_starts():
            raise BadArgument(f"unknown class {clean_text(class_name)[:MAX_ECHO_LEN]!r}; "
                              f"classes: {', '.join(sorted(self._class_starts()))}")
        chosen = info["ascendancy"]
        if ascendancy and clean_text(ascendancy):
            asked = self.lookup.class_info(ascendancy)
            if asked is None or asked["ascendancy"] is None or asked["class"] != info["class"]:
                raise BadArgument(f"{clean_text(ascendancy)[:MAX_ECHO_LEN]!r} is not an ascendancy of {info['class']}")
            if chosen and chosen != asked["ascendancy"]:
                raise BadArgument(f"class_name names {chosen} but ascendancy names {asked['ascendancy']}")
            chosen = asked["ascendancy"]
        if chosen and chosen not in self._ascendancy_starts():
            raise BadArgument(f"{chosen} has no ascendancy tree in the local data")
        return info["class"], chosen

    def _path_targets(self, names: list[str]) -> tuple[list[dict], list[dict]]:
        facts, unverified, seen = [], [], set()
        for name in names:
            fact = self.passive_fact(name)
            if fact is None:
                key = ("unknown passive", _name_key(name))
                if key not in seen:
                    seen.add(key)
                    unverified.append(self.unverified_entry(name, "passive"))
            elif fact["id"] not in seen:
                seen.add(fact["id"])
                facts.append(fact)
        return facts, unverified

    def _settle_ascendancy(self, cls: str, chosen: str | None, facts: list[dict],
                           unverified: list[dict]) -> tuple[str | None, bool]:
        """Pick the ascendancy when the targets imply exactly one; move targets of any other
        ascendancy from `facts` to `unverified`."""
        nodes = self.lookup.passives
        named = {nodes[f["id"]]["ascendancy"] for f in facts if nodes[f["id"]].get("ascendancy")}
        inferred = False
        if chosen is None and len(named) == 1:
            only = next(iter(named))
            info = self.lookup.class_info(only)
            if info and info["class"] == cls:
                chosen, inferred = only, True
        for fact in list(facts):
            theirs = nodes[fact["id"]].get("ascendancy")
            if theirs and theirs != chosen:
                facts.remove(fact)
                reason = (f"{fact['name']} belongs to the {theirs} ascendancy; pass ascendancy={theirs!r}"
                          if chosen is None else f"{fact['name']} belongs to the {theirs} ascendancy, not {chosen}")
                unverified.append({"input": fact["input"], "expected": "passive", "reason": reason, "suggestions": []})
        return chosen, inferred

    def _pathfinder(self) -> PassivePathfinder:
        if self._finder is None:
            self._finder = PassivePathfinder(self.lookup.passives)
        return self._finder

    def _class_starts(self) -> dict[str, str]:
        return {c: n["id"] for n in self.lookup.passives.values() if n.get("type") == START_NODE_TYPE
                for c in n.get("class_start") or []}

    def _class_start(self, cls: str) -> str:
        return self._class_starts()[cls]

    def _ascendancy_starts(self) -> dict[str, str]:
        return {n["ascendancy"]: n["id"] for n in self.lookup.passives.values()
                if n.get("is_ascendancy_start") and n.get("ascendancy")}

    def _ascendancy_start(self, ascendancy: str) -> str:
        return self._ascendancy_starts()[ascendancy]

    def _target_row(self, fact: dict, routes: list) -> dict:
        route = next(r for r in routes if fact["id"] in r.alone)
        return {"input": fact["input"], "id": fact["id"], "name": fact["name"], "name_zh_tw": fact["name_zh_tw"],
                "type": fact["type"], "cite": fact.get("cite"),
                "points_alone": route.alone[fact["id"]], "added_points": route.exclusive[fact["id"]]}

    def _unreachable_row(self, fact: dict, chosen: str | None) -> dict:
        lock = self.lookup.passives[fact["id"]].get("unlock_ascendancy")
        reason = (f"needs the {lock} ascendancy" if lock and lock != chosen
                  else "not connected to the rest of the tree in the local data")
        return {"input": fact["input"], "id": fact["id"], "name": fact["name"], "name_zh_tw": fact["name_zh_tw"],
                "reason": reason}

    def _path_rows(self, route, targets: set[str], lang: str) -> list[dict]:
        rows = []
        for order, node_id in enumerate(route.order, 1):
            node = self.lookup.passives[node_id]
            zh = node.get("stats_zh_tw") or []
            rows.append({"order": order, "id": node_id, "name": node.get("name"), "name_zh_tw": node.get("name_zh_tw"),
                         "type": node.get("type"),
                         "stats": zh if lang == "zh-tw" and zh else node.get("stats") or [],
                         "target": node_id in targets})
        return rows

    def _stat_totals(self, node_ids: list[str], lang: str) -> tuple[list[dict], list[str]]:
        """What the allocated nodes give together: numeric stats summed per (family, kind);
        lines that are rules rather than numbers are listed once each."""
        groups: dict[tuple[str, str], dict] = {}
        texts: list[str] = []
        for node_id in node_ids:
            for row in self._node_stats().get(node_id, []):
                if row["kind"] == "text" or row.get("value") is None:
                    line = (row.get("text_zh_tw") if lang == "zh-tw" else None) or row["text"]
                    if line not in texts:
                        texts.append(line)
                    continue
                group = groups.setdefault((row["family"], row["kind"]), {
                    "family": row["family"], "kind": row["kind"], "total": 0.0, "lines": 0,
                    "template": row["template"], "template_zh_tw": row.get("template_zh_tw")})
                group["total"] += row["value"]
                group["lines"] += 1
        totals = sorted(groups.values(), key=lambda g: (-g["lines"], g["family"], g["kind"]))
        for group in totals:
            group["total"] = round(group["total"], 2)
        return totals, texts[:MAX_TEXT_STATS]

    # -- Path of Building export ------------------------------------------------------

    def export_pob(self, class_name: str, targets: list[str] | None = None, skills: list[str] | None = None,
                   ascendancy: str | None = None, main_skill: str | None = None, title: str | None = None,
                   attribute: str | None = None, character_level: int | None = None,
                   gear: list[str] | None = None, config: bool = True, lang: str | None = None) -> dict:
        """A Path of Building build code for a class, the route to `targets` and skill groups
        ("skill: support, support"). Only names that match local data go in; everything left out
        is listed in `not_exported` with the reason. Character level, gem levels and the
        attribute passives are worked out from the data. Writes nothing and needs no network."""
        names = _names(targets, "targets")
        groups_in = _names(skills, "skills", MAX_SKILL_GROUPS, MAX_GROUP_LEN)
        gear_in = _names(gear, "gear", MAX_GEAR, MAX_GEAR_LEN)
        if not (names or groups_in or gear_in):
            raise BadArgument("give at least one target passive, skill or gear entry")
        _require(class_name, "class_name")
        _cap(class_name, "class_name")
        _cap(ascendancy, "ascendancy")
        _cap(main_skill, "main_skill", MAX_NAME_LEN)
        _cap(title, "title", MAX_TITLE_LEN)
        wanted_attribute, asked_level = _attribute(attribute), _character_level(character_level)
        if not isinstance(config, bool):
            raise BadArgument("config must be true or false")
        lang = _lang(lang) or ("zh-tw" if is_cjk("".join([class_name, ascendancy or "", *names, *groups_in, *gear_in]))
                               else "en")
        parsed = [_parse_group(entry) for entry in groups_in]   # format errors before any work
        parsed_gear = [_parse_gear(entry) for entry in gear_in]
        not_exported: list[dict] = []
        route = self._export_route(class_name, names, ascendancy, lang, not_exported)
        acts = (self.lookup.classes_doc or {}).get("pob_level_acts") or []
        needed_level = pob_level(route["points"]["passive"]["used"], acts) if acts else None
        level = asked_level or needed_level or 1
        groups, unchecked = self._export_groups(groups_in, parsed, not_exported, level)
        main_group = self._main_group(main_skill, groups, not_exported)
        main_colour = groups[main_group - 1]["colour"] if groups else None
        items = self._export_gear(gear_in, parsed_gear, not_exported)
        plan = self._attribute_plan(route, groups, wanted_attribute, main_colour, items)
        spirit = self._spirit_plan(level, route["nodes"], groups, items)
        options = self._config_plan(route["nodes"], groups, items) if config else {}
        text = TEXT[lang]
        tree = self.lookup.spec.source("pob2_tree")["version"]
        facts = {"tree": tree, "level": level, "max": GEM_LEVEL, "quality": GEM_QUALITY}
        build = PobBuild(
            title=clean_text(title) if title and clean_text(title) else text["pob_title"].format(name=route["ascendancy"]
                                                                                                or route["class"]),
            class_name=route["class"], class_id=route["class_id"], ascendancy_name=route["ascendancy"],
            ascendancy_id=route["ascendancy_id"], tree_version=tree, nodes=route["nodes"],
            groups=[g["group"] for g in groups], main_group=main_group, attributes=plan["nodes"],
            level=level, auto_level=asked_level is None, items=[i["item"] for i in items], config=list(options),
            notes=text["pob_notes"].format(date=datetime.now(timezone.utc).date().isoformat(),
                                           gear=text["pob_notes_gear" if items else "pob_notes_no_gear"], **facts)
                  + "\n" + _config_note(text, options))
        notes = self._export_notes(text, facts, route["points"], plan, unchecked,
                                   skip=(*([NO_GEAR_FACT] if items else []),
                                         *([NO_WEAPON_FACT] if any(i["item"].slot == "Weapon 1" for i in items) else [])),
                                   after_facts=_config_notes(text, options, config))
        if spirit["have"] is not None and spirit["need"] > spirit["have"]:
            notes.append(text["pob_spirit"].format(gap=spirit["need"] - spirit["have"], have=spirit["have"],
                                                   need=spirit["need"]))
        if spirit.get("unknown"):
            notes.append(text["pob_spirit_unknown"].format(names=", ".join(spirit["unknown"])))
        quests = (self.lookup.classes_doc or {}).get("pob_spirit_quests") or []
        if any(q["level"] > level for q in quests) and any(g["spirit"] for g in groups):
            notes.append(text["pob_spirit_quests"].format(levels=", ".join(str(q["level"]) for q in quests)))
        if items:
            notes.append(text["pob_gear"])
        for i in items:
            if i["requires_level"] and i["requires_level"] > level:
                notes.append(text["pob_item_level"].format(item=i["label"], needed=i["requires_level"], level=level))
        if asked_level and needed_level and needed_level > asked_level:
            notes.append(text["pob_level_low"].format(points=route["points"]["passive"]["used"], needed=needed_level,
                                                      level=asked_level))
        if not acts and not asked_level:
            notes.append(text["pob_level_unknown"])
        return {
            "lang": lang,
            "code": encode_code(build_xml(build)),
            "summary": {"class": route["class"], "ascendancy": route["ascendancy"], "points": route["points"],
                        "tree_version": tree, "skill_groups": len(groups),
                        "gems": sum(len(g["group"].gems) for g in groups),
                        "main_skill": groups[main_group - 1]["label"] if groups else None,
                        "character_level": level, "attributes": plan["attributes"],
                        "attribute_passives": plan["assigned"], "spirit": spirit,
                        "config": [{"option": name, "label": text["config_labels"][name], "evidence": why}
                                   for name, why in options.items()],
                        "gear": [{"slot": i["item"].slot, "item": i["label"], "rarity": i["item"].rarity,
                                  "modifiers": i["modifiers"]} for i in items]},
            "groups": [{"skill": g["label"], "level": g["group"].gems[0].level,
                        "gems": [gem.name for gem in g["group"].gems],
                        **({"spirit": g["spirit"]} if g["spirit"] else {})} for g in groups],
            "not_exported": not_exported,
            "notes": notes,
            "how_to_import": text["pob_how"],
        }

    def _attribute_plan(self, route: dict, groups: list[dict], wanted: str | None, main_colour: str | None,
                        items: list[dict] | None = None) -> dict:
        """Which attribute each attribute passive on the route gets, and have / need per attribute.
        `need` follows Path of Building (CalcSetup.lua, CalcPerform.lua): every skill gem is one
        requirement, all support gems together are another (their additions summed over every
        group), and the highest one counts. `have` is the class base plus the fixed attributes of
        the route's other passives plus the attribute passives assigned here. Each attribute
        passive goes to the attribute furthest below its need (ties: the main skill's); when every
        need is met the rest go to the main skill's attribute, or to the attribute the gems need
        most when that skill names none. `wanted` overrides. Gear counts both ways: an item's own
        requirement is one more source of need, its fixed attributes add to have."""
        passives = self.lookup.passives
        free = [i for i in route["nodes"] if passives.get(i, {}).get("type") == ATTRIBUTE_TYPE]
        items = items or []
        need = {a: max(max((g["needs"].get(a, 0) for g in groups), default=0),
                       sum(g["support_adds"].get(a, 0) for g in groups),
                       max((i["requires"].get(a, 0) for i in items), default=0)) for a in ATTRIBUTES}
        entry = next((c for c in (self.lookup.classes_doc or {}).get("classes", []) if c["name"] == route["class"]), {})
        base = entry.get("base_attributes")
        have = self._tree_attributes([i for i in route["nodes"] if i not in free])
        for item in items:
            for a in ATTRIBUTES:
                have[a] += item["adds"].get(a, 0)
        if base:
            have = {a: have[a] + base[a] for a in ATTRIBUTES}
        order = sorted(ATTRIBUTES, key=lambda a: a != main_colour)        # the main skill's attribute first
        most_needed = max(order, key=lambda a: need[a])
        rest = main_colour or (most_needed if need[most_needed] > 0 else None)
        assigned: dict[str, list[str]] = {a: [] for a in ATTRIBUTES}
        for node_id in free:
            short = max(order, key=lambda a: need[a] - have[a])
            target = wanted or (short if base and need[short] > have[short] else rest)
            if target is None:
                break
            assigned[target].append(node_id)
            have[target] += ATTRIBUTE_PASSIVE_VALUE
        return {"nodes": {a: ids for a, ids in assigned.items() if ids}, "free": len(free), "asked": wanted,
                "assigned": {a: len(ids) for a, ids in assigned.items() if ids},
                "attributes": {a: {"have": have[a] if base else None, "need": need[a]} for a in ATTRIBUTES}}

    def _spirit_plan(self, level: int, node_ids: list[str], groups: list[dict], items: list[dict]) -> dict:
        """Spirit the persistent skills reserve against what the character has. `need`: each spirit
        gem's reservation plus its supports' additional reservation. `have`: the Spirit quest
        rewards (all of them, as PoB counts them by default), a weapon's base Spirit and fixed
        "+# to Spirit" on the exported gear and the route's passives (None when the local data has
        no quest rewards). Skills whose reservation the data does not give per level are listed in
        `unknown` and not counted."""
        need = sum(g["spirit"] for g in groups)
        unknown = [g["label"] for g in groups if not g["spirit_known"]]
        quests = (self.lookup.classes_doc or {}).get("pob_spirit_quests")
        if not quests:
            return {"have": None, "need": need, **({"unknown": unknown} if unknown else {})}
        have = sum(q["spirit"] for q in quests)        # PoB counts every Spirit quest reward by default
        have += sum(i["spirit"] for i in items)
        have += sum(int(m.group(1)) for i in items for line in (*i["item"].implicits, *i["item"].explicits)
                    if (m := SPIRIT_LINE.match(line.strip())))
        have += sum(int(row["value"]) for node_id in node_ids for row in self._node_stats().get(node_id, [])
                    if row["family"] == SPIRIT_FAMILY and row["kind"] == "flat" and row.get("value") is not None)
        return {"have": have, "need": need, **({"unknown": unknown} if unknown else {})}

    def _config_plan(self, node_ids: list[str], groups: list[dict], items: list[dict]) -> dict[str, list[dict]]:
        """PoB configuration options this build has evidence for, each with up to three pieces of
        evidence. Evidence is text of the exported gems, the route's passives and the exported gear
        (a charge the build gains, a state it inflicts, a stat that needs a recent Critical Hit),
        and the glossary rule that hits of an element inflict that element's ailment."""
        found: dict[str, list[dict]] = {}

        def add(option: str, source: str, name: str, line: str) -> None:
            entries = found.setdefault(option, [])
            if len(entries) < MAX_EVIDENCE and not any(e["name"] == name for e in entries):
                entries.append({"source": source, "name": name, "text": line[:MAX_EVIDENCE_LEN]})

        for group in groups:
            blocked = set()                       # "Supported Skills cannot inflict Shock": not for this group
            for _, _, record in group["records"]:
                for line in _gem_lines(record):
                    blocked |= _blocked_options(line)
            for name, kind, record in group["records"]:
                tags = {str(t).casefold() for t in record.get("tags") or []}
                for line in _gem_lines(record):
                    for option in _line_options(line, tags):
                        if option not in blocked:
                            add(option, "gem", name, line)
                if kind != "support_gem" and tags & DAMAGE_TAGS and not tags & NON_HIT_TAGS:   # buffs never hit
                    for element, (option, keyword) in ELEMENT_OPTIONS.items():
                        if element in tags and option not in blocked:
                            add(option, "glossary", keyword, f"{element.title()} damage from Hits ({name})")
        attacks = any("attack" in {str(t).casefold() for t in (g["records"][0][2].get("tags") or [])} for g in groups)
        for node_id in node_ids:
            node = self.lookup.passives.get(node_id, {})
            for line in node.get("stats") or []:
                for option in _line_options(line, set()):
                    add(option, "passive", node.get("name") or node_id, line)
        for item in items:
            for line in (*item["item"].implicits, *item["item"].explicits):
                for option in _line_options(line, set()):
                    add(option, "gear", item["label"], line)
                element = GEAR_ELEMENT.search(line)
                if element and attacks and item["item"].slot == "Weapon 1":   # only attacks use the weapon
                    option, keyword = ELEMENT_OPTIONS[element.group(1).casefold()]
                    add(option, "glossary", keyword, f"{element.group(1)} damage from Hits ({item['label']})")
        return {option: found[option] for option in CONFIG_ORDER if option in found}

    def _tree_attributes(self, node_ids: list[str]) -> dict[str, int]:
        """Fixed attributes ("+10 to Strength", "+5 to all Attributes") the given passives give."""
        totals = dict.fromkeys(ATTRIBUTES, 0)
        for node_id in node_ids:
            for row in self._node_stats().get(node_id, []):
                if row["kind"] == "flat" and row.get("value") is not None:
                    for key in ATTRIBUTE_FAMILIES.get(row["family"], ()):
                        totals[key] += int(row["value"])
        return totals

    def _node_stats(self) -> dict[str, list[dict]]:
        if self._stats_by_node is None:
            by_node: dict[str, list[dict]] = {}
            for row in self.lookup.stat_rows:
                by_node.setdefault(str(row["node_id"]), []).append(row)
            self._stats_by_node = by_node
        return self._stats_by_node

    def _export_route(self, class_name: str, names: list[str], ascendancy: str | None, lang: str,
                      not_exported: list[dict]) -> dict:
        """Class, ascendancy, PoB ids, points and allocated node ids (starts included). An
        ascendancy PoB has no id for is left out with its passives, and the route is made again
        without it."""
        route = self.path_to(class_name, names, ascendancy=ascendancy, lang=lang) if names else None
        cls, chosen = ((route["class"], route["ascendancy"]) if route
                       else self._class_and_ascendancy(class_name, ascendancy))
        class_id, ascendancy_id = self._pob_ids(cls, chosen)
        if route:
            not_exported += [{**u, "expected": "passive"} for u in route["unverified"]]
            not_exported += [_unreachable_entry(u) for u in route["unreachable"]]
        if chosen and ascendancy_id is None:
            not_exported.append({"input": chosen, "expected": "ascendancy", "suggestions": [],
                                 "reason": "Path of Building has no id for this ascendancy in the local data; "
                                           "exported without the ascendancy"})
            route = self._route_without(cls, chosen, route, lang, not_exported)
            chosen = None
        limits = (self.lookup.classes_doc or {}).get("points") or {}
        points = route["points"] if route else {"passive": _budget(0, limits.get("passive")),
                                                "ascendancy": _budget(0, limits.get("ascendancy"))}
        nodes = [self._class_start(cls), *(row["id"] for row in (route or {}).get("path", []))]
        if chosen:
            nodes += [self._ascendancy_start(chosen), *(row["id"] for row in route["ascendancy_path"])] if route \
                else [self._ascendancy_start(chosen)]
        return {"class": cls, "ascendancy": chosen, "class_id": class_id, "ascendancy_id": ascendancy_id if chosen else None,
                "points": points, "nodes": list(dict.fromkeys(nodes))}

    def _route_without(self, cls: str, chosen: str, route: dict | None, lang: str, not_exported: list[dict]) -> dict | None:
        """The route again without the left-out ascendancy: its passives are reported, and main-tree
        passives it unlocks become unreachable."""
        if route is None:
            return None
        nodes = self.lookup.passives
        kept = []
        for target in route["targets"]:
            if nodes[target["id"]].get("ascendancy") == chosen:
                not_exported.append({"input": target["input"], "expected": "passive", "suggestions": [],
                                     "reason": f"belongs to the {chosen} ascendancy, which was left out"})
            else:
                kept.append(target["input"])
        if not kept:
            return None
        again = self.path_to(cls, kept, ascendancy=None, lang=lang)
        not_exported += [_unreachable_entry(u) for u in again["unreachable"]]
        return again

    def _export_groups(self, groups_in: list[str], parsed: list[tuple[str, list[str]]],
                       not_exported: list[dict], level: int) -> tuple[list[dict], list[str]]:
        """One dict per exported group (group, label, slug, colour, needs) and the skills whose
        supports could not be checked."""
        groups, unchecked, skills_seen = [], [], set()
        for entry, (skill, supports) in zip(groups_in, parsed):
            exported = self._pob_group(entry, skill, supports, not_exported, level)
            if exported is None:
                continue
            if exported["slug"] in skills_seen:
                not_exported.append({"input": entry, "expected": "skill gem", "suggestions": [],
                                     "reason": f"{exported['label']} is already the skill of an earlier group"})
                continue
            skills_seen.add(exported["slug"])
            if not exported["checked"]:
                unchecked.append(exported["label"])
            groups.append(exported)
        return groups, unchecked

    def _export_notes(self, text: dict, facts: dict, points: dict, plan: dict, unchecked: list[str],
                      skip: tuple[int, ...] = (), after_facts: list[str] | None = None) -> list[str]:
        notes = [line.format(**facts) for index, line in enumerate(text["pob_facts"]) if index not in skip]
        notes += after_facts or []
        for kind, key in (("passive", "pob_over"), ("ascendancy", "pob_over_asc")):
            if points[kind].get("over"):
                notes.append(text[key].format(used=points[kind]["used"], limit=points[kind]["limit"]))
        names = text["attribute_names"]
        unset = plan["free"] - sum(plan["assigned"].values())
        if plan["assigned"]:
            parts = ", ".join(f"{names[a]} × {n}" for a, n in plan["assigned"].items())
            key = "pob_attribute_asked" if plan["asked"] else "pob_attribute"
            notes.append(text[key].format(count=plan["free"] - unset, parts=parts))
        if unset:
            notes.append(text["pob_no_attribute"].format(count=unset))
        for key, row in plan["attributes"].items():
            if row["have"] is not None and row["need"] > row["have"]:
                notes.append(text["pob_short"].format(attribute=names[key], have=row["have"], need=row["need"],
                                                      gap=row["need"] - row["have"]))
        if unchecked:
            notes.append(text["pob_unchecked"].format(names=", ".join(unchecked)))
        return notes

    def _export_gear(self, gear_in: list[str], parsed: list[tuple[str, str, list[str]]],
                     not_exported: list[dict]) -> list[dict]:
        """One dict per exported item (item, label, requires, requires_level, adds). A rare's target
        modifiers are checked like verify_build's affixes (what the class can roll, 3 prefixes +
        3 suffixes, one per family) and written at the upper end of their best tier."""
        items, used = [], set()
        for entry, (slot, name, affixes) in zip(gear_in, parsed):
            numbered = NUMBERED_SLOTS.get(slot)
            if numbered:                                    # "ring", "charm": the next free numbered slot
                slot = next((s for s in numbered if s not in used), numbered[0])
            if slot in used:
                not_exported.append({"input": entry, "expected": "gear", "suggestions": [],
                                     "reason": f"{slot} already has an item in this export"})
                continue
            exported = self._gear_item(entry, slot, name, affixes, not_exported)
            if exported is not None:
                used.add(slot)
                items.append(exported)
        weapon = next((i for i in items if i["item"].slot == "Weapon 1"), None)
        offhand = next((i for i in items if i["item"].slot == "Weapon 2"), None)
        problem = _offhand_problem(weapon["item_class"] if weapon else None, offhand["item_class"]) if offhand else None
        if problem:
            items.remove(offhand)
            not_exported.append({"input": offhand["input"], "expected": "gear", "suggestions": [], "reason": problem})
        return items

    def _gear_item(self, entry: str, slot: str, name: str, affixes: list[str], not_exported: list[dict]) -> dict | None:
        try:
            kind, record = self.items._resolve(name)
        except AmbiguousItem as exc:
            not_exported.append({"input": entry, "expected": "gear", "reason": str(exc),
                                 "suggestions": [{"slug": option} for option in exc.options]})
            return None
        except NotFound:
            unknown = self._unknown_item(name)
            not_exported.append({**unknown, "input": entry, "expected": "gear",
                                 "reason": f"{unknown['reason']} ({name}); the item was left out"})
            return None
        item_class = record.get("item_class")
        if item_class not in SLOT_CLASSES[slot]:
            not_exported.append({"input": entry, "expected": "gear", "suggestions": [],
                                 "reason": f"{record['name']} is {item_class or 'of no known class'}, "
                                           f"which does not go in {slot}"})
            return None
        implicits = _item_lines(record.get("implicits"))
        if kind == "unique":
            for text in affixes:
                not_exported.append({"input": text, "expected": "affix", "suggestions": [],
                                     "reason": f"{record['name']} is a unique: its modifiers are fixed"})
            base = record.get("base") or ""
            if not base:
                not_exported.append({"input": entry, "expected": "gear", "suggestions": [],
                                     "reason": f"{record['name']} has no base type in the local data"})
                return None
            item = PobItem(slot, "UNIQUE", record["name"], base, implicits, _item_lines(record.get("mods")))
            modifiers = len(item.explicits)
        else:
            texts = self._gear_modifiers(slot, record["name"], affixes, not_exported)
            item = PobItem(slot, "RARE" if texts else "NORMAL", RARE_NAME.format(slot=slot), record["name"],
                           implicits, _item_lines(texts))
            modifiers = len(texts)
        return {"item": item, "input": entry, "label": record["name"], "item_class": item_class, "modifiers": modifiers,
                "spirit": self._base_spirit(record["name"] if kind != "unique" else record.get("base")),
                "requires": {a: v for a, v in (record.get("requires") or {}).items() if a in ATTRIBUTES},
                "requires_level": record.get("requires_level"), "adds": _gear_attributes(implicits + item.explicits)}

    def _base_spirit(self, base: str | None) -> int:
        """A base's own Spirit property ("Spirit: 100" on sceptres); PoB adds it to the character."""
        record = next((b for b in self.items.bases.values() if b.get("name") == base), None) if base else None
        return next((int(m.group(1)) for p in (record or {}).get("properties") or [] if (m := BASE_SPIRIT.match(p))), 0)

    def _gear_modifiers(self, slot: str, base: str, affixes: list[str], not_exported: list[dict]) -> list[str]:
        """The best-tier text of each verified modifier (one modifier can be several stat lines)."""
        kept, lines = [], []
        for text in affixes:
            fact = self.affix_fact(f"{base}: {text}")
            if fact.get("expected") == "affix":
                not_exported.append({**fact, "input": text})
                continue
            fact = {**fact, "item": slot, "input": text}          # the 3 + 3 count is per item, not per base
            problem = _affix_conflict(fact, kept)
            if problem:
                not_exported.append({"input": text, "expected": "affix", "reason": problem, "suggestions": []})
                continue
            if any(_same_modifier(fact, other) for other in kept):
                continue
            best = (fact.get("best") or {}).get("text")
            if not best:
                not_exported.append({"input": text, "expected": "affix", "suggestions": [],
                                     "reason": "the modifier has no English text in the local data"})
                continue
            kept.append(fact)
            lines.append(best)
        return lines

    def _pob_ids(self, cls: str, ascendancy: str | None) -> tuple[int, str | None]:
        """PoB's class integer id and ascendancy internal id (None when PoB has none for it)."""
        entry = next((c for c in (self.lookup.classes_doc or {}).get("classes", []) if c["name"] == cls), None)
        if entry is None or not isinstance(entry.get("pob_id"), int):
            raise ServiceUnavailable("the class data has no Path of Building ids; "
                                     "update the passive data (update_data with scope passives)")
        if ascendancy is None:
            return entry["pob_id"], None
        asc = next((a for a in entry.get("ascendancies", []) if a["name"] == ascendancy), None)
        return entry["pob_id"], (asc or {}).get("pob_id")

    def _pob_group(self, entry: str, skill: str, supports: list[str], not_exported: list[dict],
                   level: int) -> dict | None:
        """One entry as a group with its verified, compatible supports, the skill gem at the highest
        level a character of `level` can use, and the attributes the group needs; None when the
        skill itself does not verify (the whole entry is then reported)."""
        main = self._pob_gem_record(skill)
        if main is None:
            unknown = self.unverified_entry(skill, "gem")
            not_exported.append({**unknown, "input": entry, "expected": "skill gem",
                                 "reason": f"{unknown['reason']} ({skill}); the whole group was left out"})
            return None
        if main["kind"] == "support_gem" or main["gem"] is None:
            reason = ("the gem before the colon is a support gem; it goes after a skill's colon"
                      if main["kind"] == "support_gem" else f"{main['name']}: {NO_GAME_ID}")
            not_exported.append({"input": entry, "expected": "skill gem", "reason": reason, "suggestions": []})
            return None
        gem_level, needs = gem_level_and_needs(main["record"], level)
        gems, seen, adds = [replace(main["gem"], level=gem_level)], set(), {}
        records = [(main["name"], main["kind"], main["record"])]
        cost = str(main["record"].get("cost") or "")
        base_spirit = _number(SPIRIT_COST, cost)
        persistent = "persistent" in {str(t).casefold() for t in main["record"].get("tags") or []}
        spirit_known = bool(base_spirit) or not (SPIRIT_RANGE.search(cost) or persistent)
        spirit, multiplier, to_life = base_spirit, 1.0, False
        allowed = self._support_slugs(main["slug"])
        for name in supports:
            record = self._pob_gem_record(name)
            if record is not None and record["slug"] in seen:
                continue
            problem = self._support_problem(name, record, main, allowed, len(gems) - 1)
            if problem:
                not_exported.append(problem)
                continue
            seen.add(record["slug"])
            gems.append(record["gem"])
            records.append((record["name"], record["kind"], record["record"]))
            for key, value in support_needs(record["record"]).items():
                adds[key] = adds.get(key, 0) + value
            if base_spirit:                    # a support reserves extra Spirit only on a skill that reserves it
                spirit += _number(SPIRIT_EXTRA, record["record"].get("main_stat"))
                multiplier *= _number(SPIRIT_MULTIPLIER, record["record"].get("main_stat")) / 100 or 1
                to_life |= bool(SPIRIT_TO_LIFE.search(str(record["record"].get("description") or "")))
        return {"group": PobSkillGroup(label=main["name"], gems=tuple(gems)), "label": main["name"],
                "slug": main["slug"], "colour": main["colour"], "checked": allowed is not None, "needs": needs,
                "support_adds": adds, "records": records,
                # PoB: (base + additional reservation) x the supports' multipliers, rounded
                "spirit": 0 if to_life else math.floor(spirit * multiplier + 0.5), "spirit_known": spirit_known}

    def _support_problem(self, name: str, record: dict | None, main: dict, allowed: set[str] | None,
                         count: int) -> dict | None:
        """Why a support cannot join the group, as a `not_exported` entry, or None."""
        if record is None:
            return {**self.unverified_entry(name, "gem"), "expected": "support gem"}
        if record["slug"] == main["slug"]:
            reason = f"{record['name']} is the group's own skill, not a support"
        elif record["kind"] != "support_gem":
            reason = f"{record['name']} is not a support gem"
        elif record["gem"] is None:
            reason = NO_GAME_ID
        elif allowed is not None and record["slug"] not in allowed:
            reason = f"{record['name']} cannot support {main['name']} in the local data"
        elif count >= MAX_SUPPORTS:
            reason = f"a skill group here holds at most {MAX_SUPPORTS} supports"
        else:
            return None
        return {"input": name, "expected": "support gem", "reason": reason, "suggestions": []}

    def _pob_gem_record(self, name: str) -> dict | None:
        """slug, kind, English name, attribute colour and the PoB gem for a gem name; None when the
        name does not verify. `gem` is None when the record has no game id PoB could load it by."""
        try:
            entity = self.lookup._resolve(name, GEM_KINDS)
            record = self.lookup._gem_record(entity["kind"], entity["slug"])
        except NotFound:
            return None
        english = record.get("name") or entity["name_en"]
        gem_id, variant = record.get("item_type"), record.get("game_id")
        has_ids = isinstance(gem_id, str) and gem_id and isinstance(variant, str) and variant
        colour = record.get("attribute_colour")
        return {"slug": entity["slug"], "kind": entity["kind"], "name": english, "record": record,
                "colour": colour if colour in ATTRIBUTES else None,
                "gem": PobGem(name=english, gem_id=gem_id, variant_id=variant,
                              support=entity["kind"] == "support_gem") if has_ids else None}

    def _support_slugs(self, skill_slug: str) -> set[str] | None:
        """Support gems that can support the skill; None when the knowledge graph is missing or
        does not hold the skill (supports then go in unchecked, and a note says so)."""
        graph = self.lookup.graph
        node_id = f"gem:{skill_slug}"
        if graph is None or node_id not in graph:
            return None
        return {graph.nodes[u].get("slug") for u, _, d in graph.in_edges(node_id, data=True)
                if d.get("type") == "SUPPORTS"}

    def _main_group(self, main_skill: str | None, groups: list, not_exported: list[dict]) -> int:
        if not main_skill or not clean_text(main_skill):
            return 1
        record = self._pob_gem_record(main_skill)
        for index, exported in enumerate(groups, 1):
            if record and record["gem"] and exported["group"].gems[0].gem_id == record["gem"].gem_id:
                return index
        not_exported.append({"input": main_skill, "expected": "main skill", "suggestions": [],
                             "reason": ("not the skill of any exported group; the first group is the main skill"
                                        if groups else "no skill group was exported")})
        return 1

    def ladder_source(self, lang: str = "en") -> dict:
        """Where the reference builds come from: label, URL, league and snapshot date."""
        rows, _ = self._load_builds()
        league = _most_common((r.get("league") for r in rows), 1)
        league_name = league[0]["name"] if league else None
        label = TEXT[lang]["ninja"] + (f" ({league_name})" if league_name else "")
        return {"label": label, "url": POE_NINJA_URL, "fetched_at": self._builds_date, "league": league_name}

    def _canonical_skill(self, main_skill: str) -> str:
        _require(main_skill, "main_skill")
        try:
            return self.lookup._resolve(main_skill, GEM_KINDS)["name_en"]
        except NotFound:
            return clean_text(main_skill)

    def _load_builds(self) -> tuple[list[dict], int]:
        with self._builds_lock:
            if self._builds is None:
                if not self.builds_path.exists():
                    raise ServiceUnavailable(
                        "community builds missing; update the ladder data (update_data with scope ninja)")
                try:
                    builds = _read_builds(self.builds_path)
                    modified = self.builds_path.stat().st_mtime
                except OSError as exc:
                    raise ServiceUnavailable(
                        f"community builds unreadable ({type(exc).__name__}): {self.builds_path.name}") from exc
                # When the data was fetched (recorded in the rows), not when the file was copied.
                self._builds_date = (_snapshot_date(builds[0])
                                     or datetime.fromtimestamp(modified, timezone.utc).date().isoformat())
                self._builds = builds
            return self._builds


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def number_sources(facts: list[dict]) -> list[dict]:
    """One numbered row per distinct URL; each fact gets `cite` = the number of its row."""
    rows: list[dict] = []
    by_url: dict[str, dict] = {}
    for fact in facts:
        primary = fact["sources"][0] if fact.get("sources") else None
        if primary is None:
            continue
        row = by_url.get(primary["url"])
        if row is None:
            on_poe2db = primary["label"].startswith(POE2DB_LABEL)
            zh = next((s["url"] for s in fact["sources"][1:] if "zh-TW" in s["label"]), None)
            row = {"n": len(rows) + 1, "label": POE2DB_LABEL if on_poe2db else primary["label"],
                   "name": fact.get("name") if on_poe2db else None,
                   "name_zh_tw": fact.get("name_zh_tw") if on_poe2db else None,
                   "url": primary["url"], "url_zh_tw": zh, "fetched_at": primary.get("fetched_at")}
            by_url[primary["url"]] = row
            rows.append(row)
        fact["cite"] = row["n"]
        for extra in fact["sources"][1:]:  # where a page-less node's Chinese text comes from
            if extra["label"] == TREE_DATA_LABEL and extra["url"] not in by_url:
                by_url[extra["url"]] = {"n": len(rows) + 1, "label": extra["label"], "name": None, "name_zh_tw": None,
                                        "url": extra["url"], "url_zh_tw": None, "fetched_at": extra.get("fetched_at"),
                                        "note": "zh_text"}
                rows.append(by_url[extra["url"]])
    return rows


def render_sources(sources: list[dict], unverified: list[dict], lang: str = "en") -> str:
    """The Sources section as Markdown, in the answer language. Written by code so links and
    names never depend on what the model remembers."""
    text = TEXT[lang]
    lines = [text["header"]]
    for row in sources:
        lines.append(f"{row['n']}. {_source_line(row, lang)}")
    if unverified:
        names = ", ".join(_removed_name(u, text) for u in unverified)
        lines += ["", text["removed"].format(names=names)]
    return "\n".join(lines)


def render_ladder_source(source: dict, lang: str = "en", total: int | None = None) -> str:
    """The poe.ninja line that follows the Sources section when ladder builds were used."""
    text = TEXT[lang]
    line = text["reference"].format(label=_md_text(source["label"]), url=source["url"], date=source["fetched_at"])
    return line + (text["matched"].format(total=total) if total is not None else "")


def _source_line(row: dict, lang: str) -> str:
    text = TEXT[lang]
    if row["label"] != POE2DB_LABEL:  # PoB2 tree: one row for every node without a page
        what = text[row.get("note") or "no_page"]
        date = (row.get("fetched_at") or "")[:10]
        tail = text["fetched"].format(label=what, date=date) if date else what
        return f"[{_md_text(row['label'])}]({_md_url(row['url'])}) — {tail}"
    name = row.get("name") or row.get("name_zh_tw") or str(row["url"]).rsplit("/", 1)[-1]
    links = [f"[{_md_text(name)}]({_md_url(row['url'])})"]
    if row.get("name_zh_tw") and row.get("url_zh_tw"):
        links.append(f"[{_md_text(row['name_zh_tw'])}]({_md_url(row['url_zh_tw'])})")
    if lang == "zh-tw":
        links.reverse()
    date = (row.get("fetched_at") or "")[:10]
    tail = text["fetched"].format(label=row["label"], date=date) if date else row["label"]
    return f"{' · '.join(links)} — {tail}"


def _removed_name(entry: dict, text: dict) -> str:
    name = _md_code(entry["input"])
    if entry.get("replaced_by"):
        return text["replaced"].format(name=name, other=_md_text(entry["replaced_by"]))
    return name


def _md_text(value: str) -> str:
    """Single line, bounded, with the characters that open Markdown links / emphasis escaped."""
    flat = " ".join(str(value).split())[:MAX_ECHO_LEN]
    for ch in ("\\", "[", "]", "(", ")", "<", ">", "`", "*", "_", "|", "!"):
        flat = flat.replace(ch, "\\" + ch)
    return flat


def _md_code(value: str) -> str:
    """Text the caller typed, as an inline code span: nothing in it renders as a link (bare
    URLs included), HTML or heading."""
    flat = " ".join(str(value).split())[:MAX_ECHO_LEN].replace("`", "'")
    return f"`{flat}`"


def _md_url(url: str) -> str:
    return str(url).replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")


def _names(values: list[str] | None, label: str, limit: int = MAX_NAMES, max_len: int = MAX_NAME_LEN) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise BadArgument(f"{label} must be a list of names")
    if len(values) > limit:
        raise BadArgument(f"{label} has {len(values)} names; the limit is {limit}")
    out = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise BadArgument(f"{label} must contain non-empty names")
        if len(value) > max_len:
            raise BadArgument(f"a name in {label} is longer than {max_len} characters")
        out.append(clean_text(value))
    return out


def _attribute(value: str | None) -> str | None:
    """str / dex / int for an attribute name in English or 繁體中文; None when not given."""
    if value is None or not str(value).strip():
        return None
    _cap(value, "attribute")
    key = ATTRIBUTE_ALIASES.get(clean_text(value).casefold())
    if key is None:
        raise BadArgument(f"attribute must be one of str, dex, int (or Strength, Dexterity, Intelligence, "
                          f"力量, 敏捷, 智慧), not {clean_text(value)[:MAX_ECHO_LEN]!r}")
    return key


def _parse_gear(entry: str) -> tuple[str, str, list[str]]:
    """'Slot: item; modifier; modifier' → (PoB slot, item, modifiers)."""
    parts = AFFIX_SEPARATOR.split(entry, maxsplit=1)
    if len(parts) != 2 or not clean_text(parts[0]):
        raise BadArgument(f"a gear entry is 'slot: item; modifier; modifier', e.g. "
                          f"'Ring 1: Ruby Ring; +# to maximum Life'; got {entry[:MAX_ECHO_LEN]!r}")
    slot = SLOT_ALIASES.get(clean_text(parts[0]).casefold())
    if slot is None:
        raise BadArgument(f"unknown gear slot {clean_text(parts[0])[:MAX_ECHO_LEN]!r}; slots: {', '.join(SLOT_CLASSES)}")
    item, *affixes = [clean_text(p) for p in GEAR_SEPARATOR.split(parts[1])]
    if not item:
        raise BadArgument(f"a gear entry needs an item after the slot; got {entry[:MAX_ECHO_LEN]!r}")
    for name in [item, *affixes]:
        if len(name) > MAX_NAME_LEN:
            raise BadArgument(f"a name in gear is longer than {MAX_NAME_LEN} characters")
    return slot, item, [a for a in affixes if a]


def _item_lines(texts: list[str] | None) -> tuple[str, ...]:
    """Stat lines for PoB from stored modifier texts: one line per stat (a modifier's text can
    hold several), every range at its upper end, lines the game hides left out."""
    lines = [line.strip() for text in texts or [] if text for line in upper_value(text).split("\n")]
    return tuple(line for line in lines if line and HIDDEN_LINE not in line and not INTERNAL_LINE.match(line))


def _offhand_problem(weapon: str | None, offhand: str) -> str | None:
    """Why the off-hand item cannot sit next to the main-hand class (None: no weapon), or None."""
    if offhand == "Quivers":
        return None if weapon == "Bows" else "a quiver goes in Weapon 2 only with a bow in Weapon 1"
    if weapon == "Bows":
        return "a bow in Weapon 1 takes only a quiver in Weapon 2"
    if weapon in TWO_HANDED:
        return f"Weapon 1 holds a two-handed item ({weapon}); Weapon 2 stays empty"
    if offhand in OFFHAND_WEAPONS and weapon in NO_WEAPON_OFFHAND:
        return f"with {weapon} in Weapon 1, Weapon 2 takes a shield, buckler, focus or sceptre, not a weapon"
    return None


def _gear_attributes(lines: tuple[str, ...]) -> dict[str, int]:
    """Fixed attributes on an item's lines ("+30 to Dexterity", "+10 to all Attributes")."""
    totals: dict[str, int] = {}
    for line in lines:
        match = GEAR_ATTRIBUTE.match(line.strip())
        if match:
            for key in ATTRIBUTE_FAMILIES[match.group(2).casefold()]:
                totals[key] = totals.get(key, 0) + int(match.group(1))
    return totals


def _character_level(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CHARACTER_LEVEL:
        raise BadArgument(f"character_level must be a whole number from 1 to {MAX_CHARACTER_LEVEL}")
    return value


def gem_level_and_needs(record: dict, character_level: int) -> tuple[int, dict[str, int]]:
    """The highest gem level (at most GEM_LEVEL) whose required level the character meets, and the
    attributes that level requires, read from the gem's own level table. A gem no row allows
    yet stays at its lowest level."""
    best = lowest = None
    for row in record.get("level_effects") or []:
        level, required = _whole(row.get("Level")), _whole(row.get("Requires Level"))
        if level is None or required is None or level > GEM_LEVEL:
            continue
        if lowest is None or level < lowest[0]:
            lowest = (level, row)
        if required <= character_level and (best is None or level > best[0]):
            best = (level, row)
    best = best or lowest          # nothing usable yet: the gem's lowest level
    if best is None:
        return 1, {}
    needs = {key: _whole(best[1].get(column)) for column, key in ATTRIBUTE_COLUMNS.items()}
    return best[0], {key: value for key, value in needs.items() if value}


def support_needs(record: dict) -> dict[str, int]:
    """What a support gem adds to its skill's attribute requirements ("+5 Int")."""
    found = SUPPORT_NEED.findall(str(record.get("requires_stats") or ""))
    return {ATTRIBUTE_COLUMNS[column]: int(value) for value, column in found}


def _gem_lines(record: dict) -> list[str]:
    """A gem's own text: description, stat lines and the extra columns of its level table (some
    gems state an effect only there, e.g. "Gain a Frenzy Charge when you Freeze ...")."""
    columns = (record.get("level_effects") or [{}])[0]
    extra = [key for key in columns if key not in LEVEL_TABLE_COLUMNS]
    lines = [record.get("description"), *(record.get("extra_properties") or []), record.get("main_stat"), *extra]
    return [sentence for line in lines if line for sentence in _sentences(str(line))]


def _sentences(text: str) -> list[str]:
    return [" ".join(part.split()) for part in re.split(r"(?<=[.!?])\s+|\n", text) if part.strip()]


def _line_options(line: str, tags: set[str]) -> list[str]:
    """The configuration options one line of the build's text is evidence for."""
    if NOT_EVIDENCE.search(line):
        return []
    found = [option for kind, option in CHARGE_OPTIONS.items()
             if re.search(CHARGE_GAIN.format(kind=kind), line, re.I)
             and not re.search(CHARGE_TRIGGERED.format(kind=kind), line, re.I)]
    for option, words in STATE_OPTIONS.items():
        if re.search(STATE_CAUSE.format(w=words), line, re.I) and not re.search(STATE_BENEFIT.format(w=words), line, re.I):
            found.append(option)
    exposure = EXPOSURE_CAUSE.search(line)
    if exposure:
        element = (exposure.group(2) or "").casefold()
        if element == "elemental" or "elemental resistances" in line.casefold():
            elements = list(EXPOSURE_OPTIONS)
        elif element in EXPOSURE_OPTIONS:
            elements = [element]
        else:
            elements = [e for e in EXPOSURE_OPTIONS if e in tags]
        found += [EXPOSURE_OPTIONS[e] for e in elements]
    if CRIT_RECENT.search(line):
        found.append(CRIT_RECENTLY)
    return found


def _blocked_options(line: str) -> set[str]:
    """Options a "cannot …" line rules out for its skill group (e.g. a support whose skills
    cannot inflict Shock, or cannot generate Frenzy Charges)."""
    if not CANNOT.search(line) or NOT_A_BLOCK.search(line):
        return set()
    blocked = {option for kind, option in CHARGE_OPTIONS.items() if re.search(rf"\b{kind} charges?\b", line, re.I)}
    blocked |= {option for option, words in STATE_OPTIONS.items() if re.search(rf"\b(?:{words})\w*", line, re.I)}
    return blocked


def _config_note(text: dict, options: dict) -> str:
    """The line for PoB's Notes tab."""
    if not options:
        return text["pob_config_none"]
    return text["pob_config_on"].format(names=", ".join(text["config_labels"][o] for o in options))


def _config_notes(text: dict, options: dict, asked: bool) -> list[str]:
    if not asked:
        return [text["pob_config_off"]]
    notes = [_config_note(text, options)]
    if any(o in CHARGE_OPTIONS.values() for o in options):
        notes.append(text["pob_config_charges"])
    missing = [text["config_labels"][o] for o in NINJA_OPTIONS if o not in options]
    if missing:
        notes.append(text["pob_config_ladder"].format(names=", ".join(missing)))
    return notes


def _number(pattern: re.Pattern, text) -> int:
    match = pattern.search(str(text or ""))
    return int(match.group(1)) if match else 0


def _whole(value) -> int | None:
    text = str(value).strip() if value is not None else ""
    return int(text) if text.isdigit() else None


def _unreachable_entry(row: dict) -> dict:
    return {"input": row["input"], "expected": "passive", "reason": row["reason"], "suggestions": []}


def _parse_group(entry: str) -> tuple[str, list[str]]:
    """'Skill: Support, Support' → ("Skill", ["Support", "Support"]); a bare skill has no supports."""
    parts = AFFIX_SEPARATOR.split(entry, maxsplit=1)
    skill = clean_text(parts[0])
    supports = [clean_text(s) for s in SUPPORT_SEPARATOR.split(parts[1])] if len(parts) == 2 else []
    supports = [s for s in supports if s]
    if not skill:
        raise BadArgument(f"a skill group must start with a skill gem, e.g. 'Ice Shot: Pierce I, Martial Tempo'; "
                          f"got {entry[:MAX_ECHO_LEN]!r}")
    for name in [skill, *supports]:
        if len(name) > MAX_NAME_LEN:
            raise BadArgument(f"a gem name in skills is longer than {MAX_NAME_LEN} characters")
    return skill, supports


def _read_builds(path: Path) -> tuple[list[dict], int]:
    """Rows of the ladder file. A line that is not valid UTF-8 JSON (or is nested too deeply to
    parse) is counted in `skipped`; it never fails the whole load."""
    rows, skipped = [], 0
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):   # ValueError covers JSON and UTF-8 errors
                skipped += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                skipped += 1
    return rows, skipped


def _most_common(values, top: int = COMMON_TOP) -> list[dict]:
    counts = Counter(str(v) for v in values if v)
    return [{"name": name, "count": count} for name, count in counts.most_common(top)]


def _others(row: dict) -> list[str]:
    """The gems of a ladder row besides its main skill."""
    main = str(row.get("main_skill") or "").lower()
    return [g for g in _strings(row.get("skill_gems")) if g.lower() != main]


def _strings(value) -> list[str]:
    """The strings of a list field; anything else (a bare string, a number) counts as empty."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _snapshot_date(rows: list[dict]) -> str | None:
    """Latest `fetched_at` day recorded in the rows (ISO dates sort as text)."""
    days = [r["fetched_at"][:10] for r in rows
            if isinstance(r.get("fetched_at"), str) and _DATE_RE.match(r["fetched_at"])]
    return max(days, default=None)


def _budget(used: int, limit: int | None) -> dict:
    return {"used": used, "limit": limit, "over": used > limit if isinstance(limit, int) else None}


def _is_start(node: dict) -> bool:
    return node.get("type") == START_NODE_TYPE or bool(node.get("is_ascendancy_start"))


def _name_key(name: str) -> str:
    """Folded spelling of a name, so 'Mega Slam' and 'mega slam' are reported once."""
    aliases = make_aliases(name)
    return aliases[-1] if aliases else name.casefold()


def _same_modifier(fact: dict, kept: dict) -> bool:
    return (fact["item"].casefold(), fact["family"], fact["group"], fact["modifier"]) == \
        (kept["item"].casefold(), kept["family"], kept["group"], kept["modifier"])


def _affix_conflict(fact: dict, kept: list[dict]) -> str | None:
    """Why this modifier cannot join the ones already verified for the same item, or None.
    Counted per item as written (two rings are two items); a rare item holds at most
    MAX_PER_AFFIX prefixes and MAX_PER_AFFIX suffixes, and one modifier per family."""
    same_item = [k for k in kept if k["item"].casefold() == fact["item"].casefold()]
    for other in same_item:
        if (other["family"], other["group"]) == (fact["family"], fact["group"]) and other["modifier"] != fact["modifier"]:
            return f"same modifier family as {other['input']!r}; an item cannot have both"
    if any(_same_modifier(fact, other) for other in same_item):
        return None
    if fact["affix"] and sum(1 for k in same_item if k["affix"] == fact["affix"]) >= MAX_PER_AFFIX:
        return (f"{fact['item']} already has {MAX_PER_AFFIX} {fact['affix']}es in this list; an item holds at most "
                f"{MAX_PER_AFFIX} prefixes and {MAX_PER_AFFIX} suffixes")
    return None


def _compact_affix(fact: dict, lang: str) -> dict:
    """An affix fact as returned: its page is in the numbered sources (`cite`), and the tier texts
    are given in the answer language only, so a full set of gear fits in one response."""
    key = "text_zh_tw" if lang == "zh-tw" else "text"
    out = {k: v for k, v in fact.items() if k not in ("sources", "name", "name_zh_tw", "best", "lowest")}
    for tier in ("best", "lowest"):
        out[tier] = {"text": fact[tier].get(key) or fact[tier]["text"], "level": fact[tier]["level"]}
    return out


def _returned_fact(fact: dict, detail: str) -> dict:
    """A fact as verify_build returns it. Its page is in the numbered source list (`cite`), so the
    links are not repeated on every fact; `brief` keeps only what names and cites it."""
    if detail == "brief":
        return {k: fact[k] for k in BRIEF_KEYS if k in fact}
    return {k: v for k, v in fact.items() if k != "sources"}
