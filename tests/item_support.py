"""Synthetic poe2db item class pages (English + Chinese) in the layout collect_items reads.

Everything here is made up; only the HTML and JSON shapes follow the real pages.
"""

from __future__ import annotations

import copy
import json

from src.catalog.spec import Spec, load_spec

FETCHED = "2026-01-01T00:00:00+00:00"

BOW_BASES = [
    {"slug": "Shortbow", "en": "Shortbow", "zh": "短弓", "level": 5, "dex": 12,
     "props": [("Physical Damage", "物理傷害", "7-14"), ("Attacks per Second", "每秒攻擊次數", "1.25")], "implicit": None},
    {"slug": "Dualstring_Bow", "en": "Dualstring Bow", "zh": "雙弦弓", "level": 28, "dex": 52,
     "props": [("Physical Damage", "物理傷害", "19-35")],
     "implicit": ("+50% Surpassing chance to fire an additional Arrow", "+50%滿溢機率發射額外一枚箭矢")},
]
BOW_UNIQUES = [
    {"slug": "Quill_Rain", "en": "Quill Rain", "zh": "驟雨之弦", "base": ("Shortbow", "短弓"), "level": 5, "dex": 12,
     "mods": [("100% increased Attack Speed", "增加100%攻擊速度"), ("40% less Attack Damage", "40%更少攻擊傷害")]},
]
# (group, generation id, family, level, name en, name zh, text en, text zh, tags)
BOW_MODS = [
    ("normal", "1", "FireDamage", 1, "Heated", "加熱的", "Adds (1—2) to (3—5) Fire Damage", "附加(1—2)至(3—5)火焰傷害", ["fire", "attack"]),
    ("normal", "1", "FireDamage", 33, "Burning", "燃燒的", "Adds (20—27) to (31—47) Fire Damage", "附加(20—27)至(31—47)火焰傷害", ["fire", "attack"]),
    ("normal", "1", "FireDamage", 75, "Cremating", "火化的", "Adds (62—84) to (95—145) Fire Damage", "附加(62—84)至(95—145)火焰傷害", ["fire", "attack"]),
    ("normal", "2", "IncreasedAttackSpeed", 1, "of Skill", "技巧之", "(5—7)% increased Attack Speed", "增加(5—7)%攻擊速度", ["attack", "speed"]),
    ("normal", "2", "IncreasedAttackSpeed", 37, "of Mastery", "精通之", "(17—19)% increased Attack Speed", "增加(17—19)%攻擊速度", ["attack", "speed"]),
    ("normal", "2", "Dexterity", 1, "of the Mongoose", "貓鼬之", "+(5—8) to Dexterity", "+(5—8)點敏捷", ["attribute"]),
    ("desecrated", "1", "IncreasedAttackAreaOfEffect", 65, "Amanamu's", "阿馬納姆的", "(12—23)% increased Area of Effect for Attacks", "增加(12—23)%攻擊範圍效果", ["attack"]),
    ("corrupted", "5", "LocalAttributeRequirements", 1, None, None, "(10—20)% reduced Attribute Requirements", "減少(10—20)%屬性需求", []),
]
SOCKETABLES = [("Lesser_Desert_Rune", "Lesser Desert Rune", "低階沙漠符文", "Adds 4 to 6 Fire Damage", "附加4至6火焰傷害")]
GENERATION_NAMES = {"en": {"1": "Prefix", "2": "Suffix"}, "zh-tw": {"1": "前綴", "2": "後綴"}}

ARMOUR_BASES = [
    {"slug": "Golden_Mantle", "en": "Golden Mantle", "zh": "黃金斗篷", "level": 1, "dex": 0,
     "props": [("Armour", "護甲", "10"), ("Evasion Rating", "閃避值", "10"), ("Energy Shield", "能量護盾", "5")], "implicit": None},
    {"slug": "Rusted_Cuirass", "en": "Rusted Cuirass", "zh": "鏽蝕胸甲", "level": 1, "dex": 0,
     "props": [("Armour", "護甲", "45")], "implicit": None},
]
ARMOUR_MODS = [
    ("normal", "1", "BaseLocalDefences", 1, "Shining", "閃耀的", "+(10—15) to maximum Energy Shield", "+(10—15)最大能量護盾", ["defences"]),
    ("normal", "2", "FireResistance", 1, "of the Whelpling", "幼龍之", "+(6—10)% to Fire Resistance", "+(6—10)%火焰抗性", ["fire", "resistance"]),
]


