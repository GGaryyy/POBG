import pytest
import requests

from src.catalog.spec import load_spec
from src.scrapers import collect_glossary as gl
from src.scrapers.common import read_jsonl
from src.scrapers.hover import KeywordRef, keyword_hover_url
from tests.support import fixture_text

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def hover(slug, name, body):
    return (f'<div class="newItemPopup keywordPopups"><div class="card"><h5 class="card-header">'
            f'<a href="{slug}">{name}</a></h5><div class="card-body"><div class="keyword-body">{body}</div></div></div></div>')


def link(lang, slug, hash_, text):
    cdn = f"https://cdn.poe2db.tw/cache2/{lang}/Poe_Data_KeywordPopups_hover/{hash_}"
    return f'<a class="KeywordPopups" href="{slug}" data-hover="{cdn}">{text}</a>'


@pytest.fixture
def page_cache(tmp_path):
    cache = tmp_path / "pages"
    cache.mkdir()
    for lang, suffix in (("en", "en"), ("zh-tw", "zh")):
        for page, stem in (("Keystone", "keystone"), ("Notable", "notable")):
            (cache / f"{lang}_{page}.html").write_text(
                fixture_text("html", f"passive_{stem}_cards_{suffix}.html"), encoding="utf-8")
    (cache / "en_Skill_Gems.html").write_text(
        '<div class="tab-pane" id="SkillGems"><p>' + link("us", "Minions", "c0de", "Minions") + " "
        + '<a class="GemTags KeywordPopups" href="AoE" data-hover="x/aa01">AoE</a></p></div>', encoding="utf-8")
    return cache


@pytest.fixture
def detail_cache(tmp_path):
    cache = tmp_path / "detail"
    (cache / "en").mkdir(parents=True)
    (cache / "en" / "Leap_Slam.html").write_text(fixture_text("html", "detail_skill_keywords.html"), encoding="utf-8")
    return cache


# -- harvest_refs ------------------------------------------------------------------

def test_harvest_refs_from_cards_listings_and_details(spec, page_cache, detail_cache):
    hashes = gl.harvest_refs(spec, page_cache=page_cache, detail_cache=detail_cache)
    assert hashes == {
        "Chaos_Damage": {"en": "b1", "zh-tw": "d1"},
        "Armour": {"en": "b2", "zh-tw": "d2"},
        "Cold_Damage": {"en": "f1", "zh-tw": "9a"},
        "Minions": {"en": "c0de"},
        "Stun": {"en": "aa03"},
        "Critical_Hits": {"en": "aa04"},
    }
    assert "AoE" not in hashes  # GemTags anchor excluded


def test_harvest_refs_empty_caches(spec, tmp_path):
    assert gl.harvest_refs(spec, page_cache=tmp_path / "none", detail_cache=tmp_path / "nada") == {}


def test_harvest_refs_ignores_anchors_without_hash(spec, tmp_path):
    cache = tmp_path / "pages"
    cache.mkdir()
    (cache / "en_Skill_Gems.html").write_text(
        '<div class="tab-pane" id="SkillGems"><a class="KeywordPopups" href="Attacks">Attack</a></div>', encoding="utf-8")
    assert gl.harvest_refs(spec, page_cache=cache, detail_cache=tmp_path / "d") == {}


def test_harvest_first_hash_wins(spec, tmp_path):
    cache = tmp_path / "pages"
    cache.mkdir()
    (cache / "en_Skill_Gems.html").write_text(
        '<div class="tab-pane" id="SkillGems">' + link("us", "Stun", "aa01", "Stun") + link("us", "Stun", "bb02", "Stun")
        + "</div>", encoding="utf-8")
    assert gl.harvest_refs(spec, page_cache=cache, detail_cache=tmp_path / "d") == {"Stun": {"en": "aa01"}}


# -- fill_from_gem_hovers ---------------------------------------------------------------

GEM_HOVER_TW = "https://cdn.poe2db.tw/cache2/tw/Poe_Data_GemEffects_hover/ab12"


@pytest.fixture
def gem_env(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "zh-tw_Skill_Gems.html").write_text(
        f'<div class="tab-pane" id="技能寶石"><a class="gem_red" data-hover="{GEM_HOVER_TW}" href="/tw/Leap_Slam">躍擊</a>'
        '<a class="gem_red" data-hover="x/Poe_Data_GemEffects_hover/ee55" href="/tw/Unmentioning_Gem">無</a></div>',
        encoding="utf-8")
    data = tmp_path / "data"
    from src.scrapers.common import write_jsonl
    write_jsonl(data / "skill_gems" / "Skill_Gems_Detail.jsonl", [
        {"slug": "Unmentioning_Gem", "keyword_slugs": []}, {"slug": "Leap_Slam", "keyword_slugs": ["Stun", "Armour"]},
        {"slug": "Gem_Without_Hash", "keyword_slugs": ["Orphan"]}])
    return {"data_dir": data, "page_cache": pages, "cache_dir": tmp_path / "hover"}


