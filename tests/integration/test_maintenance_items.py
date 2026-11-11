"""The `items` update scope and the merge of a partial item update (maintenance + collect_items)."""

import json

import pytest

from src.scrapers import collect_items as ci
from src.scrapers.common import DATA_LOCK_FILE, read_jsonl
from src.tools import maintenance as mnt
from src.tools.lookup import BadArgument, ServiceUnavailable
from tests.item_support import ARMOUR_BASES, BOW_BASES, BOW_MODS, BOW_UNIQUES, SOCKETABLES, ItemSite, class_page, item_spec
from tests.kg_support import GRAPH_REL, build_full_environment

pytestmark = pytest.mark.integration

ITEM_FILES = ("data/items/bases.jsonl", "data/items/uniques.jsonl", "data/items/modifiers.jsonl", "data/items/classes.json")
ALL_URLS = 6        # three pages, two languages


@pytest.fixture
def base(tmp_path):
    return build_full_environment(tmp_path, item_spec())


@pytest.fixture
def tool(base):
    return mnt.DataMaintenance(base, item_spec(), base / GRAPH_REL)


def item_files(base) -> dict[str, bytes]:
    return {rel: (base / rel).read_bytes() for rel in ITEM_FILES if (base / rel).exists()}


def test_first_items_update_writes_every_file_and_indexes_the_items(tool, base):
    site = ItemSite()
    result = tool.update("items", fetch=site)
    assert result["done"] is True and result["left"] == 0 and result["requests"] == ALL_URLS
    assert (result["pages"], result["bases"], result["uniques"]) == (3, 4, 1)
    assert result["modifiers"] == len(BOW_MODS) + len(SOCKETABLES) + 2 and result["zh_name_ratio"] == 1.0
    assert result["modifier_zh_ratio"] == 1.0 and result["mod_groups_english_only"] == 0
    bases = {b["slug"]: b["item_page"] for b in read_jsonl(base / ITEM_FILES[0])}
    assert bases == {"Shortbow": "Bows", "Dualstring_Bow": "Bows", "Golden_Mantle": "Body_Armours",
                     "Rusted_Cuirass": "Body_Armours"}
    assert set(item_files(base)) == set(ITEM_FILES)
    kinds = {row["kind"] for row in read_jsonl(base / "data" / "catalog" / "entity_index.jsonl")}
    assert {"item_base", "item_unique"} <= kinds and result["index_entities"] > 0
    assert not (base / "output" / "cache" / "items_update" / "all").exists()


def test_items_update_in_small_batches_fetches_every_page_once(tool, base, monkeypatch):
    monkeypatch.setattr(mnt, "ITEMS_BATCH", 4)
    calls, lefts = [], []
    for _ in range(5):
        site = ItemSite()
        result = tool.update("items", fetch=site)
        calls += site.calls
        lefts.append(result["left"])
        if result["done"]:
            break
        assert item_files(base) == {}                              # nothing written until every page is in
    assert lefts == [2, 0] and len(calls) == ALL_URLS == len(set(calls))


def test_items_status_lists_counts(tool, base):
    tool.update("items", fetch=ItemSite())
    items = next(d for d in tool.status()["datasets"] if d["name"] == "items")
    assert (items["records"], items["uniques"], items["modifiers"], items["update_scope"]) == (4, 1, 11, "items")


def test_partial_update_replaces_only_the_named_class(tool, base):
    tool.update("items", fetch=ItemSite())
    before = {b["slug"]: b for b in read_jsonl(base / ITEM_FILES[0])}
    site = ItemSite()
    for lang in ("en", "zh-tw"):
        path = "us" if lang == "en" else "tw"
        site.pages[f"https://poe2db.tw/{path}/Bows"] = class_page(lang, bases=BOW_BASES[:1], uniques=BOW_UNIQUES,
                                                                  mods=BOW_MODS[:2], socketables=SOCKETABLES)
    result = tool.update("items", names=["bows"], fetch=site)
    assert result["done"] is True and sorted(site.calls) == ["https://poe2db.tw/tw/Bows", "https://poe2db.tw/us/Bows"]
    after = {b["slug"]: b for b in read_jsonl(base / ITEM_FILES[0])}
    assert "Dualstring_Bow" not in after and after["Golden_Mantle"] == before["Golden_Mantle"]       # other class kept
    mods = read_jsonl(base / ITEM_FILES[2])
    assert sum(m["mod_page"] == "Bows" and m["group"] == "normal" for m in mods) == 2
    assert sum(m["mod_page"] == "Body_Armours_str_dex_int" for m in mods) == 2
    pages = [p["slug"] for p in json.loads((base / ITEM_FILES[3]).read_text(encoding="utf-8"))["pages"]]
    assert pages == ["Bows", "Body_Armours_str_dex_int"] and after["Golden_Mantle"]["mod_page"] == "Body_Armours_str_dex_int"


