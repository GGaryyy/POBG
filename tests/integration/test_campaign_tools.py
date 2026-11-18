"""Campaign stages, campaign questions and campaign-stage builds on synthetic data (tests/campaign_support.py)."""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET

import pytest

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import Spec, load_spec
from src.scrapers.common import read_jsonl, write_jsonl
from src.tools import maintenance as mnt
from src.tools.build_tools import BuildTools
from src.tools.campaign import CampaignLookup
from src.tools.lookup import BadArgument, LookupService, NotFound, ServiceUnavailable
from src.tools.pob_export import decode_code
from tests.campaign_support import CampaignSite, site_pages, write_campaign_data
from tests.integration.test_maintenance import fixture_spec
from tests.item_support import write_item_data
from tests.kg_support import GRAPH_REL, ZH_NAMES, build_full_environment, routing_classes_doc, routing_tree

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = build_full_environment(tmp_path_factory.mktemp("campaign_env"), load_spec(), tree=routing_tree(),
                                  classes=routing_classes_doc())
    write_item_data(base)
    write_campaign_data(base, tmp_path_factory.mktemp("campaign_cache"))
    entities = build_entity_index(load_spec(), data_dir=base / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(base / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return base


@pytest.fixture
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


@pytest.fixture
def campaign(tools):
    return tools.campaign


def stage(campaign, stage_id):
    return next(s for s in campaign.campaign_stages()["stages"] if s["id"] == stage_id)


# -- stage limits ------------------------------------------------------------------------------------------

def test_stage_limits_come_from_the_data(campaign):
    limits = {s["id"]: s["limits"] for s in campaign.campaign_stages()["stages"]}
    assert limits["act_1"] == {"level": 12, "passive_points": 13, "quest_passive_points": 2, "ascendancy_points": 0,
                               "quest_spirit": 30, "skill_gem_level": 4, "skill_gem_tiers": [1, 3],
                               "spirit_gem_tiers": [4], "support_gem_tier": 1, "support_sockets": 2}
    assert limits["act_2"] == {"level": 28, "passive_points": 31, "quest_passive_points": 4, "ascendancy_points": 2,
                               "quest_spirit": 30, "skill_gem_level": 6, "skill_gem_tiers": [1, 3, 5],
                               "spirit_gem_tiers": [4], "support_gem_tier": 2, "support_sockets": 3}
    # the Epilog's points are placed in the last stage
    assert limits["interlude"]["passive_points"] == 40 + 6 and limits["interlude"]["quest_spirit"] == 70
    assert (limits["interlude"]["support_gem_tier"], limits["interlude"]["support_sockets"]) == (3, 3)


def test_stage_lists_rewards_trials_bosses_and_sources(campaign):
    act1 = stage(campaign, "act_1")
    assert [r["giver"] for r in act1["rewards"]] == ["Beira", "Lute", "King"]
    assert act1["rewards"][1]["tags"] == ["passive points", "天賦點"] and act1["rewards"][1]["passive_points"] == 2
    assert [b["name"] for b in act1["bosses"]] == ["Bloated One", "Beira", "Count", "Candle"]
    assert stage(campaign, "act_2")["trials"][0]["ascendancy_points"] == 2
    assert act1["sources"][0]["url"] == "https://poe2db.tw/us/Act_1"
    assert "level_note" not in act1 and "64" not in stage(campaign, "interlude")["level_note"]
    assert "61" in stage(campaign, "interlude")["level_note"]


def test_campaign_stages_say_what_is_not_in_the_data(campaign):
    result = campaign.campaign_stages(lang="zh-tw")
    assert result["lang"] == "zh-tw" and any("抗性懲罰" in line for line in result["not_in_data"])
    assert [b["name"] for b in result["stages"][0]["bosses"]][:2] == ["浮腫者", "貝伊拉"]


@pytest.mark.parametrize("name, expected", [
    ("act_2", "act_2"), ("Act 2", "act_2"), ("第 2 章", "act_2"), ("ACT2", "act_2"), (2, "act_2"),
    ("interlude", "interlude"), ("插曲", "interlude"), ("間歇", "interlude"), ("Interludes", "interlude")])
def test_stages_are_found_by_id_name_or_number(campaign, name, expected):
    assert campaign.find_stage(name)["id"] == expected


def test_unknown_or_empty_stage(campaign):
    with pytest.raises(NotFound, match="act_1 \\(Act 1\\)"):
        campaign.find_stage("Act 9")
    with pytest.raises(BadArgument):
        campaign.find_stage("")


def edited(campaign, **trial):
    """The loaded data with Act 2's trial changed (a copy; the files are not touched)."""
    copy_ = CampaignLookup(campaign.lookup)
    copy_._load()
    copy_.stages = copy.deepcopy(copy_.stages)
    copy_.stages[1]["trials"][0].update(trial)
    return copy_


def test_a_trial_at_exactly_the_stage_level_counts_and_one_above_does_not(campaign):
    assert edited(campaign, area_level=28).stage_limits("act_2")["limits"]["ascendancy_points"] == 2
    assert edited(campaign, area_level=29).stage_limits("act_2")["limits"]["ascendancy_points"] == 0
    assert edited(campaign, area_level=29).stage_limits("interlude")["limits"]["ascendancy_points"] == 2


def test_no_campaign_data_names_the_update(tmp_path):
    base = build_full_environment(tmp_path, load_spec())
    tools = BuildTools(LookupService(base_dir=base, graph_path=base / GRAPH_REL))
    with pytest.raises(ServiceUnavailable, match="update_data scope campaign"):
        tools.campaign.campaign_stages()
    with pytest.raises(ServiceUnavailable, match="campaign"):
        tools.lookup.gems_by(tag="Spell", max_level=5, earliest=tools.campaign.earliest_level)


# -- what a level allows ------------------------------------------------------------------------------------

@pytest.mark.parametrize("tier, kind, level", [(1, "skill_gem", 1), (3, "skill_gem", 6), (5, "skill_gem", 14),
                                               (4, "spirit_gem", 10), (1, "support_gem", 1), (2, "support_gem", 16),
                                               (3, "support_gem", 33), (None, "skill_gem", None),
                                               (9, "skill_gem", None)])
def test_earliest_level_of_a_gem_tier(campaign, tier, kind, level):
    assert campaign.earliest_level({"tier": tier}, kind) == level


def test_gems_by_max_level_keeps_what_can_be_had(tools):
    def names(level):
        return [g["name"] for g in tools.lookup.gems_by(kind="spirit_gem", max_level=level,
                                                         earliest=tools.campaign.earliest_level)["gems"]]
    assert names(9) == [] and names(10) == ["Herald of Ash"]
    found = tools.lookup.gems_by(kind="spirit_gem", max_level=10, earliest=tools.campaign.earliest_level)
    assert found["gems"][0]["from_level"] == 10 and found["filters"]["max_level"] == 10
    with pytest.raises(BadArgument, match="max_level"):
        tools.lookup.gems_by(kind="spirit_gem", max_level=0, earliest=tools.campaign.earliest_level)
    with pytest.raises(BadArgument, match="campaign data"):
        tools.lookup.gems_by(kind="spirit_gem", max_level=10)


def test_supports_for_max_level(tools):
    every = tools.supports_for("Unearth")
    assert "max_level" not in every
    early = tools.supports_for("Unearth", max_level=15)
    assert all(s["from_level"] <= 15 for s in early["supports"]) and early["max_level"] == 15
    assert early["total"] <= every["total"]


# -- verify_build with a level ------------------------------------------------------------------------------

def test_verify_build_moves_what_comes_later_to_too_early(tools):
    res = tools.verify_build(gems=["Herald of Ash", "Unearth", "Faster Attacks"], items=["Dualstring Bow", "Shortbow"],
                             character_level=9)
    assert [g["name"] for g in res["verified"]["gems"]] == ["Unearth"]
    assert [i["name"] for i in res["verified"]["items"]] == ["Shortbow"]
    assert {(t["name"], t["from_level"]) for t in res["too_early"]} == {
        ("Herald of Ash", 10), ("Faster Attacks", 16), ("Dualstring Bow", 28)}
    assert res["character_level"] == 9
    assert "Herald" not in res["sources_markdown"]


def test_verify_build_at_exactly_the_level_keeps_it(tools):
    res = tools.verify_build(gems=["Faster Attacks"], items=["Dualstring Bow"], character_level=28)
    assert res["too_early"] == [] and len(res["verified"]["gems"]) == len(res["verified"]["items"]) == 1


def test_modifier_tier_follows_the_level(tools):
    def best(level):
        res = tools.verify_build(affixes=["Bows: Adds # to # Fire Damage"], character_level=level)
        return res["verified"]["affixes"][0]["best"]["level"]
    assert (best(32), best(33), best(80)) == (1, 33, 75)
    res = tools.verify_build(affixes=["Bows: #% increased Area of Effect for Attacks"], character_level=30)
    assert res["verified"]["affixes"] == [] and res["too_early"][0]["from_level"] == 65


def test_verify_build_without_a_level_is_unchanged(tools):
    res = tools.verify_build(gems=["Herald of Ash"])
    assert "too_early" not in res and "character_level" not in res
    with pytest.raises(BadArgument):
        tools.verify_build(gems=["Unearth"], character_level=101)


# -- path_to by stage --------------------------------------------------------------------------------------

def small_stages(monkeypatch, tools, passive=(3, 6, 9), ascendancy=(0, 2, 4)):
    real = tools.campaign.campaign_stages

    def fake(lang=None):
        result = real(lang)
        for row, points, asc in zip(result["stages"], passive, ascendancy):
            row["limits"] = {**row["limits"], "passive_points": points, "ascendancy_points": asc}
        return result
    monkeypatch.setattr(tools.campaign, "campaign_stages", fake)


def test_path_by_stage_takes_targets_in_the_listed_order(tools, monkeypatch):
    small_stages(monkeypatch, tools)
    res = tools.path_to("Witch", ["Chaos Inoculation", "Heart of Ice"], by_stage=True)
    rows = {r["stage"]: r for r in res["stages"]}
    assert [n["id"] for n in rows["act_1"]["new_nodes"]] == ["101", "102", "103"]
    assert rows["act_2"]["targets_reached"] == ["Chaos Inoculation"]        # 106, 107, then 104
    assert rows["act_2"]["passive"] == {"used": 6, "limit": 6, "over": False}
    assert rows["interlude"]["targets_reached"] == ["Heart of Ice"] and rows["interlude"]["after_campaign"] == []
    assert [r["order"] for r in res["path"]] == list(range(1, 8))


def test_targets_beyond_the_last_stage_are_listed(tools, monkeypatch):
    small_stages(monkeypatch, tools, passive=(1, 2, 3))
    res = tools.path_to("Witch", ["Heart of Ice", "Chaos Inoculation"], by_stage=True)
    assert set(res["stages"][-1]["after_campaign"]) == {"Heart of Ice", "Chaos Inoculation"}


def test_ascendancy_points_are_cut_by_stage_too(tools, monkeypatch):
    small_stages(monkeypatch, tools)
    res = tools.path_to("Infernalist", ["Beidat's Will"], by_stage=True)
    rows = {r["stage"]: r for r in res["stages"]}
    assert rows["act_1"]["new_nodes"] == [] and rows["act_2"]["targets_reached"] == ["Beidat's Will"]
    assert rows["act_2"]["ascendancy"]["used"] == 2


def test_path_without_by_stage_is_unchanged(tools):
    res = tools.path_to("Witch", ["Heart of Ice"])
    assert "stages" not in res
    with pytest.raises(BadArgument):
        tools.path_to("Witch", ["Heart of Ice"], by_stage="yes")


# -- export_pob for a stage -----------------------------------------------------------------------------------

def specs_of(result) -> list[tuple[str, int]]:
    tree = ET.fromstring(decode_code(result["code"])).find("Tree")
    return [(s.get("title"), len(s.get("nodes").split(","))) for s in tree.findall("Spec")]


def test_stage_export_holds_one_tree_per_stage_and_the_stage_level(tools, monkeypatch):
    small_stages(monkeypatch, tools)
    res = tools.export_pob("Witch", ["Chaos Inoculation", "Heart of Ice"], ["Unearth: Added Fire Damage"],
                           stage="act_2")
    assert specs_of(res) == [("Act 1 (level 12)", 4), ("Act 2 (level 28)", 7)]     # starts + 3, starts + 6
    tree = ET.fromstring(decode_code(res["code"])).find("Tree")
    assert tree.get("activeSpec") == "2"
    build = ET.fromstring(decode_code(res["code"])).find("Build")
    assert (build.get("level"), build.get("characterLevelAutoMode")) == ("28", "false")
    assert res["stage"]["id"] == "act_2" and res["stage"]["trees"] == ["Act 1 (level 12)", "Act 2 (level 28)"]
    assert res["summary"]["points"]["passive"] == {"used": 6, "limit": 6, "over": False}
    assert [e["input"] for e in res["not_exported"]] == ["Heart of Ice"]
    assert "after Act 2" in res["not_exported"][0]["reason"]
    assert res["notes"][0].startswith("Stage Act 2: character level 28")


def test_stage_export_holds_gems_sockets_and_spirit_to_the_stage(tools, monkeypatch):
    res = tools.export_pob("Witch", [], ["Unearth: Added Fire Damage", "Herald of Ash"], stage="act_1")
    assert res["groups"][0]["gems"] == ["Unearth", "Added Fire Damage"] and res["groups"][0]["level"] == 3
    assert res["summary"]["spirit"]["have"] == 30                        # Act 1's quest Spirit only
    monkeypatch.setattr(tools.campaign, "rules", {**tools.campaign.rules, "base_support_sockets": 0})
    res = tools.export_pob("Witch", [], ["Unearth: Added Fire Damage"], stage="act_1")
    assert "0 support sockets by this stage" in res["not_exported"][0]["reason"]


def test_a_support_of_a_later_tier_stays_out(tools, monkeypatch):
    real = tools.campaign.earliest_level
    monkeypatch.setattr(tools.campaign, "earliest_level",
                        lambda record, kind: 16 if record.get("name") == "Added Fire Damage" else real(record, kind))
    res = tools.export_pob("Witch", [], ["Unearth: Added Fire Damage"], stage="act_1")
    assert res["groups"][0]["gems"] == ["Unearth"]
    assert "drops from area level 16, above 12" in res["not_exported"][0]["reason"]


def test_a_skill_gem_of_a_later_tier_drops_its_whole_group(tools, monkeypatch):
    monkeypatch.setattr(tools.campaign, "earliest_level", lambda record, kind: 30 if record.get("name") == "Unearth" else 1)
    res = tools.export_pob("Witch", [], ["Unearth: Added Fire Damage", "Contagion"], stage="act_1")
    assert [g["skill"] for g in res["groups"]] == ["Contagion"]
    assert "can be had from level 30, above 12; the whole group was left out" in res["not_exported"][0]["reason"]


def test_stage_export_holds_gear_to_the_level(tools):
    res = tools.export_pob("Witch", [], [], gear=["Weapon 1: Dualstring Bow; Adds # to # Fire Damage; "
                                                   "#% increased Area of Effect for Attacks"], stage="act_2")
    assert [e["reason"] for e in res["not_exported"]] == [
        "no tier of this modifier rolls below item level 65 (the stage is level 28)"]
    text = ET.fromstring(decode_code(res["code"])).find("Items").find("Item").text
    assert "Adds 2 to 5 Fire Damage" in text                            # tier "Heated": item level 1, not 33
    assert res["notes"][-1].startswith("Gear modifiers are written at the upper end of the best tier an item of level 28")


def test_stage_export_leaves_out_gear_above_the_level(tools):
    res = tools.export_pob("Witch", [], [], gear=["Weapon 1: Dualstring Bow"], stage="act_1")
    assert res["summary"]["gear"] == [] and "requires level 28, above 12" in res["not_exported"][0]["reason"]


def test_stage_and_character_level_together_are_refused(tools):
    with pytest.raises(BadArgument, match="either stage or character_level"):
        tools.export_pob("Witch", ["Heart of Ice"], stage="act_1", character_level=20)
    with pytest.raises(NotFound):
        tools.export_pob("Witch", ["Heart of Ice"], stage="act_9")


def test_export_without_a_stage_has_one_tree(tools):
    res = tools.export_pob("Witch", ["Heart of Ice"])
    assert len(specs_of(res)) == 1 and "stage" not in res


# -- campaign questions ----------------------------------------------------------------------------------------

def test_lookup_entity_finds_areas_bosses_and_quests(tools):
    hits = tools.lookup.lookup_entity("貝伊拉")["hits"]
    assert hits[0]["kind"] == "campaign_boss" and hits[0]["slug"] == "Beira"
    assert tools.lookup.lookup_entity("宅第", kind="campaign_area")["hits"][0]["slug"] == "Manor"
    assert tools.lookup.lookup_entity("The Lost Lute")["hits"][0]["kind"] == "campaign_quest"


def test_get_area_by_name_or_by_boss(campaign):
    area = campaign.get_area("貝伊拉")
    assert area["area"]["slug"] == "Field" and area["stage"]["name_zh_tw"] == "第 1 章"
    assert [c["name"] for c in area["connects"]] == ["營地", "宅第"]
    assert [q["name_zh_tw"] for q in area["quests"]] == ["遺失的魯特琴"]
    assert area["sources"][0]["url"] == "https://poe2db.tw/us/Field"
    assert campaign.get_area("Manor")["area"]["name_zh_tw"] == "宅第"
    with pytest.raises(NotFound, match="campaign_by"):
        campaign.get_area("Nowhere")


def test_get_quest_in_either_language(campaign):
    quest = campaign.get_quest("遺失的魯特琴")
    assert quest["quest"]["rewards"] == ["Book of Specialisation , 2 Passive Skill Points"]
    assert quest["stage"]["id"] == "act_1" and campaign.get_quest("Lost_Lute")["quest"]["name_zh_tw"] == "遺失的魯特琴"
    with pytest.raises(NotFound):
        campaign.get_quest("Nothing")


def test_campaign_by_rewards_in_chinese(campaign):
    found = campaign.campaign_by("reward", text="天賦點")
    assert [(r["stage"], r["giver"]) for r in found["results"]] == [
        ("act_1", "Lute"), ("act_2", "The Final Letter"), ("interlude", "Siege")]
    assert campaign.campaign_by("reward", text="選擇")["results"][0]["giver"] == "Medallion"


def test_campaign_by_quests_bosses_and_areas(campaign):
    assert [q["slug"] for q in campaign.campaign_by("quest", text="天賦點")["results"]] == ["Lost_Lute", "Final_Letter"]
    assert [b["name"] for b in campaign.campaign_by("boss", stage="第 2 章")["results"]] == ["Trial of Ascendancy", "Jamanra"]
    assert [a["slug"] for a in campaign.campaign_by("area", text="first town")["results"]] == ["Camp"]
    found = campaign.campaign_by("area", stage="act_1", limit=2)
    assert found["total"] == 4 and len(found["results"]) == 2 and found["sources"][0]["url"].endswith("Act_1")


def test_campaign_by_refuses_an_unknown_kind_or_long_text(campaign):
    with pytest.raises(BadArgument, match="kind"):
        campaign.campaign_by("monster")
    with pytest.raises(BadArgument):
        campaign.campaign_by("quest", text="x" * 500)


# -- update ------------------------------------------------------------------------------------------------------

def update_spec() -> Spec:
    raw = copy.deepcopy(fixture_spec().raw)
    raw["sources"]["campaign"]["expect_min"] = {"stages": 3, "areas_per_stage": 3, "quests": 3,
                                                "skill_gem_levels": 6, "support_gem_levels": 3}
    return Spec(raw)


def test_campaign_update_writes_the_data_and_the_names(tmp_path):
    base = build_full_environment(tmp_path, fixture_spec())
    tool = mnt.DataMaintenance(base, update_spec(), base / GRAPH_REL)
    site = CampaignSite()
    result = tool.update("campaign", fetch=site)
    assert result["stages"] == ["act_1", "act_2", "interlude"] and result["previous_stages"] == []
    assert (result["areas"], result["quests"], result["requests"]) == (10, 5, 20)
    index = {r["slug"]: r["kind"] for r in read_jsonl(base / "data" / "catalog" / "entity_index.jsonl")}
    assert index["Field"] == "campaign_area" and index["Lost_Lute"] == "campaign_quest"
    status = {d["name"]: d for d in tool.status()["datasets"]}["campaign"]
    assert (status["records"], status["areas"], status["quests"]) == (3, 10, 5)
    again = tool.update("campaign", fetch=CampaignSite())
    assert again["previous_stages"] == ["act_1", "act_2", "interlude"]


def test_campaign_update_that_does_not_parse_writes_nothing(tmp_path):
    base = build_full_environment(tmp_path, fixture_spec())
    tool = mnt.DataMaintenance(base, update_spec(), base / GRAPH_REL)
    pages = site_pages()
    pages["https://poe2db.tw/us/Act"] = "<html>no acts</html>"
    with pytest.raises(ServiceUnavailable, match="Nothing was written"):
        tool.update("campaign", fetch=CampaignSite(pages))
    assert not (base / "data" / "campaign").exists()


def test_campaign_update_takes_no_gem_options(tmp_path):
    base = build_full_environment(tmp_path, fixture_spec())
    tool = mnt.DataMaintenance(base, update_spec(), base / GRAPH_REL)
    with pytest.raises(BadArgument, match="a campaign update always"):
        tool.update("campaign", names=["Act 1"], fetch=CampaignSite())


def test_update_prompt_for_campaign():
    from src.tools.build_workflow import update_prompt_text
    text = update_prompt_text("campaign")
    assert 'scope="campaign"' in text and "about 26 requests" in text
    assert re.search(r"Report the `stages`", text)


# -- review follow-ups ---------------------------------------------------------------------------------------

def test_stage_export_with_an_ascendancy_pob_lacks_keeps_the_main_tree(tools, monkeypatch):
    small_stages(monkeypatch, tools)
    res = tools.export_pob("Blood Mage", ["Chaos Inoculation", "Sanguimancy"], stage="act_2")
    assert specs_of(res)[-1][1] == 6                      # the start + the 5 passives to Chaos Inoculation
    assert res["summary"]["points"]["passive"]["used"] == 5 and res["summary"]["ascendancy"] is None


def test_later_targets_are_reported_as_written(tools, monkeypatch):
    small_stages(monkeypatch, tools, passive=(1, 2, 3))
    res = tools.export_pob("Witch", ["冰之心"], stage="act_1")
    assert [e["input"] for e in res["not_exported"]] == ["冰之心"]


def test_a_stage_export_without_targets_has_one_starts_only_tree_per_stage(tools):
    res = tools.export_pob("Witch", [], ["Unearth"], stage="act_2")
    assert specs_of(res) == [("Act 1 (level 12)", 1), ("Act 2 (level 28)", 1)]


def test_supports_for_max_level_drops_a_later_tier(tools, monkeypatch):
    real = tools.campaign.earliest_level
    monkeypatch.setattr(tools.campaign, "earliest_level",
                        lambda record, kind: 16 if record.get("name") == "Added Fire Damage" else real(record, kind))
    assert "Added Fire Damage" not in [s["name"] for s in tools.supports_for("Unearth", max_level=15)["supports"]]
    kept = tools.supports_for("Unearth", max_level=16)["supports"]
    assert [(s["name"], s["from_level"]) for s in kept if s["name"] == "Added Fire Damage"] == [("Added Fire Damage", 16)]


def test_results_are_copies(campaign):
    campaign.get_area("Field")["area"]["bosses"].clear()
    campaign.get_quest("Lost_Lute")["quest"]["rewards"].append("x")
    stage(campaign, "act_2")["trials"].clear()
    assert campaign.get_area("Field")["area"]["bosses"] and stage(campaign, "act_2")["trials"]
    assert campaign.get_quest("Lost_Lute")["quest"]["rewards"] == ["Book of Specialisation , 2 Passive Skill Points"]


@pytest.mark.parametrize("name", ["Interlude 2", "插曲 1", "interludes"])
def test_a_numbered_interlude_is_the_interlude_stage(campaign, name):
    assert campaign.find_stage(name)["id"] == "interlude"


def test_an_area_name_inside_a_longer_word_is_not_a_mention(campaign):
    # "Camp" is named in "Find the Camp past Riverside." and "Return to the Camp.", not in "Campsite"
    assert [q["slug"] for q in campaign.get_area("Camp")["quests"]] == ["Reach_Camp", "Secrets"]


def test_a_collector_that_breaks_on_a_changed_page_writes_nothing(tmp_path, monkeypatch):
    from src.scrapers import collect_campaign
    base = build_full_environment(tmp_path, fixture_spec())
    tool = mnt.DataMaintenance(base, update_spec(), base / GRAPH_REL)

    def broken(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'select'")
    monkeypatch.setattr(collect_campaign, "collect", broken)
    with pytest.raises(ServiceUnavailable, match="changed shape.*Nothing was written"):
        tool.update("campaign", fetch=CampaignSite())
    assert not (base / "data" / "campaign").exists()


def test_the_real_budget_runs_through_the_stage_cuts(tools):
    res = tools.path_to("Witch", ["Heart of Ice", "Chaos Inoculation"], by_stage=True)
    assert res["stages"][0]["passive"]["limit"] == 13 and res["stages"][0]["passive"]["used"] == 7
    assert res["stages"][0]["targets_reached"] == ["Heart of Ice", "Chaos Inoculation"]
