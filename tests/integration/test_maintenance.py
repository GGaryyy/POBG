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
from src.scrapers.common import DATA_LOCK_FILE, LockBusy, file_lock, read_jsonl, write_jsonl
from src.tools import maintenance as mnt
from src.tools.lookup import DATA_LOCK, BadArgument, LookupService, ServiceUnavailable
from tests.kg_support import FETCHED, GRAPH_REL, build_full_environment
from tests.support import fixture_text, html, lowered_spec
from tests.ninja_support import LEAGUE, FakeNinja, characters
from tests.unit.test_collect_glossary import hover, link
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
    """Every data file; the lock file is not data (it stays in place, only the OS lock on it is released)."""
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*"))
            if p.is_file() and p.name != DATA_LOCK_FILE}


def lock_is_free(base) -> bool:
    try:
        with file_lock(base / "data" / DATA_LOCK_FILE):
            return True
    except LockBusy:
        return False


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
    assert sets["glossary"]["update_scope"] == "glossary" and sets["glossary"]["records"] == 7
    assert sets["ladder"] == {"name": "ladder", "update_scope": "ladder", "league": None, "records": 0,
                              "oldest_fetched_at": None, "newest_fetched_at": None, "oldest_age_days": None}
    assert sets["entity_index"]["records"] == len(read_jsonl(base / INDEX)) and sets["entity_index"]["newest_built_at"]
    assert status["version"] == __version__ and status["writable"] is True and status["data_dir"] == str(base / "data")
    assert status["catalog"] == {"spec_version": tool.spec.raw["spec_version"], "verified_at": tool.spec.raw["verified_at"],
                                 "pob2_tree_version": "0_5", "tree_data_version": "4.5"}
    assert status["update_scopes"] == ["skill_gems", "spirit_gems", "support_gems", "passives", "glossary", "ladder"]
    assert status["not_updatable"] == {}
    assert {d["name"] for d in status["datasets"] if d["update_scope"]} == set(status["update_scopes"])


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
    ("", "scope is required and must be one of: skill_gems, spirit_gems, support_gems, passives, glossary, ladder"),
    (None, "scope is required"),
    ("all", "there is no update for everything"),
    ("gems", "scope is required"),
    ("x" * 5000, "scope is required"),
    ("items", "scope is required"),
    ("entity_index", "scope is required"),
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


@pytest.mark.parametrize("scope", ["passives", "glossary", "ladder"])
@pytest.mark.parametrize("options", [{"names": ["Blood Magic"]}, {"older_than_days": 3}, {"dry_run": True},
                                     {"max_gems": 5}])
def test_whole_set_scopes_take_no_gem_options(tool, scope, options):
    web = Web()
    with pytest.raises(BadArgument, match=f"only apply to the gem scopes; a {scope} update always"):
        tool.update(scope, fetch=web, **options)
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
    with pytest.raises(ServiceUnavailable, match=r"2 detail pages failed.*Nothing was written"):
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
    web, before = Web(), snapshot(base)
    with file_lock(base / "data" / DATA_LOCK_FILE):           # held through another open file, as by another process
        with pytest.raises(ServiceUnavailable, match="another process is updating this data folder"):
            tool.update("skill_gems", fetch=web)
        assert web.calls == [] and snapshot(base) == before
        assert tool.update("skill_gems", dry_run=True, fetch=web)["selected"] == 3


def test_lock_file_left_behind_by_a_dead_process_does_not_block(tool, base):
    (base / "data" / DATA_LOCK_FILE).write_text("4242 crashed\n", encoding="utf-8")
    assert tool.update("skill_gems", fetch=Web())["updated"] == 3
    assert lock_is_free(base)


def test_refresh_gem_respects_another_process_and_releases_its_own_lock(base):
    service = LookupService(base, fixture_spec(), base / GRAPH_REL)
    with file_lock(base / "data" / DATA_LOCK_FILE):
        with pytest.raises(ServiceUnavailable, match="another process is updating this data folder"):
            service.refresh_gem("Leap_Slam", fetcher=Web())
    assert service.refresh_gem("Leap_Slam", fetcher=Web())["slug"] == "Leap_Slam"
    assert lock_is_free(base)


