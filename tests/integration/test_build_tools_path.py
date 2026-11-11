import pytest

from src.catalog.spec import load_spec
from src.tools.build_tools import MAX_NAMES, START_REASON, BuildTools
from src.tools.lookup import TREE_DATA_LABEL, BadArgument, LookupService, ServiceUnavailable
from tests.kg_support import GRAPH_REL, build_full_environment, routing_classes_doc, routing_tree

pytestmark = pytest.mark.integration

POB2_LABEL = "PathOfBuilding-PoE2 tree 0_5"


def make_tools(base, **points):
    env = build_full_environment(base, load_spec(), tree=routing_tree(), classes=routing_classes_doc(**points))
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


@pytest.fixture(scope="module")
def tools(tmp_path_factory):
    return make_tools(tmp_path_factory.mktemp("routing_env"))


def ids(rows):
    return [r["id"] for r in rows]


# -- routes -----------------------------------------------------------------------------------------

def test_single_target_route_and_points(tools):
    res = tools.path_to("Witch", ["Heart of Ice"])
    assert ids(res["path"]) == ["110", "111", "112", "105"]           # the side road is one point shorter
    assert [r["order"] for r in res["path"]] == [1, 2, 3, 4]
    assert [r["target"] for r in res["path"]] == [False, False, False, True]
    assert res["points"] == {"passive": {"used": 4, "limit": 123, "over": False},
                             "ascendancy": {"used": 0, "limit": 8, "over": False}}
    assert res["class"] == "Witch" and res["ascendancy"] is None and res["ascendancy_inferred"] is False
    assert res["ascendancy_path"] == [] and res["unverified"] == [] and res["unreachable"] == []
    assert res["approximate"] is True


def test_two_targets_share_the_trunk(tools):
    res = tools.path_to("Witch", ["Heart of Ice", "Chaos Inoculation"])
    assert ids(res["path"]) == ["101", "102", "103", "104", "106", "105", "107"]
    assert res["points"]["passive"]["used"] == 7
    rows = {t["name"]: t for t in res["targets"]}
    assert (rows["Heart of Ice"]["points_alone"], rows["Heart of Ice"]["added_points"]) == (4, 2)
    assert (rows["Chaos Inoculation"]["points_alone"], rows["Chaos Inoculation"]["added_points"]) == (5, 2)
    assert rows["Heart of Ice"]["id"] == "105" and rows["Heart of Ice"]["type"] == "Notable"


@pytest.mark.parametrize("targets", [["105"], ["Heart_of_Ice"], ["冰之心"], ["heart of ice"], ["105", "Heart of Ice"]])
def test_targets_by_id_slug_or_chinese_name(tools, targets):
    res = tools.path_to("Witch", targets)
    assert ids(res["targets"]) == ["105"] and res["points"]["passive"]["used"] == 4


@pytest.mark.parametrize("name, cls, asc", [
    ("Witch", "Witch", None), ("女巫", "Witch", None), ("sorceress", "Sorceress", None),
    ("Infernalist", "Witch", "Infernalist"), ("獄火師", "Witch", "Infernalist"), ("天啟先知", "Druid", "Oracle"),
])
def test_class_or_ascendancy_name_in_either_language(tools, name, cls, asc):
    res = tools.path_to(name, ["Chaos Inoculation"])
    assert (res["class"], res["ascendancy"]) == (cls, asc)


def test_classes_sharing_a_start_get_the_same_route(tools):
    witch, sorc = tools.path_to("Witch", ["107"]), tools.path_to("Sorceress", ["107"])
    assert ids(witch["path"]) == ids(sorc["path"]) == ["101", "102", "103", "106", "107"]


# -- ascendancy-locked nodes ----------------------------------------------------------------------------

def test_oracle_only_shortcut_is_closed_to_other_druids(tools):
    res = tools.path_to("Druid", ["Chaos Inoculation"])
    assert ids(res["path"]) == ["301", "103", "106", "107"] and res["ascendancy"] is None


