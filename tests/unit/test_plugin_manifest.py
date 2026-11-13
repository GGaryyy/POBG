import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:   # Python 3.10
    import tomli as tomllib

from src import __version__
from src.scrapers.common import USER_AGENT
from src.tools import build_workflow
from src.tools.mcp_server import server

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MARKET = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
CODEX = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
CODEX_MCP = json.loads((ROOT / ".codex-plugin" / "mcp.json").read_text(encoding="utf-8"))
CODEX_MARKET = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SKILL = (ROOT / "skills" / "poe2-advisor" / "SKILL.md").read_text(encoding="utf-8")
REPO_URL = "https://github.com/GGaryyy/POBG"
# The advisor skill is the workflow for Claude Code, so it does not need the tool that returns the
# workflow; the data tools belong to the status and update skills.
WORKFLOW_TOOL = "build_workflow"
DATA_TOOLS = {"data_status", "update_data"}
STATUS_SKILL = (ROOT / "skills" / "status" / "SKILL.md").read_text(encoding="utf-8")
UPDATE_SKILL = (ROOT / "skills" / "update" / "SKILL.md").read_text(encoding="utf-8")
HEAVY_MODULES = ("faiss", "torch", "langchain", "langchain_core", "langgraph", "sentence_transformers", "fastapi")
TOOL_LIKE = re.compile(r"\b(?:lookup_entity|get_\w+|explain_\w+|passives_\w+|gems_\w+|supports_\w+|"
                       r"reference_\w+|verify_\w+|refresh_\w+|path_to|export_pob|build_workflow|data_status|update_data|items_by|modifiers_for)\b")


def tool_names() -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}


def requirement_name(line: str) -> str:
    return re.split(r"[\[<>=!~; ]", line.strip(), maxsplit=1)[0].lower()


def test_versions_agree():
    assert PLUGIN["version"] == CODEX["version"] == PYPROJECT["project"]["version"] == __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_names_agree():
    assert PLUGIN["name"] == server.name == "pobg"
    assert MARKET["name"] == PYPROJECT["project"]["name"] == "pobg"
    assert [p["name"] for p in MARKET["plugins"]] == ["pobg"] and MARKET["plugins"][0]["source"] == "./"
    assert list(PLUGIN["mcpServers"]) == ["pobg"]
    assert PLUGIN["repository"] == REPO_URL and REPO_URL in USER_AGENT
    assert MARKET["owner"]["name"] == PLUGIN["author"]["name"]
    assert MARKET["metadata"]["description"] and PLUGIN["description"]


def test_the_codex_plugin_matches_the_claude_one():
    assert CODEX["name"] == CODEX_MARKET["name"] == "pobg" and CODEX["description"] == PLUGIN["description"]
    assert CODEX["repository"] == PLUGIN["repository"] and CODEX["author"] == PLUGIN["author"]
    assert [p["name"] for p in CODEX_MARKET["plugins"]] == ["pobg"]
    assert CODEX_MARKET["plugins"][0]["source"] == {"source": "local", "path": "./"}
    assert CODEX["skills"] == "./skills/" and (ROOT / CODEX["mcpServers"]).is_file()
    assert len(CODEX["interface"]["shortDescription"]) <= 30                     # Codex's limit for the subtitle
    assert list(CODEX_MCP["mcpServers"]) == ["pobg"]


def test_the_codex_launcher_starts_the_same_server_from_the_plugin_folder():
    claude, codex = PLUGIN["mcpServers"]["pobg"], CODEX_MCP["mcpServers"]["pobg"]
    assert codex["command"] == claude["command"] == "uv" and codex["cwd"] == "."
    assert codex["args"] == [("." if arg == "${CLAUDE_PLUGIN_ROOT}" else arg) for arg in claude["args"]]
    assert "CLAUDE" not in json.dumps(codex)                                       # Codex does not expand them


def test_skills_name_the_commands_for_both_hosts():
    for name in ("status", "update", "poe2-advisor"):
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        flat = " ".join(text.split())
        assert "in Claude Code" in flat and "in Codex" in flat, name
    update_pob = (ROOT / "skills" / "update-pob" / "SKILL.md").read_text(encoding="utf-8")
    assert update_pob.count("${CLAUDE_PLUGIN_ROOT}") == 1 and "in Codex, the folder two levels" in update_pob


