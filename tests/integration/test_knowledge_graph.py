import json

import networkx as nx
import pytest

from src.catalog.spec import load_spec
from src.kg import build_graph as bg
from src.kg.build_graph import build_knowledge_graph, graph_summary, load_graph, save_graph
from src.scrapers.common import read_jsonl, write_jsonl
from tests.kg_support import EXPECTED_EDGE_TYPES, write_data_dir

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture
def data_dir(tmp_path, spec):
    return write_data_dir(tmp_path, spec)


@pytest.fixture
def graph(spec, data_dir):
    return build_knowledge_graph(spec, data_dir)


def edges_of(g, type_):
    return [(u, v, d) for u, v, d in g.edges(data=True) if d["type"] == type_]


def test_summary_counts(graph):
    summary = graph_summary(graph)
    assert summary["edge_types"] == EXPECTED_EDGE_TYPES
    assert summary["node_types"] == {"keyword": 14, "passive": 8, "family": 8, "gem": 6, "class": 3,
                                     "weapon": 2, "ascendancy": 1}
    assert summary["nodes"] == 42 and summary["edges"] == sum(EXPECTED_EDGE_TYPES.values())


def test_every_node_has_a_type(graph):
    assert all("type" in d for _, d in graph.nodes(data=True))


def test_supports_direction_support_to_skill(graph):
    pairs = {(u, v) for u, v, _ in edges_of(graph, "SUPPORTS")}
    assert pairs == {("gem:Added_Fire_Damage", "gem:Leap_Slam"), ("gem:Faster_Attacks", "gem:Leap_Slam"),
                     ("gem:Added_Fire_Damage", "gem:Unearth")}
    assert "gem:Ghost_Support" not in graph  # unknown supporter is skipped, not dangling


def test_supported_by_attribute_is_consumed(graph):
    assert all("supported_by" not in d for _, d in graph.nodes(data=True))


def test_gemcutting_edges_and_attrs(graph):
    cut = {(u, v): d for u, v, d in edges_of(graph, "GEMCUTTING")}
    assert set(cut) == {("class:Witch", "gem:Unearth"), ("class:Witch", "gem:Contagion"),
                        ("class:Warrior", "gem:Leap_Slam"), ("class:Witch", "gem:Herald_of_Ash")}
    assert cut[("class:Witch", "gem:Unearth")]["tier"] == 1 and cut[("class:Witch", "gem:Unearth")]["group"] == "Occult"
    assert cut[("class:Warrior", "gem:Leap_Slam")] == {"type": "GEMCUTTING", "tier": 7, "group": "Brawler"}
    assert cut[("class:Witch", "gem:Herald_of_Ash")]["tier"] == 4


def test_gives_stat_edges_and_attrs(graph):
    stats = [(u, v, d) for u, v, d in edges_of(graph, "GIVES_STAT")]
    attack_speed = [e for e in stats if e[1] == "family:attack speed"]
    assert len(attack_speed) == 1
    u, _, d = attack_speed[0]
    assert u == "passive:5" and d["kind"] == "increased" and d["value"] == 12.0 and d["text"] == "12% increased Attack Speed"
    cold = {u: d for u, v, d in stats if v == "family:cold damage"}
    assert set(cold) == {"passive:3", "passive:4"} and cold["passive:4"]["value"] == 8.0
    assert graph.nodes["family:cold damage"] == {"type": "family", "name": "cold damage", "parent": "cold damage",
                                                 "name_zh_tw": "冰冷傷害增加 #%"}
    spirit = [d for u, v, d in stats if v == "family:spirit"]
    assert spirit[0]["kind"] == "flat" and spirit[0]["value"] == 10.0


def test_adjacent_edges_keep_kind(graph):
    adj = {(u, v): d["kind"] for u, v, d in edges_of(graph, "ADJACENT")}
    assert adj[("passive:5", "passive:10")] == adj[("passive:10", "passive:5")] == "bridge"
    assert adj[("passive:10", "passive:11")] == adj[("passive:11", "passive:10")] == "ascendancy"
    assert adj[("passive:1", "passive:2")] == adj[("passive:2", "passive:1")] == "tree"
    assert len(adj) == 12  # six tree connections, each in both directions


