import json

import pytest

from src.kg import stats
from src.kg.stats import (StatAtom, build_stat_index, learn_zh_templates, normalise_stat, parse_summary,
                          summarise_families, template_of)
from src.scrapers.common import read_jsonl, write_jsonl

pytestmark = pytest.mark.unit


# -- template_of ------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("12% increased Attack Speed", "#% increased Attack Speed"),
    ("(25—35)% increased Cold Damage", "#% increased Cold Damage"),
    ("(25 – 35)% x", "#% x"),
    ("(1.5—2.5)% and +3 and -4.5 and 12", "#% and # and # and #"),
    ("  Gain   5   Mana ", "Gain # Mana"),
    ("Immune to Chaos Damage", "Immune to Chaos Damage"),
    ("增加 20% 傷害", "增加 #% 傷害"),
    ("", ""),
])
def test_template_of(text, expected):
    assert template_of(text) == expected


# -- normalise_stat: one case per shape ------------------------------------------------------

CASES = [
    # text, shape/kind, value, family, parent_family
    ("12% increased Attack Speed", "increased", 12.0, "attack speed", "attack speed"),                       # pct
    ("(25—35)% increased Cold Damage", "increased", 25.0, "cold damage", "cold damage"),                    # pct range
    ("10% faster Cast Speed", "faster", 10.0, "cast speed", "cast speed"),                                  # pct
    ("5% reduced Mana Cost of Skills", "reduced", 5.0, "mana cost of skills", "mana cost of skills"),
    ("Minions deal 10% increased Damage", "increased", 10.0, "minions damage", "minions damage"),           # subject
    ("Skills have 10% less Cost", "less", 10.0, "skills cost", "skills cost"),                              # subject
    ("+5 to Strength", "flat", 5.0, "strength", "strength"),                                                # to
    ("+(10—20) to maximum Life", "flat", 10.0, "maximum life", "maximum life"),                             # to range
    ("-5% to Fire Resistance", "flat_percent", -5.0, "fire resistance", "fire resistance"),                 # to %
    ("Minions have +7% to all Elemental Resistances", "flat_percent", 7.0,
     "minions all elemental resistances", "minions all elemental resistances"),                             # subject_to
    ("15% chance to Poison on Hit", "chance", 15.0, "chance to poison on hit", "chance to poison on hit"),
    ("20% of Armour also applies to Fire Damage taken", "of", 20.0,
     "armour also applies to fire damage taken", "armour also applies to fire damage taken"),
    ("Gain Armour equal to 10% of your Strength", "gain", 10.0, "gain armour from your strength",
     "gain armour"),
    ("Damage Penetrates 5% Fire Resistance", "penetration", 5.0, "fire resistance penetration",
     "fire resistance penetration"),
    ("Regenerate 2% of Life per second", "regenerate", 2.0, "regenerate life per second", "regenerate life"),
    ("Gain 5 Mana per Enemy Killed", "gain", 5.0, "gain mana per enemy killed", "gain mana"),
    ("Damage 8% increased", "increased", 8.0, "damage", "damage"),                                          # trailing
    ("Attacks with Bows deal 8% increased Damage with Hits", "increased", 8.0,
     "attacks with bows damage with hits", "attacks"),                                                      # qualifier stripped
    ("Requires The Unseen Path", "requires", None, "requires the unseen path", "requires the unseen path"),
    ("Immune to Chaos Damage", "text", None, "immune to chaos damage", "immune to chaos damage"),           # fallback
    ("Maximum Life is 1", "text", 1.0, "maximum life is", "maximum life is"),                               # fallback + value
]


@pytest.mark.parametrize("text, kind, value, family, parent", CASES, ids=[c[0] for c in CASES])
def test_normalise_stat(text, kind, value, family, parent):
    atom = normalise_stat(text)
    assert (atom.kind, atom.value, atom.family, atom.parent_family) == (kind, value, family, parent)
    assert atom.text == text and atom.template == template_of(text)


def test_normalise_collapses_whitespace():
    atom = normalise_stat("  12%   increased   Attack  Speed ")
    assert atom.text == "12% increased Attack Speed" and atom.family == "attack speed"


def test_normalise_range_uses_lower_bound_and_template_hides_numbers():
    atom = normalise_stat("(25—35)% increased Cold Damage")
    assert atom.value == 25.0 and atom.template == "#% increased Cold Damage"


def test_same_stat_different_numbers_share_template_and_family():
    a, b = normalise_stat("12% increased Attack Speed"), normalise_stat("(5—9)% increased Attack Speed")
    assert (a.template, a.family) == (b.template, b.family)


def test_penetration_variants_agree():
    assert normalise_stat("Hits Penetrate 10% Cold Resistance").family == "cold resistance penetration"