def test_update_releases_its_lock_even_when_it_fails(tool, base):
    with pytest.raises(BadArgument):
        tool.update("skill_gems", names=["nope"], fetch=Web())
    with pytest.raises(ServiceUnavailable):
        tool.update("skill_gems", fetch=Web(broken=("Grim_Feast", "Unearth")))
    assert lock_is_free(base)


def test_online_check_waits_for_no_one_and_is_refused_while_another_process_updates(probe_tool, base):
    with file_lock(base / "data" / DATA_LOCK_FILE):
        with pytest.raises(ServiceUnavailable, match="another process is updating this data folder"):
            probe_tool.online_check(fetch=make_fake())
    assert lock_is_free(base)


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


# -- update: ladder ----------------------------------------------------------------------------

LADDER = "data/community_builds/poe_ninja_builds.jsonl"


@pytest.fixture
def ninja(monkeypatch):
    """poe.ninja as the ladder fetcher sees it; 120 synthetic characters with secret-looking names."""
    site = FakeNinja()
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    return site


def test_ladder_update_writes_a_snapshot_without_names(tool, base, ninja):
    result = tool.update("ladder")
    assert result == {"scope": "ladder", "dry_run": False, "records": 120, "league": LEAGUE, "previous_records": 0,
                      "previous_league": None, "requests": len(ninja.calls)}
    assert result["requests"] == 14                                # index, 10 result pages, 3 dictionaries
    rows = read_jsonl(base / LADDER)
    assert len(rows) == 120 and "Secret" not in (base / LADDER).read_text(encoding="utf-8")
    assert sorted(rows[0]) == ["class", "fetched_at", "keystones", "league", "level", "main_skill", "rank",
                               "skill_gems", "source"]
    ladder = next(d for d in tool.status()["datasets"] if d["name"] == "ladder")
    assert ladder["records"] == 120 and ladder["league"] == LEAGUE and ladder["oldest_age_days"] == 0
    assert lock_is_free(base)


def test_ladder_update_reports_the_league_it_replaced(tool, base, ninja):
    (base / LADDER).parent.mkdir(parents=True)
    (base / LADDER).write_text(fixture_text("jsonl", "poe_ninja_builds.jsonl"), encoding="utf-8")
    old = read_jsonl(base / LADDER)
    result = tool.update("ladder")
    assert result["previous_records"] == len(old) and result["previous_league"] == old[0]["league"] != LEAGUE


def test_ladder_update_prints_nothing_to_stdout_and_no_names_anywhere(tool, ninja, capsys):
    tool.update("ladder")
    out, err = capsys.readouterr()
    assert out == "" and "Secret" not in err


def test_small_ladder_answer_keeps_the_old_snapshot(tool, base, monkeypatch):
    site = FakeNinja(characters(40))
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match=r"returned 40 characters.*format has probably changed. The old snapshot is kept"):
        tool.update("ladder")
    assert snapshot(base) == before and mnt.MIN_LADDER_ROWS == 100


def test_ladder_answer_without_class_names_keeps_the_old_snapshot(tool, base, monkeypatch):
    site = FakeNinja(dictionaries={"gem": ["Arc", "Comet", "Fireball", "Leap Slam", "Spark"]})     # class dictionary empty
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match="120 characters, 0 with a class"):
        tool.update("ladder")
    assert snapshot(base) == before


def test_ladder_network_error_keeps_the_old_snapshot(tool, base, monkeypatch):
    def down(url):
        raise requests.ConnectionError("poe.ninja unreachable")

    monkeypatch.setattr(mnt.ladder, "_get_json", down)
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match="network error: poe.ninja unreachable. Nothing was written"):
        tool.update("ladder")
    assert snapshot(base) == before


def test_ladder_answer_in_an_unexpected_shape_keeps_the_old_snapshot(tool, base, monkeypatch):
    site = FakeNinja(index_state={"buildLeagues": [], "snapshotVersions": []})
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    before = snapshot(base)
    with pytest.raises(ServiceUnavailable, match=r"unexpected shape \(RuntimeError: No build leagues"):
        tool.update("ladder")
    assert snapshot(base) == before


# -- update: glossary --------------------------------------------------------------------------

