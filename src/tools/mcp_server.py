"""
mcp_server.py — the POBG MCP server: Path of Exile 2 lookup, build and data tools over stdio.

    python -m src.tools.mcp_server

Any MCP client can start it (docs/clients.md); the Claude Code plugin manifest and the project
.mcp.json register it as "pobg". The lookup and build tools answer from local data and return
poe2db source URLs. Three tools can reach the network: `refresh_gem` (one gem page),
`update_data` (one data set, a bounded number of pages) and `data_status` when asked to check
the live sites.
`verify_build` plus the `build_guide` prompt (or the `build_workflow` tool, for clients without
prompt support) are the cited-build workflow.
"""

from __future__ import annotations

import functools
import threading

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from src import __version__
from src.tools.build_tools import BuildTools
from src.tools.build_workflow import (
    SERVER_INSTRUCTIONS,
    build_guide_text,
    build_workflow_text,
    status_prompt_text,
    update_prompt_text,
)
from src.tools.lookup import LookupFailed, LookupService, answer_lang
from src.tools.maintenance import DEFAULT_MAX_GEMS, DataMaintenance

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SERVER_NAME = "pobg"
INSTRUCTIONS = SERVER_INSTRUCTIONS
# Hints for clients: refresh_gem and update_data fetch from the sources and replace stored records
# (a destructive update in MCP terms); data_status only reads, but can probe the live sites.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_ONLY_NETWORK = ToolAnnotations(read_only_hint=True, open_world_hint=True)
NETWORK_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                                open_world_hint=True)

server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, version=__version__)
_service: LookupService | None = None
_tools: BuildTools | None = None
_service_lock = threading.Lock()


def service() -> LookupService:
    """Load the data once, on first use (tools run in worker threads, hence the lock)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = LookupService()
    return _service


def build_tools() -> BuildTools:
    """Build helpers bound to the current lookup service."""
    global _tools
    lookup = service()
    with _service_lock:
        if _tools is None or _tools.lookup is not lookup:
            _tools = BuildTools(lookup)
    return _tools


def maintenance() -> DataMaintenance:
    """Bound to the loaded service's folder when there is one. Status must work even when the
    data cannot be loaded, so this never loads it."""
    with _service_lock:
        current = _service
    if current is None:
        return DataMaintenance()
    return DataMaintenance(current.base_dir, current.spec, current.graph_path)


def _reload_service() -> None:
    """After an update: later calls in this session answer from the new files."""
    global _service
    with _service_lock:
        current = _service
    if current is None:
        return
    try:    # built outside the lock: loading takes about a second and must not block other tools
        fresh = LookupService(base_dir=current.base_dir, spec=current.spec, graph_path=current.graph_path)
    except (ValueError, OSError) as exc:
        raise ToolError(f"the data was updated, but reloading it failed ({exc}); restart the server") from exc
    with _service_lock:
        _service = fresh


def _user_errors(fn):
    """Turn lookup errors into ToolError so their message (hints included) reaches the model."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LookupFailed as exc:
            raise ToolError(str(exc)) from exc
    return wrapper


# ---------------------------------------------------------------------------
# TOOLS
# ---------------------------------------------------------------------------


@server.tool(title="Find a gem, passive or term by name", annotations=READ_ONLY)
@_user_errors
def lookup_entity(query: str, kind: str | None = None, limit: int = 5) -> dict:
    """Resolve a gem, passive node or ascendancy name (English or 繁體中文) to its slug, kind and
    poe2db URLs. kind filters to one of: skill_gem, spirit_gem, support_gem, passive_keystone,
    passive_notable, passive_ascendancy, keyword. Matches are exact, then prefix, then substring."""
    return service().lookup_entity(query, kind=kind, limit=limit)


@server.tool(title="Gem record", annotations=READ_ONLY)
@_user_errors
def get_gem(slug_or_name: str) -> dict:
    """Full record of one gem: tier, tags, cost, requirements, per-level effects, quality,
    hidden stats, glossary terms, supports (for skills) or supported skills (for supports),
    plus poe2db sources with fetched_at."""
    return service().get_gem(slug_or_name)


