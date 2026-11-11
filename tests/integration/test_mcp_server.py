import asyncio
import json
import re
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from src.catalog.spec import load_spec
from src.tools import lookup as lk
from src.tools import maintenance as mnt
from src.tools import mcp_server
from src.tools.build_tools import POE_NINJA_URL, BuildTools
from src.tools.build_workflow import BUILD_WORKFLOW, MAX_REQUEST_LEN, SERVER_INSTRUCTIONS, build_workflow_text
from src.tools.lookup import LookupService
from tests.kg_support import GRAPH_REL, build_full_environment
from tests.support import html

pytestmark = pytest.mark.integration

TOOLS = ["lookup_entity", "get_gem", "get_passive", "passives_with_stat", "explain_keyword", "gems_by",
         "supports_for", "reference_builds", "verify_build", "path_to", "get_item", "items_by", "modifiers_for",
         "refresh_gem", "build_workflow",
         "data_status", "update_data"]
LADDER = Path(__file__).resolve().parents[1] / "fixtures" / "jsonl" / "poe_ninja_builds.jsonl"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    return build_full_environment(tmp_path_factory.mktemp("mcp_env"), load_spec())


@pytest.fixture
def svc(env, monkeypatch):
    service = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    monkeypatch.setattr(mcp_server, "_service", service)
    return service


def call(name, args):
    return asyncio.run(mcp_server.server.call_tool(name, args))


def payload(result):
    assert result.is_error is False
    return json.loads(result.content[0].text)


def test_lists_the_seventeen_tools():
    tools = asyncio.run(mcp_server.server.list_tools())
    assert [t.name for t in tools] == TOOLS
    assert all(t.description for t in tools)


def test_tool_schemas_declare_required_arguments():
    schemas = {t.name: t.input_schema for t in asyncio.run(mcp_server.server.list_tools())}
    assert schemas["lookup_entity"]["required"] == ["query"]
    assert set(schemas["lookup_entity"]["properties"]) == {"query", "kind", "limit"}
    assert schemas["gems_by"].get("required", []) == []                         # every filter optional
    assert schemas["refresh_gem"]["required"] == ["slug_or_name"]


def test_lookup_entity_returns_hit(svc):
    data = payload(call("lookup_entity", {"query": "leap slam"}))
    assert data["query"] == "leap slam"
    assert [h["slug"] for h in data["hits"]] == ["Leap_Slam"]
    assert data["hits"][0]["url_zh_tw"] == "https://poe2db.tw/tw/Leap_Slam" and data["hits"][0]["name_zh_tw"] == "躍擊"


def test_cjk_text_is_not_escaped(svc):
    result = call("lookup_entity", {"query": "躍擊"})
    assert "躍擊" in result.content[0].text


@pytest.mark.parametrize("tool, args, check", [
    ("get_gem", {"slug_or_name": "Added Fire Damage"}, lambda d: d["supports_skills"]["total"] == 2),
    ("get_passive", {"slug_or_id": "Heart_of_Ice"}, lambda d: d["passive"]["id"] == "3"),
    ("passives_with_stat", {"query": "cold damage"}, lambda d: [p["id"] for p in d["with_page"]] == ["3"]),
    ("explain_keyword", {"query": "Stun"}, lambda d: d["answer_text"] == "Stunned enemies cannot act."),
    ("gems_by", {"tag": "Fire"}, lambda d: d["total"] == 2),
])
def test_each_read_tool_answers(svc, tool, args, check):
    assert check(payload(call(tool, args)))


def test_optional_arguments_pass_through(svc):
    data = payload(call("passives_with_stat", {"query": "cold damage", "include_without_page": True}))
    assert [n["id"] for n in data["without_page"]["nodes"]] == ["4"]
    assert payload(call("gems_by", {"class_name": "Witch", "limit": 1}))["gems"][0]["slug"] == "Unearth"


