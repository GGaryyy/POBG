import pytest
import requests

from src.scrapers import collect_gems
from src.scrapers.collect_gems import CollectionError, collect_kind, main
from src.scrapers.common import read_jsonl
from tests.support import html, lowered_spec

pytestmark = pytest.mark.integration

LISTING_URL = "https://poe2db.tw/us/Skill_Gems"


def good_fetcher(url, **_):
    return html("listing_skill_us.html") if url == LISTING_URL else html("detail_skill.html")


def test_collect_skill_gems(tmp_path):
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=good_fetcher)
    detail = tmp_path / "skill_gems" / "Skill_Gems_Detail.jsonl"
    listing = tmp_path / "skill_gems" / "Skill_Gems_Listing.jsonl"
    cutting = tmp_path / "skill_gems" / "Skill_Gems_SkillGemsGemcutting.jsonl"
    assert detail.exists() and listing.exists() and cutting.exists()

    records = read_jsonl(detail)
    assert [r["slug"] for r in records] == ["Leap_Slam", "Unearth", "Grim_Feast"]
    leap, unearth, grim = records
    assert leap["tag_slugs"] == ["Attacks", "Area_of_Effect_Skills"] and leap["attribute_colour"] == "str"
    assert unearth["tag_slugs"] == ["Spells", "Minions"] and unearth["attribute_colour"] == "int"
    assert grim["attribute_colour"] is None
    assert leap["href"] == "https://poe2db.tw/us/Leap_Slam"
    assert leap["tier"] == 7 and leap["hidden_stats"] == ["is area damage [1]"]

    listing_rows = read_jsonl(listing)
    assert len(listing_rows) == 3
    assert listing_rows[0]["kind"] == "skill_gem" and listing_rows[0]["url"] == LISTING_URL.replace("Skill_Gems", "Leap_Slam")
    cut_rows = read_jsonl(cutting)
    assert [(r["class_name"], r["gem_slug"]) for r in cut_rows] == [("Occult", "Unearth"), ("Occult", "Contagion")]
    assert cut_rows[0]["source_url"] == LISTING_URL

    assert summary["kind"] == "skill_gem"
    assert summary["listing_rows"] == 3 and summary["records"] == 3
    assert summary["gemcutting_rows"] == 2 and summary["skipped"] == []
    assert set(summary) == {"kind", "mode", "listing_rows", "records", "refetched", "added", "removed",
                            "skipped", "gemcutting_rows", "targets_total", "targets_left", "reasons", "recently_fetched",
                            "stored_elsewhere",
                            "null_rate", "warnings", "files"}
    assert len(summary["files"]) == 3
    assert summary["null_rate"]["tier"] == 0.0
    assert summary["null_rate"]["quality_effects"] == 0.0


def test_detail_markup_drift_aborts_without_writing(tmp_path):
    def fetcher(url):
        if url == LISTING_URL:
            return html("listing_skill_us.html")
        return html("detail_nopopup.html")

    # every detail page lost its popup => markup drift => never overwrite good data
    with pytest.raises(CollectionError, match="no parsable popup"):
        collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=fetcher)
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_single_broken_detail_page_under_threshold_still_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_gems, "MAX_BROKEN_RATIO", 0.5)

    def fetcher(url):
        if url == LISTING_URL:
            return html("listing_skill_us.html")
        if url.endswith("/Leap_Slam"):
            return html("detail_nopopup.html")
        return html("detail_skill.html")

    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=fetcher)
    recs = {r["slug"]: r for r in read_jsonl(tmp_path / "skill_gems" / "Skill_Gems_Detail.jsonl")}
    broken = recs["Leap_Slam"]
    assert broken["tier"] == 7 and broken["tags"] == ["Attack", "AoE"]   # backfilled from the listing row
    assert {"tier_from_listing", "tags_from_listing", "no_popup"} <= set(broken["parse_warnings"])
    assert summary["warnings"]["no_popup"] == 1


def test_listing_below_expect_min(tmp_path):
    spec = lowered_spec(1)
    spec.raw["sources"]["skill_gems_listing"]["sections"]["list"]["expect_min"] = 4
    with pytest.raises(CollectionError, match="below expect_min=4"):
        collect_kind("skill_gem", spec, out_dir=tmp_path, fetcher=good_fetcher)
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_all_detail_pages_failing(tmp_path):
    def fetcher(url):
        if url == LISTING_URL:
            return html("listing_skill_us.html")
        raise requests.ConnectionError("down")

    with pytest.raises(CollectionError, match="3 of 3 detail pages failed"):
        collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=fetcher)
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_limit(tmp_path):
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=good_fetcher, limit=1)
    assert summary["records"] == 1 and summary["listing_rows"] == 1
    assert len(read_jsonl(tmp_path / "skill_gems" / "Skill_Gems_Detail.jsonl")) == 1


def test_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        collect_kind("wand_gem", lowered_spec(1), out_dir=tmp_path, fetcher=good_fetcher)


def test_main_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(collect_gems, "load_spec", lambda: lowered_spec(1))
    monkeypatch.setattr(collect_gems, "fetch_html", lambda url, **kw: good_fetcher(url))
    assert main(["--kind", "skill", "--out-dir", str(tmp_path), "--no-cache"]) == 0
    assert (tmp_path / "skill_gems" / "Skill_Gems_Detail.jsonl").exists()
    assert "skill_gem [full]: listing=3 records=3 refetched=3 gemcutting=2 skipped=0" in capsys.readouterr().out


def test_main_returns_1_on_collection_error(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_gems, "fetch_html", lambda url, **kw: good_fetcher(url))
    # real spec expects 380 gems -> CollectionError -> exit code 1
    assert main(["--kind", "skill", "--out-dir", str(tmp_path), "--no-cache"]) == 1
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_main_returns_1_on_http_error(monkeypatch, tmp_path):
    def boom(url, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(collect_gems, "load_spec", lambda: lowered_spec(1))
    monkeypatch.setattr(collect_gems, "fetch_html", boom)
    assert main(["--kind", "skill", "--out-dir", str(tmp_path), "--no-cache"]) == 1
