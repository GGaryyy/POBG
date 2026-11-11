import json

import pytest

from src.catalog.spec import load_spec
from src.scrapers.common import read_jsonl
from src.tools import lookup as lk
from src.tools.lookup import BadArgument, LookupFailed, LookupService, NotFound, ServiceUnavailable
from tests.kg_support import FETCHED, GRAPH_REL, build_full_environment
from tests.support import html

pytestmark = pytest.mark.integration

POB2_URL = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json"


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture(scope="module")
def env(tmp_path_factory, spec):
    return build_full_environment(tmp_path_factory.mktemp("lookup_env"), spec)


@pytest.fixture(scope="module")
def svc(env, spec):
    return LookupService(base_dir=env, spec=spec, graph_path=env / GRAPH_REL)


@pytest.fixture
def fresh_env(tmp_path, spec):
    """A private copy for tests that mutate files."""
    return build_full_environment(tmp_path, spec)


def slugs(items):
    return [i["slug"] for i in items]


# -- construction ---------------------------------------------------------------------------

def test_error_hierarchy():
    assert issubclass(NotFound, LookupFailed) and issubclass(BadArgument, LookupFailed)
    assert issubclass(ServiceUnavailable, LookupFailed)


def test_loads_graph_gems_and_index(svc):
    assert svc.graph is not None and svc.graph.number_of_nodes() == 42
    assert set(svc.gems) == {"skill_gem", "spirit_gem", "support_gem"}
    assert sorted(svc.gems["skill_gem"]) == ["Contagion", "Leap_Slam", "Unearth"]
    assert svc.keywords["Stun"]["name_zh_tw"] == "暈眩"


def test_missing_graph_file_is_rebuilt_in_memory(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / "nope" / "g.json")
    assert svc.graph is not None
    assert svc.get_gem("Leap_Slam")["supported_by"]["total"] == 2


def test_corrupt_graph_file_is_rebuilt_with_warning(fresh_env, spec, capsys):
    (fresh_env / GRAPH_REL).write_text("{not json", encoding="utf-8")
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    assert svc.graph is not None and "unreadable" in capsys.readouterr().err


def test_default_graph_path_is_under_base_dir(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec)
    assert svc.graph.number_of_nodes() == 42


def test_no_graph_and_no_inputs_gives_none_graph(fresh_env, spec):
    (fresh_env / GRAPH_REL).unlink()
    (fresh_env / "data" / "kg" / "keywords.jsonl").unlink()
    svc = LookupService(base_dir=fresh_env, spec=spec)
    assert svc.graph is None
    assert svc.get_gem("Leap_Slam")["supported_by"] == {"total": 0, "examples": []}
    with pytest.raises(ServiceUnavailable, match="knowledge graph"):
        svc.gems_by(class_name="Witch")


def test_missing_glossary_and_stats_raise_service_unavailable(fresh_env, spec):
    (fresh_env / "data" / "kg" / "keywords.jsonl").unlink()
    (fresh_env / "data" / "kg" / "passive_stats.jsonl").unlink()
    svc = LookupService(base_dir=fresh_env, spec=spec)
    with pytest.raises(ServiceUnavailable, match="glossary"):
        svc.explain_keyword("Stun")
    with pytest.raises(ServiceUnavailable, match="stat index"):
        svc.passives_with_stat("damage")
    assert svc.get_gem("Leap_Slam")["gem"]["name"] == "Leap Slam"  # unrelated tools keep working


# -- lookup_entity ----------------------------------------------------------------------------

def test_lookup_entity_exact_en_and_zh(svc):
    en = svc.lookup_entity("leap slam")
    assert en["query"] == "leap slam" and len(en["hits"]) == 1
    hit = en["hits"][0]
    assert hit == {"slug": "Leap_Slam", "kind": "skill_gem", "name_en": "Leap Slam", "name_zh_tw": "躍擊",
                   "url_en": "https://poe2db.tw/us/Leap_Slam", "url_zh_tw": "https://poe2db.tw/tw/Leap_Slam",
                   "tier": 7, "match_type": "exact"}
    assert svc.lookup_entity("躍擊")["hits"][0]["slug"] == "Leap_Slam"


