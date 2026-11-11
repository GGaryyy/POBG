import re

import pytest

from src.catalog.spec import load_spec
from src.tools.build_tools import (
    MAX_ECHO_LEN, MAX_NAME_LEN, MAX_NAMES, MAX_STAT_LINES, START_REASON, BuildTools, _md_code, _md_text, _md_url,
    render_sources,
)
from src.tools.lookup import TREE_DATA_LABEL, BadArgument, LookupService
from tests.kg_support import GRAPH_REL, build_full_environment

pytestmark = pytest.mark.integration

POB2_ROW_LABEL = "PathOfBuilding-PoE2 tree 0_5"
GEM_KEYS = {"input", "slug", "kind", "name", "tier", "tags", "cost", "main_stat", "requires_weapons",
            "description", "quality_effects", "stats", "name_zh_tw", "sources", "cite"}
PASSIVE_KEYS = {"input", "id", "slug", "name", "name_zh_tw", "type", "ascendancy", "stats", "stats_zh_tw",
                "sources", "cite"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return build_full_environment(tmp_path_factory.mktemp("verify_env"), load_spec())


@pytest.fixture(scope="module")
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


def source_for(result, fact):
    return next(row for row in result["sources"] if row["n"] == fact["cite"])


# -- exact matches -------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Leap Slam", "leap slam", "躍擊", "Leap_Slam"])
def test_gem_verifies_by_name_language_or_slug(tools, name):
    result = tools.verify_build(gems=[name])
    gem = result["verified"]["gems"][0]
    assert gem["slug"] == "Leap_Slam" and gem["input"] == name and result["unverified"] == []
    assert set(gem) == GEM_KEYS
    assert gem["name_zh_tw"] == "躍擊" and gem["kind"] == "skill_gem"


@pytest.mark.parametrize("name, node_id", [("Heart of Ice", "3"), ("冰之心", "3"), ("Heart_of_Ice", "3"),
                                           ("3", "3"), ("Chaos Inoculation", "2"), ("2", "2")])
def test_passive_verifies_by_name_language_slug_or_id(tools, name, node_id):
    result = tools.verify_build(passives=[name])
    passive = result["verified"]["passives"][0]
    assert passive["id"] == node_id and result["unverified"] == []
    assert set(passive) == PASSIVE_KEYS


def test_cite_matches_the_source_row_with_url(tools):
    result = tools.verify_build(gems=["Leap Slam", "Herald of Ash"], passives=["Heart of Ice"])
    facts = result["verified"]["gems"] + result["verified"]["passives"]
    for fact in facts:
        row = source_for(result, fact)
        assert row["url"] == fact["sources"][0]["url"] and row["url"].startswith("https://")
    assert [f["cite"] for f in facts] == [1, 2, 3]
    assert [r["n"] for r in result["sources"]] == [1, 2, 3]


def test_duplicates_in_all_spellings_collapse(tools):
    result = tools.verify_build(gems=["Leap Slam", "躍擊", "Leap_Slam", "leap slam"])
    assert [g["slug"] for g in result["verified"]["gems"]] == ["Leap_Slam"]
    assert len(result["sources"]) == 1 and result["unverified"] == []


def test_duplicate_passives_collapse(tools):
    result = tools.verify_build(passives=["Heart of Ice", "冰之心", "3"])
    assert [p["id"] for p in result["verified"]["passives"]] == ["3"]


def test_nodes_without_a_page_share_one_pob2_row(tools):
    result = tools.verify_build(passives=["4", "5", "Heart of Ice"])
    small = [p for p in result["verified"]["passives"] if p["slug"] is None]
    assert [p["id"] for p in small] == ["4", "5"]
    assert all(p["sources"][0]["label"] == POB2_ROW_LABEL for p in small)
    assert small[0]["cite"] == small[1]["cite"]
    pob2_rows = [r for r in result["sources"] if r["label"] == POB2_ROW_LABEL]
    assert len(pob2_rows) == 1 and pob2_rows[0]["name"] is None
    assert [r["n"] for r in result["sources"]] == [1, 2, 3]
    assert result["sources"][1]["label"] == TREE_DATA_LABEL        # node 5's Chinese text comes from poe2db's tree data


def test_source_rows_are_unique_by_url(tools):
    result = tools.verify_build(gems=["Leap Slam", "Unearth"], passives=["4", "5", "2"])
    urls = [r["url"] for r in result["sources"]]
    assert len(urls) == len(set(urls)) == 5


# -- unverified ----------------------------------------------------------------------------

def test_prefix_only_name_is_unverified_with_suggestions(tools):
    result = tools.verify_build(gems=["leap"])
    assert result["verified"] == {"gems": [], "passives": []}
    entry = result["unverified"][0]
    assert entry["input"] == "leap" and entry["expected"] == "gem"
    assert entry["reason"] == "no exact match in local data"
    assert entry["suggestions"] == [{"slug": "Leap_Slam", "kind": "skill_gem", "name_en": "Leap Slam",
                                     "name_zh_tw": "躍擊", "match_type": "prefix"}]


def test_suggestions_are_capped_and_shaped(tools):
    entry = tools.verify_build(gems=["a"])["unverified"][0]
    assert 1 <= len(entry["suggestions"]) <= 3
    for suggestion in entry["suggestions"]:
        assert set(suggestion) == {"slug", "kind", "name_en", "name_zh_tw", "match_type"}
        assert suggestion["kind"] in {"skill_gem", "spirit_gem", "support_gem"}


@pytest.mark.parametrize("gems, passives", [
    (["leap"], None), (["Leap Sl"], None), (["slam"], None), (["fire damage"], None), (["Added"], None),
    (None, ["Heart of"]), (None, ["冰之"]), (None, ["Inoculation"]), (None, ["Chaos"]),
])
def test_partial_names_never_reach_verified(tools, gems, passives):
    result = tools.verify_build(gems=gems, passives=passives)
    assert result["verified"] == {"gems": [], "passives": []}
    assert len(result["unverified"]) == 1 and result["sources"] == []


def test_gem_name_in_passives_is_wrong_kind(tools):
    result = tools.verify_build(passives=["Leap Slam"])
    entry = result["unverified"][0]
    assert entry["reason"] == "this name is a skill_gem, not a passive" and entry["expected"] == "passive"
    assert result["verified"]["passives"] == []


def test_passive_name_in_gems_is_wrong_kind(tools):
    result = tools.verify_build(gems=["Heart of Ice"])
    entry = result["unverified"][0]
    assert entry["reason"] == "this name is a passive_notable, not a gem" and entry["expected"] == "gem"


def test_mixed_input_splits_into_verified_and_unverified(tools):
    result = tools.verify_build(gems=["Leap Slam", "Nonexistent Gem"], passives=["Heart of Ice", "Nope"])
    assert [g["slug"] for g in result["verified"]["gems"]] == ["Leap_Slam"]
    assert [u["input"] for u in result["unverified"]] == ["Nonexistent Gem", "Nope"]


# -- bad arguments -------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs, message", [
    ({}, "at least one gem or passive"),
    ({"gems": [], "passives": []}, "at least one gem or passive"),
    ({"gems": ["Leap Slam"] * (MAX_NAMES + 1)}, "limit is 40"),
    ({"passives": ["x"] * (MAX_NAMES + 1)}, "passives has 41"),
    ({"gems": ["x" * (MAX_NAME_LEN + 1)]}, "longer than 120"),
    ({"gems": [""]}, "non-empty"),
    ({"gems": ["   "]}, "non-empty"),
    ({"gems": "Leap Slam"}, "must be a list"),
    ({"passives": "Heart of Ice"}, "must be a list"),
    ({"gems": [5]}, "non-empty"),
    ({"gems": ["Leap Slam"], "lang": "fr"}, "lang must be one of"),
])
def test_bad_arguments(tools, kwargs, message):
    with pytest.raises(BadArgument, match=message):
        tools.verify_build(**kwargs)


