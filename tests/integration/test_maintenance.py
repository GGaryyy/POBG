"""Data status and scoped updates (src/tools/maintenance.py) on a synthetic data folder."""

from __future__ import annotations

import copy
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from src import __version__
from src.catalog.spec import Spec
from src.scrapers.common import DATA_LOCK_FILE, read_jsonl, write_jsonl
from src.tools import maintenance as mnt
from src.tools.lookup import DATA_LOCK, BadArgument, LookupService, ServiceUnavailable
from tests.kg_support import FETCHED, GRAPH_REL, build_full_environment
from tests.support import fixture_text, html, lowered_spec
from tests.unit.test_probe import make_fake

pytestmark = pytest.mark.integration

SKILL_DETAIL = "data/skill_gems/Skill_Gems_Detail.jsonl"
INDEX = "data/catalog/entity_index.jsonl"
NODES = "data/passive_tree/passive_nodes.jsonl"
STATS = "data/kg/passive_stats.jsonl"
LISTING_US = "https://poe2db.tw/us/Skill_Gems"
LISTING_TW = "https://poe2db.tw/tw/Skill_Gems"
TREE_URL = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json"
PASSIVE_PAGES = {
    "https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json": ("poe2db_tree", "data_us_mini.json"),
    "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json": ("poe2db_tree", "data_tw_mini.json"),
    TREE_URL: ("pob2", "tree_mini.json"),
    "https://poe2db.tw/us/Keystone": ("html", "passive_keystone_cards_en.html"),
    "https://poe2db.tw/tw/Keystone": ("html", "passive_keystone_cards_zh.html"),
    "https://poe2db.tw/us/Notable": ("html", "passive_notable_cards_en.html"),
    "https://poe2db.tw/tw/Notable": ("html", "passive_notable_cards_zh.html"),
}


def fixture_spec(listing_min: int = 1) -> Spec:
    """Real catalog with the minimum counts lowered to what the fixtures hold."""
    raw = copy.deepcopy(lowered_spec(listing_min).raw)
    raw["sources"]["passive_tree_data"]["expect_min"] = {"nodes": 10, "zh_name_ratio": 0.7}
    raw["sources"]["pob2_tree"]["expect_min"] = {"nodes": 10, "keystones": 1, "notables": 3, "class_starts": 1,
                                                 "ascendancy_starts": 1, "poe2db_name_match_ratio": 0.7}
    return Spec(raw)


class Web:
    """Fake site: the fixture pages, a log of every request, and no page for anything else."""

    def __init__(self, listing: str | None = None, broken: tuple[str, ...] = ()) -> None:
        self.calls: list[str] = []
        self.broken = broken
        self.listing = listing or html("listing_skill_us.html")

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url == LISTING_US:
            return self.listing
        if url == LISTING_TW:
            return html("listing_skill_tw.html")
        if url in PASSIVE_PAGES:
            return fixture_text(*PASSIVE_PAGES[url])
        if url.startswith("https://poe2db.tw/us/") and "Gems" not in url:
            slug = url.rsplit("/", 1)[-1]
            if slug in self.broken:
                raise requests.ConnectionError(f"404 for {slug}")
            return html("detail_skill.html").replace("Leap Slam", slug.replace("_", " "))
        raise requests.ConnectionError(f"no fixture for {url}")

    def details(self) -> list[str]:
        return [u.rsplit("/", 1)[-1] for u in self.calls if u.startswith("https://poe2db.tw/us/") and u != LISTING_US
                and u not in PASSIVE_PAGES]


@pytest.fixture
def base(tmp_path):
    return build_full_environment(tmp_path, fixture_spec())


@pytest.fixture
def tool(base):
    return mnt.DataMaintenance(base, fixture_spec(), base / GRAPH_REL)


@pytest.fixture
def lenient_stats(monkeypatch):
    """The synthetic tree has many rule-like lines; the real threshold is tested on its own below."""
    monkeypatch.setattr(mnt, "MIN_PARSED_RATIO", 0.5)


def snapshot(base) -> dict[str, bytes]:
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def slugs(base, rel=SKILL_DETAIL) -> list[str]:
    return sorted(r["slug"] for r in read_jsonl(base / rel))


def index_names(base) -> dict[str, str | None]:
    return {r["slug"]: r["name_zh_tw"] for r in read_jsonl(base / INDEX)}