def test_lookup_entity_prefix_substring_kind_and_limit(svc):
    res = svc.lookup_entity("heart", kind="passive_notable")
    assert [(h["slug"], h["match_type"]) for h in res["hits"]] == [("Heart_of_Ice", "prefix")]
    assert [h["match_type"] for h in svc.lookup_entity("slam")["hits"]] == ["substring"]
    assert svc.lookup_entity("a", limit=2)["hits"].__len__() == 2
    assert svc.lookup_entity("stun", kind="keyword")["hits"][0]["kind"] == "keyword"


def test_lookup_entity_unknown_gives_no_hits(svc):
    assert svc.lookup_entity("zzzzzz")["hits"] == []


@pytest.mark.parametrize("kwargs", [{"query": ""}, {"query": "   "}, {"query": "x", "limit": 0},
                                    {"query": "x", "kind": "bogus_kind"}])
def test_lookup_entity_bad_arguments(svc, kwargs):
    with pytest.raises(BadArgument):
        svc.lookup_entity(**kwargs)


def test_lookup_entity_limit_is_capped(svc):
    assert len(svc.lookup_entity("a", limit=10_000)["hits"]) <= lk.MAX_LIMIT


# -- get_gem -------------------------------------------------------------------------------------

def test_get_gem_skill(svc):
    res = svc.get_gem("Leap_Slam")
    assert res["gem"]["name"] == "Leap Slam" and res["gem"]["tier"] == 7
    assert [k["slug"] for k in res["keywords"]] == ["Stun", "Critical_Hits", "Armour"]
    assert res["keywords"][1]["name_en"] == "Critical Hit" and res["keywords"][1]["name_zh_tw"] == "暴擊"
    assert res["sources"] == [
        {"label": "poe2db (en)", "url": "https://poe2db.tw/us/Leap_Slam", "fetched_at": FETCHED},
        {"label": "poe2db (zh-TW)", "url": "https://poe2db.tw/tw/Leap_Slam", "fetched_at": FETCHED}]
    assert res["supported_by"]["total"] == 2
    assert {e["slug"] for e in res["supported_by"]["examples"]} == {"Added_Fire_Damage", "Faster_Attacks"}
    assert "supports_skills" not in res


@pytest.mark.parametrize("query", ["Leap Slam", "leap_slam", "躍擊", "Leap_Slam"])
def test_get_gem_by_name_slug_or_zh(svc, query):
    assert svc.get_gem(query)["gem"]["slug"] == "Leap_Slam"


def test_get_gem_support_shows_supported_skills(svc):
    res = svc.get_gem("Added Fire Damage")
    assert res["supports_skills"]["total"] == 2
    assert {e["slug"] for e in res["supports_skills"]["examples"]} == {"Leap_Slam", "Unearth"}
    assert "supported_by" not in res


def test_get_gem_spirit(svc):
    res = svc.get_gem("灰燼信使")
    assert res["gem"]["tier"] == 4 and res["supported_by"] == {"total": 0, "examples": []}


@pytest.mark.parametrize("query", ["Chaos Inoculation", "zzz", "Stun"])
def test_get_gem_not_a_gem_is_not_found(svc, query):
    with pytest.raises(NotFound):
        svc.get_gem(query)


def test_get_gem_empty_is_bad_argument(svc):
    with pytest.raises(BadArgument):
        svc.get_gem("  ")


# -- get_passive ---------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["3", "Heart_of_Ice", "Heart of Ice", "冰之心"])
def test_get_passive_by_id_slug_or_name(svc, query):
    res = svc.get_passive(query)
    assert res["passive"]["id"] == "3" and res["passive"]["name"] == "Heart of Ice"


def test_get_passive_page_node_details(svc):
    res = svc.get_passive("3")
    assert [n["id"] for n in res["neighbors"]] == ["2", "4"]
    assert res["neighbors"][0]["name"] == "Chaos Inoculation" and res["neighbors"][0]["type"] == "Keystone"
    assert res["keywords"] == [{"slug": "Cold_Damage", "name_en": "Cold Damage", "name_zh_tw": "冰冷傷害",
                                "url_en": "https://poe2db.tw/us/Cold_Damage"}]
    assert res["sources"] == [
        {"label": "poe2db (en)", "url": "https://poe2db.tw/us/Heart_of_Ice", "fetched_at": None},
        {"label": "poe2db (zh-TW)", "url": "https://poe2db.tw/tw/Heart_of_Ice", "fetched_at": None}]


