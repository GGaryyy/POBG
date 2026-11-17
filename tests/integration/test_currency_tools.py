"""Currency lookups, the currency update scope and the MCP tools, on synthetic data (tests/currency_support.py)."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest
import requests
from mcp.server.mcpserver.exceptions import ToolError

from src.catalog.entity_index import build_entity_index
from src.catalog.spec import Spec, load_spec
from src.scrapers.common import read_jsonl, write_jsonl
from src.tools import maintenance as mnt
from src.tools import mcp_server
from src.tools.build_tools import BuildTools
from src.tools.currency import CurrencyLookup, essence_group
from src.tools.lookup import BadArgument, LookupService, NotFound, ServiceUnavailable
from tests.currency_support import CurrencySite, site_pages, write_currency_data
from tests.integration.test_maintenance import fixture_spec
from tests.kg_support import GRAPH_REL, ZH_NAMES, build_full_environment

pytestmark = pytest.mark.integration

CURRENCY_FILE = "data/currency/currency.jsonl"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = build_full_environment(tmp_path_factory.mktemp("currency_env"), load_spec())
    write_currency_data(base, tmp_path_factory.mktemp("currency_cache"))
    entities = build_entity_index(load_spec(), data_dir=base / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(base / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return base


@pytest.fixture
def lookup(env):
    return LookupService(base_dir=env, graph_path=env / GRAPH_REL)


@pytest.fixture
def currency(lookup):
    return BuildTools(lookup).currency


# -- one item -----------------------------------------------------------------------------------------------

def test_get_currency_by_english_chinese_or_slug(currency):
    for name in ("Greater Chaos Orb", "高階混沌石", "Greater_Chaos_Orb", "greater chaos orb"):
        result = currency.get_currency(name)
        assert result["currency"]["slug"] == "Greater_Chaos_Orb"
    item = currency.get_currency("Greater Chaos Orb")["currency"]
    assert (item["min_modifier_level"], item["drop_level"], item["stack_size"]) == (35, 35, 20)


def test_get_currency_cites_both_pages_with_the_date(currency):
    sources = currency.get_currency("Chaos Orb")["sources"]
    assert [s["url"] for s in sources] == ["https://poe2db.tw/us/Chaos_Orb", "https://poe2db.tw/tw/Chaos_Orb"]
    assert all(s["fetched_at"] for s in sources)


def test_related_lists_the_items_whose_effects_name_it(currency):
    related = currency.get_currency("Chaos Orb")["related"]
    assert [r["slug"] for r in related] == ["Omen_of_Whittling"]
    assert related[0]["lines"] == ["While this item is active in your inventory your next Chaos Orb will remove the "
                                   "lowest level modifier"]
    assert currency.get_currency("混沌石")["related"][0]["lines"] == [
        "此物品在你的背包裡啟動時，你的下一個混沌石會移除最低等級的詞綴"]


def test_related_does_not_take_a_longer_name_for_the_item(currency, lookup):
    assert [r["slug"] for r in currency.get_currency("Exalted Orb")["related"]] == ["Omen_of_Greater_Exaltation"]
    assert currency.get_currency("Perfect Exalted Orb")["related"] == []
    # "Greater Chaos Orb" is not named by an omen about "Chaos Orb"
    assert currency.get_currency("Greater Chaos Orb")["related"] == []


def test_related_ignores_a_name_inside_a_longer_one(lookup, env, tmp_path):
    rows = read_jsonl(env / CURRENCY_FILE)
    rows.append({**rows[0], "slug": "Omen_X", "name": "Omen X", "category": "omen",
                 "effects": ["your next Greater Chaos Orb will add", "two Chaos Orbs at once"], "effects_zh_tw": []})
    (tmp_path / "data" / "currency").mkdir(parents=True)
    write_jsonl(tmp_path / CURRENCY_FILE, rows)
    own = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    own.base_dir = tmp_path
    found = {r["slug"]: r["lines"] for r in CurrencyLookup(own).get_currency("Chaos_Orb")["related"]}
    assert found["Omen_X"] == ["two Chaos Orbs at once"]


def test_an_essence_points_to_its_modifier_group(currency):
    assert "group: essence" in currency.get_currency("Greater Essence of the Body")["note"]
    assert "perfect_essence" in currency.get_currency("完美肉體精髓")["note"]
    assert "modifiers_for" in currency.get_currency("Essence of the Body")["note"]
    assert "note" not in currency.get_currency("Chaos Orb")
    assert essence_group({"category": "currency", "name": "Runic Alloy"}) is None


def test_get_currency_says_what_is_not_in_the_data(currency):
    assert any("Prices" in line for line in currency.get_currency("Chaos Orb")["not_in_data"])
    assert any("價格" in line for line in currency.get_currency("混沌石")["not_in_data"])


def test_unknown_currency_gives_close_names(currency):
    with pytest.raises(NotFound, match="Close names: Chaos Orb"):
        currency.get_currency("Chaos")
    with pytest.raises(BadArgument):
        currency.get_currency("  ")


def test_lookup_entity_finds_currency_in_either_language(lookup):
    hits = lookup.lookup_entity("崇高石", kind="currency")["hits"]
    assert hits[0]["slug"] == "Exalted_Orb" and hits[0]["kind"] == "currency"


# -- lists -----------------------------------------------------------------------------------------------

def test_currency_by_category_in_english_or_chinese(currency):
    omens = currency.currency_by(category="omen")
    assert omens["total"] == 3 and omens["filters"]["category"] == "omen"
    assert currency.currency_by(category="預兆")["total"] == 3
    assert currency.currency_by(category="Omens")["total"] == 3
    zh = currency.currency_by(category="符文")
    assert [r["slug"] for r in zh["results"]] == ["Desert_Rune", "Amanamus_Gaze"]
    assert zh["results"][0]["lines"] == ["軍用武器: 附加7至11火焰傷害", "護甲: +14%火焰抗性"]


def test_currency_by_text_searches_effects_tags_and_names(currency):
    assert [r["slug"] for r in currency.currency_by(text="Fire Resistance")["results"]] == ["Desert_Rune"]
    assert [r["slug"] for r in currency.currency_by(text="Exalted Orb")["results"]] == [
        "Exalted_Orb", "Perfect_Exalted_Orb", "Omen_of_Greater_Exaltation"]
    assert {r["slug"] for r in currency.currency_by(text="currency_shard")["results"]} == {"Artificers_Shard"}
    assert currency.currency_by(text="混沌石")["total"] == 3


def test_currency_by_max_level_uses_drop_and_required_level(currency):
    by = {lvl: {r["slug"] for r in currency.currency_by(max_level=lvl, limit=200)["results"]} for lvl in (12, 14, 15, 20)}
    assert "Chaos_Orb" in by[12] and "Greater_Chaos_Orb" not in by[12]
    assert "Desert_Rune" not in by[14] and "Desert_Rune" in by[15]
    assert "Amanamus_Gaze" not in by[15] and "Amanamus_Gaze" in by[20]       # drops at 1, requires 20
    sorted_rows = currency.currency_by(category="currency", max_level=35)["results"]
    assert [r["slug"] for r in sorted_rows] == ["Chaos_Orb", "Greater_Chaos_Orb", "Exalted_Orb", "Artificers_Shard",
                                                "Thaumaturgic_Flux_Level_5"]


def test_currency_by_counts_items_without_a_drop_level(lookup, env, tmp_path):
    rows = read_jsonl(env / CURRENCY_FILE)
    rows[0] = {**rows[0], "drop_level": None, "detail_fetched_at": None}
    (tmp_path / "data" / "currency").mkdir(parents=True)
    write_jsonl(tmp_path / CURRENCY_FILE, rows)
    own = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    own.base_dir = tmp_path
    result = CurrencyLookup(own).currency_by(max_level=80, limit=200)
    assert result["without_drop_level"] == 1 and result["total"] == 17


def test_currency_by_without_a_filter_lists_the_categories(currency):
    result = currency.currency_by()
    assert result["categories"] == {"currency": 8, "essence": 3, "splinter": 1, "catalyst": 1, "omen": 3, "augment": 2}


def test_currency_by_rejects_bad_arguments(currency):
    with pytest.raises(BadArgument, match="category must be one of"):
        currency.currency_by(category="maps")
    for level in (0, True, "5"):
        with pytest.raises(BadArgument, match="max_level"):
            currency.currency_by(max_level=level)
    with pytest.raises(BadArgument):
        currency.currency_by(text="x" * 500)


def test_currency_by_respects_the_limit(currency):
    result = currency.currency_by(category="currency", limit=2)
    assert result["total"] == 8 and len(result["results"]) == 2


# -- missing or broken data -----------------------------------------------------------------------------------

def test_missing_currency_data_names_the_update(lookup, tmp_path):
    lookup.base_dir = tmp_path
    with pytest.raises(ServiceUnavailable, match="update_data scope currency"):
        CurrencyLookup(lookup).get_currency("Chaos Orb")


def test_unreadable_currency_data_names_the_update(lookup, tmp_path):
    (tmp_path / "data" / "currency").mkdir(parents=True)
    (tmp_path / CURRENCY_FILE).write_text('{"slug": "X"}\n', encoding="utf-8")
    lookup.base_dir = tmp_path
    with pytest.raises(ServiceUnavailable, match="unreadable"):
        CurrencyLookup(lookup).currency_by(category="omen")


# -- MCP --------------------------------------------------------------------------------------------------------

def test_currency_tools_through_the_server(lookup, monkeypatch):
    monkeypatch.setattr(mcp_server, "_service", lookup)
    result = asyncio.run(mcp_server.server.call_tool("get_currency", {"name": "削切之兆"}))
    assert result.is_error is False
    assert json.loads(result.content[0].text)["currency"]["slug"] == "Omen_of_Whittling"
    listed = asyncio.run(mcp_server.server.call_tool("currency_by", {"category": "essence"}))
    assert json.loads(listed.content[0].text)["total"] == 3
    with pytest.raises(ToolError, match="category must be one of"):
        asyncio.run(mcp_server.server.call_tool("currency_by", {"category": "maps"}))


# -- update -----------------------------------------------------------------------------------------------------

def update_spec(**expect) -> Spec:
    raw = copy.deepcopy(fixture_spec().raw)
    raw["sources"]["currency"]["expect_min"] = {
        "records": 10, "categories": {"currency": 5, "essence": 2, "splinter": 1, "catalyst": 1, "omen": 2,
                                      "augment": 2},
        "zh_ratio": 0.9, "detail_ratio": 0.9, **expect}
    return Spec(raw)


@pytest.fixture
def updater(tmp_path):
    base = build_full_environment(tmp_path, fixture_spec())
    return mnt.DataMaintenance(base, update_spec(), base / GRAPH_REL)


def test_currency_update_writes_the_data_and_the_names(updater):
    result = updater.update("currency", fetch=CurrencySite())
    assert result["done"] is True and result["records"] == 18 and result["requests"] == 6 + 18
    assert result["categories"]["omen"] == 3 and len(result["added"]) == 18 and result["removed"] == []
    index = {r["slug"]: r["kind"] for r in read_jsonl(updater.data_dir / "catalog" / "entity_index.jsonl")}
    assert index["Chaos_Orb"] == "currency"
    status = {d["name"]: d for d in updater.status()["datasets"]}["currency"]
    assert status["records"] == 18 and status["categories"]["augment"] == 2 and status["without_item_page"] == 0


def test_a_routine_update_reads_only_the_listings(updater):
    updater.update("currency", fetch=CurrencySite())
    again = updater.update("currency", fetch=CurrencySite())
    assert again["requests"] == 6 and again["item_pages_reused"] == 18 and again["added"] == []


def test_older_than_days_zero_reads_every_item_page(updater):
    updater.update("currency", fetch=CurrencySite())
    again = updater.update("currency", older_than_days=0, fetch=CurrencySite())
    assert again["requests"] == 24 and again["item_pages_read"] == 18


def test_a_new_item_on_the_site_is_the_only_page_read(updater):
    updater.update("currency", fetch=CurrencySite())
    rows = read_jsonl(updater.data_dir / "currency" / "currency.jsonl")
    write_jsonl(updater.data_dir / "currency" / "currency.jsonl", [r for r in rows if r["slug"] != "Desert_Rune"])
    site = CurrencySite()
    again = updater.update("currency", fetch=site)
    assert site.calls[-1] == "https://poe2db.tw/us/Desert_Rune" and again["added"] == ["Desert_Rune"]


def test_the_update_runs_in_batches_and_continues(updater, monkeypatch):
    monkeypatch.setattr(mnt, "CURRENCY_BATCH", 10)
    first = updater.update("currency", fetch=CurrencySite())
    assert first["done"] is False and first["fetched"] == 10 and first["left"] == 14
    assert not (updater.data_dir / "currency").exists()
    second = updater.update("currency", fetch=CurrencySite())
    assert second["done"] is False and second["left"] == 4
    third = updater.update("currency", fetch=CurrencySite())
    assert third["done"] is True and third["requests"] == 4 and third["records"] == 18
    assert not (updater.base_dir / "output" / "cache" / "currency_update" / "new").exists()


def test_a_listing_that_does_not_parse_writes_nothing(updater):
    pages = site_pages()
    pages["https://poe2db.tw/us/Augment"] = "<html>moved</html>"
    with pytest.raises(ServiceUnavailable, match="Nothing was written"):
        updater.update("currency", fetch=CurrencySite(pages))
    assert not (updater.data_dir / "currency").exists()


def test_a_listing_that_cannot_be_fetched_keeps_the_run(updater):
    pages = site_pages()
    del pages["https://poe2db.tw/tw/Omen"]
    with pytest.raises(ServiceUnavailable, match="calling again continues"):
        updater.update("currency", fetch=CurrencySite(pages))
    assert not (updater.data_dir / "currency").exists()


def test_currency_update_options(updater):
    for options in ({"names": ["Chaos Orb"]}, {"dry_run": True}, {"max_gems": 5}):
        with pytest.raises(BadArgument, match="a currency update reads"):
            updater.update("currency", fetch=CurrencySite(), **options)
    with pytest.raises(BadArgument, match="older_than_days must be between"):
        updater.update("currency", older_than_days=-1, fetch=CurrencySite())


def test_detail_freshness():
    assert mnt._detail_is_fresh({"detail_fetched_at": "2020-01-01T00:00:00+00:00"}, None) is True
    assert mnt._detail_is_fresh({"detail_fetched_at": "2020-01-01T00:00:00+00:00"}, 30) is False
    assert mnt._detail_is_fresh({"detail_fetched_at": mnt.now_iso()}, 30) is True
    assert mnt._detail_is_fresh({"detail_fetched_at": mnt.now_iso()}, 0) is False
    assert mnt._detail_is_fresh({}, None) is False


def test_update_prompt_for_currency():
    from src.tools.build_workflow import update_prompt_text
    text = update_prompt_text("currency")
    assert 'scope="currency"' in text and "older_than_days=0" in text and "at most 16 calls" in text


# -- review findings (2026-11-17) ----------------------------------------------------------------------------

def test_english_category_words(currency):
    for word in ("runes", "Rune", "soul cores", "currencies", "orbs"):
        assert currency.currency_by(category=word)["filters"]["category"] in ("augment", "currency")
    assert currency.currency_by(category="soul core")["total"] == 2


def test_a_blank_text_is_no_filter(currency):
    assert "categories" in currency.currency_by(text="   ")


def own_lookup(env, tmp_path, rows):
    (tmp_path / "data" / "currency").mkdir(parents=True)
    write_jsonl(tmp_path / CURRENCY_FILE, rows)
    own = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    own.base_dir = tmp_path
    return CurrencyLookup(own)


def test_related_matches_any_case_and_the_possessive(env, tmp_path):
    rows = read_jsonl(env / CURRENCY_FILE)
    rows.append({**rows[0], "slug": "Omen_Y", "name": "Omen Y", "category": "omen",
                 "effects": ["a CHAOS ORB's power doubles"], "effects_zh_tw": []})
    found = {r["slug"]: r["lines"] for r in own_lookup(env, tmp_path, rows).get_currency("Chaos_Orb")["related"]}
    assert found["Omen_Y"] == ["a CHAOS ORB's power doubles"]


def test_related_falls_back_to_english_when_the_chinese_lines_differ(env, tmp_path):
    rows = read_jsonl(env / CURRENCY_FILE)
    rows.append({**rows[0], "slug": "Omen_Z", "name": "Omen Z", "category": "omen",
                 "effects": ["first line", "your next Chaos Orb is lucky"], "effects_zh_tw": ["只有一行"]})
    found = {r["slug"]: r["lines"] for r in own_lookup(env, tmp_path, rows).get_currency("混沌石")["related"]}
    assert found["Omen_Z"] == ["your next Chaos Orb is lucky"]


def test_a_long_related_list_is_cut_and_counted(env, tmp_path, monkeypatch):
    import src.tools.currency as module
    monkeypatch.setattr(module, "MAX_RELATED", 1)
    rows = read_jsonl(env / CURRENCY_FILE)
    rows.append({**rows[0], "slug": "Omen_W", "name": "Omen W", "category": "omen",
                 "effects": ["two Chaos Orbs"], "effects_zh_tw": []})
    result = own_lookup(env, tmp_path, rows).get_currency("Chaos_Orb")
    assert len(result["related"]) == 1 and result["related_total"] == 2


def test_missing_item_pages_do_not_stop_the_run(updater):
    pages = site_pages()
    for slug in ("Chaos_Orb", "Greater_Chaos_Orb", "Exalted_Orb", "Perfect_Exalted_Orb", "Artificers_Shard"):
        del pages[f"https://poe2db.tw/us/{slug}"]
    with pytest.raises(ServiceUnavailable, match="item page read"):    # 5 of 18 is below the 90% minimum
        updater.update("currency", fetch=CurrencySite(pages))


def test_a_network_outage_says_so_and_keeps_the_run(updater):
    pages = site_pages()

    def site(url):
        if url in pages and url.endswith(("Stackable_Currency", "Omen", "Augment")):
            return pages[url]
        raise requests.ConnectionError("down")
    with pytest.raises(ServiceUnavailable, match="in a row failed") as err:
        updater.update("currency", fetch=site)
    assert "changed shape" not in str(err.value)


def test_a_refresh_keeps_stored_details_when_a_page_fails(updater):
    updater.update("currency", fetch=CurrencySite())
    pages = site_pages()
    del pages["https://poe2db.tw/us/Breach_Splinter"]
    result = updater.update("currency", older_than_days=0, fetch=CurrencySite(pages))
    assert result["item_pages_failed"] == ["Breach_Splinter"]
    rows = {r["slug"]: r for r in read_jsonl(updater.data_dir / "currency" / "currency.jsonl")}
    assert rows["Breach_Splinter"]["drop_level"] == 66 and rows["Breach_Splinter"]["detail_fetched_at"]


def test_left_does_not_count_pages_that_failed(updater, monkeypatch):
    monkeypatch.setattr(mnt, "CURRENCY_BATCH", 10)
    pages = site_pages()
    del pages["https://poe2db.tw/us/Chaos_Orb"]
    first = updater.update("currency", fetch=CurrencySite(pages))
    assert first["done"] is False and first["left"] == 14          # 18 items: 3 read, 1 failed (15 if it were counted)


def test_a_long_added_list_is_cut_and_counted():
    assert mnt._listed("added", ["a"] * 5) == {"added": ["a"] * 5}
    long = mnt._listed("added", [str(i) for i in range(40)])
    assert len(long["added"]) == mnt.MAX_LISTED_SLUGS and long["added_count"] == 40