def age_records(base, hours: float = 1.0) -> None:
    """Pretend the stored skill gems were fetched some hours ago (outside the 15-minute window)."""
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    write_jsonl(base / SKILL_DETAIL, [{**r, "fetched_at": stamp} for r in read_jsonl(base / SKILL_DETAIL)])


# -- status ------------------------------------------------------------------------------------

def test_status_reports_counts_dates_and_scopes(tool, base, monkeypatch):
    monkeypatch.setattr(mnt, "fetch_html", lambda *a, **k: pytest.fail("status must not use the network"))
    status = tool.status()
    sets = {d["name"]: d for d in status["datasets"]}
    assert list(sets) == ["skill_gems", "spirit_gems", "support_gems", "passives", "glossary", "ladder", "entity_index"]
    assert sets["skill_gems"] == {"name": "skill_gems", "update_scope": "skill_gems", "records": 3,
                                  "oldest_fetched_at": FETCHED, "newest_fetched_at": FETCHED,
                                  "oldest_age_days": sets["skill_gems"]["oldest_age_days"]}
    assert isinstance(sets["skill_gems"]["oldest_age_days"], int) and sets["skill_gems"]["oldest_age_days"] >= 0
    assert (sets["spirit_gems"]["records"], sets["support_gems"]["records"]) == (1, 2)
    assert sets["passives"]["records"] == len(read_jsonl(base / NODES)) and sets["passives"]["update_scope"] == "passives"
    assert sets["glossary"]["update_scope"] is None and "terminal only" in sets["glossary"]["note"]
    assert sets["ladder"] == {"name": "ladder", "update_scope": None, "note": mnt.NOT_UPDATABLE["ladder"],
                              "league": None, "records": 0, "oldest_fetched_at": None, "newest_fetched_at": None,
                              "oldest_age_days": None}
    assert sets["entity_index"]["records"] == len(read_jsonl(base / INDEX)) and sets["entity_index"]["newest_built_at"]
    assert status["version"] == __version__ and status["writable"] is True and status["data_dir"] == str(base / "data")
    assert status["catalog"] == {"spec_version": tool.spec.raw["spec_version"], "verified_at": tool.spec.raw["verified_at"],
                                 "pob2_tree_version": "0_5", "tree_data_version": "4.5"}
    assert status["update_scopes"] == ["skill_gems", "spirit_gems", "support_gems", "passives"]
    assert set(status["not_updatable"]) == {"glossary", "ladder"}


def test_status_of_an_empty_folder_is_zeros_not_an_error(tmp_path):
    status = mnt.DataMaintenance(tmp_path, fixture_spec()).status()
    assert status["writable"] is False
    assert all(d["records"] == 0 and d["oldest_age_days"] is None for d in status["datasets"])


def test_status_reads_the_ladder_snapshot(tool, base):
    path = base / "data" / "community_builds" / "poe_ninja_builds.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(fixture_text("jsonl", "poe_ninja_builds.jsonl"), encoding="utf-8")
    ladder = next(d for d in tool.status()["datasets"] if d["name"] == "ladder")
    rows = read_jsonl(path)
    assert ladder["records"] == len(rows) and ladder["league"] == rows[0]["league"]
    assert ladder["newest_fetched_at"] == max(r["fetched_at"] for r in rows)


@pytest.mark.parametrize("stamp, expected", [
    ((datetime.now(timezone.utc) - timedelta(days=40, hours=1)).isoformat(), 40),
    ((datetime.now(timezone.utc) + timedelta(days=3)).isoformat(), 0),
    ((datetime.now(timezone.utc) - timedelta(days=2, hours=1)).replace(tzinfo=None).isoformat(), 2),
    ("not a date", None), (None, None), ("", None),
])
def test_age_in_days(stamp, expected):
    assert mnt._age_days(stamp) == expected


@pytest.fixture
def probe_tool(base, monkeypatch):
    """The probe fixtures cover English pages only, and some sections hold no rows."""
    monkeypatch.setattr(mnt, "PROBE_LANGS", ["en"])
    return mnt.DataMaintenance(base, fixture_spec(listing_min=0), base / GRAPH_REL)


def test_online_check_reports_no_problem_when_the_sites_parse(probe_tool, base):
    report = probe_tool.online_check(fetch=make_fake())
    assert report["ok"] is True and report["problems"] == []
    assert report["requests"] >= 10 and report["checks"] >= report["requests"]
    assert not (base / "output").exists()                       # the probe's metrics file is not written


