import pytest

from src.catalog.spec import load_spec
from src.scrapers.gem_detail import parse_detail
from tests.support import html

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def skill(spec):
    return parse_detail(html("detail_skill_keywords.html"), spec, "Leap_Slam", "skill_gem")


def test_keyword_slugs_exclude_gemtags_and_itemclasses(skill):
    assert "AoE" not in skill["keyword_slugs"]
    assert "One_Hand_Maces" not in skill["keyword_slugs"]


def test_keyword_slugs_popup_then_acronym_deduped(skill):
    # popup order: Stun, Critical_Hits (Stun repeated in the mod); acronym row: Stun, Armour
    assert skill["keyword_slugs"] == ["Stun", "Critical_Hits", "Armour"]


def test_supported_by_deduped_in_document_order(skill):
    assert skill["supported_by"] == ["Added_Fire_Damage", "Faster_Attacks"]


def test_spirit_gem_also_reads_supported_by(spec):
    rec = parse_detail(html("detail_skill_keywords.html"), spec, "Herald_of_Ash", "spirit_gem")
    assert rec["supported_by"] == ["Added_Fire_Damage", "Faster_Attacks"]


def test_support_gem_has_empty_supported_by(spec):
    rec = parse_detail(html("detail_skill_keywords.html"), spec, "Fire_Attunement", "support_gem")
    assert rec["supported_by"] == []
    assert rec["keyword_slugs"] == ["Stun", "Critical_Hits", "Armour"]  # keywords still collected


def test_page_without_extras_gives_empty_lists(spec):
    rec = parse_detail(html("detail_skill.html"), spec, "Leap_Slam", "skill_gem")
    assert rec["keyword_slugs"] == [] and rec["supported_by"] == []


def test_no_popup_page_still_reads_acronym_row(spec):
    page = ("<html><body><table><tr><td>Id</td><td>X</td></tr>"
            '<tr><td>Acronym</td><td><a href="/us/Stun">Stun</a></td></tr></table></body></html>')
    rec = parse_detail(page, spec, "Some_Gem", "skill_gem")
    assert "no_popup" in rec["parse_warnings"]
    assert rec["keyword_slugs"] == ["Stun"]


def test_supported_by_ignores_non_gem_anchors_and_other_languages(spec):
    page = ('<div id="SupportedBy"><a href="/us/Plain">no hover</a>'
            '<a data-hover="x/Poe_Data_GemEffects_hover/a" href="/tw/Other_Lang">tw</a>'
            '<a data-hover="x/Poe_Data_GemEffects_hover/a" href="/us/Real">Real</a></div>')
    assert parse_detail(page, spec, "S", "skill_gem")["supported_by"] == ["Real"]