KEYWORDS = "data/kg/keywords.jsonl"
HOVER = "https://cdn.poe2db.tw/cache2/{lang}/Poe_Data_KeywordPopups_hover/{hash}"
HOVERS = {
    ("us", "b1"): hover("Chaos_Damage", "Chaos Damage", "Chaos bypasses shields. " + link("us", "Wither", "e7", "Wither")),
    ("us", "b2"): hover("Armour", "Armour", "Armour lowers physical hits."),
    ("us", "f1"): hover("Cold_Damage", "Cold Damage", "Cold chills."),
    ("us", "aa03"): hover("Stun", "Stun", "A stunned enemy stops. " + link("us", "Freeze", "c9", "Freeze")),
    ("us", "aa04"): hover("Critical_Hits", "Critical Hit", "A lucky hit."),
    ("us", "c9"): hover("Freeze", "Freeze", "Frozen solid."),
    ("us", "e7"): hover("Wither", "Wither", "Withered enemies take more Chaos Damage."),
    ("tw", "d1"): hover("Chaos_Damage", "混沌傷害", "混沌傷害無視護盾。"),
    ("tw", "d2"): hover("Armour", "護甲", "護甲降低物理傷害。"),
    ("tw", "9a"): hover("Cold_Damage", "冰冷傷害", "冰冷會冰緩。"),
}
CARD_PAGES = {"https://poe2db.tw/us/Keystone": "passive_keystone_cards_en.html",
              "https://poe2db.tw/tw/Keystone": "passive_keystone_cards_zh.html",
              "https://poe2db.tw/us/Notable": "passive_notable_cards_en.html",
              "https://poe2db.tw/tw/Notable": "passive_notable_cards_zh.html"}
GEM_LISTINGS = [f"https://poe2db.tw/{lang}/{page}" for lang in ("us", "tw") for page in ("Skill_Gems", "Spirit_Gems", "Support_Gems")]
GEM_PAGES = ["https://poe2db.tw/us/Leap_Slam", "https://poe2db.tw/us/Unearth"]         # mention Stun / Critical_Hits / Minions
FULL_GLOSSARY_REQUESTS = len(CARD_PAGES) + len(GEM_LISTINGS) + len(GEM_PAGES) + len(HOVERS)


class GlossarySite:
    def __init__(self, hovers=None):
        self.calls: list[str] = []
        self.hovers = HOVERS if hovers is None else hovers

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url in CARD_PAGES:
            return fixture_text("html", CARD_PAGES[url])
        if url in GEM_LISTINGS:
            return '<div class="tab-pane" id="x"><p>' + "no glossary links here, only padding " * 3 + "</p></div>"
        if url in GEM_PAGES:
            return html("detail_skill_keywords.html")
        for (lang, hash_), body in self.hovers.items():
            if url == HOVER.format(lang=lang, hash=hash_):
                return body
        raise requests.ConnectionError(f"no fixture for {url}")


@pytest.fixture
def lenient_glossary(monkeypatch):
    """Six of the seven fixture terms are reachable; the real 90 % rule is tested on its own."""
    monkeypatch.setattr(mnt, "MIN_GLOSSARY_KEPT_RATIO", 0.8)


def test_glossary_update_refreshes_reachable_terms_and_keeps_the_rest(tool, base, lenient_glossary):
    old = {e["slug"]: e for e in read_jsonl(base / KEYWORDS)}
    site = GlossarySite()
    result = tool.update("glossary", fetch=site)
    assert result == {"scope": "glossary", "dry_run": False, "done": True, "left": 0, "records": 8, "refreshed": 7,
                      "changed": 6, "added": ["Wither"], "kept_without_refresh": 1, "failed_requests": 0,
                      "index_entities": result["index_entities"], "requests": FULL_GLOSSARY_REQUESTS}
    assert sorted(site.calls) == sorted([*CARD_PAGES, *GEM_LISTINGS, *GEM_PAGES,
                                         *(HOVER.format(lang=lang, hash=h) for lang, h in HOVERS)])
    new = {e["slug"]: e for e in read_jsonl(base / KEYWORDS)}
    assert list(new) == sorted(new) and set(new) == set(old) | {"Wither"}
    assert new["Chaos_Damage"]["text_en"].startswith("Chaos bypasses shields.") and new["Chaos_Damage"]["text_zh_tw"] == "混沌傷害無視護盾。"
    assert new["Chaos_Damage"]["see_also"] == ["Wither"] and new["Stun"]["see_also"] == ["Freeze"]
    assert new["Freeze"]["text_en"] == "Frozen solid."                          # found through Stun
    assert new["Freeze"]["fetched_at"] == FETCHED        # its Chinese name is the old one, so the old date stays
    assert new["Chaos_Damage"]["fetched_at"] > FETCHED   # both languages refreshed: new date
    assert new["Minions"] == old["Minions"]                                    # not reachable: kept as it was
    # the fixture site has no Chinese hover for Stun or Critical Hit: their old Chinese text must survive
    assert new["Stun"]["text_zh_tw"] == old["Stun"]["text_zh_tw"] and new["Stun"]["name_zh_tw"] == "暈眩"
    assert new["Critical_Hits"]["text_zh_tw"] == old["Critical_Hits"]["text_zh_tw"]
    assert new["Stun"]["text_en"].startswith("A stunned enemy stops.") and new["Freeze"]["name_zh_tw"] == "冰凍"
    for field in ("name_en", "name_zh_tw", "text_en", "text_zh_tw"):
        assert not [slug for slug in old if old[slug].get(field) and not new[slug].get(field)], field
    assert index_names(base).get("Wither", "missing") is None                  # indexed, no Chinese name yet
    assert not (base / "output" / "cache" / "glossary_update").exists()        # the run cache is gone


