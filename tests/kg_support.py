"""Synthetic data directory shared by the knowledge-graph / lookup integration tests.

Everything is hand-written; nothing is read from the real data/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import Spec, load_spec
from src.kg.build_graph import build_knowledge_graph, save_graph
from src.kg.stats import build_stat_index
from src.scrapers.common import write_jsonl
from src.scrapers.gem_detail import parse_detail
from tests.support import html

FETCHED = "2026-01-01T00:00:00+00:00"
ZH_NAMES = {"Leap_Slam": "躍擊", "Unearth": "掘屍", "Contagion": "傳染", "Herald_of_Ash": "灰燼信使",
            "Added_Fire_Damage": "附加火焰傷害", "Faster_Attacks": "快速攻擊",
            "Chaos_Inoculation": "混沌禁錮", "Heart_of_Ice": "冰之心", "Beidats_Will": "貝達之意"}
GRAPH_REL = Path("indexes") / "graph" / "knowledge_graph.json"
EXPECTED_EDGE_TYPES = {
    "ADJACENT": 12, "STARTS_AT": 2, "IN_ASCENDANCY": 2, "MENTIONS": 10, "HAS_TAG": 12,
    "REQUIRES_WEAPON": 2, "SUPPORTS": 3, "GEMCUTTING": 4, "GIVES_STAT": 9,
}


def gem(spec: Spec, slug: str, kind: str, **over) -> dict:
    """A detail record: the keyword fixture page parsed for `kind`, then overridden."""
    rec = parse_detail(html("detail_skill_keywords.html"), spec, slug, kind)
    rec.update(fetched_at=FETCHED, **over)
    return rec


def gem_records(spec: Spec) -> dict[str, list[dict]]:
    leap = gem(spec, "Leap_Slam", "skill_gem", tag_slugs=["Attacks", "Area_of_Effect_Skills"],
               attribute_colour="str", summary="Jump and slam")
    unearth = gem(spec, "Unearth", "skill_gem", name="Unearth", tier=1, tags=["Spell", "Minion"],
                  tag_slugs=["Spells", "Minions"], requires_weapons=None, keyword_slugs=["Minions"],
                  supported_by=["Added_Fire_Damage", "Ghost_Support"])
    contagion = gem(spec, "Contagion", "skill_gem", name="Contagion", tier=1, tags=["Spell", "Chaos"],
                    tag_slugs=["Spells", "Chaos"], requires_weapons=None, keyword_slugs=[], supported_by=[])
    herald = gem(spec, "Herald_of_Ash", "spirit_gem", name="Herald of Ash", tier=4, tags=["Spirit", "Fire"],
                 tag_slugs=["Persistent_Skills", "Fire"], requires_weapons=["Any Martial Weapon"],
                 keyword_slugs=[], supported_by=[])
    added = gem(spec, "Added_Fire_Damage", "support_gem", name="Added Fire Damage", tier=1,
                tags=["Support", "Fire"], tag_slugs=["Support", "Fire"], requires_weapons=None, keyword_slugs=[])
    faster = gem(spec, "Faster_Attacks", "support_gem", name="Faster Attacks", tier=2,
                 tags=["Support", "Attack"], tag_slugs=["Support", "Attacks"], requires_weapons=None, keyword_slugs=[])
    return {"skill_gem": [leap, unearth, contagion], "spirit_gem": [herald], "support_gem": [added, faster]}


def _passive(nid, name, type_, **over) -> dict:
    node = {"id": nid, "name": name, "type": type_, "stats": [], "ascendancy": None, "class_start": [],
            "is_ascendancy_start": False, "is_notable": type_ == "Notable", "position": {"x": 0.0, "y": 0.0},
            "neighbors": [], "slug": None, "url_en": None, "url_zh_tw": None, "name_zh_tw": None,
            "stats_zh_tw": [], "zh_source": None, "unlock_ascendancy": None, "keyword_slugs": [], "timeless": False,
            "stats_source": "pob2",
            "pob2_tree_version": "0_5", "fetched_at": FETCHED}
    node.update(over)
    if node["url_zh_tw"] and node["name_zh_tw"]:
        node["zh_source"] = "poe2db_page"
    return node


def _page(slug: str) -> dict:
    return {"slug": slug, "url_en": f"https://poe2db.tw/us/{slug}", "url_zh_tw": f"https://poe2db.tw/tw/{slug}",
            "stats_source": "poe2db"}


def passive_nodes() -> list[dict]:
    return [
        _passive("1", "WITCH", "ClassStart", class_start=["Witch", "Sorceress"], neighbors=["2"]),
        _passive("2", "Chaos Inoculation", "Keystone", stats=["Maximum Life is 1", "Immune to Chaos Damage"],
                 stats_zh_tw=["最大生命 1", "免疫混沌傷害"], name_zh_tw="混沌禁錮", keyword_slugs=["Chaos_Damage"],
                 neighbors=["1", "3"], **_page("Chaos_Inoculation")),
        _passive("3", "Heart of Ice", "Notable", stats=["20% increased Cold Damage", "10% increased Spell Damage"],
                 stats_zh_tw=["冰冷傷害增加 20%", "法術傷害增加 10%"], name_zh_tw="冰之心", keyword_slugs=["Cold_Damage"],
                 neighbors=["2", "4"], **_page("Heart_of_Ice")),
        _passive("4", "", "Small", stats=["8% increased Cold Damage"], neighbors=["3", "5"]),
        _passive("5", "Attack Speed", "Small", stats=["12% increased Attack Speed"], neighbors=["4", "10"],
                 name_zh_tw="攻擊速度", stats_zh_tw=["增加 12% 攻擊速度"], zh_source="poe2db_tree_data"),
        _passive("10", "Infernalist", "Ascendancy", ascendancy="Infernalist", is_ascendancy_start=True,
                 neighbors=["5", "11"]),
        _passive("11", "Beidat's Will", "Ascendancy", ascendancy="Infernalist", is_notable=True,
                 stats=["+10 to Spirit", "15% increased Spell Damage with Staves"],
                 stats_zh_tw=["+10 精魂", "持有長杖時法術傷害增加 15%"], name_zh_tw="貝達之意", neighbors=["10"],
                 **_page("Beidats_Will")),
        _passive("Black_Scythe_Training", "Black Scythe Training", "Keystone", timeless=True, position=None,
                 stats=["20% increased Armour"], keyword_slugs=["Armour"], pob2_tree_version=None,
                 **_page("Black_Scythe_Training")),
    ]


def passive_edges() -> list[dict]:
    return [{"from": "1", "to": "2", "kind": "tree"}, {"from": "2", "to": "3", "kind": "tree"},
            {"from": "3", "to": "4", "kind": "tree"}, {"from": "4", "to": "5", "kind": "tree"},
            {"from": "5", "to": "10", "kind": "bridge"}, {"from": "10", "to": "11", "kind": "ascendancy"}]


def keywords() -> list[dict]:
    def kw(slug, en, zh, text_en, text_zh, see_also=()):
        return {"slug": slug, "name_en": en, "name_zh_tw": zh, "text_en": text_en, "text_zh_tw": text_zh,
                "see_also": list(see_also), "url_en": f"https://poe2db.tw/us/{slug}",
                "url_zh_tw": f"https://poe2db.tw/tw/{slug}", "fetched_at": FETCHED}
    return [
        kw("Stun", "Stun", "暈眩", "Stunned enemies cannot act.", "被暈眩的敵人無法行動。", ["Freeze", "Critical_Hits"]),
        kw("Freeze", "Freeze", "冰凍", "Frozen enemies cannot act.", None),
        kw("Critical_Hits", "Critical Hit", "暴擊", "A Critical Hit deals extra damage.", "暴擊造成額外傷害。", ["Stun"]),
        kw("Chaos_Damage", "Chaos Damage", "混沌傷害", "Chaos Damage ignores Energy Shield.", "混沌傷害。"),
        kw("Cold_Damage", "Cold Damage", "冰冷傷害", "Cold Damage can Freeze.", "冰冷傷害可以冰凍。"),
        kw("Minions", "Minions", "召喚物", "Minions follow you.", None),
        kw("Armour", "Armour", "護甲", "Armour reduces Physical Damage.", None),
    ]


def gemcutting(spec: Spec) -> dict[str, list[dict]]:
    def row(cls, tier, slug, class_slug):
        return {"class_name": cls, "tier": tier, "gem_name": slug.replace("_", " "), "gem_slug": slug,
                "class_slug": class_slug}
    return {
        "skill": [row("Occult", 1, "Unearth", "Witch"), row("Occult", 1, "Contagion", "Witch"),
                  row("Brawler", 7, "Leap_Slam", "Warrior"),
                  row("Weapon Set", 3, "Leap_Slam", None),            # no class link: skipped
                  row("Occult", 1, "Ghost_Gem", "Witch")],            # gem not in the detail files: skipped
        "spirit": [row("Occult", 4, "Herald_of_Ash", "Witch")],
    }


def routing_tree() -> tuple[list[dict], list[dict]]:
    """A tree made for route tests (nodes, edges). Witch / Sorceress start at 100, Druid at 300.

        100 - 101 - 102 - 103 - 104 - 105 "Heart of Ice"        trunk, 5 points to 105
                           |
                          106 - 107 "Chaos Inoculation"          5 points from 100
        100 - 110 - 111 - 112 - 105                              side road, 4 points to 105
        300 - 301 - 103                                          Druid joins the trunk
        300 - 320 - 107                                          320 is Oracle-only: a shortcut
        130 "Lone Star"                                          connected to nothing
        100 = 140 - 141 - 142 "Beidat's Will"; 140 - 143 - 144   Infernalist tree
        100 = 150 - 151 "Sanguimancy"                            Blood Mage tree
        300 = 340 - 341 "Converging Paths"                       Oracle tree
    """
    asc = lambda name: {"ascendancy": name}  # noqa: E731
    nodes = [
        _passive("100", "WITCH", "ClassStart", class_start=["Witch", "Sorceress"]),
        _passive("101", "Intelligence", "Small", stats=["+5 to Intelligence"]),
        _passive("102", "Intelligence", "Small", stats=["+5 to Intelligence"]),
        _passive("103", "Cold Damage", "Small", stats=["10% increased Cold Damage"],
                 name_zh_tw="冰冷傷害", stats_zh_tw=["增加 10% 冰冷傷害"], zh_source="poe2db_tree_data"),
        _passive("104", "Cold Damage", "Small", stats=["8% increased Cold Damage"]),
        _passive("105", "Heart of Ice", "Notable", stats=["20% increased Cold Damage"],
                 stats_zh_tw=["增加 20% 冰冷傷害"], name_zh_tw="冰之心", **_page("Heart_of_Ice")),
        _passive("106", "Strength", "Small", stats=["+5 to Strength"]),
        _passive("107", "Chaos Inoculation", "Keystone", stats=["Maximum Life is 1", "Immune to Chaos Damage"],
                 stats_zh_tw=["最大生命 1", "免疫混沌傷害"], name_zh_tw="混沌禁錮", **_page("Chaos_Inoculation")),
        _passive("110", "Attack Speed", "Small", stats=["3% increased Attack Speed"]),
        _passive("111", "Attack Speed", "Small", stats=["3% increased Attack Speed"]),
        _passive("112", "Attack Speed", "Small", stats=["3% increased Attack Speed"]),
        _passive("130", "Lone Star", "Notable", stats=["5% increased Spirit"], name_zh_tw="孤星", **_page("Lone_Star")),
        _passive("140", "Infernalist", "Ascendancy", is_ascendancy_start=True, **asc("Infernalist")),
        _passive("141", "Spirit", "Ascendancy", stats=["5% increased Spirit"], **asc("Infernalist")),
        _passive("142", "Beidat's Will", "Ascendancy", is_notable=True, stats=["+10 to Spirit"], name_zh_tw="貝達之意",
                 **asc("Infernalist"), **_page("Beidats_Will")),
        _passive("143", "Life", "Ascendancy", stats=["3% increased maximum Life"], **asc("Infernalist")),
        _passive("144", "Altered Flesh", "Ascendancy", is_notable=True, stats=["20% increased Armour"],
                 **asc("Infernalist"), **_page("Altered_Flesh")),
        _passive("150", "Blood Mage", "Ascendancy", is_ascendancy_start=True, **asc("Blood Mage")),
        _passive("151", "Sanguimancy", "Ascendancy", is_notable=True, stats=["10% increased maximum Life"],
                 **asc("Blood Mage"), **_page("Sanguimancy")),
        _passive("300", "DRUID", "ClassStart", class_start=["Druid"]),
        _passive("301", "Dexterity", "Small", stats=["+5 to Dexterity"]),
        _passive("320", "Hidden Path", "Small", stats=["+5 to Dexterity"], unlock_ascendancy="Oracle"),
        _passive("340", "Oracle", "Ascendancy", is_ascendancy_start=True, **asc("Oracle")),
        _passive("341", "Converging Paths", "Ascendancy", is_notable=True, stats=["+10 to Spirit"],
                 **asc("Oracle"), **_page("Converging_Paths")),
    ]
    pairs = [("100", "101", "tree"), ("101", "102", "tree"), ("102", "103", "tree"), ("103", "104", "tree"),
             ("104", "105", "tree"), ("103", "106", "tree"), ("106", "107", "tree"), ("100", "110", "tree"),
             ("110", "111", "tree"), ("111", "112", "tree"), ("112", "105", "tree"), ("300", "301", "tree"),
             ("301", "103", "tree"), ("300", "320", "tree"), ("320", "107", "tree"),
             ("100", "140", "bridge"), ("140", "141", "ascendancy"), ("141", "142", "ascendancy"),
             ("140", "143", "ascendancy"), ("143", "144", "ascendancy"), ("100", "150", "bridge"),
             ("150", "151", "ascendancy"), ("300", "340", "bridge"), ("340", "341", "ascendancy")]
    by_id = {n["id"]: n for n in nodes}
    for a, b, _ in pairs:
        by_id[a]["neighbors"].append(b)
        by_id[b]["neighbors"].append(a)
    return nodes, [{"from": a, "to": b, "kind": kind} for a, b, kind in pairs]


def routing_classes_doc(passive: int = 123, ascendancy: int = 8) -> dict:
    doc = classes_doc()
    doc["points"] = {"passive": passive, "ascendancy": ascendancy}
    doc["classes"][0]["ascendancies"].append({"id": "Witch2", "name": "Blood Mage", "name_zh_tw": "血法師"})
    doc["classes"].append({"name": "Druid", "name_zh_tw": "德魯伊",
                           "ascendancies": [{"id": "Druid1", "name": "Oracle", "name_zh_tw": "天啟先知"}]})
    return doc


def write_data_dir(base: Path, spec: Spec | None = None, tree: tuple[list[dict], list[dict]] | None = None,
                   classes: dict | None = None) -> Path:
    """Create <base>/data with every file the graph builder and lookup service read."""
    spec = spec or load_spec()
    data = base / "data"
    records = gem_records(spec)
    for kind, recs in records.items():
        _, source = spec.source_for_kind(kind)
        write_jsonl(base / source["detail_file"], recs)
    cutting = gemcutting(spec)
    write_jsonl(base / spec.source("skill_gems_listing")["gemcutting_file"], cutting["skill"])
    write_jsonl(base / spec.source("spirit_gems_listing")["gemcutting_file"], cutting["spirit"])
    nodes, edges = tree or (passive_nodes(), passive_edges())
    write_jsonl(base / spec.source("pob2_tree")["nodes_file"], nodes)
    write_jsonl(base / spec.source("pob2_tree")["edges_file"], edges)
    write_jsonl(data / "kg" / "keywords.jsonl", keywords())
    rows, families = build_stat_index(nodes)
    write_jsonl(data / "kg" / "passive_stats.jsonl", rows)
    (data / "kg" / "stat_families.json").write_text(json.dumps(families, ensure_ascii=False), encoding="utf-8")
    classes_file = base / spec.source("passive_tree_data")["classes_file"]
    classes_file.write_text(json.dumps(classes or classes_doc(), ensure_ascii=False), encoding="utf-8")
    return data


def classes_doc() -> dict:
    def cls(name, zh, *ascendancies):
        return {"name": name, "name_zh_tw": zh,
                "ascendancies": [{"id": f"{name}{i}", "name": a, "name_zh_tw": a_zh}
                                 for i, (a, a_zh) in enumerate(ascendancies, 1)]}
    return {"version": "4.5", "source_url": "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json",
            "fetched_at": FETCHED, "points": {"passive": 123, "ascendancy": 8},
            "classes": [cls("Witch", "女巫", ("Infernalist", "獄火師")),
                        cls("Sorceress", "女術者", ("Stormweaver", "風暴編織者")),
                        cls("Warrior", "戰士", ("Titan", "泰坦"))]}


def build_full_environment(base: Path, spec: Spec | None = None, tree: tuple[list[dict], list[dict]] | None = None,
                           classes: dict | None = None) -> Path:
    """data dir + entity index + knowledge graph (JSON + graphml) under `base`."""
    spec = spec or load_spec()
    data = write_data_dir(base, spec, tree, classes)
    entities = build_entity_index(spec, data_dir=data, zh_names=ZH_NAMES, fetcher=_no_network)
    write_jsonl(data / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    graph = build_knowledge_graph(spec, data)
    save_graph(graph, base / GRAPH_REL, base / GRAPH_REL.with_suffix(".graphml"))
    return base


def _no_network(url):
    raise AssertionError(f"network must not be used: {url}")
