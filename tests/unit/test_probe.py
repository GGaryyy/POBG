import json

import pytest
import requests

from src.catalog import probe
from src.catalog.probe import run_probe, write_metrics
from tests.support import fixture_text, html, lowered_spec

pytestmark = pytest.mark.unit

PAGES = {
    "https://poe2db.tw/us/Skill_Gems": "listing_skill_us.html",
    "https://poe2db.tw/us/Spirit_Gems": "listing_spirit_us.html",
    "https://poe2db.tw/us/Support_Gems": "listing_support_us.html",
    "https://poe2db.tw/us/Keystone": "keystone_us.html",
    "https://poe2db.tw/us/Notable": "notable_us.html",
    "https://poe2db.tw/us/Leap_Slam": "detail_skill.html",
    "https://poe2db.tw/us/Herald_of_Ash": "detail_spirit.html",
    "https://poe2db.tw/us/Fire_Attunement": "detail_support.html",
    "https://cdn.poe2db.tw/cache2/us/Poe_Data_KeywordPopups_hover/"
    "4a439d13631e43c7f47aab345a7e6b64877fb0209f2c42901d14cd9d9f36da1c": "keyword_hover_accuracy.html",
}
API_URL = ("https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/contents/"
           "src/TreeData?ref=dev")
API_OK = json.dumps([{"name": "0_4"}, {"name": "0_5"}, {"name": "legion"}])


VIEWER_URL = "https://poe2db.tw/tw/passive-skill-tree/"
SCRIPT_URL = "https://cdn.poe2db.tw/js/passive-skill-tree.e0cc6da0156e37d5.js"
DATA_URL = "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json"
VIEWER_OK = f'<html><script src="{SCRIPT_URL}"></script></html>'
SCRIPT_OK = 'new PassiveSkillTree({poe1version:"3.29",poe2version:"4.5",debug:!1})'
DATA_OK = fixture_text("poe2db_tree", "data_tw_mini.json")


def make_fake(api_body=API_OK, viewer=VIEWER_OK, script=SCRIPT_OK, data=DATA_OK):
    extra = {API_URL: api_body, VIEWER_URL: viewer, SCRIPT_URL: script, DATA_URL: data}

    def fetch(url):
        return extra[url] if url in extra else html(PAGES[url])
    return fetch


fake = make_fake()


def find(doc, source, section):
    return next(c for c in doc["checks"] if c["source"] == source and c["section"] == section)


def test_probe_ok():
    doc = run_probe(lowered_spec(0), ["en"], fetcher=fake)
    assert doc["ok"] is True, [c for c in doc["checks"] if not c["ok"]]
    assert doc["stage"] == "catalog_probe" and doc["languages"] == ["en"]
    assert find(doc, "skill_gems_listing", "list")["count"] == 3
    assert find(doc, "skill_gems_listing", "gemcutting")["count"] == 2
    assert find(doc, "support_gems_listing", "list")["count"] == 3
    assert find(doc, "passive_keystones", "list")["count"] == 1
    assert find(doc, "passive_keystones", "timeless")["count"] == 1
    assert find(doc, "passive_notables", "list")["count"] == 2
    assert find(doc, "gem_detail", "skill_gem")["count"] == 6
    assert find(doc, "keyword_hover", "sample")["count"] == 1
    pob2 = find(doc, "pob2_tree", "version")
    assert pob2["ok"] is True and pob2["error"] is None and pob2["url"] == API_URL
    assert all(c["error"] is None for c in doc["checks"])


def test_probe_expect_min_violation():
    spec = lowered_spec(0)
    spec.raw["sources"]["skill_gems_listing"]["sections"]["list"]["expect_min"] = 4
    doc = run_probe(spec, ["en"], fetcher=fake)
    bad = find(doc, "skill_gems_listing", "list")
    assert bad["ok"] is False and bad["count"] == 3 and bad["expect_min"] == 4
    assert doc["ok"] is False
    assert find(doc, "spirit_gems_listing", "list")["ok"] is True


def test_probe_pob2_newer_version_flags_drift():
    api = json.dumps([{"name": "0_5"}, {"name": "0_10"}, {"name": "legion"}])
    doc = run_probe(lowered_spec(0), ["en"], fetcher=make_fake(api))
    chk = find(doc, "pob2_tree", "version")
    assert chk["ok"] is False and chk["count"] == 0
    assert "update" in chk["error"] and "latest 0_10" in chk["error"] and "pinned 0_5" in chk["error"]
    assert doc["ok"] is False


def test_probe_pob2_older_listing_not_drift():
    doc = run_probe(lowered_spec(0), ["en"], fetcher=make_fake(json.dumps([{"name": "0_4"}, {"name": "0_5"}])))
    assert find(doc, "pob2_tree", "version")["ok"] is True


@pytest.mark.parametrize("body", ["not json at all", '{"message": "rate limited"}', '[1, 2]'])
def test_probe_pob2_bad_api_response(body):
    doc = run_probe(lowered_spec(0), ["en"], fetcher=make_fake(body))
    chk = find(doc, "pob2_tree", "version")
    assert chk["ok"] is False and "unexpected API response" in chk["error"]
    assert doc["ok"] is False


def test_probe_pob2_api_fetch_error():
    base = make_fake()

    def broken(url):
        if url == API_URL:
            raise requests.ConnectionError("rate limit")
        return base(url)

    chk = find(run_probe(lowered_spec(0), ["en"], fetcher=broken), "pob2_tree", "version")
    assert chk["ok"] is False and "ConnectionError: rate limit" in chk["error"]