def test_fill_from_gem_hovers_adds_missing_language_hash(spec, gem_env):
    hashes = {"Stun": {"en": "aa03"}, "Armour": {"en": "b2", "zh-tw": "d2"}}
    pages = {GEM_HOVER_TW: "<p>" + link("tw", "Stun", "cc77", "暈眩") + link("tw", "Orphan", "dd88", "孤") + "</p>"}
    fetched = []
    read = gl.fill_from_gem_hovers(spec, hashes, fetch=make_fetch(pages, fetched), **gem_env)
    assert read == 1 and fetched == [GEM_HOVER_TW]
    assert hashes["Stun"] == {"en": "aa03", "zh-tw": "cc77"}
    assert hashes["Armour"] == {"en": "b2", "zh-tw": "d2"}  # already had zh: untouched
    assert (gem_env["cache_dir"] / "zh-tw" / "gem" / "ab12.html").exists()


def test_fill_from_gem_hovers_nothing_missing_makes_no_requests(spec, gem_env):
    hashes = {"Armour": {"en": "b2", "zh-tw": "d2"}}
    assert gl.fill_from_gem_hovers(spec, hashes, fetch=lambda url: 1 / 0, **gem_env) == 0


def test_fill_from_gem_hovers_skips_terms_without_mentioning_gem_hover(spec, gem_env):
    hashes = {"Orphan": {"en": "aa"}, "Unknown_Term": {"en": "bb"}}
    assert gl.fill_from_gem_hovers(spec, hashes, fetch=lambda url: 1 / 0, **gem_env) == 0
    assert "zh-tw" not in hashes["Orphan"]


def test_fill_from_gem_hovers_request_error_is_warned(spec, gem_env, capsys):
    hashes = {"Stun": {"en": "aa03"}}
    read = gl.fill_from_gem_hovers(spec, hashes, fetch=make_fetch({GEM_HOVER_TW: requests.Timeout("slow")}), **gem_env)
    assert read == 0 and "zh-tw" not in hashes["Stun"]
    assert "[WARN] gem hover zh-tw/Leap_Slam" in capsys.readouterr().err


def test_fill_from_gem_hovers_offline_without_cache(spec, gem_env):
    hashes = {"Stun": {"en": "aa03"}}
    assert gl.fill_from_gem_hovers(spec, hashes, fetch=lambda url: 1 / 0, offline=True, **gem_env) == 0


# -- crawl ---------------------------------------------------------------------------------

def make_fetch(pages, log=None):
    def fetch(url):
        if log is not None:
            log.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result
    return fetch


def u(lang, hash_):
    return keyword_hover_url(load_spec(), lang, hash_)


def test_crawl_follows_nested_refs_per_language(spec, tmp_path):
    pages = {
        u("en", "b1"): hover("Chaos_Damage", "Chaos Damage", "Damage of chaos. See " + link("us", "Chaos_Resistance", "e5", "Chaos Res")),
        u("en", "e5"): hover("Chaos_Resistance", "Chaos Resistance", "Reduces " + link("us", "Chaos_Damage", "b1", "Chaos Damage")
                             + " and " + link("us", "Poison", "e7", "Poison")),
        u("en", "e7"): hover("Poison", "Poison", "Leaf"),
        u("zh-tw", "d1"): hover("Chaos_Damage", "混沌傷害", "混沌的傷害"),
    }
    hashes = {"Chaos_Damage": {"en": "b1", "zh-tw": "d1"}}
    fetched = []
    parsed = gl.crawl(spec, hashes, fetch=make_fetch(pages, fetched), cache_dir=tmp_path / "h")
    assert set(parsed["en"]) == {"Chaos_Damage", "Chaos_Resistance", "Poison"}
    assert set(parsed["zh-tw"]) == {"Chaos_Damage"}
    assert parsed["en"]["Chaos_Damage"]["text"] == "Damage of chaos. See Chaos Res"
    assert parsed["zh-tw"]["Chaos_Damage"]["name"] == "混沌傷害"
    assert fetched.count(u("en", "b1")) == 1  # cycle back to Chaos_Damage does not refetch
    assert len(fetched) == 4
    assert hashes["Poison"] == {"en": "e7"}  # discovered links extend hashes in place


