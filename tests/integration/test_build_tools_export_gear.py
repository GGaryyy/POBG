import re
import xml.etree.ElementTree as ET

import pytest

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import load_spec
from src.scrapers.common import write_jsonl
from src.tools import build_tools as bt
from src.tools.build_tools import MAX_GEAR, BuildTools
from src.tools.lookup import BadArgument, LookupService
from src.tools.pob_export import decode_code
from tests.item_support import write_item_data
from tests.kg_support import GRAPH_REL, ZH_NAMES, build_full_environment, routing_classes_doc, routing_tree

pytestmark = pytest.mark.integration

BOW = "Weapon 1: Dualstring Bow; Adds # to # Fire Damage; #% increased Attack Speed; +# to Dexterity"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = build_full_environment(tmp_path_factory.mktemp("gear_env"), load_spec(), tree=routing_tree(),
                                  classes=routing_classes_doc())
    write_item_data(base)
    entities = build_entity_index(load_spec(), data_dir=base / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(base / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return base


@pytest.fixture
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


def xml_of(result) -> ET.Element:
    return ET.fromstring(decode_code(result["code"]))


def items_of(result) -> dict[str, str]:
    """Slot name -> the item's text, as PoB will read it."""
    root = xml_of(result)
    texts = {i.attrib["id"]: i.text for i in root.findall("Items/Item")}
    return {s.attrib["name"]: texts[s.attrib["itemId"]] for s in root.findall("Items/ItemSet/Slot")}


def reasons(result) -> dict[str, str]:
    return {entry["input"]: entry["reason"] for entry in result["not_exported"]}


# -- what goes in -------------------------------------------------------------------------------------

def test_a_rare_is_written_at_the_upper_end_of_its_best_tiers(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW])
    assert items_of(res) == {"Weapon 1": "\n".join([
        "Rarity: RARE", "POBG Weapon 1", "Dualstring Bow", "Implicits: 1",
        "+50% Surpassing chance to fire an additional Arrow",
        "Adds 84 to 145 Fire Damage", "19% increased Attack Speed", "+8 to Dexterity"])}
    assert res["not_exported"] == []
    assert res["summary"]["gear"] == [{"slot": "Weapon 1", "item": "Dualstring Bow", "rarity": "RARE", "modifiers": 3}]
    root = xml_of(res)
    assert root.find("Items").attrib == {"activeItemSet": "1", "useSecondWeaponSet": "false"}
    assert root.find("Items/ItemSet").attrib == {"id": "1", "useSecondWeaponSet": "false"}


def test_a_unique_keeps_its_own_modifiers_and_extra_ones_are_reported(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Weapon 1: Quill Rain; +# to Dexterity"])
    assert items_of(res)["Weapon 1"] == "\n".join([
        "Rarity: UNIQUE", "Quill Rain", "Shortbow", "Implicits: 0",
        "100% increased Attack Speed", "40% less Attack Damage"])
    assert reasons(res) == {"+# to Dexterity": "Quill Rain is a unique: its modifiers are fixed"}


def test_a_base_without_modifiers_is_a_normal_item(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Body Armour: Golden Mantle"])
    assert items_of(res) == {"Body Armour": "Rarity: NORMAL\nGolden Mantle\nImplicits: 0"}
    assert res["summary"]["gear"][0]["rarity"] == "NORMAL"


def test_chinese_slots_items_and_modifiers(tools):
    en = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW, "Body Armour: Golden Mantle; +#% to Fire Resistance"])
    zh = tools.export_pob("女巫", skills=["掘屍"], gear=["武器：雙弦弓；附加#至#火焰傷害；增加#%攻擊速度；+#點敏捷",
                                                     "胸甲: 黃金斗篷; +#%火焰抗性"])
    assert items_of(zh) == items_of(en) and zh["lang"] == "zh-tw"
    assert any(line.startswith("裝備詞綴以最高階的上限寫入") for line in zh["notes"])


# -- what stays out -----------------------------------------------------------------------------------

def test_modifiers_the_class_cannot_roll_or_partly_written_stay_out(tools):
    res = tools.export_pob("Witch", skills=["Unearth"],
                           gear=["Weapon 1: Shortbow; +# to maximum Energy Shield; Fire Damage; #% increased Attack Speed"])
    assert items_of(res)["Weapon 1"].splitlines()[-1] == "19% increased Attack Speed"
    why = reasons(res)
    assert set(why) == {"+# to maximum Energy Shield", "Fire Damage"}
    assert next(e for e in res["not_exported"] if e["input"] == "Fire Damage")["suggestions"]   # the full wording


def test_three_plus_three_is_counted_per_item_not_per_base(tools, monkeypatch):
    monkeypatch.setattr(bt, "MAX_PER_AFFIX", 1)
    monkeypatch.setitem(bt.SLOT_CLASSES, "Helmet", ("Helmets", "Body Armours"))
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[
        "Weapon 1: Dualstring Bow; #% increased Attack Speed; +# to Dexterity",
        "Body Armour: Golden Mantle; +#% to Fire Resistance", "Helmet: Golden Mantle; +#% to Fire Resistance"])
    assert "already has 1 suffixes" in reasons(res)["+# to Dexterity"]
    assert items_of(res)["Body Armour"].endswith("+10% to Fire Resistance")
    assert items_of(res)["Helmet"].endswith("+10% to Fire Resistance")      # the same base twice: two items


