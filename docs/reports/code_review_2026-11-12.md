# Code Review — 2026-11-12 (0.9.0, Path of Building export part 1)

Four passes by the `reviewer` agent on the uncommitted work, with fixes by the main session
between them. No Critical or High finding in any round.

| Round | Scope | Verdict | Findings |
|---|---|---|---|
| 1 | Everything | Needs Revision | 24 (four Medium) |
| 2 | The round-1 fixes and the character level | Approved with Notes | 13 (Low / Info) |
| 3 | Gem levels, attribute requirements and allocation, `character_level` | Needs Revision | 9 (two Medium) |
| 4 | The round-3 fixes | **Approved** | 0 |

All findings are fixed and covered by tests.

## Scope

New: `src/tools/pob_export.py`, `src/tools/pob_update.py`, `skills/update-pob/SKILL.md`,
`tests/unit/test_pob_export.py`, `tests/unit/test_pob_update.py`,
`tests/integration/test_build_tools_export.py`. Changed: `src/tools/build_tools.py` (`export_pob`
and helpers), `mcp_server.py`, `build_workflow.py`, `maintenance.py`,
`src/scrapers/collect_passives.py`, `skills/poe2-advisor/SKILL.md`, test support and existing
tests, READMEs, ROADMAP, client guide, flow diagram, changelog.

## Quality assessment

- The XML was checked against PoB 0.23.1's loaders (`ImportTab.lua`, `Build.lua`,
  `PassiveSpec.lua`, `SkillsTab.lua`, `TreeTab.lua`): root element, target version, class and
  ascendancy ids (0 mismatches against the installed `tree.json`), gem lookup by `gemId` /
  `variantId`, unknown nodes skipped.
- Security: the MCP tool writes nothing and uses no network. The updater refuses zip-slip paths
  (incl. backslashes, drive prefixes, UNC), bounds unpacked size, never opens `Settings.xml`
  (account tokens), prints no secrets. `pip-audit`: no known vulnerabilities. Secret grep: only
  a deliberate fake token in a test fixture.
- Conventions: constants blocks, no bare `except`, nothing printed on the server's stdout.

## Findings and resolutions