def test_online_check_reports_a_newer_passive_tree(probe_tool):
    report = probe_tool.online_check(fetch=make_fake(api_body=json.dumps([{"name": "0_5"}, {"name": "0_6"}])))
    assert report["ok"] is False
    [problem] = report["problems"]
    assert problem["source"] == "pob2_tree" and "latest 0_6" in problem["error"]
    assert set(problem) == {"source", "section", "lang", "count", "expect_min", "error"}


def test_online_check_reports_unreachable_pages_as_problems(probe_tool):

    def down(url):
        raise requests.ConnectionError("offline")

    report = probe_tool.online_check(fetch=down)
    assert report["ok"] is False and report["problems"] and all("offline" in p["error"] for p in report["problems"])


# -- update: gem scopes ------------------------------------------------------------------------

def test_first_gem_update_fetches_new_and_changed_gems_and_rebuilds_the_index(tool, base):
    web = Web()
    graph_before = (base / GRAPH_REL).read_bytes()
    result = tool.update("skill_gems", fetch=web)
    assert result == {"scope": "skill_gems", "dry_run": False, "selected": 3, "updated": 3, "left": 0,
                      "reasons": {"new": 1, "listing_changed": 2}, "recently_updated": 0, "added": ["Grim_Feast"],
                      "removed": ["Contagion"], "skipped": [], "records": 3,
                      "index_entities": result["index_entities"], "requests": 5}
    assert {r["slug"]: r["name"] for r in read_jsonl(base / SKILL_DETAIL)} == {
        "Leap_Slam": "Leap Slam", "Unearth": "Unearth", "Grim_Feast": "Grim Feast"}       # each record is its own page
    assert web.calls[0] == LISTING_US and web.calls[-1] == LISTING_TW
    assert sorted(web.details()) == ["Grim_Feast", "Leap_Slam", "Unearth"]
    assert slugs(base) == ["Grim_Feast", "Leap_Slam", "Unearth"]
    names = index_names(base)
    assert names["Grim_Feast"] == "殘酷盛宴" and names["Leap_Slam"] == "躍擊" and "Contagion" not in names
    assert names["Herald_of_Ash"] == "灰燼信使"                  # other scopes keep their Chinese names
    assert result["index_entities"] == len(names)
    assert (base / GRAPH_REL).read_bytes() != graph_before and b"Grim_Feast" in (base / GRAPH_REL).read_bytes()
    assert LookupService(base, fixture_spec(), base / GRAPH_REL).get_gem("殘酷盛宴")["gem"]["slug"] == "Grim_Feast"


def test_second_gem_update_finds_nothing_to_fetch(tool, base):
    tool.update("skill_gems", fetch=Web())
    web = Web()
    result = tool.update("skill_gems", fetch=web)
    assert web.calls == [LISTING_US]
    assert (result["selected"], result["updated"], result["left"], result["added"], result["requests"]) == (0, 0, 0, [], 1)


def test_dry_run_reports_and_writes_nothing(tool, base):
    before = snapshot(base)
    web = Web()
    result = tool.update("skill_gems", dry_run=True, fetch=web)
    assert web.calls == [LISTING_US] and snapshot(base) == before
    assert result == {"scope": "skill_gems", "dry_run": True, "selected": 3, "updated": 0, "left": 3,
                      "reasons": {"new": 1, "listing_changed": 2}, "recently_updated": 0, "added": ["Grim_Feast"],
                      "removed": ["Contagion"], "skipped": [], "records": 3, "requests": 1}


def test_capped_update_is_finished_by_repeating_the_call(tool, base):
    updated, lefts = 0, []
    for _ in range(5):
        result = tool.update("skill_gems", max_gems=1, fetch=Web())
        updated += result["updated"]
        lefts.append(result["left"])
        if result["left"] == 0:
            break
    assert lefts == [2, 1, 0] and updated == 3
    assert slugs(base) == ["Grim_Feast", "Leap_Slam", "Unearth"] and index_names(base)["Grim_Feast"] == "殘酷盛宴"


@pytest.mark.parametrize("name", ["Leap Slam", "Leap_Slam", "躍擊", "leap slam"])
def test_named_gem_is_refetched(tool, base, name):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    web = Web()
    result = tool.update("skill_gems", names=[name], fetch=web)
    assert web.details() == ["Leap_Slam"] and result["reasons"] == {"requested": 1} and result["updated"] == 1


