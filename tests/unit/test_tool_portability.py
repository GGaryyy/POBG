"""Limits that MCP clients other than Claude Code place on tool definitions."""
import asyncio
import json
import re

import pytest

from src.tools.mcp_server import server

pytestmark = pytest.mark.unit

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")   # OpenAI and Gemini function-name rule
MAX_DESCRIPTION = 1024                                 # OpenAI function-description limit
WRITING_TOOLS = {"refresh_gem", "update_data"}
NETWORK_READERS = {"data_status"}      # read-only, but can reach the live sites when asked
SIMPLE_TYPES = {"string", "integer", "number", "boolean", "null"}

TOOLS = asyncio.run(server.list_tools())
IDS = [t.name for t in TOOLS]


@pytest.mark.parametrize("tool", TOOLS, ids=IDS)
def test_name_fits_every_client(tool):
    assert NAME_PATTERN.fullmatch(tool.name)


@pytest.mark.parametrize("tool", TOOLS, ids=IDS)
def test_description_is_present_and_short_enough(tool):
    assert 40 <= len(tool.description.strip()) <= MAX_DESCRIPTION


@pytest.mark.parametrize("tool", TOOLS, ids=IDS)
def test_title_is_a_short_human_label(tool):
    assert tool.title and 3 <= len(tool.title) <= 40 and tool.title != tool.name


@pytest.mark.parametrize("tool", TOOLS, ids=IDS)
def test_input_schema_is_a_flat_object(tool):
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    for name, prop in schema["properties"].items():
        variants = prop.get("anyOf", [prop])
        for variant in variants:
            assert variant["type"] in SIMPLE_TYPES | {"array"}, (tool.name, name)
            if variant["type"] == "array":
                assert variant["items"] == {"type": "string"}, (tool.name, name)
    assert set(schema.get("required", [])) <= set(schema["properties"])


@pytest.mark.parametrize("tool", TOOLS, ids=IDS)
def test_annotations_tell_read_only_tools_from_the_one_that_writes(tool):
    hints = tool.annotations
    assert hints is not None
    if tool.name in WRITING_TOOLS:
        assert hints.read_only_hint is False and hints.open_world_hint is True
        assert hints.destructive_hint is True and hints.idempotent_hint is True
    else:
        assert hints.read_only_hint is True
        assert hints.open_world_hint is (tool.name in NETWORK_READERS)


def test_only_the_refresh_and_update_tools_write():
    assert {t.name for t in TOOLS if not t.annotations.read_only_hint} == WRITING_TOOLS


def test_annotations_use_the_wire_names():
    dumped = TOOLS[0].model_dump(by_alias=True, exclude_none=True)
    assert dumped["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
    assert "inputSchema" in dumped and "title" in dumped
    for writer in (t for t in TOOLS if t.name in WRITING_TOOLS):
        assert writer.model_dump(by_alias=True, exclude_none=True)["annotations"] == {
            "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True}