def test_crawl_skips_unparsable_hover(spec, tmp_path):
    pages = {u("en", "f1"): "<div>garbage</div>", u("en", "b1"): hover("Chaos_Damage", "Chaos Damage", "ok")}
    parsed = gl.crawl(spec, {"Cold_Damage": {"en": "f1"}, "Chaos_Damage": {"en": "b1"}},
                      fetch=make_fetch(pages), cache_dir=tmp_path / "h")
    assert set(parsed["en"]) == {"Chaos_Damage"} and parsed["zh-tw"] == {}


def test_crawl_records_request_errors_as_skipped(spec, tmp_path, capsys):
    pages = {u("en", "b2"): requests.ConnectionError("boom"), u("en", "b1"): hover("Chaos_Damage", "Chaos Damage", "ok")}
    parsed = gl.crawl(spec, {"Armour": {"en": "b2"}, "Chaos_Damage": {"en": "b1"}},
                      fetch=make_fetch(pages), cache_dir=tmp_path / "h")
    assert set(parsed["en"]) == {"Chaos_Damage"}
    err = capsys.readouterr().err
    assert "[WARN] keyword hover en/b2" in err and "boom" in err
    assert not (tmp_path / "h" / "en" / "keyword" / "b2.html").exists()  # failures are not cached


def test_crawl_caches_and_serves_offline(spec, tmp_path):
    pages = {u("en", "b1"): hover("Chaos_Damage", "Chaos Damage", "ok")}
    cache = tmp_path / "h"
    gl.crawl(spec, {"Chaos_Damage": {"en": "b1"}}, fetch=make_fetch(pages), cache_dir=cache)
    assert (cache / "en" / "keyword" / "b1.html").exists()

    def no_network(url):
        raise AssertionError("cache must be used")

    again = gl.crawl(spec, {"Chaos_Damage": {"en": "b1"}}, fetch=no_network, cache_dir=cache, offline=True)
    assert set(again["en"]) == {"Chaos_Damage"}


def test_crawl_offline_without_cache_is_empty(spec, tmp_path):
    parsed = gl.crawl(spec, {"Chaos_Damage": {"en": "b1"}}, fetch=lambda url: 1 / 0, cache_dir=tmp_path / "h", offline=True)
    assert parsed == {"en": {}, "zh-tw": {}}


def test_crawl_only_visits_languages_with_a_hash(spec, tmp_path):
    fetched = []
    gl.crawl(spec, {"X": {"zh-tw": "d1"}}, fetch=make_fetch({u("zh-tw", "d1"): hover("X", "叉", "文")}, fetched),
             cache_dir=tmp_path / "h")
    assert fetched == [u("zh-tw", "d1")]


def test_crawl_ref_without_hash_is_not_queued(spec, tmp_path):
    pages = {u("en", "b1"): hover("A", "A", '<a class="KeywordPopups" href="B">B</a>')}
    hashes = {"A": {"en": "b1"}}
    parsed = gl.crawl(spec, hashes, fetch=make_fetch(pages), cache_dir=tmp_path / "h")
    assert set(parsed["en"]) == {"A"} and "B" not in hashes


# -- build_entries / coverage ---------------------------------------------------------------------------

def entry(slug, name, text, refs=()):
    return {"slug": slug, "name": name, "text": text, "refs": [KeywordRef(r, None, r) for r in refs]}


def test_build_entries_merges_languages(spec):
    parsed = {
        "en": {"Stun": entry("Stun", "Stun", "Stuns.", ["Stun", "Freeze", "Armour"]),
               "Freeze": entry("Freeze", "Freeze", "Freezes.")},
        "zh-tw": {"Stun": entry("Stun", "暈眩", "暈眩。", ["Freeze", "Ignite", "Stun"]),
                  "Ignite": entry("Ignite", "點燃", "點燃。")},
    }
    entries = {e["slug"]: e for e in gl.build_entries(spec, parsed)}
    assert list(entries) == ["Freeze", "Ignite", "Stun"]  # sorted union
    stun = entries["Stun"]
    assert (stun["name_en"], stun["name_zh_tw"], stun["text_en"], stun["text_zh_tw"]) == ("Stun", "暈眩", "Stuns.", "暈眩。")
    assert stun["see_also"] == ["Freeze", "Armour", "Ignite"]  # no self link, no duplicates, en first
    assert stun["url_en"] == "https://poe2db.tw/us/Stun" and stun["url_zh_tw"] == "https://poe2db.tw/tw/Stun"
    assert stun["fetched_at"]
    assert entries["Freeze"]["name_zh_tw"] is None and entries["Freeze"]["text_zh_tw"] is None
    assert entries["Ignite"]["name_en"] is None and entries["Ignite"]["see_also"] == []