def test_unknown_name_is_refused_before_any_request(tool, base):
    web = Web()
    with pytest.raises(BadArgument, match=r"not a skill_gem in the local data: 'Leap'.*close: Leap Slam.*Nothing was fetched"):
        tool.update("skill_gems", names=["Leap"], fetch=web)
    with pytest.raises(BadArgument, match="not a skill_gem in the local data: 'Herald of Ash'"):
        tool.update("skill_gems", names=["Herald of Ash"], fetch=web)       # a spirit gem
    assert web.calls == []


def test_older_than_selects_stale_gems(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    result = tool.update("skill_gems", older_than_days=0, dry_run=True, fetch=Web())
    assert result["reasons"] == {"stale": 3} and result["selected"] == 3
    assert tool.update("skill_gems", older_than_days=30, dry_run=True, fetch=Web())["selected"] == 0


@pytest.mark.parametrize("scope", [" SKILL_GEMS ", "Skill_Gems"])
def test_scope_ignores_case_and_spaces(tool, scope):
    assert tool.update(scope, dry_run=True, fetch=Web())["scope"] == "skill_gems"


@pytest.mark.parametrize("scope, message", [
    ("", "scope is required and must be one of: skill_gems, spirit_gems, support_gems, passives"),
    (None, "scope is required"),
    ("all", "there is no update for everything"),
    ("gems", "scope is required"),
    ("x" * 5000, "scope is required"),
    ("glossary", "glossary cannot be updated by command: terminal only"),
    ("ladder", "ladder cannot be updated by command"),
])
def test_missing_or_unknown_scope_is_refused_without_a_request(tool, base, scope, message):
    web, before = Web(), snapshot(base)
    with pytest.raises(BadArgument, match=message) as caught:
        tool.update(scope, fetch=web)
    assert web.calls == [] and snapshot(base) == before and "xxxxxxxx" not in str(caught.value)


@pytest.mark.parametrize("options, message", [
    ({"max_gems": 0}, "max_gems must be between 1 and 40"),
    ({"max_gems": 41}, "max_gems must be between 1 and 40"),
    ({"older_than_days": -1}, "older_than_days must be between 0 and 3650"),
    ({"older_than_days": 10**6}, "older_than_days must be between 0 and 3650"),
    ({"older_than_days": 1.5}, "older_than_days must be a whole number"),
    ({"older_than_days": True}, "older_than_days must be a whole number"),
    ({"max_gems": True}, "max_gems must be a whole number"),
    ({"max_gems": "5"}, "max_gems must be a whole number"),
    ({"names": ["a"] * 41}, "at most 40 names"),
    ({"names": ["x" * 121]}, "a name is longer than 120 characters"),
    ({"names": ["  "]}, "names must be non-empty strings"),
    ({"names": [5]}, "names must be non-empty strings"),
])
def test_bad_gem_options_are_refused_without_a_request(tool, options, message):
    web = Web()
    with pytest.raises(BadArgument, match=message):
        tool.update("skill_gems", fetch=web, **options)
    assert web.calls == []


def test_listing_below_the_expected_count_aborts_with_nothing_written(base):
    tool = mnt.DataMaintenance(base, fixture_spec(listing_min=5), base / GRAPH_REL)
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match=r"below expect_min=5.*Nothing was written.*check_online=true"):
        tool.update("skill_gems", fetch=Web())
    assert snapshot(base) == before


def test_network_error_aborts_with_nothing_written(tool, base):
    before = snapshot(base)

    def down(url):
        raise requests.ConnectionError("no route")

    with pytest.raises(ServiceUnavailable, match="network error: no route. Nothing was written"):
        tool.update("skill_gems", fetch=down)
    assert snapshot(base) == before


def test_unwritable_data_folder_refuses_the_update_but_allows_a_dry_run(tool, monkeypatch):
    monkeypatch.setattr(mnt.os, "access", lambda path, mode: False)
    web = Web()
    with pytest.raises(ServiceUnavailable, match="is not writable; nothing was fetched"):
        tool.update("skill_gems", fetch=web)
    assert web.calls == []
    assert tool.update("skill_gems", dry_run=True, fetch=web)["selected"] == 3


