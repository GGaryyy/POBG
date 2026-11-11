import pytest

from src.catalog.spec import load_spec
from src.tools.build_tools import BuildTools
from src.tools.lookup import BadArgument, LookupService, NotFound, ServiceUnavailable
from tests.kg_support import GRAPH_REL, build_full_environment

pytestmark = pytest.mark.integration

ROW_KEYS = {"slug", "name", "name_zh_tw", "tier", "tags", "url_en", "url_zh_tw"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return build_full_environment(tmp_path_factory.mktemp("supports_env"), load_spec())


@pytest.fixture
def tools(env):
    return BuildTools(LookupService(base_dir=env, graph_path=env / GRAPH_REL))


def slugs(result):
    return [s["slug"] for s in result["supports"]]


def test_supports_are_ordered_by_tier(tools):
    result = tools.supports_for("Leap Slam")
    assert result["total"] == 2 and slugs(result) == ["Added_Fire_Damage", "Faster_Attacks"]
    assert [s["tier"] for s in result["supports"]] == [1, 2]
    assert result["skill"] == {"slug": "Leap_Slam", "kind": "skill_gem", "name_en": "Leap Slam", "name_zh_tw": "躍擊"}
    assert result["tag"] is None


def test_rows_carry_names_and_both_urls(tools):
    row = tools.supports_for("Leap Slam")["supports"][0]
    assert set(row) == ROW_KEYS
    assert row["name_zh_tw"] == "附加火焰傷害"
    assert row["url_en"] == "https://poe2db.tw/us/Added_Fire_Damage"
    assert row["url_zh_tw"] == "https://poe2db.tw/tw/Added_Fire_Damage"


def test_tag_filter(tools):
    result = tools.supports_for("Leap Slam", tag="Fire")
    assert slugs(result) == ["Added_Fire_Damage"] and result["total"] == 1 and result["tag"] == "Fire"
    assert tools.supports_for("Leap Slam", tag="nonexistent")["total"] == 0


def test_limit_keeps_total(tools):
    result = tools.supports_for("Leap Slam", limit=1)
    assert result["total"] == 2 and slugs(result) == ["Added_Fire_Damage"]


def test_skill_by_traditional_chinese_name(tools):
    assert slugs(tools.supports_for("躍擊")) == ["Added_Fire_Damage", "Faster_Attacks"]


def test_skill_with_one_support(tools):
    assert slugs(tools.supports_for("Unearth")) == ["Added_Fire_Damage"]


def test_spirit_gem_is_accepted(tools):
    result = tools.supports_for("Herald of Ash")
    assert result["skill"] == {"slug": "Herald_of_Ash", "kind": "spirit_gem", "name_en": "Herald of Ash",
                               "name_zh_tw": "灰燼信使"}
    assert result["total"] == 0 and result["supports"] == []   # the fixture graph has no edge to it


def test_sources_point_at_the_skill_page(tools):
    sources = tools.supports_for("Leap Slam")["sources"]
    assert [s["url"] for s in sources] == ["https://poe2db.tw/us/Leap_Slam", "https://poe2db.tw/tw/Leap_Slam"]


def test_support_gem_as_input_is_rejected(tools):
    with pytest.raises(BadArgument, match="get_gem"):
        tools.supports_for("Added Fire Damage")


def test_unknown_skill(tools):
    with pytest.raises(NotFound):
        tools.supports_for("Not A Skill")


def test_missing_graph(tools, monkeypatch):
    monkeypatch.setattr(tools.lookup, "graph", None)
    with pytest.raises(ServiceUnavailable, match="knowledge graph"):
        tools.supports_for("Leap Slam")


@pytest.mark.parametrize("limit", [0, -1])
def test_bad_limit(tools, limit):
    with pytest.raises(BadArgument, match="limit must be >= 1"):
        tools.supports_for("Leap Slam", limit=limit)


def test_over_long_tag_is_rejected(tools):
    with pytest.raises(BadArgument, match="tag is longer than 120 characters"):
        tools.supports_for("Leap Slam", tag="x" * 121)
