import json

import pytest

from src.catalog.entity_index import EntityIndex, build_entity_index
from src.catalog.spec import load_spec
from src.scrapers.common import write_jsonl

pytestmark = pytest.mark.unit


GEM_FILES = ("skill_gems/Skill_Gems_Detail.jsonl", "spirit_gems/Spirit_Gems_Detail.jsonl",
             "support_skill_gems/Support_Gems_Detail.jsonl")


def no_network(url):
    raise AssertionError(f"network must not be used: {url}")


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def write_nodes(tmp_path, nodes):
    data = tmp_path / "data"
    for rel in GEM_FILES:
        write_jsonl(data / rel, [])
    write_jsonl(data / "passive_tree" / "passive_nodes.jsonl", nodes)
    return data


def node(nid, name, type_, slug="__absent__", **extra):
    rec = {"id": nid, "name": name, "type": type_, **extra}
    if slug != "__absent__":
        rec["slug"] = slug
    return rec


def build(spec, data, zh=None):
    return build_entity_index(spec, data_dir=data, zh_names=zh or {}, fetcher=no_network, offline=False)


def test_slug_nodes_use_slug_without_network(spec, tmp_path):
    data = write_nodes(tmp_path, [
        node("101", "Chaos Inoculation", "Keystone", "Chaos_Inoculation", name_zh_tw="混沌禁錮"),
        node("102", "Heart of Ice", "Notable", "Heart_of_Ice"),
        node("103", "Beidat's Will", "Ascendancy", "Beidats_Will"),
    ])
    ents = {e.slug: e for e in build(spec, data, zh={"Heart_of_Ice": "冰之心"})}
    ci = ents["Chaos_Inoculation"]
    assert ci.kind == "passive_keystone" and ci.node_id == "101" and ci.record_key == {"id": "101"}
    assert ci.url_en == "https://poe2db.tw/us/Chaos_Inoculation" and ci.url_zh_tw == "https://poe2db.tw/tw/Chaos_Inoculation"
    assert ci.name_zh_tw == "混沌禁錮"                      # node's own zh name wins
    assert ents["Heart_of_Ice"].name_zh_tw == "冰之心"       # falls back to the zh_names map by slug
    assert ents["Beidats_Will"].kind == "passive_ascendancy"
    assert ci.record_file == "data/passive_tree/passive_nodes.jsonl"
    assert "chaosinoculation" in ci.aliases and "混沌禁錮" in ci.aliases


def test_one_entity_per_slug(spec, tmp_path):
    data = write_nodes(tmp_path, [
        node("5", "Heart of Ice", "Notable", "Heart_of_Ice"),
        node("3", "Heart of Ice", "Notable", "Heart_of_Ice"),
        node("9", "Other", "Notable", "Other"),
    ])
    ents = build(spec, data)
    assert [(e.slug, e.node_id) for e in ents] == [("Heart_of_Ice", "5"), ("Other", "9")]  # first node wins


def test_nodes_without_page_get_node_key_and_no_urls(spec, tmp_path):
    data = write_nodes(tmp_path, [
        node("11", "Asc Notable", "Ascendancy", None, is_notable=True),
        node("12", "Asc Start", "Ascendancy", None, is_ascendancy_start=True),
        node("13", "Small thing", "Small", None),         # not a named kind
        node("14", "", "Notable", "Nameless"),            # no name
    ])
    ents = build(spec, data)
    assert [e.slug for e in ents] == ["node_11", "node_12"]
    assert all(e.url_en is None and e.url_zh_tw is None for e in ents)


def test_ascendancy_small_nodes_are_not_indexed(spec, tmp_path):
    data = write_nodes(tmp_path, [
        node("20", "Life", "Ascendancy", None),                         # generic small node: skipped
        node("21", "Mana", "Ascendancy", None, is_notable=False),
        node("22", "Page Node", "Ascendancy", "Page_Node"),            # has a poe2db page: kept
        node("23", "Notable", "Ascendancy", None, is_notable=True),
        node("24", "Keystone", "Keystone", None),                      # filter only applies to ascendancy nodes
    ])
    assert sorted(e.slug for e in build(spec, data)) == ["Page_Node", "node_23", "node_24"]


def test_timeless_slug_ids_have_slug_key(spec, tmp_path):
    data = write_nodes(tmp_path, [node("Black_Scythe_Training", "Black Scythe Training", "Keystone",
                                       "Black_Scythe_Training", timeless=True)])
    [ent] = build(spec, data)
    assert ent.slug == "Black_Scythe_Training" and ent.node_id == "Black_Scythe_Training"