def test_only_one_update_runs_at_a_time_and_the_lock_is_released(tool, base):
    web = Web()
    with DATA_LOCK:
        with pytest.raises(ServiceUnavailable, match="already running"):
            tool.update("skill_gems", fetch=web)
    assert web.calls == []
    with pytest.raises(BadArgument):
        tool.update("skill_gems", names=["nope"], fetch=web)                # fails inside the lock
    assert tool.update("skill_gems", fetch=web)["updated"] == 3             # the lock was released both times


def test_missing_index_is_rebuilt_within_the_request_bound(tool, base):
    (base / INDEX).unlink()
    web = Web()
    result = tool.update("skill_gems", max_gems=1, fetch=web)
    assert [u for u in web.calls if u.startswith("https://poe2db.tw/tw/")] == [LISTING_TW]      # this scope's page only
    assert result["requests"] == 3                                    # listing + one gem + one /tw/ listing
    names = index_names(base)
    assert names["Leap_Slam"] == "躍擊" and names["Herald_of_Ash"] is None and result["index_entities"] == len(names)


def test_passives_update_without_an_index_stays_at_seven_requests(tool, base, lenient_stats):
    (base / INDEX).unlink()
    web = Web()
    assert tool.update("passives", fetch=web)["requests"] == 7 == len(web.calls)
    assert (base / INDEX).exists()


def test_failed_index_rebuild_says_how_to_repair_and_the_next_update_repairs_it(tool, base, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("duplicate slug")

    monkeypatch.setattr(mnt, "build_entity_index", broken)
    with pytest.raises(ServiceUnavailable, match=r"not rebuilt \(duplicate slug\).*run the same update again"):
        tool.update("skill_gems", fetch=Web())
    assert slugs(base) == ["Grim_Feast", "Leap_Slam", "Unearth"] and "Grim_Feast" not in index_names(base)
    monkeypatch.undo()
    web = Web()
    assert tool.update("skill_gems", fetch=web)["selected"] == 0
    assert web.calls == [LISTING_US, LISTING_TW]                   # the repair fetches the missing Chinese names
    assert index_names(base)["Grim_Feast"] == "殘酷盛宴" and index_names(base)["Leap_Slam"] == "躍擊"


def test_update_prints_nothing_to_stdout(tool, capsys):
    tool.update("skill_gems", fetch=Web())
    assert capsys.readouterr().out == ""


def test_update_without_a_graph_file_does_not_create_one(tool, base):
    (base / GRAPH_REL).unlink()
    tool.update("skill_gems", fetch=Web())
    assert not (base / GRAPH_REL).exists()


def test_update_leaves_no_cache_or_temporary_files_in_the_data_folder(tool, base):
    before = set(snapshot(base))
    tool.update("skill_gems", fetch=Web())
    added = set(snapshot(base)) - before
    assert added == {"data/skill_gems/Skill_Gems_Listing.jsonl"}
    assert not (base / "output").exists()


# -- update: passives --------------------------------------------------------------------------

def test_passives_update_with_too_few_parsed_stat_lines_writes_nothing(tool, base):
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match=r"only 64% of the passive stat lines parsed. Nothing was written"):
        tool.update("passives", fetch=Web())
    assert snapshot(base) == before and mnt.MIN_PARSED_RATIO == 0.8


def test_passives_update_replaces_the_tree_and_the_stat_index(tool, base, lenient_stats):
    old_nodes, old_stats = (base / NODES).read_bytes(), (base / STATS).read_bytes()
    web = Web()
    result = tool.update("passives", fetch=web)
    assert sorted(web.calls) == sorted(PASSIVE_PAGES) and result["requests"] == 7
    nodes = read_jsonl(base / NODES)
    assert result["scope"] == "passives" and result["dry_run"] is False
    assert result["records"] == len(nodes) > 10 and result["stat_lines"] == len(read_jsonl(base / STATS)) > 0
    assert (result["tree_version"], result["tree_data_version"]) == ("0_5", "4.5")
    assert (base / NODES).read_bytes() != old_nodes and (base / STATS).read_bytes() != old_stats
    assert result["added"] + result["changed"] > 0 and result["removed"] >= 0
    classes = json.loads((base / "data" / "passive_tree" / "classes.json").read_text(encoding="utf-8"))
    assert classes["version"] == "4.5" and classes["fetched_at"] > FETCHED and classes["classes"]
    assert result["index_entities"] == len(index_names(base))
    assert slugs(base) == ["Contagion", "Leap_Slam", "Unearth"]            # gems are not touched
    passives = next(d for d in tool.status()["datasets"] if d["name"] == "passives")
    assert passives["records"] == len(nodes) and passives["tree_data_version"] == "4.5"


