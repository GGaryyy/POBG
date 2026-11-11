# Plan: data commands — `status` and scoped `update` (0.7.0, before the first public push)

Approved 2026-11-11.
It continues Phase 15 (`docs/plan_public_release.md`); all work is in the new folder.

## Context

The README has no user-facing command for the data: updating means six terminal commands, and
from an AI client only `refresh_gem` (one gem) exists. The user wants commands such as
`/poe2db status` and `/poe2db update`, with two rules: **status is required**, and **update must
name a scope** (skill gems, passives, …) — there is no "update everything".

Decisions (user, 2026-11-11):

| Topic | Decision |
|---|---|
| `status` | Must exist |
| `update` | A scope is mandatory; no full crawl from a command |
| `poe2-advisor` | Stays as it is (a skill that tells Claude Code how to answer; not a data command) |
| poe.ninja fetcher | Keep it, but send the project's identifying User-Agent instead of a browser one. Test with one small request; if poe.ninja refuses, report back and keep only the existing snapshot |
| `CLAUDE.md`, `.claude/` | Stay in the public repo |

Facts that shape the design:

| Fact | Consequence |
|---|---|
| A fresh clone or plugin install has no `output/cache/` | Updates must not rely on caches, and must never be answered from a stale cache: each run uses a temporary cache folder |
| A gem crawl is one request per gem, 0.8 s apart; MCP clients time out long tool calls | Each call fetches at most `max_gems` detail pages (default 20, hard cap 40) and reports how many are left; the caller repeats |
| `collect_kind` rewrites the listing file every run | With a cap, gems whose listing row changed but were not fetched yet must keep their old listing row, or the next call would not see them as changed |
| The glossary collector finds its hover hashes in cached gem pages and needs about 700 requests | Glossary is **not** an update scope; status marks it "terminal only" |
| Tree versions (`0_5`, `4.5`) are pinned in the catalog | `update passives` re-fetches the pinned versions. Status reports when a newer version exists; moving to it is a release change, not a command |
| Collectors print progress; stdout is the MCP channel | The tools run collectors with stdout redirected to stderr |
| `LookupService` loads a saved graph file when one exists | After an update the graph file is rebuilt if present, and the server swaps in a freshly loaded service |

## What is added

### Tools (14 in total)

**`data_status(check_online=False)`** — read-only.
- Local (default, no network): for each data set — records, oldest / newest `fetched_at`, age
  in days, whether it can be updated by command; versions (package, catalog spec and its
  `verified_at`, PoB2 tree, poe2db tree data); ladder snapshot date and league; where the data
  folder is and whether it is writable.
- `check_online=True`: runs the existing probe (`src/catalog/probe.py: run_probe`, about 19
  requests, 0.8 s apart) without writing its metrics file: per source ok / drift, and whether a
  newer passive tree version exists.
- Annotations: read-only, open-world (it can reach the network when asked).

**`update_data(scope, names=None, older_than_days=None, max_gems=20, dry_run=False)`** — writes.
- `scope` is required: `skill_gems`, `spirit_gems`, `support_gems`, `passives`, `ladder`.
  Anything else (including `all`, empty) → error listing the scopes.
- Gem scopes: one listing request, then only the gems that are new, changed on the listing,
  broken, named in `names`, or older than `older_than_days` — at most `max_gems` per call.
  Result: counts by reason, `updated`, `added`, `removed`, `left` (call again when > 0).
- `passives`: PoB2 `tree.json`, the two poe2db tree data files, the four Keystone / Notable
  listings (7 requests); then the stat index is rebuilt. `names`, `older_than_days`, `max_gems`
  are rejected for this scope.
- `ladder`: runs the poe.ninja fetcher (about 20 requests) and replaces the snapshot when it
  validates. Only offered if poe.ninja accepts the identifying User-Agent (see step 1).
