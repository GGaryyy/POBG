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


def others_of(*lines: str) -> list[str]:
    return [form for line in lines for form in ss.shown(line)]


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
    four = [c for c in found if len(c) == 4]
    assert four[0] == "gth$" and "stre" in four                       # tied to the end first
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
    assert not any(hits(found.piece, line) for line in others)


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
    assert found.clashes == [] and found.shared == ["#% increased attack speed"]
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
    assert found.piece == "fir" and found.clashes == ['fire "y"']          # the shortest of the equal ones


def test_no_piece_when_the_line_has_too_few_letters():
    assert ss.best_piece(tiers_of("+(1—2) a"), others_of("ice"), 3) == ss.Found(None)


def test_modifier_names_and_item_text_are_other_lines():
    found = ss.best_piece(tiers_of("+(5—8) to Dexterity"), others_of("of the Mongoose", "Dexterity: 12"), 3)
    assert not hits(found.piece, "dexterity: 12") and not hits(found.piece, "of the mongoose")
    text = ss.item_text([{"name": "Shortbow", "implicits": ["+50% Surpassing chance"], "properties": ["Physical Damage: 7-14"]}],
                        [{"name": "Quill Rain"}], "")
    assert text == ["Shortbow", "+50% Surpassing chance", "Physical Damage: 7-14", "Quill Rain"]


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
    assert "too short" in ss._avoided("e", entries)[1]
    assert ss._avoided("frozen solid", entries)[1] == "no waystone modifier has these words"


def test_names_takes_the_words_without_numbers():
    assert ss._names("monsters deal of damage as extra fire", "monsters deal #% of damage as extra fire")
    assert not ss._names("extra cold", "monsters deal #% of damage as extra fire")
    assert ss._names("額外火焰", "怪物造成等同於傷害#%的額外火焰傷害")
