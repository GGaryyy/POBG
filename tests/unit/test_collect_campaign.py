import copy
import json

import pytest
import requests

from src.scrapers import collect_campaign as cc
from src.scrapers.common import make_soup
from tests.campaign_support import (
    ACT1_ROWS,
    QUEST_REWARDS,
    CampaignSite,
    act_map,
    act_page,
    area_row,
    campaign_spec,
    quest_entry,
    site_pages,
)


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    return cc.collect(campaign_spec(), fetch=CampaignSite(), cache_dir=tmp_path_factory.mktemp("campaign_cache"))


def by_slug(rows):
    return {r["slug"]: r for r in rows}


# -- pages ------------------------------------------------------------------------------------------------

def test_act_index_lists_act_pages_in_order_without_repeats():
    assert cc.act_slugs(site_pages()["https://poe2db.tw/us/Act"], r"^Act_(\d+)$") == ["Act_1", "Act_2", "Act_5", "Act_6"]


def test_area_table_keeps_each_area_once_with_level_town_waypoint_and_bosses():
    page = cc.parse_act_page(act_page("Act 1", "Act 1 Area", "Act 1 Quest", ACT1_ROWS["en"], []))
    areas = by_slug(page["areas"])
    assert list(areas) == ["Riverside", "Camp", "Field", "Manor"]          # "Field" is listed twice
    assert (areas["Camp"]["level"], areas["Camp"]["town"], areas["Camp"]["waypoint"]) == (15, True, True)
    assert (areas["Riverside"]["town"], areas["Riverside"]["waypoint"]) == (False, False)
    assert areas["Field"]["bosses"] == [{"name": "Beira", "slug": "Beira"}]
    assert areas["Field"]["content"] == ["Beira ( +10 % to Cold Resistance )", "Mysterious Campsite"]
    assert [b["name"] for b in areas["Manor"]["bosses"]] == ["Count", "Candle"]
    assert page["title"] == "Act 1"


def test_area_level_is_the_first_number_of_its_cell():
    row = area_row("Trial", "Trial", "38<span>38</span>")
    page = cc.parse_act_page(act_page("Act 3", "Act 3 Area", "", [row], []))
    assert page["areas"][0]["level"] == 38


def test_a_boss_without_a_monster_link_has_no_slug():
    row = area_row("Trial", "Trial", "22", bosses=(("Trial of Ascendancy", None, ""),))
    assert cc.parse_act_page(act_page("A", "A Area", "", [row], []))["areas"][0]["bosses"] == [
        {"name": "Trial of Ascendancy", "slug": None}]


def test_rows_without_an_area_link_or_level_are_skipped():
    rows = ["<tr><td>no link</td><td>3</td><td></td></tr>", area_row("X", "X", "no level"), area_row("Y", "Y", "4")]
    assert [a["slug"] for a in cc.parse_act_page(act_page("A", "A Area", "", rows, []))["areas"]] == ["Y"]


def test_quests_merge_steps_of_one_quest_and_read_type_reward_objective():
    quests = [quest_entry("Q", "Quest", "Normal", "Act 1", "Gold", "Step one."),
              quest_entry("Q", "Quest", "Normal", "Act 1", None, "Step two."),
              quest_entry("Q", "Quest", "Normal", "Act 1", "Gold", "Step one."),
              quest_entry("R", "Other", "Optional", "Act 1", None, None)]
    page = cc.parse_act_page(act_page("A", "A Area", "A Quest", [], quests))
    assert page["quests"] == [
        {"slug": "Q", "name": "Quest", "type": "Normal", "rewards": ["Gold"], "objectives": ["Step one.", "Step two."]},
        {"slug": "R", "name": "Other", "type": "Optional", "rewards": [], "objectives": []}]


def test_chinese_reward_label_is_read_too():
    page = cc.parse_act_page(act_page("A", "A Area", "第 1 章 任務", [],
                                      [quest_entry("Q", "任務", "支線", "第 1 章", "專精之書", "目標。", "獎勵:")]))
    assert page["quests"][0]["rewards"] == ["專精之書"] and page["quests"][0]["type"] == "支線"