def test_get_passive_without_page_cites_pob2(svc):
    res = svc.get_passive("4")
    assert res["passive"]["slug"] is None and res["passive"]["stats"] == ["8% increased Cold Damage"]
    assert res["sources"] == [{"label": "PathOfBuilding-PoE2 tree 0_5", "url": POB2_URL}]


def test_get_passive_without_page_with_tree_data_text_cites_both(svc):
    res = svc.get_passive("5")
    assert res["passive"]["name_zh_tw"] == "攻擊速度" and res["passive"]["stats_zh_tw"] == ["增加 12% 攻擊速度"]
    assert res["sources"] == [
        {"label": "PathOfBuilding-PoE2 tree 0_5", "url": POB2_URL},
        {"label": lk.TREE_DATA_LABEL, "url": "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json"}]


@pytest.mark.parametrize("name, expected", [
    ("泰坦", "Titan"), ("女巫", "Witch"), ("titan", "Titan"), (" Stormweaver ", "Stormweaver"),
    ("風暴編織者", "Stormweaver"), ("不存在的職業", "不存在的職業"), ("Nobody", "Nobody"),
])
def test_canonical_class(svc, name, expected):
    assert svc.canonical_class(name) == expected


def test_missing_classes_file_warns_and_keeps_english_only(fresh_env, spec, capsys):
    (fresh_env / "data" / "passive_tree" / "classes.json").unlink()
    service = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    assert "classes.json missing" in capsys.readouterr().err
    assert service.canonical_class("泰坦") == "泰坦" and service.canonical_class("Titan") == "Titan"


def test_unreadable_classes_file_warns_without_the_path(fresh_env, spec, capsys):
    (fresh_env / "data" / "passive_tree" / "classes.json").write_text("{broken", encoding="utf-8")
    service = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    err = capsys.readouterr().err
    assert "classes.json unreadable" in err and str(fresh_env) not in err
    assert service.canonical_class("泰坦") == "泰坦"


def test_get_passive_timeless_and_ascendancy(svc):
    assert svc.get_passive("Black_Scythe_Training")["passive"]["timeless"] is True
    asc = svc.get_passive("Beidat's Will")
    assert asc["passive"]["id"] == "11" and asc["passive"]["ascendancy"] == "Infernalist"
    assert svc.get_passive("Infernalist")["passive"]["id"] == "10"      # ascendancy start, found by name


def test_get_passive_unknown_and_empty(svc):
    with pytest.raises(NotFound):
        svc.get_passive("999999")
    with pytest.raises(NotFound):
        svc.get_passive("Leap Slam")  # a gem, not a passive
    with pytest.raises(BadArgument):
        svc.get_passive("")


# -- passives_with_stat ---------------------------------------------------------------------------------

def test_passives_with_stat_en_groups_by_page(svc):
    res = svc.passives_with_stat("cold damage")
    assert res["lang"] == "en" and res["families"] == {"cold damage": 2}
    assert [p["id"] for p in res["with_page"]] == ["3"] and res["with_page_total"] == 1
    entry = res["with_page"][0]
    assert (entry["line"], entry["value"], entry["kind"], entry["family"]) == (
        "20% increased Cold Damage", 20.0, "increased", "cold damage")
    assert entry["line_zh_tw"] == "冰冷傷害增加 20%" and entry["url_en"] == "https://poe2db.tw/us/Heart_of_Ice"
    wo = res["without_page"]
    assert wo["total"] == 1 and wo["by_type"] == {"Small": 1} and wo["by_family"] == {"cold damage": 1}
    assert wo["source"] == POB2_URL and "nodes" not in wo


def test_passives_with_stat_include_without_page(svc):
    res = svc.passives_with_stat("cold damage", include_without_page=True)
    [node] = res["without_page"]["nodes"]
    assert node["id"] == "4" and node["value"] == 8.0 and node["line_zh_tw"] is None and node["url_en"] is None


