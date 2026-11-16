"""
campaign_support.py — A synthetic poe2db campaign site (Act pages in two languages, the gem and
Jeweller's Orb pages) and PoB quest rewards, in the shape the real pages have (checked 2026-11-14),
plus a helper that collects it into <base>/data/campaign the way the collector does.

Acts: Act 1 and Act 2 are stages; Act 5 has no areas (a datamined act, not a stage); Act 6 holds the
Interlude page's areas, so it is named Interlude. Stage levels: Act 1 = 12 (its town is 15 and does
not count), Act 2 = 28, Interlude = 41.
"""

from __future__ import annotations

import copy
from pathlib import Path

from src.catalog.spec import Spec, load_spec

# ---------------------------------------------------------------------------
# PAGE PARTS
# ---------------------------------------------------------------------------

BOSS_ICON = '<img src="https://cdn.poe2db.tw/image/Art/WorldMapContentBoss.webp"/>'
CHEST_ICON = '<img src="https://cdn.poe2db.tw/image/Art/WorldMapContentChest.webp"/>'
MONSTER_HOVER = "https://cdn.poe2db.tw/cache2/us/Poe_Data_MonsterVarieties_hover/abc"


def area_row(slug: str, name: str, level: str, *, town: bool = False, waypoint: bool = False,
             bosses: tuple = (), extra: tuple = ()) -> str:
    """One row of an Act page's area table. bosses: (name, slug, grants or "")."""
    icons = ('<img alt="town24" src="town24.webp"/>' if town else "") + \
            ('<img alt="waypoint24" src="waypoint24.webp"/>' if waypoint else "")
    links = " · ".join(f'<a data-hover="{MONSTER_HOVER}" href="/us/{s}">{n}</a>' for n, s, _ in bosses if s)
    blocks = "".join(f'<div class=""><span>{BOSS_ICON}<span class="UniqueItem">{n}</span></span>'
                     + (f'<span class="explicitMod">( {g} )</span>' if g else "") + "</div>"
                     for n, _, g in bosses)
    blocks += "".join(f'<div class=""><span>{CHEST_ICON} {text}</span></div>' for text in extra)
    return (f'<tr><td><a class="WorldAreas" href="{slug}">{name}</a></td><td>{level} {icons}<br/></td>'
            f"<td>{links}<br/>{blocks}</td></tr>")


def quest_entry(slug: str, name: str, kind: str, act: str, reward: str | None, objective: str | None,
                reward_label: str = "Reward:") -> str:
    reward_html = f'<div class="property">{reward_label} <span>{reward}</span></div>' if reward else ""
    objective_html = f'<div class="implicitMod">{objective}</div>' if objective else ""
    return (f'<div class="col"><div class="d-flex"><div class="flex-shrink-0"><a class="Quest" href="{slug}">'
            f'<img alt="icon"/></a></div><div class="flex-grow-1"><div><a class="Quest" href="{slug}">{name}</a></div>'
            f'<div class="property">{kind}</div><div class="property">{act}</div>{reward_html}'
            f'<div class="separator"></div>{objective_html}</div></div></div>')