def test_a_class_name_takes_its_attribute_pages_too(tool):
    assert tool._item_pages(["Body Armours"]) == ["Body_Armours", "Body_Armours_str_dex_int"]
    assert tool._item_pages([]) == ["Bows", "Body_Armours", "Body_Armours_str_dex_int"]


def test_a_page_slug_takes_that_page_only(tool):
    assert tool._item_pages(["Body_Armours_str_dex_int"]) == ["Body_Armours_str_dex_int"]
    assert tool._item_pages(["body_armours"]) == ["Body_Armours"]


def test_chinese_class_names_need_the_stored_class_registry(tool):
    with pytest.raises(BadArgument, match="not an item class page: '胸甲'"):
        tool._item_pages(["胸甲"])
    tool.update("items", fetch=ItemSite())
    assert tool._item_pages(["胸甲"]) == ["Body_Armours", "Body_Armours_str_dex_int"]
    assert tool._item_pages(["弓"]) == ["Bows"]


def test_unknown_class_name_is_refused_without_a_request(tool):
    site = ItemSite()
    with pytest.raises(BadArgument, match="not an item class page: 'Swords'"):
        tool.update("items", names=["Swords"], fetch=site)
    assert site.calls == []


@pytest.mark.parametrize("options", [{"dry_run": True}, {"older_than_days": 3}, {"max_gems": 5}])
def test_items_takes_no_gem_options(tool, options):
    with pytest.raises(BadArgument, match="only apply to the gem scopes; an items update"):
        tool.update("items", fetch=ItemSite(), **options)


def test_partial_update_without_stored_data_is_refused_before_any_request(tool, base):
    site = ItemSite()
    with pytest.raises(ServiceUnavailable, match="no local item data to update in part"):
        tool.update("items", names=["Bows"], fetch=site)
    assert item_files(base) == {} and site.calls == []


def test_page_that_no_longer_parses_writes_nothing_and_drops_the_run(tool, base):
    tool.update("items", fetch=ItemSite())
    before = item_files(base)
    site = ItemSite()
    site.pages["https://poe2db.tw/us/Bows"] = class_page("en", bases=BOW_BASES, uniques=BOW_UNIQUES)   # no modifier object
    with pytest.raises(ServiceUnavailable, match="Bows: no modifier object.*Nothing was written"):
        tool.update("items", fetch=site)
    assert item_files(base) == before and not (base / "output" / "cache" / "items_update" / "all").exists()


def test_too_few_records_write_nothing(base):
    tool = mnt.DataMaintenance(base, item_spec(bases=50), base / GRAPH_REL)
    with pytest.raises(ServiceUnavailable, match="only 4 bases parsed, below expect_min=50"):
        tool.update("items", fetch=ItemSite())
    assert item_files(base) == {}


def test_a_page_that_fails_to_download_keeps_the_progress(tool, base):
    site = ItemSite()
    del site.pages["https://poe2db.tw/tw/Body_Armours"]
    with pytest.raises(ServiceUnavailable, match="network error.*calling again continues"):
        tool.update("items", fetch=site)
    assert item_files(base) == {}
    retry = ItemSite()
    result = tool.update("items", fetch=retry)
    assert result["done"] is True                          # the pages fetched before the error are not asked again
    assert retry.calls == ["https://poe2db.tw/tw/Body_Armours", "https://poe2db.tw/us/Body_Armours_str_dex_int",
                           "https://poe2db.tw/tw/Body_Armours_str_dex_int"]


def test_items_update_releases_both_locks(tool, base):
    from src.scrapers.common import file_lock
    from src.tools.lookup import DATA_LOCK
    tool.update("items", fetch=ItemSite())
    assert DATA_LOCK.acquire(blocking=False)
    DATA_LOCK.release()
    with file_lock(base / "data" / DATA_LOCK_FILE):
        pass


def test_named_runs_get_their_own_cache_and_left_counts_only_their_pages(tool, base, monkeypatch):
    tool.update("items", fetch=ItemSite())
    monkeypatch.setattr(mnt, "ITEMS_BATCH", 1)
    first = tool.update("items", names=["Body Armours"], fetch=ItemSite())
    assert first == {**first, "done": False, "left": 3}
    second = tool.update("items", names=["Bows"], fetch=ItemSite())
    assert second["left"] == 1
    runs = sorted(p.name for p in (base / "output" / "cache" / "items_update").iterdir())
    assert len(runs) == 2 and all(name.startswith("pages_") and len(name) == 18 for name in runs)


