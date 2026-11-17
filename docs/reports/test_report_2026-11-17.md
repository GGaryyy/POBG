# Test Report — 2026-11-17 (0.14.0, currency items)

Scope: the `currency` data set and update scope, the shared item-page reader (also used by the campaign
collector), the two currency tools, the name index, server instructions, skills and the `update_data`
description. Tier: new feature — unit, integration, end-to-end on real data. Plan: `docs/plan_currency.md`.

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| Unit (`tests/unit`) | 940 | 0 | 0 |
| Integration (`tests/integration`, incl. calls through the MCP server) | 940 | 0 | 0 |
| **Total (`uv run pytest`)** | **1,880** | 0 | 0 |

1,797 before. All tests are offline (synthetic currency site in `tests/currency_support.py`; `data/` is
never read by tests). `uv run ruff check src tests`: no findings.

## Coverage (`pytest --cov=src --cov-branch`)

| File | Lines | Branches | Total |
|---|---|---|---|
| `src/scrapers/collect_currency.py` (new) | 223 stmts, 3 missed | 84, 6 partial | 97 % |
| `src/scrapers/item_page.py` (new) | 23 stmts, 0 missed | 10, 2 partial | 94 % |
| `src/tools/currency.py` (new) | 157 stmts, 1 missed | 60, 2 partial | 99 % |
| `src/tools/maintenance.py` | 610 stmts, 25 missed | 160, 6 partial | 96 % |
| `src/scrapers/collect_campaign.py` | 432 stmts, 33 missed | 192, 22 partial | 91 % |
| **All of `src/`** | 7,620 stmts, 262 missed | 2,754, 159 partial | **96 %** |

## New tests

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_collect_currency.py` | 34 | Entry names with and without the inline icon, names with a level; properties by keyword (minimum modifier level, maximum item level) and label (stack size, limit); a line break inside a sentence; value ranges with the long dash; lines by kind (effects, implicits, enchants, bonded); required level (the level, not the first number; the Chinese label); an entry without effects kept, without a link skipped, with an unusual slug skipped; only mapped tabs read; Chinese joined by slug, missing Chinese left empty, the Chinese entry with the most lines wins; duplicates kept once with `also_in`; facts box from cards and table rows, first value wins, plain digits only; the campaign reader on the new layout; whole collection (18 items, counts per category, both languages, details, sources); reuse of stored details (one item page requested); a missing item page; an item page without facts not counted as read; a failed page keeping the earlier fields; refusals (too few item pages, a listing that no longer parses, a Chinese outage, offline without cache); `pending_pages` (listings missing, all cached, one missing, reused, failed in the run); write and read back; the command line (nothing written on error, summary, listings fetched again, item pages only when asked) |
| `tests/integration/test_currency_tools.py` | 39 | `get_currency` by English, Chinese, slug and any case; sources with dates; `related` (the omens that change an orb, Chinese lines, not a longer item name, any case and the possessive, Chinese lines only when they line up, cut and counted); essence notes per group; `not_in_data` in both languages; close names for an unknown item; `lookup_entity` kind `currency`; `currency_by` by category (English, Chinese, plural, runes / soul cores), text in effects, tags and names, `max_level` on drop and required level at the boundary, items without a drop level counted, no filter lists the categories, a blank text is no filter, bad arguments, limit; missing and unreadable data name the update; both tools through the MCP server; the update scope (writes the data and index, status, a routine update reads only the 6 listings, `older_than_days=0` reads all, a new item is the only page read, batches with `left` and resume, failed pages not counted in `left`, a refresh keeping stored details when a page fails, too many missing pages refused, a network outage reported as such, a listing that no longer parses or cannot be fetched, options, freshness by age, long `added` lists cut); the update prompt |

Updated expectations: tool list (24 tools), update scopes and data sets (`currency`), the tool-name pattern
of the skill test, the batch and call limits in the `update_data` description and the update skill,
version 0.14.0.

## Failures fixed during the run

| Found by | Problem | Fix |
|---|---|---|
| Real pages | poe2db item pages now show DropLevel as name/value cards: the campaign collector found no Jeweller's Orb drop level, so the next `update campaign` would have refused to write | `src/scrapers/item_page.py` reads both layouts; checked on the real Lesser Jeweller's Orb page (25) |
| Tool portability test | The `update_data` description went over 1,024 characters | Shortened, keeping the tested phrases |
| New test | `requires_level` took the whole match ("Level 15") | The number group |
| Independent review | See `code_review_2026-11-17.md`: an item page that parsed to nothing counted as read; the failure-streak error was reported as "pages changed shape"; a refresh could lose stored drop levels; and others | Fixed, each with a test |

## End-to-end on real data

| Run | Result |
|---|---|
| Collector against poe2db (6 listing pages + 620 item pages, 0.8 s apart, project User-Agent) | 620 items: currency 145, essence 82, splinter 4, catalyst 26, omen 50, augment 313; every item has a Chinese name; 619 item pages read; one (Tecrod's Gaze) answered with a timeout and 503s |
| Second run with the review fixes (7 requests) | The 6 listing pages again, 619 drop levels reused, the failed page read: 620 of 620 with an item page |
| Name index rebuilt offline | 5,815 entities |
| Lookups through `CurrencyLookup` | 高階混沌石: minimum modifier level 35, drop level 72, Chinese effect. Chaos Orb `related`: 7 omens (Whittling, Sinistral / Dextral Erasure, …); Exalted Orb: 5 omens. Greater Essence of the Body: points to `modifiers_for` group `essence`. `currency_by(category="currency", text="Orb", max_level=30)`: 17 orbs. 符文: Chinese lines. Omens with text 崇高石: 5 |

Seen on real data and documented rather than changed: poe2db gives DropLevel 1 to some items that only come
from specific content (Fracturing Orb, the Orbs of Sacrifice); `not_in_data` and `docs/tools*.md` say so.

Not tested yet: a currency question asked in Claude Code or Codex after a plugin update.
