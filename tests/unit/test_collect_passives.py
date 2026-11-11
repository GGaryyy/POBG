import json
import math

import pytest
import requests

from src.catalog.spec import load_spec
from src.scrapers import collect_passives as cp
from src.scrapers.collect_passives import (PassiveBuildError, attach_cards, join_wrapped, node_position, node_type,
                                           tree_edges, tree_nodes, validate)
from src.scrapers.common import read_jsonl
from src.scrapers.passive_listing import parse_passive_listing
from tests.support import fixture_text, mini_spec, mini_tree, mini_tree_data

pytestmark = pytest.mark.unit

VERSION = "0_5"


def load_cards(spec):
    out = {}
    for lang, suffix in (("en", "en"), ("zh-tw", "zh")):
        cards = {}
        for source, stem in (("passive_keystones", "keystone"), ("passive_notables", "notable")):
            text = fixture_text("html", f"passive_{stem}_cards_{suffix}.html")
            for card in parse_passive_listing(text, spec, source, lang):
                cards.setdefault(card.slug, card)
        out[lang] = cards
    return out


@pytest.fixture
def tree():
    return mini_tree()


@pytest.fixture
def nodes(tree):
    return tree_nodes(tree, VERSION)


# -- node_type ----------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ({"classesStart": ["Witch"]}, "ClassStart"),
    ({"ascendancyName": "Infernalist"}, "Ascendancy"),
    ({"ascendancyName": "Infernalist", "isNotable": True}, "Ascendancy"),
    ({"isKeystone": True}, "Keystone"),
    ({"isNotable": True}, "Notable"),
    ({"isJewelSocket": True}, "JewelSocket"),
    ({"isAttribute": True}, "Attribute"),
    ({}, "Small"),
    ({"ascendancyName": ""}, "Small"),
    ({"classesStart": [], "isKeystone": True}, "ClassStart"),  # key presence wins
])
def test_node_type(raw, expected):
    assert node_type(raw) == expected


# -- node_position --------------------------------------------------------------

def test_node_position_hand_computed(tree):
    # group 1 = (100, 200); orbit 2 radius 162, index 1 angle pi/6 -> dx = 162*0.5, dy = -162*cos(pi/6)
    pos = node_position(tree, {"group": 1, "orbit": 2, "orbitIndex": 1})
    assert pos == {"x": 181.0, "y": round(200 - 162 * math.sqrt(3) / 2, 2)}
    assert pos["y"] == 59.7


def test_node_position_orbit_zero_and_quarter_turns(tree):
    assert node_position(tree, {"group": 1, "orbit": 0, "orbitIndex": 0}) == {"x": 100.0, "y": 200.0}
    assert node_position(tree, {"group": 1, "orbit": 1, "orbitIndex": 1}) == {"x": 182.0, "y": 200.0}
    assert node_position(tree, {"group": 1, "orbit": 1, "orbitIndex": 2}) == {"x": 100.0, "y": 282.0}
    assert node_position(tree, {"group": 2, "orbit": 1}) == {"x": 1000.0, "y": -82.0}  # defaults to index 0


@pytest.mark.parametrize("node", [{}, {"group": 0}, {"group": 4}, {"group": 99}, {"group": -1}, {"group": None}])
def test_node_position_missing_group(tree, node):
    assert node_position(tree, node) is None


def test_node_position_group_ids_are_one_based(tree):
    # group 1 is groups[0] (100, 200); group 3 is groups[2] (-500, 300)
    assert node_position(tree, {"group": 1, "orbit": 0}) == {"x": 100.0, "y": 200.0}
    assert node_position(tree, {"group": 3, "orbit": 0}) == {"x": -500.0, "y": 300.0}


def test_node_position_null_group_entry(tree):
    tree["groups"][1] = None
    assert node_position(tree, {"group": 2, "orbit": 0}) is None


def test_every_mini_tree_node_listed_in_its_group(tree):
    for raw in tree["nodes"].values():
        assert raw["skill"] in tree["groups"][raw["group"] - 1]["nodes"], raw["skill"]


# -- join_wrapped -----------------------------------------------------------------

def test_join_wrapped():
    assert join_wrapped(["Minions deal 20% increased", "damage while on Full Life", "+5 to Strength"]) == [
        "Minions deal 20% increased damage while on Full Life", "+5 to Strength"]