def test_limits_are_inclusive(tools):
    assert tools.verify_build(gems=["Leap Slam"] * MAX_NAMES)["verified"]["gems"]
    assert tools.verify_build(gems=["x" * MAX_NAME_LEN])["unverified"]


# -- language ------------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs, lang", [
    ({"gems": ["Leap Slam"]}, "en"),
    ({"gems": ["躍擊"]}, "zh-tw"),
    ({"gems": ["Leap Slam"], "passives": ["冰之心"]}, "zh-tw"),
    ({"gems": ["躍擊"], "lang": "en"}, "en"),
    ({"gems": ["Leap Slam"], "lang": "zh-TW"}, "zh-tw"),
])
def test_language_detection_and_override(tools, kwargs, lang):
    assert tools.verify_build(**kwargs)["lang"] == lang


def test_sources_markdown_english(tools):
    md = tools.verify_build(gems=["Leap Slam"], passives=["4"])["sources_markdown"]
    lines = md.split("\n")
    assert lines[0] == "## Sources"
    assert lines[1] == ("1. [Leap Slam](https://poe2db.tw/us/Leap_Slam) · [躍擊](https://poe2db.tw/tw/Leap_Slam)"
                        " — poe2db, fetched 2026-01-01")
    assert lines[2].startswith("2. [PathOfBuilding-PoE2 tree 0\\_5](https://raw.githubusercontent.com/")
    assert lines[2].endswith("— passive nodes without a poe2db page, fetched 2026-01-01")
    assert "Not found" not in md