def test_class_start_and_ascendancy_edges(graph):
    assert {(u, v) for u, v, _ in edges_of(graph, "STARTS_AT")} == {("class:Witch", "passive:1"), ("class:Sorceress", "passive:1")}
    assert {(u, v) for u, v, _ in edges_of(graph, "IN_ASCENDANCY")} == {
        ("passive:10", "ascendancy:Infernalist"), ("passive:11", "ascendancy:Infernalist")}


def test_mentions_edges_from_gems_passives_and_keywords(graph):
    mentions = {(u, v) for u, v, _ in edges_of(graph, "MENTIONS")}
    assert ("gem:Leap_Slam", "keyword:Stun") in mentions and ("gem:Leap_Slam", "keyword:Armour") in mentions
    assert ("passive:2", "keyword:Chaos_Damage") in mentions
    assert ("passive:Black_Scythe_Training", "keyword:Armour") in mentions
    assert ("keyword:Stun", "keyword:Freeze") in mentions and ("keyword:Critical_Hits", "keyword:Stun") in mentions


def test_has_tag_and_requires_weapon(graph):
    tags = {(u, v) for u, v, _ in edges_of(graph, "HAS_TAG")}
    assert ("gem:Leap_Slam", "keyword:Attacks") in tags and ("gem:Added_Fire_Damage", "keyword:Support") in tags
    weapons = {(u, v) for u, v, _ in edges_of(graph, "REQUIRES_WEAPON")}
    assert weapons == {("gem:Leap_Slam", "weapon:One Hand Maces"), ("gem:Herald_of_Ash", "weapon:Any Martial Weapon")}


def test_node_attributes_carry_urls_and_names(graph):
    gem = graph.nodes["gem:Leap_Slam"]
    assert gem["type"] == "gem" and gem["kinds"] == ["skill_gem"] and gem["tier"] == 7
    assert gem["url_en"] == "https://poe2db.tw/us/Leap_Slam" and gem["url_zh_tw"] == "https://poe2db.tw/tw/Leap_Slam"
    passive = graph.nodes["passive:3"]
    assert passive["name"] == "Heart of Ice" and passive["name_zh_tw"] == "冰之心" and passive["slug"] == "Heart_of_Ice"
    assert graph.nodes["passive:Black_Scythe_Training"]["timeless"] is True
    kw = graph.nodes["keyword:Critical_Hits"]
    assert (kw["name"], kw["name_zh_tw"]) == ("Critical Hit", "暴擊")
    assert graph.nodes["keyword:Attacks"] == {"type": "keyword", "slug": "Attacks"}  # tag-only keyword stub


@pytest.mark.parametrize("rel", ["kg/keywords.jsonl", "kg/passive_stats.jsonl", "passive_tree/passive_edges.jsonl",
                                 "passive_tree/passive_nodes.jsonl", "skill_gems/Skill_Gems_Detail.jsonl",
                                 "spirit_gems/Spirit_Gems_SpiritGemsGemcutting.jsonl"])
def test_missing_input_file_raises(spec, data_dir, rel):
    (data_dir / rel).unlink()
    with pytest.raises(FileNotFoundError, match="input missing"):
        build_knowledge_graph(spec, data_dir)


def test_min_counts_guard(spec, data_dir):
    g = build_knowledge_graph(spec, data_dir, min_counts={"gem": 6, "passive": 8})  # exactly met
    assert graph_summary(g)["node_types"]["gem"] == 6
    with pytest.raises(ValueError, match="too small") as err:
        build_knowledge_graph(spec, data_dir, min_counts={"gem": 7, "passive": 8, "keyword": 99})
    assert "'gem': 6" in str(err.value) and "'keyword': 14" in str(err.value) and "'passive'" not in str(err.value).split("minimums")[0]


def test_min_counts_missing_type_counts_as_zero(spec, data_dir):
    with pytest.raises(ValueError, match="'nonexistent': 0"):
        build_knowledge_graph(spec, data_dir, min_counts={"nonexistent": 1})