def test_stat_atom_as_dict():
    atom = normalise_stat("+5 to Strength")
    assert isinstance(atom, StatAtom)
    assert atom.as_dict() == {"text": "+5 to Strength", "template": "# to Strength", "kind": "flat", "value": 5.0,
                              "family": "strength", "parent_family": "strength"}


def test_stat_atom_is_frozen():
    with pytest.raises(AttributeError):
        normalise_stat("+5 to Strength").kind = "x"


# -- learn_zh_templates ---------------------------------------------------------------------------

def node(en, zh, nid="n"):
    return {"id": nid, "stats": en, "stats_zh_tw": zh}


def test_learn_zh_majority_vote():
    nodes = [node(["12% increased Attack Speed"], ["攻擊速度增加 12%"]),
             node(["10% increased Attack Speed"], ["攻擊速度增加 10%"]),
             node(["8% increased Attack Speed"], ["攻速提高 8%"])]
    assert learn_zh_templates(nodes) == {"#% increased Attack Speed": "攻擊速度增加 #%"}


def test_learn_zh_tie_resolves_to_first_seen():
    nodes = [node(["12% increased Attack Speed"], ["甲 12%"]), node(["10% increased Attack Speed"], ["乙 10%"])]
    assert learn_zh_templates(nodes) == {"#% increased Attack Speed": "甲 #%"}


def test_learn_zh_number_signature_guard():
    nodes = [node(["10% increased Damage"], ["增加 20% 傷害"]),          # numbers differ: misaligned pair
             node(["+5 to Strength"], ["+5 力量"])]                       # leading '+' ignored in the signature
    learned = learn_zh_templates(nodes)
    assert learned == {"# to Strength": "# 力量"}
    assert "#% increased Damage" not in learned


def test_learn_zh_signature_ignores_number_order():
    nodes = [node(["Adds 3 to 5 Fire Damage"], ["附加 5 至 3 火焰傷害"])]
    assert learn_zh_templates(nodes) == {"Adds # to # Fire Damage": "附加 # 至 # 火焰傷害"}


def test_learn_zh_skips_unaligned_and_empty_nodes():
    nodes = [node(["a 1", "b 2"], ["甲 1"]),            # line count mismatch
             node([], ["x"]), node(["c 3"], []), {"id": "z"}]
    assert learn_zh_templates(nodes) == {}


# -- build_stat_index ---------------------------------------------------------------------------------

@pytest.fixture
def index_nodes():
    return [
        {"id": "1", "stats": ["12% increased Attack Speed", "+5 to Strength"], "stats_zh_tw": ["攻擊速度增加 12%", "+5 力量"]},
        {"id": "2", "stats": ["8% increased Attack Speed"], "stats_zh_tw": []},   # small node: no own zh
        {"id": "3", "stats": ["Immune to Chaos Damage"]},
        {"id": "4", "stats": None},
    ]


def test_build_stat_index_rows(index_nodes):
    rows, families = build_stat_index(index_nodes)
    assert [(r["node_id"], r["line"]) for r in rows] == [("1", 0), ("1", 1), ("2", 0), ("3", 0)]
    first, second, inherited, plain = rows
    assert first["text_zh_tw"] == "攻擊速度增加 12%" and first["template_zh_tw"] == "攻擊速度增加 #%"
    assert second["text_zh_tw"] == "+5 力量" and second["kind"] == "flat" and second["family"] == "strength"
    assert inherited["text_zh_tw"] is None                        # not aligned: no own text ...
    assert inherited["template_zh_tw"] == "攻擊速度增加 #%"        # ... but the learned template is inherited
    assert plain["kind"] == "text" and plain["template_zh_tw"] is None and plain["text_zh_tw"] is None
    assert set(first) >= {"node_id", "line", "text", "template", "kind", "value", "family", "parent_family",
                          "text_zh_tw", "template_zh_tw"}


def test_build_stat_index_families(index_nodes):
    _, families = build_stat_index(index_nodes)
    assert list(families)[0] == "attack speed"                   # sorted by count desc
    assert families["attack speed"]["count"] == 2
    assert families["attack speed"]["kinds"] == {"increased": 2}
    assert families["attack speed"]["examples"] == ["12% increased Attack Speed", "8% increased Attack Speed"]


def test_build_stat_index_empty():
    assert build_stat_index([]) == ([], {})


def test_summarise_families_caps_examples_and_dedupes():
    rows = [{"family": "f", "parent_family": "f", "kind": "flat", "text": t} for t in ("a", "a", "b", "c", "d")]
    fam = summarise_families(rows)["f"]
    assert fam["count"] == 5 and fam["examples"] == ["a", "b", "c"] and fam["kinds"] == {"flat": 5}


# -- parse_summary ---------------------------------------------------------------------------------------------