def test_sources_markdown_traditional_chinese(tools):
    md = tools.verify_build(gems=["Leap Slam"], lang="zh-tw")["sources_markdown"]
    assert md.split("\n") == ["## 資料來源",
                              "1. [躍擊](https://poe2db.tw/tw/Leap_Slam) · [Leap Slam](https://poe2db.tw/us/Leap_Slam)"
                              " — poe2db，擷取於 2026-01-01"]


def test_removed_names_line_english(tools):
    md = tools.verify_build(gems=["Leap Slam", "Bogus One"], passives=["Bogus Two"])["sources_markdown"]
    assert md.endswith("\n\nNot found in local data (removed): `Bogus One`, `Bogus Two`")


def test_removed_names_line_chinese(tools):
    md = tools.verify_build(gems=["不存在"], passives=["Bogus"])["sources_markdown"]
    assert md == "## 資料來源\n\n本地資料查無（已移除）：`不存在`, `Bogus`"


def test_no_removed_line_when_everything_verified(tools):
    assert "\n\n" not in tools.verify_build(gems=["Leap Slam"])["sources_markdown"]


# -- markdown safety -----------------------------------------------------------------------

def test_hostile_input_is_one_line_inside_a_code_span(tools):
    result = tools.verify_build(gems=["[x](http://evil) \n# Title"])
    removed = result["sources_markdown"].split("\n\n")[-1]
    assert removed == "Not found in local data (removed): `[x](http://evil) # Title`"
    assert result["sources_markdown"].count("`") == 2


@pytest.mark.parametrize("name, shown", [
    ("https://evil.example/x", "`https://evil.example/x`"),          # a bare URL would autolink
    ("<https://evil.example>", "`<https://evil.example>`"),
    ("a`b``c", "`a'b''c`"),                                          # a backtick cannot close the span
    ("<img src=x onerror=1>", "`<img src=x onerror=1>`"),
])
def test_echoed_names_cannot_become_links_or_html(tools, name, shown):
    md = tools.verify_build(gems=[name])["sources_markdown"]
    assert md == f"## Sources\n\nNot found in local data (removed): {shown}"


def test_long_input_is_truncated(tools):
    removed = tools.verify_build(gems=["[" * 100])["sources_markdown"].split("(removed): ")[1]
    assert removed == "`" + "[" * MAX_ECHO_LEN + "`"


def test_md_code_flattens_and_truncates():
    assert _md_code("  two\t lines\nhere ") == "`two lines here`"
    assert _md_code("x" * 200) == "`" + "x" * MAX_ECHO_LEN + "`"


def test_md_text_escapes_markdown_characters():
    assert _md_text("a*b_c`d|e!f<g>h\\i") == "a\\*b\\_c\\`d\\|e\\!f\\<g\\>h\\\\i"
    assert _md_text("  two\t spaces\n") == "two spaces"


def test_md_url_percent_encodes():
    assert _md_url("https://x.test/a b(c)<d>") == "https://x.test/a%20b%28c%29%3Cd%3E"


def test_render_sources_replaced_by():
    unverified = [{"input": "Old Gem", "replaced_by": "New Gem"}, {"input": "Plain"}]
    assert render_sources([], unverified, "en").endswith("`Old Gem` (replaced by New Gem), `Plain`")
    assert render_sources([], unverified, "zh-tw").endswith("`Old Gem`（改用 New Gem）, `Plain`")


def test_render_sources_without_fetched_date():
    row = {"n": 1, "label": "poe2db", "name": "A (b)", "name_zh_tw": None, "url": "https://x.test/a b",
           "url_zh_tw": None, "fetched_at": None}
    assert render_sources([row], [], "en") == "## Sources\n1. [A \\(b\\)](https://x.test/a%20b) — poe2db"


def test_fetched_date_is_date_only():
    row = {"n": 1, "label": "poe2db", "name": "A", "name_zh_tw": "甲", "url": "https://x.test/a",
           "url_zh_tw": "https://x.test/tw/a", "fetched_at": "2026-03-04T05:06:07+00:00"}
    assert re.search(r"fetched 2026-03-04$", render_sources([row], [], "en"))


# -- review fixes (2026-11-10) -------------------------------------------------------------

