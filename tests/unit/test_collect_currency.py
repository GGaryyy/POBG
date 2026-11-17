"""The currency collector and the shared item-page parser, on synthetic pages (tests/currency_support.py)."""

from __future__ import annotations

import pytest

from src.scrapers import collect_currency as cc
from src.scrapers.collect_campaign import parse_item_page
from src.scrapers.common import make_soup
from src.scrapers.item_page import drop_level, item_fields
from tests.currency_support import (
    CurrencySite,
    card_page,
    currency_spec,
    entry,
    limited,
    listing,
    max_level,
    min_level,
    pane,
    site_pages,
    stack,
    table_page,
)

PANES = {"A": "currency", "B": "omen"}


def parse(html: str) -> dict:
    return cc.parse_entry(make_soup(html).select_one("div.col"))


@pytest.fixture
def records(tmp_path):
    return {r["slug"]: r for r in cc.collect(currency_spec(), fetch=CurrencySite(), cache_dir=tmp_path)[0]}


# -- listing entries ---------------------------------------------------------------------------------------

def test_entry_name_with_and_without_inline_icon():
    assert parse(entry("Chaos_Orb", "Chaos Orb"))["name"] == "Chaos Orb"
    assert parse(entry("Omen_X", "Omen X", icon=False, link_class="whiteitem Omen"))["name"] == "Omen X"
    assert parse(entry("Flux_5", "Thaumaturgic Flux (Level 5)"))["name"] == "Thaumaturgic Flux (Level 5)"


def test_entry_reads_properties_by_keyword_and_label():
    row = parse(entry("G", "Greater Chaos Orb", (stack(size=20), min_level(35))))
    assert (row["stack_size"], row["min_modifier_level"], row["max_item_level"]) == (20, 35, None)
    assert row["properties"] == ["Stack Size: 1 / 20", "Minimum Modifier Level: 35"]
    bone = parse(entry("Bone", "Gnawed Jawbone", (stack(), max_level(64))))
    assert (bone["max_item_level"], bone["min_modifier_level"]) == (64, None)
    gaze = parse(entry("Gaze", "Amanamu's Gaze", (limited("1 Ancient Augment"),)))
    assert (gaze["limit"], gaze["stack_size"]) == ("1 Ancient Augment", None)


def test_entry_lines_join_a_line_break_and_keep_ranges():
    row = parse(entry("O", "Omen", lines=(("explicitMod", "your next<br/>\nChaos Orb will remove"),
                                          ("explicitMod", '+(30<span class="ndash">—</span>39) to maximum Life'))))
    assert row["effects"] == ["your next Chaos Orb will remove", "+(30—39) to maximum Life"]


def test_entry_sorts_lines_by_kind_and_reads_the_required_level():
    row = parse(entry("R", "Desert Rune", lines=(("implicitMod", "Armour: +14% to Fire Resistance"),
                                                 ("enchantMod", "Waystone: 10% more Rarity"),
                                                 ("bondedMod", "Bonded:")),
                      requires='Requires: <span class="colourDefault">Level 15</span>'))
    assert (row["implicits"], row["enchants"], row["bonded"], row["effects"]) == (
        ["Armour: +14% to Fire Resistance"], ["Waystone: 10% more Rarity"], ["Bonded:"], [])
    assert row["requires_level"] == 15


def test_an_entry_without_an_effect_line_is_kept():
    row = parse(entry("Artificers_Shard", "Artificer's Shard", (stack(size=10),)))
    assert row["slug"] == "Artificers_Shard" and row["effects"] == [] and row["stack_size"] == 10


def test_an_entry_without_a_name_link_is_skipped():
    assert cc.parse_entry(make_soup('<div class="col"><div class="flex-grow-1">no link</div></div>')
                          .select_one("div.col")) is None


def test_listing_reads_only_the_mapped_tabs_with_their_category():
    html = listing(pane("A", "A", [entry("X", "X")]), pane("Ref", "Ref", [entry("Y", "Y")]),
                   pane("B", "B", [entry("Z", "Z")]))
    assert [(e["slug"], e["category"]) for e in cc.parse_listing(html, PANES)] == [("X", "currency"), ("Z", "omen")]
    assert [e["slug"] for e in cc.parse_listing(html)] == ["X", "Y", "Z"]