def test_join_wrapped_collapses_blanks_and_whitespace():
    assert join_wrapped(["  a   b ", "", "   ", "Next"]) == ["a b", "Next"]
    assert join_wrapped([]) == []
    assert join_wrapped(["lower first line"]) == ["lower first line"]  # nothing to attach to


def test_join_wrapped_digit_start_is_not_continuation():
    assert join_wrapped(["Gain", "10% more"]) == ["Gain", "10% more"]


# -- tree_nodes ------------------------------------------------------------------------

def test_tree_nodes_drops_image_only_and_keeps_rest(nodes):
    assert set(nodes) == {str(i) for i in range(1, 13)}  # 13 = isOnlyImage mastery


def test_tree_nodes_schema_and_values(nodes):
    key = nodes["2"]
    assert key == {
        "id": "2", "name": "Chaos Inoculation", "type": "Keystone",
        "stats": ["Maximum Life is 1", "Immune to Chaos Damage"], "ascendancy": None, "class_start": [],
        "is_ascendancy_start": False, "is_notable": False, "position": {"x": 182.0, "y": 200.0},
        "neighbors": [], "slug": None, "url_en": None, "url_zh_tw": None, "name_zh_tw": None,
        "stats_zh_tw": [], "zh_source": None, "unlock_ascendancy": None, "keyword_slugs": [], "timeless": False,
        "stats_source": "pob2", "pob2_tree_version": VERSION}


def test_tree_nodes_class_start_filtered_to_tree_classes(nodes):
    assert nodes["1"]["class_start"] == ["Witch", "Sorceress"]
    assert nodes["1"]["type"] == "ClassStart"


def test_tree_nodes_types_and_flags(nodes):
    types = {i: n["type"] for i, n in nodes.items()}
    assert types == {"1": "ClassStart", "2": "Keystone", "3": "Notable", "4": "Notable", "5": "Notable",
                     "6": "Small", "7": "Small", "8": "Attribute", "9": "JewelSocket",
                     "10": "Ascendancy", "11": "Ascendancy", "12": "Ascendancy"}
    assert nodes["10"]["is_ascendancy_start"] is True and nodes["11"]["is_ascendancy_start"] is False
    assert nodes["11"]["is_notable"] is True and nodes["12"]["is_notable"] is False
    assert nodes["11"]["ascendancy"] == "Infernalist"


def test_tree_nodes_wrapped_stat_joined(nodes):
    assert nodes["7"]["stats"] == ["Minions deal 20% increased damage while on Full Life"]


def test_tree_nodes_newlines_inside_a_stat_replaced():
    tree = {"classes": [], "constants": {"orbitRadii": [0], "orbitAnglesByOrbit": [[0]]}, "groups": [None],
            "nodes": {"1": {"skill": 1, "name": "x", "stats": ["first half\nsecond half"]}}}
    assert tree_nodes(tree, VERSION)["1"]["stats"] == ["first half second half"]


def test_tree_nodes_skips_entries_without_skill(tree):
    tree["nodes"]["99"] = {"name": "No skill id"}
    assert "99" not in tree_nodes(tree, VERSION)


def test_tree_nodes_uses_skill_not_dict_key(tree):
    tree["nodes"]["alt"] = {"skill": 500, "name": "Keyed oddly"}
    assert tree_nodes(tree, VERSION)["500"]["name"] == "Keyed oddly"


# -- tree_edges -------------------------------------------------------------------------

def test_tree_edges_dedupe_and_kinds(tree, nodes):
    edges, _ = tree_edges(tree, nodes)
    pairs = {frozenset((e["from"], e["to"])): e["kind"] for e in edges}
    assert len(edges) == len(pairs) == 11  # 1<->2 listed in both directions, stored once
    assert frozenset(("1", "2")) in pairs
    assert pairs[frozenset(("10", "11"))] == pairs[frozenset(("11", "12"))] == "ascendancy"
    assert pairs[frozenset(("6", "10"))] == "bridge"
    assert [k for k in pairs.values()].count("tree") == 8


def test_tree_edges_drop_removed_nodes(tree, nodes):
    edges, dropped = tree_edges(tree, nodes)
    assert dropped == 1  # only 3 -> 13 (mastery); 13's own connections are not walked
    assert all("13" not in (e["from"], e["to"]) for e in edges)  # mastery 13 <-> 3 removed
    assert all(e["from"] in nodes and e["to"] in nodes for e in edges)


