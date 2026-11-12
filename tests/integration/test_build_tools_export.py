import copy
import xml.etree.ElementTree as ET

import pytest

from src.catalog.spec import load_spec
from src.tools import build_tools as bt
from src.tools.build_tools import MAX_SKILL_GROUPS, NO_GAME_ID, BuildTools
from src.tools.lookup import BadArgument, LookupService, ServiceUnavailable
from src.tools.pob_export import decode_code
from tests.kg_support import GRAPH_REL, build_full_environment, routing_classes_doc, routing_tree

pytestmark = pytest.mark.integration


def make_tools(base, classes=None, **points):
    env = build_full_environment(base, load_spec(), tree=routing_tree(),
                                 classes=classes or routing_classes_doc(**points))
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    return make_tools(tmp_path_factory.mktemp("export_env"))


def xml_of(result) -> ET.Element:
    return ET.fromstring(decode_code(result["code"]))


def spec_of(result) -> dict:
    return xml_of(result).find("Tree/Spec").attrib


def gems_of(result) -> list[list[tuple[str, str]]]:
    return [[(g.attrib["nameSpec"], g.attrib["gemId"]) for g in skill]
            for skill in xml_of(result).findall("Skills/SkillSet/Skill")]


def reasons(result) -> dict[str, str]:
    return {entry["input"]: entry["reason"] for entry in result["not_exported"]}


# -- what goes in ------------------------------------------------------------------------------------

