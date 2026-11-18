"""Map stages, waystone modifiers, search strings and the atlas update scope on synthetic data
(tests/atlas_support.py, tests/campaign_support.py, tests/item_support.py)."""

from __future__ import annotations

import asyncio
import json
import shutil
import xml.etree.ElementTree as ET

import pytest

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import load_spec
from src.scrapers.common import write_jsonl
from mcp.server.mcpserver.exceptions import ToolError

from src.scrapers import collect_atlas
from src.scrapers.common import read_jsonl
from src.tools import maintenance as mnt
from src.tools import mcp_server
from src.tools import search_string as ss
from src.tools.build_tools import BuildTools
from src.tools.build_workflow import update_prompt_text
from src.tools.lookup import BadArgument, LookupService, NotFound, ServiceUnavailable
from src.tools.pob_export import decode_code
from tests.atlas_support import AtlasSite, atlas_spec, site_pages, waystones_page, write_atlas_data
from tests.campaign_support import write_campaign_data
from tests.item_support import write_item_data
from tests.kg_support import GRAPH_REL, ZH_NAMES, build_full_environment, routing_classes_doc, routing_tree

pytestmark = pytest.mark.integration

ACTS = ["act_1", "act_2", "interlude"]
MAPS = ["maps_t1", "maps_t10", "maps_t16"]