def test_passives_with_stat_exact_family_ranks_before_larger_value(svc):
    res = svc.passives_with_stat("spell damage")
    # node 11's family ("spell damage with staves", parent "spell damage") has the larger value (15 > 10)
    assert [p["id"] for p in res["with_page"]] == ["3", "11"]
    assert [p["value"] for p in res["with_page"]] == [10.0, 15.0]


def test_passives_with_stat_substring_orders_by_value(svc):
    res = svc.passives_with_stat("damage")
    assert [p["id"] for p in res["with_page"]] == ["3", "11", "2"]
    assert res["with_page_total"] == 3 and res["without_page"]["total"] == 1
    assert res["families"]["cold damage"] == 2 and res["families"]["immune to chaos damage"] == 1


def test_passives_with_stat_limit(svc):
    res = svc.passives_with_stat("damage", limit=1)
    assert len(res["with_page"]) == 1 and res["with_page_total"] == 3


def test_passives_with_stat_kind_filter(svc):
    res = svc.passives_with_stat("damage", kind="increased")
    assert [p["id"] for p in res["with_page"]] == ["3", "11"]  # node 2's text line is excluded
    flat = svc.passives_with_stat("spirit", kind="flat")
    assert [p["id"] for p in flat["with_page"]] == ["11"] and flat["with_page"][0]["value"] == 10.0
    assert svc.passives_with_stat("spirit", kind="more")["with_page"] == []


def test_passives_with_stat_zh_query(svc):
    res = svc.passives_with_stat("冰冷傷害")
    assert res["lang"] == "zh-tw"
    assert [p["id"] for p in res["with_page"]] == ["3"]
    assert res["without_page"]["total"] == 1                 # node 4 matched via the inherited zh template
    assert res["with_page"][0]["line_zh_tw"] == "冰冷傷害增加 20%"


def test_passives_with_stat_zh_orders_by_english_rank(svc):
    res = svc.passives_with_stat("法術傷害")
    assert [p["id"] for p in res["with_page"]] == ["3", "11"]   # family==parent (rank 1) before qualified family


def test_passives_with_stat_lang_override_and_validation(svc):
    assert svc.passives_with_stat("cold damage", lang="EN")["lang"] == "en"
    assert svc.passives_with_stat("冰冷傷害", lang="en")["with_page"] == []   # Chinese text vs English ranks
    with pytest.raises(BadArgument, match="lang"):
        svc.passives_with_stat("cold damage", lang="fr")


def test_passives_with_stat_bad_arguments(svc):
    with pytest.raises(BadArgument):
        svc.passives_with_stat("")
    with pytest.raises(BadArgument):
        svc.passives_with_stat("damage", limit=0)


def test_passives_with_stat_no_match(svc):
    res = svc.passives_with_stat("nonexistent stat")
    assert res["with_page"] == [] and res["families"] == {} and res["without_page"]["total"] == 0


def test_signed_value_for_negative_kinds():
    assert lk._signed({"kind": "reduced", "value": 5}) == -5
    assert lk._signed({"kind": "less", "value": 5}) == -5
    assert lk._signed({"kind": "increased", "value": 5}) == 5
    assert lk._signed({"kind": "text", "value": None}) == 0


# -- explain_keyword --------------------------------------------------------------------------------------

def test_explain_keyword_by_slug(svc):
    res = svc.explain_keyword("Stun")
    assert res["keyword"]["slug"] == "Stun" and res["answer_text"] == "Stunned enemies cannot act."
    assert [k["slug"] for k in res["see_also"]] == ["Freeze", "Critical_Hits"]
    assert res["see_also"][1]["name_zh_tw"] == "暴擊"
    assert res["sources"] == [
        {"label": "poe2db (en)", "url": "https://poe2db.tw/us/Stun", "fetched_at": FETCHED},
        {"label": "poe2db (zh-TW)", "url": "https://poe2db.tw/tw/Stun", "fetched_at": FETCHED}]
    mentioned = res["mentioned_by"]
    assert mentioned["gem"]["total"] == 1 and mentioned["gem"]["examples"][0]["slug"] == "Leap_Slam"
    assert mentioned["passive"]["total"] == 0 and mentioned["keyword"]["total"] == 1


def test_explain_keyword_mentioned_by_passive(svc):
    mentioned = svc.explain_keyword("Armour")["mentioned_by"]
    assert mentioned["passive"]["examples"][0]["name"] == "Black Scythe Training"
    assert mentioned["gem"]["total"] == 1