def test_abandoned_runs_are_swept(tool, base):
    import os
    import time
    stale = base / "output" / "cache" / "items_update" / "pages_000000000000"
    (stale / "pages").mkdir(parents=True)
    old_file = stale / "pages" / "x.html"
    old_file.write_text("x", encoding="utf-8")
    old = time.time() - mnt.RUN_CACHE_SECONDS - 60
    os.utime(old_file, (old, old))
    tool.update("items", fetch=ItemSite())
    assert not stale.exists()


def test_an_item_on_two_pages_keeps_the_first_pages_record_in_a_partial_update(tool, base):
    shared = {**BOW_BASES[0], "props": [("Armour", "護甲", "999")]}          # Shortbow listed again, other numbers
    site = ItemSite()
    for lang, path in (("en", "us"), ("zh-tw", "tw")):
        site.pages[f"https://poe2db.tw/{path}/Body_Armours"] = class_page(lang, bases=[*ARMOUR_BASES, shared])
    tool.update("items", fetch=site)
    full = {b["slug"]: b for b in read_jsonl(base / ITEM_FILES[0])}
    assert full["Shortbow"]["item_page"] == "Bows"
    for names in (["Body Armours"], ["Bows"]):
        tool.update("items", names=names, fetch=site)
        merged = {b["slug"]: b for b in read_jsonl(base / ITEM_FILES[0])}
        assert merged["Shortbow"] == {**full["Shortbow"], "fetched_at": merged["Shortbow"]["fetched_at"]}
        assert list(merged) == list(full)                                            # same order as a full run


# -- merge_records on its own -------------------------------------------------------------------

def test_merge_keeps_other_classes_and_relinks_bases():
    spec = item_spec()
    full, _ = ci.collect(spec, ItemSite())
    site = ItemSite()
    for lang in ("en", "zh-tw"):
        path = "us" if lang == "en" else "tw"
        site.pages[f"https://poe2db.tw/{path}/Body_Armours"] = class_page(lang, bases=ARMOUR_BASES[:1])
    fresh, _ = ci.collect(spec, site, slugs=["Body_Armours"])
    merged = ci.merge_records(spec, full, fresh, ["Body_Armours"])
    slugs = {b["slug"] for b in merged["bases"]}
    assert slugs == {"Shortbow", "Dualstring_Bow", "Golden_Mantle"}                    # Rusted Cuirass left the page
    golden = next(b for b in merged["bases"] if b["slug"] == "Golden_Mantle")
    assert golden["mod_page"] == "Body_Armours_str_dex_int"                            # relinked from the kept class page
    assert len(merged["modifiers"]) == len(full["modifiers"])                          # an items-only page has no modifiers
    assert merged["uniques"][0]["base_slug"] == "Shortbow"


def test_read_records_returns_none_when_a_file_is_missing(tmp_path):
    spec = item_spec()
    assert ci.read_records(spec, tmp_path) is None
    records, _ = ci.collect(spec, ItemSite())
    ci.write_records(spec, tmp_path, records)
    assert len(ci.read_records(spec, tmp_path)["bases"]) == 4
    (tmp_path / "items" / "uniques.jsonl").unlink()
    assert ci.read_records(spec, tmp_path) is None


# -- page checks ------------------------------------------------------------------------------

def test_a_page_that_parses_to_no_items_stops_the_collection():
    site = ItemSite()
    site.pages["https://poe2db.tw/us/Bows"] = class_page("en", mods=BOW_MODS, socketables=SOCKETABLES)
    with pytest.raises(ci.ItemCollectionError, match="Bows: no bases or uniques parsed"):
        ci.collect(item_spec(), site)


def test_a_page_whose_modifier_object_is_empty_stops_the_collection():
    site = ItemSite()
    site.pages["https://poe2db.tw/us/Bows"] = class_page("en", bases=BOW_BASES, uniques=BOW_UNIQUES, mods=[])
    with pytest.raises(ci.ItemCollectionError, match="Bows: no normal modifiers parsed"):
        ci.collect(item_spec(), site)


def test_modifiers_without_chinese_text_stop_the_update(base):
    tool = mnt.DataMaintenance(base, item_spec(zh_ratio=0.9), base / GRAPH_REL)
    site = ItemSite()
    site.pages["https://poe2db.tw/tw/Bows"] = class_page("zh-tw", bases=BOW_BASES, uniques=BOW_UNIQUES,
                                                         mods=BOW_MODS[:1], socketables=SOCKETABLES)
    with pytest.raises(ServiceUnavailable, match="modifiers have Chinese text"):
        tool.update("items", fetch=site)
    assert item_files(base) == {}