def environment(base, cache, atlas: bool):
    build_full_environment(base, load_spec(), tree=routing_tree(), classes=routing_classes_doc())
    write_item_data(base)
    write_campaign_data(base, cache / "campaign")
    if atlas:
        write_atlas_data(base, cache / "atlas")
    entities = build_entity_index(load_spec(), data_dir=base / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(base / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return base


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return environment(tmp_path_factory.mktemp("atlas_env"), tmp_path_factory.mktemp("atlas_cache"), atlas=True)


@pytest.fixture(scope="module")
def bare_env(tmp_path_factory):
    return environment(tmp_path_factory.mktemp("no_atlas_env"), tmp_path_factory.mktemp("no_atlas_cache"), atlas=False)


@pytest.fixture
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


def stages(tools, **options):
    return {s["id"]: s for s in tools.campaign.campaign_stages(**options)["stages"]}


# -- map stages ----------------------------------------------------------------------------------------------

def test_map_stages_follow_the_acts_with_levels_from_the_tier_table(tools):
    rows = stages(tools)
    assert list(rows) == ACTS + MAPS
    assert [rows[i]["limits"]["level"] for i in MAPS] == [65, 74, 80]
    assert [rows[i]["area_levels"] for i in MAPS] == [[42, 65], [66, 74], [75, 80]]     # the Interlude ends at 41
    assert [rows[i]["kind"] for i in ACTS + MAPS] == ["campaign"] * 3 + ["maps"] * 3
    assert [rows[i]["tier"] for i in MAPS] == [1, 10, 16]
    assert rows["maps_t16"]["name"] == "Maps, Tier 16" and rows["maps_t16"]["name_zh_tw"] == "地圖（階級 16）"


def test_map_stages_count_points_the_same_way_and_add_the_endgame_trials(tools):
    rows = stages(tools)
    interlude, t1, t16 = rows["interlude"]["limits"], rows["maps_t1"]["limits"], rows["maps_t16"]["limits"]
    quest_points = interlude["quest_passive_points"]
    assert t1["passive_points"] == 64 + quest_points and t16["passive_points"] == 79 + quest_points
    assert t1["quest_spirit"] == interlude["quest_spirit"] and t16["quest_passive_points"] == quest_points
    assert t1["ascendancy_points"] == interlude["ascendancy_points"] + 2      # the trial at level 60
    assert t16["ascendancy_points"] == interlude["ascendancy_points"] + 4     # and the one at 80
    assert rows["maps_t10"]["trials"] == [] and rows["maps_t1"]["trials"][0]["area_level"] == 60
    assert rows["maps_t16"]["trials"][0]["name_zh_tw"].startswith("絲克瑪試煉第四層")
    assert t16["support_sockets"] >= interlude["support_sockets"] and t16["skill_gem_level"] >= interlude["skill_gem_level"]


def test_every_stage_has_the_resistance_penalty_of_its_level(tools):
    rows = stages(tools)
    # act 1 = level 12, act 2 = 28, the Interlude = 41; the table steps at 16, 33, 45 ... 65
    assert [rows[i]["limits"]["resistance_penalty"] for i in ACTS + MAPS] == [0, -10, -20, -60, -60, -60]


def test_map_stage_sources_are_the_waystones_and_ascendancy_pages(tools):
    urls = [s["url"] for s in stages(tools)["maps_t10"]["sources"]]
    assert urls == ["https://poe2db.tw/us/Waystones", "https://poe2db.tw/tw/Waystones",
                    "https://poe2db.tw/us/Ascendancy_class"]
    assert stages(tools)["maps_t10"]["bosses"] == [] and stages(tools)["maps_t10"]["rewards"] == []


def test_the_penalty_is_no_longer_listed_as_missing_and_map_limits_are(tools):
    result = tools.campaign.campaign_stages(lang="zh-tw")
    assert not any("抗性懲罰" in line for line in result["not_in_data"])
    assert any("巔峰頭目" in line for line in result["not_in_data"]) and "地圖階段" in result["how"]
    assert "maps_note" not in result


def test_maps_false_gives_the_acts_only(tools):
    result = tools.campaign.campaign_stages(maps=False)
    assert [s["id"] for s in result["stages"]] == ACTS
    assert not any("pinnacle" in line for line in result["not_in_data"]) and "Map stages" not in result["how"]
    assert result["stages"][1]["limits"]["resistance_penalty"] == -10
    with pytest.raises(BadArgument, match="maps must be true or false"):
        tools.campaign.campaign_stages(maps="no")


@pytest.mark.parametrize("words, stage_id", [("T16", "maps_t16"), ("tier 10", "maps_t10"), ("maps_t1", "maps_t1"),
                                             ("第 16 階", "maps_t16"), ("階級 10", "maps_t10"), ("Act 2", "act_2"),
                                             ("第 2 章", "act_2"), ("地圖（階級 1）", "maps_t1")])
def test_find_stage_knows_the_map_stages(tools, words, stage_id):
    assert tools.campaign.find_stage(words)["id"] == stage_id


def test_a_tier_that_is_not_a_stage_is_not_found(tools):
    with pytest.raises(NotFound, match="maps_t16"):
        tools.campaign.find_stage("T5")


def test_without_atlas_data_the_stages_are_the_acts_and_say_why(bare_env):
    tools = BuildTools(LookupService(base_dir=bare_env, graph_path=bare_env / GRAPH_REL))
    result = tools.campaign.campaign_stages()
    assert [s["id"] for s in result["stages"]] == ACTS
    assert "update_data scope atlas" in result["maps_note"]
    assert "resistance_penalty" not in result["stages"][0]["limits"]
    assert any("resistance penalty" in line for line in result["not_in_data"])
    with pytest.raises(ServiceUnavailable, match="scope atlas"):
        tools.atlas.waystone_mods()


def copied(env, tmp_path):
    target = tmp_path / "copy"
    shutil.copytree(env, target)
    return target


def tools_in(base):
    return BuildTools(LookupService(base_dir=base, graph_path=base / GRAPH_REL))


def atlas_doc(env) -> dict:
    return json.loads((env / "data" / "atlas" / "atlas.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("change", [
    lambda d: "{not json",
    lambda d: json.dumps({**d, "tiers": {"1": 65}}),
    lambda d: json.dumps({**d, "tiers": [{**d["tiers"][0], "area_level": None}, *d["tiers"][1:]]}),
    lambda d: json.dumps({k: v for k, v in d.items() if k != "url_en"}),
    lambda d: json.dumps({**d, "resistance_penalty": [{"penalty": -10}]}),
    lambda d: json.dumps([1, 2]),
])
def test_atlas_data_of_the_wrong_shape_leaves_the_acts_and_names_the_update(env, tmp_path, change):
    base = copied(env, tmp_path)
    (base / "data" / "atlas" / "atlas.json").write_text(change(atlas_doc(env)), encoding="utf-8")
    tools = tools_in(base)
    result = tools.campaign.campaign_stages()
    assert [s["id"] for s in result["stages"]] == ACTS and "unreadable" in result["maps_note"]
    assert tools.path_to("Witch", ["Heart of Ice"], by_stage=True)["stages"][-1]["stage"] == "interlude"
    with pytest.raises(ServiceUnavailable, match="scope atlas"):
        tools.atlas.waystone_mods()


def test_a_waystone_modifier_without_an_id_is_unreadable(env, tmp_path):
    base = copied(env, tmp_path)
    path = base / "data" / "atlas" / "waystone_mods.jsonl"
    rows = read_jsonl(path)
    write_jsonl(path, [{**rows[0], "id": None}, *rows[1:]])
    assert "unreadable" in tools_in(base).campaign.campaign_stages()["maps_note"]


@pytest.mark.parametrize("level, penalty", [(1, 0), (15, 0), (16, -10), (64, -50), (65, -60), (80, -60)])
def test_penalty_at_the_table_steps(tools, level, penalty):
    assert tools.atlas.penalty_at(level) == penalty


def test_penalty_with_an_empty_table_is_none(env, tmp_path):
    base = copied(env, tmp_path)
    (base / "data" / "atlas" / "atlas.json").write_text(json.dumps({**atlas_doc(env), "resistance_penalty": []}),
                                                        encoding="utf-8")
    tools = tools_in(base)
    assert tools.atlas.penalty_at(70) is None
    assert stages(tools)["maps_t1"]["limits"]["resistance_penalty"] is None


# -- builds held to a map stage --------------------------------------------------------------------------------

def test_path_to_by_stage_cuts_the_route_at_the_map_stages_too(tools):
    res = tools.path_to("Witch", ["Chaos Inoculation", "Heart of Ice"], by_stage=True)
    assert [row["stage"] for row in res["stages"]] == ACTS + MAPS
    assert res["stages"][-1]["level"] == 80


def test_export_to_tier_16_holds_one_tree_per_stage_at_level_80(tools):
    res = tools.export_pob("Witch", ["Chaos Inoculation"], ["Unearth: Added Fire Damage"], stage="T16")
    tree = ET.fromstring(decode_code(res["code"])).find("Tree")
    titles = [s.get("title") for s in tree.findall("Spec")]
    assert len(titles) == 6 and titles[-1] == "Maps, Tier 16 (level 80)" and tree.get("activeSpec") == "6"
    assert ET.fromstring(decode_code(res["code"])).find("Build").get("level") == "80"
    assert res["stage"]["id"] == "maps_t16" and res["notes"][0].startswith("Stage Maps, Tier 16: character level 80")


# -- waystone modifiers ----------------------------------------------------------------------------------------

def test_waystone_mods_groups_tiers_and_lists_both_languages(tools):
    res = tools.atlas.waystone_mods()
    assert res["total"] == 5
    fire = next(m for m in res["modifiers"] if "Extra Fire" in m["text"])
    assert fire["tiers"] == 2 and fire["ids"] == ["waystone_3", "waystone_4"] and fire["affix"] == "prefix"
    assert fire["lines"][0] == "Monsters deal (10—14)% of Damage as Extra Fire"
    assert fire["lines_zh_tw"][0] == "怪物造成等同於傷害(10—14)%的額外火焰傷害"
    assert res["sources"][0]["url"] == "https://poe2db.tw/us/Waystones" and res["not_in_data"]


def test_waystone_mods_filters_by_words_in_either_language_and_affix(tools):
    assert [m["id"] for m in tools.atlas.waystone_mods(text="curse")["modifiers"]] == ["waystone_6", "waystone_7"]
    zh = tools.atlas.waystone_mods(text="詛咒")
    assert [m["id"] for m in zh["modifiers"]] == ["waystone_6", "waystone_7"] and "怪物" in zh["not_in_data"][1]
    assert [m["id"] for m in tools.atlas.waystone_mods(affix="prefix")["modifiers"]] == ["waystone_4"]
    assert tools.atlas.waystone_mods(text="  ")["total"] == 5
    assert tools.atlas.waystone_mods(text="Monsters deal 7% of Damage as Extra Fire")["total"] == 1
    assert tools.atlas.waystone_mods(limit=2)["total"] == 5 and len(tools.atlas.waystone_mods(limit=2)["modifiers"]) == 2


def test_waystone_mods_refuses_bad_arguments(tools):
    with pytest.raises(BadArgument, match="affix"):
        tools.atlas.waystone_mods(affix="both")
    with pytest.raises(BadArgument, match="limit"):
        tools.atlas.waystone_mods(limit=0)
    with pytest.raises(BadArgument, match="longer than"):
        tools.atlas.waystone_mods(text="x" * 500)


# -- search strings --------------------------------------------------------------------------------------------

def other_map_lines(tools, lang: str, leave: set[str]) -> list[str]:
    key = "templates" if lang == "en" else "templates_zh_tw"
    return [line for f in tools.atlas.families() if not {t["id"] for t in f["tiers"]} & leave for line in f[key]]


def test_map_string_leaves_out_the_named_modifiers_only(tools):
    res = tools.search.search_string("maps", ["less effect of Curses on Monsters",
                                              "Monsters take 22% reduced Extra Damage from Critical Hits"])
    for lang in ("en", "zh-tw"):
        string = res[lang]["strings"][0]
        assert string.startswith('"!') and string.endswith('"') and len(res[lang]["strings"]) == 1
        pieces = [row["piece"] for row in res[lang]["pieces"]]
        assert string == '"!' + "|".join(pieces) + '"' and all(row["also_matches"] == [] for row in res[lang]["pieces"])
        assert not any(p in line for p in pieces for line in other_map_lines(tools, lang, {"waystone_5", "waystone_6"}))
        assert not any(ch.isdigit() for p in pieces for ch in p)
    assert res["en"]["strings"] == ['"!less effect|extra damage"'] and res["zh-tw"]["strings"] == ['"!少效果|外傷害"']
    assert [row["id"] for row in res["en"]["pieces"]] == ["waystone_6", "waystone_5"]
    assert res["en"]["pieces"][0]["matched"].startswith("(20—30)% less effect of Curses")
    assert res["unmatched"] == [] and res["kind"] == "maps" and "stay dark" in res["how_to_use"]


def test_map_string_pieces_never_match_the_tier_names_or_property_labels(tools):
    labels = tools.atlas.labels()
    assert "area level" in labels["en"] and "區域等級" in labels["zh-tw"] and "waystone (tier 16)" in labels["en"]
    for text in ("Rare Monsters have additional Modifiers", "Monsters deal of Damage as Extra Fire"):
        res = tools.search.search_string("maps", [text])
        for lang in ("en", "zh-tw"):
            piece = res[lang]["pieces"][0]["piece"]
            assert piece and not any(piece in label for label in labels[lang])


def test_waystone_mods_text_and_id_go_straight_into_search_string(tools):
    curses = tools.atlas.waystone_mods(text="less effect of curses")["modifiers"][0]
    by_text = tools.search.search_string("maps", [curses["text"]])
    by_id = tools.search.search_string("maps", [curses["id"]])
    assert by_text["unmatched"] == [] and by_id["unmatched"] == []
    assert by_text["en"]["strings"] == by_id["en"]["strings"] == ['"!less effect"']


def test_fire_names_both_tiers_of_one_modifier_with_one_piece(tools):
    res = tools.search.search_string("maps", ["Extra Fire"])
    assert len(res["en"]["pieces"]) == 1 and res["en"]["strings"] == ['"!extra fire"']
    assert all("extra fire" in line.casefold() for m in tools.atlas.waystone_mods(text="Extra Fire")["modifiers"]
               for line in m["lines"][:1])


def test_a_modifier_without_chinese_lines_is_listed_as_missing(env, tmp_path):
    base = copied(env, tmp_path)
    path = base / "data" / "atlas" / "waystone_mods.jsonl"
    write_jsonl(path, [{**row, "lines_zh_tw": []} if row["id"] == "waystone_6" else row for row in read_jsonl(path)])
    res = tools_in(base).search.search_string("maps", ["less effect of Curses on Monsters", "Cursed with Enfeeble"])
    assert res["zh-tw"]["missing"] == [{"input": "less effect of Curses on Monsters",
                                        "reason": "no zh-tw wording in the local data"}]
    assert len(res["zh-tw"]["strings"]) == 1 and "missing" not in res["en"]


def test_map_string_reports_what_it_cannot_place(tools, monkeypatch):
    res = tools.search.search_string("maps", ["Monsters are frozen solid", "less effect of Curses on Monsters", "fi"])
    assert res["unmatched"][0] == {"input": "Monsters are frozen solid", "reason": "no waystone modifier has these words"}
    assert "too short" in res["unmatched"][1]["reason"]
    monkeypatch.setattr(ss, "MAX_AVOID_MATCHES", 2)
    res = tools.search.search_string("maps", ["found in Area"])
    assert "names 5 waystone modifiers" in res["unmatched"][0]["reason"] and res["en"]["strings"] == []


def test_map_string_keeps_everything_to_leave_out_in_one_string(tools, monkeypatch):
    raw = json.loads(json.dumps(tools.lookup.spec.raw))
    raw["sources"]["atlas"]["search"]["max_chars"] = 30
    monkeypatch.setattr(tools.search, "spec", type(tools.lookup.spec)(raw))
    res = tools.search.search_string("maps", ["less effect of Curses on Monsters", "Cursed with Enfeeble",
                                              "Extra Damage from Critical Hits"])
    pieces = [row["piece"] for row in res["en"]["pieces"]]
    assert res["en"]["strings"] == ['"!less effect|extra damage"'] and res["en"]["left_out"] == [pieces[1]]
    assert sorted(res["en"]["strings"][0][2:-1].split("|") + res["en"]["left_out"]) == sorted(pieces)


def test_gear_string_lights_up_the_wanted_modifiers_of_the_class(tools):
    res = tools.search.search_string("gear", ["Adds # to # Fire Damage", "#% increased Attack Speed"], item="Bows")
    assert res["item_class"] == "Bows" and res["unmatched"] == []
    assert res["en"]["strings"] == ['"fire damage|attack speed"'] and res["zh-tw"]["strings"] == ['"火焰傷|擊速度"']
    assert all(row["also_matches"] == [] for lang in ("en", "zh-tw") for row in res[lang]["pieces"])
    assert res["en"]["pieces"][0]["matched"] == "Adds (62—84) to (95—145) Fire Damage"
    assert res["sources"][0]["url"] == "https://poe2db.tw/us/Bows" and "light up" in res["how_to_use"]


def test_gear_string_reports_modifiers_the_class_does_not_roll(tools):
    res = tools.search.search_string("gear", ["+# to Dexterity", "+# to maximum Mana"], item="Bows")
    assert [row["input"] for row in res["en"]["pieces"]] == ["+# to Dexterity"]
    assert res["unmatched"][0]["input"] == "+# to maximum Mana" and res["unmatched"][0]["reason"]


def test_gear_string_in_chinese_takes_chinese_input(tools):
    res = tools.search.search_string("gear", ["附加 # 至 # 火焰傷害"], item="弓")
    assert res["zh-tw"]["strings"] == ['"火焰傷"'] and res["en"]["strings"] == ['"fire damage"']
    assert "倉庫" in res["how_to_use"] and "字串必須" in res["not_checked"][1]


def test_gear_pieces_are_checked_against_the_bases_and_every_modifier_group(tools):
    others = {"bases": ["shortbow", "dualstring bow", "physical damage", "attacks per second"],
              "groups": ["reduced attribute requirements", "increased area of effect for attacks"]}
    res = tools.search.search_string("gear", ["+# to Dexterity"], item="Bows")
    piece = res["en"]["pieces"][0]["piece"]
    assert piece == "to dexterity" and not any(piece in text for texts in others.values() for text in texts)
    base_text = ss._base_text(list(tools.items.bases.values()), "")
    assert "physical damage" in base_text and "shortbow" in base_text
    assert any("surpassing chance" in line for line in base_text)            # implicits, numbers as #


@pytest.mark.parametrize("kind, modifiers, item, message", [
    ("gear", [1], "Bows", "each modifier must be a text"),
    ("gear", ["fire"], 5, "item must be a text"),
    ("weapons", ["x"], "Bows", "kind must be one of"),
    ("gear", [], "Bows", "non-empty list"),
    ("gear", "fire", "Bows", "non-empty list"),
    ("gear", ["x"] * 13, "Bows", "at most 12"),
    ("gear", ["fire"], None, "item must not be empty"),
    ("maps", ["  "], None, "modifier must not be empty"),
])
def test_search_string_refuses_bad_arguments(tools, kind, modifiers, item, message):
    with pytest.raises(BadArgument, match=message):
        tools.search.search_string(kind, modifiers, item=item)


# -- the update scope ------------------------------------------------------------------------------------------

@pytest.fixture
def updater(tmp_path):
    base = build_full_environment(tmp_path, load_spec())
    return mnt.DataMaintenance(base, atlas_spec(), base / GRAPH_REL)


def test_update_atlas_writes_both_files_with_two_requests(updater):
    site = AtlasSite()
    result = updater.update("atlas", fetch=site)
    assert result["requests"] == 2 and len(site.calls) == 2
    assert result["waystone_tiers"] == 16 and result["area_levels"] == [65, 80]
    assert (result["resistance_penalty_rows"], result["waystone_modifiers"]) == (7, 6)
    status = {d["name"]: d for d in updater.status()["datasets"]}["atlas"]
    assert status["records"] == 6 and status["waystone_tiers"] == 16 and status["update_scope"] == "atlas"


def test_update_atlas_writes_nothing_when_the_page_no_longer_parses(updater):
    updater.update("atlas", fetch=AtlasSite())
    path = updater.base_dir / "data" / "atlas" / "atlas.json"
    before = path.read_text(encoding="utf-8")
    pages = site_pages()
    pages["https://poe2db.tw/us/Waystones"] = waystones_page("en", tiers=range(1, 12))
    with pytest.raises(ServiceUnavailable, match="no waystone tier 16.*Nothing was written; the old data stays"):
        updater.update("atlas", fetch=AtlasSite(pages))
    assert path.read_text(encoding="utf-8") == before


def test_update_atlas_reports_a_network_error(updater):
    with pytest.raises(ServiceUnavailable, match="404"):
        updater.update("atlas", fetch=AtlasSite({}))


def test_update_atlas_takes_no_other_argument(updater):
    with pytest.raises(BadArgument, match="re-fetches the whole data set"):
        updater.update("atlas", names=["Waystones"])


def test_status_of_a_folder_without_atlas_data_is_zeros(updater):
    status = {d["name"]: d for d in updater.status()["datasets"]}["atlas"]
    assert (status["records"], status["waystone_tiers"]) == (0, 0)


def test_update_atlas_reports_a_page_of_another_shape(updater, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("area_level")
    monkeypatch.setattr(collect_atlas, "collect", broken)
    with pytest.raises(ServiceUnavailable, match="changed shape.*KeyError"):
        updater.update("atlas", fetch=AtlasSite())


def test_update_atlas_reports_a_file_that_cannot_be_written(updater, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(collect_atlas, "write", refuse)
    with pytest.raises(ServiceUnavailable, match="could not be written.*disk full"):
        updater.update("atlas", fetch=AtlasSite())


# -- through the server ----------------------------------------------------------------------------------------

def test_atlas_tools_through_the_server(env, monkeypatch):
    monkeypatch.setattr(mcp_server, "_service", LookupService(base_dir=env, graph_path=env / GRAPH_REL))
    monkeypatch.setattr(mcp_server, "_tools", None)
    mods = json.loads(asyncio.run(mcp_server.server.call_tool("waystone_mods", {"affix": "prefix"})).content[0].text)
    assert mods["total"] == 1
    found = asyncio.run(mcp_server.server.call_tool("search_string", {"kind": "maps", "modifiers": ["Extra Fire"]}))
    assert json.loads(found.content[0].text)["en"]["strings"] == ['"!extra fire"']
    acts = asyncio.run(mcp_server.server.call_tool("campaign_stages", {"maps": False}))
    assert [s["id"] for s in json.loads(acts.content[0].text)["stages"]] == ACTS
    with pytest.raises(ToolError, match="kind must be one of"):
        asyncio.run(mcp_server.server.call_tool("search_string", {"kind": "boots", "modifiers": ["x"]}))


def test_update_prompt_has_the_atlas_steps():
    text = update_prompt_text("atlas")
    assert 'scope="atlas"' in text and "2 requests" in text and "waystone_modifiers" in text