@server.tool(title="Passive node record", annotations=READ_ONLY)
@_user_errors
def get_passive(slug_or_id: str) -> dict:
    """One passive node by poe2db slug, tree id or name: type, stats (en + zh-TW), ascendancy,
    class start, glossary terms, neighbouring nodes and its source (poe2db page or PoB2 tree)."""
    return service().get_passive(slug_or_id)


@server.tool(title="Passives that give a stat", annotations=READ_ONLY)
@_user_errors
def passives_with_stat(query: str, lang: str | None = None, kind: str | None = None,
                       include_without_page: bool = False, limit: int = 50) -> dict:
    """Which passive nodes give a stat, e.g. "attack speed", "critical hit chance", "攻擊速度".
    Results are grouped by stat family; nodes with a poe2db page are listed first, small /
    attribute nodes (PoB2 data) are summarised unless include_without_page is true.
    kind narrows to increased, reduced, more, less, flat, flat_percent, chance, of, ...; when no
    stat has that kind the result lists `available_kinds`. At most 100 nodes per list."""
    return service().passives_with_stat(query, lang=lang, kind=kind,
                                        include_without_page=include_without_page, limit=limit)


@server.tool(title="Glossary explanation", annotations=READ_ONLY)
@_user_errors
def explain_keyword(query: str, lang: str | None = None) -> dict:
    """Official glossary explanation of a game term (slug like "Critical_Hits", or a name in
    English / 繁體中文), related terms, and which gems and passives mention it."""
    return service().explain_keyword(query, lang=lang)


@server.tool(title="Filter gems", annotations=READ_ONLY)
@_user_errors
def gems_by(tag: str | None = None, tier: int | None = None, class_name: str | None = None,
            weapon: str | None = None, kind: str | None = None, limit: int = 50,
            text: str | None = None) -> dict:
    """Filter gems by tag (e.g. "Fire", "Minions"), tier, gemcutting class (e.g. "Witch" or the
    group label "Occult"), required weapon (substring), kind (skill_gem, spirit_gem,
    support_gem) and/or text (English substring of the name, description or stat lines, e.g.
    "rage"). At least one filter is required."""
    return service().gems_by(tag=tag, tier=tier, class_name=class_name, weapon=weapon, kind=kind, limit=limit,
                             text=text)


@server.tool(title="Support gems for a skill", annotations=READ_ONLY)
@_user_errors
def supports_for(skill: str, tag: str | None = None, limit: int = 50) -> dict:
    """Every support gem that can support a skill or spirit gem (name in English or 繁體中文),
    lowest tier first, optionally narrowed by tag. `total` counts all of them."""
    return build_tools().supports_for(skill, tag=tag, limit=limit)


@server.tool(title="Ladder reference builds", annotations=READ_ONLY)
@_user_errors
def reference_builds(class_name: str | None = None, main_skill: str | None = None, limit: int = 5,
                     lang: str | None = None) -> dict:
    """What ladder characters run, from the local poe.ninja snapshot: top builds (class, main
    skill, rank, gems, keystones; no character names) and the most common main skills, other
    gems and keystones among the matches. Filter by class_name and/or main_skill; when nothing
    matches, `available_classes` lists the class names in the snapshot."""
    return build_tools().reference_builds(class_name=class_name, main_skill=main_skill, limit=limit, lang=lang)


@server.tool(title="Verify a draft build", annotations=READ_ONLY)
@_user_errors
def verify_build(gems: list[str] | None = None, passives: list[str] | None = None,
                 lang: str | None = None) -> dict:
    """Check every gem and passive name of a draft build against local poe2db data. Names that
    match exactly (English, 繁體中文, slug or tree id) come back under `verified` with their real
    facts and a `cite` number; the others are listed in `unverified` with close names as
    suggestions. `sources_markdown` is the finished Sources section in the answer language
    (lang: en or zh-tw): end the build answer with it, unchanged. At most 40 names per list,
    120 characters per name."""
    return build_tools().verify_build(gems=gems, passives=passives, lang=lang)


