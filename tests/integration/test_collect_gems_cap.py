"""A capped or dry incremental run: what is fetched now, what is left, and what the next run sees."""

from __future__ import annotations

import pytest

from src.scrapers.collect_gems import CollectionError, collect_kind
from src.scrapers.common import read_jsonl
from tests.support import html, lowered_spec

pytestmark = pytest.mark.integration

LISTING_URL = "https://poe2db.tw/us/Skill_Gems"
DETAIL = "skill_gems/Skill_Gems_Detail.jsonl"
LISTING = "skill_gems/Skill_Gems_Listing.jsonl"
SLUGS = ["Leap_Slam", "Unearth", "Grim_Feast"]             # listing order of the fixture
TWO_TIERS_CHANGED = (html("listing_skill_us.html").replace("Leap Slam</a> (7)", "Leap Slam</a> (9)")
                     .replace("Grim Feast</a> (4)", "Grim Feast</a> (8)"))


def run(tmp_path, listing=None, **options):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return (listing or html("listing_skill_us.html")) if url == LISTING_URL else html("detail_skill.html")

    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=tmp_path, fetcher=fetch, **options)
    return summary, [c.rsplit("/", 1)[-1] for c in calls if c != LISTING_URL], calls


def stored(tmp_path, rel=DETAIL):
    return {r["slug"]: r for r in read_jsonl(tmp_path / rel)}


def files(tmp_path):
    return {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in sorted(tmp_path.rglob("*.jsonl"))}


@pytest.fixture
def seeded(tmp_path):
    run(tmp_path)
    return tmp_path


def test_cap_limits_the_detail_pages_of_one_run(seeded):
    summary, fetched, calls = run(seeded, slugs=SLUGS, max_targets=1)
    assert fetched == ["Leap_Slam"] and len(calls) == 2
    assert summary["refetched"] == 1 and summary["targets_total"] == 3 and summary["targets_left"] == 2
    assert summary["reasons"] == {"requested": 3} and summary["records"] == 3


def test_uncapped_incremental_run_reports_nothing_left(seeded):
    summary, fetched, _ = run(seeded, slugs=["Unearth"])
    assert fetched == ["Unearth"] and summary["targets_total"] == 1 and summary["targets_left"] == 0


def test_gem_left_for_later_is_still_selected_by_the_next_run(seeded):
    first, fetched_first, _ = run(seeded, TWO_TIERS_CHANGED, changed_only=True, max_targets=1)
    assert fetched_first == ["Leap_Slam"] and first["targets_left"] == 1
    assert first["reasons"] == {"listing_changed": 2}
    rows = stored(seeded, LISTING)
    assert rows["Leap_Slam"]["tier"] == 9 and rows["Grim_Feast"]["tier"] == 4      # old row kept for the pending gem

    second, fetched_second, _ = run(seeded, TWO_TIERS_CHANGED, changed_only=True, max_targets=1)
    assert fetched_second == ["Grim_Feast"] and second["targets_left"] == 0
    assert stored(seeded, LISTING)["Grim_Feast"]["tier"] == 8

    third, fetched_third, _ = run(seeded, TWO_TIERS_CHANGED, changed_only=True, max_targets=1)
    assert fetched_third == [] and third["targets_total"] == 0


def test_new_gem_beyond_the_cap_is_absent_until_it_is_fetched(seeded):
    listing = html("listing_skill_us.html").replace('href="/us/Unearth"', 'href="/us/Gone"')
    summary, fetched, _ = run(seeded, listing, changed_only=True, max_targets=0)
    assert fetched == [] and summary["targets_left"] == 1 and summary["reasons"] == {"new": 1}
    assert sorted(stored(seeded)) == ["Grim_Feast", "Leap_Slam"]
    assert sorted(stored(seeded, LISTING)) == ["Grim_Feast", "Leap_Slam"]
    assert summary["added"] == [] and summary["removed"] == ["Unearth"]

    later, fetched_later, _ = run(seeded, listing, changed_only=True, max_targets=5)
    assert fetched_later == ["Gone"] and later["added"] == ["Gone"] and later["targets_left"] == 0
    assert sorted(stored(seeded)) == ["Gone", "Grim_Feast", "Leap_Slam"]


def test_requested_gems_are_fetched_before_stale_ones(seeded):
    summary, fetched, _ = run(seeded, slugs=["Grim_Feast"], older_than_days=0, max_targets=1)
    assert fetched == ["Grim_Feast"]
    assert summary["reasons"] == {"requested": 1, "stale": 3} and summary["targets_left"] == 2


def test_new_gems_are_fetched_before_changed_ones(seeded):
    listing = TWO_TIERS_CHANGED.replace('href="/us/Unearth"', 'href="/us/Gone"')
    _, fetched, _ = run(seeded, listing, changed_only=True, max_targets=1)
    assert fetched == ["Gone"]


