"""Map stages, waystone modifiers, search strings and the atlas update scope on synthetic data
(tests/atlas_support.py, tests/campaign_support.py, tests/item_support.py)."""

from __future__ import annotations

import asyncio
import json
import re
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
# The game reads a string as a regular expression, line by line, in any case: so do these tests.

def hits(regex: str, line: str) -> bool:
    return bool(re.search(regex, line, re.IGNORECASE))


def map_lines(tools, lang: str) -> dict[str, list[str]]:
    """Every shown waystone line in the data, by modifier id (both ends of each range)."""
    field_name = "lines" if lang == "en" else "lines_zh_tw"
    return {t["id"]: [form for line in t[field_name] for form in ss.shown(line)]
            for f in tools.atlas.families() for t in f["tiers"]}


def family_ids(tools, member: str) -> set[str]:
    return next({t["id"] for t in f["tiers"]} for f in tools.atlas.families() if member in {t["id"] for t in f["tiers"]})


# Lines every item or waystone shows, written here rather than taken from the module, so that a
# line the module forgets is still caught.
FIXED = {"en": ["rarity: normal", "rarity: magic", "rarity: rare", "rarity: unique", "item level: 80", "quality: +20%",
                "item rarity: +40%", "corrupted", "unidentified", "requires: level 33, 57 dex",
                "requires: level 65, 100 str", "requires: level 65, 100 int", "revives available: 3",
                "waystone drop chance: +105%", "monster effectiveness: +16%", "monster rarity: +30%",
                "monster pack size: +20%"],
         "zh-tw": ["稀有度: 魔法", "稀有度: 稀有", "稀有度: 傳奇", "物品等級: 80", "品質: +20%", "物品稀有度: +40%",
                   "需求: 等級 33, 57 敏捷", "需求: 等級 65, 100 力量", "需求: 等級 65, 100 智慧", "可用的復活: 3"]}


def assert_leaves_out(tools, res, ids: set[str]):
    """Each piece matches a line of each named modifier and no line of any other waystone modifier,
    tier name or property line."""
    labels = tools.atlas.labels()
    for lang in ("en", "zh-tw"):
        lines = map_lines(tools, lang)
        other = [line for mod_id, forms in lines.items() if mod_id not in ids for line in forms]
        other += labels[lang] + [f"{label}: 65" for label in labels[f"{lang}_properties"]] + FIXED[lang]
        pieces = [row["piece"] for row in res[lang]["pieces"]]
        assert res[lang]["strings"] == ['"!' + "|".join(pieces) + '"']
        for mod_id in ids:
            assert any(hits(p, line) for p in pieces for line in lines[mod_id]), (lang, mod_id)
        assert not any(hits(p, line) for p in pieces for line in other), lang


def test_map_string_leaves_out_the_named_modifiers_only(tools):
    res = tools.search.search_string("maps", ["less effect of Curses on Monsters",
                                              "Monsters take 22% reduced Extra Damage from Critical Hits"])
    assert_leaves_out(tools, res, {"waystone_5", "waystone_6"})
    assert [row["id"] for row in res["en"]["pieces"]] == ["waystone_6", "waystone_5"]
    assert res["en"]["pieces"][0]["matched"].startswith("(20—30)% less effect of Curses")
    assert all(row["also_matches"] == [] for lang in ("en", "zh-tw") for row in res[lang]["pieces"])
    assert res["unmatched"] == [] and res["kind"] == "maps" and "stay dark" in res["how_to_use"]


def test_every_waystone_modifier_gets_a_piece_of_its_own(tools):
    for family in tools.atlas.families():
        ids = {t["id"] for t in family["tiers"]}
        res = tools.search.search_string("maps", [family["tiers"][0]["id"]])
        assert_leaves_out(tools, res, ids)
        rows = [row for lang in ("en", "zh-tw") for row in res[lang]["pieces"]]
        assert all(len(row["piece"]) <= 40 and row["piece"].endswith("$") and not row.get("unanchored") for row in rows)


