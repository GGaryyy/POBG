# Test Report — 2026-11-11 (0.7.0, first public release)

Scope: the lean export (catalog, scrapers, knowledge graph, tools, MCP server, plugin), the
client-readiness changes (annotations, titles, `build_workflow`), the data commands (`status`,
`update`), and the fixes from both code reviews. Tier: new feature — unit, integration,
end-to-end.

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| Unit (`-m unit`) | 530 | 0 | 0 |
| Integration (`-m integration`) | 539 | 0 | 0 |
| **Total (`uv run pytest`)** | **1,069** | 0 | 0 |

Run time 32 s (about 55 s with coverage). All tests are offline and use `tests/fixtures/` only.
`uv run ruff check .` (rules E4, E7, E9, F): no findings.

## Coverage (line + branch)

| Package | Cover |
|---|---|
| `src/tools/` — `maintenance` 99 %, `build_tools` 99 %, `lookup` 98 %, `mcp_server` 97 %, `pathing` 92 %, `build_workflow` 100 % | 92 – 100 % |
| `src/kg/` | 98 – 99 % |
| `src/scrapers/` — `collect_gems` 93 % | 93 – 100 % |
| `src/catalog/` — `entity_index` 88 % | 88 – 97 % |
| `src/fetch_poe_ninja_builds.py` | 20 % — headers, name stripping and the summary are tested; the network loop and the protobuf decoder are not |
| **Total** | **89 %** |

## New and changed tests

| File | What it checks |
|---|---|
| `tests/integration/test_maintenance.py` (new, 77) | Status: counts, dates, ages, versions, an empty folder, the ladder snapshot, no network. Online check: clean, newer tree, unreachable pages, no metrics file. Gem updates: first update (new / changed / removed gems, index and graph rebuilt, Chinese names kept), nothing to do, dry run, capped and repeated, named gems (English, Chinese, slug), unknown names, stale gems. Refusals: missing / unknown / "all" scope, bad options, unwritable folder, a second update while one runs. Aborts with every file byte-identical: short listing, network error, failed tree validation, reshaped tree, too few parsed stat lines. Repair after a failed index rebuild, Chinese names included. Nothing on stdout, no cache or temporary files left. After the second review: repeated capped calls end (more names than the cap, `older_than_days=0`), the 15-minute window, one failed page skipped and two aborting, no local file, failed writes, a lock held by another process, a stale lock, `refresh_gem` under that lock, the online check during an update, unreadable files in status, request bounds without an index |
| `tests/integration/test_collect_gems_cap.py` (new, 15) | The cap, `targets_left`, a changed gem left for later is selected again, a new gem beyond the cap is absent until fetched, fetch order under a cap, dry run, refusal on a full crawl, the recent window, a skipped page keeping its old listing row, one copy per gem (a spirit gem on the skill listing is neither fetched nor stored, an existing duplicate is removed) |
| `tests/integration/test_mcp_server.py` (97, +41 over the export) | Fourteen tools, three prompts; `build_workflow`; `data_status` (bound to the loaded folder, works before data is loaded, online report); `update_data` (dry run keeps the service, a real update reloads it and the session sees the new gem, cap, errors, failure keeps the service, nothing on stdout); refusal while another update runs, a reload failure reported as such, the repeat-call cap in the description; the `status` and `update` prompt texts; over-long `lang` / `kind` |
| `tests/unit/test_file_lock.py` (new, 5) | The cross-process lock: held and released, second holder refused, released on error, a fresh foreign lock respected, a stale one taken over |
| `tests/unit/test_tool_portability.py` (new, 72) | Per tool: name pattern, description 40–1,024 characters, title, flat input schema, annotations; only `refresh_gem` and `update_data` write; wire form of the annotations |
| `tests/unit/test_plugin_manifest.py` | Names, repo URL (also in the User-Agent), `--no-dev` launchers, lean runtime dependencies; the `status` and `update` skills (frontmatter, user-invoked update, scopes and limits equal to the code) |
| `tests/unit/test_fetch_poe_ninja_private.py` (+3) | The summary prints no names; absolute output path; the headers carry the project User-Agent and no browser string |
| `tests/integration/test_lookup_service.py` (+7) | Stat-limit cap on both lists, the real cap, `available_kinds`, cache-before-write in `refresh_gem`, the polite delay, the newer copy of a gem stored under two kinds |

