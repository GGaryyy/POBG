"""The pieces and strings of search_string.py, on hand-made modifier wordings."""

from __future__ import annotations

from src.tools import search_string as ss


def pieces(line: str, minimum: int = 4) -> list[str]:
    return list(ss._pieces(line, minimum))


# -- pieces --------------------------------------------------------------------------------------------------

def test_english_pieces_are_whole_words_without_numbers_or_symbols():
    found = pieces("# to maximum life")
    assert "maximum life" in found and "maximum" in found and "life" in found
    assert not any(p in found for p in ("to m", "aximum", "o max", "# to"))
    assert all("#" not in p and "+" not in p for p in pieces("+#% to fire resistance (#)"))


def test_english_pieces_keep_a_possessive_and_skip_short_and_function_words():
    found = pieces("monster's damage from crits")
    assert "monster's" in found and "from" not in found and "damage from crits" in found
    assert "from crits" not in found and "monster's damage from" not in found      # no "from" at an edge
    assert all(len(p) >= 4 for p in pieces("a to of life"))


def test_chinese_pieces_are_runs_of_chinese_without_particles_at_the_edges():
    found = pieces("怪物身上的詛咒具有#%更少效果", minimum=2)
    assert "詛咒" in found and "更少效果" in found
    assert not any(p[0] in ss.CJK_EDGE or p[-1] in ss.CJK_EDGE for p in found)
    assert "上的" not in found and "%更" not in found


def test_shortest_piece_avoids_every_other_modifier():
    others = [("b", ["#% increased maximum life"]), ("c", ["# to maximum mana"])]
    piece, clashes = ss.shortest_piece(["# to maximum life"], others, 4)
    assert (piece, clashes) == ("to maximum life", [])


def test_shortest_piece_reports_what_it_also_matches_when_nothing_is_unique():
    others = [("b", ["fire damage taken"]), ("c", ["more fire damage"])]
    piece, clashes = ss.shortest_piece(["fire damage"], others, 4)
    assert (piece, clashes) == ("fire damage", ["fire damage taken", "more fire damage"])


def test_shortest_piece_with_no_lines_is_none():
    assert ss.shortest_piece([], [("b", ["life"])], 4) == (None, [])


def test_tiers_that_differ_only_in_numbers_share_a_piece():
    # the wording is the template (numbers as #): the piece is found in every tier's own text
    piece, _ = ss.shortest_piece(["monsters deal #% of damage as extra fire"],
                                 [("b", ["#% increased waystones found in area"])], 4)
    tiers = ["monsters deal (5—9)% of damage as extra fire", "monsters deal (15—19)% of damage as extra fire"]
    assert piece == "extra fire" and all(piece in tier for tier in tiers)


def test_several_words_come_before_a_shorter_single_word():
    piece, _ = ss.shortest_piece(["# to maximum life"], [("b", ["# to maximum mana"])], 4)
    assert piece == "maximum life"                                  # not "life"


def test_pieces_never_cross_a_line_break():
    found = pieces("#% increased armour\nadds # to # physical damage")
    assert found and not any("\n" in p for p in found) and "physical damage" in found


def test_a_chinese_piece_at_a_run_edge_comes_before_one_inside_it():
    # 暴擊時 ends the first run; 物遭暴 sits inside it
    piece, _ = ss.shortest_piece(["怪物遭暴擊時，減少#%承受的額外傷害"], [("b", ["怪物額外傷害"])], 2)
    assert piece == "怪物遭"


# -- packing -------------------------------------------------------------------------------------------------

def test_pack_joins_pieces_in_quotes_and_splits_wanted_gear():
    strings, left = ss.pack(["alpha", "beta", "gamma"], 14, leave_out=False)
    assert strings == ['"alpha|beta"', '"gamma"'] and left == []
    assert all(len(s) <= 14 for s in strings)


def test_pack_keeps_pieces_to_leave_out_in_one_string():
    strings, left = ss.pack(["alpha", "beta", "gamma"], 14, leave_out=True)
    assert strings == ['"!alpha|beta"'] and left == ["gamma"]


def test_pack_reports_a_piece_longer_than_the_limit():
    strings, left = ss.pack(["a" * 20], 10, leave_out=False)
    assert strings == [] and left == ["a" * 20]
    strings, left = ss.pack(["abc", "a" * 20, "def"], 12, leave_out=False)     # also after another piece
    assert strings == ['"abc"', '"def"'] and left == ["a" * 20]


def test_names_takes_the_words_without_numbers():
    assert ss._names("monsters deal of damage as extra fire", "monsters deal #% of damage as extra fire")
    assert ss._names("extra fire", "monsters deal #% of damage as extra fire")
    assert not ss._names("extra cold", "monsters deal #% of damage as extra fire")
    assert ss._names("額外火焰", "怪物造成等同於傷害#%的額外火焰傷害")
    assert not ss._names("冰冷", "怪物造成等同於傷害#%的額外火焰傷害")


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