def test_tree_edges_ignore_self_loops_and_unknown_targets(tree, nodes):
    tree["nodes"]["9"]["connections"] = [{"id": 9}, {"id": 4242}]
    edges, dropped = tree_edges(tree, nodes)
    assert dropped == 2  # 3 -> 13 and 9 -> 4242; the self-loop is ignored but not counted
    assert not any(e["from"] == e["to"] for e in edges)
    assert not any("4242" in (e["from"], e["to"]) for e in edges)
    assert len(edges) == 11


def test_edge_direction_follows_first_declaration(tree, nodes):
    edge = next(e for e in tree_edges(tree, nodes)[0] if {e["from"], e["to"]} == {"1", "2"})
    assert (edge["from"], edge["to"]) == ("1", "2")


# -- attach_cards ----------------------------------------------------------------------------

@pytest.fixture
def joined(nodes):
    spec = mini_spec()
    cards = load_cards(spec)
    stats = attach_cards(nodes, cards, spec)
    return nodes, stats, spec


def test_attach_cards_statistics(joined):
    _, stats, _ = joined
    assert stats == {"cards_matched": 4, "cards_unmatched": 1, "ambiguous_names": 1,
                     "named_tree_nodes": 5, "named_with_page": 4}


def test_attach_cards_keystone_fields(joined):
    node = joined[0]["2"]
    assert node["slug"] == "Chaos_Inoculation"
    assert node["url_en"] == "https://poe2db.tw/us/Chaos_Inoculation"
    assert node["url_zh_tw"] == "https://poe2db.tw/tw/Chaos_Inoculation"
    assert node["name_zh_tw"] == "混沌禁錮"
    assert node["stats"] == ["Maximum Life is 1", "Immune to Chaos Damage"]
    assert node["stats_zh_tw"] == ["最大生命 1", "免疫混沌傷害"]
    assert node["keyword_slugs"] == ["Chaos_Damage"]
    assert node["stats_source"] == "poe2db"


def test_attach_cards_same_name_only_best_matching_node_gets_the_card(joined):
    nodes = joined[0]
    # node 3 shares the card's numbers (20, 10); node 5 (only "20% increased Cold Damage") does not
    assert nodes["3"]["slug"] == "Heart_of_Ice"
    assert nodes["3"]["stats"] == ["20% increased Cold Damage", "10% increased Spell Damage", "Poe2db extra line"]
    assert nodes["5"]["slug"] is None and nodes["5"]["url_en"] is None
    assert nodes["5"]["stats"] == ["20% increased Cold Damage"] and nodes["5"]["stats_source"] == "pob2"
    assert nodes["5"]["name_zh_tw"] is None


def test_attach_cards_ambiguity_picks_other_node_when_its_stats_fit(nodes):
    spec = mini_spec()
    cards = load_cards(spec)
    nodes["5"]["stats"] = ["20% increased Cold Damage", "10% increased Spell Damage"]
    nodes["3"]["stats"] = ["99% increased Something Else"]
    stats = attach_cards(nodes, cards, spec)
    assert nodes["5"]["slug"] == "Heart_of_Ice" and nodes["3"]["slug"] is None
    assert stats["ambiguous_names"] == 1


def test_attach_cards_matches_ascendancy_notable_but_not_small(joined):
    nodes = joined[0]
    assert nodes["11"]["slug"] == "Beidats_Will" and nodes["11"]["stats_source"] == "poe2db"
    assert nodes["12"]["slug"] is None and nodes["12"]["stats_source"] == "pob2"
    assert nodes["10"]["slug"] is None  # ascendancy start: neither keystone nor notable


def test_attach_cards_leaves_other_nodes_untouched(joined):
    nodes = joined[0]
    for nid in ("1", "6", "7", "8", "9"):
        assert nodes[nid]["slug"] is None and nodes[nid]["stats_source"] == "pob2" and nodes[nid]["name_zh_tw"] is None


def test_attach_cards_adds_timeless_node_with_slug_id(joined):
    nodes = joined[0]
    tl = nodes["Black_Scythe_Training"]
    assert tl["id"] == "Black_Scythe_Training" and tl["timeless"] is True
    assert tl["type"] == "Keystone" and tl["position"] is None and tl["pob2_tree_version"] is None
    assert tl["name_zh_tw"] == "黑鐮訓練" and tl["slug"] == "Black_Scythe_Training"
    assert tl["stats_source"] == "poe2db" and tl["is_notable"] is False
    assert tl["keyword_slugs"] == ["Armour", "Chaos_Damage"]
    assert len(nodes) == 13