def test_act_map_joins_rows_and_columns():
    table = make_soup(act_map([["", "A|A|1"], ["", "↕"], ["", "B|B|2", "↔", "C|C|3"], ["", "", "", "↓"],
                               ["", "", "", "D|D|4"], ["E|E|5"]])).select_one("table")
    assert cc.parse_act_map(table) == [["A", "B"], ["B", "C"], ["C", "D"]]   # E has no arrow


def test_guide_is_grouped_by_area_heading_and_drops_the_town_suffix():
    mark = make_soup('<div id="markContent"><h1>Act</h1><h2>A</h2><p>One.</p><ul><li>Two.</li></ul>'
                     '<h2>Camp (Town) <img/></h2><p>Three.</p><h2>Empty</h2></div>').select_one("#markContent")
    assert cc.parse_guide(mark) == {"A": "One.\nTwo.", "Camp": "Three."}


# -- PoB quest rewards ----------------------------------------------------------------------------------------

def test_quest_rewards_read_stat_points_spirit_and_options():
    rewards = cc.quest_rewards(QUEST_REWARDS)
    assert [r["giver"] for r in rewards] == ["Beira", "Lute", "King", "The Final Letter", "Medallion", "Lythara",
                                              "Siege"]
    lute, king, medallion = rewards[1], rewards[2], rewards[4]
    assert (lute["passive_points"], lute["spirit"], lute["area_level"]) == (2, 0, 2)
    assert (king["spirit"], king["passive_points"]) == (30, 0)
    assert medallion["stat"] is None and medallion["options"] == ["30% increased Charm Charges Gained\n+1 Charm Slot",
                                                                 "30% increased Charm Effect Duration\n+1 Charm Slot"]
    assert rewards[0] == {"description": "Act 1", "act": 1, "area": "Field", "giver": "Beira",
                          "stat": "+10% to Cold Resistance", "options": [], "passive_points": 0, "spirit": 0,
                          "area_level": 2}


def test_quest_rewards_of_an_unreadable_file_are_empty():
    assert cc.quest_rewards("return {}") == [] and cc.quest_rewards("") == []


# -- stages -------------------------------------------------------------------------------------------------

def test_stages_skip_acts_without_areas_and_name_the_interlude(result):
    stages = result["stages"]
    assert [(s["id"], s["name"], s["name_zh_tw"], s["order"]) for s in stages] == [
        ("act_1", "Act 1", "第 1 章", 1), ("act_2", "Act 2", "第 2 章", 2), ("interlude", "Interludes", "間歇", 3)]
    assert stages[2]["page"] == "Interlude" and stages[2]["url_zh_tw"] == "https://poe2db.tw/tw/Interlude"


def test_stage_level_range_leaves_towns_out(result):
    levels = {s["id"]: (s["area_level_min"], s["area_level_max"]) for s in result["stages"]}
    assert levels == {"act_1": (1, 12), "act_2": (16, 28), "interlude": (40, 41)}


def test_rewards_go_to_their_stage_and_area(result):
    stages = {s["id"]: s for s in result["stages"]}
    assert [(r["giver"], r["area_slug"]) for r in stages["act_1"]["rewards"]] == [
        ("Beira", "Field"), ("Lute", "Field"), ("King", "Manor")]      # "field" and "The Manor" still match
    interlude = stages["interlude"]["rewards"]
    assert interlude[0]["area_slug"] is None                            # PoB's "Peaks" is no area name here
    assert interlude[1]["giver"] == "Siege" and "last stage" in interlude[1]["placed"]
    assert [r["giver"] for r in by_slug(result["areas"])["Field"]["rewards"]] == ["Beira", "Lute"]


def test_trials_are_marked_with_their_points(result):
    stages = {s["id"]: s for s in result["stages"]}
    assert stages["act_2"]["trials"] == [{"area": "Trial_of_the_Sekhemas", "name": "Trial of the Sekhemas",
                                          "name_zh_tw": "絲克瑪試煉", "area_level": 22, "ascendancy_points": 2}]
    assert stages["act_1"]["trials"] == []