Not carried over from the private project: tests of the removed pipeline (agents, graph, API,
retrievers) and `tests/conftest.py`, which only held their fixtures.

## End-to-end (real data and real sites, measured 2026-11-11)

| Check | Result |
|---|---|
| Linux launcher | Server `poe2db 0.7.0`, 14 tools, 3 prompts; lookup and build tools with Chinese and English input all succeeded, 1–19 ms after the first call |
| Windows launcher (Windows `uv.exe`, Python 3.12.10, system code page 950) | 14 tools, 3 prompts; the same lookup calls with identical response sizes; `data_status` (data folder `D:\…\data`, writable); a dry-run `update_data` (1 request) |
| Windows first start | The environment install outlasted a 400 s handshake wait on this connection. Documented in `docs/clients.md` |
| `data_status` | 0.4 s locally, no request. With the online check: 38 s, 18 requests, 37 checks, no problems |
| `update_data` dry run, three gem scopes | 1 request each (2–3 s); nothing selected, as the data was one day old |
| `update_data` `skill_gems`, three named gems | 10 s, 4 requests, 3 updated, 0 left; `get_gem` in the same session returned the new `fetched_at`; the Chinese lookup still resolved |
| `update_data` `passives` | 17 s, 7 requests; 4,714 nodes, 5,187 edges, 6,377 stat lines; 0 changed; `path_to` worked afterwards |
| `update_data` scope `all` | Refused, no request |
| Repeated capped update after the fix: three named spirit gems, `max_gems=1` | Call 1: 1 updated, 1 left (the third had been fetched minutes before: `recently_updated` 1). Call 2: 1 updated, 0 left. A further call: nothing selected, 1 request. `get_gem` then answered from the updated spirit copy |
| `update_data` with `older_than_days` one million | Refused with the allowed range, no request |
| A real one-gem update through the Windows launcher | 2 requests, 1 updated; the lock file was removed; lookups and status worked afterwards. It showed that Windows wrote the data files with CRLF line endings; writes now force LF and the four affected files were normalised |
| poe.ninja fetcher with the project User-Agent | All 18 requests answered (HTTP 200). **0 rows parsed**: the site's response format changed. No `ladder` update scope; the snapshot is unchanged |
| MCP Inspector CLI (before the data commands were added) | `tools/list`, `prompts/list`, `tools/call` for `lookup_entity`, `build_workflow`, `path_to` |
| Claude Code `--plugin-dir`, from an unrelated folder | Exactly one server, `plugin:poe2db:poe2db … ✔ Connected` |
| `claude plugin validate --strict` on a clean copy of the files to be published | Passes (the project rules now live in `.claude/CLAUDE.md`). The plugin-directory hint about a missing icon remains and does not affect the result. In the working folder the local, git-ignored `CLAUDE.local.md` still triggers a warning |
| Removing the 53 duplicate spirit gems from the skill gem data | 400 → 347 records; index 2,838 → 2,785 entities, none without a Chinese name; `get_gem`, `lookup_entity`, `verify_build`, `supports_for` answered for spirit gems; the server starts |
| Publication scan of the files to be committed | No email address, no common secret pattern; `character_name` / `account_name` only in code, tests and one synthetic fixture, never in `data/`; largest file 4.4 MB |

Response sizes per tool are listed in `docs/clients.md`.

## Not tested

- Claude Desktop in-app (the owner's manual test follows this report), Cursor, VS Code,
  Gemini CLI, Codex CLI.
- The `status` / `update` commands as typed commands inside a client (the tools and prompt texts
  were tested; how each client presents prompts was not).
- Plugin install from GitHub (the repository is not published yet).
- A real gem update that hits the cap (nothing had changed on poe2db); the cap is covered by
  the fixture tests only.
- macOS.
- Stress tests: not run in this phase.

## Failures fixed during the run

- The first Windows session timed out because the Windows environment was still downloading
  packages; rerun after the install, it passed without changes.
- The second code review found that repeated capped calls did not end for named or zero-day
  updates (reproduced with the fixtures, then fixed and confirmed on the real site), plus the
  other points listed in `code_review_2026-11-11.md`.
- Re-testing on real data showed that an updated spirit gem was still answered from its older
  skill-gem copy; lookups now use the newer copy.
- After the first code review a new check was first written too strictly (rejecting any stat
  `kind` not present in the data broke an existing test); it became the hint `available_kinds`.
- An existing test pinned the exact keys of the gem collector's summary; it was extended with
  the three new keys.
