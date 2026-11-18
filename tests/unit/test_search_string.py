"""The lines, pieces and strings of search_string.py, on hand-made modifier wordings. Every piece
is checked the way the game uses it: a regular expression, line by line, in any case."""

from __future__ import annotations

import re

import pytest

from src.tools import search_string as ss


def hits(regex: str, line: str) -> bool:
    return bool(re.search(regex, line, re.IGNORECASE))


def tiers_of(*lines_per_tier: str) -> list[list[list[str]]]:
    """Tiers of a one-line modifier, each as the item shows it."""
    return [[ss.shown(line)] for line in lines_per_tier]


def others_of(*lines: str, source: str = "modifier") -> list[tuple[str, str]]:
    return [(source, form) for line in lines for form in ss.shown(line)]


# -- lines ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line, forms", [
    ("+(31—33) to Strength", ["+31 to strength", "+33 to strength"]),
    ("Adds (37—55) to (63—94) Physical Damage", ["adds 37 to 63 physical damage", "adds 55 to 94 physical damage"]),
    ("35% increased Movement Speed", ["35% increased movement speed"]),
    ("(1.5—2.5)% of Damage Leeched", ["1.5% of damage leeched", "2.5% of damage leeched"]),
    ("(-10—-3)% maximum Player Resistances", ["-10% maximum player resistances", "-3% maximum player resistances"]),
    ("附加(9—14)至(15—22)火焰傷害", ["附加9至15火焰傷害", "附加14至22火焰傷害"]),
])
def test_a_line_is_shown_at_the_low_and_the_high_end_of_its_ranges(line, forms):
    assert ss.shown(line) == forms


def test_a_hybrid_modifier_is_two_lines():
    assert ss.split_lines("(15—19)% increased Physical Damage\n+(16—20) to Accuracy Rating") == [
        "(15—19)% increased Physical Damage", "+(16—20) to Accuracy Rating"]
    assert ss.split_lines(None) == [] and ss.split_lines(" \n ") == []


def test_the_search_form_marks_each_number_once():
    assert ss.search_form("adds 37 to 63 physical damage") == "adds # to # physical damage"
    assert ss.search_form("1.5% of damage leeched") == "#% of damage leeched"
    assert ss.search_form("+31 to strength") == "+# to strength"


def test_a_piece_writes_numbers_as_digits_and_escapes_special_characters():
    assert ss.to_regex("+# to strength") == r"\+\d+ to strength"
    assert ss.to_regex("# (a.b)?") == r"\d+ \(a\.b\)\?"
    assert ss.to_regex("火焰傷") == "火焰傷"


# -- candidates ----------------------------------------------------------------------------------------------

def test_candidates_are_valid_shortest_first_and_tied_to_the_end_first_at_equal_length():
    found = ss.candidates(["+31 to strength"], 3)
    assert all(re.compile(c) for c in found)
    assert [len(c) for c in found] == sorted(len(c) for c in found)
    tied = ss.candidates(["+31 to strength"], 3, anchor="$")
    assert tied[0] == "gth$" and all(c.endswith("$") for c in tied)
    assert all(c.startswith("^") and not c.endswith("$") for c in ss.candidates(["+31 to strength"], 3, anchor="^"))
    assert not any(c.startswith("^") or c.endswith("$") for c in ss.candidates(["+31 to strength"], 3, anchor=""))
    assert r"\+\d+ to strength$" in found and r"^\+\d+ to strength$" in found
    assert not any(c.strip("^$") != c.strip("^$").strip() for c in found)     # no space at an edge


def test_candidates_hold_enough_letters_and_never_a_quote_or_bang():
    assert not any('"' in c or "!" in c for c in ss.candidates(['say "hi"! now'], 3))
    assert all(len(ss.LETTER_RE.findall(c.replace(r"\d+", ""))) >= 3 for c in ss.candidates(["+31 to strength"], 3))
    assert all(len(ss.LETTER_RE.findall(c.replace(r"\d+", ""))) >= 2 for c in ss.candidates(["增加35%移動速度"], 2))


# -- the best piece ------------------------------------------------------------------------------------------

def test_the_piece_matches_every_tier_and_no_other_line():
    tiers = tiers_of("Adds (3—4) to (6—7) Physical Damage", "Adds (37—55) to (63—94) Physical Damage")
    others = others_of("(170—179)% increased Physical Damage", "Physical Damage: 13-18", "Adds (2—3) to (4—5) Fire Damage")
    found = ss.best_piece(tiers, others, 3)
    assert found.clashes == [] and found.piece
    assert all(hits(found.piece, form) for tier in tiers for form in tier[0])
    assert not any(hits(found.piece, line) for _, line in others)


def test_adds_physical_damage_never_matches_the_weapon_property_line():
    found = ss.best_piece(tiers_of("Adds (37—55) to (63—94) Physical Damage"),
                          others_of("Physical Damage: 13-18", "(170—179)% increased Physical Damage"), 3)
    assert not hits(found.piece, "physical damage: 13-18") and not hits(found.piece, "170% increased physical damage")