def test_oracle_takes_the_shortcut(tools):
    for kwargs in ({"class_name": "Oracle"}, {"class_name": "Druid", "ascendancy": "Oracle"},
                   {"class_name": "德魯伊", "ascendancy": "天啟先知"}):
        res = tools.path_to(targets=["Chaos Inoculation"], **kwargs)
        assert ids(res["path"]) == ["320", "107"] and res["ascendancy"] == "Oracle"


def test_locked_node_as_a_target_is_unreachable_with_the_reason(tools):
    res = tools.path_to("Druid", ["320", "Chaos Inoculation"])
    assert res["unreachable"] == [{"input": "320", "id": "320", "name": "Hidden Path", "name_zh_tw": None,
                                   "reason": "needs the Oracle ascendancy"}]
    assert ids(res["targets"]) == ["107"] and res["points"]["passive"]["used"] == 4


def test_isolated_node_is_unreachable(tools):
    res = tools.path_to("Witch", ["Lone Star"])
    assert res["unreachable"][0]["reason"] == "not connected to the rest of the tree in the local data"
    assert res["path"] == [] and res["targets"] == [] and res["points"]["passive"]["used"] == 0
    assert res["stat_totals"] == [] and res["sources"] == []


# -- ascendancy targets -------------------------------------------------------------------------------

def test_ascendancy_is_inferred_from_the_targets(tools):
    res = tools.path_to("Witch", ["Beidat's Will", "Heart of Ice"])
    assert res["ascendancy"] == "Infernalist" and res["ascendancy_inferred"] is True
    assert ids(res["ascendancy_path"]) == ["141", "142"] and ids(res["path"]) == ["110", "111", "112", "105"]
    assert res["points"]["ascendancy"] == {"used": 2, "limit": 8, "over": False}
    assert res["points"]["passive"]["used"] == 4
    assert all(not r["id"].startswith("14") for r in res["path"])        # the main route never enters the ascendancy


def test_whole_ascendancy_tree(tools):
    res = tools.path_to("Infernalist", ["Beidat's Will", "Altered Flesh"])
    assert ids(res["ascendancy_path"]) == ["141", "143", "142", "144"] and res["ascendancy_inferred"] is False
    assert res["path"] == [] and res["points"]["ascendancy"]["used"] == 4


def test_targets_from_two_ascendancies_need_a_choice(tools):
    res = tools.path_to("Witch", ["Beidat's Will", "Sanguimancy", "Heart of Ice"])
    assert res["ascendancy"] is None and res["ascendancy_path"] == []
    reasons = {u["input"]: u["reason"] for u in res["unverified"]}
    assert reasons == {"Beidat's Will": "Beidat's Will belongs to the Infernalist ascendancy; pass ascendancy='Infernalist'",
                       "Sanguimancy": "Sanguimancy belongs to the Blood Mage ascendancy; pass ascendancy='Blood Mage'"}
    assert ids(res["targets"]) == ["105"]


def test_target_of_another_ascendancy_is_set_aside(tools):
    res = tools.path_to("Witch", ["Beidat's Will", "Sanguimancy"], ascendancy="Blood Mage")
    assert ids(res["ascendancy_path"]) == ["151"] and res["ascendancy"] == "Blood Mage"
    assert [u["reason"] for u in res["unverified"]] == [
        "Beidat's Will belongs to the Infernalist ascendancy, not Blood Mage"]


def test_ascendancy_of_another_class_is_not_inferred(tools):
    res = tools.path_to("Druid", ["Beidat's Will"])
    assert res["ascendancy"] is None and res["ascendancy_inferred"] is False
    assert "pass ascendancy='Infernalist'" in res["unverified"][0]["reason"]


# -- names that do not verify ------------------------------------------------------------------------------