def test_untyped_node_raises_value_error(spec, data_dir):
    rows = read_jsonl(data_dir / "kg" / "passive_stats.jsonl")
    rows[0]["node_id"] = "no-such-node"
    write_jsonl(data_dir / "kg" / "passive_stats.jsonl", rows)
    with pytest.raises(ValueError, match="no type"):
        build_knowledge_graph(spec, data_dir)


def test_dangling_edge_endpoint_raises(spec, data_dir):
    edges = read_jsonl(data_dir / "passive_tree" / "passive_edges.jsonl") + [{"from": "1", "to": "404", "kind": "tree"}]
    write_jsonl(data_dir / "passive_tree" / "passive_edges.jsonl", edges)
    with pytest.raises(ValueError, match="passive:404"):
        build_knowledge_graph(spec, data_dir)


def test_save_load_roundtrip(graph, tmp_path):
    pkl, gml = tmp_path / "out" / "g.json", tmp_path / "out" / "g.graphml"
    save_graph(graph, pkl, gml)
    loaded = load_graph(pkl)
    assert graph_summary(loaded) == graph_summary(graph)
    assert loaded.nodes["gem:Leap_Slam"] == graph.nodes["gem:Leap_Slam"]
    assert sorted(loaded.edges(data=True), key=repr) == sorted(graph.edges(data=True), key=repr)
    assert loaded.is_multigraph() and loaded.is_directed()


def test_saved_graph_is_plain_json_not_pickle(graph, tmp_path):
    path = tmp_path / "g.json"
    save_graph(graph, path, None)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {n["id"] for n in data["nodes"]} == set(graph.nodes)
    assert len(data["edges"]) == graph.number_of_edges()
    assert "冰之心" in path.read_text(encoding="utf-8")                 # ensure_ascii=False
    assert not list(tmp_path.glob("*.tmp"))                            # atomic write leaves no temp file


def test_save_overwrites_existing_file_atomically(graph, tmp_path):
    path = tmp_path / "g.json"
    path.write_text("{}", encoding="utf-8")
    save_graph(graph, path, None)
    assert graph_summary(load_graph(path)) == graph_summary(graph)

def test_graphml_written_and_loadable(graph, tmp_path):
    pkl, gml = tmp_path / "g.json", tmp_path / "g.graphml"
    save_graph(graph, pkl, gml)
    g2 = nx.read_graphml(gml)
    assert g2.number_of_nodes() == graph.number_of_nodes() and g2.number_of_edges() == graph.number_of_edges()
    assert g2.nodes["passive:3"]["name_zh_tw"] == "冰之心"
    assert "supported_by" not in g2.nodes["gem:Leap_Slam"]


def test_save_without_graphml(graph, tmp_path):
    save_graph(graph, tmp_path / "g.json", None)
    assert (tmp_path / "g.json").exists() and not (tmp_path / "g.graphml").exists()


def test_graphml_safe_drops_none_and_encodes_collections():
    g = nx.MultiDiGraph()
    g.add_node("a", type="x", name=None, tags=["é", "b"], meta={"k": 1}, n=3)
    g.add_node("b", type="x")
    g.add_edge("a", "b", type="E", note=None, items=[1, 2])
    safe = bg._graphml_safe(g)
    assert safe.nodes["a"] == {"type": "x", "tags": '["é", "b"]', "meta": '{"k": 1}', "n": 3}
    assert list(safe.edges(data=True))[0][2] == {"type": "E", "items": "[1, 2]"}
    assert g.nodes["a"]["name"] is None  # input untouched


@pytest.fixture
def small_minimums(monkeypatch):
    monkeypatch.setattr(bg, "MIN_COUNTS", {"gem": 6, "passive": 8})


def test_main_builds_and_writes(tmp_path, data_dir, capsys, small_minimums):
    out = tmp_path / "idx" / "kg.json"
    assert bg.main(["--data-dir", str(data_dir), "--out", str(out)]) == 0
    assert out.exists() and out.with_suffix(".graphml").exists()
    assert "edges: 56" in capsys.readouterr().out
    assert bg.main(["--data-dir", str(data_dir), "--out", str(tmp_path / "x.json"), "--no-graphml"]) == 0
    assert not (tmp_path / "x.graphml").exists()