def test_refresh_gem_tool_uses_network_layer(svc, monkeypatch):
    seen = []
    monkeypatch.setattr(lk, "fetch_html",
                        lambda url, delay=0.0: seen.append((url, delay)) or html("detail_skill_keywords.html"))
    data = payload(call("refresh_gem", {"slug_or_name": "Leap_Slam"}))
    polite = svc.spec.raw["robots"]["polite_delay_seconds"]
    assert seen == [("https://poe2db.tw/us/Leap_Slam", polite)] and data["changed_fields"] == []


@pytest.mark.parametrize("tool, args, message", [
    ("get_gem", {"slug_or_name": "zzz"}, "no skill_gem/spirit_gem/support_gem matches 'zzz'"),
    ("explain_keyword", {"query": "Not A Keyword"}, "unknown keyword"),
    ("gems_by", {}, "give at least one filter"),
    ("lookup_entity", {"query": "x", "limit": 0}, "limit must be >= 1"),
    ("passives_with_stat", {"query": "damage", "lang": "fr"}, "lang must be one of"),
])
def test_lookup_failures_surface_as_tool_errors_with_message(svc, tool, args, message):
    with pytest.raises(ToolError) as err:
        call(tool, args)
    assert message in str(err.value)


def test_service_unavailable_surfaces_as_tool_error(svc, monkeypatch):
    monkeypatch.setattr(svc, "stat_rows", [])
    with pytest.raises(ToolError, match="stat index missing"):
        call("passives_with_stat", {"query": "damage"})


def test_missing_required_argument_is_rejected(svc):
    with pytest.raises(ToolError, match="query\\s+Field required"):
        call("lookup_entity", {})


def test_service_is_created_lazily_once(monkeypatch):
    created = []

    class Fake:
        def __init__(self):
            created.append(1)

    monkeypatch.setattr(mcp_server, "_service", None)
    monkeypatch.setattr(mcp_server, "LookupService", Fake)
    first, second = mcp_server.service(), mcp_server.service()
    assert first is second and created == [1]


def test_service_returns_preset_instance(svc):
    assert mcp_server.service() is svc


def test_instructions_name_the_tools():
    assert "lookup_entity" in mcp_server.INSTRUCTIONS and "refresh_gem" in mcp_server.INSTRUCTIONS


# -- cited-build tools and prompt ------------------------------------------------------------

@pytest.fixture
def ladder(svc, monkeypatch):
    tools = BuildTools(svc, builds_path=LADDER)
    monkeypatch.setattr(mcp_server, "_tools", tools)
    return tools


def prompt_text(name, args):
    result = asyncio.run(mcp_server.server.get_prompt(name, args))
    assert len(result.messages) == 1 and result.messages[0].role == "user"
    return result.messages[0].content.text


def test_server_version_is_package_version():
    from src import __version__
    assert __version__ == "0.8.0" and mcp_server.server.version == __version__
    assert mcp_server.server.name == mcp_server.SERVER_NAME == "pobg"


def test_instructions_mention_the_cited_workflow():
    assert "verify_build" in mcp_server.INSTRUCTIONS and "sources_markdown" in mcp_server.INSTRUCTIONS


def test_build_guide_prompt_is_listed_with_arguments():
    prompts = asyncio.run(mcp_server.server.list_prompts())
    assert [p.name for p in prompts] == ["build_guide", "status", "update"]
    arguments = {a.name: a.required for a in prompts[0].arguments}
    assert arguments == {"request": True, "lang": False}


def test_build_guide_prompt_text():
    text = prompt_text("build_guide", {"request": "a fire Titan", "lang": "zh-tw"})
    assert "a fire Titan" in text and "Traditional Chinese" in text and "verify_build" in text


def test_build_guide_defaults_to_english():
    assert "Answer language: English" in prompt_text("build_guide", {"request": "x"})


def test_build_guide_unknown_lang_falls_back_to_english():
    assert "Answer language: English" in prompt_text("build_guide", {"request": "x", "lang": "fr"})


def test_build_guide_truncates_long_request():
    text = prompt_text("build_guide", {"request": "a" * (MAX_REQUEST_LEN + 500)})
    assert "a" * MAX_REQUEST_LEN in text and "a" * (MAX_REQUEST_LEN + 1) not in text


