# Code Review — 2026-11-11 (0.7.0, before the first public push)

Reviewer: the `reviewer` subagent (independent pass; it did not write the code). It ran the
suite (912 passed at that point), `ruff`, `pip-audit` on the runtime lock export (no known
vulnerabilities), `bandit -r src` (only `assert` findings in the ladder fetcher) and a secret
scan (0 hits). The dispositions below were written by the main session.

## Scope

The whole folder as it would be committed (127 files), with focus on what changed for this
release: `src/tools/mcp_server.py`, `src/tools/build_workflow.py`, `src/tools/lookup.py`, the
manifests, `pyproject.toml`, the new and changed tests, and all documentation.

## Publication safety

Clean: no email address, real name or local path in any committed file; the git identity is a
GitHub noreply address; `data/community_builds/poe_ninja_builds.jsonl` has 588 rows with the
fields class, level, main_skill, skill_gems, keystones, league, rank, source, fetched_at and no
name field; `floorplan/`, `CLAUDE.local.md`, `.venv` are ignored. `refresh_gem` cannot be made
to choose a URL or a path: the slug comes from the local index, the URL from the catalog.

## Findings

| # | File | Severity | Finding | Disposition |
|---|---|---|---|---|
| 1 | `src/fetch_poe_ninja_builds.py` `_print_summary` | Medium (privacy) | Printed one raw record, with character and account name, to stdout | **Fixed**: prints the stored form; test added |
| 2 | READMEs, `ROADMAP.md` vs `collect_passives.py`, `probe.py`, `entity_index.py` | Medium | Docs said 0.8 s between pages; three modules used 0.5 s and the catalog value was never read | **Fixed**: all three read `polite_delay_seconds` (0.8 s) from the catalog |
| 3 | READMEs, `ROADMAP.md` | Low | "retry three times" — the code makes three attempts | **Fixed** (wording) |
| 4 | READMEs, update recipe | Medium | `entity_index build` ran before the passive and glossary collectors it reads from | **Fixed** (order) |
| 5 | READMEs, `docs/clients.md` | Low | "nothing else is installed" / "four small packages": about 40 packages with dependencies | **Fixed** (wording) |
| 6 | READMEs | Low | poe.ninja endpoints are JSON and protobuf | **Fixed** (wording) |
| 7 | `src/fetch_poe_ninja_builds.py` | Medium (etiquette) | Browser-style User-Agent on an undocumented poe.ninja API, next to a "polite, identifiable client" claim | **Fixed** (owner's decision): the fetcher sends the project User-Agent. poe.ninja accepted it, but its response format has changed and the fetcher reads no rows (README, roadmap) |
| 8 | `data/` | Medium (policy) | Redistribution terms of poe2db content were not checked | **Addressed**: poe2db's General disclaimer states CC BY-NC-SA 3.0; both READMEs now say the data follows those terms, not MIT. Publishing the data remains the owner's decision |
| 9 | `.mcp.json` + plugin manifest | Medium (unverified) | A second server might start from the root `.mcp.json` in a plugin install | **Checked**: loading the plugin from an unrelated folder shows exactly one `pobg` server, connected. To be confirmed again on the GitHub install |
| 10 | `src/tools/lookup.py` `refresh_gem` | Medium (design) | Writes into the plugin's own folder; lost on plugin update | **Documented** in both READMEs (Limits). A separate data folder is not built |
| 11 | `src/tools/lookup.py` | Low | Record written before the page cache; a cache failure left disk and memory out of step | **Fixed**: cache first; test added |
| 12 | `src/tools/mcp_server.py` | Low | `refresh_gem` marked non-destructive; no rate limit | **Fixed**: `destructiveHint: true`; the default fetch waits the catalog delay inside the refresh lock |
| 13 | `src/tools/lookup.py`, `mcp_server.py` | Low | Over-long `lang` / `kind` echoed in the error | **Fixed**: refused by length first; tests added |
| 14 | `src/tools/lookup.py` | Low | A mistyped `kind` in `passives_with_stat` silently matched nothing | **Fixed differently**: the result lists `available_kinds` when no stat has that kind (a hard error would reject valid kinds that a data set happens not to contain) |
| 15 | `mcp_server.py` vs `build_workflow.py` | Low | The tool rejects an unknown language, the prompt falls back to English; duplicated check | **Partly fixed**: the tool reuses the shared check (`answer_lang`). The prompt keeps its tested fallback |
| 16 | `tests/unit/test_plugin_manifest.py` | Low | `tomllib` needs Python 3.11; the project says 3.10+ | **Fixed**: `tomli` fallback in the dev group |
| 17 | docstrings in `src/kg`, `src/tools` | Low | Mentions of the removed pipeline and HTTP codes | **Fixed** |
| 18 | `.claude/skills/*` | Low | Point to folders that do not exist yet (`docs/issues/`, `tests/e2e/` …) | **Not changed**: they say where such files go when they exist |
| 19 | `docs/plan_public_release.md`, `CLAUDE.md` | Low | The plan mentioned an old commit of the private repo; `CLAUDE.md` holds personal workflow conventions | Plan sentence **removed**. `CLAUDE.md` and `.claude/` stay in the repo (owner's decision) |
| 20 | `src/fetch_poe_ninja_builds.py` | Low | Output path relative to the working directory | **Fixed**; test added |
| 21 | `.gitignore` | Low | The knowledge graph is rebuilt in memory at every start | **Documented** in `docs/clients.md` (about one second on the first call) |

## Test-quality audit

| Gap the reviewer named | Disposition |
|---|---|
| Names printed by the fetcher summary were not tested | Test added |
| The limit in the tool description could drift from `MAX_STAT_LIMIT` | Test ties them |
| The cap test never checked `without_page` or the real value 100 | Both asserted |
| `TOOL_LIKE` could not see `build_workflow` | Added to the pattern; a test asserts the server instructions name it |
| `pytest.raises(Exception)` for a missing argument | Now the validation error and its message |
| `build_workflow` compared with its own output | Replaced by assertions on the text itself |
| Wire form of `refresh_gem`'s annotations unchecked | Asserted |
| No consistency test between the READMEs and the code | **Open**: only the tool list is cross-checked (skill and workflow text); README tables are not |
| No Python version matrix, no CI | **Open** (CI is out of scope for this phase) |

## Quality notes

Constants blocks, specific exceptions and function size follow `CLAUDE.md`. The only broad
catch (`common.py`, `except BaseException`) cleans up and re-raises.

## Verdict

**Approved with Notes** (the reviewer's verdict for everything except the data commands, which
were written afterwards and are covered by the second review below).

---

# Second review — the data commands (`status`, `update`)

Reviewer: the `reviewer` subagent again, on the code added after the first review
(`src/tools/maintenance.py`, the capped gem collector, the two tools, prompts and skills). It
read the plan, ran the offline suite and reproduced its findings with the test fixtures; no
network was used. **Its verdict: Needs Revision.** The dispositions are by the main session;
the fixes were not reviewed again by the subagent.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | **High** | Repeated calls never ended when there were more `names` than `max_gems`, or with `older_than_days=0`: the same gems were selected and fetched on every call, and only the command texts capped the loop | **Fixed**: a gem fetched in the last 15 minutes is not selected again by name or age; the tool description caps repeats at 10; tests for both cases; confirmed on the real site |
| 2 | Medium | After a failed index rebuild, "run the same update again" did not restore the Chinese names of new gems | **Fixed**: the scope's `/tw/` listing is fetched whenever one of its gems has no Chinese name; the test now asserts the name |
| 3 | Medium | A failure in the middle of writing left files half updated with only a generic error; `stat_families.json` was not written atomically | **Partly fixed**: the error now says files may be half updated and that the same update finishes the job; atomic write added. Files are not staged and swapped together |
| 4 | Medium | With no entity index, all five `/tw/` listings were fetched, breaking the request bound (12 for passives) | **Fixed**: only the updated gem scope's own listing; passives fetch none. Tests assert the counts |
| 5 | Medium | A huge `older_than_days` raised an unexplained error after one request | **Fixed**: 0–3650, refused before any request; booleans and non-integers refused |
| 6 | Medium | The lock only worked inside one process | **Fixed for the tools**: a lock file in `data/` for `update_data` and `refresh_gem`, stale after 15 minutes. **Open**: the terminal collectors do not take it |
| 7 | Low-Med | `data_status` failed on one unreadable file | **Fixed**: that data set reports `error`, the others are listed |
| 8 | Low | The service reload ran after the lock was released and blocked other tools while loading | **Partly fixed**: the new service is built outside the server lock and swapped in; a reload failure says the data was updated. The reload still happens after the data lock is released |
| 9 | Low | `redirect_stdout` is process-wide; the SDK already keeps stdout for the protocol | **Kept** as a guard, with a comment |
| 10 | Low | Two online checks, or one during an update, doubled the request rate | **Fixed**: the online check takes the same lock, without waiting |
| 11 | Low | `max_gems` was accepted for `passives`; `True` counted as 1 | **Fixed** |
| 12 | Low | Any single failed page aborted a small run, so one dead page could block a scope for good | **Fixed**: one failed page is skipped and reported; two, or more than 2 %, still abort |
| 13 | Low | An update with nothing to do still rewrites the files and the index | **Not changed**: the rebuild is what lets a repeated update repair a failed one |
| 14 | Low | `requests` counts pages, not HTTP attempts (up to three per page) | **Documented** in `docs/clients.md` |
| 15 | Low | Catching `KeyError` / `IndexError` / `TypeError` can hide a bug as "the source changed shape" | **Kept**; the traceback now goes to stderr |
| 16 | Low | Docstring and comment still called `refresh_gem` the only network tool | **Fixed** |
| 17 | Low | A data set without local files turned into a full crawl spread over many calls | **Fixed** for a missing detail file (refused, sent to the terminal). A missing listing file still selects every gem; the command asks for confirmation above 60 |
| 18 | Info | Names in the prompt are cut to 120 characters and 40 names silently | **Not changed** |

Test gaps it named, and what was done: the two loops (tests added); the hollow Chinese-name
check (now asserts the name); failed writes (two tests); the request bound without an index
(two tests); a second detail-page failure through `update` (added); `requests <= 4` (now `== 4`);
every gem parsing to the same name (each fixture page now carries its own name, and a test
checks slug against name); concurrency through the server (refusal test added; a refresh
waiting behind an update is still untested); huge / boolean options (added); a corrupt file and
a missing `classes.json` in status (added).

Found by the main session while re-testing on real data, not by the reviewer: every spirit gem
is stored twice, and `get_gem` answered from the older copy after a `spirit_gems` update.
Fixed (`_freshest_gem`), with tests.

**State after the fixes:** 1,064 tests passed (1,069 after the owner's follow-up decisions: one copy per gem, rules file moved). Open notes: the fixes above have not had an
independent review; files are written one after another; the terminal collectors ignore the
lock file.

---

# Third review — `ladder` and `glossary` scopes, one copy per gem, the rename

Reviewer: the `reviewer` subagent, on the changes after the first commit. Offline only; it
reproduced finding 1 with the test fixtures. **Its verdict: Needs Revision** (one High, a
data-loss bug). Dispositions by the main session; the fixes were not reviewed again.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | **High** | A refreshed glossary term replaced the whole old entry; a hover missing in one language erased that language's name and text, and the update still reported success | **Fixed**: field-by-field merge; a crawl that keeps Chinese text for fewer than half of the terms that had it is refused; tests assert that no field is lost. A real update running with the old code was stopped before it wrote |
| 2 | Medium | Hover network errors were swallowed and retried on every call; with the network down one call could take very long and never progress | **Fixed**: five failures in a row end the call (progress kept); a hover that failed is asked once per run; the result reports `failed_requests` |
| 3 | Medium | Ladder columns were not checked for equal length, so a short column would shift every later row | **Fixed**: a column whose length differs from the name column is dropped; the gates then refuse the snapshot |
| 4 | Medium | A ladder snapshot from only the first result page, or without keystones, passed the gates | **Fixed**: a failed result page stops the run; no keystones, or less than half the rows of the previous snapshot of the same league, is refused |
| 5 | Medium | The number of dictionary requests was set by the response; hashes went into the URL unchecked | **Fixed**: only `class`, `gem`, `keypassive`, once each, hash must be hex |
| 6 | Low | `dps.skill` was assumed to index the gem dictionary | **Fixed**: used only when the column names the gem dictionary |
| 7 | Low | Varints had no length cap | **Fixed**: over 10 bytes or unterminated is malformed |
| 8 | Low | `assert` on network data | **Removed** |
| 9 | Low | No glossary baseline switched the 90 % gate off | **Fixed**: refused, sent to the terminal |
| 10 | Low | The `left` estimate for the glossary is rough and there is no server-side call cap | **Not changed**: the cap is in the description, the prompt and the skill |
| 11 | Low | The run expired 30 minutes after it started, not after its last use; a folder without marker was reused | **Fixed** |
| 12 | Low | `--kind all` stored spirit gems twice in a fresh folder; a corrupt spirit file raised an unexplained error | **Fixed**: owners are collected first; the error is reported. A gem that moved to the spirit data still shows under `removed` |
| 13 | Low | `AttributeError` from an unexpected index-state shape was not caught | **Fixed** |
| 14 | Low | `MAX_RECORDS` is checked between passes (593 rows); `rank` overlaps between passes | **Not changed**; noted |
| 15 | Low | Outdated "run the fetcher script" message | **Fixed** |
| 16 | Low | The fetcher's terminal summary printed one full record | **Removed** |
| 17 | Low | Hover host matched by substring | **Fixed** (`urlparse`) |
| 18 | Low | Nothing said what to do when 12 glossary calls were not enough | **Fixed** in the prompt and the skill |
| 19 | Low | Old plugin name in two skill headings and two plan lines | **Fixed** |
| 20 | Low | A test depended on a line wrap | **Fixed** |

Test gaps it named were closed with tests for: text kept per field, the Chinese gate, repeated
and single hover failures, column misalignment, a failed result page, a smaller snapshot, no
keystones, extra and invalid dictionary references, hostile varints and headers, long
dictionary strings, a missing glossary baseline, run expiry by last use, a corrupt spirit file,
and collection order. Still untested: names in the traceback of an unexpected ladder shape.

**State after the fixes:** 1,135 tests pass.

---

# Fourth review — re-review of the fixes from the second and third reviews

Reviewer: the `reviewer` subagent, on HEAD `8b6e386`, offline; it reproduced findings 1 and 2
with scripts. **Its verdict: Needs Revision** (one High). Dispositions by the main session.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | **High** | One gem page that stays unparsable was selected as "broken" on every call and, being more than 2 % of a capped run, aborted every update of its scope, named updates included | **Fixed**: pages that were already broken do not count as markup drift; one newly broken page is always allowed; a page that was broken minutes ago is not fetched again within 15 minutes. Tests reproduce the case |
| 2 | Medium | The lock file was removed on release without an ownership check; a holder outliving the 15-minute window removed the next holder's lock | **Fixed** by replacing the lock: an OS lock (`flock` / `msvcrt`) on the file, released when the holder exits or crashes; no age-based takeover at all. Checked on this drive from Linux and from Windows Python |
| 3 | Medium | Race in the stale-lock takeover | **Fixed** with 2 (no takeover any more) |
| 4 | Medium | The skip limit was checked only after every page; a hanging site could keep one call going for about an hour | **Fixed**: the run stops as soon as more pages failed than it may skip |
| 5 | Medium | A glossary gem page returning 404 failed every call, so the run never finished | **Fixed**: gem pages are optional and asked once per run; only listing pages are required |
| 6 | Low | A merged glossary term took the new date even when part of its text was old | **Fixed**: the old date stays when any text field was kept |
| 7 | Low | A failed index rebuild after the glossary write needed a whole new crawl to repair | **Fixed**: derived files are rebuilt before the run cache is removed; a repeat costs no requests (tested) |
| 8 | Low | Reload race between two updates in one session | **Not changed**; updates are serialised, the window is a reload of about a second |
| 9 | Low | The server reloaded after unfinished glossary calls that wrote nothing | **Fixed** |
| 10 | Low | `_freshest_gem` raised for a gem stored only under another kind | **Fixed** |
| 11 | Low | A gem counted as recently fetched and selected at once | **Fixed** |
| 12 | Low | `left` does not include pages that failed and will be retried | **Not changed**; they are listed in `skipped` |
| 13 | Low | Stale gems were fetched in listing order, not oldest first | **Fixed** |
| 14 | Low | The online check took only the in-process lock | **Fixed**: it also takes the file lock, without waiting |
| 15 | Low | Windows `PermissionError` on removing the lock file | **Fixed** with 2 (the file is no longer removed) |
| 16 | Low | File descriptor leak when writing the lock file fails | **Fixed** with 2 |
| 17 | Low | Hover bodies under 64 bytes were fetched again on every call | **Fixed**: asked once per run (tested) |
| 18 | Low | The `update` prompt description omitted two scopes | **Fixed** (tested) |

Also taken from its test audit: the failure registry carrying over to the next call, the 404
gem page, tiny hovers, the glossary repair, the single-copy gem, the unfinished-call reload,
the bytes assertion. Still untested: names in a ladder traceback after rows exist, and a refresh
waiting behind an update in one session.

**State after the fixes:** 1,150 tests pass. A real one-gem update through the Windows launcher
(2 requests) completed and released the lock. These fixes have not been reviewed again.