def test_dry_run_fetches_only_the_listing_and_writes_nothing(seeded):
    before = files(seeded)
    summary, fetched, calls = run(seeded, TWO_TIERS_CHANGED.replace('href="/us/Unearth"', 'href="/us/Gone"'),
                                  changed_only=True, dry_run=True)
    assert calls == [LISTING_URL] and fetched == []
    assert files(seeded) == before
    assert summary["mode"] == "dry_run" and summary["refetched"] == 0
    assert summary["targets_total"] == summary["targets_left"] == 3
    assert summary["reasons"] == {"new": 1, "listing_changed": 2}
    assert summary["added"] == ["Gone"] and summary["removed"] == ["Unearth"] and summary["files"] == []


@pytest.mark.parametrize("options", [{"max_targets": 1}, {"dry_run": True}])
def test_cap_and_dry_run_are_refused_for_a_full_crawl(tmp_path, options):
    with pytest.raises(CollectionError, match="need an incremental mode"):
        run(tmp_path, **options)
    assert files(tmp_path) == {}


def test_recent_window_keeps_requested_and_stale_gems_from_being_selected_again(seeded):
    summary, fetched, _ = run(seeded, slugs=SLUGS, older_than_days=0, max_targets=1, skip_recent_seconds=600)
    assert fetched == [] and summary["targets_total"] == 0 and summary["recently_fetched"] == 3
    summary, fetched, _ = run(seeded, slugs=["Unearth"], skip_recent_seconds=0)
    assert fetched == ["Unearth"] and summary["recently_fetched"] == 0        # the terminal default: no window


def test_one_failed_page_is_skipped_and_keeps_its_old_listing_row(seeded):
    calls = []

    def fetch(url):
        calls.append(url)
        if url == LISTING_URL:
            return TWO_TIERS_CHANGED
        if url.endswith("/Grim_Feast"):
            raise __import__("requests").ConnectionError("gone")
        return html("detail_skill.html")

    summary = collect_kind("skill_gem", lowered_spec(1), out_dir=seeded, fetcher=fetch, changed_only=True)
    assert summary["skipped"] == ["Grim_Feast"] and summary["refetched"] == 1
    rows = stored(seeded, LISTING)
    assert rows["Leap_Slam"]["tier"] == 9 and rows["Grim_Feast"]["tier"] == 4      # still "changed" for the next run


# -- one copy per gem: a spirit gem on the Skill Gems page is not stored as a skill gem ----------

SPIRIT_DETAIL = "spirit_gems/Spirit_Gems_Detail.jsonl"


def with_spirit_data(tmp_path, slugs):
    from src.scrapers.common import write_jsonl
    write_jsonl(tmp_path / SPIRIT_DETAIL, [{"slug": slug, "name": slug, "kind": "spirit_gem"} for slug in slugs])


def test_skill_listing_rows_owned_by_the_spirit_data_are_not_fetched_or_stored(tmp_path):
    with_spirit_data(tmp_path, ["Grim_Feast"])
    summary, fetched, _ = run(tmp_path)
    assert sorted(fetched) == ["Leap_Slam", "Unearth"] and summary["stored_elsewhere"] == 1
    assert sorted(stored(tmp_path)) == ["Leap_Slam", "Unearth"] == sorted(stored(tmp_path, LISTING))
    assert summary["listing_rows"] == 2 and summary["records"] == 2


def test_existing_duplicate_is_removed_by_the_next_incremental_run(seeded):
    assert "Grim_Feast" in stored(seeded)
    with_spirit_data(seeded, ["Grim_Feast"])
    summary, fetched, _ = run(seeded, changed_only=True)
    assert fetched == [] and summary["removed"] == ["Grim_Feast"] and summary["stored_elsewhere"] == 1
    assert sorted(stored(seeded)) == ["Leap_Slam", "Unearth"]


def test_dry_run_reports_the_duplicate_as_removed_without_touching_files(seeded):
    with_spirit_data(seeded, ["Grim_Feast"])
    before = files(seeded)
    summary, _, calls = run(seeded, changed_only=True, dry_run=True)
    assert summary["removed"] == ["Grim_Feast"] and summary["stored_elsewhere"] == 1 and files(seeded) == before
    assert calls == [LISTING_URL]


def test_spirit_gems_are_not_filtered_by_the_skill_data(tmp_path):
    from src.scrapers.collect_gems import OWNED_BY, _stored_under_another_kind
    assert OWNED_BY == {"skill_gem": ("spirit_gem",)}
    run(tmp_path)                                               # skill data now holds Leap_Slam, Unearth, Grim_Feast
    assert _stored_under_another_kind("spirit_gem", lowered_spec(1), tmp_path) == set()
    assert _stored_under_another_kind("support_gem", lowered_spec(1), tmp_path) == set()


def test_all_kinds_are_collected_owners_first(monkeypatch, tmp_path):
    from src.scrapers import collect_gems
    order = []
    monkeypatch.setattr(collect_gems, "collect_kind", lambda kind, spec, **kw: order.append(kind) or {
        "kind": kind, "mode": "full", "listing_rows": 0, "records": 0, "refetched": 0, "added": [], "removed": [],
        "skipped": [], "gemcutting_rows": 0, "null_rate": {}, "warnings": {}, "files": []})
    monkeypatch.setattr(collect_gems, "_print_summary", lambda summaries: None)
    assert collect_gems.main(["--kind", "all", "--out-dir", str(tmp_path)]) == 0
    assert order.index("spirit_gem") < order.index("skill_gem") and len(order) == 3