def test_verify_build_through_the_server(svc, ladder):
    data = payload(call("verify_build", {"gems": ["Leap Slam", "leap"], "passives": ["冰之心"]}))
    assert [g["slug"] for g in data["verified"]["gems"]] == ["Leap_Slam"]
    assert data["verified"]["passives"][0]["cite"] == 2
    assert data["unverified"][0]["input"] == "leap" and data["lang"] == "zh-tw"
    assert data["sources_markdown"].startswith("## 資料來源")


def test_supports_for_through_the_server(svc, ladder):
    data = payload(call("supports_for", {"skill": "Leap Slam", "limit": 1}))
    assert data["total"] == 2 and [s["slug"] for s in data["supports"]] == ["Added_Fire_Damage"]


def test_reference_builds_through_the_server(svc, ladder):
    data = payload(call("reference_builds", {"class_name": "Titan", "main_skill": "躍擊"}))
    assert data["total_matching"] == 2 and data["source"]["url"] == POE_NINJA_URL
    assert "SecretHero" not in json.dumps(data)


def test_gems_by_text_through_the_server(svc):
    data = payload(call("gems_by", {"text": "Herald"}))
    assert data["filters"]["text"] == "Herald" and [g["slug"] for g in data["gems"]] == ["Herald_of_Ash"]


@pytest.mark.parametrize("tool, args, message", [
    ("verify_build", {}, "give at least one gem, passive, item or affix"),
    ("verify_build", {"gems": ["x"], "lang": "fr"}, "lang must be one of"),
    ("supports_for", {"skill": "Added Fire Damage"}, "use get_gem"),
    ("supports_for", {"skill": "Not A Skill"}, "matches 'Not A Skill'"),
    ("supports_for", {"skill": "Leap Slam", "tag": "x" * 121}, "tag is longer than 120 characters"),
    ("reference_builds", {"class_name": "x" * 121}, "class_name is longer than 120 characters"),
    ("gems_by", {"text": "x" * 121}, "text is longer than 120 characters"),
    ("lookup_entity", {"query": "x" * 501}, "longer than 500 characters"),
    ("explain_keyword", {"query": "x" * 501}, "longer than 500 characters"),
    ("passives_with_stat", {"query": "x" * 501}, "longer than 500 characters"),
    ("verify_build", {"gems": ["x" * 121]}, "120"),
    ("verify_build", {"gems": ["x"] * 41}, "40"),
])
def test_build_tool_failures_surface_as_tool_errors(svc, ladder, tool, args, message):
    with pytest.raises(ToolError) as err:
        call(tool, args)
    assert message in str(err.value)


def test_reference_builds_missing_file_is_a_tool_error(svc, monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_server, "_tools", BuildTools(svc, builds_path=tmp_path / "none.jsonl"))
    with pytest.raises(ToolError, match="scope ladder"):
        call("reference_builds", {})


def test_every_tool_has_a_description():
    assert all(t.description and t.description.strip() for t in asyncio.run(mcp_server.server.list_tools()))


def test_build_schemas_declare_required_arguments():
    schemas = {t.name: t.input_schema for t in asyncio.run(mcp_server.server.list_tools())}
    assert schemas["supports_for"]["required"] == ["skill"]
    assert schemas["verify_build"].get("required", []) == []
    assert schemas["reference_builds"].get("required", []) == []
    assert "text" in schemas["gems_by"]["properties"]


def test_build_tools_rebuilds_when_service_changes(env, monkeypatch):
    first = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    second = LookupService(base_dir=env, graph_path=env / GRAPH_REL)
    monkeypatch.setattr(mcp_server, "_tools", None)
    monkeypatch.setattr(mcp_server, "_service", first)
    tools = mcp_server.build_tools()
    assert tools.lookup is first and mcp_server.build_tools() is tools
    monkeypatch.setattr(mcp_server, "_service", second)
    rebuilt = mcp_server.build_tools()
    assert rebuilt is not tools and rebuilt.lookup is second