def test_a_repeated_modifier_is_written_once(tools):
    res = tools.export_pob("Witch", skills=["Unearth"],
                           gear=["Weapon 1: Shortbow; #% increased Attack Speed; #% increased attack speed"])
    assert items_of(res)["Weapon 1"].count("Attack Speed") == 1 and res["not_exported"] == []


def test_wrong_slot_duplicate_slot_and_unknown_item(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[
        "Helmet: Dualstring Bow", "Body Armour: Golden Mantle", "Body Armour: Rusted Cuirass", "Boots: Not A Boot"])
    why = reasons(res)
    assert why["Helmet: Dualstring Bow"] == "Dualstring Bow is Bows, which does not go in Helmet"
    assert why["Body Armour: Rusted Cuirass"] == "Body Armour already has an item in this export"
    assert why["Boots: Not A Boot"].endswith("(Not A Boot); the item was left out")
    assert list(items_of(res)) == ["Body Armour"]


def test_an_item_class_given_as_an_item_stays_out_with_its_reason(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Weapon 1: Bows"])
    assert "this is an item class, not an item" in reasons(res)["Weapon 1: Bows"]


def test_an_off_hand_that_does_not_fit_the_main_hand_is_left_out(tools, monkeypatch):
    monkeypatch.setitem(bt.SLOT_CLASSES, "Weapon 2", ("Body Armours",))
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Weapon 1: Shortbow", "Weapon 2: Golden Mantle"])
    assert list(items_of(res)) == ["Weapon 1"]
    assert reasons(res)["Weapon 2: Golden Mantle"] == "a bow in Weapon 1 takes only a quiver in Weapon 2"
    assert res["summary"]["attributes"]["dex"]["need"] == 12            # only the bow counts


@pytest.mark.parametrize("weapon, offhand, problem", [
    ("Bows", "Quivers", None), (None, "Shields", None), ("One Hand Swords", "Daggers", None),
    ("Daggers", "Sceptres", None), ("Wands", "Foci", None), ("Spears", "Bucklers", None),
    (None, "Quivers", "only with a bow"), ("Daggers", "Quivers", "only with a bow"),
    ("Bows", "Shields", "takes only a quiver"), ("Staves", "Foci", "two-handed item (Staves)"),
    ("Traps", "Shields", "two-handed item (Traps)"), ("Talismans", "Sceptres", "two-handed item (Talismans)"),
    ("Wands", "Daggers", "not a weapon"), ("Sceptres", "Claws", "not a weapon"),
])
def test_off_hand_rules_follow_path_of_building(weapon, offhand, problem):
    found = bt._offhand_problem(weapon, offhand)
    assert (found is None) if problem is None else (problem in found)


def test_slot_classes_match_pobs_hands():
    assert "Spears" in bt.SLOT_CLASSES["Weapon 1"] and "Spears" not in bt.SLOT_CLASSES["Weapon 2"]
    assert "Wands" not in bt.SLOT_CLASSES["Weapon 2"] and "Sceptres" in bt.SLOT_CLASSES["Weapon 2"]
    assert "Traps" in bt.TWO_HANDED and set(bt.ONE_HANDED).isdisjoint(bt.TWO_HANDED)


def test_a_modifier_with_two_stats_is_written_as_two_lines(tools):
    tools.items._load()
    row = next(r for rows in tools.items.modifiers.values() for r in rows if r["text"] == "(17—19)% increased Attack Speed")
    row["text"] = "(17—19)% increased Attack Speed\n+(11—20) to Dexterity"          # as the collector stores a hybrid
    res = tools.export_pob("Witch", skills=["Unearth"],
                           gear=["Weapon 1: Shortbow; #% increased Attack Speed +# to Dexterity"])
    assert items_of(res)["Weapon 1"].splitlines()[-2:] == ["19% increased Attack Speed", "+20 to Dexterity"]
    assert res["summary"]["gear"][0]["modifiers"] == 1                               # one modifier, two lines
    assert res["summary"]["attributes"]["dex"]["have"] == 27                         # 7 + 20 from the line


def test_unnumbered_rings_take_the_next_free_slot(tools, monkeypatch):
    monkeypatch.setitem(bt.SLOT_CLASSES, "Ring 1", ("Body Armours",))
    monkeypatch.setitem(bt.SLOT_CLASSES, "Ring 2", ("Body Armours",))
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Ring: Golden Mantle", "戒指: Rusted Cuirass",
                                                               "ring: Golden Mantle"])
    assert list(items_of(res)) == ["Ring 1", "Ring 2"]
    assert reasons(res) == {"ring: Golden Mantle": "Ring 1 already has an item in this export"}


