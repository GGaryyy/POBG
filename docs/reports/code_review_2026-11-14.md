# Code Review — 2026-11-14 (0.13.0, campaign builds)

Reviewer: an independent reviewer agent (read-only), then fixes by the main session. Plan:
`docs/plan_campaign_build.md`.

## Scope

New: `src/scrapers/collect_campaign.py`, `src/tools/campaign.py`, `tests/campaign_support.py`,
`tests/unit/test_collect_campaign.py`, `tests/integration/test_campaign_tools.py`. Changed:
`src/tools/build_tools.py`, `src/tools/lookup.py`, `src/tools/pathing.py`, `src/tools/pob_export.py`,
`src/tools/maintenance.py`, `src/tools/build_workflow.py`, `src/tools/mcp_server.py`,
`src/catalog/entity_index.py`, `src/catalog/spec.py`, `src/catalog/poe2db_sources.json`, the three skills,
docs, flowcharts.

## Quality

- The collector keeps parsing, assembly and fetching apart; every limit in `campaign.py` is a short
  function of the stored data, and what the data lacks is returned as `not_in_data` instead of guessed.
- The build tools take the new parameters as options; without them the results are unchanged (the
  1,680 earlier tests pass as they were, apart from lists that now include the new tools and scope).
- Stage data is derived from the pages (stages, the Interlude, trials, rewards), so 1.0's Acts 5 and 6
  need a data update, not a code change; the one fixed list is the two campaign trials in the catalog.
- Security: no secrets; regexes have no nested quantifiers; cache names go through `safe_cache_name`;
  walkthrough text is capped; nothing is printed to stdout on the MCP path; ladder names are untouched.
  Page size is not capped (inherited from `fetch_html`): Low.

## Findings

| # | File | Severity | Finding | Resolution |
|---|---|---|---|---|
| 1 | `build_tools.py` `_route_without` | High | An ascendancy PoB has no id made the route be computed again without `by_stage`; the stage export then wrote only the start nodes | Fixed: `by_stage` passed through; test |
| 2 | `collect_campaign.py` `collect` | Medium | A 404 for the Interlude page (expected when 1.0 removes the Interludes) failed the whole update | Fixed: 404 means no Interlude; other errors still stop; tests |
| 3 | `collect_campaign.py` `build_stages` | Medium | The Interlude was recognised only by an exact area match | Fixed: 80 % of the Interlude page's areas; `check` refuses Interlude areas no act holds; tests |
| 4 | `collect_campaign.py` `parse_listing_slugs` | Medium | Every link of the support listing was followed: unbounded requests if the page changes | Fixed: only "(Level N)" items, at most 10; test |
| 5 | `build_tools.py` `export_pob` | Medium | Earlier stages' trees get attribute passives for the final stage's gems and gear | Kept for this version (the plan splits only the tree); the stage note in the code says so |
| 6 | `build_tools.py` `_pob_group` | Low | Socket limit could exceed PoB's group maximum | `min(sockets, MAX_SUPPORTS)` |
| 7 | `campaign.py` | Low | Results returned internal objects | Deep copies; test |
| 8 | `maintenance.py`, `collect_campaign.py` `_mark_trials` | Low | `StopIteration`, `RecursionError`, `re.error` would escape the update | Default for `next`; caught; test for a breaking collector |
| 9, 10 | `collect_campaign.py` Lua parsing | Low | Escaped backslash, `--` comments and a nested table in Options | One depth counter with an escape flag and comment skip; test |
| 11 | `collect_campaign.py` `_card` | Low | "Area" matched any header containing the letters | English words on boundaries (Chinese headers lose their spaces in cleaning) |
| 12 | `campaign.py` | Low | Unused constant | Removed |
| 13 | `campaign.py` `find_stage` | Low | "Interlude 2" / "插曲 1" did not resolve; repeated literal | Trailing number ignored; `INTERLUDE_STAGE` shared from `spec.py`; test |
| 14 | `campaign.py` | Low | The Epilog's points count in the last stage | Kept (plan rule), stated in `how` |
| 15 | `campaign.py` | Low | Skill / Spirit gem tiers use the gem level's required level, not uncut gem drop levels | Kept, stated in `how` |
| 16 | `campaign.py` `_mentions` | Low | "Camp" matched "Campsite" | Word boundaries for English names; test |
| 17 | `build_tools.py` `_stage_trees` | Low | Later targets were reported by node name, not as written | Reported by the caller's input; test |
| 18 | `build_tools.py` `_stage_trees` | Low | Without targets only one tree was written | One starts-only tree per stage; test |
| 19 | `build_tools.py` `affix_fact` | Low | Over-long line | Split |
| 20 | `docs/plan_campaign_build.md` | Low | Plan said about 12 requests and `budgets` | Plan updated (about 26, `by_stage`), with an implementation note |
| 21 | `entity_index.py` | Low | A malformed campaign row would break every index rebuild | Rows without slug or name are skipped |

## Test quality

The review noted weak assertions (`supports_for` with `max_level` passing on an empty list) and gaps
(multi-tree attribute overrides, a breaking collector, the real budget through `_stage_cuts`, the
Interlude page gone). Each now has a test that names the expected item. Remaining gaps: a stage in
the middle with no point rewards and a quest reward without an area level are not covered by their
own test; per-tree point limits are checked through node counts.

## Verdict

**Approved with Notes.** The High finding and the Medium ones that matter for the 1.0 data change are
fixed and tested; finding 5 is a documented limitation of the first version.