def test_plugin_launcher_is_portable():
    launcher = PLUGIN["mcpServers"]["pobg"]
    assert launcher["command"] == "uv"
    assert launcher["args"] == ["run", "--frozen", "--no-dev", "--directory", "${CLAUDE_PLUGIN_ROOT}", "python",
                                "-m", "src.tools.mcp_server"]
    assert launcher["env"] == {"UV_PROJECT_ENVIRONMENT": "${CLAUDE_PLUGIN_DATA}/venv"}
    assert not any(".venv" in arg or arg.startswith("/") for arg in launcher["args"])


def test_lock_file_is_shipped_and_matches_the_project():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"] for p in lock["package"]}
    for dep in PYPROJECT["project"]["dependencies"]:
        assert requirement_name(dep) in locked
    assert not locked & {"faiss-cpu", "torch", "langchain", "langgraph", "sentence-transformers"}


def test_runtime_dependencies_stay_lean_and_tests_live_in_the_dev_group():
    lean = {requirement_name(dep) for dep in PYPROJECT["project"]["dependencies"]}
    assert lean == {"mcp", "networkx", "requests", "beautifulsoup4"}
    assert "pytest" in {requirement_name(dep) for dep in PYPROJECT["dependency-groups"]["dev"]}
    assert PYPROJECT["tool"]["uv"]["package"] is False


def test_the_plugin_is_the_only_place_that_registers_the_server():
    # a project .mcp.json would register a second, identical server next to the plugin's
    assert not (ROOT / ".mcp.json").exists()


def test_skill_frontmatter():
    head = SKILL.split("---")[1]
    assert re.search(r"^name: poe2-advisor$", head, re.MULTILINE)
    assert re.search(r"^description: .{40,}$", head, re.MULTILINE)


def test_skill_names_only_real_tools_and_all_of_them():
    named = set(TOOL_LIKE.findall(SKILL))
    assert named == tool_names() - {WORKFLOW_TOOL} - DATA_TOOLS


@pytest.mark.parametrize("text_name", ["BUILD_WORKFLOW", "SERVER_INSTRUCTIONS"])
def test_workflow_texts_name_only_real_tools(text_name):
    named = set(TOOL_LIKE.findall(getattr(build_workflow, text_name)))
    assert named and named <= tool_names()
    assert "verify_build" in named


def test_build_workflow_covers_the_build_tools():
    named = set(TOOL_LIKE.findall(build_workflow.BUILD_WORKFLOW))
    assert {"reference_builds", "supports_for", "gems_by", "verify_build", "lookup_entity"} <= named


def test_skill_and_workflow_share_the_ending_rule():
    for text in (SKILL, build_workflow.BUILD_WORKFLOW, build_workflow.SERVER_INSTRUCTIONS):
        assert "sources_markdown" in text


def test_server_version_is_the_package_version():
    assert server.version == __version__


