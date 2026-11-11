import pytest

from src.catalog.spec import load_spec
from src.scrapers.gem_listing import GemcuttingRow, ListingRow, parse_gemcutting, parse_listing
from tests.support import html

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def by_slug(rows):
    return {r.slug: r for r in rows}


def test_us_skill_listing(spec):
    rows = parse_listing(html("listing_skill_us.html"), spec, "skill_gems_listing", "en")
    assert [r.slug for r in rows] == ["Leap_Slam", "Unearth", "Grim_Feast"]
    rows = by_slug(rows)
    leap = rows["Leap_Slam"]
    assert (leap.name, leap.tier, leap.attribute_colour) == ("Leap Slam", 7, "str")
    assert leap.tag_slugs == ["Attacks", "Area_of_Effect_Skills"]
    assert leap.tag_names == ["Attack", "AoE"]
    unearth = rows["Unearth"]
    assert (unearth.name, unearth.tier, unearth.attribute_colour) == ("Unearth", 1, "int")
    assert unearth.tag_slugs == ["Spells", "Minions"]
    grim = rows["Grim_Feast"]
    assert (grim.name, grim.tier, grim.attribute_colour) == ("Grim Feast", 4, None)
    assert grim.tag_slugs == ["Persistent_Skills"]


def test_tw_skill_listing_same_slugs_chinese_names(spec):
    us = parse_listing(html("listing_skill_us.html"), spec, "skill_gems_listing", "en")
    tw = parse_listing(html("listing_skill_tw.html"), spec, "skill_gems_listing", "zh-tw")
    assert [r.slug for r in tw] == [r.slug for r in us]
    assert [r.name for r in tw] == ["躍擊", "掘屍", "殘酷盛宴"]
    assert [r.tag_slugs for r in tw] == [r.tag_slugs for r in us]
    assert by_slug(tw)["Leap_Slam"].tag_names == ["攻擊", "範圍"]
    assert [r.tier for r in tw] == [7, 1, 4]


def test_icon_only_anchor_not_duplicated(spec):
    rows = parse_listing(html("listing_skill_us.html"), spec, "skill_gems_listing", "en")
    slugs = [r.slug for r in rows]
    assert len(slugs) == len(set(slugs)) == 3
    assert all(r.name for r in rows)


def test_nav_slugs_excluded(spec):
    rows = parse_listing(html("listing_skill_us.html"), spec, "skill_gems_listing", "en")
    assert "Skill_Gems" not in [r.slug for r in rows]


def test_wrong_language_path_finds_nothing(spec):
    # /us/ hrefs do not match the /tw/ anchor selector
    assert parse_listing(html("listing_skill_us.html"), spec, "skill_gems_listing", "zh-tw") == []


def test_spirit_listing(spec):
    rows = parse_listing(html("listing_spirit_us.html"), spec, "spirit_gems_listing", "en")
    assert [(r.slug, r.tier, r.attribute_colour) for r in rows] == [
        ("Herald_of_Ash", 4, "dex"), ("Herald_of_Thunder", 8, "str")]


def test_support_listing_union_includes_gemtags_only_gem(spec):
    rows = by_slug(parse_listing(html("listing_support_us.html"), spec, "support_gems_listing", "en"))
    assert set(rows) == {"Fire_Attunement", "Added_Fire_Damage", "Ruthless"}
    assert rows["Ruthless"].tier is None
    assert rows["Ruthless"].tag_slugs == []
    assert rows["Ruthless"].attribute_colour == "str"
    # list pane wins for gems present in both
    assert rows["Fire_Attunement"].tier == 1
    assert rows["Fire_Attunement"].tag_slugs == ["Fire"]
    # non-universe panes (summary / all_gems) are ignored
    assert "Summary_Only" not in rows and "All_Only" not in rows


def test_empty_page_returns_empty(spec):
    assert parse_listing("<html><body></body></html>", spec, "skill_gems_listing", "en") == []
    assert parse_gemcutting("<html></html>", spec, "skill_gems_listing", "en") == []


def test_parse_gemcutting_rows_and_weapon_row_skipped(spec):
    rows = parse_gemcutting(html("listing_skill_us.html"), spec, "skill_gems_listing", "en")
    assert [(r.class_name, r.tier, r.gem_name, r.gem_slug) for r in rows] == [
        ("Occult", 1, "Unearth", "Unearth"), ("Occult", 1, "Contagion", "Contagion")]
    assert isinstance(rows[0], GemcuttingRow)
    assert rows[0].as_dict()["gem_slug"] == "Unearth"


def test_parse_gemcutting_tw_uses_en_id_fallback(spec):
    rows = parse_gemcutting(html("listing_skill_tw.html"), spec, "skill_gems_listing", "zh-tw")
    assert [r.gem_name for r in rows] == ["掘屍", "傳染"]


def test_gemcutting_spirit(spec):
    rows = parse_gemcutting(html("listing_spirit_us.html"), spec, "spirit_gems_listing", "en")
    assert [(r.tier, r.gem_slug) for r in rows] == [(4, "Herald_of_Ash")]


def test_support_source_has_no_gemcutting(spec):
    assert parse_gemcutting(html("listing_support_us.html"), spec, "support_gems_listing", "en") == []


def test_gemcutting_dedupes_same_gem_in_row(spec):
    page = html("listing_skill_us.html").replace(
        "</td></tr><tr><td>Any Weapon Set",
        ' <a class="gem_blue" data-hover="x/GemEffects_hover/x" href="/us/Unearth">Unearth</a></td></tr><tr><td>Any Weapon Set')
    rows = parse_gemcutting(page, spec, "skill_gems_listing", "en")
    assert [r.gem_slug for r in rows] == ["Unearth", "Contagion"]


def test_listing_row_as_dict():
    d = ListingRow(slug="a", name="A", tier=1, attribute_colour=None).as_dict()
    assert d == {"slug": "a", "name": "A", "tier": 1, "attribute_colour": None,
                 "tag_slugs": [], "tag_names": [], "row_text": None}
