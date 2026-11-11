"""Gear bases, uniques and modifiers from item class pages (src/scrapers/collect_items.py)."""

import json

import pytest

from src.scrapers import collect_items as ci
from src.scrapers.common import read_jsonl
from tests.item_support import (
    ARMOUR_BASES,
    ARMOUR_MODS,
    BOW_BASES,
    BOW_MODS,
    BOW_UNIQUES,
    SOCKETABLES,
    ItemSite,
    class_page,
    item_spec,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def spec():
    return item_spec()


def run(spec, site=None):
    return ci.collect(spec, site or ItemSite())


# -- one page ----------------------------------------------------------------------------------

def test_bases_are_parsed_with_properties_requirements_and_implicits(spec):
    page = ci.parse_class_page(class_page("en", bases=BOW_BASES), spec, "Bows")
    assert [b["slug"] for b in page.bases] == ["Shortbow", "Dualstring_Bow"]
    short, dual = page.bases
    assert short == {"slug": "Shortbow", "name": "Shortbow", "properties": ["Physical Damage: 7-14", "Attacks per Second: 1.25"],
                     "requirements": "Requires: Level 5, 12 Dex", "implicits": [], "effects": []}
    assert dual["implicits"] == ["+50% Surpassing chance to fire an additional Arrow"]


def test_uniques_are_parsed_with_base_and_every_modifier_line(spec):
    page = ci.parse_class_page(class_page("zh-tw", uniques=BOW_UNIQUES), spec, "Bows")
    assert page.uniques == [{"slug": "Quill_Rain", "name": "驟雨之弦", "base": "短弓", "requirements": "需求: 等級 5, 12 敏捷",
                             "implicits": [], "mods": ["增加100%攻擊速度", "40%更少攻擊傷害"]}]


def test_modifier_object_is_read_with_affix_family_level_text_and_tags(spec):
    page = ci.parse_class_page(class_page("en", mods=BOW_MODS, socketables=SOCKETABLES), spec, "Bows")
    assert page.has_mod_object and page.label == "Bows"
    assert {g: len(rows) for g, rows in page.mods.items()} == {"normal": 6, "desecrated": 1, "corrupted": 1, "essence": 0,
                                                               "perfect_essence": 0, "socketable": 1}
    heated = page.mods["normal"][0]
    assert heated == {"group": "normal", "affix": "prefix", "name": "Heated", "source_slug": None, "level": 1,
                      "family": "FireDamage", "text": "Adds (1—2) to (3—5) Fire Damage", "tags": ["fire", "attack"]}
    assert page.mods["normal"][3]["affix"] == "suffix" and page.mods["corrupted"][0]["affix"] is None
    rune = page.mods["socketable"][0]
    assert rune["name"] == "Lesser Desert Rune" and rune["source_slug"] == "Lesser_Desert_Rune" and rune["text"] == "Adds 4 to 6 Fire Damage"


def test_prefix_and_suffix_come_from_the_generation_id_in_every_language(spec):
    page = ci.parse_class_page(class_page("zh-tw", mods=BOW_MODS), spec, "Bows")      # `gen` names are Chinese there
    assert [m["affix"] for m in page.mods["normal"]] == ["prefix", "prefix", "prefix", "suffix", "suffix", "suffix"]


def test_weights_are_never_kept(spec):
    page = ci.parse_class_page(class_page("en", mods=BOW_MODS), spec, "Bows")
    assert all("weight" not in key.lower() and "drop" not in key.lower() for row in page.mods["normal"] for key in row)


@pytest.mark.parametrize("which", ["bases", "uniques"])
def test_tab_count_that_differs_from_the_cards_is_markup_drift(spec, which):
    html = (class_page("en", bases=BOW_BASES, base_count=3) if which == "bases"
            else class_page("en", uniques=BOW_UNIQUES, unique_count=5))
    found = 2 if which == "bases" else 1
    with pytest.raises(ci.ItemCollectionError, match=f"lists {3 if which == 'bases' else 5} items but {found} cards parsed"):
        ci.parse_class_page(html, spec, "Bows")


NEW_LAYOUT_UNIQUE = (
    '<div class="col"><div class="d-flex"><div class="flex-grow-1 ms-2"><div class="UniqueItem">'
    '<a class="UniqueItem" href="Apron_of_Emiran">Apron of Emiran</a> <span class="uniqueTypeLine">Hermit Garb</span></div>'
    '<div><div class="property">Body Armours</div><div class="requirements">Requires:  <span>Level 40</span></div>'
    '<div class="implicitMod">Grants Skill: Level 19 Geyser</div><div class="explicitMod">+(60—80) to maximum Life</div></div></div></div></div>')


def pane(pane_id, title, cards, count):
    return (f'<li><a class="nav-link" href="#{pane_id}">{title} /{count}</a></li>',
            f'<div class="tab-pane" id="{pane_id}"><div class="row">{cards}</div></div>')


def test_both_unique_card_layouts_are_read(spec):
    from tests.item_support import _unique_card
    tab, body = pane("ArmourUnique", "Unique", _unique_card(BOW_UNIQUES[0], "en") + NEW_LAYOUT_UNIQUE, 2)
    page = ci.parse_class_page(f'<ul class="nav">{tab}</ul>{body}', spec, "Body_Armours")
    newer = page.uniques[1]
    assert newer == {"slug": "Apron_of_Emiran", "name": "Apron of Emiran", "base": "Hermit Garb", "requirements": "Requires: Level 40",
                     "implicits": ["Grants Skill: Level 19 Geyser"], "mods": ["+(60—80) to maximum Life"]}


def test_a_whitespace_text_node_before_the_name_falls_back_to_the_link_text(spec):
    card = NEW_LAYOUT_UNIQUE.replace('href="Apron_of_Emiran">Apron of Emiran</a>',
                                     'href="Apron_of_Emiran">  <b>Apron of Emiran</b></a>')
    tab, body = pane("ArmourUnique", "Unique", card, 1)
    page = ci.parse_class_page(f'<ul class="nav">{tab}</ul>{body}', spec, "Body_Armours")
    assert page.uniques[0]["name"] == "Apron of Emiran"


def test_every_pure_unique_pane_is_collected_and_mixed_reference_panes_are_not(spec):
    from tests.item_support import _base_card, _unique_card
    first = pane("GlovesUnique", "Unique", _unique_card(BOW_UNIQUES[0], "en"), 1)
    second = pane("FistsUniques", "Fists", NEW_LAYOUT_UNIQUE, 1)
    mixed = pane("GloveRef", "Ref", _unique_card(BOW_UNIQUES[0], "en") + _base_card(BOW_BASES[0], "en"), 9)
    html = f'<ul class="nav">{first[0]}{second[0]}{mixed[0]}</ul>{first[1]}{second[1]}{mixed[1]}'
    page = ci.parse_class_page(html, spec, "Gloves")
    assert [u["slug"] for u in page.uniques] == ["Quill_Rain", "Apron_of_Emiran"] and page.bases == []


def test_page_without_a_modifier_object_has_none(spec):
    page = ci.parse_class_page(class_page("en", bases=BOW_BASES), spec, "Bows")
    assert not page.has_mod_object and page.mods == {} and page.label is None


def test_broken_modifier_json_is_an_error(spec):
    html = "<html><script>new ModsView({\"normal\": [});</script></html>"
    with pytest.raises(ci.ItemCollectionError, match="not valid JSON"):
        ci.parse_class_page(html, spec, "Bows")


# -- the whole run ----------------------------------------------------------------------------

def test_run_joins_languages_and_pages(spec):
    records, summary = run(spec)
    bases = {b["slug"]: b for b in records["bases"]}
    assert set(bases) == {"Shortbow", "Dualstring_Bow", "Golden_Mantle", "Rusted_Cuirass"}
    short = bases["Shortbow"]
    assert short["name_zh_tw"] == "短弓" and short["properties_zh_tw"] == ["物理傷害: 7-14", "每秒攻擊次數: 1.25"]
    assert short["requires_level"] == 5 and short["requires"] == {"dex": 12} and short["item_class"] == "Bows"
    assert short["url_en"] == "https://poe2db.tw/us/Shortbow" and short["url_zh_tw"] == "https://poe2db.tw/tw/Shortbow"
    assert bases["Golden_Mantle"]["mod_page"] == "Body_Armours_str_dex_int"           # from the attribute page
    assert bases["Rusted_Cuirass"]["mod_page"] is None                                # listed on no modifier page
    quill = records["uniques"][0]
    assert quill["base_slug"] == "Shortbow" and quill["mods_zh_tw"] == ["增加100%攻擊速度", "40%更少攻擊傷害"]
    assert summary["bases"] == 4 and summary["uniques"] == 1 and summary["bases_without_mod_page"] == 1
    assert summary["modifiers"] == len(BOW_MODS) + len(SOCKETABLES) + len(ARMOUR_MODS)


def test_modifiers_get_tiers_per_family_with_tier_one_the_highest(spec):
    records, _ = run(spec)
    fire = sorted((m for m in records["modifiers"] if m["family"] == "FireDamage"), key=lambda m: m["tier"])
    assert [(m["name"], m["tier"], m["tiers"]) for m in fire] == [("Cremating", 1, 3), ("Burning", 2, 3), ("Heated", 3, 3)]
    assert fire[0]["name_zh_tw"] == "火化的" and fire[0]["text_zh_tw"] == "附加(62—84)至(95—145)火焰傷害"
    assert {m["mod_page"] for m in records["modifiers"] if m["family"] == "FireResistance"} == {"Body_Armours_str_dex_int"}


def test_class_registry_lists_modifier_pages_with_their_bases(spec):
    records, _ = run(spec)
    pages = {p["slug"]: p for p in records["classes"]["pages"]}
    assert set(pages) == {"Bows", "Body_Armours_str_dex_int"}
    armour = pages["Body_Armours_str_dex_int"]
    assert armour["label"] == "Body Armours" and armour["label_zh_tw"] == "胸甲"
    assert armour["attributes"] == ["str", "dex", "int"] and armour["bases"] == ["Golden_Mantle"]
    assert pages["Bows"]["attributes"] == []


def test_chinese_group_that_does_not_line_up_keeps_english_only(spec):
    site = ItemSite()
    shuffled = list(BOW_MODS)
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
    site.pages["https://poe2db.tw/tw/Bows"] = class_page("zh-tw", bases=BOW_BASES, uniques=BOW_UNIQUES, mods=shuffled,
                                                         socketables=SOCKETABLES)
    records, summary = run(spec, site)
    normal = [m for m in records["modifiers"] if m["mod_page"] == "Bows" and m["group"] == "normal"]
    assert all(m["text_zh_tw"] is None for m in normal) and summary["mod_groups_english_only"] == 1
    desecrated = next(m for m in records["modifiers"] if m["group"] == "desecrated")
    assert desecrated["text_zh_tw"] == "增加(12—23)%攻擊範圍效果"                  # other groups still joined


def test_missing_chinese_card_is_counted(spec):
    site = ItemSite()
    site.pages["https://poe2db.tw/tw/Body_Armours"] = class_page("zh-tw", bases=ARMOUR_BASES[:1])
    records, summary = run(spec, site)
    rusted = next(b for b in records["bases"] if b["slug"] == "Rusted_Cuirass")
    assert rusted["name_zh_tw"] is None and summary["bases_zh_missing"] == 1


def test_modifier_page_without_its_object_aborts(spec):
    site = ItemSite()
    site.pages["https://poe2db.tw/us/Bows"] = class_page("en", bases=BOW_BASES, uniques=BOW_UNIQUES)
    with pytest.raises(ci.ItemCollectionError, match="Bows: no modifier object"):
        run(spec, site)


@pytest.mark.parametrize("key, value, message", [
    ("bases", 10, "only 4 bases parsed, below expect_min=10"),
    ("uniques", 2, "only 1 uniques parsed"),
    ("modifiers", 999, "only 11 modifiers parsed"),
])
def test_validation_refuses_too_few_records(key, value, message):
    spec = item_spec(**{key: value})
    records, summary = run(spec)
    with pytest.raises(ci.ItemCollectionError, match=message):
        ci.validate(records, summary, spec)


def test_validation_refuses_a_run_without_chinese_names():
    spec = item_spec(zh_ratio=0.9)
    site = ItemSite()
    for url in [u for u in site.pages if "/tw/" in u]:
        site.pages[url] = "<html></html>"
    records, summary = run(spec, site)
    with pytest.raises(ci.ItemCollectionError, match="0% of bases and uniques have a Chinese name"):
        ci.validate(records, summary, spec)


def test_validation_passes_and_reports_the_chinese_ratio(spec):
    records, summary = run(spec)
    ci.validate(records, summary, spec)
    assert summary["zh_name_ratio"] == 1.0


def test_only_selected_pages_are_requested(spec):
    site = ItemSite()
    records, _ = ci.collect(spec, site, slugs=["Bows"])
    assert sorted(site.calls) == ["https://poe2db.tw/tw/Bows", "https://poe2db.tw/us/Bows"]
    assert {b["slug"] for b in records["bases"]} == {"Shortbow", "Dualstring_Bow"}


def test_cache_is_written_and_read_offline(spec, tmp_path):
    site = ItemSite()
    ci.collect(spec, site, cache_dir=tmp_path)
    assert len(site.calls) == 6 and (tmp_path / "zh-tw" / "Bows.html").exists()

    def no_network(url):
        raise AssertionError(url)

    records, _ = ci.collect(spec, no_network, cache_dir=tmp_path, offline=True)
    assert len(records["bases"]) == 4


def test_offline_without_cache_is_an_error(spec, tmp_path):
    with pytest.raises(ci.ItemCollectionError, match="not cached and --offline was given"):
        ci.collect(spec, lambda url: "", cache_dir=tmp_path, offline=True)


def test_files_are_written_where_the_catalog_says(spec, tmp_path):
    records, _ = run(spec)
    paths = ci.write_records(spec, tmp_path, records)
    assert [p.relative_to(tmp_path).as_posix() for p in paths] == [
        "items/bases.jsonl", "items/uniques.jsonl", "items/modifiers.jsonl", "items/classes.json"]
    assert len(read_jsonl(tmp_path / "items" / "bases.jsonl")) == 4
    assert json.loads((tmp_path / "items" / "classes.json").read_text(encoding="utf-8"))["pages"][0]["slug"] == "Bows"
    assert all(b"\r\n" not in p.read_bytes() for p in paths)


def test_main_writes_nothing_when_validation_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ci, "load_spec", lambda: item_spec(bases=99))
    monkeypatch.setattr(ci, "fetch_html", lambda url, delay=0.0: ItemSite()(url))
    monkeypatch.setattr(ci, "PAGE_CACHE_DIR", tmp_path / "cache")
    assert ci.main(["--out-dir", str(tmp_path / "data")]) == 1
    assert "below expect_min=99" in capsys.readouterr().err and not (tmp_path / "data").exists()


def test_main_writes_the_files_and_a_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ci, "load_spec", lambda: item_spec())
    monkeypatch.setattr(ci, "fetch_html", lambda url, delay=0.0: ItemSite()(url))
    monkeypatch.setattr(ci, "PAGE_CACHE_DIR", tmp_path / "cache")
    assert ci.main(["--out-dir", str(tmp_path / "data")]) == 0
    out = capsys.readouterr().out
    assert "bases: 4" in out and (tmp_path / "data" / "items" / "modifiers.jsonl").exists()


def test_one_family_with_several_modifiers_gets_tiers_per_modifier():
    rows = [{"group": "normal", "affix": "suffix", "family": "GemLevel", "level": lvl, "text": text}
            for lvl, text in ((5, "+1 to Level of all Minion Skills"), (45, "+2 to Level of all Minion Skills"),
                              (10, "+1 to Level of all Spell Skills"))]
    tiered = ci._with_tiers(rows)
    assert [(r["tier"], r["tiers"]) for r in tiered] == [(2, 2), (1, 2), (1, 1)]
    assert ci.modifier_template("+(10—15)% to Fire Resistance") == ci.modifier_template("+45% to fire resistance") == "#% to fire resistance"