def test_attach_cards_unmatched_card_adds_nothing(joined):
    nodes = joined[0]
    assert not any(n["name"] == "Unknown Keystone" for n in nodes.values())


def test_attach_cards_without_zh_card(nodes):
    spec = mini_spec()
    cards = load_cards(spec)
    cards["zh-tw"] = {}
    attach_cards(nodes, cards, spec)
    assert nodes["2"]["slug"] == "Chaos_Inoculation"
    assert nodes["2"]["name_zh_tw"] is None and nodes["2"]["stats_zh_tw"] == []


def test_attach_cards_card_without_stats_keeps_pob2_stats(nodes):
    spec = mini_spec()
    cards = load_cards(spec)
    cards["en"]["Chaos_Inoculation"].stats = []
    attach_cards(nodes, cards, spec)
    assert nodes["2"]["stats"] == ["Maximum Life is 1", "Immune to Chaos Damage"]
    assert nodes["2"]["stats_source"] == "pob2" and nodes["2"]["slug"] == "Chaos_Inoculation"


# -- validate ---------------------------------------------------------------------------------

def built(spec):
    nodes = tree_nodes(mini_tree(), VERSION)
    edges, _ = tree_edges(mini_tree(), nodes)
    cp.attach_tree_text(nodes, mini_tree_data())
    join = attach_cards(nodes, load_cards(spec), spec)
    return nodes, edges, join


def test_validate_passes_on_lowered_spec():
    spec = mini_spec()
    nodes, edges, join = built(spec)
    assert validate(nodes, edges, join, spec) == {
        "nodes": 13, "keystones": 1, "notables": 4, "class_starts": 1, "ascendancy_starts": 1,
        "poe2db_name_match_ratio": 0.8, "zh_names": 9, "zh_name_ratio": 0.9, "zh_stat_nodes": 9,
        "nodes_with_stats": 9}


def test_validate_counts_exclude_timeless_nodes():
    spec = mini_spec(keystones=2)
    nodes, edges, join = built(spec)
    with pytest.raises(PassiveBuildError, match=r"keystones=1 < 2"):
        validate(nodes, edges, join, spec)


def test_validate_real_expectations_fail_listing_every_count():
    spec = load_spec()
    nodes, edges, join = built(spec)
    with pytest.raises(PassiveBuildError) as err:
        validate(nodes, edges, join, spec)
    msg = str(err.value)
    for part in ("nodes=13 < 4000", "keystones=1 < 30", "notables=4 < 1100", "class_starts=1 < 6",
                 "ascendancy_starts=1 < 20", "poe2db name match ratio 0.800 < 0.97"):
        assert part in msg
    assert msg.startswith("passive tree validation failed")


def test_validate_reports_dangling_edges():
    spec = mini_spec()
    nodes, edges, join = built(spec)
    edges.append({"from": "1", "to": "nope", "kind": "tree"})
    with pytest.raises(PassiveBuildError, match="1 dangling edges"):
        validate(nodes, edges, join, spec)


def test_validate_name_ratio_threshold():
    spec = mini_spec(poe2db_name_match_ratio=0.9)
    nodes, edges, join = built(spec)
    with pytest.raises(PassiveBuildError, match="ratio 0.800 < 0.9"):
        validate(nodes, edges, join, spec)


# -- build / main (offline) -----------------------------------------------------------------------

@pytest.fixture
def caches(tmp_path):
    pob2, pages = tmp_path / "cache" / "pob2", tmp_path / "cache" / "pages"
    pob2.mkdir(parents=True)
    pages.mkdir(parents=True)
    (pob2 / f"tree_{VERSION}.json").write_text(fixture_text("pob2", "tree_mini.json"), encoding="utf-8")
    for lang, suffix in (("en", "en"), ("zh-tw", "zh")):
        for page, stem in (("Keystone", "keystone"), ("Notable", "notable")):
            (pages / f"{lang}_{page}.html").write_text(
                fixture_text("html", f"passive_{stem}_cards_{suffix}.html"), encoding="utf-8")
    tree_data = tmp_path / "cache" / "poe2db_tree"
    tree_data.mkdir()
    for lang, short in (("en", "us"), ("zh-tw", "tw")):
        (tree_data / f"data_4.5_{lang}.json").write_text(
            fixture_text("poe2db_tree", f"data_{short}_mini.json"), encoding="utf-8")
    return pob2, pages


