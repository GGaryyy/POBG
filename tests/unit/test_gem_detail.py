import pytest

from src.catalog.spec import load_spec
from src.scrapers.gem_detail import SECTION_BY_KIND, parse_detail
from tests.support import html

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def skill(spec):
    return parse_detail(html("detail_skill.html"), spec, "Leap_Slam", "skill_gem")


@pytest.fixture(scope="module")
def spirit(spec):
    return parse_detail(html("detail_spirit.html"), spec, "Herald_of_Ash", "spirit_gem")


@pytest.fixture(scope="module")
def support(spec):
    return parse_detail(html("detail_support.html"), spec, "Fire_Attunement", "support_gem")


def test_skill_record(skill):
    assert skill["name"] == "Leap Slam"
    assert skill["typeline"] == "Attack"
    assert skill["tags"] == ["Attack", "AoE", "Melee"]
    assert skill["tier"] == 7
    assert skill["level_range"] == [1, 20]
    assert skill["cost"] == "(14 — 97) Mana"
    assert skill["main_stat"] == "Attack Damage: (110 — 449)% of base"
    assert skill["requires_level"] == [1, 90]
    assert skill["requires_stats"] == "(4 — 157) Str"
    assert skill["requires_weapons"] == ["One Hand Maces", "Two Hand Maces"]
    assert skill["description"] == "Jump into the air..."
    assert skill["extra_properties"] == ["+0.65 seconds to Total Attack Time", "(50 — 88)% more Stun buildup"]
    assert skill["hidden_stats"] == ["is area damage [1]"]
    assert skill["quality_effects"] == "(0 — 20)% more Damage"
    assert skill["level_effects"] == [
        {"Level": "1", "Requires Level": "1", "Str": "4", "Mana": "14"},
        {"Level": "2", "Requires Level": "3", "Str": "8", "Mana": "16"}]
    assert skill["game_id"] == "LeapSlam"
    assert skill["item_type"] == "Metadata/Items/Gems/SkillGemLeapSlam"
    assert skill["section"] == "SkillGemsDetail"
    assert skill["href"] == skill["source_url"] == "https://poe2db.tw/us/Leap_Slam"
    assert skill["url_zh_tw"] == "https://poe2db.tw/tw/Leap_Slam"
    assert (skill["slug"], skill["kind"], skill["lang"]) == ("Leap_Slam", "skill_gem", "en")
    assert skill["parse_warnings"] == []
    assert skill["tag_slugs"] == [] and skill["attribute_colour"] is None  # filled by the collector
    assert skill["fetched_at"]


def test_script_text_stripped(skill):
    assert "SCRIPTJUNK" not in repr(skill)
    assert "color:red" not in repr(skill)


def test_spirit_record_uses_only_first_popup(spirit):
    assert spirit["tier"] == 4
    assert spirit["cost"] == "30 Spirit"
    assert spirit["requires_level"] == [1, 90]
    assert spirit["requires_stats"] == "(4 — 157) Str"
    assert spirit["requires_weapons"] == ["Any Martial Weapon"]
    assert spirit["extra_properties"] == ["Herald popup zero mod"]
    assert spirit["tags"] == ["Spirit", "Fire"]
    assert spirit["section"] == "SpiritGemsDetail"
    assert spirit["game_id"] == "HeraldOfAsh"
    assert "OTHER" not in repr(spirit)
    assert "99 Spirit" not in repr(spirit)


def test_support_record(support):
    assert support["category"] == "Fire Attunement"
    assert support["requires_stats"] == "+5 Str"
    assert support["requires_level"] == [65, 65]
    assert support["requires_weapons"] is None
    assert support["hidden_stats"] == []
    assert support["cost"] == "Mana: 110%"
    assert support["quality_effects"] is None
    assert support["requires_weapons"] is None
    assert support["tags"] == ["Support", "Fire"]
    assert support["tier"] == 1
    assert support["game_id"] == "AddedFireDamageSupport"
    assert support["section"] == "SupportGemsDetail"
    assert support["level_effects"] == [{"Level": "1", "Requires Level": "1"}]
    assert support["parse_warnings"] == []


def test_support_explicit_cost_not_overridden_by_mana_cell(spec):
    page = html("detail_support.html").replace(
        '<div class="property">Tier: 1</div>', '<div class="property">Tier: 1</div><div class="property">Cost: 5 Mana</div>')
    assert parse_detail(page, spec, "Fire_Attunement", "support_gem")["cost"] == "5 Mana"


def test_no_popup(spec):
    rec = parse_detail(html("detail_nopopup.html"), spec, "Some_Gem_Name", "skill_gem")
    assert rec["name"] == "Some Gem Name"
    assert "no_popup" in rec["parse_warnings"]
    assert "name_from_slug" in rec["parse_warnings"]
    for key in ("tier", "level_range", "cost", "main_stat", "requires_level", "requires_stats",
                "requires_weapons", "description", "quality_effects", "game_id", "item_type", "category"):
        assert rec[key] is None, key
    assert rec["tags"] == [] and rec["extra_properties"] == [] and rec["level_effects"] == []


def test_unknown_kind_raises(spec):
    with pytest.raises(ValueError, match="unknown gem kind"):
        parse_detail(html("detail_skill.html"), spec, "Leap_Slam", "wand_gem")


def test_section_by_kind_covers_all_kinds():
    assert set(SECTION_BY_KIND) == {"skill_gem", "spirit_gem", "support_gem"}


def test_zh_lang_url(spec):
    rec = parse_detail(html("detail_skill.html"), spec, "Leap_Slam", "skill_gem", lang="zh-tw")
    assert rec["href"] == "https://poe2db.tw/tw/Leap_Slam"
    assert rec["lang"] == "zh-tw"


def test_bare_level_requirement_not_weapon(spec):
    page = html("detail_support.html")
    rec = parse_detail(page, spec, "Fire_Attunement", "support_gem")
    assert rec["requires_level"] == [65, 65]
    assert rec["requires_weapons"] is None
    assert rec["requires_stats"] == "+5 Str"


def test_hidden_stats_excluded_from_extra_properties(skill):
    assert "is area damage [1]" not in skill["extra_properties"]
    assert len(skill["extra_properties"]) == 2