def test_two_chinese_modifiers_get_different_pieces():
    added = ss.best_piece(tiers_of("附加(37—55)至(63—94)物理傷害"), others_of("增加(170—179)%物理傷害", "物理傷害: 13-18"), 2)
    more = ss.best_piece(tiers_of("增加(170—179)%物理傷害"), others_of("附加(37—55)至(63—94)物理傷害", "物理傷害: 13-18"), 2)
    assert added.piece != more.piece and not added.clashes and not more.clashes
    assert not hits(added.piece, "增加170%物理傷害") and not hits(more.piece, "附加37至63物理傷害")
    assert not hits(added.piece, "物理傷害: 13-18") and not hits(more.piece, "物理傷害: 13-18")


def test_the_same_wording_elsewhere_is_shared_not_a_clash():
    tiers = tiers_of("(26—28)% increased Attack Speed")
    others = others_of("(5—7)% increased Attack Speed", "+(16—20) to Accuracy Rating", "(10—15)% increased Attack Damage")
    found = ss.best_piece(tiers, others, 3)
    assert found.clashes == [] and found.shared == [{"line": "#% increased attack speed", "source": "modifier"}]
    assert not hits(found.piece, "10% increased attack damage")


def test_a_hybrid_modifier_is_found_by_its_unshared_line():
    tiers = [[ss.shown("(15—19)% increased Physical Damage"), ss.shown("+(16—20) to Accuracy Rating")]]
    others = others_of("(170—179)% increased Physical Damage", "+(30—40) to Strength")
    found = ss.best_piece(tiers, others, 3)
    assert found.shared == [] and hits(found.piece, "+16 to accuracy rating")
    assert not hits(found.piece, "170% increased physical damage")


def test_when_every_piece_clashes_the_fewest_clashes_are_reported():
    # a quote never goes into a piece, so only "fire" is left, and another line has it
    found = ss.best_piece(tiers_of('fire "x"'), others_of('fire "y"', "ice"), 3)
    assert found.piece == "^fir" and found.clashes == ['fire "y"'] and found.clash_count == 1


def test_the_clash_count_is_counted_before_the_list_is_cut():
    others = others_of(*(f"z{chr(97 + i) * 2} common" for i in range(14)), 'q "y" common', "q stop")
    found = ss.best_piece(tiers_of('q "x" common'), others, 3)
    assert found.clash_count == 15 and len(found.clashes) == ss.MAX_SHOWN


def test_no_piece_when_the_line_has_too_few_letters():
    assert ss.best_piece(tiers_of("+(1—2) a"), others_of("ice"), 3) == ss.Found(None)


def test_modifier_names_and_item_text_are_other_lines():
    found = ss.best_piece(tiers_of("+(5—8) to Dexterity"), others_of("of the Mongoose", "Dexterity: 12"), 3)
    assert not hits(found.piece, "dexterity: 12") and not hits(found.piece, "of the mongoose")
    text = ss.item_text([{"name": "Shortbow", "implicits": ["+50% Surpassing chance"], "properties": ["Physical Damage: 7-14"]}],
                        [{"name": "Quill Rain", "mods": ["100% increased Attack Speed"]}], "")
    assert text == [("name", "Shortbow"), ("implicit", "+50% Surpassing chance"), ("property", "Physical Damage: 7-14"),
                    ("name", "Quill Rain"), ("unique", "100% increased Attack Speed")]


# -- the review's findings (0.15.2) ----------------------------------------------------------------------------

FIXED = ["Rarity: Normal", "Rarity: Magic", "Rarity: Rare", "Rarity: Unique", "Item Level: 80", "Quality: +20%",
         "Item Rarity: +40%", "Unidentified", "Requires: Level 65, 100 Dex", "Monster Pack Size: +20%"]


@pytest.mark.parametrize("line", ["(15—18)% increased Rarity of Items found", "+(5—8) to Dexterity",
                                  "+(1—5) to Level of all Melee Skills", "(10—15)% increased Parried Debuff Duration",
                                  "(20—30)% increased Pack size"])
def test_pieces_never_match_the_lines_every_item_shows(line):
    found = ss.best_piece(tiers_of(line), others_of(*FIXED, source="fixed"), 3)
    assert found.piece and not any(hits(found.piece, fixed) for fixed in FIXED)


def test_a_chinese_attribute_never_matches_the_requirement_line():
    found = ss.best_piece(tiers_of("+(31—33)點敏捷"), others_of("需求: 等級 65, 100 敏捷", source="fixed"), 2)
    assert not hits(found.piece, "需求: 等級 65, 100 敏捷") and hits(found.piece, "+31點敏捷")


def test_a_piece_tied_to_the_end_comes_before_a_shorter_free_one():
    found = ss.best_piece(tiers_of("abc def ghi"), others_of("xyz"), 3)
    assert found.piece == "ghi$" and not found.unanchored                 # "abc" is shorter and also clean
    found = ss.best_piece(tiers_of("abc def ghi"), others_of("xyz ghi"), 3)
    assert found.piece.endswith("$") and not hits(found.piece, "xyz ghi")


def test_a_free_piece_only_when_nothing_tied_to_an_end_is_clean_and_then_flagged():
    found = ss.best_piece(tiers_of('aaa "q" midd "q" bbb'), others_of("aaa xx", "yy bbb"), 3)
    assert found.piece == "idd" and found.unanchored