def test_unknown_and_wrong_kind_names_are_listed_not_raised(tools):
    res = tools.path_to("Witch", ["Heart of Ice", "Mega Node", "Leap Slam", "mega  node"])
    assert [u["input"] for u in res["unverified"]] == ["Mega Node", "Leap Slam"]
    assert res["unverified"][1]["reason"] == "this name is a skill_gem, not a passive"
    assert ids(res["targets"]) == ["105"]
    assert res["sources_markdown"].splitlines()[-1] == "Not found in local data (removed): `Mega Node`, `Leap Slam`"


def test_start_nodes_are_not_targets(tools):
    res = tools.path_to("Witch", ["100", "Infernalist"])
    assert [u["reason"] for u in res["unverified"]] == [START_REASON, START_REASON]
    assert res["path"] == [] and res["ascendancy"] is None


def test_every_target_unverified_gives_an_empty_route(tools):
    res = tools.path_to("Witch", ["nothing here"])
    assert res["path"] == [] and res["targets"] == [] and res["points"]["passive"] == {"used": 0, "limit": 123, "over": False}
    assert res["sources_markdown"] == "## Sources\n\nNot found in local data (removed): `nothing here`"


# -- budgets ----------------------------------------------------------------------------------------------

def test_over_budget_is_flagged_not_raised(tmp_path):
    small = make_tools(tmp_path, passive=6, ascendancy=1)
    res = small.path_to("Witch", ["Heart of Ice", "Chaos Inoculation", "Beidat's Will"])
    assert res["points"] == {"passive": {"used": 7, "limit": 6, "over": True},
                             "ascendancy": {"used": 2, "limit": 1, "over": True}}
    assert small.path_to("Witch", ["Heart of Ice"])["points"]["passive"] == {"used": 4, "limit": 6, "over": False}


def test_missing_point_limits_leave_over_unknown(tmp_path):
    doc = routing_classes_doc()
    del doc["points"]
    env = build_full_environment(tmp_path, load_spec(), tree=routing_tree(), classes=doc)
    res = BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL)).path_to("Witch", ["105"])
    assert res["points"]["passive"] == {"used": 4, "limit": None, "over": None}


# -- stat totals, language, sources -----------------------------------------------------------------------

def test_stat_totals_sum_numeric_lines_per_family(tools):
    res = tools.path_to("Witch", ["Heart of Ice", "Chaos Inoculation"])
    totals = {(t["family"], t["kind"]): (t["total"], t["lines"]) for t in res["stat_totals"]}
    assert totals[("cold damage", "increased")] == (38.0, 3)              # 10 + 8 + 20
    assert totals[("intelligence", "flat")] == (10.0, 2) and totals[("strength", "flat")] == (5.0, 1)
    assert [t["family"] for t in res["stat_totals"]][:2] == ["cold damage", "intelligence"]   # most lines first
    assert "Immune to Chaos Damage" in res["text_stats"]
    cold = next(t for t in res["stat_totals"] if t["family"] == "cold damage")
    assert cold["template"] == "#% increased Cold Damage" and cold["template_zh_tw"] == "增加 #% 冰冷傷害"


def test_side_road_totals_differ_from_the_trunk(tools):
    res = tools.path_to("Witch", ["Heart of Ice"])
    totals = {t["family"]: t["total"] for t in res["stat_totals"]}
    assert totals == {"attack speed": 9.0, "cold damage": 20.0}


def test_chinese_request_answers_in_chinese(tools):
    res = tools.path_to("女巫", ["冰之心", "混沌禁錮"])
    assert res["lang"] == "zh-tw" and res["note"].startswith("這是近似路線")
    by_id = {r["id"]: r for r in res["path"]}
    assert by_id["103"]["stats"] == ["增加 10% 冰冷傷害"] and by_id["103"]["name_zh_tw"] == "冰冷傷害"
    assert by_id["104"]["stats"] == ["8% increased Cold Damage"]         # no Chinese line: English kept
    assert "免疫混沌傷害" in res["text_stats"]
    assert res["sources_markdown"].startswith("## 資料來源")


