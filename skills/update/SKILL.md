---
name: update
description: Update one local Path of Exile 2 data set from its source. A scope is required (skill_gems, spirit_gems, support_gems, passives, items, glossary, ninja, campaign, currency or atlas); there is no update for everything.
argument-hint: <skill_gems|spirit_gems|support_gems|passives|items|glossary|ninja|campaign|currency|atlas> [gem names or item classes, comma-separated]
disable-model-invocation: true
---

# POBG data update

Arguments: `$ARGUMENTS`

The first word is the scope; anything after it is a comma-separated list of gem names (gem
scopes) or item classes such as `Bows`, `Body Armours` (`items`).

**No scope, or a word that is not one of `skill_gems`, `spirit_gems`, `support_gems`,
`passives`, `items`, `glossary`, `ninja`, `campaign`, `currency`, `atlas`:** do not call `update_data`. Tell the user to pick one scope,
for example `pobg:update skill_gems` (`/pobg:update` in Claude Code, `$pobg:update` in Codex).

## Gem scopes (`skill_gems`, `spirit_gems`, `support_gems`)

1. Call `update_data` with the scope, the names if any, and `dry_run: true`. Tell the user what
   it found: `selected`, `reasons`, `added`, `removed`. When the user asked for gems older than
   N days, also pass `older_than_days: N`.
2. When `selected` is 0, say this data set is up to date and stop.
3. When `selected` is more than 60, stop and ask the user to confirm: every gem is one request
   to poe2db.tw, 0.8 s apart.
4. Call `update_data` with the same arguments and `dry_run: false`. While `left` is greater
   than 0, call it again, at most 10 calls in total; give one line of progress per call.
5. Report the totals (`updated`, `added`, `removed`) and anything in `skipped`.

## `passives`

1. Call `update_data` with `scope: "passives"` and no other argument. It makes 8 requests: the
   PathOfBuilding-PoE2 tree and quest rewards, two poe2db tree data files and four listing pages.
2. Report `records`, `changed`, `added`, `removed` and the tree versions.

## `items`

1. Call `update_data` with `scope: "items"`, plus `names` when the user named item classes
   (e.g. `["Bows"]`; `"Body Armours"` or `"胸甲"` also covers its attribute pages, `"Helmets_str"`
   is that page only). One call makes at most 20 requests (10 class pages in both languages) and
   keeps its progress for 30 minutes; nothing is written until every page is fetched and checked.
2. While `done` is false, call it again with the same arguments, at most 8 calls in total; give
   one line of progress per call (`fetched`, `left`).
3. When `done` is true, report `bases`, `uniques` and `modifiers`.

## `glossary`

1. Call `update_data` with `scope: "glossary"` and no other argument. One call makes at most
   50 requests to poe2db.tw and keeps its progress; nothing is written until the whole
   glossary is fetched.
2. While `done` is false, call it again, at most 20 calls in total; give one line of progress
   per call (`fetched`, `left`).
3. When `done` is true, report `records`, `refreshed`, `changed`, `added` and
   `kept_without_refresh`. When it is still false after 20 calls, tell the user to run the
   command again within 30 minutes: it continues where it stopped.

## `ninja`

1. Call `update_data` with `scope: "ninja"` and no other argument. It makes at most 14
   requests to poe.ninja and replaces the ladder snapshot; character and account names are
   never stored.
2. Report `records` and `league`, and `previous_league` when the league changed.

## `campaign`

1. Call `update_data` with `scope: "campaign"` and no other argument. It makes about 26
   requests: the Act pages of poe2db.tw in two languages, the gem and Jeweller's Orb pages, and
   PathOfBuilding-PoE2's quest rewards.
2. Report the `stages` (and `previous_stages` when they changed), `areas` and `quests`.

## `currency`

1. Call `update_data` with `scope: "currency"`. It reads the six listing pages of poe2db.tw
   (three pages in both languages) and the own page of each item it has not read yet (the drop
   level). When the user asks to refresh every item, add `older_than_days: 0` (or `N` for pages
   older than N days). One call makes at most 50 requests and keeps its progress for 30
   minutes; nothing is written until every page is fetched and checked.
2. While `done` is false, call it again with the same arguments, at most 16 calls in total;
   give one line of progress per call (`fetched`, `left`). A first update reads about 620 item
   pages; later ones only new items.
3. When `done` is true, report `records`, `categories`, `added`, `removed` and
   `item_pages_failed`.

## `atlas`

1. Call `update_data` with `scope: "atlas"` and no other argument. It makes 2 requests: the
   Waystones page of poe2db.tw in both languages (waystone tiers and their area levels, the
   resistance penalty, the waystone modifiers).
2. Report `waystone_tiers`, `area_levels`, `resistance_penalty_rows` and `waystone_modifiers`.

## Always

- When a call returns an error, show the error and stop.
- Never call `update_data` with a scope the user did not name.
- The update changes the plugin's own copy of the data; a plugin update replaces it.