def test_glossary_update_in_small_batches_fetches_every_page_exactly_once(tool, base, lenient_glossary, monkeypatch):
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)
    before = snapshot(base)
    calls, lefts = [], []
    for _ in range(12):
        site = GlossarySite()
        result = tool.update("glossary", fetch=site)
        calls += site.calls
        lefts.append(result["left"])
        if result["done"]:
            break
        assert result == {"scope": "glossary", "dry_run": False, "done": False, "left": result["left"], "fetched": 6,
                          "note": result["note"], "requests": 6}
        assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == \
               {k: v for k, v in before.items() if k.startswith("data/")}          # nothing written until done
    assert result["done"] is True and result["records"] == 8
    assert len(calls) == FULL_GLOSSARY_REQUESTS == len(set(calls))             # resumed, never fetched twice
    assert all(left > 0 for left in lefts[:-1]) and lefts[-1] == 0 and len(lefts) == 4


def test_glossary_run_cache_that_is_too_old_is_started_again(tool, base, lenient_glossary, monkeypatch):
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)
    first = GlossarySite()
    assert tool.update("glossary", fetch=first)["done"] is False
    run = base / "output" / "cache" / "glossary_update"
    old = time.time() - mnt.GLOSSARY_RUN_SECONDS - 60
    for path in run.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    second = GlossarySite()
    tool.update("glossary", fetch=second)
    assert second.calls == first.calls                                         # the same first six pages again


def test_glossary_that_reaches_too_few_known_terms_is_not_written(tool, base):
    before = {k: v for k, v in snapshot(base).items() if k.startswith("data/")}
    with pytest.raises(ServiceUnavailable, match=r"reached 6 of 7 known terms.*Nothing was written"):
        tool.update("glossary", fetch=GlossarySite())
    assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == before
    assert not (base / "output" / "cache" / "glossary_update").exists() and mnt.MIN_GLOSSARY_KEPT_RATIO == 0.9


def test_glossary_with_unreadable_hovers_is_not_written(tool, base, lenient_glossary):
    broken = {key: "<div>maintenance page, please come back later, nothing to see here at all</div>" for key in HOVERS}
    before = {k: v for k, v in snapshot(base).items() if k.startswith("data/")}
    with pytest.raises(ServiceUnavailable, match="reached 0 of 7 known terms"):
        tool.update("glossary", fetch=GlossarySite(broken))
    assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == before


def test_glossary_hovers_wait_the_shorter_hover_delay(tool, monkeypatch):
    waits = []
    monkeypatch.setattr(mnt, "fetch_html", lambda url, delay=0.0: waits.append((url, delay)) or "x")
    tool._polite_fetch("https://cdn.poe2db.tw/cache2/us/Poe_Data_KeywordPopups_hover/b1")
    tool._polite_fetch("https://poe2db.tw/us/Keystone")
    robots = tool.spec.raw["robots"]
    assert [delay for _, delay in waits] == [robots["hover_delay_seconds"], robots["polite_delay_seconds"]]


