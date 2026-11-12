# Test Report — 2026-11-12 (0.9.0, Path of Building export part 1)

Scope: `export_pob` (build codes), `pob_export.py`, the `update-pob` command (`pob_update.py`),
PoB class ids in the passive collector, and the texts and tests that follow from them. Tier: new
feature — unit, integration, end-to-end. Plan: `docs/plan_pob_export.md`.

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| Unit (`tests/unit`) | 718 | 0 | 0 |
| Integration (`tests/integration`) | 780 | 0 | 0 |
| **Total (`uv run pytest`)** | **1,498** | 0 | 0 |

Figures are after the fixes from the review rounds and the user's PoB tests (1,405 before the
first review). All tests are offline and use
synthetic data. `uv run ruff check .`: no findings.

## Coverage (line + branch)

| Module | Cover |
|---|---|
| `src/tools/pob_export.py` (new) | 100 % |
| `src/tools/pob_update.py` (new) | 94 % (the uncovered part is the real HTTP class) |
| `src/tools/build_tools.py` | 99 % |
| `src/scrapers/collect_passives.py` | 99 % |
| `src/tools/mcp_server.py` | 95 % |
| **Total** | **96 %** (5,501 / 5,685 lines, 1,862 / 1,984 branches) |

coverage.py does not report function coverage.

## New and changed tests

| File | What it checks |
|---|---|
| `tests/unit/test_pob_export.py` (new, 33) | The code decodes the way PoB reads it (zlib header, `-`/`_` alphabet); sections and attributes PoB's loaders read; gem order, ids, supports at level 1; no ascendancy; attribute overrides hold all three lists; Chinese and markup characters; text XML cannot hold is dropped; bad, cut-off, oversized and inflating codes are refused |
| `tests/integration/test_build_tools_export.py` (new, 77) | Route and skills to a code; Chinese input gives the same build; separators `,`/`，`/`、`; ascendancy route, inference and an ascendancy PoB has no id for (left out with its passives, points reset, route made again); unknown, wrong-kind, incompatible, self and duplicate gems; a gem without a game id; unreachable targets; the support cap; supports unchecked without the graph or with the skill missing from it (and the note); main skill; budget notes for passives and ascendancy; attribute passives from the main skill, from `attribute`, or unset with a note; title clean-up; no file written; argument errors; class data without PoB ids |
| `tests/unit/test_pob_update.py` (new, 56) | Install kinds and versions; drive root and the PoB inside PoeCharm2 refused; numeric version compare; release and commit records checked (link host, size, SHA-256, sha and date shapes); check writes nothing; update of a PoB and a PoeCharm2 folder (builds and language copied, `Settings.xml` not, old folder byte- and folder-identical); a relative `--dir .`; a new PoB release next to a folder named by the old commit day; checksum mismatch, oversized download, failed download, unpackable and damaged archives, failure after unpacking (nothing kept); zip-slip members incl. backslash, drive-relative and UNC; unpacked-size limit; rename retry; stale work folders swept; progress on stderr, JSON on stdout |
| `tests/unit/test_collect_passives.py` (+12) | PoB class and ascendancy ids and base attributes read from the tree and stored in `classes.json`; PoB's act table built from the quest file (nested tables, act index 1, gaps, a failed download, the per-version cache); nodes allocated for free marked `no_point` |
| Added after the user's PoB tests | PoB's level formula against PoB's own values; the level and its mode in the code; skill gem level by character level; attribute requirements, what the build has, the allocation of attribute passives and the "must come from gear" note; `character_level` (kept, noted when the route needs more, bad values); routes that do not cross another class start; free nodes not counted |
| Existing tests updated | 18 tools and the `export_pob` schema (`tests/integration/test_mcp_server.py`), the skill and workflow texts (`tests/unit/test_plugin_manifest.py`), version 0.9.0, synthetic gems with game ids and classes with PoB ids (`tests/kg_support.py`) |

## End-to-end runs on the real data and PoB

| Run | Result |
|---|---|
| `update_data(scope="passives")` | 8 requests, 17 s; 8 classes and 23 of 25 ascendancies got PoB ids (the two without are unused in the data), base attributes and PoB's seven-act level table (identical to PoB 0.23.1's); 18 nodes are `no_point`; no passive node changed apart from `fetched_at` and the new field |
| Gem ids against PoB 0.23.1 `Data/Gems.lua` | 946 of 1,012 collected gems are in PoB; for each, our game id equals PoB's `variantId` |
| Deadeye build (4 targets, 2 skill groups) | Every one of 28 nodes is in PoB's `tree.json`; every gem id is in `Gems.lua`; the 11 attribute passives are PoB attribute nodes |
| **Pasted into PoB 0.23.1 by the user**, four codes | 1: imported (Ranger / Deadeye, 18 / 123 and 8 / 8 points, both skill groups, notes in Chinese); supports showed level 1, attack skill disabled without a weapon, attribute passives gave nothing. 2: attribute passives set, Dexterity 70; life showed 65 instead of 242 because the code said level 1. 3: level 15 written, life 242 again; PoB warned that Ice Shot (157 Dex) and Herald of Ice (86 Int) requirements were not met. 4: gems at level 5 for a level-15 character, attribute passives split 9 Dex / 2 Int, Dexterity 60 and Intelligence 17: both warnings gone |
| Same build at `character_level=90` | Gems level 20; Dexterity 70 of 157 (the figure PoB showed) and Intelligence 7 of 86 reported as needing gear |
| **Full `pob_update` on the real sites** | Old PoeCharm2 folder (PoB 0.11.2) → new `PoeCharm2-20260728-pob0.23.1` in 2 min: PoB file matched GitHub's SHA-256, language setting copied, no `Settings.xml`, old folder unchanged, no work folder left; `--check` on the new folder: up to date |
| `pob_update --check` | New folder: 0.23.1 = latest (PoeCharm2 version unknown, noted); old PoeCharm2 folder and old standalone PoB: 0.11.2 → 0.23.1; the parent folder is refused. Also run through Windows `uv.exe` with `G:\…` |
| Windows launcher (Windows `uv.exe`, Chinese input) | Server 0.9.0, 18 tools, every call ok; `export_pob` 9 ms |
| `claude plugin validate --strict` on the files that would be committed | Passed (four skills) |


## Failures fixed during the run

| Failure | Fix |
|---|---|
| A truncated code decoded without error | `decode_code` checks that the zlib stream ended |
| Synthetic gems had no game ids; giving Leap Slam one broke `refresh_gem`'s changed-fields test | Leap Slam keeps the parsed record (no item type) and serves as the "no game id" case |
| Small passives without a page could not be named in two tests | The tests use tree ids, as `path_to` does |
| Level-1 numbers, unusable gem levels and unmet attribute requirements (found by the user in PoB) | The level, gem levels and attribute passives are computed from the data |
| Code review findings, three rounds (see `code_review_2026-11-12.md`) | All fixed with tests |