def test_explain_keyword_by_en_name_case_insensitive_and_substring(svc):
    assert svc.explain_keyword("critical hit")["keyword"]["slug"] == "Critical_Hits"
    assert svc.explain_keyword("STUN")["keyword"]["slug"] == "Stun"
    assert svc.explain_keyword("crit")["keyword"]["slug"] == "Critical_Hits"


def test_explain_keyword_zh_name_answers_in_chinese(svc):
    res = svc.explain_keyword("暴擊")
    assert res["keyword"]["slug"] == "Critical_Hits" and res["answer_text"] == "暴擊造成額外傷害。"
    assert svc.explain_keyword("暴擊", lang="en")["answer_text"] == "A Critical Hit deals extra damage."
    assert svc.explain_keyword("Stun", lang="zh-TW")["answer_text"] == "被暈眩的敵人無法行動。"


def test_explain_keyword_falls_back_to_english_text(svc):
    assert svc.explain_keyword("Freeze", lang="zh-tw")["answer_text"] == "Frozen enemies cannot act."


def test_explain_keyword_errors(svc):
    with pytest.raises(NotFound):
        svc.explain_keyword("Not A Keyword")
    with pytest.raises(BadArgument):
        svc.explain_keyword(" ")
    with pytest.raises(BadArgument, match="lang"):
        svc.explain_keyword("Stun", lang="de")


# -- gems_by --------------------------------------------------------------------------------------------------

def gem_slugs(res):
    return [g["slug"] for g in res["gems"]]


def test_gems_by_tag_matches_tags_and_tag_slugs(svc):
    assert gem_slugs(svc.gems_by(tag="Fire")) == ["Herald_of_Ash", "Added_Fire_Damage"]
    assert gem_slugs(svc.gems_by(tag="spells")) == ["Unearth", "Contagion"]       # tag slug, case-insensitive
    assert gem_slugs(svc.gems_by(tag="Attack")) == ["Leap_Slam", "Faster_Attacks"]


def test_gems_by_tier_including_zero(svc):
    assert gem_slugs(svc.gems_by(tier=1)) == ["Unearth", "Contagion", "Added_Fire_Damage"]
    assert gem_slugs(svc.gems_by(tier=7)) == ["Leap_Slam"]
    assert svc.gems_by(tier=0) == {"filters": {"tag": None, "tier": 0, "class_name": None, "weapon": None, "kind": None,
                                               "text": None},
                                   "total": 0, "gems": []}


def test_gems_by_weapon_and_kind(svc):
    assert gem_slugs(svc.gems_by(weapon="mace")) == ["Leap_Slam"]
    assert gem_slugs(svc.gems_by(weapon="Martial")) == ["Herald_of_Ash"]
    assert gem_slugs(svc.gems_by(kind="support_gem")) == ["Added_Fire_Damage", "Faster_Attacks"]
    assert gem_slugs(svc.gems_by(tag="Fire", kind="spirit_gem")) == ["Herald_of_Ash"]


def test_gems_by_class_via_gemcutting(svc):
    res = svc.gems_by(class_name="Witch")
    assert gem_slugs(res) == ["Unearth", "Contagion", "Herald_of_Ash"]
    assert res["gems"][0]["gemcutting"] == {"class": "Witch", "group": "Occult", "tier": 1}
    assert res["gems"][2]["gemcutting"]["tier"] == 4
    assert gem_slugs(svc.gems_by(class_name="occult")) == ["Unearth", "Contagion", "Herald_of_Ash"]   # group label
    assert gem_slugs(svc.gems_by(class_name="Warrior")) == ["Leap_Slam"]
    assert svc.gems_by(class_name="Nobody")["total"] == 0
    assert gem_slugs(svc.gems_by(class_name="Witch", kind="spirit_gem")) == ["Herald_of_Ash"]


def test_gems_by_hit_fields_and_limit(svc):
    res = svc.gems_by(kind="skill_gem", limit=1)
    assert res["total"] == 3 and len(res["gems"]) == 1
    assert res["gems"][0] == {"slug": "Leap_Slam", "kind": "skill_gem", "name": "Leap Slam", "tier": 7,
                              "tags": ["Attack", "AoE"], "url_en": "https://poe2db.tw/us/Leap_Slam",
                              "url_zh_tw": "https://poe2db.tw/tw/Leap_Slam"}
    assert res["filters"]["kind"] == "skill_gem"


