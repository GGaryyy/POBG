"""Incremental collection: --changed-only / --slugs / --older-than."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.scrapers.collect_gems import collect_kind
from src.scrapers.common import read_jsonl
from tests.support import html, lowered_spec

pytestmark = pytest.mark.integration

LISTING_URL = "https://poe2db.tw/us/Skill_Gems"
DETAIL = "skill_gems/Skill_Gems_Detail.jsonl"


def _fetcher(calls: list[str], listing: str = "listing_skill_us.html"):
    def fetch(url: str) -> str:
        calls.append(url)
        return html(listing) if url == LISTING_URL else html("detail_skill.html")
    return fetch


def _seed(tmp_path):
    """Full run first, so the incremental run has something to compare against."""
    calls: list[str] = []
    collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls))
    return calls


def test_changed_only_fetches_nothing_when_listing_is_unchanged(tmp_path):
    _seed(tmp_path)
    calls: list[str] = []
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls), changed_only=True)
    assert calls == [LISTING_URL]
    assert summary["mode"] == "incremental" and summary["refetched"] == 0
    assert summary["records"] == 3 and summary["added"] == [] and summary["removed"] == []


def test_changed_only_refetches_changed_row_and_drops_removed_gem(tmp_path):
    _seed(tmp_path)
    before = {r["slug"]: r["fetched_at"] for r in read_jsonl(tmp_path / DETAIL)}
    # tier of Leap Slam changes on the listing; Unearth disappears from the listing
    listing = html("listing_skill_us.html").replace("Leap Slam</a> (7)", "Leap Slam</a> (9)")
    listing = listing.replace('href="/us/Unearth"', 'href="/us/Gone"')
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return listing if url == LISTING_URL else html("detail_skill.html")

    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=fetch, changed_only=True)
    after = {r["slug"]: r for r in read_jsonl(tmp_path / DETAIL)}
    assert "Unearth" not in after and "Gone" in after
    assert summary["added"] == ["Gone"] and summary["removed"] == ["Unearth"]
    assert sorted(c.rsplit("/", 1)[-1] for c in calls if c != LISTING_URL) == ["Gone", "Leap_Slam"]
    assert after["Leap_Slam"]["fetched_at"] != before["Leap_Slam"]
    unchanged = next(s for s in before if s not in ("Leap_Slam", "Unearth"))
    assert after[unchanged]["fetched_at"] == before[unchanged]


def test_slugs_refetches_only_requested(tmp_path):
    _seed(tmp_path)
    calls: list[str] = []
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls), slugs=["Leap_Slam"])
    assert [c for c in calls if c != LISTING_URL] == ["https://poe2db.tw/us/Leap_Slam"]
    assert summary["refetched"] == 1 and summary["records"] == 3


def test_older_than_refetches_stale_records(tmp_path):
    _seed(tmp_path)
    path = tmp_path / DETAIL
    recs = read_jsonl(path)
    stale = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    recs[0]["fetched_at"] = stale
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    calls: list[str] = []
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls), older_than_days=30)
    assert summary["refetched"] == 1
    assert [c.rsplit("/", 1)[-1] for c in calls if c != LISTING_URL] == [recs[0]["slug"]]


def test_detail_pages_are_cached_and_reparsed_offline(tmp_path):
    cache = tmp_path / "cache"
    calls: list[str] = []
    collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls), cache_dir=cache)
    cached = sorted(p.name for p in (cache / "en").glob("*.html"))
    assert cached == sorted(f"{r['slug']}.html" for r in read_jsonl(tmp_path / DETAIL))

    calls.clear()
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls),
                           cache_dir=cache, from_cache=True)
    assert calls == [LISTING_URL]            # only the listing is fetched; details come from the cache
    assert summary["refetched"] == 3


def test_changed_only_without_existing_data_behaves_like_full(tmp_path):
    calls: list[str] = []
    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls), changed_only=True)
    assert summary["refetched"] == 3 and summary["records"] == 3
    assert sorted(summary["added"]) == sorted(r["slug"] for r in read_jsonl(tmp_path / DETAIL))


def test_from_cache_reads_listing_from_page_cache_without_network(tmp_path):
    pages = tmp_path / "pages"
    cache = tmp_path / "cache"
    calls: list[str] = []
    collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher(calls),
                 cache_dir=cache, listing_cache_dir=pages)
    assert (pages / "en_Skill_Gems.html").exists()

    def no_network(url: str) -> str:
        raise AssertionError(f"network used under --from-cache: {url}")

    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=no_network,
                           cache_dir=cache, listing_cache_dir=pages, from_cache=True)
    assert summary["refetched"] == 3


def test_from_cache_without_cached_listing_fails_cleanly(tmp_path):
    from src.scrapers.collect_gems import CollectionError
    with pytest.raises(CollectionError, match="not cached"):
        collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher([]),
                     cache_dir=tmp_path / "cache", listing_cache_dir=tmp_path / "pages", from_cache=True)


def test_from_cache_cites_the_cache_file_time(tmp_path):
    import os
    cache = tmp_path / "cache"
    collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher([]), cache_dir=cache)
    old = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
    for page in (cache / "en").glob("*.html"):
        os.utime(page, (old, old))
    collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=_fetcher([]), cache_dir=cache, from_cache=True)
    stamps = {r["fetched_at"][:10] for r in read_jsonl(tmp_path / DETAIL)}
    assert stamps == {"2026-01-02"}
