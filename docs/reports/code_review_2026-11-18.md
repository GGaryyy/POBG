# Code Review — 2026-11-18 (0.15.1 → 0.15.2, search strings as regular expressions)

Reviewer: an independent `reviewer` agent on 0.15.1 (after it was pushed), then fixes by the main session
in 0.15.2. Plan: `docs/plan_atlas_stages.md`, "3b 修訂" and "3b 再修訂".

## Scope

`src/tools/search_string.py` (rewritten in 0.15.1), `src/tools/atlas.py` (`labels()`),
`src/catalog/poe2db_sources.json` (`atlas.search`), the `search_string` description, workflow and skill texts,
`tests/unit/test_search_string.py`, the search-string part of `tests/integration/test_atlas_tools.py`.

## Quality assessment

- **Design:** pieces are cut from the line as the item shows it (ranges at both ends), numbers as `\d+`, and
  every piece is run with Python's `re` against all known lines before it is returned. The review showed that
  "all known lines" was too narrow, and that shortest-first let short free pieces hit lines the data does not
  hold. 0.15.2 takes pieces tied to a line's end first and adds the lines every item shows.
- **Data honesty:** the fixed lines come from the two tools' output and from wording found in the data; Chinese
  lines the data has no wording for are left out and named in `not_checked`, not translated.
- **Security:** user text is never compiled into a regular expression (only compared with `in` and sets);
  generated pieces are literals, escaped metacharacters, `\d+` / `[\d.]+` and anchors, so no ReDoS. No file
  or stdout writes, no secrets. The reviewer could not run `bandit` (permission denied in its sandbox).
- **Performance:** worst case is O(L² × N) regex runs per target line; on real data the slowest call is 0.15 s
  (0.42 s in 0.15.1). An adversarial 200-character line took 4.7 s in the reviewer's test; not changed.

## Findings

| # | File | Severity | Finding | Resolution (0.15.2) |
|---|---|---|---|---|
| 1 | `search_string.py` | High | Shortest-first picked 3-letter free pieces matching lines every item shows: `ari` → `Rarity: Rare`, `dex` → `Requires: … Dex`, `ali` → `Quality`, `ack` → `Pack Size`. Measured on real data: 39 of 1,895 gear pieces, 2 of 35 waystone pieces | Pieces tied to the end first, then the start, free ones last and flagged `unanchored`; catalog `atlas.search.fixed_lines` (rarity, item level, quality, item rarity, corrupted, unidentified, waystone property lines) and requirement lines from the bases plus one per attribute. Now 0 in both languages; every gear piece is tied to the end |
| 2 | `search_string.py` | Medium | A range not in `(a—b)` form left the data's notation in the line; a piece cut from it never matches in the game | A line still holding brackets or a range is not cut; a modifier with only such lines is in `missing` with the reason. `1,000—1,200` is expanded (thousands in three-digit groups only, so `Level 5, 12 Dex` stays apart) |
| 3 | `search_string.py` | Medium | `piece: None` with no reason; hybrid lines matched by position | `missing` always has a reason (no wording, data notation, tiers share no line, nothing can be told apart); hybrid lines matched up by wording |
| 4 | `search_string.py` | Low | Fallback compared against a list already cut to 12 | Full count kept (`clash_count`, shown as `also_matches_total`) |
| 5 | `search_string.py`, `mcp_server.py` | Low/Med | `shared_with` also held implicits and unique lines while the description said "another modifier" | Entries are `{line, source}` with `modifier`, `implicit` or `unique`; fixed lines are never "shared"; texts updated |
| 6 | `search_string.py` | Low | Chinese "other" lines silently skipped for records without Chinese text | Partly: `not_checked` names the Chinese fixed lines the data lacks; the per-call count of skipped records is not reported |
| 7 | `search_string.py` | Low | Decimals always `\d+` | `[\d.]+` when the line has a decimal number; tested |
| 8 | `search_string.py` | Low (perf) | Worst case quadratic in line length | Not changed; measured 0.15 s at most on real data |
| 9 | `search_string.py` | Low (perf) | Sets rebuilt per element; values computed twice | Shared and other lines split once per target line |
| 10 | `search_string.py` | Low | `#` in `NEVER_IN_PIECE` never used | Removed |
| 11 | `search_string.py` | Low | One words-only avoid entry could name several modifiers without saying so | Row has `modifiers_named` |
| 12 | `search_string.py` | Low | Waystone ids case-sensitive | Any case |
| 13 | `search_string.py` | Low | Row id always the best tier's; `matched` English only | The id given is echoed; `matched` stays English (not changed) |
| 14 | `search_string.py` | Low | `item` ignored for maps | Not changed |
| 15 | `search_string.py` | Low | Input split at any `/` | Only at " / " or a line break |
| 16 | `search_string.py` | Low | Maps `how_to_use` did not name `unmatched` | Names `unmatched`, `missing` and `left_out` |
| 17 | catalog | Low | Minimum 3 letters made finding 1 likely | Kept, together with the fix for finding 1 |

## Test-quality audit

The reviewer found the integration checks built their "other lines" the same way the module does, so a line
both forgot could not be caught. The integration tests now carry their own list of fixed lines, written in
the test. New tests: pieces never match the fixed lines (rarity, requirements, item level, quality, pack size,
a Chinese requirement line); a piece tied to the end before a shorter free one; a free piece only when no tied
one is clean, and flagged; data notation gives no piece and a reason; thousands joined but not a list; hybrid
lines matched by wording, and tiers sharing no line; `shared_with` sources; decimals; the full clash count;
waystone ids in any case and splitting at " / ". Still thin: performance has no bound test; `also_matches`
appears only in unit tests.

## Verdict

**Approved with Notes** after the fixes (the review's verdict on 0.15.1 was Needs Revision, for finding 1).
Notes: the strings have not been tried in the game; Chinese fixed lines without wording in the data, a rare
item's random name and other item classes in the same stash are not checked.
