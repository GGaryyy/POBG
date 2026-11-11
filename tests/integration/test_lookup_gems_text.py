import pytest

from src.catalog.spec import load_spec
from src.tools.lookup import BadArgument, LookupService
from tests.kg_support import GRAPH_REL, build_full_environment

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    env = build_full_environment(tmp_path_factory.mktemp("gem_text_env"), load_spec())
    return LookupService(base_dir=env, graph_path=env / GRAPH_REL)


def slugs(result):
    return [g["slug"] for g in result["gems"]]


def test_text_alone_is_a_valid_filter(svc):
    assert slugs(svc.gems_by(text="contagion")) == ["Contagion"]


@pytest.mark.parametrize("text", ["FASTER ATT", "faster att", "Faster Att"])
def test_text_is_case_insensitive(svc, text):
    assert slugs(svc.gems_by(text=text)) == ["Faster_Attacks"]


def test_matches_name(svc):
    assert slugs(svc.gems_by(text="herald")) == ["Herald_of_Ash"]


def test_matches_description(svc):
    result = svc.gems_by(text="jump up and stun")
    assert result["total"] == 6


def test_matches_summary(svc):
    assert slugs(svc.gems_by(text="jump and slam")) == ["Leap_Slam"]


def test_matches_stat_lines(svc):
    assert svc.gems_by(text="can stun again")["total"] == 6


def test_text_with_tag(svc):
    result = svc.gems_by(text="jump up", tag="Fire")
    assert sorted(slugs(result)) == ["Added_Fire_Damage", "Herald_of_Ash"]


def test_text_with_kind(svc):
    assert slugs(svc.gems_by(text="jump up", kind="spirit_gem")) == ["Herald_of_Ash"]


def test_no_match(svc):
    result = svc.gems_by(text="zzz nothing")
    assert result["total"] == 0 and result["gems"] == []


def test_filters_echo_text(svc):
    assert svc.gems_by(text="Leap")["filters"]["text"] == "Leap"
    assert svc.gems_by(tag="Fire")["filters"]["text"] is None


def test_empty_text_alone_is_rejected(svc):
    with pytest.raises(BadArgument, match="give at least one filter"):
        svc.gems_by(text="")


def test_text_whitespace_is_collapsed(svc):
    assert slugs(svc.gems_by(text="  leap   slam  ")) == ["Leap_Slam"]


@pytest.mark.parametrize("args", [{"text": "x" * 121}, {"tag": "x" * 121}, {"class_name": "x" * 121},
                                  {"weapon": "x" * 121}])
def test_over_long_filters_are_rejected(svc, args):
    with pytest.raises(BadArgument, match="longer than 120 characters"):
        svc.gems_by(**args)


def test_over_long_queries_are_rejected(svc):
    for call in (svc.lookup_entity, svc.get_gem, svc.get_passive):
        with pytest.raises(BadArgument, match="longer than 500 characters"):
            call("x" * 501)
    assert svc.lookup_entity("x" * 500)["hits"] == []


# -- Chinese terms (gem descriptions are stored in English) ------------------------------------

def subterm_service(tmp_path):
    """The catalog with a made-up kind of the synthetic glossary term Stun: 'Heavy Stun' / 重暈眩."""
    import copy

    from src.catalog.entity_index import build_entity_index
    from src.catalog.spec import Spec
    from src.scrapers.common import write_jsonl
    from tests.kg_support import ZH_NAMES
    raw = copy.deepcopy(load_spec().raw)
    raw["keyword_subterms"] = {"_note": "x", "Stun": [{"en": "Stun Again", "zh_tw": "再次暈眩"}]}
    spec = Spec(raw)
    env = build_full_environment(tmp_path, spec)
    entities = build_entity_index(spec, data_dir=env / "data", zh_names=ZH_NAMES, passive_slugs={})
    write_jsonl(env / "data" / "catalog" / "entity_index.jsonl", (e.as_dict() for e in entities))
    return LookupService(base_dir=env, spec=spec, graph_path=env / GRAPH_REL)


def test_a_chinese_glossary_name_is_searched_by_its_english_name(svc):
    result = svc.gems_by(text="暈眩")
    assert result["text_searched"] == "Stun" and result["total"] == svc.gems_by(text="Stun")["total"] > 0
    assert result["filters"]["text"] == "暈眩"


def test_chinese_text_with_no_known_term_says_descriptions_are_english(svc):
    result = svc.gems_by(text="不存在的詞")
    assert result["total"] == 0 and "stored in English" in result["note"]
    assert "note" not in svc.gems_by(text="zzzz") and "text_searched" not in svc.gems_by(text="stun")


def test_a_named_kind_of_a_term_resolves_to_the_term_and_translates(tmp_path):
    svc = subterm_service(tmp_path)
    assert svc.gems_by(text="再次暈眩")["text_searched"] == "Stun Again"
    assert svc.gems_by(text="再次暈眩")["total"] == svc.gems_by(text="can stun again")["total"] == 6
    for name in ("再次暈眩", "Stun Again", "stun agains"):
        assert svc.explain_keyword(name)["keyword"]["slug"] == "Stun"
        assert [(h["kind"], h["slug"]) for h in svc.lookup_entity(name)["hits"]][:1] == [("keyword", "Stun")]


def test_the_catalog_names_the_three_charges():
    terms = load_spec().subterms()
    assert set(terms) == {"Charges"}
    assert {(t["en"], t["zh_tw"]) for t in terms["Charges"]} == {
        ("Frenzy Charge", "狂怒球"), ("Endurance Charge", "耐力球"), ("Power Charge", "暴擊球")}