| # | File | Severity | Finding | Resolution |
|---|---|---|---|---|
| 1 | `pob_update.py` | Medium | `--dir .` put the new folder and the work folder inside the old one (`Path('.').parent`) | The folder is made absolute first; a drive root is refused |
| 2 | `pob_update.py` | Medium | The PoeCharm2 folder was named by commit day only, so a new PoB release collided with the user's own folder (`PoeCharm2-20260728`) | Named `PoeCharm2-<day>-pob<version>` |
| 3 | `pob_update.py` | Medium | Odd GitHub JSON and damaged archives raised tracebacks | Every value is type-checked; unpack errors (`zlib.error`, `RuntimeError`, `NotImplementedError`, `EOFError`) are caught with cleanup |
| 4 | `pob_export.py`, texts | Medium | Attribute passives give nothing in PoB unless an attribute is chosen; the note claimed a default | `AttributeOverride` with all three lists; attribute from `attribute` or the main skill gem; a note when none is known |
| 5 | texts | Low | An older PoB does not only skip unknown items: it refuses an unknown tree version or ascendancy | Reworded in notes, READMEs, skill |
| 6 | `pob_export.py` | Low | Control characters or lone surrogates in a title broke the XML | Removed from every text written |
| 7 | `build_tools.py` | Low | Dropping an ascendancy without a PoB id left its points and unlocked main-tree nodes | Its passives are reported one by one and the route is made again without it |
| 8 | `build_tools.py` | Low | No note for an ascendancy over budget | Note added |
| 9 | `build_tools.py` | Low | Without the graph supports went in silently; a skill missing from the graph rejected every support | Both cases go in unchecked with a note |
| 10 | `build_tools.py` | Info | A skill as its own support, a duplicate group and an unusable `main_skill` were dropped silently | Reported in `not_exported` |
| 11 | `pob_export.py` | Info | Supports written at level 20 | Level 1 (also seen in the user's PoB test) |
| 12 | `pob_update.py` | Info | Zip-slip handling sound | Tests added for backslash, drive-relative and UNC members |
| 13 | `pob_update.py` | Low (sec) | Downloads were not capped | Capped at the published size (PoB) or 200 MB (PoeCharm2); a size of 0 is refused |
| 14 | `pob_update.py` | Low (sec) | Commit sha and date from the API were used unchecked | Checked against `^[0-9a-f]{40}$` and a date pattern; the download link must be on github.com |
| 15 | skill | Low (sec) | PoeCharm2 is unverified code from a moving branch | Disclosed; the commit and its date are shown before the user agrees |
| 16 | skill | Low (sec) | A path with `"`, `` ` `` or `$` breaks the quoted command | The skill stops and asks instead |
| 17 | skill, `pob_update.py` | Medium (ops) | A long download hit the 2-minute default timeout and left a work folder | 10-minute timeout or background in the skill; progress on stderr; stale work folders removed after an hour |
| 18 | `pob_update.py` | Low | Windows virus scanning can block the final rename | Retried five times, 2 s apart |
| 19 | `pob_update.py` | Low | `update` lacked `check`'s note about an unknown PoeCharm2 version | Note added |
| 20 | `pob_update.py` | Info | The PoB inside a PoeCharm2 folder was treated as a standalone PoB | Refused, pointing at the PoeCharm2 folder |
| 21 | `pob_update.py` | Info | Docstring called the work folder hidden | "temporary" |
| 22 | `build_tools.py` | Low (conv) | `export_pob` too long | Split into `_export_route`, `_route_without`, `_export_groups`, `_export_notes` |
| 23 | `build_tools.py` | Info (conv) | Import order | Fixed |
| 24 | data | Info | Nine gem `name_zh_tw` changes in the entity index were not in the changelog | Recorded (poe2db renamed them; the index takes names from the live `/tw/` listings) |

## Round 2 (after the level fix)

The level port was confirmed exact against PoB's Lua for 0–199 points, and the point count
against `CountAllocNodes`.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | Low | Routes could pass through another class's start node (95 single-target routes in the real tree) | Other class starts are excluded from routing (`path_to` too) |
| 2 | Low | Free ascendancy nodes counted as a point | Nodes carry `no_point`; not counted |
| 3 | Info | Extra points granted by a few ascendancy passives are not in the level | Stated in `pob_level`; those passives cannot be exported yet |
| 4 | Low | A failed quest-file download stopped the whole passive update | Caught; the export falls back with a note |
| 5 | Low | The CLI's quest-file cache never refreshed | Cached per tree version; noted in the catalog |
| 6 | Low | The quest parser skipped quests with nested tables | Brace-depth scanner |
| 7 | Info | An act index of 1 emptied the table | Accepted, as PoB does |
| 8 | Info | The act table follows PoB's dev branch | Noted in the catalog |
| 9 | Low | `--dir` with `..` still landed inside the old folder | `os.path.abspath` |
| 10 | Low | `OSError` before staging printed a traceback | JSON error |
| 11 | Info | Two runs at once can collide after an hour | Documented |
| 12 | Info | Stale docstring | Fixed |
| 13 | Low | Plan and reports did not cover the level change | Updated |

## Round 3 (gem levels and attributes)

Confirmed in PoB's code: an asked level is honoured, a gem level below 20 is kept on load.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | Medium | Support additions were added to the skill's requirement (162 Dex where PoB says 157) | Combined as PoB does: the highest of each skill gem and of all support additions summed over the groups |
| 2 | Medium | With a main skill that names no attribute, leftover attribute passives got none, and the note miscounted | They go to the attribute the gems need most; unassigned ones are reported |
| 3 | Low | The note said "to cover requirements" when `attribute` was given | Separate note |
| 4 | Low | % increased attributes and reduced requirements are not counted, undisclosed | Said in the note and READMEs |
| 5 | Low | Ties went to Strength | To the main skill's attribute |
| 6 | Low | A level table with no usable row returned its first row | Its lowest level |
| 7 | Low | A main-tree multiple-choice node would be marked free | Only ascendancy ones, as PoB |
| 8 | Low | Quest cache keyed by tree version | Noted in the catalog |
| 9 | Low | One message for every `OSError` | Neutral message |

Round 4 confirmed each of these and found nothing new. One remark, no change: PoB counts
supports by gem colour, we read each support's "+N" text; the totals agree for today's data.

## Test-quality audit

| Point | Change |
|---|---|
| The Chinese-separator test passed for the wrong reason (its skill had no game id) | Uses a skill with a compatible and an incompatible support, three separator styles |
| `Settings.xml` absence checked only for a standalone PoB | Also for PoeCharm2 |
| Ascendancy-drop test did not check points | It does, plus the reported passives |
| No tests for relative paths, name collision, odd JSON, odd sha / date, failure after unpacking | Added |
| `snapshot()` compared files only | Also folders |
| Fixture gem id looked like a typo | Commented: PoB's own key has `Gem` |

The XML is checked against our own reading of PoB's loaders, not by running PoB; the user's paste
into PoB 0.23.1 is the end-to-end check.

## Notes

- The XML contract is checked against a reading of PoB's loaders and by the user's four pastes
  into PoB 0.23.1, not by running PoB in the tests.
- The requirement combination changed after the user's fourth paste (157 instead of 162 Dex at
  level 90); the level-15 code the user confirmed is unaffected (same allocation).
- Not counted toward attributes: % increases, reduced requirements, class-conditional lines.
