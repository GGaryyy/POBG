# Test Report — 2026-11-14 (0.13.0, campaign builds)

Scope: the `campaign` data set and update scope, the four campaign tools, the level- and stage-aware
build tools (`gems_by`, `supports_for`, `verify_build`, `path_to`, `export_pob`), the campaign-first
build workflow and skills. Tier: new feature — unit, integration, end-to-end on real data.
Plan: `docs/plan_campaign_build.md`.

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| **Total (`uv run pytest`)** | **1,797** | 0 | 0 |

1,680 before. All tests are offline (synthetic campaign site in `tests/campaign_support.py`; `data/` is
never read by tests). `uv run ruff check src tests`: no findings. `claude plugin validate --strict .` on the files that
would be committed: passed (the validator's plugin-directory check notes a missing icon, which does not change the
result; in the working folder it also flags the local, uncommitted `CLAUDE.local.md`).

## Coverage (`pytest --cov=src --cov-branch`)

| File | Lines | Branches | Total |
|---|---|---|---|
| `src/scrapers/collect_campaign.py` (new) | 437 stmts, 33 missed | 196, 23 partial | 91 % |
| `src/tools/campaign.py` (new) | 244 stmts, 15 missed | 90, 10 partial | 93 % |
| `src/tools/build_tools.py` | 1,154 stmts, 10 missed | 460, 12 partial | 99 % |
| `src/tools/pathing.py` | 159 stmts, 9 missed | 76, 5 partial | 93 % |
| `src/tools/pob_export.py` | 138 stmts, 0 missed | 30, 0 partial | 100 % |
| `src/tools/maintenance.py` | 535 stmts, 16 missed | 144, 6 partial | 97 % |
| **All of `src/`** | 7,120 stmts, 249 missed | 2,582, 150 partial | **96 %** |

Not covered in the new files: the collector's command-line `main()` and a few defensive branches
(empty cells, a page without the expected card).

## New tests

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_collect_campaign.py` | 30 | Act index order; area table (repeated rows kept once, town / waypoint, bosses with and without a monster link, a level cell with two numbers, rows without a link or level); quests (steps of one quest merged, Chinese reward label); act map (row and column arrows, a lone area); walkthrough by heading, town suffix dropped; PoB rewards (points, Spirit, options with `\n\t`, escaped backslash, `--` comments, a nested table in Options); stages (empty act skipped, Interlude named from the Interlude page, an act holding 80 % of its areas, six acts without an Interlude page, Interlude page gone with 404, other HTTP errors still stop); towns left out of the level; rewards placed by description and area (case, a leading "The"), Epilog in the last stage; trials; both languages merged; rules from the gem and orb pages; support listing bounded to leveled items, at most 10; guards (minimums, missing socket rule, Interlude areas no act holds, offline without cache); requests counted (20, each once, no Chinese page for an empty act); the four files written |
| `tests/integration/test_campaign_tools.py` | 63 | Stage limits computed from the data (level, passive points incl. quest points, ascendancy points, quest Spirit, gem level and tiers, support tier, sockets); a trial at exactly the stage level counts, one above does not; rewards tagged in both languages; `not_in_data`; stage names (id, "Act 2", "第 2 章", 2, "插曲 1", "Interlude 2"); missing campaign data names the update; `earliest_level` per tier and kind; `gems_by` / `supports_for` `max_level` (one below and exactly at the level); `verify_build` `too_early` for gems, items and modifiers, the modifier tier by level (32 / 33 / 80); unchanged results without the new parameters; `path_to` `by_stage` (targets in the listed order, cut at the points, ascendancy cut, `after_campaign`, the real budget); `export_pob` `stage` (one tree per stage, active tree, fixed level, points, later targets reported as written, notes, gem and support tiers, socket limit, Spirit up to the stage, gear above the level, modifier tier by level, an ascendancy PoB lacks, no targets, stage with character_level refused, unknown stage); campaign questions (name index, `get_area` by boss, connections, quests naming an area on word boundaries, `get_quest` in Chinese, `campaign_by` for rewards / quests / bosses / areas, limits, bad kind); results are copies; update scope (writes four files and the index, status, previous stages, nothing written when a page does not parse or the collector breaks, no gem options, prompt text) |
| `tests/unit/test_pathing.py` | +2 | `priority_order`: the listed target first, every node next to an earlier one; targets off the route ignored |
| `tests/unit/test_pob_export.py` | +2 | Several trees in order, the last active, attribute overrides per tree; one tree without `tree_specs` |

Updated expectations: tool list (22 tools), update scopes (`campaign`), `export_pob` schema (`stage`),
the tool-name pattern of the skill test, version 0.13.0.

## Failures fixed during the run

| Found by | Problem | Fix |
|---|---|---|
| New test | `get_quest` passed the quest table to the resolver before loading it: the first lookup never matched | Load first |
| Full suite | `gems_by` and `supports_for` added `max_level` to their result even when it was not given | Only when given |
| Tool portability test | `verify_build` and `export_pob` descriptions over 1,024 characters | Shortened |
| Independent review | See `code_review_2026-11-14.md`: an export with an ascendancy PoB lacks lost its tree; the Interlude page going away would have failed the update; and others | Fixed, each with a test |
| Synthetic site | A card header like "第 1 章 任務" is cleaned to "第 1 章任務": a word-boundary match failed for Chinese | Boundaries for English words only |

## End-to-end on real data

| Run | Result |
|---|---|
| Collector against poe2db and GitHub (26 requests, 0.8 s apart, project User-Agent) | 5 stages (Act 1–4, Interludes / 間歇), 98 areas, 73 quests; every PoB reward placed in an area; trials in Act 2 (level 22) and Act 3 (level 38) |
| `campaign_stages` | Act 1: level 15, 18 points, Spirit 30, gem level 5, 2 sockets · Act 2: 31, 38 points, 2 ascendancy, gem 9, support tier 2, 3 sockets · Act 3: 45, 56, 4 ascendancy, Spirit 60, gem 11, tier 4, 4 sockets · Act 4: 53, 68 · Interludes: 56, 79, Spirit 100, tier 5; note that PoB places the Interlude rewards at area levels up to 64 |
| Lookups | "奧格姆宅第", "Count Geonor" found; `campaign_by(reward, "天賦點")` lists the 12 point rewards; bosses of 第 3 章 |
| `export_pob` Witch, two notables, `stage="act_3"`, zh-TW | Three trees ("第 1 章 (等級 15)" …), level 45, 42 of 56 points; a level-5 support left out in Act 2 with its drop level |

Not run here: a build answer in Claude Code or Codex with the new workflow, and importing a stage code into
PoB. Both are for the user, after the plugin is updated.
