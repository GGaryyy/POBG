import json
import shutil

import pytest
import requests

from src.catalog.entity_index import (Entity, EntityIndex, build_entity_index, coverage_summary,
                                      fetch_passive_en_slugs, fetch_zh_names, make_aliases)
from src.catalog.spec import load_spec
from tests.support import HTML_DIR, JSONL_DIR, html

pytestmark = pytest.mark.unit

ZH = {"Leap_Slam": "躍擊", "Unearth": "掘屍", "Herald_of_Ash": "灰燼信使",
      "Resolute_Technique": "堅毅之心", "Black_Scythe_Training": "黑鐮訓練"}
PASSIVE_SLUGS = {"Resolute Technique": "Resolute_Technique", "Mind Over Matter": "Mind_Over_Matter",
                 "Black Scythe Training": "Black_Scythe_Training"}


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _layout(base):
    data = base / "data"
    for rel, src in (("skill_gems/Skill_Gems_Detail.jsonl", "Skill_Gems_Detail.jsonl"),
                     ("spirit_gems/Spirit_Gems_Detail.jsonl", "Spirit_Gems_Detail.jsonl"),
                     ("support_skill_gems/Support_Gems_Detail.jsonl", "Support_Gems_Detail.jsonl"),
                     ("passive_tree/passive_nodes.jsonl", "passive_nodes.jsonl")):
        dest = data / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(JSONL_DIR / src, dest)
    return data


@pytest.fixture
def data_dir(tmp_path):
    return _layout(tmp_path)


@pytest.fixture
def entities(spec, data_dir):
    return build_entity_index(spec, data_dir=data_dir, zh_names=ZH, passive_slugs=PASSIVE_SLUGS)


def by_key(entities):
    return {f"{e.kind}:{e.slug}": e for e in entities}


def test_make_aliases():
    assert make_aliases("Leap Slam", "躍擊") == ["leap slam", "leapslam", "躍擊"]
    assert make_aliases("Fire", None, "") == ["fire"]
    assert make_aliases("Hand of Gloom's") == ["hand of gloom's", "handofglooms"]


def test_build_counts_and_gem_join(entities):
    ents = by_key(entities)
    assert len(entities) == 11
    leap = ents["skill_gem:Leap_Slam"]
    assert leap.name_zh_tw == "躍擊"
    assert leap.url_en == "https://poe2db.tw/us/Leap_Slam"
    assert leap.url_zh_tw == "https://poe2db.tw/tw/Leap_Slam"
    assert leap.tier == 7 and leap.game_id == "LeapSlam"
    assert leap.tag_slugs == ["Attacks", "Area_of_Effect_Skills"]
    assert leap.record_file == "data/skill_gems/Skill_Gems_Detail.jsonl"
    assert leap.record_key == {"slug": "Leap_Slam"}
    assert leap.aliases == ["leap slam", "leapslam", "躍擊"]
    assert ents["skill_gem:Grim_Feast"].name_zh_tw is None
    assert ents["spirit_gem:Herald_of_Ash"].name_zh_tw == "灰燼信使"
    assert "support_gem:Fire_Attunement" in ents


def test_passive_entities(entities):
    ents = by_key(entities)
    ks = ents["passive_keystone:Resolute_Technique"]
    assert ks.node_id == "44017" and ks.name_zh_tw == "堅毅之心"
    assert ks.url_en == "https://poe2db.tw/us/Resolute_Technique"
    assert ks.record_key == {"id": "44017"}
    assert ents["passive_notable:Mind_Over_Matter"].node_id == "20001"
    timeless = ents["passive_notable:Black_Scythe_Training"]
    assert timeless.node_id == "Black_Scythe_Training"
    assert timeless.url_zh_tw == "https://poe2db.tw/tw/Black_Scythe_Training"
    asc = ents["passive_ascendancy:node_55001"]
    assert asc.url_en is None and asc.url_zh_tw is None and asc.name_zh_tw is None
    assert asc.name_en == "Ancestral Bond"
    assert not any(e.node_id == "30001" for e in entities)  # Small node, no name


def test_passive_slug_fallback_from_known_slugs(spec, data_dir):
    ents = build_entity_index(spec, data_dir=data_dir, zh_names={},
                              passive_slugs={"Something else": "Mind_Over_Matter"})
    assert "passive_notable:Mind_Over_Matter" in by_key(ents)
    assert "passive_keystone:node_44017" in by_key(ents)