# -- jewels, charms: pages without their own class name, bases with their own modifier page -------

def jewel_site():
    """Bows lists the bases and uniques (no modifier object, like Jewels); Shortbow is a modifier
    page whose slug is a base (like Ruby), with an untranslated class name in its Chinese object."""
    spec = item_spec([{"slug": "Bows", "group": "jewel", "roles": ["items"]},
                      {"slug": "Shortbow", "group": "jewel", "roles": ["mods"]}])
    twice = [BOW_UNIQUES[0], {**BOW_UNIQUES[0], "base": ("Dualstring Bow", "雙弦弓"),
                              "mods": [("Adds 1 to 2 Fire Damage", "附加1至2火焰傷害")]}]
    pages = {}
    for lang, path in (("en", "us"), ("zh-tw", "tw")):
        pages[f"https://poe2db.tw/{path}/Bows"] = class_page(lang, bases=BOW_BASES, uniques=twice)
        pages[f"https://poe2db.tw/{path}/Shortbow"] = class_page(lang, mods=BOW_MODS, label=("Shortbow", "Shortbow"),
                                                               title=("Shortbow", "短弓"))
    return spec, ItemSite(pages)


def test_class_names_come_from_the_page_title_when_the_modifier_object_has_none():
    spec, site = jewel_site()
    records, _ = ci.collect(spec, site)
    assert {(b["item_class"], b["item_class_zh_tw"]) for b in records["bases"]} == {("Bows", "弓")}
    assert [(p["label"], p["label_zh_tw"]) for p in records["classes"]["pages"]] == [("Shortbow", "短弓")]


def test_a_base_with_its_own_modifier_page_is_linked_to_it():
    spec, site = jewel_site()
    records, _ = ci.collect(spec, site)
    assert {b["slug"]: b["mod_page"] for b in records["bases"]} == {"Shortbow": "Shortbow", "Dualstring_Bow": None}


def test_versions_of_one_unique_are_kept_as_variants():
    spec, site = jewel_site()
    records, _ = ci.collect(spec, site)
    assert len(records["uniques"]) == 1
    unique = records["uniques"][0]
    assert unique["base"] == "Shortbow" and unique["mods_zh_tw"][0] == "增加100%攻擊速度"
    assert unique["variants"] == [{"base": "Dualstring Bow", "base_zh_tw": "雙弦弓", "implicits": [], "implicits_zh_tw": [],
                                   "mods": ["Adds 1 to 2 Fire Damage"], "mods_zh_tw": ["附加1至2火焰傷害"]}]


def test_what_a_charm_grants_is_collected_and_searchable(tmp_path):
    from src.tools.build_tools import BuildTools
    from src.tools.lookup import LookupService
    charm = {**BOW_BASES[0], "effect": ("+25% to Fire Resistance", "+25%火焰抗性")}
    site = ItemSite()
    for lang, path in (("en", "us"), ("zh-tw", "tw")):
        site.pages[f"https://poe2db.tw/{path}/Bows"] = class_page(lang, bases=[charm, BOW_BASES[1]], uniques=BOW_UNIQUES,
                                                                  mods=BOW_MODS, socketables=SOCKETABLES)
    base = build_full_environment(tmp_path, item_spec())
    mnt.DataMaintenance(base, item_spec(), base / GRAPH_REL).update("items", fetch=site)
    tools = BuildTools(LookupService(base_dir=base, graph_path=base / GRAPH_REL))
    record = tools.items.get_item("Shortbow")["item"]
    assert record["effects"] == ["+25% to Fire Resistance"] and record["effects_zh_tw"] == ["+25%火焰抗性"]
    assert [i["slug"] for i in tools.items.items_by(text="火焰抗性")["items"]] == ["Shortbow"]
    assert "+25% to Fire Resistance" in tools.verify_build(items=["Shortbow"])["verified"]["items"][0]["lines"]


def test_an_item_class_given_as_an_item_says_so(tmp_path):
    from src.tools.build_tools import BuildTools
    from src.tools.lookup import LookupService
    base = build_full_environment(tmp_path, item_spec())
    mnt.DataMaintenance(base, item_spec(), base / GRAPH_REL).update("items", fetch=ItemSite())
    tools = BuildTools(LookupService(base_dir=base, graph_path=base / GRAPH_REL))
    result = tools.verify_build(items=["Bows", "Not An Item"])
    reasons = {u["input"]: u["reason"] for u in result["unverified"]}
    assert "this is an item class, not an item" in reasons["Bows"]
    assert "item class" not in reasons["Not An Item"]