def tree_cache(pob2):
    return pob2.parent / "poe2db_tree"


def no_network(url):
    raise AssertionError(f"unexpected fetch {url}")


def test_build_offline_from_cache(caches):
    pob2, pages = caches
    nodes, edges, summary = cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=pob2, page_cache=pages,
                 tree_data_cache=tree_cache(pob2))
    by_id = {n["id"]: n for n in nodes}
    assert len(nodes) == 13 and len(edges) == 11
    assert by_id["6"]["neighbors"] == ["5", "7", "10"]  # edge order: 5-6, 6-7, 6-10
    assert by_id["9"]["neighbors"] == ["8"]
    assert summary["types"] == {"ClassStart": 1, "Keystone": 2, "Notable": 3, "Small": 2, "Attribute": 1,
                                "JewelSocket": 1, "Ascendancy": 3}
    assert summary["edge_kinds"] == {"tree": 8, "bridge": 1, "ascendancy": 2}
    assert summary["cards_matched"] == 4 and summary["ambiguous_names"] == 1 and summary["built_at"]
    assert summary["connections_dropped"] == 1


def test_build_fetches_and_caches_when_online(tmp_path):
    spec = mini_spec()
    urls = []
    pages = {spec.resolve_url("Keystone", "en"): "passive_keystone_cards_en.html",
             spec.resolve_url("Notable", "en"): "passive_notable_cards_en.html",
             spec.resolve_url("Keystone", "zh-tw"): "passive_keystone_cards_zh.html",
             spec.resolve_url("Notable", "zh-tw"): "passive_notable_cards_zh.html"}
    tree_url = spec.source("pob2_tree")["url"].format(version=VERSION)

    data_urls = {"https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json": "data_us_mini.json",
                 "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json": "data_tw_mini.json"}

    def fetch(url):
        urls.append(url)
        if url in data_urls:
            return fixture_text("poe2db_tree", data_urls[url])
        return fixture_text("pob2", "tree_mini.json") if url == tree_url else fixture_text("html", pages[url])

    kwargs = dict(pob2_cache=tmp_path / "p", page_cache=tmp_path / "c", tree_data_cache=tmp_path / "t")
    cp.build(spec, fetch=fetch, **kwargs)
    assert len(urls) == 7 and tree_url in urls and set(data_urls) <= set(urls)
    assert (tmp_path / "t" / "data_4.5_zh-tw.json").exists()
    cp.build(spec, fetch=no_network, offline=True, **kwargs)  # second run served from the cache
    assert (tmp_path / "p" / f"tree_{VERSION}.json").exists() and (tmp_path / "c" / "en_Keystone.html").exists()


def test_build_offline_empty_cache_raises(tmp_path):
    with pytest.raises(PassiveBuildError, match="not cached and --offline"):
        cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=tmp_path / "a", page_cache=tmp_path / "b",
                 tree_data_cache=tmp_path / "c")


def test_build_missing_listing_cache_raises(caches):
    pob2, pages = caches
    (pages / "zh-tw_Notable.html").unlink()
    with pytest.raises(PassiveBuildError, match="listing page zh-tw/Notable"):
        cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=pob2, page_cache=pages,
                 tree_data_cache=tree_cache(pob2))


def test_build_invalid_tree_json_raises(caches):
    pob2, pages = caches
    (pob2 / f"tree_{VERSION}.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PassiveBuildError, match="not valid JSON"):
        cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=pob2, page_cache=pages,
                 tree_data_cache=tree_cache(pob2))


def patch_main(monkeypatch, spec, pob2, pages):
    real_build = cp.build
    monkeypatch.setattr(cp, "load_spec", lambda: spec)
    monkeypatch.setattr(cp, "TREE_DATA_CACHE_DIR", tree_cache(pob2))
    monkeypatch.setattr(cp, "build", lambda s, fetch, offline=False, tree_data=None: real_build(
        s, fetch=fetch, offline=offline, pob2_cache=pob2, page_cache=pages, tree_data=tree_data))