def test_keyword_entities_from_glossary(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "Chaos Inoculation", "Keystone", "Chaos_Inoculation")])
    write_jsonl(data / "kg" / "keywords.jsonl", [
        {"slug": "Critical_Hits", "name_en": "Critical Hit", "name_zh_tw": "暴擊",
         "url_en": "https://poe2db.tw/us/Critical_Hits", "url_zh_tw": "https://poe2db.tw/tw/Critical_Hits"},
        {"slug": "Bare_Slug", "name_en": None, "name_zh_tw": None, "url_en": None, "url_zh_tw": None},
    ])
    ents = {f"{e.kind}:{e.slug}": e for e in build(spec, data)}
    kw = ents["keyword:Critical_Hits"]
    assert (kw.name_en, kw.name_zh_tw, kw.url_en) == ("Critical Hit", "暴擊", "https://poe2db.tw/us/Critical_Hits")
    assert kw.record_file == "data/kg/keywords.jsonl" and kw.record_key == {"slug": "Critical_Hits"}
    assert "暴擊" in kw.aliases and "criticalhit" in kw.aliases
    assert ents["keyword:Bare_Slug"].name_en == "Bare Slug"           # name derived from slug
    assert "passive_keystone:Chaos_Inoculation" in ents


def test_no_keywords_file_gives_no_keyword_entities(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "A", "Keystone", "A")])
    assert {e.kind for e in build(spec, data)} == {"passive_keystone"}


def test_keyword_and_passive_same_slug_do_not_collide(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "Armour", "Notable", "Armour")])
    write_jsonl(data / "kg" / "keywords.jsonl", [{"slug": "Armour", "name_en": "Armour"}])
    kinds = sorted(e.kind for e in build(spec, data))
    assert kinds == ["keyword", "passive_notable"]


def test_keyword_records_resolve_through_index(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "A", "Keystone", "A")])
    write_jsonl(data / "kg" / "keywords.jsonl", [{"slug": "Stun", "name_en": "Stun", "text_en": "Stuns."}])
    entities = build(spec, data)
    index = EntityIndex(entities, base_dir=tmp_path)
    hit = index.find("stun", kind="keyword")[0]
    assert hit["slug"] == "Stun" and hit["match_type"] == "exact"
    assert index.record(index.get("Stun", kind="keyword"))["text_en"] == "Stuns."
    assert index.record(index.get("A", kind="passive_keystone"))["id"] == "1"


def test_legacy_nodes_without_slug_key_trigger_listing_fetch(spec, tmp_path):
    data = write_nodes(tmp_path, [node("12345", "Resolute Technique", "Keystone")])
    calls = []

    def fetcher(url):
        calls.append(url)
        raise AssertionError("not reached in this test")

    with pytest.raises(AssertionError):
        build_entity_index(spec, data_dir=data, zh_names={}, fetcher=fetcher, cache_dir=tmp_path / "c")
    assert calls and calls[0].endswith("/Keystone")


def test_entity_as_dict_is_json_serialisable(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "Chaos Inoculation", "Keystone", "Chaos_Inoculation")])
    [ent] = build(spec, data)
    assert json.loads(json.dumps(ent.as_dict(), ensure_ascii=False))["slug"] == "Chaos_Inoculation"


def test_exact_matches_any_alias_without_scanning(spec, tmp_path):
    data = write_nodes(tmp_path, [node("1", "Heart of Ice", "Notable", slug="Heart_of_Ice"),
                                  node("2", "Heart of Ice Mastery", "Notable", slug="Heart_of_Ice_Mastery")])
    index = EntityIndex(build(spec, data))
    assert [e.slug for e in index.exact("heart of ice")] == ["Heart_of_Ice"]
    assert [e.slug for e in index.exact("HEART-OF-ICE")] == ["Heart_of_Ice"]
    assert [e.slug for e in index.exact("Heart_of_Ice")] == ["Heart_of_Ice"]
    assert index.exact("Heart of") == [] and index.exact("") == []
    assert index.exact("Heart of Ice", kind="skill_gem") == []
    first = index.find("Heart of Ice", limit=1)[0]
    assert first["match_type"] == "exact" and first["slug"] == index.exact("Heart of Ice")[0].slug