@pytest.mark.parametrize("options", [{"names": ["Blood Magic"]}, {"older_than_days": 3}, {"dry_run": True},
                                     {"max_gems": 5}])
def test_passives_takes_no_gem_options(tool, options):
    web = Web()
    with pytest.raises(BadArgument, match="only apply to the gem scopes"):
        tool.update("passives", fetch=web, **options)
    assert web.calls == []


def test_passives_update_that_fails_validation_writes_nothing(base, lenient_stats):
    raw = copy.deepcopy(fixture_spec().raw)
    raw["sources"]["pob2_tree"]["expect_min"]["nodes"] = 100_000
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match="Nothing was written"):
        mnt.DataMaintenance(base, Spec(raw), base / GRAPH_REL).update("passives", fetch=Web())
    assert snapshot(base) == before


def test_passives_update_with_a_changed_tree_format_writes_nothing(tool, base, lenient_stats):
    before = snapshot(base)

    def reshaped(url):
        return json.dumps({"nodes": {"1": {"name": "x"}}}) if url == TREE_URL else Web()(url)

    with pytest.raises(ServiceUnavailable, match="Nothing was written"):
        tool.update("passives", fetch=reshaped)
    assert snapshot(base) == before


# -- repeated calls come to an end -------------------------------------------------------------

def repeat(tool, base, **options):
    """Call update until nothing is left, as the command texts tell a client to do."""
    fetched, lefts = [], []
    for _ in range(8):
        web = Web()
        result = tool.update("skill_gems", fetch=web, **options)
        fetched += web.details()
        lefts.append(result["left"])
        if result["left"] == 0:
            return fetched, lefts, result
    pytest.fail(f"update never finished: left={lefts}")