def test_hidden_unique_lines_and_unique_attributes(tools):
    tools.items._load()
    quill = tools.items.uniques["Quill_Rain"]
    quill["mods"] = [*quill["mods"], "Has 2 Augment Sockets (Hidden)", "+(10—15) to all Attributes"]
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Weapon 1: Quill Rain"])
    text = items_of(res)["Weapon 1"]
    assert "(Hidden)" not in text and text.endswith("+15 to all Attributes")
    assert res["summary"]["attributes"]["str"]["have"] == 22 and res["summary"]["gear"][0]["modifiers"] == 3


def test_a_normal_item_keeps_its_implicit(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=["Weapon 1: Dualstring Bow"])
    assert items_of(res)["Weapon 1"] == ("Rarity: NORMAL\nDualstring Bow\nImplicits: 1\n"
                                         "+50% Surpassing chance to fire an additional Arrow")


def test_the_real_cap_of_three_prefixes(tools):
    tools.items._load()
    rows = tools.items.modifiers["Bows"]
    for n, family in enumerate(("PhysA", "PhysB", "PhysC"), 1):
        rows.append({**next(r for r in rows if r["family"] == "FireDamage" and r["level"] == 75), "family": family,
                     "text": f"+(1—{n}) to Spirit {family}", "text_zh_tw": None, "name": family})
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[
        "Weapon 1: Shortbow; Adds # to # Fire Damage; +# to Spirit PhysA; +# to Spirit PhysB; +# to Spirit PhysC"])
    assert items_of(res)["Weapon 1"].splitlines()[4:] == ["Adds 84 to 145 Fire Damage", "+1 to Spirit PhysA",
                                                          "+2 to Spirit PhysB"]
    assert "already has 3 prefixes" in reasons(res)["+# to Spirit PhysC"]