def test_lang_can_be_forced(tools):
    res = tools.path_to("女巫", ["冰之心"], lang="en")
    assert res["lang"] == "en" and res["note"].startswith("Approximate route")
    with pytest.raises(BadArgument):
        tools.path_to("Witch", ["105"], lang="fr")


def test_sources_cite_target_pages_and_the_tree(tools):
    res = tools.path_to("Witch", ["Heart of Ice", "Chaos Inoculation"])
    assert [(s["n"], s["label"]) for s in res["sources"]] == [(1, "poe2db"), (2, "poe2db"), (3, POB2_LABEL)]
    assert {t["name"]: t["cite"] for t in res["targets"]} == {"Heart of Ice": 1, "Chaos Inoculation": 2}
    lines = res["sources_markdown"].splitlines()
    assert lines[1].startswith("1. [Heart of Ice](https://poe2db.tw/us/Heart_of_Ice)")
    assert lines[3].startswith(f"3. [{POB2_LABEL.replace('_', chr(92) + '_')}](")


def test_small_target_cites_tree_data_for_its_chinese_text(tools):
    res = tools.path_to("Witch", ["103"])
    assert [s["label"] for s in res["sources"]] == [POB2_LABEL, TREE_DATA_LABEL]


# -- bad arguments -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("class_name, targets, kwargs, message", [
    ("Witch", [], {}, "at least one target"),
    ("Witch", None, {}, "at least one target"),
    ("Witch", ["x"] * (MAX_NAMES + 1), {}, "targets has 41 names; the limit is 40"),
    ("Witch", ["x" * 121], {}, "longer than 120"),
    ("", ["105"], {}, "class_name"),
    ("W" * 121, ["105"], {}, "longer than 120"),
    ("Paladin", ["105"], {}, "unknown class 'Paladin'; classes: Druid, Sorceress, Witch"),
    ("Warrior", ["105"], {}, "unknown class 'Warrior'"),                  # in classes.json, but no start on this tree
    ("Titan", ["105"], {}, "unknown class 'Titan'"),
    ("Witch", ["105"], {"ascendancy": "Oracle"}, "'Oracle' is not an ascendancy of Witch"),
    ("Witch", ["105"], {"ascendancy": "Witch"}, "'Witch' is not an ascendancy of Witch"),
    ("Witch", ["105"], {"ascendancy": "Nobody"}, "'Nobody' is not an ascendancy of Witch"),
    ("Infernalist", ["105"], {"ascendancy": "Blood Mage"}, "class_name names Infernalist but ascendancy names Blood Mage"),
    ("Witch", ["105"], {"ascendancy": "A" * 121}, "longer than 120"),
])
def test_bad_arguments(tools, class_name, targets, kwargs, message):
    with pytest.raises(BadArgument, match=message):
        tools.path_to(class_name, targets, **kwargs)


def test_blank_ascendancy_means_none(tools):
    assert tools.path_to("Witch", ["105"], ascendancy="  ")["ascendancy"] is None


def test_missing_classes_file_is_service_unavailable(tmp_path):
    env = build_full_environment(tmp_path, load_spec(), tree=routing_tree(), classes=routing_classes_doc())
    (env / "data" / "passive_tree" / "classes.json").unlink()
    broken = BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))
    with pytest.raises(ServiceUnavailable, match="collect_passives"):
        broken.path_to("Witch", ["105"])


def test_every_route_is_allocatable_in_the_listed_order(tools):
    nodes = tools.lookup.passives
    for cls, targets in (("Witch", ["105", "107", "142", "144"]), ("Druid", ["105", "107"]), ("Oracle", ["105", "107", "341"])):
        res = tools.path_to(cls, targets)
        for rows, start in ((res["path"], tools._class_start(res["class"])),
                            (res["ascendancy_path"], tools._ascendancy_starts().get(res["ascendancy"]))):
            have = {start}
            for row in rows:
                assert any(n in have for n in nodes[row["id"]]["neighbors"]), (cls, row["id"])
                have.add(row["id"])
        assert all(not nodes[r["id"]].get("ascendancy") for r in res["path"])