def test_listing_without_tabs_gives_nothing():
    assert cc.parse_listing("<html><div class='col'>stray</div></html>", PANES) == []


# -- merging ------------------------------------------------------------------------------------------------

def test_merge_joins_chinese_by_slug_and_keeps_english_when_it_is_missing():
    english = [{**parse(entry("X", "X Orb", lines=(("explicitMod", "does x"),))), "category": "currency"},
               {**parse(entry("Y", "Y Orb")), "category": "currency"}]
    chinese = [{**parse(entry("X", "X 石", lines=(("explicitMod", "做 x"),))), "category": None}]
    merged = {r["slug"]: r for r in cc.merge_entries(english, chinese)}
    assert (merged["X"]["name_zh_tw"], merged["X"]["effects_zh_tw"]) == ("X 石", ["做 x"])
    assert (merged["Y"]["name_zh_tw"], merged["Y"]["effects_zh_tw"]) == (None, [])


def test_merge_keeps_the_first_tab_and_records_the_others():
    alloy = parse(entry("Alloy", "Runic Alloy"))
    merged = cc.merge_entries([{**alloy, "category": "currency"}, {**alloy, "category": "essence"},
                               {**alloy, "category": "essence"}], [])
    assert len(merged) == 1 and (merged[0]["category"], merged[0]["also_in"]) == ("currency", ["essence"])


# -- item pages ---------------------------------------------------------------------------------------------

def test_item_fields_read_cards_and_table_rows():
    cards = item_fields(card_page({"DropLevel": "12", "Class": "Stackable Currency"}))
    rows = item_fields(table_page({"DropLevel": "60", "BaseType": "Greater Jeweller's Orb"}))
    assert (cards["DropLevel"], cards["Class"], drop_level(cards)) == ("12", "Stackable Currency", 12)
    assert (rows["BaseType"], drop_level(rows)) == ("Greater Jeweller's Orb", 60)
    assert drop_level({"DropLevel": "n/a"}) is None and drop_level({}) is None


def test_item_fields_first_value_wins():
    html = card_page({"DropLevel": "5"}).replace("</body>", table_page({"DropLevel": "9"}) + "</body>")
    assert item_fields(html)["DropLevel"] == "5"


def test_campaign_reads_the_new_card_layout_too():
    page = card_page({"DropLevel": "25", "BaseType": "Lesser Jeweller's Orb"}).replace(
        "</body>", '<div class="explicitMod">Sets a Skill Gem to have 3 Support Gem Sockets</div></body>')
    assert parse_item_page(page) == {"name": "Lesser Jeweller's Orb", "drop_level": 25,
                                     "text": ["Sets a Skill Gem to have 3 Support Gem Sockets"]}


def test_parse_detail_splits_tags_and_handles_a_bare_page():
    assert cc.parse_detail(card_page({"DropLevel": "5", "Class": "Stackable Currency", "Tags": "currency_shard, currency",
                                      "Type": "Metadata/Items/Currency/X"})) == {
        "drop_level": 5, "item_class": "Stackable Currency", "tags": ["currency_shard", "currency"],
        "type": "Metadata/Items/Currency/X"}
    assert cc.parse_detail("<html></html>") == {"drop_level": None, "item_class": None, "tags": [], "type": None}


# -- collect --------------------------------------------------------------------------------------------------

def test_collect_builds_one_record_per_item(records):
    assert len(records) == 18
    counts = {c: sum(1 for r in records.values() if r["category"] == c) for c in
              ("currency", "essence", "splinter", "catalyst", "omen", "augment")}
    assert counts == {"currency": 8, "essence": 3, "splinter": 1, "catalyst": 1, "omen": 3, "augment": 2}
    assert "Mystery_Leaguestone" not in records          # a tab the catalog does not map


