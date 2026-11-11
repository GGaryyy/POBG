import pytest

from src.catalog.spec import load_spec
from src.scrapers.common import make_soup
from src.scrapers.hover import (KeywordRef, acronym_slugs, hover_hash, keyword_hover_url, keyword_refs,
                                parse_keyword_hover)
from tests.support import html

pytestmark = pytest.mark.unit

CDN = "https://cdn.poe2db.tw/cache2/us/Poe_Data_KeywordPopups_hover/"


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _node(markup):
    return make_soup(f"<div id='n'>{markup}</div>").select_one("#n")


# -- hover_hash -----------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    (CDN + "6af7", "6af7"),
    (CDN + "6af7/", "6af7"),
    (CDN + "4a439d13631e43c7f47aab345a7e6b64877fb0209f2c42901d14cd9d9f36da1c",
     "4a439d13631e43c7f47aab345a7e6b64877fb0209f2c42901d14cd9d9f36da1c"),
    ("deadbeef", "deadbeef"),
])
def test_hover_hash_valid(url, expected):
    assert hover_hash(url) == expected


@pytest.mark.parametrize("url", [None, "", CDN + "XYZ", CDN + "6AF7", CDN + "not-a-hash", "https://x/"])
def test_hover_hash_invalid(url):
    assert hover_hash(url) is None


# -- keyword_refs -----------------------------------------------------------------

def test_keyword_refs_order_dedupe_and_exclusions(spec):
    node = _node(
        f'<a class="KeywordPopups" href="Stun" data-hover="{CDN}aa01">Stun</a> then '
        f'<a class="GemTags KeywordPopups" href="AoE" data-hover="{CDN}aa02">AoE</a> '
        f'<a class="ItemClasses KeywordPopups" href="Maces" data-hover="{CDN}aa03">Maces</a> '
        f'<a class="KeywordPopups" href="/us/Critical_Hits" data-hover="{CDN}aa04">Critical   Hit</a> '
        f'<a class="KeywordPopups" href="Stun" data-hover="{CDN}ff99">Stun again</a> '
        f'<a class="KeywordPopups" href="Bare">Bare</a> '
        '<a class="Other" href="Ignored">x</a>')
    refs = keyword_refs(node, spec)
    assert [r.slug for r in refs] == ["Stun", "Critical_Hits", "Bare"]
    assert refs[0] == KeywordRef(slug="Stun", hash="aa01", text="Stun")  # first occurrence wins
    assert refs[1].text == "Critical Hit"  # whitespace collapsed
    assert refs[2].hash is None


def test_keyword_refs_none_and_empty(spec):
    assert keyword_refs(None, spec) == []
    assert keyword_refs(_node("plain text only"), spec) == []


def test_keyword_ref_as_dict():
    assert KeywordRef("A", "ab", "A").as_dict() == {"slug": "A", "hash": "ab", "text": "A"}


# -- acronym_slugs ------------------------------------------------------------------

def test_acronym_slugs_reads_row(spec):
    soup = make_soup(html("detail_skill_keywords.html"))
    assert acronym_slugs(soup, spec) == ["Stun", "Armour"]


def test_acronym_slugs_missing_row(spec):
    assert acronym_slugs(make_soup(html("detail_skill.html")), spec) == []
    assert acronym_slugs(make_soup("<table><tr><td>Acronym</td></tr></table>"), spec) == []


def test_acronym_slugs_skips_links_without_slug(spec):
    soup = make_soup('<table><tr><td>Acronym</td><td><a href="/us/Stun">S</a><a href="/">root</a><a>none</a></td></tr></table>')
    assert acronym_slugs(soup, spec) == ["Stun"]


# -- parse_keyword_hover --------------------------------------------------------------

def test_parse_keyword_hover_fixture(spec):
    entry = parse_keyword_hover(html("keyword_hover_accuracy.html"), spec)
    assert entry["slug"] == "Accuracy"
    assert entry["name"] == "Accuracy"
    assert entry["text"] == "Accuracy is used to hit with an Attack.\nSecond line."
    assert entry["refs"] == [KeywordRef(slug="Attacks", hash="6af7", text="Attack")]


@pytest.mark.parametrize("fragment", [
    "", "<div></div>",
    '<h5 class="card-header"><a href="X">X</a></h5>',          # no body
    '<div class="keyword-body">text only</div>',               # no title
])
def test_parse_keyword_hover_incomplete_is_none(spec, fragment):
    assert parse_keyword_hover(fragment, spec) is None


def test_parse_keyword_hover_empty_body_gives_none_text(spec):
    entry = parse_keyword_hover('<h5 class="card-header"><a href="X">Ex</a></h5><div class="keyword-body"> <br/> </div>', spec)
    assert entry["text"] is None and entry["refs"] == [] and entry["slug"] == "X" and entry["name"] == "Ex"


def test_parse_keyword_hover_cjk_spaces_collapsed(spec):
    entry = parse_keyword_hover(
        '<h5 class="card-header"><a href="Accuracy">命 中</a></h5><div class="keyword-body">命 中 用於 擊中</div>', spec)
    assert entry["name"] == "命中" and entry["text"] == "命中用於擊中"


# -- keyword_hover_url --------------------------------------------------------------

def test_keyword_hover_url_per_language(spec):
    assert keyword_hover_url(spec, "en", "ab12") == CDN + "ab12"
    assert keyword_hover_url(spec, "zh-tw", "ab12") == CDN.replace("/us/", "/tw/") + "ab12"


def test_keyword_hover_url_unknown_language(spec):
    with pytest.raises(ValueError, match="unknown language"):
        keyword_hover_url(spec, "fr", "ab12")
