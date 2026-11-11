"""
build_workflow.py — The cited-build workflow and the data commands as text.

One wording for every place that tells a model how to give build advice: the MCP prompt
`build_guide`, the MCP tool `build_workflow` (for clients without prompt support) and the MCP
server instructions. The plugin skill (skills/poe2-advisor/SKILL.md) repeats it for Claude
Code; a test keeps the tool names in sync. The `status` and `update` prompts (skills/status,
skills/update in the plugin) are the user-facing commands over data_status and update_data.
"""

from __future__ import annotations

from src.tools.maintenance import GEM_SCOPES, MAX_NAMES, NOT_UPDATABLE, UPDATE_SCOPES

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_REQUEST_LEN = 2000
LANGUAGE_NAMES = {"en": "English", "zh-tw": "Traditional Chinese (繁體中文)"}
INTRO = "Give Path of Exile 2 build advice for the request below, using the poe2db tools."
INTRO_NO_REQUEST = "How to give Path of Exile 2 build advice with the poe2db tools:"

WRITING_RULES = (
    "Use only the verified facts for numbers, costs, tags and effects. "
    "Do not name a gem or passive that was not verified. "
    "When the data does not cover something, say that it is not in the local data."
)

BUILD_WORKFLOW = """\
1. Read the request and answer in the user's language.
2. Optional: call reference_builds (class and/or main skill) to see what ladder characters run.
3. Gather candidates with lookup_entity, gems_by, supports_for, passives_with_stat, get_gem and get_passive.
4. Call verify_build with every gem and passive name the draft build uses.
5. For each entry in `unverified`: drop the name, or replace it from its `suggestions` or a new search.
   Call verify_build again with the final list. Do this at most twice; after that, drop what is still unverified.
6. Call path_to with the class (or ascendancy) and the verified passives. State the points it reports
   against the limits; when `over` is true, drop the passives with the largest `added_points` and call it again.
7. Write the build from the `verified` facts. """ + WRITING_RULES + """
8. End the answer with `sources_markdown` from the last verify_build call, unchanged. It already lists
   the names that were not found. Add `source_markdown` from reference_builds when step 2 was used."""

SERVER_INSTRUCTIONS = (
    "Path of Exile 2 data from poe2db.tw (gems, passive tree, glossary), English and Traditional "
    "Chinese. Resolve names with lookup_entity first, then use get_gem / get_passive / "
    "explain_keyword / passives_with_stat / gems_by / supports_for. Quote the returned records and "
    "cite the returned source URLs; do not answer numbers from memory. Use refresh_gem only when a "
    "record looks outdated (check fetched_at). "
    "For build advice: gather candidates with the tools above (reference_builds shows what ladder "
    "characters run), then call verify_build with every gem and passive the build names. Drop or "
    "replace each name it reports as unverified, call path_to with the class and the verified "
    "passives to get the point cost and allocation order, write only from the verified facts, and "
    "end the answer with the returned sources_markdown unchanged. "
    "The build_workflow tool returns these steps in full. "
    "data_status reports what the local data holds and how old it is. update_data changes it: "
    "call it only when the user asks for an update, with exactly one scope."
)

SCOPE_LIST = ", ".join(UPDATE_SCOPES)
CONFIRM_ABOVE = 60   # gems: ask before fetching more than this many pages in one command
MAX_UPDATE_CALLS = 10

STATUS_STEPS = f"""\
Report the state of the local Path of Exile 2 data.

1. Call data_status. For each data set show the number of records, when it was fetched, its age in
   days, and whether a command can update it (`update_scope`).
2. Point out what is old, including the ladder snapshot and its league, and what `not_updatable` says.
3. Ask whether to check the live sites. Only when the user agrees, call data_status with
   check_online=true (about 19 requests) and report `problems`: pages that no longer parse, or a newer
   passive tree version.
4. When something should be updated, name the command: update with one scope ({SCOPE_LIST})."""

UPDATE_NEEDS_SCOPE = f"""\
The update command needs exactly one scope. Do not call update_data.

Tell the user to choose one of: {SCOPE_LIST} (for example: update skill_gems). There is no update for
everything. The glossary and the ladder snapshot cannot be updated by command; data_status says why."""

UPDATE_GEM_STEPS = f"""\
1. Call update_data with the arguments above and dry_run=true. Tell the user what it found: `selected`,
   `reasons`, `added`, `removed`.
2. When `selected` is 0, say this data set is up to date and stop.
3. When `selected` is more than {CONFIRM_ABOVE}, stop and ask the user to confirm: every gem is one request
   to poe2db.tw, 0.8 s apart.
4. Call update_data with the same arguments and dry_run=false. While `left` is greater than 0, call it
   again, at most {MAX_UPDATE_CALLS} calls in total; give one line of progress per call.
5. Report the totals (`updated`, `added`, `removed`) and anything in `skipped`.
When a call returns an error, show the error and stop. Do not call update_data with another scope."""

UPDATE_PASSIVE_STEPS = """\
1. Call update_data with scope="passives" and no other argument. It makes 7 requests: the
   PathOfBuilding-PoE2 tree, two poe2db tree data files and four listing pages.
2. Report `records`, `changed`, `added`, `removed` and the tree versions.
When the call returns an error, show the error and stop. Do not call update_data with another scope."""

# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def build_guide_text(request: str, lang: str = "en") -> str:
    """The prompt a client sends to start a cited build answer."""
    language = LANGUAGE_NAMES.get((lang or "en").strip().lower(), LANGUAGE_NAMES["en"])
    request = " ".join(str(request).split())[:MAX_REQUEST_LEN]
    return (
        f"{INTRO}\n\n"
        f"Request: {request}\n"
        f"Answer language: {language}\n\n"
        f"{BUILD_WORKFLOW}"
    )


def build_workflow_text(lang: str = "en") -> str:
    """The same steps without a request, for clients that can call tools but not prompts."""
    language = LANGUAGE_NAMES.get((lang or "en").strip().lower(), LANGUAGE_NAMES["en"])
    return f"{INTRO_NO_REQUEST}\n\nAnswer language: {language}\n\n{BUILD_WORKFLOW}"


def status_prompt_text() -> str:
    """The `status` command."""
    return STATUS_STEPS


def update_prompt_text(scope: str = "", names: str = "") -> str:
    """The `update` command: steps for one scope, or a refusal that lists the scopes."""
    wanted = " ".join(str(scope or "").split()).lower()
    if wanted not in UPDATE_SCOPES:
        reason = f"\n\n{wanted} cannot be updated by command: {NOT_UPDATABLE[wanted]}" if wanted in NOT_UPDATABLE else ""
        return UPDATE_NEEDS_SCOPE + reason
    if wanted not in GEM_SCOPES:
        return f"Update the local Path of Exile 2 data, scope {wanted}.\n\n{UPDATE_PASSIVE_STEPS}"
    picked = [name.strip()[:120] for name in str(names or "").split(",") if name.strip()][:MAX_NAMES]
    arguments = f'scope="{wanted}"' + (f", names={picked!r}" if picked else "")
    return (f"Update the local Path of Exile 2 data, scope {wanted}.\n\n"
            f"Arguments: {arguments}. When the user asked for gems older than N days, add older_than_days=N.\n\n"
            f"{UPDATE_GEM_STEPS}")