def test_main_offline_writes_files(monkeypatch, caches, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(), *caches)
    out = tmp_path / "out"
    assert cp.main(["--offline", "--out-dir", str(out)]) == 0
    nodes = read_jsonl(out / "passive_tree" / "passive_nodes.jsonl")
    edges = read_jsonl(out / "passive_tree" / "passive_edges.jsonl")
    assert len(nodes) == 13 and len(edges) == 11
    assert {n["id"] for n in nodes} >= {"1", "Black_Scythe_Training"}
    assert next(n for n in nodes if n["id"] == "2")["name_zh_tw"] == "混沌禁錮"
    assert "混沌禁錮" in (out / "passive_tree" / "passive_nodes.jsonl").read_text(encoding="utf-8")  # not \u-escaped
    stdout = capsys.readouterr().out
    assert "=== collect_passives summary ===" in stdout and "wrote:" in stdout


def test_main_offline_empty_cache_exits_1(monkeypatch, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(), tmp_path / "a", tmp_path / "b")
    out = tmp_path / "out"
    assert cp.main(["--offline", "--out-dir", str(out)]) == 1
    assert "[ERROR]" in capsys.readouterr().err
    assert not out.exists()  # nothing overwritten


def test_main_validation_failure_exits_1_and_writes_nothing(monkeypatch, caches, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(nodes=4000, keystones=30), *caches)  # real-sized thresholds: mini tree must fail
    out = tmp_path / "out"
    assert cp.main(["--offline", "--out-dir", str(out)]) == 1
    assert "validation failed" in capsys.readouterr().err
    assert not out.exists()


def test_main_schema_change_exits_1(monkeypatch, caches, tmp_path, capsys):
    pob2, pages = caches
    (pob2 / f"tree_{VERSION}.json").write_text("{}", encoding="utf-8")  # valid JSON, wrong shape
    patch_main(monkeypatch, mini_spec(), pob2, pages)
    assert cp.main(["--offline", "--out-dir", str(tmp_path / "out")]) == 1
    assert "schema changed" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_main_network_error_exits_1(monkeypatch, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(), tmp_path / "a", tmp_path / "b")

    def boom(url, delay=0.0):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(cp, "fetch_html", boom)
    assert cp.main(["--out-dir", str(tmp_path / "out")]) == 1
    assert "down" in capsys.readouterr().err


# -- poe2db tree data (zh-TW text) --------------------------------------------------------------------

@pytest.fixture
def texted(nodes):
    stats = cp.attach_tree_text(nodes, mini_tree_data())
    return nodes, stats


def test_attach_tree_text_statistics(texted):
    _, stats = texted
    # node 10: poe2db calls the ascendancy start "Altered Flesh"; node 11: one extra Chinese line
    assert stats == {"tree_text_missing": 0, "tree_text_name_mismatch": 1, "stat_lines_unaligned": 1}


def test_attach_tree_text_fills_names_and_aligned_stats(texted):
    nodes, _ = texted
    assert nodes["8"]["name_zh_tw"] == "屬性" and nodes["8"]["stats_zh_tw"] == ["+5 任意屬性"]
    assert nodes["8"]["zh_source"] == cp.ZH_FROM_TREE_DATA
    assert nodes["12"]["name_zh_tw"] == "昇華小點" and nodes["12"]["stats_zh_tw"] == ["增加 5% 精魂"]
    assert nodes["2"]["stats_zh_tw"] == ["最大生命為 1", "免疫混沌傷害"]       # keyword markup removed


def test_attach_tree_text_name_match_ignores_case_and_markup(texted):
    nodes, _ = texted
    assert nodes["1"]["name"] == "WITCH" and nodes["1"]["name_zh_tw"] == "女巫"
    assert nodes["9"]["name_zh_tw"] == "珠寶插槽"


def test_attach_tree_text_wrapped_lines_follow_the_english_grouping(texted):
    nodes, _ = texted
    assert nodes["7"]["stats"] == ["Minions deal 20% increased damage while on Full Life"]
    assert nodes["7"]["stats_zh_tw"] == ["召喚物在滿血時造成的傷害增加 20%"]
    assert nodes["7"]["name_zh_tw"] is None and nodes["7"]["zh_source"] == cp.ZH_FROM_TREE_DATA  # nameless node