def test_areas_merge_both_languages_connections_and_guides(result):
    areas = by_slug(result["areas"])
    field = areas["Field"]
    assert (field["name_zh_tw"], field["stage"], field["connects"]) == ("原野", "act_1", ["Camp", "Manor"])
    assert field["bosses"] == [{"name": "Beira", "slug": "Beira", "name_zh_tw": "貝伊拉"}]
    assert field["content_zh_tw"] == ["貝伊拉 ( +10 % 冰冷抗性 )"]
    assert areas["Riverside"]["guide"] == "Riverside is where the game begins.\nEquip a weapon."
    assert areas["Riverside"]["guide_zh_tw"] == "遊戲從河岸開始。"
    assert areas["Camp"]["guide"] == "The first town." and areas["Desert"]["guide"] is None
    assert areas["Wolf_Hold"]["stage"] == "interlude" and areas["Wolf_Hold"]["url_en"] == "https://poe2db.tw/us/Wolf_Hold"


def test_quests_merge_both_languages(result):
    quests = by_slug(result["quests"])
    assert list(quests) == ["Reach_Camp", "Lost_Lute", "Secrets", "Final_Letter", "Clearing_the_Way"]
    secrets = quests["Secrets"]
    assert secrets["objectives"] == ["Search the Manor.", "Return to the Camp."]
    assert secrets["objectives_zh_tw"] == ["搜索宅第。", "回到營地。"] and secrets["name_zh_tw"] == "秘密"
    assert (quests["Lost_Lute"]["type"], quests["Lost_Lute"]["type_zh_tw"]) == ("Optional", "支線")
    assert quests["Clearing_the_Way"]["stage"] == "interlude"


def test_six_acts_without_an_interlude_page_are_six_stages():
    pages = []
    for number in range(1, 7):
        rows = [area_row(f"A{number}_{i}", f"Area {number}.{i}", str(number * 10 + i)) for i in range(3)]
        en = cc.parse_act_page(act_page(f"Act {number}", f"Act {number} Area", "", rows, []))
        pages.append({"slug": f"Act_{number}", "en": en, "zh-tw": en})
    stages, areas, _ = cc.build_stages(pages, None, [], campaign_spec(), "2026-01-01")
    assert [s["id"] for s in stages] == [f"act_{n}" for n in range(1, 7)] and len(areas) == 18
    assert stages[5]["area_level_max"] == 62


# -- rules ----------------------------------------------------------------------------------------------------

def test_rules_come_from_the_gem_and_orb_pages(result):
    rules = result["rules"]
    assert rules["skill_gem_levels"][:3] == [{"level": 1, "required_level": 1}, {"level": 2, "required_level": 3},
                                             {"level": 3, "required_level": 6}]
    assert (rules["skill_gem_tiers"], rules["spirit_gem_tiers"]) == ([1, 3, 5], [4])
    assert [(s["level"], s["drop_level"]) for s in rules["support_gem_levels"]] == [(1, 1), (2, 16), (3, 33)]
    assert rules["base_support_sockets"] == 2
    assert [(o["sockets"], o["drop_level"]) for o in rules["socket_orbs"]] == [(3, 25), (4, 45), (5, 65)]
    assert rules["sources"]["quest_rewards"].endswith("QuestRewards.lua")


# -- guards -----------------------------------------------------------------------------------------------------

def test_too_few_stages_or_quests_is_refused(tmp_path):
    with pytest.raises(cc.CampaignBuildError, match="stages.*quests"):
        cc.collect(campaign_spec(stages=4, quests=40), fetch=CampaignSite(), cache_dir=tmp_path)


def test_a_missing_socket_rule_is_refused(tmp_path):
    pages = site_pages()
    for slug in ("Lesser_Jewellers_Orb", "Greater_Jewellers_Orb", "Perfect_Jewellers_Orb"):
        pages[f"https://poe2db.tw/us/{slug}"] = "<html></html>"
    with pytest.raises(cc.CampaignBuildError, match="no support socket rule"):
        cc.collect(campaign_spec(), fetch=CampaignSite(pages), cache_dir=tmp_path)


def test_offline_without_a_cache_is_refused(tmp_path):
    with pytest.raises(cc.CampaignBuildError, match="not cached"):
        cc.collect(campaign_spec(), fetch=CampaignSite(), cache_dir=tmp_path, offline=True)