@pytest.mark.parametrize("text", [BUILD_WORKFLOW, SERVER_INSTRUCTIONS])
def test_tools_named_in_workflow_text_exist_on_the_server(text):
    registered = {t.name for t in asyncio.run(mcp_server.server.list_tools())}
    pattern = r"\b(" + "|".join(TOOLS) + r")\b"
    mentioned = set(re.findall(pattern, text))
    assert mentioned and mentioned <= registered
    snake = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text))
    assert {name for name in snake if name.endswith(("_entity", "_gem", "_passive", "_by", "_for", "_build",
                                                      "_builds", "_keyword", "_stat"))} <= registered | {"passives_with_stat"}


def test_verify_build_description_states_the_limits():
    tools = {t.name: t for t in asyncio.run(mcp_server.server.list_tools())}
    description = " ".join(tools["verify_build"].description.split())
    assert "At most 40 entries per list (60 affixes), 120 characters each" in description
    assert "Per item at most 3 prefixes and 3 suffixes, one modifier per family" in description
    assert "A part of a modifier is not verified" in description


# -- path_to ------------------------------------------------------------------------------------------

def test_path_to_through_the_server(svc, ladder):
    body = payload(call("path_to", {"class_name": "女巫", "targets": ["冰之心", "Not A Node"]}))
    assert body["class"] == "Witch" and body["lang"] == "zh-tw"
    assert [r["id"] for r in body["path"]] == ["2", "3"] and body["points"]["passive"]["used"] == 2
    assert [u["input"] for u in body["unverified"]] == ["Not A Node"]
    assert body["path"][1]["target"] is True and body["approximate"] is True


def test_path_to_schema_and_description():
    tool = next(t for t in asyncio.run(mcp_server.server.list_tools()) if t.name == "path_to")
    assert tool.input_schema["required"] == ["class_name", "targets"]
    assert "approximation" in tool.description and "added_points" in tool.description


@pytest.mark.parametrize("args, message", [
    ({"class_name": "Paladin", "targets": ["Heart of Ice"]}, "unknown class 'Paladin'; classes: Sorceress, Witch"),
    ({"class_name": "Witch", "targets": []}, "at least one target"),
    ({"class_name": "Witch", "targets": ["Heart of Ice"], "ascendancy": "Titan"}, "not an ascendancy of Witch"),
])
def test_path_to_errors_reach_the_model_as_tool_errors(svc, ladder, args, message):
    with pytest.raises(ToolError) as err:
        call("path_to", args)
    assert message in str(err.value)


# -- build_workflow: the workflow for clients that cannot call prompts ---------------------------

@pytest.mark.parametrize("lang, language", [("en", "English"), ("zh-tw", "Traditional Chinese"), ("ZH-TW ", "Traditional Chinese")])
def test_build_workflow_tool_returns_the_prompt_steps(lang, language):
    result = payload(call("build_workflow", {"lang": lang}))
    assert result["lang"] == lang.strip().lower()
    assert BUILD_WORKFLOW in result["workflow"] and f"Answer language: {language}" in result["workflow"]


def test_build_workflow_tool_defaults_to_english_and_needs_no_data(monkeypatch):
    monkeypatch.setattr(mcp_server, "_service", None)
    monkeypatch.setattr(mcp_server, "LookupService", lambda: pytest.fail("build_workflow must not load data"))
    result = payload(call("build_workflow", {}))
    assert result["lang"] == "en" and "Answer language: English" in result["workflow"]


def test_build_workflow_tool_rejects_unknown_language():
    with pytest.raises(ToolError, match="lang must be one of"):
        call("build_workflow", {"lang": "fr"})


def test_build_workflow_and_prompt_share_the_steps():
    steps = payload(call("build_workflow", {}))["workflow"].split("\n\n")[-1]
    assert prompt_text("build_guide", {"request": "x"}).endswith(steps)


def test_instructions_point_tool_only_clients_to_the_workflow_tool():
    assert "build_workflow" in mcp_server.INSTRUCTIONS


def test_build_workflow_text_is_the_steps_without_a_request():
    text = build_workflow_text("zh-tw")
    assert text.startswith("How to give Path of Exile 2 build advice") and text.endswith(BUILD_WORKFLOW)
    assert "Request:" not in text


