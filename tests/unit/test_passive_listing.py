import pytest

from src.catalog.spec import load_spec
from src.scrapers.hover import KeywordRef
from src.scrapers.passive_listing import PASSIVE_SOURCES, PassiveCard, parse_passive_listing
from tests.support import html

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def keystones_en(spec):
    return parse_passive_listing(html("passive_keystone_cards_en.html"), spec, "passive_keystones", "en")


def by_slug(cards):
    return {c.slug: c for c in cards}


def test_sources_constant():
    assert PASSIVE_SOURCES == {"passive_keystones": "Keystone", "passive_notables": "Notable"}


def test_keystone_cards_and_dedupe(keystones_en):
    assert [c.slug for c in keystones_en] == ["Chaos_Inoculation", "Unknown_Keystone", "Black_Scythe_Training"]


def test_regular_card_fields(keystones_en):
    ci = by_slug(keystones_en)["Chaos_Inoculation"]
    assert (ci.name, ci.node_type, ci.timeless, ci.hover_hash) == ("Chaos Inoculation", "Keystone", False, "a1")
    assert ci.stats == ["Maximum Life is 1", "Immune to Chaos Damage"]  # split on <br>, first occurrence kept
    assert ci.keywords == [KeywordRef(slug="Chaos_Damage", hash="b1", text="Chaos Damage")]


def test_timeless_card_uses_alternate_anchor(keystones_en):
    tl = by_slug(keystones_en)["Black_Scythe_Training"]
    assert tl.timeless is True and tl.hover_hash == "c3" and tl.node_type == "Keystone"
    assert tl.stats == ["Gain Armour from Bone", "Chaos Damage bonus"]
    assert [k.slug for k in tl.keywords] == ["Armour", "Chaos_Damage"]


def test_card_without_keywords(keystones_en):
    unknown = by_slug(keystones_en)["Unknown_Keystone"]
    assert unknown.keywords == [] and unknown.stats == ["Does a thing"]


def test_zh_listing_uses_localised_pane_ids(spec):
    cards = by_slug(parse_passive_listing(html("passive_keystone_cards_zh.html"), spec, "passive_keystones", "zh-tw"))
    assert set(cards) == {"Chaos_Inoculation", "Unknown_Keystone", "Black_Scythe_Training"}
    assert cards["Chaos_Inoculation"].name == "混沌禁錮"  # CJK spaces removed
    assert cards["Chaos_Inoculation"].stats == ["最大生命 1", "免疫混沌傷害"]
    assert cards["Chaos_Inoculation"].keywords[0].hash == "d1"
    assert cards["Black_Scythe_Training"].timeless is True


def test_notable_listing(spec):
    cards = parse_passive_listing(html("passive_notable_cards_en.html"), spec, "passive_notables", "en")
    assert [c.slug for c in cards] == ["Heart_of_Ice", "Mind_Over_Matter", "Beidats_Will"]
    assert all(c.node_type == "Notable" and not c.timeless for c in cards)
    assert cards[0].stats == ["20% increased Cold Damage", "10% increased Spell Damage", "Poe2db extra line"]
    assert cards[0].keywords == [KeywordRef(slug="Cold_Damage", hash="f1", text="Cold Damage")]
    assert cards[2].name == "Beidat's Will"


def test_unknown_source_raises(spec):
    with pytest.raises(KeyError):
        parse_passive_listing("<div></div>", spec, "skill_gems_listing", "en")


def test_page_without_panes_gives_no_cards(spec):
    assert parse_passive_listing("<html><body><p>nothing</p></body></html>", spec, "passive_keystones") == []


def test_card_without_text_anchor_skipped(spec):
    page = ('<div class="tab-pane" id="KeystonePassive">'
            '<div class="d-flex border-top rounded"><a class="PassiveSkills" data-hover="x/Poe_Data_PassiveSkills_hover/a1" href="Icon_Only"><img></a></div>'
            '<div class="d-flex border-top rounded"><a data-hover="x/Some_other_hover/a1" href="Wrong">Wrong Hover</a></div>'
            '<div class="d-flex border-top rounded"><a data-hover="x/Poe_Data_PassiveSkills_hover/a1">No Href</a></div>'
            '<div class="d-flex border-top rounded"><a data-hover="x/Poe_Data_PassiveSkills_hover/a1" href="Good">Good</a></div>'
            '</div>')
    cards = parse_passive_listing(page, spec, "passive_keystones")
    assert [c.slug for c in cards] == ["Good"]
    assert cards[0].stats == [] and cards[0].keywords == []


def test_as_dict_serialises_keywords():
    card = PassiveCard(slug="S", name="N", node_type="Notable", timeless=False, hover_hash="ab",
                       stats=["x"], keywords=[KeywordRef("K", "cd", "K")])
    assert card.as_dict() == {"slug": "S", "name": "N", "node_type": "Notable", "timeless": False,
                              "hover_hash": "ab", "stats": ["x"],
                              "keywords": [{"slug": "K", "hash": "cd", "text": "K"}]}
