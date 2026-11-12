"""
build_workflow.py — The cited-build workflow and the data commands as text.

One wording for every place that tells a model how to give build advice: the MCP prompt
`build_guide`, the MCP tool `build_workflow` (for clients without prompt support) and the MCP
server instructions. The plugin skill (skills/poe2-advisor/SKILL.md) repeats it for Claude
Code; a test keeps the tool names in sync. The `status` and `update` prompts (skills/status,
skills/update in the plugin) are the user-facing commands over data_status and update_data.
"""

from __future__ import annotations

from src.tools.maintenance import (
    GEM_SCOPES,
    GLOSSARY,
    GLOSSARY_BATCH,
    ITEMS,
    ITEMS_BATCH,
    LADDER,
    MAX_NAMES,
    NOT_UPDATABLE,
    PASSIVES,
    UPDATE_SCOPES,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_REQUEST_LEN = 2000
LANGUAGE_NAMES = {"en": "English", "zh-tw": "Traditional Chinese (繁體中文)"}
INTRO = "Give Path of Exile 2 build advice for the request below, using the pobg tools."
INTRO_NO_REQUEST = "How to give Path of Exile 2 build advice with the pobg tools:"

WRITING_RULES = (
    "Use only the verified facts for numbers, costs, tags and effects. "
    "Do not name a gem or passive that was not verified. "
    "When the data does not cover something, say that it is not in the local data."
)

BUILD_WORKFLOW = """\
1. Read the request and answer in the user's language.
2. Generate the build from the data, not from the ladder: gather candidates with lookup_entity, gems_by, supports_for, passives_with_stat, get_gem and get_passive.
   For gear, pick bases or uniques with items_by and get_item, and for each slot the target modifiers
   with modifiers_for, at most 3 prefixes and 3 suffixes, in order of importance (written
   "item: modifier", the whole modifier as modifiers_for shows it; for armour name the base).
   Every choice needs a reason from these records (what the gem, passive or item does), never
   "ladder characters use it".
3. Call verify_build once with every gem, passive, item and target modifier the draft build uses
   (lists take 40 entries, affixes 60). With a whole set of gear, or on a repeat check, pass
   detail="brief": you already hold the records from the lookups, and the answer is much smaller.
4. For each entry in `unverified`: drop the name, or replace it from its `suggestions` or a new search.
   Call verify_build again with the final list. Do this at most twice; after that, drop what is still unverified.
5. Call path_to with the class (or ascendancy) and the verified passives. State the points it reports
   against the limits; when `over` is true, drop the passives with the largest `added_points` and call it again.
6. Compare with the ladder: call reference_builds (class and/or main skill) now, after the build is
   drafted. Use it only to say how the build differs from what ladder characters run: what is the same,
   what this build uses that they do not, what they use that it does not, with counts. When the user
   asks what is popular, reference_builds is the answer itself.
7. Write the build from the `verified` facts, with a short "compared with the ladder" section. """ + WRITING_RULES + """ Modifiers are random: present the
   target modifiers as goals to look for, not as what the item will have, and say that damage is not calculated.
8. End the answer with `sources_markdown` from the last verify_build call, unchanged. It already lists
   the names that were not found. Add `source_markdown` from reference_builds below it.
9. Give a Path of Building code: call export_pob with the class (or ascendancy), the verified passives
   as `targets`, one "skill: support, support" entry per skill group, main skill first, and one
   "slot: item; modifier; modifier" entry per verified item in `gear` (a rare's verified target
   modifiers; nothing after a unique); pass `character_level` when the user asked for a build at
   a level. Gear values are written at the top of each modifier's best tier: say the PoB numbers
   are an ideal, since modifiers are random. The tool works out the character
   level, each gem's level and the attribute passives from the data: do not work them out yourself.
   Put `code` in a code block after the sources, with `how_to_import` and `notes`, say what is in
   `not_exported`, and report `summary.attributes` and `summary.spirit`: where `need` is above `have`,
   fix the build (other gems, fewer persistent skills or Spirit-reserving supports, attribute or Spirit
   modifiers on gear) and export again, or say plainly what is missing. List the PoB Configuration
   options in `summary.config` with their evidence: PoB's damage assumes them."""

SERVER_INSTRUCTIONS = (
    "Path of Exile 2 data from poe2db.tw (gems, passive tree, glossary), English and Traditional "
    "Chinese. Resolve names with lookup_entity first, then use get_gem / get_passive / "
    "explain_keyword / passives_with_stat / gems_by / supports_for, and for gear get_item / items_by / "
    "modifiers_for. Quote the returned records and "
    "cite the returned source URLs; do not answer numbers from memory. Use refresh_gem only when a "
    "record looks outdated (check fetched_at). "
    "For build advice: generate the build from these records, with a reason from the data for every "
    "choice (not \"ladder characters use it\"), then call verify_build with every gem, passive, item and target modifier "
    "(at most 3 prefixes and 3 suffixes per slot; modifiers are random, so present them as targets) "
    "the build names. Drop or "
    "replace each name it reports as unverified, call path_to with the class and the verified "
    "passives to get the point cost and allocation order, call reference_builds to say how the "
    "draft differs from what ladder characters run, write only from the verified facts, "
    "end the answer with the returned sources_markdown unchanged, and give the Path of Building "
    "code from export_pob after it. "
    "The build_workflow tool returns these steps in full. "
    "data_status reports what the local data holds and how old it is. update_data changes it: "
    "call it only when the user asks for an update, with exactly one scope."
)

SCOPE_LIST = ", ".join(UPDATE_SCOPES)
CONFIRM_ABOVE = 60   # gems: ask before fetching more than this many pages in one command
MAX_UPDATE_CALLS = 10
MAX_ITEMS_CALLS = 8      # 138 requests (69 pages in two languages), ITEMS_BATCH per call
MAX_GLOSSARY_CALLS = 20   # about 750 requests in all, GLOSSARY_BATCH per call

STATUS_STEPS = f"""\
Report the state of the local Path of Exile 2 data.

1. Call data_status. For each data set show the number of records, when it was fetched, its age in
   days, and whether a command can update it (`update_scope`).
2. Point out what is old, including the ladder snapshot and its league.
3. Ask whether to check the live sites. Only when the user agrees, call data_status with
   check_online=true (about 19 requests) and report `problems`: pages that no longer parse, or a newer
   passive tree version.
4. When something should be updated, name the command: update with one scope ({SCOPE_LIST})."""

UPDATE_NEEDS_SCOPE = f"""\
The update command needs exactly one scope. Do not call update_data.

Tell the user to choose one of: {SCOPE_LIST} (for example: update skill_gems). There is no update for
everything."""

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

ON_ERROR = "When a call returns an error, show the error and stop. Do not call update_data with another scope."

UPDATE_WHOLE_SET_STEPS = {
    PASSIVES: f"""\
1. Call update_data with scope="passives" and no other argument. It makes 8 requests: the
   PathOfBuilding-PoE2 tree and quest rewards, two poe2db tree data files and four listing pages.
2. Report `records`, `changed`, `added`, `removed` and the tree versions.
{ON_ERROR}""",
    GLOSSARY: f"""\
1. Call update_data with scope="glossary" and no other argument. One call makes at most {GLOSSARY_BATCH}
   requests to poe2db.tw and keeps its progress; nothing is written until the whole glossary is fetched.
2. While `done` is false, call it again, at most {MAX_GLOSSARY_CALLS} calls in total; give one line of
   progress per call (`fetched`, `left`).
3. When `done` is true, report `records`, `refreshed`, `changed`, `added` and `kept_without_refresh`.
   When it is still false after {MAX_GLOSSARY_CALLS} calls, tell the user to run the command again within 30
   minutes: it continues where it stopped.
{ON_ERROR}""",
    ITEMS: f"""\
1. Call update_data with scope="items"; to refresh only some item classes, pass their names (e.g.
   names=["Bows"] or ["Body Armours"]). One call makes at most {ITEMS_BATCH} requests (a page in two languages is two) and keeps its progress
   for 30 minutes;
   nothing is written until every page is fetched and checked.
2. While `done` is false, call it again with the same arguments, at most {MAX_ITEMS_CALLS} calls in total; give one
   line of progress per call (`fetched`, `left`).
3. When `done` is true, report `bases`, `uniques` and `modifiers`.
{ON_ERROR}""",
    LADDER: f"""\
1. Call update_data with scope="ladder" and no other argument. It makes at most 14 requests to poe.ninja
   and replaces the ladder snapshot; character and account names are never stored.
2. Report `records` and `league`, and `previous_league` when the league changed.
{ON_ERROR}""",
}

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
    picked = [name.strip()[:120] for name in str(names or "").split(",") if name.strip()][:MAX_NAMES]
    if wanted == ITEMS and picked:
        return (f"Update the local Path of Exile 2 data, scope {wanted}, item classes {picked!r}.\n\n"
                f"Arguments: scope=\"{wanted}\", names={picked!r}.\n\n{UPDATE_WHOLE_SET_STEPS[wanted]}")
    if wanted not in GEM_SCOPES:
        return f"Update the local Path of Exile 2 data, scope {wanted}.\n\n{UPDATE_WHOLE_SET_STEPS[wanted]}"
    arguments = f'scope="{wanted}"' + (f", names={picked!r}" if picked else "")
    return (f"Update the local Path of Exile 2 data, scope {wanted}.\n\n"
            f"Arguments: {arguments}. When the user asked for gems older than N days, add older_than_days=N.\n\n"
            f"{UPDATE_GEM_STEPS}")