def test_an_unknown_name_is_reported_once(tools):
    result = tools.verify_build(gems=["Mega Slam", "mega slam", "MEGA-SLAM", "Other"], passives=["Mega Slam"])
    assert [(u["input"], u["expected"]) for u in result["unverified"]] == [
        ("Mega Slam", "gem"), ("Other", "gem"), ("Mega Slam", "passive")]
    assert result["sources_markdown"].endswith("(removed): `Mega Slam`, `Other`, `Mega Slam`")


@pytest.mark.parametrize("name, reason", [
    ("1", START_REASON), ("Infernalist", START_REASON), ("10", START_REASON),
    ("WITCH", "no exact match in local data"),   # class start nodes are not in the name index at all
])
def test_start_nodes_are_not_passives_to_allocate(tools, name, reason):
    result = tools.verify_build(passives=[name])
    assert result["verified"]["passives"] == [] and result["sources"] == []
    assert [(u["input"], u["reason"]) for u in result["unverified"]] == [(name, reason)]


def test_ascendancy_notable_still_verifies(tools):
    result = tools.verify_build(passives=["Beidat's Will"])
    assert [p["id"] for p in result["verified"]["passives"]] == ["11"] and result["unverified"] == []


def test_gem_fact_carries_capped_stat_lines_and_quality(tools, monkeypatch):
    record = tools.lookup.gems["skill_gem"]["Leap_Slam"]
    lines = [f"stat line {i}" for i in range(MAX_STAT_LINES + 3)]
    monkeypatch.setitem(record, "extra_properties", lines)
    monkeypatch.setitem(record, "quality_effects", "+10% to Area of Effect")
    fact = tools.gem_fact("Leap Slam")
    assert fact["stats"] == lines[:MAX_STAT_LINES] and fact["quality_effects"] == "+10% to Area of Effect"


@pytest.mark.parametrize("value", [None, "one string", 7, [1, None]])
def test_gem_fact_stats_ignore_malformed_values(tools, monkeypatch, value):
    monkeypatch.setitem(tools.lookup.gems["skill_gem"]["Leap_Slam"], "extra_properties", value)
    assert tools.gem_fact("Leap Slam")["stats"] == []


def test_poe2db_row_without_an_english_name_is_not_called_a_tree_row():
    row = {"n": 1, "label": "poe2db", "name": None, "name_zh_tw": "甲", "url": "https://poe2db.tw/us/Some_Gem",
           "url_zh_tw": None, "fetched_at": None}
    assert render_sources([row], [], "en") == "## Sources\n1. [甲](https://poe2db.tw/us/Some_Gem) — poe2db"
    assert render_sources([{**row, "name_zh_tw": None}], [], "en") == (
        "## Sources\n1. [Some\\_Gem](https://poe2db.tw/us/Some_Gem) — poe2db")


# -- zh-TW text of page-less nodes ---------------------------------------------------------------------

TREE_DATA_URL = "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json"


def test_small_node_fact_carries_chinese_name_and_stats(tools):
    fact = tools.verify_build(passives=["5"])["verified"]["passives"][0]
    assert fact["name"] == "Attack Speed" and fact["name_zh_tw"] == "攻擊速度"
    assert fact["stats_zh_tw"] == ["增加 12% 攻擊速度"]
    assert [s["label"] for s in fact["sources"]] == [POB2_ROW_LABEL, TREE_DATA_LABEL]
    assert fact["sources"][1]["url"] == TREE_DATA_URL and fact["cite"] == 1


@pytest.mark.parametrize("lang, note", [("en", "Traditional Chinese names and stat lines of those nodes, fetched 2026-01-01"),
                                        ("zh-tw", "這些天賦點的繁體中文名稱與屬性文字，擷取於 2026-01-01")])
def test_tree_data_is_cited_in_the_rendered_sources(tools, lang, note):
    result = tools.verify_build(passives=["5"], lang=lang)
    lines = result["sources_markdown"].splitlines()
    assert lines[2] == f"2. [{TREE_DATA_LABEL}]({TREE_DATA_URL}) — {note}"
    assert len(lines) == 3


def test_tree_data_is_not_cited_when_no_fact_uses_it(tools):
    result = tools.verify_build(passives=["4", "Heart of Ice"])     # node 4 has no Chinese text; node 3 has a page
    assert all(r["label"] != TREE_DATA_LABEL for r in result["sources"])
    assert TREE_DATA_URL not in result["sources_markdown"]


def test_page_less_passive_row_without_a_date_shows_only_what_it_is(tools):
    node = tools.lookup.passives["4"]
    saved = node.pop("fetched_at")
    try:
        lines = tools.verify_build(passives=["4"])["sources_markdown"].splitlines()
        assert lines[1].endswith("— passive nodes without a poe2db page")
    finally:
        node["fetched_at"] = saved