def test_mcp_server_import_stays_lean():
    code = ("import sys, src.tools.mcp_server\n"
            f"heavy = [m for m in {HEAVY_MODULES!r} if m in sys.modules]\n"
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
    assert out.stdout.strip() == ""


def test_catalog_skill_points_to_the_advisor():
    text = (ROOT / ".claude" / "skills" / "poe2db-catalog" / "SKILL.md").read_text(encoding="utf-8")
    assert "poe2-advisor" in text


def test_server_instructions_name_the_workflow_tool_and_it_exists():
    assert "build_workflow" in set(TOOL_LIKE.findall(build_workflow.SERVER_INSTRUCTIONS)) <= tool_names()


def frontmatter(skill: str) -> dict[str, str]:
    lines = skill.split("---")[1].strip().splitlines()
    return {key.strip(): value.strip() for key, value in (line.split(":", 1) for line in lines)}


def test_status_skill_only_reads():
    head = frontmatter(STATUS_SKILL)
    assert head["name"] == "status" and len(head["description"]) >= 40
    assert "disable-model-invocation" not in head
    assert set(TOOL_LIKE.findall(STATUS_SKILL.split("---", 2)[2])) == DATA_TOOLS      # names update_data only to forbid it
    assert "Do not call `update_data` from this skill" in STATUS_SKILL


def test_update_skill_is_user_invoked_and_requires_a_scope():
    head = frontmatter(UPDATE_SKILL)
    assert head["name"] == "update" and head["disable-model-invocation"] == "true"
    assert head["argument-hint"].startswith("<skill_gems|spirit_gems|support_gems|passives|items|glossary|ninja>")
    body = UPDATE_SKILL.split("---", 2)[2]
    assert "$ARGUMENTS" in body and "do not call `update_data`" in body
    assert set(TOOL_LIKE.findall(body)) == {"update_data"}
    assert body.index("dry_run: true") < body.index("dry_run: false")


def test_skills_and_prompts_list_the_same_scopes():
    from src.tools.maintenance import UPDATE_SCOPES
    for text in (UPDATE_SKILL, STATUS_SKILL, build_workflow.STATUS_STEPS, build_workflow.UPDATE_NEEDS_SCOPE):
        assert all(scope in text for scope in UPDATE_SCOPES)


def test_update_limits_in_the_texts_match_the_code():
    from src.tools.maintenance import MAX_GEMS
    assert f"more than {build_workflow.CONFIRM_ABOVE}" in UPDATE_SKILL and f"at most {build_workflow.MAX_UPDATE_CALLS} calls" in UPDATE_SKILL
    from src.tools.maintenance import GLOSSARY_BATCH
    skill = " ".join(UPDATE_SKILL.split())
    assert f"at most {build_workflow.MAX_GLOSSARY_CALLS} calls" in skill and f"at most {GLOSSARY_BATCH} requests" in skill
    assert f"after {build_workflow.MAX_GLOSSARY_CALLS} calls" in skill and "within 30 minutes" in skill
    description = " ".join({t.name: t for t in asyncio.run(server.list_tools())}["update_data"].description.split())
    from src.tools.maintenance import ITEMS_BATCH
    assert f"glossary at most {GLOSSARY_BATCH} requests per call" in description
    assert f"items at most {build_workflow.MAX_ITEMS_CALLS} calls, glossary {build_workflow.MAX_GLOSSARY_CALLS}" in description
    assert f"at most {ITEMS_BATCH} requests per call" in description
    assert f"at most {ITEMS_BATCH} requests (10 class pages" in skill and f"at most {build_workflow.MAX_ITEMS_CALLS} calls" in skill
    assert f"(1-{MAX_GEMS})" in {t.name: t for t in asyncio.run(server.list_tools())}["update_data"].description


def test_project_rules_live_under_dot_claude_not_at_the_plugin_root():
    # a CLAUDE.md at the plugin root is not loaded by plugin users and fails strict validation
    assert not (ROOT / "CLAUDE.md").exists()
    assert (ROOT / ".claude" / "CLAUDE.md").read_text(encoding="utf-8").startswith("# Project Rules")


def test_the_ladder_is_for_comparison_not_for_choosing():
    from src.tools.build_workflow import BUILD_WORKFLOW, SERVER_INSTRUCTIONS
    skill = (ROOT / "skills" / "poe2-advisor" / "SKILL.md").read_text(encoding="utf-8")
    for text in (BUILD_WORKFLOW, skill):
        flat = " ".join(text.split())
        assert "Generate the build from the data, not from the ladder" in flat
        assert flat.index("verify_build") < flat.index("Compare with the ladder") < flat.index("sources_markdown")
        assert "Optional" not in flat.split("Compare with the ladder")[0].split("Generate the build")[1]
    assert "differs from what ladder characters run" in SERVER_INSTRUCTIONS


def test_update_pob_skill_is_user_invoked_checks_first_and_asks_before_downloading():
    text = (ROOT / "skills" / "update-pob" / "SKILL.md").read_text(encoding="utf-8")
    head = frontmatter(text)
    assert head["name"] == "update-pob" and head["disable-model-invocation"] == "true"
    body = " ".join(text.split("---", 2)[2].split())
    assert "$ARGUMENTS" in body and "Do not search the disk" in body
    command = 'uv run --directory "<plugin folder>" python -m src.tools.pob_update --dir "<folder>"'
    assert body.index(command + " --check") < body.index("Only after the user agrees") < body.rindex(command)
    assert "Never delete the old folder" in body and not TOOL_LIKE.findall(body.replace("export_pob", ""))
    assert "600000 ms" in body and "do not run anything" in body and "poecharm_latest_date" in body
    from src.tools import pob_update
    assert pob_update.MANIFEST in body and pob_update.CHARM_EXE in body


def test_advisor_points_to_the_update_pob_command():
    skill = (ROOT / "skills" / "poe2-advisor" / "SKILL.md").read_text(encoding="utf-8")
    assert "/pobg:update-pob" in skill and "$pobg:update-pob" in skill
    assert (ROOT / "skills" / "update-pob" / "SKILL.md").is_file()