def test_glossary_listing_page_that_fails_is_a_network_error_and_the_run_can_continue(tool, base, lenient_glossary):
    class Flaky(GlossarySite):
        down = True

        def __call__(self, url):
            if self.down and url == "https://poe2db.tw/us/Skill_Gems":
                self.calls.append(url)
                raise requests.HTTPError("500 for " + url)
            return super().__call__(url)

    site = Flaky()
    before = {k: v for k, v in snapshot(base).items() if k.startswith("data/")}
    with pytest.raises(ServiceUnavailable, match=r"network error: 500 for https://poe2db.tw/us/Skill_Gems. Nothing was written"):
        tool.update("glossary", fetch=site)
    assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == before
    fetched_before_the_failure = len(site.calls) - 1
    site.down = False
    again = Flaky()
    again.down = False
    result = tool.update("glossary", fetch=again)
    assert result["done"] is True and result["requests"] == FULL_GLOSSARY_REQUESTS - fetched_before_the_failure


def test_glossary_run_is_resumed_while_it_was_active_recently(tool, base, lenient_glossary, monkeypatch):
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)
    first = GlossarySite()
    tool.update("glossary", fetch=first)
    run = base / "output" / "cache" / "glossary_update"
    old = time.time() - mnt.GLOSSARY_RUN_SECONDS - 60
    os.utime(run / "started", (old, old))                       # started long ago, but worked on a moment ago
    second = GlossarySite()
    tool.update("glossary", fetch=second)
    assert not set(second.calls) & set(first.calls)


def test_glossary_run_folder_without_its_marker_is_not_trusted(tool, base, lenient_glossary, monkeypatch):
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)
    first = GlossarySite()
    tool.update("glossary", fetch=first)
    (base / "output" / "cache" / "glossary_update" / "started").unlink()
    second = GlossarySite()
    tool.update("glossary", fetch=second)
    assert second.calls == first.calls


def test_glossary_that_loses_most_chinese_text_is_not_written(tool, base, lenient_glossary):
    english_only = {key: body for key, body in HOVERS.items() if key[0] == "us"}
    before = {k: v for k, v in snapshot(base).items() if k.startswith("data/")}
    with pytest.raises(ServiceUnavailable, match=r"0 of 4 kept their Chinese text. Nothing was written"):
        tool.update("glossary", fetch=GlossarySite(english_only))
    assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == before
    assert mnt.MIN_GLOSSARY_ZH_RATIO == 0.5


def test_merged_term_keeps_every_field_the_crawl_did_not_get():
    old = {"slug": "Stun", "name_en": "Stun", "name_zh_tw": "暈眩", "text_en": "old", "text_zh_tw": "舊", "see_also": ["A"],
           "fetched_at": "2026-01-01"}
    fresh = {"slug": "Stun", "name_en": "Stun", "name_zh_tw": None, "text_en": "new", "text_zh_tw": None, "see_also": [],
             "fetched_at": "2026-02-02"}
    assert mnt._merge_term(old, fresh) == {**old, "text_en": "new", "fetched_at": "2026-01-01"}   # old text kept: old date
    complete = {**fresh, "name_zh_tw": "暈眩", "text_zh_tw": "新", "see_also": ["B"]}
    assert mnt._merge_term(old, complete)["fetched_at"] == "2026-02-02"
    assert mnt._merge_term(None, fresh) is fresh and mnt._merge_term(old, None) is old


def test_glossary_call_gives_up_after_several_hover_failures_in_a_row_and_keeps_its_progress(tool, base, lenient_glossary):
    class HoversDown(GlossarySite):
        def __call__(self, url):
            if "Poe_Data_KeywordPopups_hover" in url:
                self.calls.append(url)
                raise requests.ConnectionError("cdn unreachable")
            return super().__call__(url)

    site = HoversDown()
    before = {k: v for k, v in snapshot(base).items() if k.startswith("data/")}
    with pytest.raises(ServiceUnavailable, match=r"5 requests in a row failed.*calling again later continues"):
        tool.update("glossary", fetch=site)
    assert sum("hover" in u for u in site.calls) == mnt.MAX_CONSECUTIVE_FAILURES == 5
    assert {k: v for k, v in snapshot(base).items() if k.startswith("data/")} == before
    assert (base / "output" / "cache" / "glossary_update" / "pages").exists()


