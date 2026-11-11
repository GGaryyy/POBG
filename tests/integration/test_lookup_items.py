"""Gear lookups (src/tools/items.py) and the gear part of verify_build, on synthetic data."""

import pytest

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import load_spec
from src.scrapers.common import write_jsonl
from src.tools.build_tools import BuildTools
from src.tools.items import ItemLookup
from src.tools.lookup import BadArgument, LookupService, NotFound, ServiceUnavailable
from tests.item_support import write_item_data
from tests.kg_support import GRAPH_REL, ZH_NAMES, build_full_environment

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = build_full_environment(tmp_path_factory.mktemp("items_env"), load_spec())
    write_item_data(base)
    entities = build_entity_index(load_spec(), data_dir=base / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(base / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return base


@pytest.fixture
def items(env):
    return ItemLookup(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


@pytest.fixture
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


# -- get_item ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Quill Rain", "驟雨之弦", "Quill_Rain", "quill rain"])
def test_get_item_finds_a_unique_by_any_name(items, name):
    result = items.get_item(name)
    assert result["kind"] == "unique" and result["item"]["slug"] == "Quill_Rain"
    assert result["item"]["mods"] == ["100% increased Attack Speed", "40% less Attack Damage"]
    assert result["modifier_page"] == {"slug": "Bows", "label": "Bows", "label_zh_tw": "弓"}
    assert result["sources"][0]["url"] == "https://poe2db.tw/us/Quill_Rain" and result["sources"][0]["fetched_at"]


def test_get_item_finds_a_base_with_its_modifier_page(items):
    result = items.get_item("黃金斗篷")
    assert result["kind"] == "base" and result["item"]["properties"][0] == "Armour: 10"
    assert result["modifier_page"]["slug"] == "Body_Armours_str_dex_int"


def test_base_on_no_modifier_page_has_no_modifier_page_entry(items):
    assert "modifier_page" not in items.get_item("Rusted Cuirass")


def test_get_item_unknown_name(items):
    with pytest.raises(NotFound, match="no base or unique item matches 'Infinity Blade'"):
        items.get_item("Infinity Blade")


@pytest.mark.parametrize("name", ["", "x" * 600])
def test_get_item_bad_name(items, name):
    with pytest.raises(BadArgument):
        items.get_item(name)


def test_a_name_shared_by_two_items_asks_for_one(items):
    items._load()
    items.bases["Short_Bow_2"] = {**items.bases["Shortbow"], "slug": "Short_Bow_2", "name": "Short Bow II"}
    with pytest.raises(BadArgument, match="'短弓' names several items: Shortbow, Short_Bow_2"):
        items.get_item("短弓")


def test_an_ambiguous_item_name_is_unverified_in_a_build(tools):
    tools.items._load()
    tools.items.bases["Short_Bow_2"] = {**tools.items.bases["Shortbow"], "slug": "Short_Bow_2", "name": "Short Bow II"}
    result = tools.verify_build(gems=["Leap Slam"], items=["短弓"], affixes=["短弓: increased Attack Speed"])
    assert result["verified"]["gems"][0]["slug"] == "Leap_Slam"
    item, affix = result["unverified"]
    assert item["suggestions"] == [{"slug": "Shortbow"}, {"slug": "Short_Bow_2"}]
    assert affix["suggestions"] == [{"item": "Shortbow"}, {"item": "Short_Bow_2"}]


def test_corrupt_item_data_names_the_update(env, tmp_path):
    import shutil
    copy = tmp_path / "copy"
    shutil.copytree(env, copy)
    (copy / "data" / "items" / "bases.jsonl").write_text("{not json\n", encoding="utf-8")
    lookup = ItemLookup(LookupService(base_dir=copy, graph_path=copy / GRAPH_REL))
    with pytest.raises(ServiceUnavailable, match="item data is unreadable .*update_data scope items"):
        lookup.get_item("Quill Rain")


def test_missing_item_data_says_how_to_get_it(tmp_path):
    base = build_full_environment(tmp_path, load_spec())
    lookup = ItemLookup(LookupService(base_dir=base, graph_path=base / GRAPH_REL))
    with pytest.raises(ServiceUnavailable, match="item data missing; update it with update_data scope items"):
        lookup.get_item("Quill Rain")


# -- items_by ----------------------------------------------------------------------------------

def test_items_by_class_kind_level_and_text(items):
    assert [i["slug"] for i in items.items_by(item_class="Bows")["items"]] == ["Quill_Rain", "Shortbow", "Dualstring_Bow"]
    assert [i["slug"] for i in items.items_by(item_class="bows", kind="base", max_level=10)["items"]] == ["Shortbow"]
    hits = items.items_by(text="攻擊速度")
    assert [i["slug"] for i in hits["items"]] == ["Quill_Rain"] and hits["items"][0]["base"] == "Shortbow"
    assert items.items_by(text="ATTACK SPEED")["total"] == 1           # case does not matter


@pytest.mark.parametrize("item_class, slugs", [
    ("弓", ["Quill_Rain", "Shortbow", "Dualstring_Bow"]),
    ("胸甲", ["Golden_Mantle", "Rusted_Cuirass"]),
    ("BOW", ["Quill_Rain", "Shortbow", "Dualstring_Bow"]),
    ("armour", ["Golden_Mantle", "Rusted_Cuirass"]),
])
def test_items_by_class_in_either_language(items, item_class, slugs):
    assert [i["slug"] for i in items.items_by(item_class=item_class)["items"]] == slugs


def test_an_exact_class_name_does_not_take_longer_ones(items):
    items._load()
    items.pages["Crossbows"] = {"slug": "Crossbows", "label": "Crossbows", "label_zh_tw": "十字弓"}
    items.bases["Crossbow"] = {**items.bases["Shortbow"], "slug": "Crossbow", "name": "Crossbow", "item_class": "Crossbows",
                               "item_class_zh_tw": "十字弓"}
    assert "Crossbow" not in [i["slug"] for i in items.items_by(item_class="Bows")["items"]]
    assert "Crossbow" not in [i["slug"] for i in items.items_by(item_class="弓")["items"]]
    assert [i["slug"] for i in items.items_by(item_class="十字弓")["items"]] == ["Crossbow"]
    assert len(items.items_by(item_class="bow")["items"]) == 4          # a partial name takes both


def test_unknown_class_lists_the_class_names(items):
    with pytest.raises(NotFound, match=r"no item class matches '頭盔'. Classes: Body Armours \(胸甲\), Bows \(弓\)"):
        items.items_by(item_class="頭盔")


@pytest.mark.parametrize("kwargs, message", [
    ({}, "give at least one filter"),
    ({"item_class": "   "}, "give at least one filter"),
    ({"kind": "rare"}, "kind must be one of"),
    ({"text": "x" * 121}, "text is longer than 120"),
])
def test_items_by_bad_arguments(items, kwargs, message):
    with pytest.raises(BadArgument, match=message):
        items.items_by(**kwargs)


# -- modifiers_for -----------------------------------------------------------------------------

def test_modifiers_for_a_class_lists_each_modifier_with_tiers(items):
    result = items.modifiers_for("Bows")
    fire = next(f for f in result["families"] if f["family"] == "FireDamage")
    assert [t["tier"] for t in fire["tiers"]] == [1, 2, 3] and fire["tiers"][0]["name"] == "Cremating"
    assert fire["levels"] == [1, 75] and fire["affix"] == "prefix" and fire["tiers"][0]["text_zh_tw"].startswith("附加(62—84)")
    assert result["total_families"] == 3 and "random" in result["note"]
    assert result["sources"][0]["url"] == "https://poe2db.tw/us/Bows"


@pytest.mark.parametrize("item", ["Bows", "弓", "Shortbow", "短弓", "Quill Rain"])
def test_modifiers_for_accepts_a_class_base_or_unique(items, item):
    assert items.modifiers_for(item)["item_class"]["slug"] == "Bows"


def test_modifiers_for_filters(items):
    assert [f["family"] for f in items.modifiers_for("Bows", affix="suffix")["families"]] == ["IncreasedAttackSpeed", "Dexterity"]
    assert [f["family"] for f in items.modifiers_for("Bows", text="攻擊速度")["families"]] == ["IncreasedAttackSpeed"]
    low = items.modifiers_for("Bows", text="fire damage", max_level=40)["families"][0]
    assert [t["name"] for t in low["tiers"]] == ["Burning", "Heated"]
    assert items.modifiers_for("Bows", group="socketable")["families"][0]["tiers"][0]["name"] == "Lesser Desert Rune"
    assert items.modifiers_for("Bows", group="desecrated")["families"][0]["group"] == "desecrated"
    assert items.modifiers_for("Bows", text="   ")["total_families"] == 3           # blank text: no filter


@pytest.mark.parametrize("item, kwargs, error, message", [
    ("Bows", {"group": "veiled"}, BadArgument, "group must be one of"),
    ("Bows", {"affix": "middle"}, BadArgument, "affix must be one of"),
    ("Nothing", {}, NotFound, "no item class, base or unique matches"),
    ("Rusted Cuirass", {}, NotFound, "is on no modifier page"),
])
def test_modifiers_for_errors(items, item, kwargs, error, message):
    with pytest.raises(error, match=message):
        items.modifiers_for(item, **kwargs)


def test_class_label_with_several_attribute_pages_asks_for_one(items, monkeypatch):
    items._load()
    items.pages["Body_Armours_str"] = {**items.pages["Body_Armours_str_dex_int"], "slug": "Body_Armours_str"}
    with pytest.raises(BadArgument, match="several modifier pages by attribute type: Body_Armours_str, Body_Armours_str_dex_int"):
        items.modifiers_for("Body Armours")


# -- check_affix -------------------------------------------------------------------------------

@pytest.mark.parametrize("item, text, family", [
    ("Bows", "increased Attack Speed", "IncreasedAttackSpeed"),
    ("Bows", "#% increased Attack Speed", "IncreasedAttackSpeed"),
    ("Bows", "18% increased Attack Speed", "IncreasedAttackSpeed"),
    ("弓", "增加攻擊速度", "IncreasedAttackSpeed"),
    ("弓", "增加(17—19)%攻擊速度", "IncreasedAttackSpeed"),
    ("Bows", "Adds # to # Fire Damage", "FireDamage"),
    ("Golden Mantle", "maximum Energy Shield", "BaseLocalDefences"),
    ("Bows", "+(5—8) to Dexterity", "Dexterity"),
])
def test_the_whole_modifier_matches(items, item, text, family):
    result = items.check_affix(item, text)
    assert result["matched"] is True and result["family"]["family"] == family


@pytest.mark.parametrize("item, text, candidate", [
    ("弓", "攻擊速度", "IncreasedAttackSpeed"),        # 增加 missing
    ("Bows", "attack speed", "IncreasedAttackSpeed"),  # "increased" missing
    ("Bows", "fire damage", "FireDamage"),             # flat "Adds", not "increased": say which
    ("弓", "火焰傷害", "FireDamage"),
])
def test_part_of_a_modifier_is_not_a_match_but_returns_it(items, item, text, candidate):
    result = items.check_affix(item, text)
    assert result["matched"] is False and "names only part of a modifier" in result["reason"]
    assert result["suggestions"][0]["family"] == candidate


def test_a_vague_word_is_not_a_match_but_points_at_the_modifier(items):
    result = items.check_affix("Bows", "damage")
    assert result["matched"] is False and result["suggestions"][0]["family"] == "FireDamage"


def test_a_shorter_wording_is_not_taken_for_a_longer_modifier(items):
    items._load()
    rows = items.modifiers["Bows"]
    for n, kind in enumerate(("Spell", "Minion")):
        rows.append({**rows[0], "family": "SkillLevel", "affix": "prefix", "level": 10 + n, "name": kind,
                     "text": f"+(1—2) to Level of all {kind} Skills", "text_zh_tw": f"+(1—2)所有{kind}技能等級"})
    result = items.check_affix("Bows", "+2 to Level of all Skills")
    assert result["matched"] is False
    assert {s["text"] for s in result["suggestions"]} == {"+(1—2) to Level of all Spell Skills",
                                                          "+(1—2) to Level of all Minion Skills"}
    assert items.check_affix("Bows", "+2 to Level of all Spell Skills")["matched"] is True


def test_a_value_above_the_best_tier_is_not_a_match(items):
    result = items.check_affix("Bows", "30% increased Attack Speed")
    assert result["matched"] is False and result["reason"] == "30 is above the best tier"
    assert result["suggestions"][0]["text"] == "(17—19)% increased Attack Speed"


@pytest.mark.parametrize("text", ["Fire Resistance", "cold damage"])
def test_check_affix_refuses_what_the_class_cannot_roll(items, text):
    result = items.check_affix("Bows", text)
    assert result["matched"] is False and result["reason"] == "Bows does not roll a modifier like this"
    assert 1 <= len(result["suggestions"]) <= 3


def test_check_affix_on_an_unknown_class(items):
    with pytest.raises(NotFound, match="no item class, base or unique matches 'Rings'"):
        items.check_affix("Rings", "maximum Life")


def test_check_affix_does_not_take_a_small_part_of_a_longer_modifier(items):
    assert items.check_affix("Bows", "area")["matched"] is False


def test_check_affix_ignores_groups_that_are_not_rolled(items):
    # the corrupted group (Vaal) is not something to recommend as a rolled modifier
    assert items.check_affix("Bows", "reduced Attribute Requirements")["matched"] is False


# -- verify_build with gear --------------------------------------------------------------------

def test_verify_build_checks_items_and_affixes_and_cites_them(tools):
    result = tools.verify_build(gems=["Leap Slam"], items=["Quill Rain", "Not An Item"],
                                affixes=["Bows: increased Attack Speed", "弓：火焰抗性"], lang="zh-tw")
    assert [i["slug"] for i in result["verified"]["items"]] == ["Quill_Rain"]
    affix = result["verified"]["affixes"][0]
    assert affix["item_class"] == "Bows" and affix["affix"] == "suffix" and affix["tiers"] == 2
    assert affix["best"] == {"text": "增加(17—19)%攻擊速度", "level": 37} and affix["lowest"]["level"] == 1
    assert "sources" not in affix and affix["cite"] == next(r["n"] for r in result["sources"]
                                                            if r["url"] == "https://poe2db.tw/us/Bows")
    assert {u["input"] for u in result["unverified"]} == {"Not An Item", "弓：火焰抗性"}
    rows = [r["url"] for r in result["sources"]]
    assert "https://poe2db.tw/us/Quill_Rain" in rows and "https://poe2db.tw/us/Bows" in rows
    md = result["sources_markdown"]
    assert "[弓詞綴](https://poe2db.tw/tw/Bows)" in md and "`Not An Item`" in md


def test_verify_build_without_gear_keeps_its_old_shape(tools):
    assert set(tools.verify_build(gems=["Leap Slam"])["verified"]) == {"gems", "passives"}


def _more_bow_suffixes(tools):
    tools.items._load()
    rows = tools.items.modifiers["Bows"]
    for n, (family, text) in enumerate((("ColdResistance", "+(6—10)% to Cold Resistance"),
                                        ("ItemRarity", "(6—10)% increased Rarity of Items found"))):
        rows.append({**rows[3], "family": family, "affix": "suffix", "level": 1, "name": family,
                     "text": text, "text_zh_tw": None})


def test_at_most_three_prefixes_and_three_suffixes_per_item(tools):
    _more_bow_suffixes(tools)
    three = ["Shortbow: increased Attack Speed", "Shortbow: +# to Dexterity", "Shortbow: +#% to Cold Resistance"]
    result = tools.verify_build(affixes=[*three, "Shortbow: increased Rarity of Items found"])
    assert [a["input"] for a in result["verified"]["affixes"]] == three
    assert result["unverified"][0]["reason"] == ("Shortbow already has 3 suffixes in this list; an item holds at "
                                                 "most 3 prefixes and 3 suffixes")


def test_two_items_of_one_class_are_counted_apart(tools):
    _more_bow_suffixes(tools)
    entries = [f"{bow}: {mod}" for bow in ("Shortbow", "Dualstring Bow")
               for mod in ("increased Attack Speed", "+# to Dexterity", "+#% to Cold Resistance")]
    result = tools.verify_build(affixes=entries)
    assert len(result["verified"]["affixes"]) == 6 and result["unverified"] == []
    assert {a["item_class"] for a in result["verified"]["affixes"]} == {"Bows"}


def test_one_modifier_per_family_on_an_item(tools):
    tools.items._load()
    rows = tools.items.modifiers["Bows"]
    rows.append({**rows[0], "family": "FireDamage", "affix": "prefix", "level": 20, "name": "Searing",
                 "text": "(10—15)% increased Fire Damage", "text_zh_tw": None})
    result = tools.verify_build(affixes=["Bows: Adds # to # Fire Damage", "Bows: increased Fire Damage"])
    assert len(result["verified"]["affixes"]) == 1
    assert result["unverified"][0]["reason"] == ("same modifier family as 'Bows: Adds # to # Fire Damage'; "
                                                 "an item cannot have both")


def test_the_same_modifier_twice_is_counted_once(tools):
    result = tools.verify_build(affixes=["Bows: increased Attack Speed", "bows: (5—7)% increased Attack Speed"])
    assert len(result["verified"]["affixes"]) == 1 and result["unverified"] == []


def test_part_of_a_modifier_is_unverified_with_the_candidates(tools):
    result = tools.verify_build(gems=["Leap Slam"], affixes=["Bows: attack speed"])
    assert result["verified"]["affixes"] == [] and [g["slug"] for g in result["verified"]["gems"]] == ["Leap_Slam"]
    entry = result["unverified"][0]
    assert entry["expected"] == "affix" and entry["suggestions"][0]["family"] == "IncreasedAttackSpeed"


def test_an_armour_class_with_several_pages_is_unverified_not_an_error(tools):
    tools.items._load()
    tools.items.pages["Body_Armours_str"] = {**tools.items.pages["Body_Armours_str_dex_int"], "slug": "Body_Armours_str"}
    result = tools.verify_build(gems=["Leap Slam"], affixes=["Body Armours: maximum Energy Shield"])
    assert result["verified"]["gems"][0]["slug"] == "Leap_Slam"
    assert result["unverified"][0]["suggestions"] == [{"item": "Body_Armours_str"}, {"item": "Body_Armours_str_dex_int"}]
    ok = tools.verify_build(affixes=["Golden Mantle: maximum Energy Shield"])        # a base resolves to one page
    assert ok["verified"]["affixes"][0]["item_class"] == "Body_Armours_str_dex_int"


@pytest.mark.parametrize("entry", ["Bows increased Attack Speed", ": attack speed", "Bows:"])
def test_affix_must_name_the_item_and_the_modifier(tools, entry):
    with pytest.raises(BadArgument, match="an affix must be written as 'item: modifier'"):
        tools.verify_build(affixes=[entry])


def test_a_full_set_of_gear_fits_in_one_call(tools):
    entries = [f"Ring {n}: +#% to Fire Resistance" for n in range(60)]
    result = tools.verify_build(affixes=entries)
    assert len(result["unverified"]) == 60                       # unknown items, but the call is accepted
    with pytest.raises(BadArgument, match="affixes has 61 names; the limit is 60"):
        tools.verify_build(affixes=[*entries, "Ring 61: +#% to Fire Resistance"])
    with pytest.raises(BadArgument, match="gems has 41 names; the limit is 40"):
        tools.verify_build(gems=[f"Gem {n}" for n in range(41)])


def test_affix_tiers_come_in_the_answer_language(tools):
    affix = tools.verify_build(affixes=["Bows: #% increased Attack Speed"], lang="en")["verified"]["affixes"][0]
    assert affix["best"] == {"text": "(17—19)% increased Attack Speed", "level": 37}


def test_items_by_with_lines_lists_what_each_item_does(items):
    result = items.items_by(item_class="Bows", with_lines=True)
    by_slug = {i["slug"]: i for i in result["items"]}
    assert by_slug["Quill_Rain"]["lines"] == ["100% increased Attack Speed", "40% less Attack Damage"]
    assert by_slug["Quill_Rain"]["lines_zh_tw"] == ["增加100%攻擊速度", "40%更少攻擊傷害"]
    assert by_slug["Dualstring_Bow"]["lines"] == ["Physical Damage: 19-35", "+50% Surpassing chance to fire an additional Arrow"]
    assert "lines" not in items.items_by(item_class="Bows")["items"][0]


def test_brief_affix_facts_keep_the_input_slot_and_cite(tools):
    affix = tools.verify_build(affixes=["Bows: #% increased Attack Speed"], detail="brief")["verified"]["affixes"][0]
    assert affix == {"input": "Bows: #% increased Attack Speed", "item_class": "Bows", "affix": "suffix",
                     "family": "IncreasedAttackSpeed", "cite": 1}