# -- attributes, level and notes ----------------------------------------------------------------------

def test_gear_requirements_and_attributes_enter_the_attribute_plan(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW])
    assert res["summary"]["attributes"]["dex"] == {"have": 15, "need": 52}     # 7 base + 8 from the bow; it needs 52
    assert any(line.startswith("Dexterity: 15 of the 52 the gems and gear require") for line in res["notes"])


def test_an_item_above_the_character_level_gets_a_note(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW])
    assert "Dualstring Bow requires level 28, above the character level 1." in res["notes"]
    high = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW], character_level=30)
    assert not any("above the character level" in line for line in high["notes"])


def test_a_weapon_removes_the_attack_skill_warning_and_adds_the_gear_note(tools):
    without = tools.export_pob("Witch", skills=["Unearth"], gear=["Body Armour: Golden Mantle"])
    with_bow = tools.export_pob("Witch", skills=["Unearth"], gear=[BOW])
    assert any("disabled until a weapon" in line for line in without["notes"])
    assert not any("disabled until a weapon" in line for line in with_bow["notes"])
    assert any(line.startswith("Gear modifiers are written at the upper end of their best tier") for line in with_bow["notes"])
    bare = tools.export_pob("Witch", skills=["Unearth"])["notes"]
    assert not any("upper end" in line for line in bare) and any("The code has no gear" in line for line in bare)
    assert not any("The code has no gear" in line for line in with_bow["notes"] + without["notes"])
    assert "upper end of their best tier" in xml_of(with_bow).find("Notes").text       # the Notes tab in PoB
    assert "No gear" in xml_of(tools.export_pob("Witch", skills=["Unearth"])).find("Notes").text


def test_gear_alone_is_enough_for_a_code(tools):
    res = tools.export_pob("Witch", gear=["Body Armour: Golden Mantle"])
    assert list(items_of(res)) == ["Body Armour"] and xml_of(res).find("Skills/SkillSet").findall("Skill") == []


# -- errors ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gear, message", [
    (["Golden Mantle"], "a gear entry is 'slot: item; modifier; modifier'"),
    ([": Golden Mantle"], "a gear entry is 'slot: item; modifier; modifier'"),
    (["Hat: Golden Mantle"], "unknown gear slot 'Hat'"),
    (["Helmet: ; +# to Strength"], "needs an item after the slot"),
    (["Helmet: " + "x" * 130], "longer than 120"),
    (["Helmet: Golden Mantle"] * (MAX_GEAR + 1), "the limit is 16"),
    ("Helmet: Golden Mantle", "gear must be a list"),
])
def test_bad_gear(tools, gear, message):
    with pytest.raises(BadArgument, match=re.escape(message)):
        tools.export_pob("Witch", skills=["Unearth"], gear=gear)


def test_spirit_on_gear_counts_and_internal_lines_stay_out(tools):
    tools.items._load()
    mantle = tools.items.bases["Golden_Mantle"]
    mantle["implicits"] = ["+(20—30) to Spirit", "local weapon implicit hidden +% base damage [20]"]
    res = tools.export_pob("Witch", skills=["Herald of Ash"], gear=["Body Armour: Golden Mantle"])
    assert items_of(res)["Body Armour"] == "Rarity: NORMAL\nGolden Mantle\nImplicits: 1\n+30 to Spirit"
    assert res["summary"]["spirit"] == {"have": 90, "need": 30}            # 60 from quests + 30 on the armour


def test_a_sceptre_base_adds_its_spirit(tools, monkeypatch):
    tools.items._load()
    tools.items.bases["Golden_Mantle"]["properties"] = ["Spirit: 100"]
    res = tools.export_pob("Witch", skills=["Herald of Ash"], gear=["Body Armour: Golden Mantle"])
    assert res["summary"]["spirit"]["have"] == 160
