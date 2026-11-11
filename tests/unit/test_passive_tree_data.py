import pytest

from src.scrapers.passive_tree_data import align_wrapped, class_names, clean_lines, node_texts, strip_markup
from tests.support import mini_tree_data

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("text, expected", [
    ("對你的擊中減少12%[CriticalDamageBonus|暴擊傷害加成]", "對你的擊中減少12%暴擊傷害加成"),
    ("+10 to [Spirit]", "+10 to Spirit"),
    ("[SinisterJewelSockets|Sinister] [Jewel] Socket", "Sinister Jewel Socket"),
    ("no markup here", "no markup here"),
    ("unclosed [bracket stays", "unclosed [bracket stays"),
    ("[a|b] and [c|d]", "b and d"),
])
def test_strip_markup(text, expected):
    assert strip_markup(text) == expected


def test_clean_lines_drops_blanks_and_collapses_whitespace():
    assert clean_lines(["  +5  to [Strength] ", "", "   ", None, "增加 5%\n[Spirit|精魂]"]) == ["+5 to Strength", "增加 5% 精魂"]


def test_node_texts_keys_names_and_stats():
    data = mini_tree_data()
    en, zh = node_texts(data["en"]), node_texts(data["zh-tw"])
    assert "root" not in en and set(en) == {str(i) for i in range(1, 14)} == set(zh)
    assert en["9"] == {"name": "Jewel Socket", "stats": []}            # markup stripped from the name too
    assert zh["9"]["name"] == "珠寶插槽"
    assert zh["2"] == {"name": "異靈之體", "stats": ["最大生命為 1", "免疫混沌傷害"]}
    assert en["6"] == {"name": "", "stats": ["+5 to Strength"]}


def test_node_texts_tolerates_missing_or_odd_nodes():
    assert node_texts({}) == {}
    assert node_texts({"nodes": {"a": "not a dict", "b": {"name": "no skill"}, "c": {"skill": 7}}}) == {
        "7": {"name": "", "stats": []}}


def test_align_wrapped_joins_chinese_where_english_continues():
    en = ["Minions deal 20% increased", "damage while on Full Life", "+5 to Strength"]
    zh = ["召喚物在滿血時", "造成的傷害增加 20%", "+5 力量"]
    assert align_wrapped(en, zh) == ["召喚物在滿血時造成的傷害增加 20%", "+5 力量"]


def test_align_wrapped_plain_lines_and_empty():
    assert align_wrapped(["A", "B"], ["甲", "乙"]) == ["甲", "乙"]
    assert align_wrapped([], []) == []


def test_align_wrapped_different_line_counts_is_none():
    assert align_wrapped(["A"], ["甲", "乙"]) is None


def test_class_names_pairs_both_languages():
    data = mini_tree_data()
    classes = class_names(data["en"], data["zh-tw"])
    assert [c["name"] for c in classes] == ["Marauder", "Witch", "Sorceress"]
    witch = classes[1]
    assert witch["name_zh_tw"] == "女巫"
    assert witch["ascendancies"] == [{"id": "Witch1", "name": "Infernalist", "name_zh_tw": "獄火師"},
                                     {"id": "Witch2", "name": "Blood Mage", "name_zh_tw": "血法師"}]


def test_class_names_skips_an_ascendancy_whose_ids_disagree():
    us = {"classes": [{"name": "Witch", "ascendancies": [{"id": "Witch1", "name": "Infernalist"},
                                                         {"id": "Witch2", "name": "Blood Mage"}]}]}
    tw = {"classes": [{"name": "女巫", "ascendancies": [{"id": "Witch9", "name": "別的"},
                                                       {"id": "Witch2", "name": "血法師"}]}]}
    assert class_names(us, tw)[0]["ascendancies"] == [{"id": "Witch2", "name": "Blood Mage", "name_zh_tw": "血法師"}]


def test_class_names_without_classes():
    assert class_names({}, {"classes": [{"name": "女巫"}]}) == []
