import json

import pytest

from src import fetch_poe_ninja_builds as fetcher

pytestmark = pytest.mark.unit

RECORD = {"character_name": "SecretHero", "account_name": "SecretAccount", "class": "Titan", "level": 95,
          "main_skill": "Leap Slam", "skill_gems": ["Leap Slam"], "keystones": None, "league": "Test",
          "rank": 1, "sort_key": "dps_desc", "source": "poe.ninja", "fetched_at": "2026-11-08T00:00:00Z"}


def test_private_fields_are_the_name_fields():
    assert fetcher.PRIVATE_FIELDS == ("character_name", "account_name", "sort_key")


def test_written_rows_hold_no_names(tmp_path):
    path = tmp_path / "out" / "builds.jsonl"
    assert fetcher._write_jsonl([RECORD, {**RECORD, "rank": 2}], path) == 2
    text = path.read_text(encoding="utf-8")
    assert "Secret" not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert [r["rank"] for r in rows] == [1, 2]
    assert sorted(rows[0]) == ["class", "fetched_at", "keystones", "league", "level", "main_skill",
                               "rank", "skill_gems", "source"]


def test_writing_does_not_change_the_records_in_memory(tmp_path):
    record = dict(RECORD)
    fetcher._write_jsonl([record], tmp_path / "builds.jsonl")
    assert record == RECORD


def test_nameless_record_is_dropped_without_echoing_it(capsys):
    kept = fetcher._validate([RECORD, {**RECORD, "character_name": "", "account_name": "SecretAccount2"}])
    assert kept == [RECORD]
    assert "Secret" not in capsys.readouterr().err


def test_summary_prints_no_names(capfdbinary):
    fetcher._print_summary([RECORD, {**RECORD, "rank": 2}])
    out, err = capfdbinary.readouterr()
    assert b"Secret" not in out + err
    assert b"Titan" in out and b"main_skill  : 2/2" in out
    assert b"Leap Slam" not in out                         # counts only, no record is printed


def test_output_path_does_not_depend_on_the_working_directory():
    assert fetcher.OUTPUT_PATH.is_absolute()
    assert fetcher.OUTPUT_PATH.parts[-3:] == ("data", "community_builds", "poe_ninja_builds.jsonl")


def test_requests_identify_the_project_and_do_not_pose_as_a_browser():
    from src.scrapers.common import USER_AGENT
    assert fetcher.HEADERS == {"User-Agent": USER_AGENT, "Accept": "*/*"}
    assert USER_AGENT.startswith("POBG/") and "Mozilla" not in USER_AGENT and "Chrome" not in USER_AGENT
    assert fetcher.REQUEST_DELAY >= 0.8