def test_collect_records_have_both_languages_details_and_sources(records):
    chaos = records["Greater_Chaos_Orb"]
    assert (chaos["name_zh_tw"], chaos["min_modifier_level"], chaos["drop_level"]) == ("高階混沌石", 35, 35)
    assert chaos["type"] == "Metadata/Items/Currency/CurrencyRerollRare2" and chaos["tags"] == ["currency"]
    assert chaos["url_en"] == "https://poe2db.tw/us/Greater_Chaos_Orb" and chaos["url_zh_tw"].endswith("/tw/Greater_Chaos_Orb")
    assert chaos["fetched_at"] and chaos["detail_fetched_at"]
    assert records["Exalted_Orb"]["drop_level"] == 2                  # the older table layout
    assert records["Flesh_Catalyst"]["name_zh_tw"] is None
    assert records["Omen_of_Whittling"]["effects_zh_tw"] == ["此物品在你的背包裡啟動時，你的下一個混沌石會移除最低等級的詞綴"]
    assert records["Runic_Alloy"]["also_in"] == ["essence"]


def test_collect_reuses_stored_details_and_reads_only_new_item_pages(tmp_path, records):
    reuse = {slug: r for slug, r in records.items() if slug != "Chaos_Orb"}
    site = CurrencySite()
    fresh, summary = cc.collect(currency_spec(), fetch=site, cache_dir=tmp_path / "again", reuse=reuse)
    item_calls = [u for u in site.calls if not u.endswith(("Stackable_Currency", "Omen", "Augment"))]
    assert item_calls == ["https://poe2db.tw/us/Chaos_Orb"]
    assert (summary["item_pages_read"], summary["item_pages_reused"]) == (1, 17)
    assert {r["slug"]: r["drop_level"] for r in fresh}["Desert_Rune"] == 15


def test_collect_survives_a_missing_item_page(tmp_path):
    pages = site_pages()
    del pages["https://poe2db.tw/us/Breach_Splinter"]
    records, summary = cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path)
    splinter = next(r for r in records if r["slug"] == "Breach_Splinter")
    assert (splinter["drop_level"], splinter["detail_fetched_at"]) == (None, None)
    assert summary["item_pages_failed"] == ["Breach_Splinter"]


def test_collect_refuses_too_many_missing_item_pages(tmp_path):
    pages = {url: html for url, html in site_pages().items()
             if url.endswith(("Stackable_Currency", "Omen", "Augment"))}
    with pytest.raises(cc.CurrencyBuildError, match="item page read"):
        cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path)


def test_collect_refuses_a_listing_that_no_longer_parses(tmp_path):
    pages = site_pages()
    pages["https://poe2db.tw/us/Omen"] = "<html><body>moved</body></html>"
    with pytest.raises(cc.CurrencyBuildError, match="0 omen items"):
        cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path)


def test_collect_refuses_a_chinese_outage(tmp_path):
    pages = {url: html for url, html in site_pages().items() if "/tw/" not in url}
    pages.update({url.replace("/us/", "/tw/"): "<html></html>" for url in cc.listing_urls(currency_spec())
                  if "/us/" in url})
    with pytest.raises(cc.CurrencyBuildError, match="Chinese name"):
        cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path)


def test_collect_offline_without_a_cache_says_so(tmp_path):
    with pytest.raises(cc.CurrencyBuildError, match="not cached"):
        cc.collect(currency_spec(), fetch=CurrencySite(), cache_dir=tmp_path, offline=True)


def test_pending_pages_counts_what_a_run_still_needs(tmp_path, records):
    spec = currency_spec()
    assert cc.pending_pages(spec, tmp_path / "empty") is None
    cc.collect(spec, fetch=CurrencySite(), cache_dir=tmp_path / "run")
    assert cc.pending_pages(spec, tmp_path / "run") == 0
    (tmp_path / "run" / "items" / "Chaos_Orb.html").unlink()
    assert cc.pending_pages(spec, tmp_path / "run") == 1
    assert cc.pending_pages(spec, tmp_path / "run", reuse={"Chaos_Orb": records["Chaos_Orb"]}) == 0


def test_write_and_read_back(tmp_path, records):
    spec = currency_spec()
    cc.write(spec, tmp_path, list(records.values()))
    assert [r["slug"] for r in cc.read_records(spec, tmp_path)] == list(records)
    assert cc.read_records(spec, tmp_path / "nowhere") == []