def test_probe_keyword_hover_unparsable_flags_drift():
    base = make_fake()

    def empty(url):
        return "<div></div>" if "KeywordPopups_hover" in url else base(url)

    chk = find(run_probe(lowered_spec(0), ["en"], fetcher=empty), "keyword_hover", "sample")
    assert chk["ok"] is False and chk["count"] == 0


def test_probe_keyword_hover_wrong_slug_flags_drift():
    base = make_fake()

    def wrong(url):
        return html("keyword_hover_accuracy.html").replace('href="Accuracy"', 'href="Evasion"') \
            if "KeywordPopups_hover" in url else base(url)

    assert find(run_probe(lowered_spec(0), ["en"], fetcher=wrong), "keyword_hover", "sample")["ok"] is False


def test_probe_fetch_error():
    def broken(url):
        if url.endswith("/Keystone"):
            raise requests.ConnectionError("down")
        return fake(url)

    doc = run_probe(lowered_spec(0), ["en"], fetcher=broken)
    chk = find(doc, "passive_keystones", "page")
    assert chk["ok"] is False and chk["count"] == 0
    assert "ConnectionError: down" in chk["error"]
    assert doc["ok"] is False


def test_probe_detail_without_popup_flagged():
    def nopopup(url):
        return html("detail_nopopup.html") if url.endswith("Leap_Slam") else fake(url)

    doc = run_probe(lowered_spec(0), ["en"], fetcher=nopopup)
    chk = find(doc, "gem_detail", "skill_gem")
    assert chk["ok"] is False
    assert "no_popup" in chk["error"] and "name_missing" in chk["error"]


def test_write_metrics(tmp_path):
    doc = {"run_id": "2026-01-01T00-00-00", "ok": True, "checks": [], "name": "躍擊"}
    path = write_metrics(doc, tmp_path / "m")
    assert path.name == "catalog_probe_2026-01-01T00-00-00.json"
    latest = path.parent / "latest_catalog_probe.json"
    assert json.loads(path.read_text(encoding="utf-8")) == doc
    assert latest.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    assert "躍擊" in path.read_text(encoding="utf-8")


def _main_with(monkeypatch, ok, tmp_path):
    doc = {"run_id": "r", "spec_version": "1.0", "spec_verified_at": "x", "languages": ["en"], "ok": ok,
           "checks": [{"source": "s", "section": "list", "lang": "en", "count": 0, "expect_min": 1,
                       "ok": ok, "error": None}]}
    seen = {}
    monkeypatch.setattr(probe, "run_probe", lambda spec, langs, fetcher=None: seen.setdefault("langs", langs) and doc)
    monkeypatch.setattr(probe, "write_metrics", lambda d, m: tmp_path / "x.json")
    return seen


def test_main_returns_1_on_drift(monkeypatch, tmp_path, capsys):
    _main_with(monkeypatch, False, tmp_path)
    assert probe.main(["--metrics-dir", str(tmp_path)]) == 1
    assert "DRIFT" in capsys.readouterr().out


def test_main_returns_0_when_ok_and_langs(monkeypatch, tmp_path):
    seen = _main_with(monkeypatch, True, tmp_path)
    assert probe.main(["--lang", "en", "--metrics-dir", str(tmp_path)]) == 0
    assert seen["langs"] == ["en"]


# -- poe2db passive tree data ---------------------------------------------------------------------------

def test_probe_tree_data_ok():
    doc = run_probe(lowered_spec(0), ["en"], fetcher=fake)
    version, nodes = find(doc, "passive_tree_data", "version"), find(doc, "passive_tree_data", "nodes")
    assert version["ok"] is True and version["url"] == SCRIPT_URL and version["error"] is None
    assert nodes["ok"] is True and nodes["count"] == 13 and nodes["url"] == DATA_URL and nodes["lang"] == "zh-tw"


def test_probe_tree_data_version_drift():
    doc = run_probe(lowered_spec(0), ["en"], fetcher=make_fake(script=SCRIPT_OK.replace('"4.5"', '"4.6"')))
    chk = find(doc, "passive_tree_data", "version")
    assert chk["ok"] is False and "pinned 4.5, viewer uses 4.6" in chk["error"] and doc["ok"] is False


@pytest.mark.parametrize("kwargs, message", [
    ({"viewer": "<html>no script here</html>"}, "viewer script not found"),
    ({"script": "nothing about versions"}, "version not found"),
])
def test_probe_tree_data_viewer_changed(kwargs, message):
    chk = find(run_probe(lowered_spec(0), ["en"], fetcher=make_fake(**kwargs)), "passive_tree_data", "version")
    assert chk["ok"] is False and message in chk["error"]


def test_probe_tree_data_short_file_flags_drift():
    doc = run_probe(lowered_spec(14), ["en"], fetcher=fake)
    chk = find(doc, "passive_tree_data", "nodes")
    assert chk["ok"] is False and chk["count"] == 13 and chk["expect_min"] == 14 and chk["error"] is None


@pytest.mark.parametrize("body", ["<html>404</html>", "[1, 2]", '"text"'])
def test_probe_tree_data_unexpected_body(body):
    chk = find(run_probe(lowered_spec(0), ["en"], fetcher=make_fake(data=body)), "passive_tree_data", "nodes")
    assert chk["ok"] is False and "unexpected data file" in chk["error"]


def test_probe_tree_data_fetch_error():
    def broken(url):
        if url in (VIEWER_URL, DATA_URL):
            raise requests.ConnectionError("down")
        return fake(url)

    doc = run_probe(lowered_spec(0), ["en"], fetcher=broken)
    assert "ConnectionError" in find(doc, "passive_tree_data", "version")["error"]
    assert "ConnectionError" in find(doc, "passive_tree_data", "nodes")["error"]
