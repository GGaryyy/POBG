import json
import os
from pathlib import Path

import pytest

from src.catalog.spec import load_spec
from src.tools.build_tools import POE_NINJA_URL, BuildTools, render_ladder_source
from src.tools.lookup import BadArgument, LookupService, ServiceUnavailable
from tests.kg_support import GRAPH_REL, build_full_environment

pytestmark = pytest.mark.integration

LADDER = Path(__file__).resolve().parents[1] / "fixtures" / "jsonl" / "poe_ninja_builds.jsonl"
CALLS = [
    {}, {"class_name": "Titan"}, {"class_name": "titan"}, {"main_skill": "躍擊"}, {"main_skill": "Leap Slam"},
    {"class_name": "Titan", "main_skill": "Unearth"}, {"class_name": "Nobody"}, {"limit": 2},
    {"lang": "zh-tw"}, {"class_name": "Stormweaver"},
]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return build_full_environment(tmp_path_factory.mktemp("reference_env"), load_spec())


@pytest.fixture(scope="module")
def svc(env):
    return LookupService(base_dir=env, graph_path=env / GRAPH_REL)


@pytest.fixture
def tools(svc):
    return BuildTools(svc, builds_path=LADDER)


def walk(value):
    """Every key and every string value in a nested result."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    else:
        yield value


def ranks(result):
    return [b["rank"] for b in result["builds"]]


@pytest.mark.parametrize("kwargs", CALLS)
def test_no_character_name_anywhere(tools, kwargs):
    result = tools.reference_builds(**kwargs)
    items = list(walk(result))
    assert "character_name" not in items
    assert not any(isinstance(i, str) and "SecretHero" in i for i in items)
    assert not any(isinstance(i, str) and "SecretHero" in i for i in walk(json.dumps(result)))


def test_no_filter_returns_all_rows_ranked_with_unranked_last(tools):
    result = tools.reference_builds(limit=10)
    assert result["total_matching"] == 6
    assert ranks(result) == [1, 2, 3, 5, 7, None]


def test_build_row_fields(tools):
    row = tools.reference_builds(limit=1)["builds"][0]
    assert row == {"class": "Titan", "main_skill": "Leap Slam", "rank": 1, "level": 97,
                   "skill_gems": ["Leap Slam", "Added Fire Damage"],
                   "keystones": ["Chaos Inoculation", "Black Scythe Training"]}


@pytest.mark.parametrize("class_name", ["Titan", "titan", "TITAN"])
def test_class_filter_is_case_insensitive(tools, class_name):
    result = tools.reference_builds(class_name=class_name)
    assert result["total_matching"] == 3 and {b["class"] for b in result["builds"]} == {"Titan"}


@pytest.mark.parametrize("skill", ["躍擊", "Leap Slam", "leap slam", "Leap_Slam"])
def test_main_skill_filter_by_any_name(tools, skill):
    result = tools.reference_builds(main_skill=skill)
    assert result["total_matching"] == 2 and ranks(result) == [1, 3]


def test_unresolvable_main_skill_matches_literally(tools):
    assert tools.reference_builds(main_skill="Unknown Skill")["total_matching"] == 0


def test_both_filters(tools):
    result = tools.reference_builds(class_name="Titan", main_skill="Unearth")
    assert result["total_matching"] == 1 and ranks(result) == [5]


def test_limit_keeps_total_and_order(tools):
    result = tools.reference_builds(limit=2)
    assert result["total_matching"] == 6 and ranks(result) == [1, 2]


def test_common_counts(tools):
    common = tools.reference_builds(class_name="Titan")["common"]
    assert common["main_skills"] == [{"name": "Leap Slam", "count": 2}, {"name": "Unearth", "count": 1}]
    assert common["other_gems"][0] == {"name": "Added Fire Damage", "count": 2}
    assert {"name": "Faster Attacks", "count": 2} in common["other_gems"]
    assert {"name": "Leap Slam", "count": 1} not in common["other_gems"]
    assert common["keystones"][0] == {"name": "Chaos Inoculation", "count": 2}
    assert {"name": "Black Scythe Training", "count": 1} in common["keystones"]


def test_league_and_source(tools):
    result = tools.reference_builds()
    assert result["league"] == "Synthetic League"
    assert result["source"]["url"] == POE_NINJA_URL
    assert result["source"]["label"] == "poe.ninja PoE2 builds (Synthetic League)"
    assert result["source"]["fetched_at"] == "2026-11-08"   # latest fetched_at in the rows, not the file time
    assert result["skipped_lines"] == 0


def test_source_markdown_english(tools):
    result = tools.reference_builds(class_name="Titan")
    date = result["source"]["fetched_at"]
    assert result["source_markdown"] == (
        f"Reference builds: [poe.ninja PoE2 builds \\(Synthetic League\\)]({POE_NINJA_URL})"
        f" — ladder snapshot {date}, 3 characters matched")


def test_source_markdown_traditional_chinese(tools):
    result = tools.reference_builds(main_skill="躍擊")
    assert result["source"]["label"].startswith("poe.ninja PoE2 流派")
    assert result["source_markdown"].startswith("參考流派：[poe.ninja PoE2 流派")
    assert result["source_markdown"].endswith("，符合 2 個角色")


def test_explicit_lang_overrides_detection(tools):
    assert tools.reference_builds(main_skill="躍擊", lang="en")["source_markdown"].startswith("Reference builds")


def test_no_match_lists_available_classes(tools):
    result = tools.reference_builds(class_name="Nobody")
    assert result["total_matching"] == 0 and result["builds"] == []
    assert result["common"] == {"main_skills": [], "other_gems": [], "keystones": []}
    assert {"name": "Titan", "count": 3} in result["available_classes"]
    assert "available_classes" not in tools.reference_builds()


def test_ladder_source_and_renderer(tools):
    source = tools.ladder_source("en")
    assert set(source) == {"label", "url", "fetched_at", "league"}
    with_total = render_ladder_source(source, "en", total=4)
    without = render_ladder_source(source, "en")
    assert with_total == without + ", 4 characters matched"
    assert "matched" not in without
    assert render_ladder_source(source, "zh-tw", total=0).endswith("，符合 0 個角色")


def test_missing_file(svc, tmp_path):
    tools = BuildTools(svc, builds_path=tmp_path / "absent.jsonl")
    with pytest.raises(ServiceUnavailable, match="scope ninja"):
        tools.reference_builds()


def test_default_path_is_under_base_dir(svc):
    assert BuildTools(svc).builds_path == svc.base_dir / "data" / "community_builds" / "poe_ninja_builds.jsonl"


def test_bad_lines_are_skipped_and_counted(svc, tmp_path):
    path = tmp_path / "builds.jsonl"
    good = json.dumps({"character_name": "SecretHeroX", "class": "Titan", "main_skill": "Unearth", "rank": 1,
                       "league": "L"})
    path.write_text(f"{good}\n{{not json\n[1, 2]\n\n{good}\n", encoding="utf-8")
    result = BuildTools(svc, builds_path=path).reference_builds()
    assert result["total_matching"] == 2 and result["skipped_lines"] == 2
    assert not any(isinstance(i, str) and "SecretHero" in i for i in walk(result))


def test_empty_file_has_no_league(svc, tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    result = BuildTools(svc, builds_path=path).reference_builds()
    assert result["total_matching"] == 0 and result["league"] is None
    assert result["source"]["label"] == "poe.ninja PoE2 builds" and result["available_classes"] == []


def test_file_is_read_once(svc, monkeypatch):
    from src.tools import build_tools as bt

    reads = []
    real = bt._read_builds
    monkeypatch.setattr(bt, "_read_builds", lambda path: reads.append(path) or real(path))
    tools = BuildTools(svc, builds_path=LADDER)
    tools.reference_builds(class_name="Titan")
    tools.reference_builds(main_skill="Unearth")
    tools.ladder_source("en")
    assert reads == [LADDER]


# -- review fixes (2026-11-10) -------------------------------------------------------------

GOOD = {"character_name": "SecretHeroX", "account_name": "SecretAccountX", "class": "Titan",
        "main_skill": "Unearth", "rank": 1, "league": "L"}


def write_rows(path, *rows):
    path.write_bytes(b"".join(r if isinstance(r, bytes) else json.dumps(r).encode() + b"\n" for r in rows))
    return path


def test_invalid_utf8_and_deeply_nested_lines_are_skipped(svc, tmp_path):
    path = write_rows(tmp_path / "builds.jsonl", GOOD, b'{"class": "\xff\xfe"}\n', b"[" * 200_000 + b"\n", GOOD)
    result = BuildTools(svc, builds_path=path).reference_builds()
    assert result["total_matching"] == 2 and result["skipped_lines"] == 2


def test_snapshot_date_falls_back_to_the_file_time(svc, tmp_path):
    path = write_rows(tmp_path / "builds.jsonl", GOOD, {**GOOD, "fetched_at": "not a date"}, {**GOOD, "fetched_at": 5})
    os.utime(path, (1_700_000_000, 1_700_000_000))   # 2023-11-14 UTC
    assert BuildTools(svc, builds_path=path).reference_builds()["source"]["fetched_at"] == "2023-11-14"


def test_snapshot_date_is_the_latest_row_date(svc, tmp_path):
    path = write_rows(tmp_path / "builds.jsonl", {**GOOD, "fetched_at": "2026-02-03T23:59:59+00:00"},
                      {**GOOD, "fetched_at": "2026-02-01T00:00:00+00:00"})
    os.utime(path, (1_700_000_000, 1_700_000_000))
    assert BuildTools(svc, builds_path=path).reference_builds()["source"]["fetched_at"] == "2026-02-03"


def test_account_name_never_leaves_the_file(tools):
    for call in CALLS:
        result = tools.reference_builds(**call)
        assert "account_name" not in set(walk(result))
        assert not any(isinstance(i, str) and "SecretAccount" in i for i in walk(result))


@pytest.mark.parametrize("blank", [{"class_name": "  "}, {"main_skill": " \t"}, {"class_name": "", "main_skill": ""}])
def test_blank_filters_mean_no_filter(tools, blank):
    result = tools.reference_builds(**blank)
    assert result["total_matching"] == 6 and result["filters"] == {"class_name": None, "main_skill": None}


def test_string_list_fields_are_not_counted_per_character(svc, tmp_path):
    path = write_rows(tmp_path / "builds.jsonl",
                      {**GOOD, "keystones": "Chaos Inoculation", "skill_gems": "Leap Slam"},
                      {**GOOD, "keystones": ["Chaos Inoculation", 3], "skill_gems": ["Unearth", "Faster Attacks", None]})
    common = BuildTools(svc, builds_path=path).reference_builds()["common"]
    assert common["keystones"] == [{"name": "Chaos Inoculation", "count": 1}]
    assert common["other_gems"] == [{"name": "Faster Attacks", "count": 1}]


def test_unreadable_file_names_no_directory(svc, tmp_path):
    folder = tmp_path / "builds.jsonl"
    folder.mkdir()
    tools = BuildTools(svc, builds_path=folder)
    for _ in range(2):   # a failed load is not cached as a half-loaded snapshot
        with pytest.raises(ServiceUnavailable) as err:
            tools.reference_builds()
        assert "builds.jsonl" in str(err.value) and str(tmp_path) not in str(err.value)


@pytest.mark.parametrize("args", [{"class_name": "x" * 121}, {"main_skill": "x" * 121}])
def test_over_long_filters_are_rejected(tools, args):
    with pytest.raises(BadArgument, match="longer than 120 characters"):
        tools.reference_builds(**args)


# -- Chinese class / ascendancy names --------------------------------------------------------------------

@pytest.mark.parametrize("name, english", [("泰坦", "Titan"), ("獄火師", "Infernalist"), ("風暴編織者", "Stormweaver")])
def test_chinese_class_name_filters_like_the_english_one(tools, name, english):
    zh, en = tools.reference_builds(class_name=name), tools.reference_builds(class_name=english)
    assert zh["total_matching"] == en["total_matching"] > 0
    assert zh["builds"] == en["builds"] and zh["common"] == en["common"]
    assert zh["filters"]["class_name"] == name        # the caller's wording is echoed, not the translation
    assert zh["source_markdown"].startswith("參考流派")


def test_unknown_chinese_class_name_matches_nothing(tools):
    result = tools.reference_builds(class_name="不存在的職業")
    assert result["total_matching"] == 0 and result["builds"] == []
    assert {c["name"] for c in result["available_classes"]} == {"Titan", "Infernalist", "Stormweaver"}


def test_chinese_class_name_without_classes_file_matches_nothing(tmp_path, capsys):
    env = build_full_environment(tmp_path, load_spec())
    (env / "data" / "passive_tree" / "classes.json").unlink()
    tools = BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL), builds_path=LADDER)
    assert tools.reference_builds(class_name="泰坦")["total_matching"] == 0
    assert tools.reference_builds(class_name="Titan")["total_matching"] == 3