def test_parse_summary_numbers(index_nodes):
    rows, _ = build_stat_index(index_nodes)
    assert parse_summary(rows) == {
        "lines": 4, "parsed_ratio": 0.75, "zh_template_ratio": 0.75,
        "kinds": {"increased": 2, "flat": 1, "text": 1}}


def test_parse_summary_empty():
    assert parse_summary([]) == {"lines": 0, "parsed_ratio": 1.0, "zh_template_ratio": 0.0, "kinds": {}}


# -- main ---------------------------------------------------------------------------------------------------------------

def run_main(tmp_path, node_stats):
    nodes = tmp_path / "nodes.jsonl"
    write_jsonl(nodes, [{"id": str(i), "stats": [s], "stats_zh_tw": []} for i, s in enumerate(node_stats)])
    out, fam = tmp_path / "out" / "stats.jsonl", tmp_path / "out" / "fam.json"
    code = stats.main(["--nodes", str(nodes), "--out", str(out), "--families", str(fam)])
    return code, out, fam


def test_main_exit_1_when_parsed_ratio_too_low(tmp_path, capsys):
    code, out, fam = run_main(tmp_path, ["12% increased Damage", "Cannot be Stunned", "Immune to Fire", "Unique thing"])
    assert code == 1
    assert "regex drift" in capsys.readouterr().err
    assert not out.exists() and not fam.exists()


def test_main_writes_outputs_when_ratio_ok(tmp_path, capsys):
    lines = ["12% increased Damage", "+5 to Strength", "5% reduced Mana Cost of Skills", "10% faster Cast Speed",
             "Cannot be Stunned"]  # 4/5 = 0.8 == MIN_PARSED_RATIO is accepted
    code, out, fam = run_main(tmp_path, lines)
    assert code == 0
    assert [r["text"] for r in read_jsonl(out)] == lines
    families = json.loads(fam.read_text(encoding="utf-8"))
    assert families["damage"]["count"] == 1 and "strength" in families
    stdout = capsys.readouterr().out
    assert "parsed_ratio: 0.8" in stdout and "families: 5" in stdout


def test_min_parsed_ratio_constant():
    assert stats.MIN_PARSED_RATIO == 0.80


@pytest.mark.parametrize("text, family", [
    ("Damage Penetrates 5% of Fire Resistance", "fire resistance penetration"),   # optional "of"
    ("Damage Penetrates 5% Fire Resistance", "fire resistance penetration"),
    ("+3 to Dexterity per 10 Dexterity", "dexterity per # dexterity"),            # numbers in the family become #
    ("1% increased Damage per 5 Dexterity", "damage per # dexterity"),
])
def test_family_numbers_normalised_and_penetration_of(text, family):
    assert normalise_stat(text).family == family


def test_families_with_different_embedded_numbers_merge():
    a = normalise_stat("1% increased Damage per 5 Dexterity")
    b = normalise_stat("2% increased Damage per 10 Dexterity")
    assert a.family == b.family == "damage per # dexterity" and a.parent_family == "damage"


# -- family zh-TW names ---------------------------------------------------------------------------------

def _row(family, zh):
    return {"family": family, "parent_family": family, "kind": "increased", "text": "x", "template_zh_tw": zh}


def test_family_zh_name_is_the_shortest_of_the_three_most_common_templates():
    rows = ([_row("attack speed", "增加 #% 攻擊速度")] * 3 + [_row("attack speed", "雙持時增加 #% 攻擊速度")] * 5
            + [_row("attack speed", "攻擊速度 #%")] * 1 + [_row("attack speed", "速")] * 1)
    families = summarise_families(rows)
    # "速" and "攻擊速度 #%" tie on count; only three candidates are kept, by count then text
    assert families["attack speed"]["name_zh_tw"] == "攻擊速度 #%"


def test_family_zh_name_is_stable_when_counts_and_lengths_tie():
    a, b = _row("armour", "護甲甲 #"), _row("armour", "護甲乙 #")
    assert summarise_families([a, b])["armour"]["name_zh_tw"] == summarise_families([b, a])["armour"]["name_zh_tw"]


def test_family_without_a_chinese_template_has_no_zh_name():
    families = summarise_families([_row("chaos immunity", None), _row("spirit", "+# 精魂")])
    assert families["chaos immunity"]["name_zh_tw"] is None and families["spirit"]["name_zh_tw"] == "+# 精魂"


def test_main_writes_family_zh_names(tmp_path, index_nodes, monkeypatch):
    monkeypatch.setattr(stats, "MIN_PARSED_RATIO", 0.0)   # four fixture lines, one of them plain text
    nodes = tmp_path / "nodes.jsonl"
    write_jsonl(nodes, index_nodes)
    assert stats.main(["--nodes", str(nodes), "--out", str(tmp_path / "s.jsonl"),
                       "--families", str(tmp_path / "f.json")]) == 0
    families = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))
    assert families["attack speed"]["name_zh_tw"] == "攻擊速度增加 #%"