def _base_card(base: dict, lang: str) -> str:
    zh = lang == "zh-tw"
    props = "".join(f'<div class="property">{(z if zh else e)}: <span class="colourDefault">{v}</span></div>'
                    for e, z, v in base["props"])
    attribute = f', <span class="colourDefault">{base["dex"]} {"敏捷" if zh else "Dex"}</span>' if base["dex"] else ""
    req = (f'<div class="requirements">{"需求" if zh else "Requires"}:  '
           f'<span class="colourDefault">{"等級" if zh else "Level"} {base["level"]}</span>{attribute}</div>')
    implicit = f'<div class="implicitMod">{base["implicit"][1 if zh else 0]}</div>' if base["implicit"] else ""
    if base.get("effect"):
        implicit = f'<div class="utilityMod">{base["effect"][1 if zh else 0]}</div>' + implicit
    return (f'<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0"><a class="whiteitem Bow" '
            f'href="{base["slug"]}"><img/></a></div><div class="flex-grow-1 ms-2"><a class="whiteitem Bow" href="{base["slug"]}">'
            f'{base["zh" if zh else "en"]}</a><div>{props}<div class="separator"></div>{req}{implicit}</div></div></div></div>')


def _unique_card(unique: dict, lang: str) -> str:
    zh = lang == "zh-tw"
    path = "tw" if zh else "us"
    mods = "".join(f'<div class="explicitMod"><span class="mod-value">{(z if zh else e)}</span></div>' for e, z in unique["mods"])
    return (f'<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0"><a class="UniqueItems UniqueItem" '
            f'href="{unique["slug"]}"><img/></a></div><div class="flex-grow-1 ms-2"><div><a class="UniqueItem" href="/{path}/{unique["slug"]}">'
            f'<span class="uniqueName">{unique["zh" if zh else "en"]}</span> <span class="uniqueTypeLine">{unique["base"][1 if zh else 0]}</span>'
            f'</a></div><div class="requirements">{"需求" if zh else "Requires"}:  <span class="colourDefault">{"等級" if zh else "Level"} '
            f'{unique["level"]}</span>, <span class="colourDefault">{unique["dex"]} {"敏捷" if zh else "Dex"}</span></div>{mods}</div></div></div>')


def mod_object(lang: str, mods: list[tuple], label: tuple[str, str], socketables: list[tuple] = ()) -> dict:
    zh = lang == "zh-tw"
    obj: dict = {"baseitem": {"link_name": f'<a class="ItemClasses" href="x">{label[1] if zh else label[0]}</a>'},
                 "gen": GENERATION_NAMES[lang], "opt": {}, "config": {}}
    for group in ("normal", "desecrated", "corrupted", "essence", "perfect_essence", "socketable", "bonded"):
        obj[group] = []
    for group, gen, family, level, name_en, name_zh, text_en, text_zh, tags in mods:
        name = name_zh if zh else name_en
        obj[group].append({"Name": name or "", "Level": str(level), "ModGenerationTypeID": gen, "ModFamilyList": [family],
                           "DropChance": "1000", "str": f"<span class='mod-value'>{text_zh if zh else text_en}</span>",
                           "mod_no": [f'<span class="badge" data-tag="{t}">{t}</span>' for t in tags]})
    for slug, name_en, name_zh, text_en, text_zh in socketables:
        obj["socketable"].append({"type": "socketable", "Level": 1, "ModGenerationTypeID": 0, "mod_no": [],
                                  "Name": f'<a class="whiteitem SoulCore" href="{slug}">{name_zh if zh else name_en}</a>',
                                  "ModFamilyList": [slug.replace("Lesser_", "")], "str": text_zh if zh else text_en})
    return obj


def _tab(pane_id: str, title: str, count: int | None) -> str:
    suffix = f" /{count}" if count is not None else ""
    return f'<li><a class="nav-link" href="#{pane_id}">{title}{suffix}</a></li>'


