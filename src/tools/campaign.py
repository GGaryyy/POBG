"""
campaign.py — The campaign, act by act: what each stage allows a build, and the areas, bosses
and quests of each act.

`campaign_stages` is what a campaign build is planned against. Every limit comes from the data:
the character level is the highest area level of the stage (towns left out); passive points are
the level's points plus the quest points up to the stage; ascendancy points come from the
trials whose area level the stage reaches; Spirit from the quest rewards up to the stage; the
highest skill gem level from the gem level table; the support gem tier from the drop level of
each Uncut Support Gem; support sockets from the Jeweller's Orbs that drop by then. What the data
does not hold is listed in `not_in_data`, so an answer can say so instead of guessing.

With the atlas data (data/atlas), the map stages follow the acts (Tier 1 / 10 / 16 waystones in
0.5, see atlas.py) under the same rules, and every stage has the resistance penalty of its level.
"""

from __future__ import annotations

import copy
import json
import re
import threading

from src.catalog.spec import INTERLUDE_STAGE
from src.scrapers.common import clean_text, read_jsonl
from src.tools.atlas import NOT_IN_DATA as ATLAS_NOT_IN_DATA
from src.tools.atlas import AtlasLookup, tier_from_words
from src.tools.lookup import (
    BadArgument,
    LookupService,
    NotFound,
    ServiceUnavailable,
    _cap,
    _lang,
    _limit,
    _require,
    is_cjk,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SOURCE = "campaign"
REBUILD_HINT = "campaign data missing; update it with update_data scope campaign"
LISTED_KINDS = ("area", "quest", "boss", "reward")
DEFAULT_LIST_LIMIT = 30
STAGE_WORDS = re.compile(r"^(?:act|第)\s*(\d+)\s*(?:章)?$", re.I)
TRAILING_NUMBER = re.compile(r"\s*\d+$")    # "Interlude 2" is the one Interlude stage
ASCII_NAME = re.compile(r"^[\x00-\x7f]+$")
INTERLUDE_WORDS = ("interlude", "interludes", "插曲", "間歇")
REWARD_TAGS = (   # what a permanent reward gives, so it can be found in either language
    (re.compile(r"Passive Skill Point", re.I), ("passive points", "天賦點")),
    (re.compile(r"\bSpirit\b"), ("Spirit", "精魂")),
    (re.compile(r"Resistance", re.I), ("resistance", "抗性")),
    (re.compile(r"maximum Life|Life Recovery", re.I), ("life", "生命")),
    (re.compile(r"Mana", re.I), ("mana", "魔力")),
    (re.compile(r"Charm", re.I), ("charm", "護符")),
    (re.compile(r"Strength|Dexterity|Intelligence|Attributes", re.I), ("attributes", "屬性")),
    (re.compile(r"Armour|Evasion|Energy Shield|Deflection", re.I), ("defences", "防禦")),
)
CAMPAIGN_KIND, MAPS_KIND = "campaign", "maps"
LEVEL_GAP = 3                 # PoB placing a stage's rewards this many levels higher than poe2db is worth a note
PENALTY_NOT_IN_DATA = {      # what the atlas data answers when it is there
    "en": "The elemental resistance penalty after the acts: not in the local data (update_data scope atlas adds it).",
    "zh-tw": "各章節後的元素抗性懲罰：本機資料沒有（update_data 範圍 atlas 會加上）。",
}
NOT_IN_DATA = {
    "en": [
        "Boss mechanics and fight tips beyond the area walkthroughs: not in the local data.",
        "Drop chances: uncut gems and Jeweller's Orbs drop at random from their drop level; the limits say what can "
        "drop by then, not what a character has.",
        "Spirit from gear (sceptres, amulets, body armours) is not in the stage totals; only quest Spirit is.",
        "The character level a player reaches depends on play; `level` is the highest area level of the stage.",
    ],
    "zh-tw": [
        "頭目的機制與打法（區域攻略以外）：本機資料沒有。",
        "掉落機率：未切割寶石與工匠石自其掉落等級起隨機掉落；上限表示到此時可能掉落的，不代表角色一定已取得。",
        "裝備上的精魂（權杖、項鍊、胸甲）不計入階段總數，只計任務獎勵的精魂。",
        "玩家實際到達的角色等級取決於玩法；`level` 是該階段最高的區域等級。",
    ],
}
LIMIT_NOTES = {
    "en": "Points: level points (level - 1) plus quest points so far; PoB counts quest points both as passive "
          "and as weapon-set points, and a reward PoB places in no act (the Epilog) counts in the last act. "
          "Gem level: the highest the level allows; a skill or Spirit gem tier is taken as usable from the level "
          "that gem level needs. Support tier: the highest Uncut Support Gem level that drops by this area level. "
          "Sockets: what the Jeweller's Orbs that drop by then set.",
    "zh-tw": "天賦點：等級點數（等級 − 1）加上到此為止的任務點數；PoB 把任務點數同時算作天賦點與武器切換點，"
             "PoB 沒有放進任何章節的獎勵（尾聲）計入最後一章。"
             "寶石等級：該等級可用的最高等級；技能與精魂寶石的階級，以該寶石等級所需的角色等級起算。輔助寶石階級：到此區域等級會掉落的最高未切割輔助寶石等級。"
             "插槽：到此時會掉落的工匠石能設定的數量。",
}
MAP_NOTES = {
    "en": " Map stages: the level is the waystone tier's area level; ascendancy points add the endgame trials "
          "whose level the stage reaches (poe2db Ascendancy class page). resistance_penalty: the elemental "
          "resistance penalty from that level on (poe2db Waystones page).",
    "zh-tw": "地圖階段：等級是該換界石階級的區域等級；昇華點加上該等級可進行的後期試煉（poe2db 昇華職業頁）。"
             "resistance_penalty：從該等級起的元素抗性懲罰（poe2db 換界石頁）。",
}


class CampaignLookup:
    """Loads the campaign files once, on first use."""

    def __init__(self, lookup: LookupService) -> None:
        self.lookup = lookup
        self._loaded = False
        self._lock = threading.Lock()
        self.stages: list[dict] = []
        self.areas: dict[str, dict] = {}
        self.quests: dict[str, dict] = {}
        self.rules: dict = {}
        self.atlas = AtlasLookup(lookup)
        self.atlas_problem: str | None = None     # why there are no map stages

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            source = self.lookup.spec.source(SOURCE)
            base = self.lookup.base_dir
            paths = {key: base / source[f"{key}_file"] for key in ("stages", "areas", "quests", "rules")}
            if not all(p.exists() for p in paths.values()):
                raise ServiceUnavailable(REBUILD_HINT)
            try:
                stages = sorted(read_jsonl(paths["stages"]), key=lambda s: s["order"])
                areas = {a["slug"]: a for a in read_jsonl(paths["areas"])}
                quests = {q["slug"]: q for q in read_jsonl(paths["quests"])}
                rules = json.loads(paths["rules"].read_text(encoding="utf-8"))
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise ServiceUnavailable(f"the campaign data is unreadable ({type(exc).__name__}); "
                                         "update it with update_data scope campaign") from exc
            for entry in stages:
                entry.setdefault("kind", CAMPAIGN_KIND)
            try:
                stages += self.atlas.map_stages(stages[-1]["order"] if stages else 0,
                                                stages[-1]["area_level_max"] if stages else 0)
                self.atlas_problem = None
            except ServiceUnavailable as exc:
                self.atlas_problem = str(exc)
            self.stages, self.areas, self.quests, self.rules = stages, areas, quests, rules
            self._loaded = True

    # -- stages ------------------------------------------------------------------

    def campaign_stages(self, lang: str | None = None, maps: bool = True) -> dict:
        """Every stage with its limits, permanent rewards, trials and bosses; with maps=False the
        acts only."""
        self._load()
        lang = _lang(lang) or "en"
        if not isinstance(maps, bool):
            raise BadArgument("maps must be true or false")
        chosen = [s for s in self.stages if maps or s["kind"] == CAMPAIGN_KIND]
        has_atlas = self.atlas_problem is None
        not_in_data = ([] if has_atlas else [PENALTY_NOT_IN_DATA[lang]]) + NOT_IN_DATA[lang]
        result = {
            "lang": lang,
            "stages": [self.stage_limits(stage["id"], lang) for stage in chosen],
            "how": LIMIT_NOTES[lang] + (MAP_NOTES[lang] if has_atlas and maps else ""),
            "not_in_data": not_in_data + (ATLAS_NOT_IN_DATA[lang] if has_atlas and maps else []),
            "rules_sources": self.rules.get("sources", {}),
        }
        if maps and not has_atlas:
            result["maps_note"] = f"no map stages: {self.atlas_problem}"
        return result

    def stage_limits(self, stage: str | int, lang: str = "en") -> dict:
        """One stage: its limits (cumulative up to and including it) and what it gives."""
        self._load()
        current = self.find_stage(stage)
        upto = [s for s in self.stages if s["order"] <= current["order"]]
        level = current["area_level_max"]
        rewards = [r for s in upto for r in s["rewards"]]
        quest_points = sum(r["passive_points"] for r in rewards)
        trials = [t for s in upto for t in s["trials"] if t["area_level"] <= level]
        gem_level = max((row["level"] for row in self.rules.get("skill_gem_levels", [])
                         if row["required_level"] <= level), default=1)
        support_tier = max((row["level"] for row in self.rules.get("support_gem_levels", [])
                            if row["drop_level"] <= level), default=1)
        sockets = max([self.rules.get("base_support_sockets") or 0,
                       *(orb["sockets"] for orb in self.rules.get("socket_orbs", []) if orb["drop_level"] <= level)])
        pob_levels = [r["area_level"] for r in current["rewards"] if r.get("area_level") and not r.get("placed")]
        result = {
            "id": current["id"], "order": current["order"], "kind": current["kind"], "name": current["name"],
            "name_zh_tw": current.get("name_zh_tw"),
            "area_levels": [current["area_level_min"], level],
            "limits": {
                "level": level,
                "passive_points": level - 1 + quest_points,
                "quest_passive_points": quest_points,
                "ascendancy_points": sum(t["ascendancy_points"] for t in trials),
                "quest_spirit": sum(r["spirit"] for r in rewards),
                "skill_gem_level": gem_level,
                "skill_gem_tiers": [t for t in self.rules.get("skill_gem_tiers", []) if t <= gem_level],
                "spirit_gem_tiers": [t for t in self.rules.get("spirit_gem_tiers", []) if t <= gem_level],
                "support_gem_tier": support_tier,
                "support_sockets": sockets,
            },
            "rewards": [_reward_row(r) for r in current["rewards"]],
            "trials": copy.deepcopy(current["trials"]),
            "bosses": self._stage_bosses(current, lang),
            "sources": [{"label": f"poe2db {current['name']}", "url": current["url_en"]},
                        {"label": f"poe2db {current.get('name_zh_tw') or current['name']}", "url": current["url_zh_tw"]},
                        {"label": "PathOfBuilding-PoE2 QuestRewards.lua",
                         "url": self.rules.get("sources", {}).get("quest_rewards")}],
        }
        if self.atlas_problem is None:
            result["limits"]["resistance_penalty"] = self.atlas.penalty_at(level)
        if current["kind"] == MAPS_KIND:
            result["tier"] = current["tier"]
            result["sources"] = [*self.atlas.sources(),
                                 {"label": "poe2db Ascendancy class (endgame trials)", "url": self.atlas.trials_source()}]
        if pob_levels and max(pob_levels) - level >= LEVEL_GAP:
            result["level_note"] = (f"PoB places this stage's quest rewards at area levels up to {max(pob_levels)}, "
                                    f"above poe2db's {level}: the areas may scale with the character.")
        return result

    def find_stage(self, stage: str | int) -> dict:
        self._load()
        if isinstance(stage, int) and not isinstance(stage, bool):
            stage = f"act_{stage}"
        if stage is None or not str(stage).strip():
            raise BadArgument("stage must not be empty")
        _cap(stage, "stage")
        wanted = clean_text(str(stage)).casefold()
        tier = tier_from_words(wanted)
        if tier is not None:
            wanted = f"maps_t{tier}"
        match = STAGE_WORDS.match(wanted.replace("_", " "))
        if match:
            wanted = f"act_{match.group(1)}"
        if TRAILING_NUMBER.sub("", wanted) in INTERLUDE_WORDS:
            wanted = INTERLUDE_STAGE
        for entry in self.stages:
            names = {entry["id"], entry["name"].casefold(), (entry.get("name_zh_tw") or "").casefold()}
            if wanted in names:
                return entry
        known = ", ".join(f"{s['id']} ({s['name']})" for s in self.stages)
        raise NotFound(f"no campaign stage matches {stage!r}; stages: {known}")

    def _stage_bosses(self, stage: dict, lang: str) -> list[dict]:
        out = []
        for slug in stage["areas"]:
            area = self.areas.get(slug, {})
            for boss in area.get("bosses", []):
                out.append({"name": _named(boss, lang), "area": _named(area, lang), "area_level": area.get("level")})
        return out

    # -- what a level allows ------------------------------------------------------------

    def earliest_level(self, record: dict, kind: str) -> int | None:
        """The character (or area) level from which a gem of this tier can be had: a skill or
        Spirit gem of tier T needs an uncut gem of level T, usable from the level table's required
        level; a support gem of tier T needs an Uncut Support Gem of level T, which drops from its
        drop level. None when the gem has no tier."""
        self._load()
        tier = record.get("tier")
        if not isinstance(tier, int) or isinstance(tier, bool):
            return None
        if kind == "support_gem":
            rows = [r["drop_level"] for r in self.rules.get("support_gem_levels", []) if r["level"] >= tier]
        else:
            rows = [r["required_level"] for r in self.rules.get("skill_gem_levels", []) if r["level"] >= tier]
        return min(rows) if rows else None

    def supports_at(self, level: int) -> int:
        """Support sockets a skill can have by this level (the Jeweller's Orbs that drop by then)."""
        self._load()
        return max([self.rules.get("base_support_sockets") or 0,
                    *(o["sockets"] for o in self.rules.get("socket_orbs", []) if o["drop_level"] <= level)])

    def quest_spirit_at(self, stage_id: str) -> int:
        """Spirit from quest rewards up to and including the stage."""
        current = self.find_stage(stage_id)
        return sum(r["spirit"] for s in self.stages if s["order"] <= current["order"] for r in s["rewards"])

    # -- areas and quests ------------------------------------------------------------

    def get_area(self, name: str) -> dict:
        """One area (or the area of a boss): level, bosses, what they grant, connected areas,
        permanent rewards, the community walkthrough and the quests that name it."""
        area = self._resolve_area(name)
        lang = "zh-tw" if is_cjk(name) else "en"
        stage = self.find_stage(area["stage"])
        connected = [{"slug": s, "name": _named(self.areas[s], lang), "level": self.areas[s]["level"]}
                     for s in area.get("connects", []) if s in self.areas]
        quests = [self._quest_brief(q, lang) for q in self.quests.values()
                  if q["stage"] == area["stage"] and _mentions(q, area)]
        return {"area": copy.deepcopy(area), "stage": {"id": stage["id"], "name": stage["name"], "name_zh_tw": stage.get("name_zh_tw")},
                "connects": connected, "quests": quests, "sources": _area_sources(area)}

    def get_quest(self, name: str) -> dict:
        """One quest: type, rewards, objectives (both languages) and its stage."""
        self._load()                         # before self.quests is read: it is replaced on loading
        quest = self._resolve(name, "campaign_quest", self.quests)
        stage = self.find_stage(quest["stage"])
        return {"quest": copy.deepcopy(quest),
                "stage": {"id": stage["id"], "name": stage["name"], "name_zh_tw": stage.get("name_zh_tw")},
                "sources": _area_sources(quest)}

    def campaign_by(self, kind: str, stage: str | None = None, text: str | None = None,
                    limit: int = DEFAULT_LIST_LIMIT) -> dict:
        """Areas, quests, bosses or permanent rewards of the campaign, by stage and / or text in
        either language (names, rewards, objectives, walkthroughs)."""
        self._load()
        if kind not in LISTED_KINDS:
            raise BadArgument(f"kind must be one of {LISTED_KINDS}, not {kind!r}")
        _cap(text, "text")
        limit = _limit(limit)
        chosen = self.find_stage(stage)["id"] if stage not in (None, "") else None
        lang = "zh-tw" if text and is_cjk(text) else "en"
        wanted = clean_text(text).casefold() if text else None
        rows = {"area": self._list_areas, "quest": self._list_quests, "boss": self._list_bosses,
                "reward": self._list_rewards}[kind](chosen, wanted, lang)
        return {"kind": kind, "stage": chosen, "text": text, "total": len(rows), "results": rows[:limit],
                "sources": self._stage_sources(chosen)}

    def _list_areas(self, stage: str | None, wanted: str | None, lang: str) -> list[dict]:
        out = []
        for area in self.areas.values():
            if stage and area["stage"] != stage:
                continue
            fields = [area["name"], area.get("name_zh_tw"), *area.get("content", []), *area.get("content_zh_tw", []),
                      area.get("guide"), area.get("guide_zh_tw"), *(r.get("stat") or "" for r in area["rewards"])]
            if wanted and not _found(wanted, fields):
                continue
            out.append({"slug": area["slug"], "name": area["name"], "name_zh_tw": area.get("name_zh_tw"),
                        "stage": area["stage"], "level": area["level"], "town": area["town"],
                        "waypoint": area["waypoint"], "bosses": [_named(b, lang) for b in area["bosses"]],
                        "url_en": area["url_en"], "url_zh_tw": area["url_zh_tw"]})
        return out

    def _list_quests(self, stage: str | None, wanted: str | None, lang: str) -> list[dict]:
        out = []
        for quest in self.quests.values():
            if stage and quest["stage"] != stage:
                continue
            fields = [quest["name"], quest.get("name_zh_tw"), quest.get("type"), quest.get("type_zh_tw"),
                      *quest["rewards"], *quest.get("rewards_zh_tw", []), *quest["objectives"],
                      *quest.get("objectives_zh_tw", [])]
            if wanted and not _found(wanted, fields):
                continue
            out.append(self._quest_brief(quest, lang))
        return out

    def _list_bosses(self, stage: str | None, wanted: str | None, lang: str) -> list[dict]:
        out = []
        for area in self.areas.values():
            if stage and area["stage"] != stage:
                continue
            for boss in area["bosses"]:
                grants = [c for c in area.get("content", []) if c.startswith(boss["name"])]
                if wanted and not _found(wanted, [boss["name"], boss.get("name_zh_tw"), area["name"],
                                                  area.get("name_zh_tw"), *grants]):
                    continue
                out.append({"name": boss["name"], "name_zh_tw": boss.get("name_zh_tw"), "area": area["name"],
                            "area_zh_tw": area.get("name_zh_tw"), "area_slug": area["slug"], "stage": area["stage"],
                            "area_level": area["level"], "grants": grants, "url_en": area["url_en"]})
        return out

    def _list_rewards(self, stage: str | None, wanted: str | None, lang: str) -> list[dict]:
        out = []
        for entry in self.stages:
            if stage and entry["id"] != stage:
                continue
            for reward in entry["rewards"]:
                area = self.areas.get(reward.get("area_slug") or "", {})
                fields = [reward.get("stat"), *reward.get("options", []), reward.get("giver"), reward.get("area"),
                          area.get("name_zh_tw"), *reward_tags(reward)]
                if wanted and not _found(wanted, fields):
                    continue
                out.append({**_reward_row(reward), "stage": entry["id"], "area_zh_tw": area.get("name_zh_tw")})
        return out

    def _stage_sources(self, stage: str | None) -> list[dict]:
        stages = [s for s in self.stages if (stage is None and s["kind"] == CAMPAIGN_KIND) or s["id"] == stage]
        return [{"label": f"poe2db {s['name']}", "url": s["url_en"]} for s in stages] + \
               [{"label": "PathOfBuilding-PoE2 QuestRewards.lua", "url": self.rules.get("sources", {}).get("quest_rewards")}]

    def _quest_brief(self, quest: dict, lang: str) -> dict:
        return {"slug": quest["slug"], "name": quest["name"], "name_zh_tw": quest.get("name_zh_tw"),
                "stage": quest["stage"], "type": quest.get("type_zh_tw") if lang == "zh-tw" else quest.get("type"),
                "rewards": quest.get("rewards_zh_tw") if lang == "zh-tw" and quest.get("rewards_zh_tw") else quest["rewards"],
                "url_en": quest["url_en"], "url_zh_tw": quest["url_zh_tw"]}

    def _resolve_area(self, name: str) -> dict:
        _require(name, "area or boss name")
        self._load()
        query = clean_text(name)
        if query in self.areas:
            return self.areas[query]
        for entity in self.lookup.index.exact(query):
            if entity.kind == "campaign_area" and entity.slug in self.areas:
                return self.areas[entity.slug]
            if entity.kind == "campaign_boss":
                area = (entity.record_key or {}).get("slug")
                if area in self.areas:
                    return self.areas[area]
        folded = query.casefold()
        for area in self.areas.values():
            names = [area["name"], area.get("name_zh_tw")]
            names += [n for b in area["bosses"] for n in (b["name"], b.get("name_zh_tw"))]
            if folded in (n.casefold() for n in names if n):
                return area
        raise NotFound(f"no campaign area or boss matches {query!r}; try lookup_entity or campaign_by")

    def _resolve(self, name: str, kind: str, store: dict[str, dict]) -> dict:
        _require(name, "name")
        self._load()
        query = clean_text(name)
        if query in store:
            return store[query]
        for entity in self.lookup.index.exact(query):
            if entity.kind == kind and entity.slug in store:
                return store[entity.slug]
        folded = query.casefold()
        for record in store.values():
            if folded in ((record.get("name") or "").casefold(), (record.get("name_zh_tw") or "").casefold()):
                return record
        raise NotFound(f"no campaign quest matches {query!r}; try lookup_entity or campaign_by")


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def reward_tags(reward: dict) -> list[str]:
    """English and Chinese words for what a reward gives ("passive points", "天賦點", ...)."""
    text = " ".join([reward.get("stat") or "", *(reward.get("options") or [])])
    if reward.get("options"):
        text += " choice"
    tags = [word for pattern, words in REWARD_TAGS if pattern.search(text) for word in words]
    return tags + (["choice", "選擇"] if reward.get("options") else [])


def _reward_row(reward: dict) -> dict:
    row = {k: copy.deepcopy(reward.get(k)) for k in ("giver", "area", "area_slug", "stat", "options",
                                                     "passive_points", "spirit", "description")}
    row["tags"] = reward_tags(reward)
    if reward.get("placed"):
        row["placed"] = reward["placed"]
    return {k: v for k, v in row.items() if v not in (None, [], 0) or k in ("stat",)}


def _named(record: dict, lang: str) -> str:
    return (record.get("name_zh_tw") if lang == "zh-tw" else None) or record.get("name") or ""


def _found(wanted: str, fields: list) -> bool:
    return any(wanted in str(field).casefold() for field in fields if field)


def _mentions(quest: dict, area: dict) -> bool:
    """A quest objective names the area: a whole word in English, the name itself in Chinese."""
    texts = [*quest["objectives"], *quest.get("objectives_zh_tw", [])]
    for name in (area["name"], area.get("name_zh_tw")):
        if not name:
            continue
        pattern = re.compile(rf"\b{re.escape(name)}\b") if ASCII_NAME.match(name) else re.compile(re.escape(name))
        if any(pattern.search(text) for text in texts):
            return True
    return False


def _area_sources(record: dict) -> list[dict]:
    out = [{"label": "poe2db (en)", "url": record["url_en"], "fetched_at": record.get("fetched_at")},
           {"label": "poe2db (zh-TW)", "url": record["url_zh_tw"], "fetched_at": record.get("fetched_at")}]
    return out