def test_attach_tree_text_skips_a_node_whose_english_name_differs(texted):
    nodes, _ = texted
    assert nodes["10"]["name_zh_tw"] is None and nodes["10"]["stats_zh_tw"] == [] and nodes["10"]["zh_source"] is None


def test_attach_tree_text_unaligned_lines_keep_the_name_only(texted):
    nodes, _ = texted
    assert nodes["11"]["name_zh_tw"] == "貝達特的意志" and nodes["11"]["stats_zh_tw"] == []


def test_attach_tree_text_node_missing_from_one_language(nodes):
    data = mini_tree_data()
    del data["zh-tw"]["nodes"]["8"]
    stats = cp.attach_tree_text(nodes, data)
    assert stats["tree_text_missing"] == 1 and nodes["8"]["name_zh_tw"] is None


def test_listing_card_wins_over_tree_data(texted):
    nodes, _ = texted
    spec = mini_spec()
    attach_cards(nodes, load_cards(spec), spec)
    assert nodes["2"]["name_zh_tw"] == "混沌禁錮" and nodes["2"]["zh_source"] == cp.ZH_FROM_PAGE   # card, not 異靈之體
    assert nodes["8"]["name_zh_tw"] == "屬性" and nodes["8"]["zh_source"] == cp.ZH_FROM_TREE_DATA  # no card: unchanged


def test_card_without_zh_drops_tree_lines_that_no_longer_align(texted):
    nodes, _ = texted
    spec = mini_spec()
    cards = load_cards(spec)
    slug = next(s for s, c in cards["en"].items() if c.name == "Chaos Inoculation")
    cards["en"][slug].stats.append("One more English line")
    cards["zh-tw"].pop(slug)
    attach_cards(nodes, cards, spec)
    assert len(nodes["2"]["stats"]) == 3 and nodes["2"]["stats_zh_tw"] == []
    assert nodes["2"]["name_zh_tw"] == "異靈之體"                       # the tree-data name is still right


def test_validate_fails_below_the_zh_name_ratio():
    spec = mini_spec(zh_name_ratio=0.95)
    nodes, edges, join = built(spec)
    with pytest.raises(PassiveBuildError, match=r"zh-TW name ratio 0\.900 < 0\.95"):
        validate(nodes, edges, join, spec)


def test_classes_doc_keeps_only_classes_that_start_on_the_tree(nodes):
    doc = cp.classes_doc(mini_tree_data(), list(nodes.values()), "2026-11-11T00:00:00+00:00")
    assert doc["version"] == "4.5" and doc["fetched_at"] == "2026-11-11T00:00:00+00:00"
    assert doc["source_url"] == "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json"
    assert [(c["name"], c["name_zh_tw"]) for c in doc["classes"]] == [("Witch", "女巫"), ("Sorceress", "女術者")]
    assert doc["classes"][1]["ascendancies"] == [{"id": "Sorceress1", "name": "Stormweaver", "name_zh_tw": "風暴編織者"}]


def test_load_tree_data_offline_without_cache(tmp_path):
    with pytest.raises(PassiveBuildError, match="poe2db tree data 4.5/en is not cached and --offline"):
        cp.load_tree_data(mini_spec(), fetch=no_network, cache_dir=tmp_path, offline=True)


def test_load_tree_data_rejects_bad_json_and_short_files(caches):
    cache = tree_cache(caches[0])
    with pytest.raises(PassiveBuildError, match="has 13 nodes < 4500"):
        cp.load_tree_data(mini_spec(tree_data_nodes=4500), fetch=no_network, cache_dir=cache, offline=True)
    (cache / "data_4.5_zh-tw.json").write_text("<html>not found</html>", encoding="utf-8")
    with pytest.raises(PassiveBuildError, match="4.5/zh-tw is not valid JSON"):
        cp.load_tree_data(mini_spec(), fetch=no_network, cache_dir=cache, offline=True)
    (cache / "data_4.5_zh-tw.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(PassiveBuildError, match="has 0 nodes"):
        cp.load_tree_data(mini_spec(), fetch=no_network, cache_dir=cache, offline=True)


def test_load_tree_data_version_override_changes_url_and_cache_name(tmp_path):
    seen = []

    def fetch(url):
        seen.append(url)
        return fixture_text("poe2db_tree", "data_tw_mini.json" if url.endswith("_tw.json") else "data_us_mini.json")

    data = cp.load_tree_data(mini_spec(), fetch=fetch, cache_dir=tmp_path, version="4.6")
    assert seen == ["https://poe2db.tw/data/passive-skill-tree/4.6/data_us.json",
                    "https://poe2db.tw/data/passive-skill-tree/4.6/data_tw.json"]
    assert data["version"] == "4.6" and (tmp_path / "data_4.6_en.json").exists()


def test_build_summary_reports_zh_coverage(caches):
    pob2, pages = caches
    nodes, _, summary = cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=pob2, page_cache=pages,
                                 tree_data_cache=tree_cache(pob2))
    assert summary["zh_names"] == 9 and summary["zh_name_ratio"] == 0.9
    assert summary["tree_text_name_mismatch"] == 1 and summary["stat_lines_unaligned"] == 1
    assert summary["zh_sources"] == {"poe2db_tree_data": 7, "poe2db_page": 5, "none": 1}  # none: node 10
    assert {n["id"]: n["zh_source"] for n in nodes}["6"] == cp.ZH_FROM_TREE_DATA