def test_a_line_in_the_data_notation_gives_no_piece_and_a_reason():
    found = ss.best_piece(tiers_of("minion area of effect +% [3,6]"), others_of("ice"), 3)
    assert found.piece is None and found.reason == ss.UNUSABLE
    assert ss.usable("+1000 to armour") and not ss.usable("+(10—20) to armour") and not ss.usable("x [3,6]")


@pytest.mark.parametrize("line, forms", [
    ("+(1,000—1,200) to Armour", ["+1000 to armour", "+1200 to armour"]),
    ("Requires: Level 5, 12 Dex", ["requires: level 5, 12 dex"]),
])
def test_thousands_are_joined_but_a_list_is_not(line, forms):
    assert ss.shown(line) == forms


def test_hybrid_lines_are_matched_up_by_wording_not_by_place():
    tiers = [[ss.shown("(15—19)% increased Physical Damage"), ss.shown("+(16—20) to Accuracy Rating")],
             [ss.shown("+(21—25) to Accuracy Rating"), ss.shown("(20—24)% increased Physical Damage")]]
    found = ss.best_piece(tiers, others_of("(170—179)% increased Physical Damage"), 3)
    assert found.piece and all(hits(found.piece, f) for f in ("+16 to accuracy rating", "+25 to accuracy rating"))
    assert ss.best_piece([[ss.shown("aaa one")], [ss.shown("bbb two")]], others_of("ice"), 3).reason == ss.TIERS_DIFFER


def test_shared_lines_say_where_they_come_from():
    found = ss.best_piece(tiers_of("(26—28)% increased Attack Speed"),
                          others_of("10% increased Attack Speed", source="implicit") + others_of("ice"), 3)
    assert found.shared == [{"line": "#% increased attack speed", "source": "implicit"}]
    named = ss.best_piece(tiers_of("(26—28)% increased Attack Speed"), others_of("5% increased Attack Speed", source="fixed"), 3)
    assert named.shared == []                                     # a fixed line is not something an item rolls


def test_a_decimal_number_is_written_so_that_it_matches():
    found = ss.best_piece(tiers_of("(1.5—2.5)% of Physical Damage Leeched as Life"), others_of("ice"), 3)
    assert all(hits(found.piece, f) for f in ("1.5% of physical damage leeched as life", "2.5% of physical damage leeched as life"))
    assert ss.to_regex("#% x", decimal=True) == r"[\d.]+% x"


# -- packing -------------------------------------------------------------------------------------------------

def test_pack_joins_pieces_in_quotes_and_splits_wanted_gear():
    strings, left = ss.pack(["alpha", "beta", "gamma"], 14, leave_out=False)
    assert strings == ['"alpha|beta"', '"gamma"'] and left == []


def test_pack_keeps_pieces_to_leave_out_in_one_string():
    strings, left = ss.pack(["alpha", "beta", "gamma"], 14, leave_out=True)
    assert strings == ['"!alpha|beta"'] and left == ["gamma"]


def test_pack_reports_a_piece_longer_than_the_limit():
    assert ss.pack(["a" * 20], 10, leave_out=False) == ([], ["a" * 20])
    strings, left = ss.pack(["abc", "a" * 20, "def"], 12, leave_out=False)
    assert strings == ['"abc"', '"def"'] and left == ["a" * 20]


# -- avoided waystone modifiers --------------------------------------------------------------------------------

def keyed(*families):
    return [((f"k{i}",), {"templates": lines, "templates_zh_tw": [], "tiers": [{"id": f"waystone_{i}", "lines": lines}]})
            for i, lines in enumerate(families, 1)]


def test_avoided_takes_an_id_a_whole_text_a_line_or_words():
    entries = keyed(["# less effect of curses on monsters", "#% more rarity of items found in this area"],
                    ["players are periodically cursed with enfeeble", "#% more waystones found in area"])
    whole = "(20—30)% less effect of Curses on Monsters / 10% more Rarity of Items found in this Area"
    for text in (whole, "waystone_1", "less effect of Curses on Monsters", "effect curses"):
        found, reason = ss._avoided(text, entries)
        assert reason is None and [k for k, _ in found] == [("k1",)], text
    assert ss._avoided("waystone_9", entries) == ([], "no waystone modifier has the id waystone_9")
    assert [k for k, _ in ss._avoided("Waystone_1", entries)[0]] == [("k1",)]           # any case
    assert ss.INPUT_PARTS.split("a / b") == ["a", "b"] and ss.INPUT_PARTS.split("damage/second") == ["damage/second"]
    assert "too short" in ss._avoided("e", entries)[1]
    assert ss._avoided("frozen solid", entries)[1] == "no waystone modifier has these words"


def test_names_takes_the_words_without_numbers():
    assert ss._names("monsters deal of damage as extra fire", "monsters deal #% of damage as extra fire")
    assert not ss._names("extra cold", "monsters deal #% of damage as extra fire")
    assert ss._names("額外火焰", "怪物造成等同於傷害#%的額外火焰傷害")