def test_hover_that_failed_is_asked_once_per_run_and_counted(tool, base, monkeypatch):
    monkeypatch.setattr(mnt, "MIN_GLOSSARY_KEPT_RATIO", 0.7)        # five of the seven fixture terms are reached here
    class OneDead(GlossarySite):
        def __call__(self, url):
            if url.endswith("/aa04"):
                self.calls.append(url)
                raise requests.ConnectionError("404")
            return super().__call__(url)

    site = OneDead()
    result = tool.update("glossary", fetch=site)
    assert sum(u.endswith("/aa04") for u in site.calls) == 1
    assert result["done"] is True and result["failed_requests"] == 1 and result["kept_without_refresh"] == 2
    new = {e["slug"]: e for e in read_jsonl(base / KEYWORDS)}
    assert new["Critical_Hits"]["text_en"] == "A Critical Hit deals extra damage."      # its old text


def test_glossary_without_a_local_file_is_sent_to_the_terminal(tool, base):
    (base / KEYWORDS).unlink()
    site = GlossarySite()
    with pytest.raises(ServiceUnavailable, match="no local glossary to update; a first crawl is done in a terminal"):
        tool.update("glossary", fetch=site)
    assert site.calls == []


def test_ladder_snapshot_much_smaller_than_the_last_one_of_the_same_league_is_refused(tool, base, ninja, monkeypatch):
    tool.update("ladder")                                        # 120 rows
    small = FakeNinja(characters(100)[:55] + characters(100, "Other")[:45])
    assert len(small.rows) == 100
    monkeypatch.setattr(mnt, "MIN_LADDER_SHARE_OF_PREVIOUS", 0.9)
    monkeypatch.setattr(mnt.ladder, "_get_json", small.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", small.get_binary)
    before = (base / LADDER).read_bytes()
    with pytest.raises(ServiceUnavailable, match=r"returned 100 characters.*previous snapshot has 120"):
        tool.update("ladder")
    assert (base / LADDER).read_bytes() == before and b"Secret" not in before


def test_ladder_without_any_keystone_is_refused(tool, base, monkeypatch):
    site = FakeNinja(dictionaries={"class": ["Blood Mage", "Deadeye", "Titan"], "gem": ["Arc", "Comet", "Fireball", "Leap Slam", "Spark"]})
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    with pytest.raises(ServiceUnavailable, match="0 with keystones"):
        tool.update("ladder")
    assert not (base / LADDER).exists()


def test_ladder_result_page_that_fails_keeps_the_old_snapshot(tool, base, monkeypatch):
    site = FakeNinja()
    pages = []

    def flaky(url):
        if "/search" in url:
            pages.append(url)
            if len(pages) == 3:
                raise requests.HTTPError("429 Too Many Requests")
        return site.get_binary(url)

    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", flaky)
    with pytest.raises(ServiceUnavailable, match="network error: 429 Too Many Requests. Nothing was written"):
        tool.update("ladder")
    assert not (base / LADDER).exists() and len(pages) == 3


def test_unreadable_spirit_gem_file_stops_a_skill_gem_update(tool, base):
    (base / "data" / "spirit_gems" / "Spirit_Gems_Detail.jsonl").write_text("{broken\n", encoding="utf-8")
    with pytest.raises(ServiceUnavailable, match="a local gem file is unreadable"):
        tool.update("skill_gems", fetch=Web())
    assert slugs(base) == ["Contagion", "Leap_Slam", "Unearth"]


# -- after the re-review ----------------------------------------------------------------------

def mark_broken(base, slug, minutes_ago=60):
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    rows = read_jsonl(base / SKILL_DETAIL)
    for row in rows:
        if row["slug"] == slug:
            row["parse_warnings"] = ["no_popup"]
            row["fetched_at"] = stamp
    write_jsonl(base / SKILL_DETAIL, rows)


class StillBroken(Web):
    """A gem page that keeps failing to parse (the site serves no popup for it)."""

    def __init__(self, slug, listing=None):
        super().__init__(listing)
        self.slug = slug

    def __call__(self, url):
        if url.endswith("/" + self.slug):
            self.calls.append(url)
            return html("detail_nopopup.html")
        return super().__call__(url)


def test_one_gem_page_that_stays_broken_does_not_block_the_scope(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    mark_broken(base, "Unearth")
    first = tool.update("skill_gems", fetch=StillBroken("Unearth"))
    assert first["reasons"] == {"broken": 1} and first["updated"] == 1
    named = tool.update("skill_gems", names=["Leap Slam"], fetch=StillBroken("Unearth"))
    assert named["updated"] == 1                                   # other gems can still be updated
    again = StillBroken("Unearth")
    assert tool.update("skill_gems", fetch=again)["recently_updated"] == 1 and again.details() == []


def test_many_newly_broken_pages_are_still_refused_as_markup_drift(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    before = snapshot(base)

    class AllBroken(Web):
        def __call__(self, url):
            if url.startswith("https://poe2db.tw/us/") and "Gems" not in url:
                self.calls.append(url)
                return html("detail_nopopup.html")
            return super().__call__(url)

    with pytest.raises(ServiceUnavailable, match="no parsable popup.*markup probably changed"):
        tool.update("skill_gems", older_than_days=0, fetch=AllBroken())
    assert snapshot(base) == before


def test_failing_pages_stop_the_run_early(tool, base):
    tool.update("skill_gems", fetch=Web())
    age_records(base)
    web = Web(broken=("Leap_Slam", "Unearth", "Grim_Feast"))
    with pytest.raises(ServiceUnavailable, match="2 detail pages failed"):
        tool.update("skill_gems", older_than_days=0, fetch=web)
    assert len(web.details()) == 2                                 # the third page is never asked for


def test_stale_gems_are_fetched_oldest_first(tool, base):
    tool.update("skill_gems", fetch=Web())
    rows = read_jsonl(base / SKILL_DETAIL)
    for hours, row in zip((1, 3, 2), rows):
        row["fetched_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    write_jsonl(base / SKILL_DETAIL, rows)
    web = Web()
    tool.update("skill_gems", older_than_days=0, max_gems=3, fetch=web)
    order = {row["slug"]: hours for hours, row in zip((1, 3, 2), rows)}
    assert [order[slug] for slug in web.details()] == [3, 2, 1]


def test_glossary_gem_page_that_fails_is_skipped_and_the_run_finishes(tool, base, lenient_glossary):
    class DeadGemPage(GlossarySite):
        def __call__(self, url):
            if url == GEM_PAGES[0]:
                self.calls.append(url)
                raise requests.HTTPError("404 for " + url)
            return super().__call__(url)

    site = DeadGemPage()
    result = tool.update("glossary", fetch=site)
    assert result["done"] is True and site.calls.count(GEM_PAGES[0]) == 1


def test_glossary_failure_registry_carries_over_to_the_next_call(tool, base, monkeypatch):
    monkeypatch.setattr(mnt, "MIN_GLOSSARY_KEPT_RATIO", 0.7)        # five of the seven fixture terms are reached
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)

    class OneDead(GlossarySite):
        def __call__(self, url):
            if url.endswith("/aa04"):
                self.calls.append(url)
                raise requests.ConnectionError("404")
            return super().__call__(url)

    calls = []
    for _ in range(12):
        site = OneDead()
        result = tool.update("glossary", fetch=site)
        calls += site.calls
        if result["done"]:
            break
    assert result["done"] is True and sum(u.endswith("/aa04") for u in calls) == 1


def test_tiny_hover_bodies_are_not_fetched_again_in_the_same_run(tool, base, monkeypatch):
    monkeypatch.setattr(mnt, "MIN_GLOSSARY_KEPT_RATIO", 0.7)
    monkeypatch.setattr(mnt, "GLOSSARY_BATCH", 6)
    tiny = HOVER.format(lang="us", hash="c9")

    class TinyFreeze(GlossarySite):
        def __call__(self, url):
            if url == tiny:
                self.calls.append(url)
                return "x"
            return super().__call__(url)

    calls = []
    for _ in range(12):
        site = TinyFreeze()
        result = tool.update("glossary", fetch=site)
        calls += site.calls
        if result["done"]:
            break
    assert result["done"] is True and calls.count(tiny) == 1


def test_failed_index_rebuild_after_the_glossary_write_is_repaired_without_new_requests(tool, base, lenient_glossary, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("duplicate slug")

    with monkeypatch.context() as patch:
        patch.setattr(mnt, "build_entity_index", broken)
        with pytest.raises(ServiceUnavailable, match="not rebuilt"):
            tool.update("glossary", fetch=GlossarySite())
    site = GlossarySite()
    result = tool.update("glossary", fetch=site)
    assert result["done"] is True and site.calls == []          # everything came from the kept run cache