def test_map_pieces_never_match_the_tier_names_or_property_lines(tools):
    labels = tools.atlas.labels()
    assert labels["en_properties"] == ["Area Level"] and labels["zh-tw_properties"] == ["區域等級"]
    assert "Waystone (Tier 16)" in labels["en"] and "換界石（階級 16）" in labels["zh-tw"]
    res = tools.search.search_string("maps", ["Rare Monsters have additional Modifiers"])
    for lang in ("en", "zh-tw"):
        piece = res[lang]["pieces"][0]["piece"]
        assert not any(hits(piece, line) for line in labels[lang] + ["area level: 65", "區域等級: 65"])


def test_waystone_mods_text_and_id_go_straight_into_search_string(tools):
    curses = tools.atlas.waystone_mods(text="less effect of curses")["modifiers"][0]
    by_text = tools.search.search_string("maps", [curses["text"]])
    by_id = tools.search.search_string("maps", [curses["id"]])
    assert by_text["unmatched"] == [] and by_id["unmatched"] == []
    assert by_text["en"]["strings"] == by_id["en"]["strings"] and by_text["zh-tw"]["strings"] == by_id["zh-tw"]["strings"]
    assert_leaves_out(tools, by_id, {"waystone_6"})


def test_one_piece_leaves_out_both_tiers_of_a_modifier(tools):
    res = tools.search.search_string("maps", ["Extra Fire"])
    assert len(res["en"]["pieces"]) == 1
    assert_leaves_out(tools, res, family_ids(tools, "waystone_3"))


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
    full = tools.search.search_string("maps", ["less effect of Curses on Monsters", "Cursed with Enfeeble",
                                               "Extra Damage from Critical Hits"])
    pieces = [row["piece"] for row in full["en"]["pieces"]]
    limit = len('"!' + "|".join(pieces[:2]) + '"')
    raw = json.loads(json.dumps(tools.lookup.spec.raw))
    raw["sources"]["atlas"]["search"]["max_chars"] = limit
    monkeypatch.setattr(tools.search, "spec", type(tools.lookup.spec)(raw))
    res = tools.search.search_string("maps", ["less effect of Curses on Monsters", "Cursed with Enfeeble",
                                              "Extra Damage from Critical Hits"])
    assert res["en"]["strings"] == ['"!' + "|".join(pieces[:2]) + '"'] and res["en"]["left_out"] == [pieces[2]]


def bow_lines(tools, lang: str) -> dict[tuple, list[str]]:
    """Every shown line of the Bows modifier page, by modifier (every group), plus the bases' and
    uniques' text under ("item",)."""
    from src.tools.items import _families
    families = _families(tools.items.modifiers["Bows"])
    lines = {ss._key(f): [form for t in f["tiers"] for line in ss.split_lines(t[ss.text_field(lang)])
                          for form in ss.shown(line)] for f in families}
    suffix = "" if lang == "en" else "_zh_tw"
    names = [t[f"name{suffix}"] for f in families for t in f["tiers"] if t.get(f"name{suffix}")]
    bases = [b for b in tools.items.bases.values() if b.get("mod_page") == "Bows"]
    item = [line for _, line in ss.item_text(bases, list(tools.items.uniques.values()), suffix)]
    lines[("item",)] = [form for line in names + item + FIXED[lang] for form in ss.shown(line)]
    return lines


def assert_lights_up(tools, res, wanted: list[str]):
    """Each wanted modifier's lines are matched by a piece; no other line of the class is."""
    keys = {ss._key(tools.items.check_affix("Bows", text)["family"]) for text in wanted}
    for lang in ("en", "zh-tw"):
        lines = bow_lines(tools, lang)
        pieces = [row["piece"] for row in res[lang]["pieces"]]
        wanted_forms = {ss.search_form(form) for key in keys for form in lines[key]}
        for key in keys:
            assert any(hits(p, form) for p in pieces for form in lines[key]), (lang, key)
        other = [form for key, forms in lines.items() if key not in keys for form in forms
                 if ss.search_form(form) not in wanted_forms]          # the same wording in another group is the same line
        assert not any(hits(p, form) for p in pieces for form in other), lang