def test_route_and_skills_become_a_code(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"], ["Unearth: Added Fire Damage", "Herald of Ash"])
    spec = spec_of(res)
    assert spec["classInternalId"] == "1" and spec["ascendancyInternalId"] == ""
    assert spec["nodes"] == "100,110,111,112,105"                    # class start, then the path_to route
    assert spec["treeVersion"] == "0_5"
    assert gems_of(res) == [[("Unearth", "Metadata/Items/Gems/Unearth"),
                             ("Added Fire Damage", "Metadata/Items/Gems/Added_Fire_Damage")],
                            [("Herald of Ash", "Metadata/Items/Gems/Herald_of_Ash")]]
    assert res["not_exported"] == []
    assert res["summary"] == {"class": "Witch", "ascendancy": None, "tree_version": "0_5",
                              "points": {"passive": {"used": 4, "limit": 123, "over": False},
                                         "ascendancy": {"used": 0, "limit": 8, "over": False}},
                              "skill_groups": 2, "gems": 3, "main_skill": "Unearth",
                              "character_level": 5, "attribute_passives": {}, "gear": [],
                              "spirit": {"have": 60, "need": 30},
                              "config": [],                         # the synthetic Herald of Ash has no damage tag
                              "attributes": {"str": {"have": 7, "need": 4}, "dex": {"have": 7, "need": 4},
                                             "int": {"have": 15, "need": 9}}}
    assert res["groups"] == [{"skill": "Unearth", "level": 2, "gems": ["Unearth", "Added Fire Damage"]},
                             {"skill": "Herald of Ash", "level": 1, "gems": ["Herald of Ash"], "spirit": 30}]
    assert xml_of(res).find("Build").attrib["className"] == "Witch"
    assert spec["title"] == "Witch (POBG)"


def test_chinese_input_gives_the_same_build_and_chinese_texts(tools):
    en = tools.export_pob("Witch", ["Heart of Ice"], ["Unearth: Added Fire Damage"])
    zh = tools.export_pob("女巫", ["冰之心"], ["掘屍：附加火焰傷害"])
    assert zh["lang"] == "zh-tw" and en["lang"] == "en"
    assert spec_of(zh)["nodes"] == spec_of(en)["nodes"] and gems_of(zh) == gems_of(en)
    assert "匯入" in zh["how_to_import"] and "Import" in en["how_to_import"]
    assert zh["notes"][0].startswith("角色等級 5。每顆技能寶石依其等級表") and "不含裝備" in xml_of(zh).find("Notes").text
    assert spec_of(zh)["title"] == "Witch（POBG）"


@pytest.mark.parametrize("entry", ["掘屍：附加火焰傷害、快速攻擊", "掘屍: 附加火焰傷害，快速攻擊", "Unearth:Added Fire Damage,Faster Attacks"])
def test_supports_split_on_chinese_and_english_separators(tools, entry):
    res = tools.export_pob("Witch", skills=[entry])
    assert [name for name, _ in gems_of(res)[0]] == ["Unearth", "Added Fire Damage"]
    assert [e["reason"] for e in res["not_exported"]] == ["Faster Attacks cannot support Unearth in the local data"]


def test_ascendancy_route_and_internal_id(tools):
    res = tools.export_pob("Infernalist", ["Beidat's Will"])
    spec = spec_of(res)
    assert spec["ascendancyInternalId"] == "Witch1" and spec["classInternalId"] == "1"
    assert spec["nodes"] == "100,140,141,142"
    assert res["summary"]["ascendancy"] == "Infernalist"
    assert res["summary"]["points"]["ascendancy"]["used"] == 2
    assert xml_of(res).find("Build").attrib["ascendClassName"] == "Infernalist"


def test_ascendancy_inferred_from_its_targets(tools):
    res = tools.export_pob("Witch", ["Heart of Ice", "Beidat's Will"])
    assert spec_of(res)["ascendancyInternalId"] == "Witch1"
    assert spec_of(res)["nodes"].split(",")[-3:] == ["140", "141", "142"]


def test_ascendancy_without_a_pob_id_is_left_out(tools):
    res = tools.export_pob("Witch", ["Heart of Ice", "Sanguimancy"], ascendancy="Blood Mage")
    spec = spec_of(res)
    assert spec["ascendancyInternalId"] == "" and spec["nodes"] == "100,110,111,112,105"
    assert res["summary"]["ascendancy"] is None
    assert res["summary"]["points"]["ascendancy"]["used"] == 0 and res["summary"]["points"]["passive"]["used"] == 4
    why = reasons(res)
    assert "no id for this ascendancy" in why["Blood Mage"]
    assert why["Sanguimancy"] == "belongs to the Blood Mage ascendancy, which was left out"


def test_ascendancy_without_a_pob_id_given_as_the_class(tools):
    res = tools.export_pob("Blood Mage", skills=["Unearth"])
    assert spec_of(res)["nodes"] == "100" and spec_of(res)["ascendancyInternalId"] == ""
    res = tools.export_pob("Blood Mage", ["Sanguimancy"])
    assert spec_of(res)["nodes"] == "100" and res["summary"]["points"]["ascendancy"]["used"] == 0


def test_only_skills_gives_the_class_start(tools):
    res = tools.export_pob("Sorceress", skills=["Herald of Ash"])
    assert spec_of(res)["nodes"] == "100" and spec_of(res)["classInternalId"] == "7"
    assert res["summary"]["points"]["passive"] == {"used": 0, "limit": 123, "over": False}


def test_only_targets_gives_an_empty_skill_set(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"])
    assert gems_of(res) == [] and res["summary"]["skill_groups"] == 0 and res["summary"]["main_skill"] is None


def test_control_characters_in_the_title_are_dropped(tools):
    assert spec_of(tools.export_pob("Witch", ["Heart of Ice"], title="Cold\x01Witch"))["title"] == "ColdWitch"


def test_supports_are_written_at_level_one(tools):
    gems = xml_of(tools.export_pob("Witch", skills=["Unearth: Added Fire Damage"])).findall("Skills/SkillSet/Skill/Gem")
    assert [g.attrib["level"] for g in gems] == ["1", "1"]            # no points spent: character level 1


def test_custom_title(tools):
    assert spec_of(tools.export_pob("Witch", ["Heart of Ice"], title="  Cold   Witch  "))["title"] == "Cold Witch"
    assert spec_of(tools.export_pob("Witch", ["Heart of Ice"], title="冰之女巫"))["title"] == "冰之女巫"
    assert spec_of(tools.export_pob("Witch", ["Heart of Ice"], title="   "))["title"] == "Witch (POBG)"


# -- what stays out ------------------------------------------------------------------------------------

def test_unknown_incompatible_and_wrong_kind_supports_stay_out(tools):
    res = tools.export_pob("Witch", skills=["Unearth: Faster Attacks, Not A Gem, Herald of Ash, "
                                            "Added Fire Damage, added fire damage"])
    assert gems_of(res) == [[("Unearth", "Metadata/Items/Gems/Unearth"),
                             ("Added Fire Damage", "Metadata/Items/Gems/Added_Fire_Damage")]]
    why = reasons(res)
    assert why["Faster Attacks"] == "Faster Attacks cannot support Unearth in the local data"
    assert why["Not A Gem"] == "no exact match in local data"
    assert why["Herald of Ash"] == "Herald of Ash is not a support gem"
    assert len(res["not_exported"]) == 3                                # the repeated support is not reported
    assert {entry["expected"] for entry in res["not_exported"]} == {"support gem"}


def test_unknown_or_support_skill_leaves_the_whole_group_out(tools):
    res = tools.export_pob("Witch", skills=["Not A Gem: Added Fire Damage", "Added Fire Damage: Unearth",
                                            "Herald of Ash"])
    assert gems_of(res) == [[("Herald of Ash", "Metadata/Items/Gems/Herald_of_Ash")]]
    why = reasons(res)
    assert why["Not A Gem: Added Fire Damage"].endswith("(Not A Gem); the whole group was left out")
    assert "support gem" in why["Added Fire Damage: Unearth"]
    assert res["summary"]["skill_groups"] == 1


def test_gem_without_game_id_stays_out_with_its_reason(tools):
    res = tools.export_pob("Witch", skills=["Leap Slam: Added Fire Damage"])
    assert gems_of(res) == [] and reasons(res)["Leap Slam: Added Fire Damage"] == f"Leap Slam: {NO_GAME_ID}"


def test_unknown_and_unreachable_targets_are_reported(tools):
    res = tools.export_pob("Druid", ["Not A Node", "320", "Heart of Ice"])
    assert reasons(res) == {"Not A Node": "no exact match in local data", "320": "needs the Oracle ascendancy"}
    assert {e["expected"] for e in res["not_exported"]} == {"passive"}
    assert "320" not in spec_of(res)["nodes"].split(",") and spec_of(res)["nodes"].endswith(",105")
    assert spec_of(res)["classInternalId"] == "11" and spec_of(res)["ascendancyInternalId"] == ""


def test_ascendancy_target_unlocks_its_path(tools):
    res = tools.export_pob("Druid", ["Converging Paths", "320"])
    assert res["not_exported"] == [] and spec_of(res)["ascendancyInternalId"] == "Druid1"
    assert {"300", "320", "340", "341"} <= set(spec_of(res)["nodes"].split(","))


def test_support_cap(tools, monkeypatch):
    monkeypatch.setattr(bt, "MAX_SUPPORTS", 0)
    res = tools.export_pob("Witch", skills=["Unearth: Added Fire Damage"])
    assert gems_of(res) == [[("Unearth", "Metadata/Items/Gems/Unearth")]]
    assert reasons(res)["Added Fire Damage"] == "a skill group here holds at most 0 supports"


def test_supports_go_in_unchecked_without_the_graph_and_a_note_says_so(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph = None
    res = tools.export_pob("Witch", skills=["Unearth: Faster Attacks"])
    assert gems_of(res)[0][1] == ("Faster Attacks", "Metadata/Items/Gems/Faster_Attacks")
    assert res["notes"][-1].startswith("Support compatibility was not checked for Unearth")


def test_a_skill_missing_from_the_graph_is_unchecked_not_rejected(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph.remove_node("gem:Unearth")
    res = tools.export_pob("Witch", skills=["Unearth: Added Fire Damage", "Herald of Ash: Added Fire Damage"])
    assert [name for name, _ in gems_of(res)[0]] == ["Unearth", "Added Fire Damage"]
    assert [e["input"] for e in res["not_exported"]] == ["Added Fire Damage"]      # Herald of Ash: checked, rejected
    assert any("not checked for Unearth:" in line for line in res["notes"])


# -- main skill ------------------------------------------------------------------------------------------

def test_main_skill_picks_its_group(tools):
    res = tools.export_pob("Witch", skills=["Unearth", "Herald of Ash"], main_skill="灰燼信使")
    assert xml_of(res).find("Build").attrib["mainSocketGroup"] == "2"
    assert res["summary"]["main_skill"] == "Herald of Ash"


def test_self_support_duplicate_group_and_main_skill_without_groups_are_reported(tools):
    res = tools.export_pob("Witch", skills=["Unearth: Unearth", "掘屍", "Herald of Ash"])
    why = reasons(res)
    assert why["Unearth"] == "Unearth is the group's own skill, not a support"
    assert why["掘屍"] == "Unearth is already the skill of an earlier group"
    assert [g["skill"] for g in res["groups"]] == ["Unearth", "Herald of Ash"]
    res = tools.export_pob("Witch", ["Heart of Ice"], skills=["Not A Gem"], main_skill="Unearth")
    assert reasons(res)["Unearth"] == "no skill group was exported"


@pytest.mark.parametrize("main_skill", ["Contagion", "Not A Gem", "Leap Slam"])
def test_main_skill_not_in_the_groups_falls_back_to_the_first(tools, main_skill):
    res = tools.export_pob("Witch", skills=["Unearth", "Herald of Ash"], main_skill=main_skill)
    assert xml_of(res).find("Build").attrib["mainSocketGroup"] == "1"
    assert "first group is the main skill" in reasons(res)[main_skill]


def test_blank_main_skill_is_ignored(tools):
    res = tools.export_pob("Witch", skills=["Unearth"], main_skill="  ")
    assert res["not_exported"] == []


# -- budget and notes ------------------------------------------------------------------------------------

def test_over_budget_route_gets_a_note(tmp_path):
    res = make_tools(tmp_path, passive=2).export_pob("Witch", ["Heart of Ice"])
    assert res["summary"]["points"]["passive"]["over"] is True
    assert res["notes"][-1] == "The route uses 4 passive points, more than the 2 available."


def test_ascendancy_over_budget_gets_its_own_note(tmp_path):
    res = make_tools(tmp_path, ascendancy=1).export_pob("Infernalist", ["Beidat's Will"])
    assert res["summary"]["points"]["ascendancy"]["over"] is True
    assert res["notes"][-1] == "The route uses 2 ascendancy points, more than the 1 available."


# -- attribute passives -------------------------------------------------------------------------------

@pytest.fixture
def attr_tools(tmp_path):
    tools = make_tools(tmp_path)
    for node_id in ("110", "111"):                      # on the Heart of Ice route
        tools.lookup.passives[node_id]["type"] = "Attribute"
    tools.lookup._gem_record("skill_gem", "Unearth")["attribute_colour"] = "int"
    return tools


def overrides_of(result):
    node = xml_of(result).find("Tree/Spec/Overrides/AttributeOverride")
    return None if node is None else dict(node.attrib)


def test_requirements_met_so_attribute_passives_take_the_main_skill_attribute(attr_tools):
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"])           # needs 9 Int, Witch has 15
    assert overrides_of(res) == {"strNodes": "", "dexNodes": "", "intNodes": "110,111"}
    assert res["summary"]["attribute_passives"] == {"int": 2}
    assert res["summary"]["attributes"]["int"] == {"have": 25, "need": 9}
    assert res["notes"][-1].startswith("2 attribute passives on the route are set to cover the gems' "
                                       "requirements first: Intelligence × 2.")


def test_attribute_passives_go_to_the_attribute_that_is_short_first(attr_tools):
    herald = attr_tools.lookup._gem_record("spirit_gem", "Herald_of_Ash")
    herald["level_effects"] = [{"Level": "1", "Requires Level": "0", "Str": "4", "Dex": "12"}]   # Witch has 7 Dex
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth", "Herald of Ash"])
    assert overrides_of(res) == {"strNodes": "", "dexNodes": "110", "intNodes": "111"}
    assert res["summary"]["attributes"]["dex"] == {"have": 12, "need": 12}
    assert not any("must come from gear" in line for line in res["notes"])


def test_what_the_passives_cannot_cover_is_reported(attr_tools):
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth: Added Fire Damage"], character_level=10)
    assert res["groups"][0]["level"] == 3                                           # level 3 needs level 10
    assert res["summary"]["attributes"]["int"] == {"have": 25, "need": 30}          # PoB: max(gem 30, supports 5)
    assert "Intelligence: 25 of the 30 the gems and gear require; the missing 5 must come from gear" in res["notes"][-1]
    assert "Only fixed attributes are counted" in res["notes"][-1]


def test_support_additions_are_summed_over_all_groups_and_compared_not_added(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph = None                                          # so both groups take the support
    tools.lookup._gem_record("support_gem", "Added_Fire_Damage")["requires_stats"] = "+20 Int"
    res = tools.export_pob("Witch", skills=["Unearth: Added Fire Damage", "Contagion: Added Fire Damage"])
    assert [len(g["gems"]) for g in res["groups"]] == [2, 2]
    assert res["summary"]["attributes"]["int"]["need"] == 40           # 20 + 20 from supports; the gems need 4


def test_a_skill_without_a_colour_sends_the_rest_to_the_most_needed_attribute(attr_tools):
    herald = attr_tools.lookup._gem_record("spirit_gem", "Herald_of_Ash")
    herald["level_effects"] = [{"Level": "1", "Requires Level": "0", "Str": "4", "Dex": "12"}]
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Herald of Ash"])     # short 5 Dex, two passives
    assert overrides_of(res) == {"strNodes": "", "dexNodes": "110,111", "intNodes": ""}
    assert any(line.startswith("2 attribute passives on the route are set to cover") for line in res["notes"])


def test_ties_go_to_the_main_skill_attribute(attr_tools):
    unearth = attr_tools.lookup._gem_record("skill_gem", "Unearth")
    unearth["level_effects"] = [{"Level": "1", "Requires Level": "0", "Str": "12", "Int": "20"}]   # both short 5
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"])
    assert overrides_of(res) == {"strNodes": "111", "dexNodes": "", "intNodes": "110"}


def test_asked_attribute_has_its_own_note(attr_tools):
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"], attribute="str")
    assert res["notes"][-1] == "2 attribute passives on the route are set as asked: Strength × 2."


def test_fixed_attributes_of_other_passives_count(attr_tools):
    attr_tools._stats_by_node = None
    attr_tools.lookup.stat_rows.append({"node_id": "112", "family": "all attributes", "kind": "flat", "value": 5.0,
                                        "text": "+5 to all Attributes", "template": "+# to all Attributes"})
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"])
    assert res["summary"]["attributes"]["str"]["have"] == 12 and res["summary"]["attributes"]["int"]["have"] == 30


@pytest.mark.parametrize("given, key", [("dex", "dexNodes"), ("Strength", "strNodes"), ("敏捷", "dexNodes")])
def test_attribute_argument_wins(attr_tools, given, key):
    res = attr_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"], attribute=given)
    assert overrides_of(res)[key] == "110,111"


def test_no_attribute_known_leaves_them_unset_with_a_note(attr_tools):
    res = attr_tools.export_pob("Witch", ["Heart of Ice"])                           # no gem to take one from
    assert overrides_of(res) is None and res["summary"]["attribute_passives"] == {}
    assert res["notes"][-1].startswith("2 attribute passives on the route give nothing")


def test_without_base_attributes_have_is_unknown_and_the_main_skill_attribute_is_used(tmp_path):
    doc = copy.deepcopy(routing_classes_doc())
    for cls in doc["classes"]:
        cls.pop("base_attributes")
    tools = make_tools(tmp_path, classes=doc)
    tools.lookup.passives["110"]["type"] = "Attribute"
    tools.lookup._gem_record("skill_gem", "Unearth")["attribute_colour"] = "int"
    res = tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"], character_level=10)
    assert overrides_of(res)["intNodes"] == "110"
    assert res["summary"]["attributes"]["int"] == {"have": None, "need": 30}
    assert not any("must come from gear" in line for line in res["notes"])


def test_route_without_attribute_passives_writes_no_overrides(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"], attribute="int")
    assert overrides_of(res) is None and res["summary"]["attribute_passives"] == {}


# -- character level and gem levels --------------------------------------------------------------------

@pytest.mark.parametrize("level, gem_level", [(None, 2), (1, 1), (9, 2), (10, 3), (100, 3)])
def test_skill_gem_level_follows_the_character_level(tools, level, gem_level):
    res = tools.export_pob("Witch", ["Heart of Ice"], ["Unearth", "Leap Slam"], character_level=level)
    assert res["groups"][0]["level"] == gem_level
    assert xml_of(res).find("Skills/SkillSet/Skill/Gem").attrib["level"] == str(gem_level)


def test_asked_level_is_kept_and_a_route_that_needs_more_gets_a_note(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"], character_level=3)
    build = xml_of(res).find("Build").attrib
    assert build["level"] == "3" and build["characterLevelAutoMode"] == "false"
    assert res["notes"][-1] == ("The route spends 4 passive points, which needs level 5; the code is set to "
                                "level 3 as asked.")
    high = tools.export_pob("Witch", ["Heart of Ice"], character_level=60)
    assert xml_of(high).find("Build").attrib["level"] == "60" and "as asked" not in high["notes"][-1]
    assert xml_of(tools.export_pob("Witch", ["Heart of Ice"])).find("Build").attrib["characterLevelAutoMode"] == "true"


@pytest.mark.parametrize("level", [0, 101, -5, "5", 5.0, True])
def test_bad_character_level(tools, level):
    with pytest.raises(BadArgument, match="character_level must be a whole number from 1 to 100"):
        tools.export_pob("Witch", ["Heart of Ice"], character_level=level)


def test_gem_level_and_needs_reads_the_level_table():
    record = {"level_effects": [{"Level": "1", "Requires Level": "0", "Dex": "4"},
                                {"Level": "20", "Requires Level": "90", "Dex": "157", "Int": ""},
                                {"Level": "21", "Requires Level": "", "Dex": ""},
                                {"Level": "x", "Requires Level": "1"}]}
    assert bt.gem_level_and_needs(record, 89) == (1, {"dex": 4})
    assert bt.gem_level_and_needs(record, 90) == (20, {"dex": 157})
    assert bt.gem_level_and_needs({}, 50) == (1, {})
    assert bt.gem_level_and_needs({"level_effects": [{"Level": "1", "Requires Level": "8", "Str": "9"}]}, 2) == (1, {"str": 9})
    late = {"level_effects": [{"Level": "20", "Requires Level": "90", "Int": "150"},
                              {"Level": "5", "Requires Level": "14", "Int": "28"}]}
    assert bt.gem_level_and_needs(late, 1) == (5, {"int": 28})          # nothing usable yet: its lowest level
    assert bt.support_needs({"requires_stats": "+5 Int"}) == {"int": 5}
    assert bt.support_needs({"requires_stats": "(4 — 157) Dex"}) == {} and bt.support_needs({}) == {}


# -- spirit ---------------------------------------------------------------------------------------------

def test_spirit_reserved_against_what_the_level_has(tools):
    low = tools.export_pob("Witch", skills=["Unearth", "Herald of Ash"])                 # PoB counts every quest reward
    assert low["summary"]["spirit"] == {"have": 60, "need": 30}
    assert not any(line.startswith("Spirit:") for line in low["notes"])
    assert any(line.startswith("Spirit counts every Spirit quest reward, as PoB does by default; in the game they come "
                               "at area levels 11, 36.") for line in low["notes"])
    high = tools.export_pob("Witch", skills=["Herald of Ash"], character_level=90)
    assert high["summary"]["spirit"]["have"] == 60
    assert not any(line.startswith("Spirit counts every") for line in high["notes"])


def test_spirit_short_gets_a_note(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup._gem_record("spirit_gem", "Herald_of_Ash")["cost"] = "90 Spirit"
    res = tools.export_pob("Witch", skills=["Herald of Ash"])
    assert res["summary"]["spirit"] == {"have": 60, "need": 90}
    assert any(line.startswith("Spirit: the persistent skills and their supports reserve 90, the character has 60; "
                               "30 short.") for line in res["notes"])


def test_reservation_multiplier_life_reservation_and_unknown_costs(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph = None
    added = tools.lookup._gem_record("support_gem", "Added_Fire_Damage")
    added["main_stat"] = "Reservation Multiplier: 130%"
    assert tools.export_pob("Witch", skills=["Herald of Ash: Added Fire Damage"])["summary"]["spirit"]["need"] == 39
    added["main_stat"] = "Reservation Multiplier: 135%"           # 30 x 1.35 = 40.5: PoB rounds a half up
    assert tools.export_pob("Witch", skills=["Herald of Ash: Added Fire Damage"])["summary"]["spirit"]["need"] == 41
    added.update(main_stat=None, description="Supports Persistent Skills, making them Reserve Life instead of Spirit .")
    assert tools.export_pob("Witch", skills=["Herald of Ash: Added Fire Damage"])["summary"]["spirit"]["need"] == 0
    unearth = tools.lookup._gem_record("skill_gem", "Unearth")
    unearth.update(cost="(90 — 30) Spirit", tags=["Minion", "Persistent"])
    res = tools.export_pob("Witch", skills=["Unearth", "Herald of Ash"])
    assert res["summary"]["spirit"] == {"have": 60, "need": 30, "unknown": ["Unearth"]}
    assert any(line.startswith("Spirit reserved by Unearth is not counted") for line in res["notes"])


def test_supports_add_reservation_only_on_skills_that_reserve_spirit(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph = None                                              # so both skills take the support
    tools.lookup._gem_record("support_gem", "Added_Fire_Damage")["main_stat"] = "Additional Reservation: 20 Spirit"
    res = tools.export_pob("Witch", skills=["Herald of Ash: Added Fire Damage", "Unearth: Added Fire Damage"],
                           character_level=40)
    assert res["summary"]["spirit"] == {"have": 60, "need": 50}
    assert [g.get("spirit") for g in res["groups"]] == [50, None]


def test_spirit_from_passives_counts_and_no_quest_data_leaves_have_unknown(tmp_path):
    tools = make_tools(tmp_path)
    res = tools.export_pob("Infernalist", ["Beidat's Will"], ["Herald of Ash"])          # the node gives +10 Spirit
    assert res["summary"]["spirit"] == {"have": 70, "need": 30}
    doc = copy.deepcopy(routing_classes_doc())
    doc.pop("pob_spirit_quests")
    bare = make_tools(tmp_path / "bare", classes=doc).export_pob("Witch", skills=["Herald of Ash"])
    assert bare["summary"]["spirit"] == {"have": None, "need": 30}
    assert not any(line.startswith("Spirit:") for line in bare["notes"])


# -- PoB configuration -------------------------------------------------------------------------------------

def config_of(result):
    node = xml_of(result).find("Config/ConfigSet")
    return [] if node is None else [i.attrib["name"] for i in node.findall("Input")]


@pytest.fixture
def cfg_tools(tmp_path):
    tools = make_tools(tmp_path)
    unearth = tools.lookup._gem_record("skill_gem", "Unearth")
    unearth.update(description="Raise a corpse. Grants you a Power Charge on Hit.", extra_properties=["Blinds Enemies"],
                   tags=["Spell", "Minion", "Lightning"])
    tools.lookup._gem_record("support_gem", "Added_Fire_Damage").update(
        description="Supported Skills deal more damage against Bleeding Enemies.", extra_properties=[],
        main_stat=None, tags=["Support", "Fire"])
    tools.lookup.passives["105"]["stats"] = ["10% chance to Daze on Hit"]
    return tools


def test_options_come_with_their_evidence(cfg_tools):
    res = cfg_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth: Added Fire Damage"])
    assert config_of(res) == ["usePowerCharges", "conditionEnemyShocked", "conditionEnemyBlinded", "conditionEnemyDazed"]
    evidence = {c["option"]: c["evidence"] for c in res["summary"]["config"]}
    assert evidence["usePowerCharges"] == [{"source": "gem", "name": "Unearth", "text": "Grants you a Power Charge on Hit."}]
    assert evidence["conditionEnemyShocked"][0] == {"source": "glossary", "name": "Shock",
                                                    "text": "Lightning damage from Hits (Unearth)"}
    assert evidence["conditionEnemyDazed"][0]["source"] == "passive" and evidence["conditionEnemyDazed"][0]["name"] == "Heart of Ice"
    assert "conditionEnemyBleeding" not in evidence                     # "against Bleeding Enemies" only benefits
    assert "conditionEnemyIgnited" not in evidence                      # a support's element tag is not damage
    assert {c["label"] for c in res["summary"]["config"]} == {"Power Charges", "enemy Shocked", "enemy Blinded",
                                                              "enemy Dazed"}


def test_config_notes_and_the_notes_tab(cfg_tools):
    res = cfg_tools.export_pob("Witch", ["Heart of Ice"], ["Unearth"])
    assert any(n.startswith("PoB Configuration switched on, each from this build's own gems, passives or gear: "
                            "Power Charges, enemy Shocked, enemy Blinded, enemy Dazed.") for n in res["notes"])
    assert "Charges are counted at their maximum; set a lower count in PoB's Configuration tab." in res["notes"]
    ladder = next(n for n in res["notes"] if n.startswith("poe.ninja's ladder exports"))
    assert "Crit Recently, enemy Bleeding" in ladder and "enemy Blinded" not in ladder and "enemy Dazed" not in ladder
    assert "Power Charges, enemy Shocked" in xml_of(res).find("Notes").text
    zh = cfg_tools.export_pob("女巫", ["冰之心"], ["掘屍"])
    assert any(n.startswith("PoB 配置已開啟") and "暴擊球" in n for n in zh["notes"])


def test_a_skill_left_out_is_no_evidence(cfg_tools):
    cfg_tools.lookup._gem_record("support_gem", "Faster_Attacks").update(description="Grants a Frenzy Charge on Hit.")
    res = cfg_tools.export_pob("Witch", skills=["Unearth: Faster Attacks"])           # Faster Attacks cannot support it
    assert "useFrenzyCharges" not in config_of(res)


def test_gear_lines_and_weapon_elements_are_evidence(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup._gem_record("skill_gem", "Unearth").update(description="Raise a corpse.", extra_properties=[], tags=[])
    gear = [{"label": "Ring", "item": bt.PobItem("Ring 1", "RARE", "x", "Ruby Ring", (), ("5% chance to Poison on Hit",))},
            {"label": "Bow", "item": bt.PobItem("Weapon 1", "RARE", "x", "Bow", (), ("Adds 5 to 9 Fire Damage",))}]
    plan = tools._config_plan([], [], gear)                               # no attack: the weapon's element is unused
    assert list(plan) == ["conditionEnemyPoisoned"]
    attack = {"records": [("Leap Slam", "skill_gem", {"tags": ["Attack"], "description": "Jump."})]}
    plan = tools._config_plan([], [attack], gear)
    assert list(plan) == ["conditionEnemyIgnited", "conditionEnemyPoisoned"]
    offhand = [{"label": "Quiver", "item": bt.PobItem("Weapon 2", "RARE", "x", "Quiver", (), ("Adds 5 to 9 Fire Damage",))}]
    assert list(tools._config_plan([], [attack], offhand)) == []           # only the main hand's element
    assert plan["conditionEnemyPoisoned"][0] == {"source": "gear", "name": "Ring", "text": "5% chance to Poison on Hit"}


def test_buffs_do_not_hit_and_cannot_lines_block_their_group(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.graph = None
    tools.lookup._gem_record("spirit_gem", "Herald_of_Ash").update(tags=["Buff", "Aura", "Persistent", "Lightning"],
                                                                   description="An aura.", extra_properties=[])
    assert "conditionEnemyShocked" not in config_of(tools.export_pob("Witch", skills=["Herald of Ash"]))
    tools.lookup._gem_record("skill_gem", "Contagion").update(tags=["Spell", "Curse", "Cold"], description="A curse.",
                                                              extra_properties=[])        # spell-tagged, does not hit
    assert "conditionEnemyChilled" not in config_of(tools.export_pob("Witch", skills=["Contagion"]))
    tools.lookup._gem_record("skill_gem", "Unearth").update(tags=["Spell", "Lightning"], description="Zap.",
                                                            extra_properties=[])
    tools.lookup._gem_record("support_gem", "Added_Fire_Damage").update(
        description="Supported Skills Cannot inflict Shock", extra_properties=[], main_stat=None)
    assert "conditionEnemyShocked" in config_of(tools.export_pob("Witch", skills=["Unearth"]))
    blocked = tools.export_pob("Witch", skills=["Unearth: Added Fire Damage"])
    assert "conditionEnemyShocked" not in config_of(blocked)


def test_no_evidence_and_config_off_write_no_config(tmp_path):
    tools = make_tools(tmp_path)
    for kind, slug in (("skill_gem", "Unearth"), ("spirit_gem", "Herald_of_Ash")):
        tools.lookup._gem_record(kind, slug).update(description="Nothing.", extra_properties=[], tags=[])
    res = tools.export_pob("Witch", skills=["Unearth", "Herald of Ash"])
    assert config_of(res) == [] and res["summary"]["config"] == []
    assert any(n.startswith("No PoB Configuration option has evidence") for n in res["notes"])
    off = make_tools(tmp_path / "b").export_pob("Witch", skills=["Unearth"], config=False)
    assert config_of(off) == [] and any(n.startswith("PoB Configuration left empty as asked") for n in off["notes"])


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_config_must_be_a_boolean(tools, value):
    with pytest.raises(BadArgument, match="config must be true or false"):
        tools.export_pob("Witch", skills=["Unearth"], config=value)


# -- routes PoB can build ---------------------------------------------------------------------------------

def test_routes_do_not_pass_through_another_class_start(tools):
    res = tools.path_to("Druid", ["110"])                       # the short way would cross the Witch start
    assert "100" not in [row["id"] for row in res["path"]] and res["path"][-1]["id"] == "110"


def test_nodes_allocated_for_free_cost_no_point(tmp_path):
    tools = make_tools(tmp_path)
    tools.lookup.passives["141"]["no_point"] = True
    res = tools.path_to("Infernalist", ["Beidat's Will"])
    assert [row["id"] for row in res["ascendancy_path"]] == ["141", "142"]
    assert res["points"]["ascendancy"]["used"] == 1


def test_notes_name_the_gem_level_and_tree_version(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"])
    assert res["notes"][0] == ("Character level 5. Each skill gem is set to the highest level (at most 20) a "
                               "level-5 character can use, from its level table, quality 0; support gems have no level.")
    assert any("disabled until a weapon is added" in line for line in res["notes"])
    assert any("0_5" in line for line in res["notes"])
    assert "0_5" in xml_of(res).find("Notes").text


def test_writes_no_file(tmp_path):
    tools = make_tools(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    tools.export_pob("Witch", ["Heart of Ice"], ["Unearth: Added Fire Damage"])
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")} == before


# -- errors ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kwargs, message", [
    ({"class_name": "Witch"}, "at least one target passive, skill or gear entry"),
    ({"class_name": "Nobody", "targets": ["Heart of Ice"]}, "unknown class"),
    ({"class_name": "", "targets": ["Heart of Ice"]}, "class_name must not be empty"),
    ({"class_name": "Witch", "skills": "Unearth"}, "skills must be a list"),
    ({"class_name": "Witch", "skills": ["Unearth"] * (MAX_SKILL_GROUPS + 1)}, "the limit is 12"),
    ({"class_name": "Witch", "skills": [": Added Fire Damage"]}, "must start with a skill gem"),
    ({"class_name": "Witch", "skills": ["Unearth: " + "a" * 130]}, "longer than 120"),
    ({"class_name": "Witch", "skills": ["x" * 401]}, "longer than 400"),
    ({"class_name": "Witch", "skills": ["Unearth"], "title": "t" * 81}, "title is longer than 80"),
    ({"class_name": "Witch", "skills": ["Unearth"], "main_skill": "m" * 121}, "main_skill is longer"),
    ({"class_name": "Witch", "skills": ["Unearth"], "ascendancy": "Titan"}, "not an ascendancy of Witch"),
    ({"class_name": "Witch", "skills": ["Unearth"], "lang": "fr"}, "lang must be one of"),
    ({"class_name": "Witch", "skills": ["Unearth"], "attribute": "luck"}, "attribute must be one of"),
])
def test_bad_arguments(tools, kwargs, message):
    with pytest.raises(BadArgument, match=message):
        tools.export_pob(**kwargs)


def test_the_code_carries_the_level_pob_would_set(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"])                   # 4 points: act 1 gives level 5
    assert xml_of(res).find("Build").attrib["level"] == "5" and res["summary"]["character_level"] == 5
    assert xml_of(tools.export_pob("Witch", skills=["Unearth"])).find("Build").attrib["level"] == "1"


def test_without_the_act_table_the_level_is_1_with_a_note(tmp_path):
    doc = copy.deepcopy(routing_classes_doc())
    doc.pop("pob_level_acts")
    res = make_tools(tmp_path, classes=doc).export_pob("Witch", ["Heart of Ice"])
    assert xml_of(res).find("Build").attrib["level"] == "1"
    assert res["notes"][-1].startswith("The code says level 1 because the local data has no PoB act table")


def test_class_data_without_pob_ids_names_the_update(tmp_path):
    doc = copy.deepcopy(routing_classes_doc())
    for cls in doc["classes"]:
        cls.pop("pob_id", None)
    tools = make_tools(tmp_path, classes=doc)
    with pytest.raises(ServiceUnavailable, match="update_data with scope passives"):
        tools.export_pob("Witch", ["Heart of Ice"])