- `dry_run=True`: fetches the listing only and reports what would be updated; writes nothing.
- After a real update: the entity index is rebuilt (Chinese names reused from the current
  index; the scope's `/tw/` listing is fetched only when new entries appeared), the graph file
  is rebuilt if it exists, and the server reloads its data.
- Collectors keep their own guards: a page that no longer parses or a count below `expect_min`
  aborts without writing.
- One update at a time (shared lock with `refresh_gem`); a second call gets "an update is
  already running".
- Annotations: not read-only, destructive, idempotent, open-world.

### Commands

| Where | Command | Does |
|---|---|---|
| Claude Code plugin | `/poe2db:status` (`skills/status/SKILL.md`) | Calls `data_status`; offers the online check |
| Claude Code plugin | `/poe2db:update <scope> [names…]` (`skills/update/SKILL.md`, user-invoked only) | Requires a scope, shows the dry run, then updates and repeats while `left > 0` |
| Any MCP client | prompts `status` and `update(scope, names)` | The same instructions (Claude Desktop "+" menu, `/poe2db.update` in VS Code, slash commands in Gemini CLI) |

Both the skill and the prompt refuse to run `update` without a scope and list the scopes.

## Steps

1. **poe.ninja fetcher** (`src/fetch_poe_ninja_builds.py`): use `USER_AGENT` from
   `src/scrapers/common.py`, drop the browser `Referer`, delay 0.8 s. Test: one request to the
   small `index-state` endpoint. Accepted → run the fetcher once end to end (about 20 requests)
   into a temporary file to confirm it still parses, and enable the `ladder` scope. Refused →
   leave the scope out, say so in status and the README.
2. **Gem collector cap** (`src/scrapers/collect_gems.py`): `max_targets` and `dry_run` for
   incremental runs; pending gems keep their previous listing row; summary gains
   `targets_total`, `targets_left`, `reasons`.
3. **`src/tools/maintenance.py`** (new): `DataMaintenance(base_dir, spec)` with `status()`,
   `online_check(fetch)`, `update(scope, …, fetch)`; scope table as a constant; temporary cache
   folders; index / stats / graph rebuild using `build_entity_index` (with `zh_names` from the
   current index), `build_stat_index`, `build_knowledge_graph` / `save_graph`.
4. **`src/tools/mcp_server.py`**: the two tools, the two prompts, stdout redirection, service
   reload; `src/tools/build_workflow.py` gets the two prompt texts.
5. **Skills**: `skills/status/SKILL.md`, `skills/update/SKILL.md`; the `poe2db-catalog`
   maintenance skill points to them.
6. **Docs**: a "Commands" section in `README.md` and `README.zh-TW.md` (commands, scopes,
   limits); the data-source table and `docs/clients.md` updated (14 tools, 3 prompts, poe.ninja
   User-Agent); `ROADMAP.md`, changelog `[0.7.0]`, `docs/flow/system_flow.md`.
7. Tests, reports, floorplan refresh.

## Error handling

| Case | Behaviour |
|---|---|
| No scope, unknown scope, `all` | Error listing the valid scopes; nothing fetched |
| `names` not found in the scope | Error naming them, with close matches; nothing fetched |
| `max_gems` < 1 or > 40; `older_than_days` < 0; gem-only options on `passives` / `ladder` | Error |
| Listing or page no longer parses, counts below `expect_min`, more than 2 % of pages failed | Collector aborts; nothing written; message says to run status with the online check |
| Network error | Error with the URL; nothing written |
| Data folder not writable | Status says so; update refuses before any request |
| Update already running | Error |
| Index rebuild fails after the data was written | Error says the data is updated and the index is not; running the same update again repairs it |
| poe.ninja refuses or its format changed | `ladder` update aborts; the old snapshot stays |

## Tests (offline, fixtures and fake fetchers only)

| File | Key cases |
|---|---|
| `tests/unit/test_collect_gems_cap.py` | cap respected; `targets_left`; a listing-changed gem left for later is still selected on the next run; new gems beyond the cap are absent, not broken; `dry_run` writes nothing and makes one request |
| `tests/integration/test_maintenance.py` | status: counts, dates, ages, versions, writable flag, missing files; online check with a fake probe fetcher (ok and drift), no metrics file written; update per gem scope (changed / named / stale / nothing to do), `passives` (7 requests, stats rebuilt), unknown scope, bad options, unknown names, collector abort leaves files byte-identical, no cache folder left behind, index and graph refreshed, Chinese names kept |
| `tests/integration/test_mcp_server.py` | 14 tools, 3 prompts; tools through the server; nothing printed to stdout during an update; the service is reloaded; concurrent update refused |
| `tests/unit/test_tool_portability.py`, `test_plugin_manifest.py` | annotations of the two tools; skills name real tools; `update` skill is user-invoked only |
| `tests/unit/test_fetch_poe_ninja_private.py` | the fetcher's headers carry the project User-Agent and no browser string |

End to end on the real data: `data_status` locally and online; `update_data` dry run for each
gem scope; one real `skill_gems` update with `max_gems=3` and one `passives` update, followed
by a lookup that shows the new `fetched_at`; the poe.ninja check from step 1; Windows launcher
and MCP Inspector list 14 tools.

## Acceptance criteria

1. `update_data` cannot run without one of the listed scopes; no code path crawls everything.
2. One call makes at most 1 + `max_gems` (+1) requests for a gem scope and 7 (+2) for passives.
3. A failed or aborted update leaves every data file unchanged.
4. After an update, lookups in the same session return the new records without a restart.
5. `data_status` without `check_online` makes no network request.
6. The commands exist as plugin skills and as MCP prompts and are documented in both READMEs.
7. The poe.ninja fetcher sends the project User-Agent; the README says what was observed.
8. Offline suite passes; `src/tools` coverage ≥ 90 %. No commit or push until asked.

## Out of scope

Glossary updates by command; moving to a newer passive tree version by command; a full gem
crawl by command; scheduled updates; keeping updated data outside the plugin folder.

## Result (2026-11-11)

| Criterion | Result |
|---|---|
| Scope is mandatory | `update_data` and both command texts refuse an empty, unknown or "all" scope before any request |
| Request bound | Measured: dry run 1 request; three named gems 4; `passives` 7; online status 18 |
| Failed update leaves files unchanged | Tested byte for byte for a short listing, a network error, a failed tree validation, a reshaped tree and too few parsed stat lines |
| Same-session freshness | After a real update of three gems the session returned the new `fetched_at` without a restart |
| `data_status` offline | No request without `check_online` (tested) |
| Commands | Plugin skills `status`, `update`; MCP prompts `status`, `update` |
| poe.ninja | The identifying User-Agent was accepted (HTTP 200 on all 18 requests) |
| Tests | 1,028 passed at the end of implementation; 1,064 after the second review |

Deviations from the plan:

- **No `ladder` scope.** poe.ninja accepted the requests, but its response format has changed
  (the row data moved to another message field with different cell encodings) and the fetcher
  parsed 0 rows. Per the plan's error table the old snapshot stays; `ladder` is listed under
  `not_updatable` with the reason. Repairing the parser is on the roadmap.
- The cap tests are in `tests/integration/test_collect_gems_cap.py` (they run the collector end
  to end), not `tests/unit/`.
- Gem pages that fail to download are treated like gems left for later (their previous listing
  row is kept), so the next run selects them again.
- Under a cap, gems are fetched in the order requested, new, changed on the listing, broken, stale.
- The entity index is rebuilt after every real update, also when nothing was fetched, so that a
  repeated update repairs an index that failed to build.

### After the second independent review

The first implementation was reviewed as "Needs Revision" (`docs/reports/code_review_2026-11-11.md`,
second review). What changed as a result:

- **Repeated calls now end.** With more `names` than `max_gems`, or `older_than_days=0`, the
  same gems were selected on every call. A gem fetched in the last 15 minutes is no longer
  selected by name or age (`recently_updated` reports how many), and the tool description caps
  the repeat calls at 10. Verified on the real site: three named gems with `max_gems=1`.
- **Request bound with no index.** Only the updated gem scope's own `/tw/` listing is fetched
  (it was all five). The same single page is fetched whenever a gem of the scope has no Chinese
  name yet, which is what makes "run the same update again" a real repair.
- **Writes.** A failed write is reported as "some files may already be updated; run the same
  update again" instead of a generic error. Files are still written one after another, not
  staged and swapped together, so criterion 3 holds for every abort before the first write and
  not for a disk failure in the middle of writing.
- **Other processes.** A lock file in `data/` covers `update_data` and `refresh_gem`. The
  terminal collectors do not take it.
- **Also:** `older_than_days` limited to 0–3650, booleans refused for the numeric options,
  `max_gems` refused for `passives`, a gem scope without a local file is sent to the terminal,
  one failed page is skipped instead of aborting, `data_status` survives an unreadable file,
  the online check does not run alongside an update, the service reload happens outside the
  server lock and reports its own failure.
- **Found while re-testing:** every spirit gem is stored twice (poe2db lists them among the
  skill gems), so an update of `spirit_gems` was not visible through `get_gem`. Lookups now
  answer from the newer copy.

Final count at that point: 1,064 tests.

## Addendum (owner's decisions, 2026-11-11, after the first Claude Desktop round)

| Topic | Decision |
|---|---|
| Ladder | Repair the poe.ninja parser for the site's current response format and add a `ladder` update scope |
| Glossary | Add a `glossary` update scope that works from an AI client (bounded requests per call) |
| Data licence | Accepted: the data follows poe2db's terms (CC BY-NC-SA 3.0), the code is MIT |
| Spirit gems stored twice | Keep one copy: a gem that is in the spirit gem data is no longer stored in the skill gem data |
| `CLAUDE.md` | Leave the plugin root so that `claude plugin validate --strict` passes |

Design notes:

- **One copy per gem.** poe2db's Skill Gems page also lists every spirit gem. `collect_kind`
  skips skill-listing rows whose slug is already in the spirit gem data (`OWNED_BY`), and the
  53 duplicate records are removed from the skill gem files. A new spirit gem is stored as a
  skill gem only until the spirit gems are updated.
- **`CLAUDE.md`** moves to `.claude/CLAUDE.md`, which Claude Code reads as project
  instructions just the same; the plugin root then holds no `CLAUDE.md`.
- **`ladder` and `glossary` scopes**: designed in the sections below once the sources have
  been examined. Both keep the rules of the other scopes: one scope per call, a bounded number
  of requests, nothing written when the source does not validate.