def class_page(lang: str, *, bases: list[dict] = (), uniques: list[dict] = (), mods: list[tuple] | None = None,
               label: tuple[str, str] = ("Bows", "弓"), socketables: list[tuple] = (), base_count: int | None = None,
               unique_count: int | None = None, title: tuple[str, str] | None = None) -> str:
    """One class page. base_count / unique_count override the number shown in the tab title."""
    zh = lang == "zh-tw"
    unique_id, base_id = ("弓傳奇", "弓物品") if zh else ("BowsUnique", "BowsItem")
    tabs, panes = [], []
    if uniques:
        tabs.append(_tab(unique_id, "傳奇" if zh else "Unique", len(uniques) if unique_count is None else unique_count))
        panes.append(f'<div class="tab-pane" id="{unique_id}"><div class="card"><div class="row">'
                     f'{"".join(_unique_card(u, lang) for u in uniques)}</div></div></div>')
    if bases:
        tabs.append(_tab(base_id, "物品" if zh else "Item", len(bases) if base_count is None else base_count))
        panes.append(f'<div class="tab-pane" id="{base_id}"><div class="card"><div class="row">'
                     f'{"".join(_base_card(b, lang) for b in bases)}</div></div></div>')
    script = ""
    if mods is not None:
        tabs.append(_tab("ModifiersCalc", "Modifiers Calc", None))
        panes.append('<div class="tab-pane" id="ModifiersCalc"></div>')
        script = f"<script>new ModsView({json.dumps(mod_object(lang, mods, label, socketables), ensure_ascii=False)});</script>"
    name = title or label
    title = f"{name[1]} - 流亡2編年史, Path of Exile Wiki tw" if zh else f"{name[0]} - PoE2DB, Path of Exile Wiki us"
    return (f'<html><head><title>{title}</title></head><body><ul class="nav">{"".join(tabs)}</ul>'
            f'<div class="tab-content">{"".join(panes)}</div>{script}</body></html>')


def item_spec(pages: list[dict] | None = None, **expect) -> Spec:
    """The real catalog with only the given pages and lowered minimums."""
    raw = copy.deepcopy(load_spec().raw)
    raw["sources"]["item_pages"]["pages"] = pages or [
        {"slug": "Bows", "group": "two_hand_weapon", "roles": ["items", "mods"]},
        {"slug": "Body_Armours", "group": "armour", "roles": ["items"]},
        {"slug": "Body_Armours_str_dex_int", "group": "armour", "roles": ["mods"]},
    ]
    raw["sources"]["item_pages"]["expect_min"] = {"pages": 1, "bases": 1, "uniques": 1, "modifiers": 1, "zh_ratio": 0.5,
                                                  **expect}
    return Spec(raw)


def site_pages() -> dict[str, str]:
    """{url: html} for the three pages of item_spec()."""
    pages = {}
    for lang, path in (("en", "us"), ("zh-tw", "tw")):
        pages[f"https://poe2db.tw/{path}/Bows"] = class_page(lang, bases=BOW_BASES, uniques=BOW_UNIQUES, mods=BOW_MODS,
                                                             socketables=SOCKETABLES)
        pages[f"https://poe2db.tw/{path}/Body_Armours"] = class_page(lang, bases=ARMOUR_BASES, label=("Body Armours", "胸甲"))
        pages[f"https://poe2db.tw/{path}/Body_Armours_str_dex_int"] = class_page(
            lang, bases=ARMOUR_BASES[:1], mods=ARMOUR_MODS, label=("Body Armours", "胸甲"))
    return pages


class ItemSite:
    """Fake poe2db for the item pages, with a request log."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = site_pages() if pages is None else pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.pages:
            import requests
            raise requests.ConnectionError(f"no fixture for {url}")
        return self.pages[url]


def write_item_data(base) -> dict:
    """Collect the synthetic site and write data/items/* under `base`, the way the collector does."""
    from src.scrapers import collect_items
    spec = item_spec()
    records, _ = collect_items.collect(spec, ItemSite())
    collect_items.write_records(spec, base / "data", records)
    return records
