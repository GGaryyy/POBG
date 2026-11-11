import json

import pytest
import requests

from src.scrapers import common
from src.scrapers.common import (clean_text, fetch_html, find_section, make_soup, parse_range,
                                 read_jsonl, slug_from_href, write_jsonl)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("text,expected", [
    ("(1 — 20)", [1, 20]),
    ("(1—20)", [1, 20]),
    ("(0.5 - 1.5)", [0.5, 1.5]),
    ("(110 — 449)% of base", [110, 449]),
    ("Level (1 — 90)", None),
    ("30 Spirit", None),
    ("", None),
    (None, None),
])
def test_parse_range(text, expected):
    assert parse_range(text) == expected


def test_parse_range_types():
    assert [type(v) for v in parse_range("(1 — 20)")] == [int, int]
    assert [type(v) for v in parse_range("(0.5 - 1.5)")] == [float, float]


def test_clean_text_collapses_whitespace_and_keeps_ascii_space():
    assert clean_text("  Leap \n  Slam\t ") == "Leap Slam"


def test_clean_text_removes_cjk_spaces():
    assert clean_text("躍  擊 之 力") == "躍擊之力"
    assert clean_text("Leap 躍 擊") == "Leap 躍擊"


@pytest.mark.parametrize("href,expected", [
    ("/us/Leap_Slam", "Leap_Slam"),
    ("https://poe2db.tw/tw/Leap_Slam#x", "Leap_Slam"),
    ("Resolute_Technique", "Resolute_Technique"),
    ("/us/Leap_Slam/?q=1", "Leap_Slam"),
    ("/", None),
    ("", None),
    (None, None),
])
def test_slug_from_href(href, expected):
    assert slug_from_href(href) == expected


HTML = ('<div class="tab-pane" id="SkillGems">a</div><div class="tab-pane" id="Other">b</div>'
        '<div class="tab-pane" id="技能寶石">c</div>')


def test_find_section_by_en_id():
    node = find_section(make_soup(HTML), {"en": "SkillGems"}, "en")
    assert node.get_text() == "a"


def test_find_section_by_zh_id():
    node = find_section(make_soup(HTML), {"en": "SkillGems", "zh-tw": "技能寶石"}, "zh-tw")
    assert node.get_text() == "c"


def test_find_section_lang_falls_back_to_en_id():
    node = find_section(make_soup(HTML), {"en": "SkillGems"}, "zh-tw")
    assert node.get_text() == "a"


def test_find_section_pane_index_fallback():
    node = find_section(make_soup(HTML), {"en": "Missing"}, "en", pane_index=1)
    assert node.get("id") == "Other"


def test_find_section_none_when_both_fail():
    soup = make_soup(HTML)
    assert find_section(soup, {"en": "Missing"}, "en") is None
    assert find_section(soup, {"en": "Missing"}, "en", pane_index=9) is None


def test_make_soup_strips_script_and_style():
    soup = make_soup("<script>evil()</script><style>.a{}</style><p>hi</p>")
    assert soup.get_text() == "hi"


class FakeResp:
    def __init__(self, status, text="ok"):
        self.status_code = status
        self.text = text
        self.headers = {"content-type": "text/html"}
        self.encoding = None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(common.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def _patch_get(monkeypatch, statuses):
    calls = []
    seq = iter(statuses)

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResp(next(seq), text="<html>body</html>")

    monkeypatch.setattr(common.requests, "get", fake_get)
    return calls


def test_fetch_html_retries_then_succeeds(monkeypatch, no_sleep):
    calls = _patch_get(monkeypatch, [503, 503, 200])
    assert fetch_html("https://x/y") == "<html>body</html>"
    assert len(calls) == 3
    assert calls[0][1]["headers"]["User-Agent"] == common.USER_AGENT
    assert no_sleep == [common.BACKOFF_BASE_SECONDS, common.BACKOFF_BASE_SECONDS * 2]


def test_fetch_html_raises_after_exhausting_retries(monkeypatch, no_sleep):
    calls = _patch_get(monkeypatch, [503, 503, 503])
    with pytest.raises(requests.HTTPError, match="503"):
        fetch_html("https://x/y")
    assert len(calls) == 3


def test_fetch_html_404_no_retry(monkeypatch, no_sleep):
    calls = _patch_get(monkeypatch, [404, 200])
    with pytest.raises(requests.HTTPError):
        fetch_html("https://x/y")
    assert len(calls) == 1
    assert no_sleep == []


def test_fetch_html_retries_connection_error(monkeypatch, no_sleep):
    seq = [requests.ConnectionError("boom"), FakeResp(200, "fine")]

    def fake_get(url, **kwargs):
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(common.requests, "get", fake_get)
    assert fetch_html("https://x/y") == "fine"


def test_jsonl_roundtrip_utf8(tmp_path):
    path = tmp_path / "sub" / "a.jsonl"
    records = [{"name": "躍擊", "n": 1}, {"name": "Leap Slam", "n": 2}]
    assert write_jsonl(path, records) == 2
    raw = path.read_text(encoding="utf-8")
    assert "躍擊" in raw and "\\u" not in raw
    assert read_jsonl(path) == records
    assert not path.with_suffix(".jsonl.tmp").exists()


def test_read_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(json.dumps({"a": 1}) + "\n\n" + json.dumps({"a": 2}) + "\n", encoding="utf-8")
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_read_jsonl_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_jsonl(tmp_path / "nope.jsonl")


def test_atomic_write_keeps_unix_line_endings_on_every_platform(tmp_path):
    from src.scrapers.common import atomic_write_text, write_jsonl
    atomic_write_text(tmp_path / "a.txt", "one\ntwo\n")
    write_jsonl(tmp_path / "b.jsonl", [{"a": 1}, {"b": "中"}])
    assert (tmp_path / "a.txt").read_bytes() == b"one\ntwo\n"
    assert (tmp_path / "b.jsonl").read_bytes() == '{"a": 1}\n{"b": "中"}\n'.encode("utf-8")
