"""Regression tests for the findings of the 2026-11-10 code review (docs/reports/code_review_2026-11-10.md)."""

from __future__ import annotations

import json

import pytest
import requests

from src.catalog.entity_index import Entity, EntityIndex
from src.catalog.spec import load_spec
from src.scrapers import collect_gems
from src.scrapers.common import fetch_html, slug_from_href, write_jsonl
from src.scrapers.gem_detail import parse_detail
from src.scrapers.gem_listing import parse_listing
from tests.support import html, lowered_spec

pytestmark = pytest.mark.unit

SPEC = load_spec()


# ---------------------------------------------------------------------------
# F2 — Spec.field picks the right family
# ---------------------------------------------------------------------------

def test_field_falls_back_within_family_only():
    assert SPEC.field("passive_keystone", "name")["source"].startswith("poe2db listing card")
    assert SPEC.field("skill_gem", "stats") is None
    assert SPEC.field("spirit_gem", "cost")["source"].startswith("property 'Reservation:'")
    assert SPEC.field("support_gem", "level_range")["type"] == "[int,int]|null"


# ---------------------------------------------------------------------------
# F3 / F13 — retry behaviour
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status: int, text: str = "ok", headers: dict | None = None) -> None:
        self.status_code = status
        self.text = text
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


def test_fetch_html_retries_read_timeout(monkeypatch):
    calls = iter([requests.ReadTimeout("slow"), requests.exceptions.ChunkedEncodingError("cut"), _Resp(200, "fine")])

    def fake_get(url, timeout, headers):
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("src.scrapers.common.time.sleep", lambda s: None)
    assert fetch_html("https://poe2db.tw/us/X") == "fine"


def test_fetch_html_honours_retry_after(monkeypatch):
    sleeps: list[float] = []
    calls = iter([_Resp(429, headers={"Retry-After": "7"}), _Resp(200, "fine")])
    monkeypatch.setattr(requests, "get", lambda url, timeout, headers: next(calls))
    monkeypatch.setattr("src.scrapers.common.time.sleep", lambda s: sleeps.append(s))
    assert fetch_html("https://poe2db.tw/us/X") == "fine"
    assert sleeps == [7]


def test_fetch_html_rejects_zero_retries():
    with pytest.raises(ValueError, match="retries"):
        fetch_html("https://poe2db.tw/us/X", retries=0)


# ---------------------------------------------------------------------------
# F4 / F5 — CLI guards against overwriting data/
# ---------------------------------------------------------------------------

def test_limit_requires_explicit_out_dir():
    with pytest.raises(SystemExit) as exc:
        collect_gems.main(["--kind", "skill", "--limit", "2", "--no-cache"])
    assert exc.value.code == 2


def test_lang_other_than_en_is_rejected_by_cli():
    with pytest.raises(SystemExit):
        collect_gems.main(["--kind", "skill", "--lang", "zh-tw", "--out-dir", "/tmp/x", "--no-cache"])


def test_lang_other_than_en_is_rejected_by_collect_kind(tmp_path):
    with pytest.raises(collect_gems.CollectionError, match="supports"):
        collect_gems.collect_kind("skill_gem", lowered_spec(0), out_dir=tmp_path, lang="zh-tw",
                                  fetcher=lambda url: html("listing_skill_tw.html"))


# ---------------------------------------------------------------------------
# F6 / F7 / F8 — detail parser robustness
# ---------------------------------------------------------------------------

def test_mana_multiplier_only_from_level_table():
    page = html("detail_support.html").replace("<body>", "<body><table><tr><td>Mana: 999%</td></tr></table>", 1)
    rec = parse_detail(page, SPEC, "Fire_Attunement", "support_gem")
    assert rec["cost"] == "Mana: 110%"


def test_level_and_weapons_in_one_requirements_div():
    page = (
        '<div class="newItemPopup GemPopup"><div class="itemName typeLine"><span class="lc">Attack</span></div>'
        '<div class="itemName"><span class="lc">Combo</span></div><div class="content">'
        '<div class="property">Tier: 1</div>'
        '<div class="requirements">Requires: <span>Level (1 — 90)</span>, <span>(4 — 157) Str</span>, '
        '<a class="ItemClasses" href="Bows">Bows</a></div></div></div>'
    )
    rec = parse_detail(page, SPEC, "Combo", "skill_gem")
    assert rec["requires_level"] == [1, 90]
    assert rec["requires_stats"] == "(4 — 157) Str"
    assert rec["requires_weapons"] == ["Bows"]