def test_main_refuses_partial_graph_with_real_minimums(tmp_path, data_dir, capsys):
    out = tmp_path / "o.json"
    assert bg.main(["--data-dir", str(data_dir), "--out", str(out)]) == 1   # tiny synthetic graph < MIN_COUNTS
    assert "too small" in capsys.readouterr().err and not out.exists()


def test_main_returns_1_on_missing_input(tmp_path, data_dir, capsys, small_minimums):
    (data_dir / "kg" / "keywords.jsonl").unlink()
    assert bg.main(["--data-dir", str(data_dir), "--out", str(tmp_path / "o.json")]) == 1
    assert "input missing" in capsys.readouterr().err


def test_main_returns_1_on_untyped_nodes(tmp_path, data_dir, capsys, small_minimums):
    rows = read_jsonl(data_dir / "kg" / "passive_stats.jsonl")
    rows[0]["node_id"] = "ghost"
    write_jsonl(data_dir / "kg" / "passive_stats.jsonl", rows)
    assert bg.main(["--data-dir", str(data_dir), "--out", str(tmp_path / "o.json")]) == 1
    assert "[ERROR]" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


def test_gem_listed_in_two_files_gets_both_kinds(spec, data_dir):
    spirit = data_dir / "spirit_gems" / "Spirit_Gems_Detail.jsonl"
    rows = read_jsonl(spirit)
    skill_copy = dict(rows[0], kind="skill_gem")
    write_jsonl(data_dir / "skill_gems" / "Skill_Gems_Detail.jsonl",
                read_jsonl(data_dir / "skill_gems" / "Skill_Gems_Detail.jsonl") + [skill_copy])
    g = build_knowledge_graph(spec, data_dir)
    assert g.nodes["gem:Herald_of_Ash"]["kinds"] == ["skill_gem", "spirit_gem"]


# -- zh-TW names on class / ascendancy / family / weapon nodes ------------------------------------------

def test_class_and_ascendancy_nodes_get_chinese_names(graph):
    assert graph.nodes["class:Witch"]["name_zh_tw"] == "女巫"
    assert graph.nodes["class:Sorceress"]["name_zh_tw"] == "女術者"
    assert graph.nodes["class:Warrior"]["name_zh_tw"] == "戰士"          # known only through the gemcutting table
    assert graph.nodes["ascendancy:Infernalist"]["name_zh_tw"] == "獄火師"


def test_family_nodes_get_a_chinese_name_only_when_a_template_exists(graph):
    assert graph.nodes["family:attack speed"]["name_zh_tw"] == "增加 #% 攻擊速度"
    assert "name_zh_tw" not in graph.nodes["family:armour"]             # no Chinese line anywhere for this family


def test_weapon_node_takes_its_chinese_name_from_the_glossary(spec, data_dir):
    path = data_dir / "kg" / "keywords.jsonl"
    rows = read_jsonl(path)
    rows.append({**rows[0], "slug": "One_Hand_Maces", "name_en": "one hand maces", "name_zh_tw": "單手錘", "see_also": []})
    write_jsonl(path, rows)
    g = build_knowledge_graph(spec, data_dir)
    assert g.nodes["weapon:One Hand Maces"]["name_zh_tw"] == "單手錘"   # matched ignoring case
    assert "name_zh_tw" not in g.nodes["weapon:Any Martial Weapon"]      # no glossary entry: stays English


def test_summary_counts_chinese_names_per_type(graph):
    with_zh = graph_summary(graph)["with_name_zh_tw"]
    assert with_zh["class"] == 3 and with_zh["ascendancy"] == 1 and with_zh["passive"] == 4


def test_graph_builds_without_classes_or_families_files(spec, data_dir, capsys):
    (data_dir / "passive_tree" / "classes.json").unlink()
    (data_dir / "kg" / "stat_families.json").unlink()
    g = build_knowledge_graph(spec, data_dir)
    assert "name_zh_tw" not in g.nodes["class:Witch"] and "name_zh_tw" not in g.nodes["family:attack speed"]
    assert "classes.json missing" in capsys.readouterr().err
    assert graph_summary(g)["nodes"] == 42