def test_main_writes_nothing_when_offline_without_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cc, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cc, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(cc, "collect", lambda *a, **k: (_ for _ in ()).throw(cc.CurrencyBuildError("not cached")))
    assert cc.main(["--offline"]) == 1
    assert "nothing was written" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_main_prints_a_summary(tmp_path, monkeypatch, capsys, records):
    monkeypatch.setattr(cc, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cc, "collect", lambda *a, **k: (list(records.values()), {
        "records": 18, "item_pages_read": 18, "item_pages_reused": 0, "item_pages_failed": []}))
    assert cc.main([]) == 0
    out = capsys.readouterr().out
    assert "currency: 8" in out and "records 18" in out
    assert (tmp_path / "data" / "currency" / "currency.jsonl").exists()


# -- review findings (2026-11-17) ----------------------------------------------------------------------------

def test_an_item_page_without_facts_does_not_count_as_read(tmp_path):
    pages = {url: ("<html><body>new layout</body></html>" if "/us/" in url and not url.endswith(
        ("Stackable_Currency", "Omen", "Augment")) else html) for url, html in site_pages().items()}
    with pytest.raises(cc.CurrencyBuildError, match="item page read"):
        cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path)
    record = cc.add_details({"slug": "X"}, cc.parse_detail("<html></html>"), "2026-11-17")
    assert (record["drop_level"], record["detail_fetched_at"]) == (None, None)


def test_a_failed_item_page_keeps_the_earlier_fields(tmp_path, records):
    pages = site_pages()
    del pages["https://poe2db.tw/us/Breach_Splinter"]
    fresh, summary = cc.collect(currency_spec(), fetch=CurrencySite(pages), cache_dir=tmp_path / "refresh",
                                fallback=records)
    splinter = next(r for r in fresh if r["slug"] == "Breach_Splinter")
    assert splinter["drop_level"] == 66 and splinter["detail_fetched_at"] == records["Breach_Splinter"]["detail_fetched_at"]
    assert summary["item_pages_failed"] == ["Breach_Splinter"]


def test_an_entry_with_an_unusual_slug_is_skipped(capsys):
    assert parse(entry("Odd Slug&x", "Odd")) is None
    assert "unusual slug" in capsys.readouterr().err


def test_the_required_level_is_the_level_not_the_first_number():
    row = parse(entry("R", "Rune", requires='Requires: <span class="colourDefault">20 Str</span>'))
    assert row["requires_level"] is None
    zh = parse(entry("R", "符文", requires='需求: <span class="colourDefault">等級 15</span>'))
    assert zh["requires_level"] == 15


def test_the_chinese_entry_with_the_most_lines_wins():
    stub = {**parse(entry("X", "X 石")), "category": None}
    full = {**parse(entry("X", "X 石", (stack("堆疊數量"),), (("explicitMod", "做 x"),))), "category": None}
    english = [{**parse(entry("X", "X Orb", lines=(("explicitMod", "does x"),))), "category": "currency"}]
    assert cc.merge_entries(english, [stub, full])[0]["effects_zh_tw"] == ["做 x"]


def test_pending_pages_leaves_out_pages_that_failed_in_the_run(tmp_path):
    spec = currency_spec()
    cc.collect(spec, fetch=CurrencySite(), cache_dir=tmp_path)
    (tmp_path / "items" / "Chaos_Orb.html").unlink()
    assert cc.pending_pages(spec, tmp_path, failed={"https://poe2db.tw/us/Chaos_Orb"}) == 0


def test_drop_level_needs_plain_digits():
    assert drop_level({"DropLevel": "²"}) is None and drop_level({"DropLevel": "12"}) == 12


def test_main_fetches_the_listings_again_and_item_pages_only_when_asked(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    for folder in ("listings", "items"):
        (cache / folder).mkdir(parents=True)
        (cache / folder / "old.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cc, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cc, "CACHE_DIR", cache)
    seen = {}
    monkeypatch.setattr(cc, "collect", lambda spec, **k: seen.update(k) or ([], {
        "records": 0, "item_pages_read": 0, "item_pages_reused": 0, "item_pages_failed": []}))
    cc.main([])
    assert not (cache / "listings").exists() and (cache / "items" / "old.html").exists()
    cc.main(["--refresh-item-pages"])
    assert not (cache / "items").exists() and seen["reuse"] == {}