def test_support_requirements_without_colon_does_not_crash():
    page = (
        '<div class="newItemPopup GemPopup"><div class="itemName"><span class="lc">Odd</span></div>'
        '<div class="content"><div class="requirements">Support Requirements</div></div></div>'
    )
    rec = parse_detail(page, SPEC, "Odd", "support_gem")
    assert rec["requires_stats"] is None


def test_popup_index_out_of_range_is_a_warning(tmp_path):
    import copy
    from src.catalog.spec import Spec
    raw = copy.deepcopy(SPEC.raw)
    raw["sources"]["gem_detail"]["popup_index"] = 9
    rec = parse_detail(html("detail_skill.html"), Spec(raw), "Leap_Slam", "skill_gem")
    assert "no_popup" in rec["parse_warnings"]


# ---------------------------------------------------------------------------
# F10 — tier must directly follow the gem name
# ---------------------------------------------------------------------------

def test_tier_not_taken_from_later_text():
    page = html("listing_skill_us.html").replace("Leap Slam</a> (7)", "Leap Slam</a> see note (7)")
    rows = {r.slug: r for r in parse_listing(page, SPEC, "skill_gems_listing", "en")}
    assert rows["Leap_Slam"].tier is None


# ---------------------------------------------------------------------------
# F12 / F16 / F17 — entity index lookups and record safety
# ---------------------------------------------------------------------------

def _entity(slug: str, name: str, kind: str = "skill_gem", **kw) -> Entity:
    from src.catalog.entity_index import make_aliases
    return Entity(slug=slug, kind=kind, name_en=name, name_zh_tw=None, url_en=None, url_zh_tw=None,
                  aliases=make_aliases(name), **kw)


def test_slug_dots_rejected():
    assert slug_from_href("/us/..") is None
    assert slug_from_href("/us/.") is None


def test_get_accepts_decoded_slug():
    index = EntityIndex([_entity("Companion%3A_Wolf", "Companion: Wolf")])
    assert index.get("Companion:_Wolf") is not None
    assert index.get("Companion%3A_Wolf") is not None


def test_find_prefix_hits_ranked_by_alias_length():
    index = EntityIndex([_entity("Frostbolt_Nova", "Frostbolt Nova"), _entity("Frostbolt", "Frostbolt"),
                         _entity("Frostbolt_Nova_Extended", "Frostbolt Nova Extended")])
    hits = index.find("frostb")
    assert [h["slug"] for h in hits] == ["Frostbolt", "Frostbolt_Nova", "Frostbolt_Nova_Extended"]
    assert {h["match_type"] for h in hits} == {"prefix"}


def test_record_refuses_paths_outside_data(tmp_path):
    (tmp_path / "data").mkdir()
    outside = tmp_path / "secret.jsonl"
    outside.write_text(json.dumps({"slug": "X"}) + "\n", encoding="utf-8")
    index = EntityIndex([], base_dir=tmp_path)
    with pytest.raises(ValueError, match="under data/"):
        index.record({"record_file": "../secret.jsonl", "record_key": {"slug": "X"}})
    with pytest.raises(ValueError, match="under data/"):
        index.record({"record_file": str(outside), "record_key": {"slug": "X"}})


def test_record_is_cached_per_file(tmp_path):
    data = tmp_path / "data" / "skill_gems"
    data.mkdir(parents=True)
    f = data / "Skill_Gems_Detail.jsonl"
    f.write_text(json.dumps({"slug": "A", "name": "A"}) + "\n", encoding="utf-8")
    index = EntityIndex([], base_dir=tmp_path)
    key = {"record_file": "data/skill_gems/Skill_Gems_Detail.jsonl", "record_key": {"slug": "A"}}
    assert index.record(key)["name"] == "A"
    f.write_text(json.dumps({"slug": "A", "name": "changed"}) + "\n", encoding="utf-8")
    assert index.record(key)["name"] == "A"  # served from the per-file cache


# ---------------------------------------------------------------------------
# F14 — atomic writes
# ---------------------------------------------------------------------------

def test_write_jsonl_keeps_old_file_when_generator_fails(tmp_path):
    target = tmp_path / "out.jsonl"
    target.write_text('{"keep": true}\n', encoding="utf-8")

    def records():
        yield {"a": 1}
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        write_jsonl(target, records())
    assert target.read_text(encoding="utf-8") == '{"keep": true}\n'
    assert not (tmp_path / "out.jsonl.tmp").exists()
