"""The atlas collector on the synthetic Waystones page (tests/atlas_support.py)."""

from __future__ import annotations

import json

import pytest

from src.scrapers import collect_atlas as ca
from src.scrapers.common import make_soup, read_jsonl
from tests.atlas_support import MODS, PANES, AtlasSite, atlas_spec, site_pages, waystones_page


def parsed(lang: str = "en", **options) -> dict:
    return ca.parse_page(waystones_page(lang, **options), PANES[lang])


# -- parsing -------------------------------------------------------------------------------------------------

def test_tiers_carry_their_area_level_in_both_languages():
    en, zh = parsed()["tiers"], parsed("zh-tw")["tiers"]
    assert [(t["tier"], t["area_level"]) for t in en][:2] == [(1, 65), (2, 66)] and en[-1] == {
        "tier": 16, "name": "Waystone (Tier 16)", "slug": "Waystone_%28Tier_16%29", "area_level": 80}
    assert zh[9]["name"] == "換界石（階級 10）" and zh[9]["area_level"] == 74


def test_tiers_are_sorted_by_tier_whatever_the_page_order():
    rows = parsed(tiers=[16, 1, 10])["tiers"]
    assert [t["tier"] for t in rows] == [1, 10, 16]


def test_penalty_table_is_read_by_level():
    assert parsed()["penalty"][:2] == [{"level": 1, "penalty": 0}, {"level": 16, "penalty": -10}]
    assert parsed()["penalty"][-1] == {"level": 65, "penalty": -60}


def test_mod_lines_are_split_at_line_breaks_and_keep_ranges():
    mods = parsed()["mods"]
    assert len(mods) == len(MODS) and mods[0] == {"level": 1, "affix": "prefix", "lines": []}
    assert mods[2]["lines"] == ["Monsters deal (5—9)% of Damage as Extra Fire", "15% more Waystones found in Area"]
    assert parsed("zh-tw")["mods"][4]["affix"] == "suffix"
    assert parsed("zh-tw")["mods"][4]["lines"][0] == "怪物遭暴擊時，減少(20—25)%承受的額外傷害"


def test_cell_lines_drop_empty_lines():
    cell = make_soup("<td>a<br/><br/> b <br/></td>").find("td")
    assert ca.cell_lines(cell) == ["a", "b"]


def test_a_missing_tab_is_an_error_that_names_it():
    with pytest.raises(ca.AtlasBuildError, match="'Missing'"):
        ca.parse_page(waystones_page("en"), {**PANES["en"], "mods": "Missing"})


# -- merging and checks --------------------------------------------------------------------------------------

def test_merge_joins_chinese_rows_by_place_and_skips_rows_without_lines():
    atlas, mods = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "2026-11-17T00:00:00+00:00")
    assert atlas["tiers"][0]["name_zh_tw"] == "換界石（階級 1）"
    assert atlas["url_en"] == "https://poe2db.tw/us/Waystones" and atlas["url_zh_tw"] == "https://poe2db.tw/tw/Waystones"
    assert [m["id"] for m in mods] == ["waystone_2", "waystone_3", "waystone_4", "waystone_5", "waystone_6", "waystone_7"]
    assert mods[0]["lines_zh_tw"] == ["稀有怪物有1個額外詞綴", "增加10%此區域找到的換界石"]
    assert all(m["fetched_at"] == "2026-11-17T00:00:00+00:00" for m in mods)


def test_merge_leaves_chinese_empty_when_the_rows_do_not_line_up():
    zh = parsed("zh-tw")
    zh["mods"][3]["affix"] = "prefix" if zh["mods"][3]["affix"] == "suffix" else "suffix"
    _, mods = ca.merge(parsed(), zh, atlas_spec(), "now")
    assert mods[2]["lines_zh_tw"] == [] and mods[1]["lines_zh_tw"]           # only that row
    zh["mods"].pop()
    _, mods = ca.merge(parsed(), zh, atlas_spec(), "now")
    assert all(m["lines_zh_tw"] == [] for m in mods)                       # counts differ: no row joins


def test_check_refuses_too_few_rows_a_missing_stage_tier_and_little_chinese():
    atlas, mods = ca.merge(parsed(tiers=range(1, 13)), parsed("zh-tw"), atlas_spec(), "now")
    with pytest.raises(ca.AtlasBuildError, match="no waystone tier 16"):
        ca.check(atlas, mods, atlas_spec())
    atlas, mods = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "now")
    with pytest.raises(ca.AtlasBuildError, match="6 waystone modifiers"):
        ca.check(atlas, mods, atlas_spec(mods=60))
    with pytest.raises(ca.AtlasBuildError, match="resistance penalty rows"):
        ca.check(atlas, mods, atlas_spec(penalty_rows=8))
    with pytest.raises(ca.AtlasBuildError, match="waystone tiers"):
        ca.check(atlas, mods, atlas_spec(tiers=20))
    for m in mods[:3]:
        m["lines_zh_tw"] = []
    with pytest.raises(ca.AtlasBuildError, match="Chinese lines"):
        ca.check(atlas, mods, atlas_spec())


