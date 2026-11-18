# Test Report — 2026-11-18 (0.15.1, search strings as regular expressions)

Scope: `src/tools/search_string.py` (rewritten), `atlas.labels()`, the `search_string` description, workflow
and skill texts. Tier: small fix of a new feature — unit and integration for the touched code, plus a
measured run on real data. Plan: `docs/plan_atlas_stages.md`, "3b 修訂".

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| **Total (`uv run pytest`)** | **1,998** | 0 | 0 |

1,987 before (0.15.0). `uv run ruff check src tests`: no findings. Tests are offline and use synthetic data.

## Coverage (`pytest --cov=src --cov-branch`)

| File | Lines | Branches | Total |
|---|---|---|---|
| `src/tools/search_string.py` (rewritten) | 237 stmts, 3 missed | 94, 5 partial | 98 % |
| `src/tools/atlas.py` | 110 stmts, 3 missed | 24, 1 partial | 97 % |
| **All of `src/`** | 8,179 stmts, 269 missed | 2,938, 171 partial | **96 %** |

## Tests changed

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_search_string.py` | 24 (rewritten) | A line shown at both ends of its ranges (one range, two ranges, `+`, decimals, negative ranges, Chinese); a hybrid modifier as two lines; the search form; `\d+` and escaping; candidates shortest first, tied to the end first at equal length, never a space at an edge, a quote or `!`, at least the minimum letters; the piece matches every tier and no other line; "Adds # to # Physical Damage" never matches `Physical Damage: 13-18` or "increased Physical Damage"; two Chinese modifiers get different pieces; the same sentence with other numbers is shared, not a clash; a hybrid found by its unshared line; the fewest clashes when every piece clashes; no piece with too few letters; names and item text; packing; avoid entries |
| `tests/integration/test_atlas_tools.py` (search-string part) | 15 | Every check runs the pieces with `re`, line by line, in any case, against every line of the synthetic data: leaving out named waystone modifiers; **every** waystone modifier and **every** normal Bows modifier gets a piece matching only itself; tier names and property lines never matched; `waystone_mods` text and id go straight in; both tiers left out by one piece; `missing`, `unmatched`, `left_out`; gear strings in both languages; base, unique and property lines never matched; through the MCP server |

## Measured on real data

| Run | Result |
|---|---|
| One piece for every normal modifier of every item class (1,895) | English: 971 only match themselves, 924 also match the same sentence on another modifier (`shared_with`), 0 with `also_matches`; Chinese: 970, 924, 1. Mean length 7.1 characters (median 5, longest 39) in English, 3.4 (median 2, longest 12) in Chinese. Slowest call 0.42 s (a Time-Lost Diamond modifier). 9 modifiers not run: one item class has a modifier without text, and `check_affix` refuses the top tier of "increased Rarity of Items found" on helmets ("above the best tier"), an existing lookup quirk |
| Every waystone modifier (35) | All match only themselves in both languages; mean 4.3 characters in English, 2.1 in Chinese, longest 5 and 4 |
| Side by side with poe2.re (its public data, read for comparison only) | Two-handed maces: `sed p` / `^\d+% increased p`, `\d+ phys` / `\d+ ph`, `\d+ to strength$` / `gth$`; waystones: `rses` / `ses`, `from` / `tak`, `eble` / `eble`, `fire$` / `fir`; Chinese `上的` / `身`, `弱詛` / `被衰`. Ours are sometimes longer because corrupted, essence and rune modifiers are checked too |

Not tested: the strings in the game. Not checked, because the data does not have them: rarity, item level
and requirement lines, a rare item's random name, a waystone's pack size, rarity, drop chance and revive
lines, and whether desecrated or corrupted lines carry a suffix in the game's search text.