def act_map(rows: list[list[str]]) -> str:
    """rows of cells: "" (empty), an arrow, or "Slug|Name|1 / 45" for an area."""
    out = []
    for row in rows:
        cells = []
        for cell in row:
            if "|" in cell:
                slug, name, levels = cell.split("|")
                cells.append(f'<td style="border: 1px solid grey;"><a href="/us/{slug}">{name}</a><br/>{levels}</td>')
            else:
                cells.append(f"<td>{cell}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    return '<table class="actmap"><tbody>' + "".join(out) + "</tbody></table>"


def act_page(title: str, area_header: str, quest_header: str, rows: list[str], quests: list[str],
             mark: str = "") -> str:
    area_card = (f'<div class="card"><h5 class="card-header">{area_header} /{len(rows)}</h5>'
                 f'<table><thead><tr><th>Name</th><th>Level</th><th>Boss</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div>')
    quest_card = (f'<div class="card"><h5 class="card-header">{quest_header} /{len(quests)}</h5>'
                  f'<div class="row">{"".join(quests)}</div></div>') if quest_header else ""
    audio = '<div class="card"><h5 class="card-header">Text Audio /1</h5><table><tbody></tbody></table></div>'
    wiki = (f'<div class="card"><div class="card-body markdown-body"><div id="markContent"><h1>{title}</h1>'
            f"{mark}</div></div></div>")
    return f"<html><body>{area_card}{quest_card}{audio}{wiki}</body></html>"


# ---------------------------------------------------------------------------
# THE SITE
# ---------------------------------------------------------------------------

ACT1_ROWS = {
    "en": [area_row("Riverside", "Riverside", "1", bosses=(("Bloated One", "Bloated_One", ""),)),
           area_row("Camp", "Camp", "15", town=True, waypoint=True),
           area_row("Field", "Field", "2", waypoint=True,
                    bosses=(("Beira", "Beira", "+10 % to Cold Resistance"),), extra=("Mysterious Campsite",)),
           area_row("Field", "Field", "2"),                                      # repeated row: kept once
           area_row("Manor", "Manor", "12", bosses=(("Count", "Count", ""), ("Candle", "Candle", "+20 to maximum Life")))],
    "zh-tw": [area_row("Riverside", "河岸", "1", bosses=(("浮腫者", "Bloated_One", ""),)),
              area_row("Camp", "營地", "15", town=True, waypoint=True),
              area_row("Field", "原野", "2", waypoint=True, bosses=(("貝伊拉", "Beira", "+10 % 冰冷抗性"),)),
              area_row("Manor", "宅第", "12", bosses=(("伯爵", "Count", ""), ("燭光", "Candle", "+20 最大生命")))],
}
ACT1_QUESTS = {
    "en": [quest_entry("Reach_Camp", "Reach the Camp", "Normal", "Act 1", "Uncut Skill Gem (Level 1)",
                       "Find the Camp past Riverside."),
           quest_entry("Lost_Lute", "The Lost Lute", "Optional", "Act 1",
                       "Book of Specialisation , 2 Passive Skill Points", "Find the lute in the Field."),
           quest_entry("Secrets", "Secrets", "Normal", "Act 1", "Runed Spikes", "Search the Manor."),
           quest_entry("Secrets", "Secrets", "Normal", "Act 1", None, "Return to the Camp.")],
    "zh-tw": [quest_entry("Reach_Camp", "抵達營地", "主線", "第 1 章", "未切割的技能寶石（等級 1）", "穿過河岸尋找營地。",
                          "獎勵:"),
              quest_entry("Lost_Lute", "遺失的魯特琴", "支線", "第 1 章", "專精之書 , 2 點天賦點數", "在原野找到魯特琴。",
                          "獎勵:"),
              quest_entry("Secrets", "秘密", "主線", "第 1 章", "符文尖刺", "搜索宅第。", "獎勵:"),
              quest_entry("Secrets", "秘密", "主線", "第 1 章", None, "回到營地。", "獎勵:")],
}
ACT1_MAP = act_map([["", "Riverside|Riverside|1 / 45"], ["", "↕"], ["", "Camp|Camp|"], ["", "↕"],
                    ["", "Field|Field|2 / 45", "↔", "Manor|Manor|12 / 50"]])
ACT1_GUIDE = {
    "en": ("<h2>Riverside</h2><p>Riverside is where the game begins.</p><ul><li>Equip a weapon.</li></ul>"
           "<h2>Camp (Town) <img/></h2><p>The first town.</p>"),
    "zh-tw": "<h2>河岸</h2><p>遊戲從河岸開始。</p><h2>營地</h2><p>第一座城鎮。</p>",
}
ACT2_ROWS = {
    "en": [area_row("Desert", "Desert", "16", waypoint=True),
           area_row("Trial_of_the_Sekhemas", "Trial of the Sekhemas", "22<span>22</span>",   # a second number follows
                    bosses=(("Trial of Ascendancy", None, ""),)),
           area_row("Deshar", "Deshar", "28", bosses=(("Jamanra", "Jamanra", ""),))],
    "zh-tw": [area_row("Desert", "沙漠", "16"), area_row("Trial_of_the_Sekhemas", "絲克瑪試煉", "22"),
              area_row("Deshar", "戴斯哈", "28", bosses=(("賈馬拉", "Jamanra", ""),))],
}
ACT2_QUESTS = {
    "en": [quest_entry("Final_Letter", "The Final Letter", "Optional", "Act 2",
                       "Book of Specialisation , 2 Passive Skill Points", "Take the letter to Deshar.")],
    "zh-tw": [quest_entry("Final_Letter", "最後的信", "支線", "第 2 章", "專精之書 , 2 點天賦點數", "把信帶到戴斯哈。", "獎勵:")],
}
INTERLUDE_ROWS = {
    "en": [area_row("Refuge", "The Refuge", "64", town=True),
           area_row("Wolf_Hold", "Wolf Hold", "40", bosses=(("Oswin", "Oswin", ""),)),
           area_row("Peaks", "Kriar Peaks", "41", bosses=(("Lythara", "Lythara", ""),))],
    "zh-tw": [area_row("Refuge", "避難所", "64", town=True), area_row("Wolf_Hold", "狼之要塞", "40"),
              area_row("Peaks", "庫萊亞山峰", "41", bosses=(("萊塔拉", "Lythara", ""),))],
}
INTERLUDE_QUESTS = {
    "en": [quest_entry("Clearing_the_Way", "Clearing the Way", "Optional", "Act 6", "Book of Specialisation",
                       "Travel to Wolf Hold.")],
    "zh-tw": [quest_entry("Clearing_the_Way", "開闢道路", "支線", "第 6 章", "專精之書", "前往狼之要塞。", "獎勵:")],
}

QUEST_REWARDS = """\
return {
\t{
\t\t["Act"] = 1,
\t\t["Description"] = "Act 1",
\t\t["Area"] = "Field",
\t\t["Info"] = "Beira",
\t\t["Stat"] = "+10% to Cold Resistance",
\t\t["AreaLevel"] = 2,
\t\t["useConfig"] = true
\t},
\t{
\t\t["Act"] = 1,
\t\t["Description"] = "Act 1",
\t\t["Area"] = "field",
\t\t["Info"] = "Lute",
\t\t["Stat"] = "+2 Weapon Set Passive Skill Points",
\t\t["questPoints"] = 2,
\t\t["AreaLevel"] = 2,
\t\t["useConfig"] = false
\t},
\t{
\t\t["Act"] = 1,
\t\t["Description"] = "Act 1",
\t\t["Area"] = "The Manor",
\t\t["Info"] = "King",
\t\t["Stat"] = "+30 to Spirit",
\t\t["AreaLevel"] = 11,
\t\t["useConfig"] = true
\t},
\t{
\t\t["Act"] = 2,
\t\t["Description"] = "Act 2",
\t\t["Area"] = "Deshar",
\t\t["Info"] = "The Final Letter",
\t\t["Stat"] = "+2 Weapon Set Passive Skill Points",
\t\t["questPoints"] = 2,
\t\t["AreaLevel"] = 28,
\t\t["useConfig"] = false
\t},
\t{
\t\t["Act"] = 2,
\t\t["Description"] = "Act 2",
\t\t["Area"] = "Desert",
\t\t["Info"] = "Medallion",
\t\t["Options"] = {
\t\t\t"30% increased Charm Charges Gained\\n\\t+1 Charm Slot",
\t\t\t"30% increased Charm Effect Duration\\n\\t+1 Charm Slot",
\t\t},
\t\t["AreaLevel"] = 26,
\t\t["useConfig"] = true
\t},
\t{
\t\t["Act"] = 5,
\t\t["Description"] = "Interlude 3",
\t\t["Area"] = "Peaks",
\t\t["Info"] = "Lythara",
\t\t["Stat"] = "+40 to Spirit",
\t\t["AreaLevel"] = 61,
\t\t["useConfig"] = true
\t},
\t{
\t\t["Act"] = 6,
\t\t["Description"] = "Epilog",
\t\t["Area"] = "Camp",
\t\t["Info"] = "Siege",
\t\t["Stat"] = "+2 Weapon Set Passive Skill Points",
\t\t["questPoints"] = 2,
\t\t["AreaLevel"] = 62,
\t\t["useConfig"] = false
\t},
}
"""


def _table_card(header: str, heads: list[str], rows: list[list[str]]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    head = "".join(f"<th>{h}</th>" for h in heads)
    return (f'<div class="card"><h5 class="card-header">{header}</h5><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def item_page(name: str, drop_level: int, text: str) -> str:
    card = _table_card(f"{name} /6", ["Name", "Show Full Descriptions"],
                       [["DropLevel", str(drop_level)], ["BaseType", name]])
    return f'<html><body>{card}<div class="explicitMod">{text}</div></body></html>'


SKILL_GEM_PAGE = ("<html><body>"
                  + _table_card("Skill Gems Gemcutting /3", ["Weapon", "Tier", "Gems"],
                                [["Occult", "1", "Contagion"], ["Occult", "3", "Bone Cage"], ["Bow", "5", "Snipe"]])
                  + _table_card("Tier Level /6", ["Req Level", "Socket Number", "Skill Level"],
                                [["", "2", "1"], ["3", "", "2"], ["6", "", "3"], ["10", "", "4"], ["14", "", "5"],
                                 ["18", "", "6"]])
                  + "</body></html>")
SPIRIT_GEM_PAGE = ("<html><body>" + _table_card("Spirit Gems Gemcutting /1", ["Weapon", "Tier", "Gems"],
                                                [["Occult", "4", "Grim Feast"]]) + "</body></html>")
SUPPORT_LEVELS = {1: 1, 2: 16, 3: 33}
SUPPORT_LISTING = ("<html><body><div class='card'><h5 class='card-header'>Uncut Support Gems Item /3</h5>"
                   + "".join(f'<div class="col"><a href="Uncut_Support_Gem_%28Level_{n}%29"><img/></a>'
                             f'<a href="Uncut_Support_Gem_%28Level_{n}%29">Uncut Support Gem (Level {n})</a></div>'
                             for n in SUPPORT_LEVELS) + "</div></body></html>")
ORBS = {"Lesser_Jewellers_Orb": ("Lesser Jeweller's Orb", 25, 3), "Greater_Jewellers_Orb": ("Greater Jeweller's Orb", 45, 4),
        "Perfect_Jewellers_Orb": ("Perfect Jeweller's Orb", 65, 5)}
ACT_INDEX = ("<html><body><a href='/us/Act'>Act</a><a href='Act_1'>Act 1</a><a href='Act_2'>Act 2</a>"
             "<a href='Interlude_Curse'>Interlude: Curse</a><a href='Act_5'>Act 5</a><a href='Act_6'>Act 6</a>"
             "<a href='Act_1'>Act 1 again</a></body></html>")


def site_pages() -> dict[str, str]:
    """{url: html} for every page the collector reads."""
    spec = load_spec()
    pages: dict[str, str] = {}

    def put(slug: str, html: str, lang: str = "en") -> None:
        pages[spec.resolve_url(slug, lang)] = html

    put("Act", ACT_INDEX)
    for lang, title, header, quest_header in (("en", "Act 1", "Act 1 Area", "Act 1 Quest"),
                                              ("zh-tw", "第 1 章", "第 1 章 Area", "第 1 章 任務")):
        put("Act_1", act_page(title, header, quest_header, ACT1_ROWS[lang], ACT1_QUESTS[lang],
                              ACT1_MAP + ACT1_GUIDE[lang]), lang)
    for lang, title, header, quest_header in (("en", "Act 2", "Act 2 Area", "Act 2 Quest"),
                                              ("zh-tw", "第 2 章", "第 2 章 Area", "第 2 章 任務")):
        put("Act_2", act_page(title, header, quest_header, ACT2_ROWS[lang], ACT2_QUESTS[lang]), lang)
    put("Act_5", act_page("Act 5", "Act 5 Area", "Act 5 Quest", [], []))
    for lang, header, quest_header in (("en", "Act 6 Area", "Act 6 Quest"), ("zh-tw", "第 6 章 Area", "第 6 章 任務")):
        put("Act_6", act_page("Act 6" if lang == "en" else "第 6 章", header, quest_header, INTERLUDE_ROWS[lang],
                              INTERLUDE_QUESTS[lang]), lang)
    for lang, title in (("en", "Interludes"), ("zh-tw", "間歇")):
        put("Interlude", act_page(title, "Act 6 Area", "", INTERLUDE_ROWS[lang], []), lang)
    put("Uncut_Skill_Gem", SKILL_GEM_PAGE)
    put("Uncut_Spirit_Gem", SPIRIT_GEM_PAGE)
    put("Uncut_Support_Gems", SUPPORT_LISTING)
    for level, drop in SUPPORT_LEVELS.items():
        put(f"Uncut_Support_Gem_%28Level_{level}%29",
            item_page(f"Uncut Support Gem (Level {level})", drop, "Creates a Support Gem"))
    for slug, (name, drop, sockets) in ORBS.items():
        put(slug, item_page(name, drop, f"Sets a Skill Gem to have {sockets} Support Gem Sockets"))
    pages[spec.source("pob2_tree")["quest_rewards_url"]] = QUEST_REWARDS
    return pages


class CampaignSite:
    """A fetcher over the synthetic site that counts its requests."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages if pages is not None else site_pages()
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"the collector asked for an unknown page: {url}")
        return self.pages[url]


def campaign_spec(**expect) -> Spec:
    """The real catalog with minimums this small site meets (or the ones given)."""
    raw = copy.deepcopy(load_spec().raw)
    raw["sources"]["campaign"]["expect_min"] = {"stages": 3, "areas_per_stage": 3, "quests": 3,
                                                "skill_gem_levels": 6, "support_gem_levels": 3, **expect}
    return Spec(raw)


def write_campaign_data(base: Path, cache_dir: Path) -> dict:
    """Collect the synthetic site and write data/campaign/* under `base`, the way the collector does."""
    from src.scrapers import collect_campaign
    spec = campaign_spec()
    result = collect_campaign.collect(spec, fetch=CampaignSite(), cache_dir=cache_dir)
    collect_campaign.write(spec, base, result)
    return result