def test_gems_by_bad_arguments(svc):
    for kwargs in ({}, {"tag": ""}, {"kind": "wand_gem"}, {"tag": "Fire", "limit": 0}):
        with pytest.raises(BadArgument):
            svc.gems_by(**kwargs)


# -- refresh_gem -----------------------------------------------------------------------------------------------

def changed_page():
    page = html("detail_skill_keywords.html").replace("Tier: <span>7</span>", "Tier: <span>9</span>")
    start = page.index('<li><a class="gem_blue"')
    return page[:start] + page[page.index("</li>", start) + 5:]          # drops the Faster_Attacks entry


def test_refresh_gem_updates_record_and_reports_changes(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    urls = []

    def fetcher(url):
        urls.append(url)
        return changed_page()

    res = svc.refresh_gem("Leap Slam", fetcher=fetcher)
    assert urls == ["https://poe2db.tw/us/Leap_Slam"]
    assert res["slug"] == "Leap_Slam" and res["changed_fields"] == ["supported_by", "tier"]
    assert res["gem"]["tier"] == 9 and res["gem"]["supported_by"] == ["Added_Fire_Damage"]
    assert res["graph_stale"] is True
    assert res["gem"]["fetched_at"] != FETCHED
    assert [s["url"] for s in res["sources"]] == ["https://poe2db.tw/us/Leap_Slam", "https://poe2db.tw/tw/Leap_Slam"]

    stored = {r["slug"]: r for r in read_jsonl(fresh_env / "data" / "skill_gems" / "Skill_Gems_Detail.jsonl")}
    assert set(stored) == {"Leap_Slam", "Unearth", "Contagion"}                  # other records preserved
    leap = stored["Leap_Slam"]
    assert leap["tier"] == 9 and leap["supported_by"] == ["Added_Fire_Damage"]
    assert leap["tag_slugs"] == ["Attacks", "Area_of_Effect_Skills"]            # listing fields preserved
    assert leap["attribute_colour"] == "str" and leap["summary"] == "Jump and slam"
    assert stored["Unearth"]["tier"] == 1

    assert svc.get_gem("Leap_Slam")["gem"]["tier"] == 9                        # in-memory cache refreshed
    cached = fresh_env / "output" / "cache" / "detail" / "en" / "Leap_Slam.html"
    assert cached.read_text(encoding="utf-8") == changed_page()


def test_refresh_gem_unchanged_page_reports_nothing(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    res = svc.refresh_gem("Leap_Slam", fetcher=lambda url: html("detail_skill_keywords.html"))
    assert res["changed_fields"] == []


def test_refresh_gem_keeps_old_tier_when_page_has_none(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    page = html("detail_skill_keywords.html").replace('<div class="property">Tier: <span>7</span></div>', "")
    res = svc.refresh_gem("Leap_Slam", fetcher=lambda url: page)
    assert res["gem"]["tier"] == 7 and "tier" not in res["changed_fields"]


def test_refresh_gem_refuses_broken_page_and_keeps_record(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    path = fresh_env / "data" / "skill_gems" / "Skill_Gems_Detail.jsonl"
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ServiceUnavailable, match="did not parse"):
        svc.refresh_gem("Leap_Slam", fetcher=lambda url: html("detail_nopopup.html"))
    assert path.read_text(encoding="utf-8") == before
    assert svc.get_gem("Leap_Slam")["gem"]["tier"] == 7


def test_refresh_gem_unknown_and_missing_record(fresh_env, spec):
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    with pytest.raises(NotFound):
        svc.refresh_gem("Chaos Inoculation", fetcher=lambda url: "")
    path = fresh_env / "data" / "skill_gems" / "Skill_Gems_Detail.jsonl"
    rows = [r for r in read_jsonl(path) if r["slug"] != "Leap_Slam"]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(NotFound, match="is not in"):
        svc.refresh_gem("Leap_Slam", fetcher=lambda url: html("detail_skill_keywords.html"))


def test_refresh_gem_fetch_error_propagates_and_leaves_file(fresh_env, spec):
    import requests
    svc = LookupService(base_dir=fresh_env, spec=spec, graph_path=fresh_env / GRAPH_REL)
    path = fresh_env / "data" / "skill_gems" / "Skill_Gems_Detail.jsonl"
    before = path.read_bytes()

    def boom(url):
        raise requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        svc.refresh_gem("Leap_Slam", fetcher=boom)
    assert path.read_bytes() == before


def test_passives_with_stat_caps_the_limit_below_the_general_maximum(svc, monkeypatch):
    assert lk.MAX_STAT_LIMIT < lk.MAX_LIMIT
    full = svc.passives_with_stat("damage", include_without_page=True, limit=lk.MAX_LIMIT)
    assert len(full["with_page"]) > 1
    monkeypatch.setattr(lk, "MAX_STAT_LIMIT", 1)
    capped = svc.passives_with_stat("damage", include_without_page=True, limit=lk.MAX_LIMIT)
    assert len(capped["with_page"]) == 1 and capped["with_page_total"] == full["with_page_total"]
    assert capped["with_page"] == full["with_page"][:1]
    assert len(full["without_page"]["nodes"]) >= 1
    assert capped["without_page"]["nodes"] == full["without_page"]["nodes"][:1]
    assert capped["without_page"]["total"] == full["without_page"]["total"]


def test_real_stat_limit_is_one_hundred():
    assert lk.MAX_STAT_LIMIT == 100


def test_passives_with_stat_unknown_kind_lists_the_kinds_in_the_data(svc):
    typo = svc.passives_with_stat("damage", kind="increase")
    assert typo["with_page"] == [] and "increased" in typo["available_kinds"]
    assert typo["available_kinds"] == sorted(typo["available_kinds"])
    assert "available_kinds" not in svc.passives_with_stat("damage", kind="increased")
    assert "available_kinds" not in svc.passives_with_stat("damage")


def test_refresh_caches_the_page_before_it_replaces_the_record(svc, monkeypatch):
    before = svc.get_gem("Leap_Slam")["gem"]["fetched_at"]
    monkeypatch.setattr(svc, "_cache_detail_page", lambda slug, page: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        svc.refresh_gem("Leap_Slam", fetcher=lambda url: html("detail_skill_keywords.html"))
    stored = [r for r in read_jsonl(svc.base_dir / svc.spec.source_for_kind("skill_gem")[1]["detail_file"])
              if r["slug"] == "Leap_Slam"]
    assert stored[0]["fetched_at"] == before == svc.get_gem("Leap_Slam")["gem"]["fetched_at"]


def test_default_refresh_fetch_waits_the_catalog_delay(svc, monkeypatch):
    calls = []
    monkeypatch.setattr(lk, "fetch_html", lambda url, delay=0.0: calls.append((url, delay)) or "<html></html>")
    assert svc._polite_fetch("https://poe2db.tw/us/X") == "<html></html>"
    assert calls == [("https://poe2db.tw/us/X", svc.spec.raw["robots"]["polite_delay_seconds"])]


def test_gem_stored_under_two_kinds_is_answered_from_the_newer_copy(svc):
    spirit = svc.gems["spirit_gem"]["Herald_of_Ash"]
    older = {**spirit, "kind": "skill_gem", "fetched_at": "2025-01-01T00:00:00+00:00", "cost": "old copy"}
    svc.gems["skill_gem"]["Herald_of_Ash"] = older
    try:
        assert svc.get_gem("Herald_of_Ash")["gem"] is spirit                 # the spirit copy is newer
        older["fetched_at"] = "2099-01-01T00:00:00+00:00"
        assert svc.get_gem("Herald_of_Ash")["gem"]["cost"] == "old copy"     # now the skill copy is newer
        older["fetched_at"] = spirit["fetched_at"]
        assert svc.get_gem("Herald_of_Ash")["gem"]["kind"] in ("skill_gem", "spirit_gem")
    finally:
        del svc.gems["skill_gem"]["Herald_of_Ash"]


def test_gem_stored_once_is_unaffected_by_the_newest_copy_rule(svc):
    assert svc.get_gem("Leap_Slam")["gem"] is svc.gems["skill_gem"]["Leap_Slam"]