def test_check_refuses_a_row_that_is_neither_prefix_nor_suffix():
    atlas, mods = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "now")
    mods[0]["affix"] = None
    with pytest.raises(ca.AtlasBuildError, match="neither prefix nor suffix"):
        ca.check(atlas, mods, atlas_spec())


# -- collecting and writing ----------------------------------------------------------------------------------

def test_collect_reads_two_pages_and_writes_both_files(tmp_path):
    site = AtlasSite()
    result = ca.collect(atlas_spec(), fetch=site, cache_dir=tmp_path / "cache")
    assert site.calls == ["https://poe2db.tw/us/Waystones", "https://poe2db.tw/tw/Waystones"]
    ca.write(atlas_spec(), tmp_path, result)
    atlas = json.loads((tmp_path / "data" / "atlas" / "atlas.json").read_text(encoding="utf-8"))
    assert len(atlas["tiers"]) == 16 and len(atlas["resistance_penalty"]) == 7
    assert [m["id"] for m in read_jsonl(tmp_path / "data" / "atlas" / "waystone_mods.jsonl")] == [m["id"] for m in result["mods"]]


def test_collect_offline_uses_the_cache_and_fails_without_it(tmp_path):
    ca.collect(atlas_spec(), fetch=AtlasSite(), cache_dir=tmp_path)
    offline = ca.collect(atlas_spec(), fetch=AtlasSite({}), cache_dir=tmp_path, offline=True)
    assert len(offline["mods"]) == 6
    with pytest.raises(ca.AtlasBuildError, match="not in the cache"):
        ca.collect(atlas_spec(), fetch=AtlasSite({}), cache_dir=tmp_path / "empty", offline=True)


def test_collect_refuses_a_page_that_lost_its_tab(tmp_path):
    pages = site_pages()
    pages["https://poe2db.tw/tw/Waystones"] = waystones_page("zh-tw", panes={"zh-tw": {**PANES["zh-tw"], "mods": "Other"}})
    with pytest.raises(ca.AtlasBuildError, match="換界石Mods"):
        ca.collect(atlas_spec(), fetch=AtlasSite(pages), cache_dir=tmp_path)


def test_main_writes_nothing_when_the_page_does_not_parse(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ca, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ca, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ca, "load_spec", atlas_spec)            # only the missing tiers fail
    monkeypatch.setattr(ca, "fetch_html", lambda url, delay=0: waystones_page("en", tiers=range(1, 5))
                        if "/us/" in url else waystones_page("zh-tw"))
    assert ca.main([]) == 1
    err = capsys.readouterr().err
    assert "nothing written" in err and "no waystone tier 10, 16" in err and "modifiers" not in err
    assert not (tmp_path / "data").exists()


def test_main_writes_and_summarises(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ca, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ca, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ca, "load_spec", atlas_spec)
    pages = site_pages()
    monkeypatch.setattr(ca, "fetch_html", lambda url, delay=0: pages[url])
    assert ca.main([]) == 0
    out = capsys.readouterr().out
    assert "16 waystone tiers (Tier 1 = area 65 ... Tier 16 = area 80)" in out and "6 waystone modifiers" in out
    assert (tmp_path / "data" / "atlas" / "atlas.json").exists()


def test_area_level_is_read_from_its_labelled_line_only():
    page = waystones_page("en").replace('<div class="property">Area Level:',
                                        '<div class="property">Waystone Tier: <span>99</span></div><div class="property">Area Level:')
    tiers, labels = ca.parse_tiers(make_soup(page).find("div", id="WaystonesItem"), "Area Level")
    assert tiers[0]["area_level"] == 65 and labels == ["Waystone Tier", "Area Level"]


def test_check_refuses_area_levels_that_do_not_rise_and_a_positive_penalty():
    atlas, mods = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "now")
    atlas["tiers"][3]["area_level"] = 90
    with pytest.raises(ca.AtlasBuildError, match="do not rise"):
        ca.check(atlas, mods, atlas_spec())
    atlas, mods = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "now")
    atlas["resistance_penalty"][2]["penalty"] = 20
    with pytest.raises(ca.AtlasBuildError, match="resistance penalty is not zero or less"):
        ca.check(atlas, mods, atlas_spec())


def test_a_typographic_minus_is_a_minus():
    page = waystones_page("en", penalty=[(1, 0), (16, "−10")])
    assert parsed_from(page)["penalty"][1] == {"level": 16, "penalty": -10}


def test_labels_of_both_languages_are_kept():
    atlas, _ = ca.merge(parsed(), parsed("zh-tw"), atlas_spec(), "now")
    assert atlas["labels"] == {"en": ["Area Level"], "zh-tw": ["區域等級"]}


def parsed_from(page: str) -> dict:
    return ca.parse_page(page, PANES["en"])