@server.tool(title="Passive tree route and point cost", annotations=READ_ONLY)
@_user_errors
def path_to(class_name: str, targets: list[str], ascendancy: str | None = None, lang: str | None = None) -> dict:
    """Which passive nodes to allocate, in order, to reach `targets` (passive names in English or
    繁體中文, slugs or tree ids; at most 40) from a class start, and what it costs. `class_name` is
    a class or ascendancy (English or 繁體中文). Returns `points` used against the limits (123
    passive, 8 ascendancy), the ordered `path` with each node's stats, `stat_totals` for the whole
    route, per-target `points_alone` / `added_points`, plus `unverified` and `unreachable`
    targets. The route is a good approximation, not a guaranteed minimum."""
    return build_tools().path_to(class_name, targets, ascendancy=ascendancy, lang=lang)


@server.tool(title="Re-fetch one gem page", annotations=NETWORK_WRITE)
@_user_errors
def refresh_gem(slug_or_name: str) -> dict:
    """Re-fetch one gem's poe2db page now, update the local record and report which fields
    changed. Network call; use when fetched_at is old or the user says a patch changed it."""
    return service().refresh_gem(slug_or_name)


@server.tool(title="Build advice workflow", annotations=READ_ONLY)
@_user_errors
def build_workflow(lang: str = "en") -> dict:
    """The step-by-step workflow for a cited Path of Exile 2 build answer (gather candidates,
    verify_build, path_to, write from verified facts, end with the source list). Call it once
    before giving build advice. lang is the answer language: en or zh-tw. Clients with prompt
    support get the same text from the build_guide prompt."""
    normalised = answer_lang(lang)
    return {"lang": normalised, "workflow": build_workflow_text(normalised)}


@server.tool(title="Data status", annotations=READ_ONLY_NETWORK)
@_user_errors
def data_status(check_online: bool = False) -> dict:
    """What the local data holds: per data set the record count, when it was fetched, its age in
    days and whether update_data can update it; the passive tree versions; the ladder snapshot's
    date and league. No network unless check_online is true, which probes the live sites (about
    19 requests) and adds `online`: pages that no longer parse and newer passive tree versions."""
    tool = maintenance()
    status = tool.status()
    if check_online:
        status["online"] = tool.online_check()
    return status


@server.tool(title="Update one data set", annotations=NETWORK_WRITE)
@_user_errors
def update_data(scope: str, names: list[str] | None = None, older_than_days: int | None = None,
                max_gems: int = DEFAULT_MAX_GEMS, dry_run: bool = False) -> dict:
    """Re-fetch one data set from its source and replace the local records. Call it only when the
    user asks for an update. scope is required, one per call (there is no update for everything):
    skill_gems, spirit_gems, support_gems, passives, glossary or ladder. Gem scopes fetch the
    listing, then the gems that are new, changed, broken, named in `names` or older than
    `older_than_days`, at most max_gems (1-40) per call; repeat while `left` is above 0, at most
    10 calls. A gem fetched in the last 15 minutes is not fetched again for `names` or
    `older_than_days`. dry_run reports what would be fetched and writes nothing. The other scopes
    take no other argument: passives (7 requests), ladder (at most 14, poe.ninja), glossary (at most
    50 per call; repeat while `done` is false, at most 20 calls). A source that no longer parses
    aborts with nothing written."""
    result = maintenance().update(scope, names=names, older_than_days=older_than_days, max_gems=max_gems,
                                  dry_run=dry_run)
    if not dry_run:
        _reload_service()
    return result


# ---------------------------------------------------------------------------
# PROMPTS
# ---------------------------------------------------------------------------


@server.prompt()
def build_guide(request: str, lang: str = "en") -> str:
    """Start a cited Path of Exile 2 build answer: the request plus the step-by-step workflow
    (gather candidates, verify_build, write from verified facts, end with the source list)."""
    return build_guide_text(request, lang)


@server.prompt()
def status() -> str:
    """Show what the local Path of Exile 2 data holds and how old it is."""
    return status_prompt_text()


@server.prompt()
def update(scope: str = "", names: str = "") -> str:
    """Update one data set from its source. scope: skill_gems, spirit_gems, support_gems or
    passives. names: optional gem names, comma-separated."""
    return update_prompt_text(scope, names)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
