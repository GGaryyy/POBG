import copy
import json

import pytest

from src.catalog.spec import SPEC_PATH, Spec, load_spec
from tests.support import FIXTURES

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _load_mutated(tmp_path, mutate):
    raw = copy.deepcopy(load_spec().raw)
    mutate(raw)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return load_spec(path)


def test_real_spec_loads(spec):
    assert isinstance(spec, Spec)
    assert spec.languages == {"en": "us", "zh-tw": "tw"}
    assert SPEC_PATH.exists()


def test_min_fixture_spec_loads():
    spec = load_spec(FIXTURES / "poe2db_sources_min.json")
    assert spec.expect_min("skill_gems_listing", "list") == 1


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_spec(tmp_path / "nope.json")


def test_resolve_url(spec):
    assert spec.resolve_url("Leap_Slam", "zh-tw") == "https://poe2db.tw/tw/Leap_Slam"
    assert spec.resolve_url("Leap_Slam") == "https://poe2db.tw/us/Leap_Slam"


def test_resolve_url_unknown_lang(spec):
    with pytest.raises(ValueError, match="unknown language"):
        spec.resolve_url("Leap_Slam", "fr")


def test_selector_formats_lang_path(spec):
    assert "/tw/" in spec.selector("gem_anchor", "zh-tw")
    assert "/us/" in spec.selector("gem_anchor", "en")
    assert spec.selector("level_table_headers") == ["Level", "Requires Level"]
    assert spec.selector("popup") == ".newItemPopup.GemPopup"


def test_selector_unknown(spec):
    with pytest.raises(ValueError, match="unknown selector"):
        spec.selector("nope")


def test_section_ids_and_expect_min(spec):
    assert spec.section_ids("skill_gems_listing", "list") == {"en": "SkillGems", "zh-tw": "技能寶石"}
    assert spec.expect_min("skill_gems_listing", "list") == 380
    assert spec.expect_min("support_gems_listing", "gem_tags") == 550


def test_source_for_kind(spec):
    name, src = spec.source_for_kind("spirit_gem")
    assert name == "spirit_gems_listing"
    assert src["slug"] == "Spirit_Gems"


def test_source_for_kind_unknown(spec):
    with pytest.raises(ValueError, match="no source with kind"):
        spec.source_for_kind("wand")


def test_unknown_source_and_section(spec):
    with pytest.raises(ValueError, match="unknown source"):
        spec.source("nope")
    with pytest.raises(ValueError, match="unknown section"):
        spec.section("skill_gems_listing", "nope")


def test_field_lookup_falls_back_to_generic(spec):
    assert spec.field("skill_gem", "tier")["reliability"] == "ok"
    assert spec.field("skill_gem", "name")["type"] == "str"
    assert spec.field("skill_gem", "nonexistent") is None


def test_missing_languages(tmp_path):
    with pytest.raises(ValueError, match="languages"):
        _load_mutated(tmp_path, lambda raw: raw.pop("languages"))


def test_languages_without_en(tmp_path):
    with pytest.raises(ValueError, match="'en'"):
        _load_mutated(tmp_path, lambda raw: raw.update(languages={"zh-tw": "tw"}))


def test_empty_language_path(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        _load_mutated(tmp_path, lambda raw: raw["languages"].update(en=""))


def test_section_without_en_id(tmp_path):
    def mutate(raw):
        del raw["sources"]["skill_gems_listing"]["sections"]["list"]["ids"]["en"]

    with pytest.raises(ValueError, match=r"sources\.skill_gems_listing\.sections\.list\.ids\.en"):
        _load_mutated(tmp_path, mutate)


def test_bad_reliability(tmp_path):
    def mutate(raw):
        raw["fields"]["gem.name"]["reliability"] = "maybe"

    with pytest.raises(ValueError, match=r"fields\.gem\.name\.reliability"):
        _load_mutated(tmp_path, mutate)


def test_missing_page_url_pattern(tmp_path):
    with pytest.raises(ValueError, match=r"url_patterns\.page"):
        _load_mutated(tmp_path, lambda raw: raw["url_patterns"].pop("page"))