def test_main_writes_classes_json(monkeypatch, caches, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(), *caches)
    out = tmp_path / "out"
    assert cp.main(["--offline", "--out-dir", str(out)]) == 0
    doc = json.loads((out / "passive_tree" / "classes.json").read_text(encoding="utf-8"))
    assert [c["name_zh_tw"] for c in doc["classes"]] == ["女巫", "女術者"]
    assert "女巫" in (out / "passive_tree" / "classes.json").read_text(encoding="utf-8")   # not \u-escaped
    stdout = capsys.readouterr().out
    assert "classes: 2" in stdout and "ascendancies: 3" in stdout and "classes.json" in stdout


def test_main_low_zh_coverage_writes_nothing(monkeypatch, caches, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(zh_name_ratio=0.99), *caches)
    out = tmp_path / "out"
    assert cp.main(["--offline", "--out-dir", str(out)]) == 1
    assert "zh-TW name ratio" in capsys.readouterr().err and not out.exists()


def test_main_offline_without_tree_data_cache_exits_1(monkeypatch, caches, tmp_path, capsys):
    patch_main(monkeypatch, mini_spec(), *caches)
    monkeypatch.setattr(cp, "TREE_DATA_CACHE_DIR", tmp_path / "empty")
    assert cp.main(["--offline", "--out-dir", str(tmp_path / "out")]) == 1
    assert "poe2db tree data" in capsys.readouterr().err and not (tmp_path / "out").exists()


# -- unlock constraints and point budgets -------------------------------------------------------------

def test_unlock_ascendancy_is_read_from_the_pob2_constraint(tree):
    tree["nodes"]["6"]["unlockConstraint"] = {"ascendancy": "Oracle", "nodes": [5571]}
    tree["nodes"]["8"]["unlockConstraint"] = {"nodes": [1, 2]}            # another shape: no ascendancy
    nodes = tree_nodes(tree, VERSION)
    assert nodes["6"]["unlock_ascendancy"] == "Oracle"
    assert nodes["8"]["unlock_ascendancy"] is None and nodes["2"]["unlock_ascendancy"] is None


def test_build_summary_counts_unlock_constraints(caches):
    pob2, pages = caches
    raw = json.loads((pob2 / f"tree_{VERSION}.json").read_text(encoding="utf-8"))
    raw["nodes"]["6"]["unlockConstraint"] = {"ascendancy": "Oracle", "nodes": [5571]}
    raw["nodes"]["8"]["unlockConstraint"] = {"nodes": [1, 2]}
    (pob2 / f"tree_{VERSION}.json").write_text(json.dumps(raw), encoding="utf-8")
    _, _, summary = cp.build(mini_spec(), fetch=no_network, offline=True, pob2_cache=pob2, page_cache=pages,
                             tree_data_cache=tree_cache(pob2))
    assert summary["unlock_ascendancy"] == {"Oracle": 1} and summary["unlock_other"] == 1


def test_classes_doc_carries_the_point_budgets(nodes):
    data = mini_tree_data()
    data["en"]["points"] = {"totalPoints": 123, "ascendancyPoints": 8}
    assert cp.classes_doc(data, list(nodes.values()), "t")["points"] == {"passive": 123, "ascendancy": 8}
    assert cp.classes_doc(mini_tree_data(), list(nodes.values()), "t")["points"] == {"passive": None, "ascendancy": None}