def test_build_entries_empty(spec):
    assert gl.build_entries(spec, {"en": {}, "zh-tw": {}}) == []


def test_coverage():
    entries = [{"text_en": "a", "text_zh_tw": "b"}, {"text_en": "a", "text_zh_tw": None},
               {"text_en": None, "text_zh_tw": None}, {"text_en": "a", "text_zh_tw": None}]
    assert gl.coverage(entries) == {"keywords": 4, "text_en": 0.75, "text_zh_tw": 0.25}


def test_coverage_empty():
    assert gl.coverage([]) == {"keywords": 0, "text_en": 0.0, "text_zh_tw": 0.0}


# -- main ---------------------------------------------------------------------------------------------------

def patch_pipeline(monkeypatch, parsed):
    monkeypatch.setattr(gl, "harvest_refs", lambda spec: {"Stun": {"en": "aa"}, "Freeze": {"en": "bb"}})
    monkeypatch.setattr(gl, "fill_from_gem_hovers", lambda *a, **k: 0)  # would read the real data/ otherwise
    monkeypatch.setattr(gl, "crawl", lambda spec, hashes, fetch, offline: parsed)


def test_main_returns_1_when_en_text_ratio_too_low(monkeypatch, tmp_path, capsys):
    parsed = {"en": {"Stun": entry("Stun", "Stun", "Stuns."), "Freeze": entry("Freeze", "Freeze", None)}, "zh-tw": {}}
    patch_pipeline(monkeypatch, parsed)
    out = tmp_path / "kw.jsonl"
    assert gl.main(["--out", str(out)]) == 1
    assert "only 50% of keywords have English text" in capsys.readouterr().err
    assert not out.exists()


def test_main_writes_file_when_ratio_ok(monkeypatch, tmp_path, capsys):
    parsed = {"en": {"Stun": entry("Stun", "Stun", "Stuns."), "Freeze": entry("Freeze", "Freeze", "Freezes.")},
              "zh-tw": {"Stun": entry("Stun", "暈眩", "暈眩。")}}
    patch_pipeline(monkeypatch, parsed)
    out = tmp_path / "sub" / "kw.jsonl"
    assert gl.main(["--offline", "--out", str(out)]) == 0
    rows = read_jsonl(out)
    assert [r["slug"] for r in rows] == ["Freeze", "Stun"]
    assert rows[1]["name_zh_tw"] == "暈眩" and "暈眩" in out.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out
    assert "text_en: 1.0" in stdout and "missing zh-TW (1): Freeze" in stdout


def test_main_threshold_boundary(monkeypatch, tmp_path):
    parsed = {"en": {"Stun": entry("Stun", "Stun", "Stuns."), "Freeze": entry("Freeze", "Freeze", None)}, "zh-tw": {}}
    patch_pipeline(monkeypatch, parsed)
    monkeypatch.setattr(gl, "MIN_EN_TEXT_RATIO", 0.5)
    assert gl.main(["--out", str(tmp_path / "kw.jsonl")]) == 0


def test_main_passes_offline_flag_to_crawl(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(gl, "harvest_refs", lambda spec: {})
    monkeypatch.setattr(gl, "fill_from_gem_hovers", lambda *a, **k: 0)

    def fake_crawl(spec, hashes, fetch, offline):
        seen["offline"] = offline
        return {"en": {"A": entry("A", "A", "t")}, "zh-tw": {}}

    monkeypatch.setattr(gl, "crawl", fake_crawl)
    assert gl.main(["--offline", "--out", str(tmp_path / "k.jsonl")]) == 0 and seen["offline"] is True
    assert gl.main(["--out", str(tmp_path / "k.jsonl")]) == 0 and seen["offline"] is False


def test_main_recrawls_when_second_gap_fill_reads_hovers(monkeypatch, tmp_path):
    calls = {"fill": 0, "crawl": 0}
    monkeypatch.setattr(gl, "harvest_refs", lambda spec: {})

    def fill(*a, **k):
        calls["fill"] += 1
        return 3 if calls["fill"] == 2 else 0

    def fake_crawl(spec, hashes, fetch, offline):
        calls["crawl"] += 1
        return {"en": {"A": entry("A", "A", "t")}, "zh-tw": {}}

    monkeypatch.setattr(gl, "fill_from_gem_hovers", fill)
    monkeypatch.setattr(gl, "crawl", fake_crawl)
    assert gl.main(["--out", str(tmp_path / "k.jsonl")]) == 0
    assert calls == {"fill": 2, "crawl": 2}