def test_more_names_than_the_cap_are_each_fetched_once_and_the_series_ends(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    fetched, lefts, last = repeat(tool, base, names=["Leap_Slam", "Unearth", "Grim_Feast"], max_gems=1)
    assert sorted(fetched) == ["Grim_Feast", "Leap_Slam", "Unearth"] and lefts == [2, 1, 0]
    assert last["recently_updated"] == 2                               # the two fetched by the earlier calls


def test_older_than_zero_days_fetches_every_gem_once_and_the_series_ends(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    fetched, lefts, _ = repeat(tool, base, older_than_days=0, max_gems=2)
    assert sorted(fetched) == ["Grim_Feast", "Leap_Slam", "Unearth"] and lefts == [1, 0]


def test_gem_fetched_a_moment_ago_is_not_fetched_again_by_name(tool, base):
    tool.update("skill_gems", fetch=Web())
    web = Web()
    result = tool.update("skill_gems", names=["Leap Slam"], fetch=web)
    assert web.details() == [] and result["selected"] == 0 and result["recently_updated"] == 1
    assert result["reasons"] == {}


def test_new_and_changed_gems_ignore_the_recent_window(tool, base):
    tool.update("skill_gems", fetch=Web())
    changed = html("listing_skill_us.html").replace("Leap Slam</a> (7)", "Leap Slam</a> (9)")
    web = Web(changed)
    assert tool.update("skill_gems", fetch=web)["reasons"] == {"listing_changed": 1} and web.details() == ["Leap_Slam"]


# -- failures while writing, other processes, unreadable files ---------------------------------

def test_one_page_that_fails_is_reported_as_skipped_and_does_not_block_the_rest(tool, base):
    web = Web(broken=("Grim_Feast",))
    result = tool.update("skill_gems", fetch=web)
    assert result["skipped"] == ["Grim_Feast"] and result["updated"] == 2 and result["left"] == 0
    assert slugs(base) == ["Leap_Slam", "Unearth"] and result["added"] == []
    again = tool.update("skill_gems", fetch=Web())
    assert again["added"] == ["Grim_Feast"] and again["reasons"] == {"new": 1}       # picked up once the page works


def test_two_pages_that_fail_abort_with_nothing_written(tool, base):
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match=r"2 of 3 detail pages failed.*Nothing was written"):
        tool.update("skill_gems", fetch=Web(broken=("Grim_Feast", "Unearth")))
    assert snapshot(base) == before


def test_gem_scope_without_local_data_is_sent_to_the_terminal(tool, base):
    (base / SKILL_DETAIL).unlink()
    web = Web()
    with pytest.raises(ServiceUnavailable, match="no local skill_gems data to update; a first crawl is done in a terminal"):
        tool.update("skill_gems", fetch=web)
    assert web.calls == []


def test_failed_write_in_a_passives_update_says_files_may_be_half_updated(tool, base, lenient_stats, monkeypatch):
    def full_disk(*args, **kwargs):
        raise OSError("No space left on device")

    with monkeypatch.context() as patch:
        patch.setattr(mnt, "write_stat_index", full_disk)
        with pytest.raises(ServiceUnavailable, match=r"could not be written \(No space left on device\).*run the same update again"):
            tool.update("passives", fetch=Web())
    assert tool.update("passives", fetch=Web())["stat_lines"] == len(read_jsonl(base / STATS))    # the rerun finishes it


def test_failed_write_in_a_gem_update_says_files_may_be_half_updated(tool, monkeypatch):
    from src.scrapers import collect_gems

    def full_disk(path, records):
        raise OSError("disk full")

    monkeypatch.setattr(collect_gems, "write_jsonl", full_disk)
    with pytest.raises(ServiceUnavailable, match=r"could not be written \(disk full\).*run the same update again"):
        tool.update("skill_gems", fetch=Web())


def test_another_process_holding_the_data_folder_blocks_the_update_but_not_a_dry_run(tool, base):
    lock = base / "data" / DATA_LOCK_FILE
    lock.write_text("4242 other process\n", encoding="utf-8")
    web, before = Web(), snapshot(base)
    with pytest.raises(ServiceUnavailable, match="another process is updating this data folder"):
        tool.update("skill_gems", fetch=web)
    assert web.calls == [] and snapshot(base) == before and lock.exists()
    assert tool.update("skill_gems", dry_run=True, fetch=web)["selected"] == 3


def test_lock_left_behind_by_a_dead_process_is_taken_over(tool, base):
    lock = base / "data" / DATA_LOCK_FILE
    lock.write_text("4242 crashed\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    assert tool.update("skill_gems", fetch=Web())["updated"] == 3
    assert not lock.exists()


def test_refresh_gem_respects_another_process_and_releases_its_own_lock(base):
    service = LookupService(base, fixture_spec(), base / GRAPH_REL)
    lock = base / "data" / DATA_LOCK_FILE
    lock.write_text("4242 other process\n", encoding="utf-8")
    with pytest.raises(ServiceUnavailable, match="another process is updating this data folder"):
        service.refresh_gem("Leap_Slam", fetcher=Web())
    lock.unlink()
    assert service.refresh_gem("Leap_Slam", fetcher=Web())["slug"] == "Leap_Slam"
    assert not lock.exists()


def test_update_removes_its_lock_file_even_when_it_fails(tool, base):
    with pytest.raises(BadArgument):
        tool.update("skill_gems", names=["nope"], fetch=Web())
    with pytest.raises(ServiceUnavailable):
        tool.update("skill_gems", fetch=Web(broken=("Grim_Feast", "Unearth")))
    assert not (base / "data" / DATA_LOCK_FILE).exists()


def test_online_check_does_not_run_alongside_an_update(probe_tool):
    with DATA_LOCK:
        with pytest.raises(ServiceUnavailable, match="already running"):
            probe_tool.online_check(fetch=make_fake())
    assert probe_tool.online_check(fetch=make_fake())["ok"] is True     # and it released the lock afterwards


def test_status_reports_an_unreadable_file_and_still_lists_the_rest(tool, base):
    (base / SKILL_DETAIL).write_text("{not json\n", encoding="utf-8")
    (base / NODES).write_text("{not json\n", encoding="utf-8")
    sets = {d["name"]: d for d in tool.status()["datasets"]}
    assert sets["skill_gems"]["records"] == 0 and sets["skill_gems"]["error"].startswith("unreadable")
    assert sets["passives"]["records"] == 0 and sets["passives"]["error"].startswith("unreadable")
    assert sets["spirit_gems"]["records"] == 1 and "error" not in sets["spirit_gems"]


def test_status_without_the_classes_file_still_counts_the_nodes(tool, base):
    (base / "data" / "passive_tree" / "classes.json").unlink()
    passives = next(d for d in tool.status()["datasets"] if d["name"] == "passives")
    assert passives["records"] > 0 and passives["tree_data_version"] is None and passives["oldest_age_days"] is None