def test_collect_reads_each_page_once_and_skips_chinese_pages_of_empty_acts(tmp_path):
    site = CampaignSite()
    cc.collect(campaign_spec(), fetch=site, cache_dir=tmp_path)
    assert len(site.calls) == len(set(site.calls)) == 20
    assert "https://poe2db.tw/tw/Act_5" not in site.calls


def test_write_puts_four_files_where_the_catalog_says(tmp_path, result):
    cc.write(campaign_spec(), tmp_path, copy.deepcopy(result))
    assert sorted(p.name for p in (tmp_path / "data" / "campaign").iterdir()) == [
        "areas.jsonl", "quests.jsonl", "rules.json", "stages.jsonl"]
    assert json.loads((tmp_path / "data" / "campaign" / "rules.json").read_text(encoding="utf-8"))["base_support_sockets"] == 2


# -- review follow-ups ------------------------------------------------------------------------------------------

class Gone(CampaignSite):
    """The site after 1.0: the Interlude page answers 404."""

    def __call__(self, url):
        if url.endswith("/Interlude"):
            self.calls.append(url)
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError("404", response=response)
        return super().__call__(url)


def test_a_missing_interlude_page_leaves_the_acts_as_acts(tmp_path):
    result = cc.collect(campaign_spec(), fetch=Gone(), cache_dir=tmp_path)
    assert [(s["id"], s["name"]) for s in result["stages"]] == [("act_1", "Act 1"), ("act_2", "Act 2"),
                                                               ("act_6", "Act 6")]


def test_other_errors_of_the_interlude_page_still_stop_the_update(tmp_path):
    class Broken(CampaignSite):
        def __call__(self, url):
            if url.endswith("/Interlude"):
                response = requests.Response()
                response.status_code = 500
                raise requests.HTTPError("500", response=response)
            return super().__call__(url)
    with pytest.raises(requests.HTTPError):
        cc.collect(campaign_spec(), fetch=Broken(), cache_dir=tmp_path)


def test_an_act_holding_most_of_the_interlude_areas_is_the_interlude(tmp_path):
    pages = site_pages()
    extra = area_row("Ruins", "Ruins", "42")
    for lang, path in (("us", "Act_6"), ("tw", "Act_6")):
        url = f"https://poe2db.tw/{lang}/{path}"
        pages[url] = pages[url].replace("</tbody></table></div>", extra + "</tbody></table></div>", 1)
    result = cc.collect(campaign_spec(), fetch=CampaignSite(pages), cache_dir=tmp_path)
    assert result["stages"][-1]["id"] == "interlude" and "Ruins" in result["stages"][-1]["areas"]


def test_interlude_areas_no_act_holds_are_refused(tmp_path):
    pages = site_pages()
    for lang in ("us", "tw"):
        pages[f"https://poe2db.tw/{lang}/Act_6"] = act_page("Act 6", "Act 6 Area", "", [area_row("X", "X", "50")], [])
    with pytest.raises(cc.CampaignBuildError, match="Interlude"):
        cc.collect(campaign_spec(), fetch=CampaignSite(pages), cache_dir=tmp_path)


def test_the_support_listing_follows_only_leveled_items_and_at_most_ten():
    links = "".join(f'<div class="col"><a href="Uncut_Support_Gem_%28Level_{n}%29">Uncut Support Gem (Level {n})</a></div>'
                    for n in range(1, 15))
    noise = '<div class="col"><a href="Support_Gems">Support Gems</a><a href="About">About</a></div>'
    slugs = cc.parse_listing_slugs(f"<html>{noise}{links}</html>")
    assert len(slugs) == cc.MAX_SUPPORT_PAGES and slugs[0] == "Uncut_Support_Gem_%28Level_1%29"


def test_lua_strings_comments_and_nested_options_do_not_confuse_the_parser():
    text = '''return {
\t-- a comment with { braces } and "quotes
\t{
\t\t["Description"] = "Act 1",
\t\t["Info"] = "A \\\\",
\t\t["Options"] = {
\t\t\t"one { brace",
\t\t\t{ "nested" },
\t\t\t"two",
\t\t},
\t\t["AreaLevel"] = 5,
\t},
}'''
    [reward] = cc.quest_rewards(text)
    assert reward["giver"] == "A \\\\" and reward["area_level"] == 5
    assert reward["options"] == ["one { brace", "nested", "two"]