def test_duplicate_slug_and_kind(spec, data_dir):
    path = data_dir / "skill_gems" / "Skill_Gems_Detail.jsonl"
    first = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(path.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate entity skill_gem:Leap_Slam"):
        build_entity_index(spec, data_dir=data_dir, zh_names=ZH, passive_slugs=PASSIVE_SLUGS)


def test_missing_data_file(spec, tmp_path):
    with pytest.raises(FileNotFoundError):
        build_entity_index(spec, data_dir=tmp_path, zh_names={}, passive_slugs={})


PAGES = {
    "https://poe2db.tw/tw/Skill_Gems": "listing_skill_tw.html",
    "https://poe2db.tw/tw/Keystone": "keystone_tw.html",
    "https://poe2db.tw/tw/Notable": "notable_tw.html",
    "https://poe2db.tw/us/Keystone": "keystone_us.html",
    "https://poe2db.tw/us/Notable": "notable_us.html",
}


def fake_fetcher(url):
    if url in PAGES:
        return html(PAGES[url])
    raise requests.ConnectionError(f"no fixture for {url}")


def never(url):
    raise AssertionError(f"unexpected fetch {url}")


def test_fetch_zh_names_and_cache(spec, tmp_path, capsys):
    cache = tmp_path / "cache"
    names = fetch_zh_names(spec, fetcher=fake_fetcher, cache_dir=cache)
    assert names == {"Leap_Slam": "躍擊", "Unearth": "掘屍", "Grim_Feast": "殘酷盛宴",
                     "Resolute_Technique": "堅毅之心", "Black_Scythe_Training": "黑鐮訓練",
                     "Mind_Over_Matter": "心靈勝物", "Heart_of_Ice": "冰之心"}
    assert (cache / "zh-tw_Skill_Gems.html").exists()
    assert "could not fetch" in capsys.readouterr().err  # spirit/support pages absent
    again = fetch_zh_names(spec, fetcher=never, cache_dir=cache, offline=True)
    assert again == names


def test_fetch_zh_names_offline_without_cache(spec, tmp_path):
    assert fetch_zh_names(spec, fetcher=never, cache_dir=tmp_path / "empty", offline=True) == {}


def test_fetch_passive_en_slugs_and_cache(spec, tmp_path):
    cache = tmp_path / "cache"
    slugs = fetch_passive_en_slugs(spec, fetcher=fake_fetcher, cache_dir=cache)
    assert slugs == {"Resolute Technique": "Resolute_Technique", "Black Scythe Training": "Black_Scythe_Training",
                     "Mind Over Matter": "Mind_Over_Matter", "Heart of Ice": "Heart_of_Ice"}
    assert fetch_passive_en_slugs(spec, fetcher=never, cache_dir=cache, offline=True) == slugs


def _ent(slug, name, kind="skill_gem", zh=None, **kw):
    return Entity(slug=slug, kind=kind, name_en=name, name_zh_tw=zh, url_en=None, url_zh_tw=None,
                  aliases=make_aliases(name, zh), **kw)


@pytest.fixture
def small_index():
    return EntityIndex([_ent("Wildfire", "Wildfire"), _ent("Fire_Storm", "Fire Storm"),
                        _ent("Fire", "Fire", kind="support_gem"), _ent("Leap_Slam", "Leap Slam", zh="躍擊")],
                       base_dir=HTML_DIR)


def test_find_ordering(small_index):
    hits = small_index.find("fire")
    assert [(h["slug"], h["match_type"]) for h in hits] == [
        ("Fire", "exact"), ("Fire_Storm", "prefix"), ("Wildfire", "substring")]


def test_find_kind_limit_and_empty(small_index):
    assert [h["slug"] for h in small_index.find("fire", kind="skill_gem")] == ["Fire_Storm", "Wildfire"]
    assert len(small_index.find("fire", limit=2)) == 2
    assert small_index.find("") == []
    assert small_index.find("   ") == []
    assert small_index.find("zzz") == []


def test_find_zh_and_punctuation_insensitive(small_index):
    assert small_index.find("躍擊")[0]["slug"] == "Leap_Slam"
    assert small_index.find("LEAP-SLAM")[0]["match_type"] == "exact"


def test_get(small_index):
    assert small_index.get("Fire").kind == "support_gem"
    assert small_index.get("Fire", kind="skill_gem") is None
    assert small_index.get("Nope") is None
    assert len(small_index) == 4


def test_record_for_gem_and_passive(entities, tmp_path):
    index = EntityIndex(entities, base_dir=tmp_path)
    gem = index.get("Leap_Slam")
    rec = index.record(gem)
    assert rec["name"] == "Leap Slam" and rec["game_id"] == "LeapSlam"
    assert set(rec) >= {"slug", "name", "href", "tier", "tag_slugs", "game_id", "level_effects"}
    node = index.record(index.get("Resolute_Technique"))
    assert node["id"] == "44017" and node["type"] == "Keystone"
    assert set(node) == {"id", "name", "type", "stats", "ascendancy", "class_start", "position", "neighbors"}
    hit = index.find("leap slam")[0]  # dict form
    assert index.record(hit)["slug"] == "Leap_Slam"


def test_record_none_cases(tmp_path):
    index = EntityIndex([], base_dir=tmp_path)
    assert index.record(_ent("A", "A")) is None
    assert index.record({"record_file": "data/x.jsonl", "record_key": None}) is None


def test_record_not_found_in_file(entities, tmp_path):
    index = EntityIndex(entities, base_dir=tmp_path)
    ghost = _ent("Ghost", "Ghost", record_file="data/skill_gems/Skill_Gems_Detail.jsonl", record_key={"slug": "Ghost"})
    assert index.record(ghost) is None


def test_load_roundtrip(entities, tmp_path):
    path = tmp_path / "idx.jsonl"
    path.write_text("".join(json.dumps(e.as_dict(), ensure_ascii=False) + "\n" for e in entities), encoding="utf-8")
    index = EntityIndex.load(path, base_dir=tmp_path)
    assert len(index) == 11
    assert index.find("堅毅之心")[0]["slug"] == "Resolute_Technique"


def test_coverage_summary(entities):
    s = coverage_summary(entities)
    assert s["total"] == 11
    assert s["by_kind"] == {"skill_gem": 3, "spirit_gem": 2, "support_gem": 2,
                            "passive_keystone": 1, "passive_notable": 2, "passive_ascendancy": 1}
    assert s["gem_zh_tw_coverage"] == round(3 / 7, 3)
    assert s["passive_zh_tw_coverage"] == round(2 / 3, 3)
    assert coverage_summary([])["gem_zh_tw_coverage"] is None
