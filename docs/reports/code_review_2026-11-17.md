# Code Review — 2026-11-17 (0.14.0, currency items)

Reviewer: an independent `reviewer` agent (second pass on code the main session wrote), then fixes by
the main session. Plan: `docs/plan_currency.md`.

## Scope

New: `src/scrapers/collect_currency.py`, `src/scrapers/item_page.py`, `src/tools/currency.py`,
`tests/currency_support.py`, `tests/unit/test_collect_currency.py`, `tests/integration/test_currency_tools.py`.
Changed: `src/tools/maintenance.py` (the `currency` scope; `_Budget` no longer counts a 404 toward the
failure streak), `src/tools/mcp_server.py` (two tools, the `update_data` and `lookup_entity`
descriptions), `src/tools/build_workflow.py`, `src/catalog/entity_index.py`, `src/catalog/spec.py`,
`src/catalog/poe2db_sources.json`, `src/tools/lookup.py`, `src/tools/build_tools.py`,
`src/scrapers/collect_campaign.py` (`parse_item_page`), the three skills, tests pinning tool and scope lists.

## Quality assessment

- **Readability and structure:** the collector follows the campaign collector (parse → merge → check →
  write), with small functions and constants at the top. The update scope reuses the items scope's batch
  pattern (`_Budget`, run cache, resume) instead of a new one.
- **Data honesty:** a record's item-page fields are kept only when the page gave facts; failures keep
  the earlier fields and date rather than inventing new ones. `not_in_data` names prices, drop sources
  and chances, and crafting steps; the low DropLevel of content-specific items is documented.
- **Conventions:** no bare `except`; stdout is only written by the command-line `main()`; tests use
  the synthetic site only.
- **Performance:** a routine update is 6 requests; a first update is about 626 requests in 13 calls of
  at most 50. `related` scans 620 records per lookup, which is negligible.
- **Security:** slugs go through `slug_from_href` and `safe_cache_name` (no path traversal); every URL is
  built by `resolve_url` on poe2db. `pip-audit`: no known vulnerabilities. `bandit` on the main files: one
  false positive (an f-string error message read as SQL). Effect text from poe2db is returned verbatim to
  the model, as for every other data set.

## Findings

| # | File | Severity | Finding | Resolution |
|---|---|---|---|---|
| 1 | `collect_currency.py` (`add_details`, `collect`) | High | An item page that loaded but had no facts box still set `detail_fetched_at`, so a layout change would be written silently and then reused forever | A page counts as read only when it gives a drop level or class (`detail_parsed`); test with every item page replaced by one without facts |
| 2 | `maintenance.py` (`_update_currency`) | Medium | The failure-streak `ServiceUnavailable` (a `ValueError` subclass) was re-wrapped as "pages changed shape"; plain 404s counted toward the streak | Re-raised unchanged; a 404 no longer counts toward the streak (the site answered). Tests for an outage and for five missing pages |
| 3 | `maintenance.py`, `collect_currency.py` | Medium | With `older_than_days`, an item page that failed lost the stored drop level | `collect(fallback=…)`: a failed page keeps the earlier fields and date; tested |
| 4 | `collect_currency.py` | Medium | One slug that cannot name a cache file aborted the update, unwrapped on the batch path | Such an entry is skipped with a warning; `pending_pages` errors are wrapped |
| 5 | `currency.py` | Medium | English words "runes", "soul cores", "currencies", "orbs" were not categories | Added to `CATEGORY_WORDS`; tested |
| 6 | `collect_currency.py` (`merge_entries`) | Low | The first Chinese entry of a slug won, even a short cross-reference stub | The entry with the most lines wins; tested |
| 7 | `currency.py` (`related`) | Low | Chinese lines were matched by position across all line kinds | Per field, and only when the field has as many lines in both languages; tested |
| 8 | `currency.py` | Low | Names matched case-sensitively, not as "Chaos Orb's"; truncation was silent | Any case, possessive; `related_total` when cut; tested |
| 9 | `currency.py` | Low | `text="  "` returned every item | Blank is no filter; tested |
| 10 | `collect_currency.py` (`pending_pages`) | Low | `left` counted pages that failed in the run | Subtracted; tested |
| 11 | `collect_currency.py` (`main`) | Low | `--refresh-item-pages` read the old cache; listings were never fetched again while stamped "now" | Listings fetched again unless `--offline`; the flag clears the item cache; tested |
| 12 | `collect_currency.py` | Low | Unused constant | Removed (`NOT_FOUND` now lives in `maintenance.py`, where it is used) |
| 13 | `maintenance.py` | Low | A first update returned about 620 slugs in `added` | At most 30, plus `added_count` / `removed_count` |
| 14 | `build_workflow.py` | Low | 12 calls of 60 left one spare; 60 requests is the longest call in the project | 50 per call, at most 16 calls (a first update takes 13) |
| 15 | `maintenance.py` | Low | The "run the online check" hint does not apply: the probe does not check the currency pages | Currency errors say "Nothing was written; the old data stays." |
| 16 | `mcp_server.py` | Low | `max_level` compares an area level and a character level | The description says which is which |
| 17 | `collect_currency.py` | Low | `requires_level` took the first number of the requirement | Matches "Level N" / "等級 N"; tested |
| 18 | `item_page.py` | Low | `isdigit()` accepts "²" | ASCII digits only; tested |

## Test-quality audit

The reviewer judged the tests reasonably strong (exact counts, slugs, request counts, `left` values) and
named the cases they missed: facts-less item pages, a failure streak, a refresh with a failing page, an
unusual slug, Chinese stub entries, Chinese line counts that differ, `left` with failed pages, English
category words, a blank text. Each now has a test. Still not covered: the run cache expiring after 30
minutes for this scope (shared code, tested for the items scope) and `data_status` with an unreadable
currency file.

## Verdict

**Approved with Notes** after the fixes (the review's own verdict on the first draft was Needs Revision,
for findings 1–5). Note: a currency question has not yet been asked through Claude Code or Codex.