def test_build_workflow_tool_treats_an_empty_language_as_english():
    assert payload(call("build_workflow", {"lang": ""}))["lang"] == "en"


@pytest.mark.parametrize("tool, args, label", [
    ("build_workflow", {"lang": "x" * 500}, "lang"),
    ("passives_with_stat", {"query": "damage", "lang": "x" * 500}, "lang"),
    ("passives_with_stat", {"query": "damage", "kind": "x" * 500}, "kind"),
    ("lookup_entity", {"query": "x", "kind": "x" * 500}, "kind"),
])
def test_over_long_lang_and_kind_are_refused_without_being_echoed(svc, tool, args, label):
    with pytest.raises(ToolError) as caught:
        call(tool, args)
    assert f"{label} is longer than" in str(caught.value) and "xxxxxxxxxx" not in str(caught.value)


def test_stat_limit_in_the_description_is_the_real_limit():
    tools = {t.name: t for t in asyncio.run(mcp_server.server.list_tools())}
    assert f"At most {lk.MAX_STAT_LIMIT} nodes per list" in " ".join(tools["passives_with_stat"].description.split())


# -- data commands: data_status, update_data, the status and update prompts ---------------------

LISTING_US = "https://poe2db.tw/us/Skill_Gems"


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A private data folder (updates change files) with the server bound to it and a fake site."""
    spec = lowered_spec_for_updates()
    base = build_full_environment(tmp_path, spec)
    service = LookupService(base_dir=base, spec=spec, graph_path=base / GRAPH_REL)
    monkeypatch.setattr(mcp_server, "_service", service)
    calls = []

    def fake_fetch(url, delay=0.0):
        calls.append((url, delay))
        if url == LISTING_US:
            return html("listing_skill_us.html")
        if url == "https://poe2db.tw/tw/Skill_Gems":
            return html("listing_skill_tw.html")
        return html("detail_skill.html")

    monkeypatch.setattr(mnt, "fetch_html", fake_fetch)
    return service, calls


def lowered_spec_for_updates():
    from tests.support import lowered_spec
    return lowered_spec(1)


def test_data_status_through_the_server_uses_the_loaded_folder_and_no_network(fresh):
    service, calls = fresh
    status = payload(call("data_status", {}))
    assert status["data_dir"] == str(service.base_dir / "data") and "online" not in status
    assert {d["name"]: d["records"] for d in status["datasets"]}["skill_gems"] == 3
    assert status["update_scopes"] == ["skill_gems", "spirit_gems", "support_gems", "passives", "items", "glossary", "ladder"]
    assert calls == []


def test_data_status_works_before_any_data_was_loaded(monkeypatch):
    monkeypatch.setattr(mcp_server, "_service", None)
    monkeypatch.setattr(mcp_server, "LookupService", lambda *a, **k: pytest.fail("status must not load the data"))
    assert payload(call("data_status", {}))["version"] == mcp_server.server.version


def test_update_data_is_refused_while_another_update_or_refresh_runs(fresh):
    service, calls = fresh
    with lk.DATA_LOCK:
        with pytest.raises(ToolError, match="already running"):
            call("update_data", {"scope": "skill_gems"})
        with pytest.raises(ToolError, match="already running"):
            call("data_status", {"check_online": True})
    assert calls == [] and mcp_server._service is service


def test_reload_failure_after_an_update_says_the_data_was_updated(fresh, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("bad index")

    service, _ = fresh
    monkeypatch.setattr(mcp_server, "LookupService", broken)
    with pytest.raises(ToolError, match=r"the data was updated, but reloading it failed \(bad index\); restart"):
        call("update_data", {"scope": "skill_gems"})
    assert mcp_server._service is service


def test_update_data_description_caps_the_repeat_calls():
    description = " ".join({t.name: t for t in asyncio.run(mcp_server.server.list_tools())}["update_data"].description.split())
    assert "at most 10 calls" in description and "not again within 15 minutes" in description
    assert mnt.RECENT_SECONDS == 15 * 60


def test_data_status_online_adds_the_probe_report(fresh, monkeypatch):
    seen = []
    monkeypatch.setattr(mnt.DataMaintenance, "online_check", lambda self: seen.append(self.base_dir) or {"ok": True})
    status = payload(call("data_status", {"check_online": True}))
    assert status["online"] == {"ok": True} and seen == [fresh[0].base_dir]


def test_update_data_dry_run_writes_nothing_and_keeps_the_loaded_service(fresh):
    service, calls = fresh
    result = payload(call("update_data", {"scope": "skill_gems", "dry_run": True}))
    assert result["selected"] == 3 and result["updated"] == 0 and result["requests"] == 1
    assert calls == [(LISTING_US, service.spec.raw["robots"]["polite_delay_seconds"])]
    assert mcp_server._service is service


def test_update_data_reloads_the_service_so_the_session_sees_the_new_gem(fresh, capfd):
    service, calls = fresh
    with pytest.raises(ToolError):
        call("get_gem", {"slug_or_name": "Grim_Feast"})
    result = payload(call("update_data", {"scope": "skill_gems"}))
    assert result["added"] == ["Grim_Feast"] and result["removed"] == ["Contagion"] and result["left"] == 0
    assert mcp_server._service is not service and mcp_server._service.base_dir == service.base_dir
    assert payload(call("get_gem", {"slug_or_name": "殘酷盛宴"}))["gem"]["slug"] == "Grim_Feast"
    with pytest.raises(ToolError):
        call("get_gem", {"slug_or_name": "Contagion"})
    assert all(delay == service.spec.raw["robots"]["polite_delay_seconds"] for _, delay in calls)
    assert capfd.readouterr().out == ""                         # stdout belongs to the MCP protocol


def test_update_data_respects_max_gems_and_reports_what_is_left(fresh):
    result = payload(call("update_data", {"scope": "skill_gems", "max_gems": 2}))
    assert result["updated"] == 2 and result["left"] == 1
    assert result["requests"] == 4                                   # listing + two gems + the /tw/ listing


@pytest.mark.parametrize("args, message", [
    ({"scope": ""}, "scope is required and must be one of: skill_gems, spirit_gems, support_gems, passives, items, glossary, ladder"),
    ({"scope": "all"}, "there is no update for everything"),
    ({"scope": "weapons"}, "scope is required"),
    ({"scope": "items", "dry_run": True}, "an items update re-fetches whole item class pages"),
    ({"scope": "ladder", "names": ["x"]}, "only apply to the gem scopes"),
    ({"scope": "skill_gems", "max_gems": 100}, "max_gems must be between 1 and 40"),
    ({"scope": "skill_gems", "names": ["Nope"]}, "not a skill_gem in the local data"),
    ({"scope": "passives", "dry_run": True}, "only apply to the gem scopes"),
])
def test_update_data_errors_reach_the_model_and_fetch_nothing(fresh, args, message):
    service, calls = fresh
    with pytest.raises(ToolError, match=message):
        call("update_data", args)
    assert calls == [] and mcp_server._service is service


def test_update_data_needs_a_scope_argument(fresh):
    with pytest.raises(ToolError, match="scope\\s+Field required"):
        call("update_data", {})


def test_failed_update_keeps_the_loaded_service(fresh, monkeypatch):
    service, _ = fresh

    def down(url, delay=0.0):
        raise mnt.requests.ConnectionError("no route")

    monkeypatch.setattr(mnt, "fetch_html", down)
    with pytest.raises(ToolError, match="network error: no route. Nothing was written"):
        call("update_data", {"scope": "skill_gems"})
    assert mcp_server._service is service


def test_status_prompt_names_the_tool_and_the_scopes():
    text = prompt_text("status", {})
    assert "Call data_status" in text and "check_online=true" in text
    assert "skill_gems, spirit_gems, support_gems, passives" in text and "update_data" not in text


@pytest.mark.parametrize("args", [{}, {"scope": ""}, {"scope": "all"}, {"scope": "everything please"}])
def test_update_prompt_without_a_scope_tells_the_model_not_to_update(args):
    text = prompt_text("update", args)
    assert text.startswith("The update command needs exactly one scope. Do not call update_data.")
    assert "skill_gems, spirit_gems, support_gems, passives" in text and "dry_run" not in text


def test_update_prompt_for_a_data_set_that_has_no_command_explains_why(monkeypatch):
    from src.tools import build_workflow
    monkeypatch.setitem(build_workflow.NOT_UPDATABLE, "runes", "no source for runes yet")
    text = prompt_text("update", {"scope": "runes"})
    assert "Do not call update_data" in text and "runes cannot be updated by command: no source for runes yet" in text


def test_update_prompt_for_the_glossary_repeats_until_done():
    text = prompt_text("update", {"scope": "glossary", "names": "Stun"})
    assert 'scope="glossary" and no other argument' in text and "While `done` is false" in text
    assert "at most 20 calls" in text and f"at most {mnt.GLOSSARY_BATCH}" in text and "Stun" not in text


def test_update_prompt_for_the_ladder_is_one_call_and_mentions_names_are_not_stored():
    text = prompt_text("update", {"scope": "ladder"})
    assert 'scope="ladder" and no other argument' in text and "poe.ninja" in text
    assert "never stored" in text and "dry_run" not in text


def test_ladder_update_through_the_server_is_visible_to_reference_builds(fresh, monkeypatch):
    from tests.ninja_support import LEAGUE, FakeNinja
    site = FakeNinja()
    monkeypatch.setattr(mnt.ladder, "_get_json", site.get_json)
    monkeypatch.setattr(mnt.ladder, "_get_binary", site.get_binary)
    with pytest.raises(ToolError, match="community builds"):
        call("reference_builds", {})                                # the fresh folder has no ladder file
    result = payload(call("update_data", {"scope": "ladder"}))
    assert result["records"] == 120 and result["league"] == LEAGUE
    builds = payload(call("reference_builds", {"class_name": "Titan", "limit": 3}))
    text = json.dumps(builds, ensure_ascii=False)
    assert builds["total_matching"] == 40 and builds["league"] == LEAGUE and "Secret" not in text


def test_update_prompt_for_a_gem_scope_starts_with_a_dry_run():
    text = prompt_text("update", {"scope": " Skill_Gems ", "names": "Leap Slam, 火球 ,"})
    assert "scope=\"skill_gems\", names=['Leap Slam', '火球']" in text
    assert text.index("dry_run=true") < text.index("dry_run=false")
    assert "more than 60" in text and "at most 10 calls" in text and "Do not call update_data with another scope" in text


def test_update_prompt_for_passives_has_no_dry_run_and_no_names():
    text = prompt_text("update", {"scope": "passives", "names": "Blood Magic"})
    assert 'scope="passives" and no other argument' in text and "dry_run" not in text and "Blood Magic" not in text


def test_update_prompt_arguments_are_optional_strings():
    prompts = {p.name: p for p in asyncio.run(mcp_server.server.list_prompts())}
    assert {a.name: a.required for a in prompts["update"].arguments} == {"scope": False, "names": False}
    assert prompts["status"].arguments in ([], None)


def test_instructions_say_updates_need_a_user_request_and_a_scope():
    assert "data_status" in mcp_server.INSTRUCTIONS and "update_data" in mcp_server.INSTRUCTIONS
    assert "only when the user asks" in mcp_server.INSTRUCTIONS and "exactly one scope" in mcp_server.INSTRUCTIONS


def test_unfinished_glossary_call_does_not_reload_the_service(fresh, monkeypatch):
    service, _ = fresh
    monkeypatch.setattr(mnt.DataMaintenance, "update", lambda self, scope, **kw: {"scope": scope, "done": False, "left": 9})
    assert payload(call("update_data", {"scope": "glossary"}))["done"] is False
    assert mcp_server._service is service
    monkeypatch.setattr(mnt.DataMaintenance, "update", lambda self, scope, **kw: {"scope": scope, "done": True})
    payload(call("update_data", {"scope": "glossary"}))
    assert mcp_server._service is not service


def test_update_prompt_description_lists_every_scope():
    prompts = {p.name: p for p in asyncio.run(mcp_server.server.list_prompts())}
    assert all(scope in prompts["update"].description for scope in mnt.UPDATE_SCOPES)