def test_gear_string_lights_up_the_wanted_modifiers_of_the_class(tools):
    wanted = ["Adds # to # Fire Damage", "#% increased Attack Speed"]
    res = tools.search.search_string("gear", wanted, item="Bows")
    assert res["item_class"] == "Bows" and res["unmatched"] == []
    assert_lights_up(tools, res, wanted)
    assert all(row["also_matches"] == [] for lang in ("en", "zh-tw") for row in res[lang]["pieces"])
    assert res["en"]["strings"] == ['"' + "|".join(row["piece"] for row in res["en"]["pieces"]) + '"']
    assert res["en"]["pieces"][0]["matched"] == "Adds (62—84) to (95—145) Fire Damage"
    assert res["sources"][0]["url"] == "https://poe2db.tw/us/Bows" and "light up" in res["how_to_use"]


def test_every_normal_modifier_of_the_class_gets_a_piece_of_its_own(tools):
    from src.tools.items import _families
    tools.items.resolve_page("Bows")                      # loads the item data
    for family in _families([r for r in tools.items.modifiers["Bows"] if r["group"] == "normal"]):
        text = family["tiers"][0]["text"]
        res = tools.search.search_string("gear", [text], item="Bows")
        assert res["unmatched"] == [], text
        assert_lights_up(tools, res, [text])


def test_gear_string_reports_modifiers_the_class_does_not_roll(tools):
    res = tools.search.search_string("gear", ["+# to Dexterity", "+# to maximum Mana"], item="Bows")
    assert [row["input"] for row in res["en"]["pieces"]] == ["+# to Dexterity"]
    assert res["unmatched"][0]["input"] == "+# to maximum Mana" and res["unmatched"][0]["reason"]


def test_gear_string_in_chinese_takes_chinese_input(tools):
    res = tools.search.search_string("gear", ["附加 # 至 # 火焰傷害"], item="弓")
    assert_lights_up(tools, res, ["Adds # to # Fire Damage"])
    assert "倉庫" in res["how_to_use"] and "字串必須" in res["not_checked"][1]


def test_gear_pieces_never_match_the_bases_names_or_property_lines(tools):
    res = tools.search.search_string("gear", ["+# to Dexterity"], item="Bows")
    for lang in ("en", "zh-tw"):
        piece = res[lang]["pieces"][0]["piece"]
        assert not any(hits(piece, line) for line in bow_lines(tools, lang)[("item",)]), lang
    text = ss.item_text(list(tools.items.bases.values()), [], "")
    assert ("property", "Physical Damage: 7-14") in text and ("name", "Shortbow") in text
    assert any(origin == "implicit" and "Surpassing chance" in line for origin, line in text)


def test_gear_requirement_lines_come_from_the_bases_and_every_attribute(tools):
    lines = tools.search._requirements([{"requires_level": 5, "requires": {"dex": 12}}], "zh-tw")
    assert lines == ["需求: 等級 65, 100 力量", "需求: 等級 65, 100 敏捷", "需求: 等級 65, 100 智慧", "需求: 等級 5, 12 敏捷"]
    assert tools.search._requirements([], "en")[1] == "Requires: Level 65, 100 Dex"


def test_shared_with_says_where_the_same_sentence_comes_from(tools):
    res = tools.search.search_string("gear", ["#% increased Attack Speed"], item="Bows")
    for lang in ("en", "zh-tw"):
        row = res[lang]["pieces"][0]
        assert all(entry["source"] in {"modifier", "implicit", "unique"} for entry in row.get("shared_with", []))
        assert row["piece"].endswith("$") and not row.get("unanchored")


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
    body = json.loads(found.content[0].text)
    assert body["en"]["strings"] == ['"!' + body["en"]["pieces"][0]["piece"] + '"'] and body["unmatched"] == []
    acts = asyncio.run(mcp_server.server.call_tool("campaign_stages", {"maps": False}))
    assert [s["id"] for s in json.loads(acts.content[0].text)["stages"]] == ACTS
    with pytest.raises(ToolError, match="kind must be one of"):
        asyncio.run(mcp_server.server.call_tool("search_string", {"kind": "boots", "modifiers": ["x"]}))


def test_update_prompt_has_the_atlas_steps():
    text = update_prompt_text("atlas")
    assert 'scope="atlas"' in text and "2 requests" in text and "waystone_modifiers" in text
