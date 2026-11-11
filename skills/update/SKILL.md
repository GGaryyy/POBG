---
name: update
description: Update one local Path of Exile 2 data set from its source. A scope is required (skill_gems, spirit_gems, support_gems or passives); there is no update for everything.
argument-hint: <skill_gems|spirit_gems|support_gems|passives> [gem names, comma-separated]
disable-model-invocation: true
---

# poe2db data update

Arguments: `$ARGUMENTS`

The first word is the scope; anything after it is a comma-separated list of gem names.

**No scope, or a word that is not one of `skill_gems`, `spirit_gems`, `support_gems`,
`passives`:** do not call `update_data`. Tell the user to pick one scope, for example
`/poe2db:update skill_gems`. The glossary and the ladder snapshot cannot be updated by command
(`data_status` says why).

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

1. Call `update_data` with `scope: "passives"` and no other argument. It makes 7 requests: the
   PathOfBuilding-PoE2 tree, two poe2db tree data files and four listing pages.
2. Report `records`, `changed`, `added`, `removed` and the tree versions.

## Always

- When a call returns an error, show the error and stop.
- Never call `update_data` with a scope the user did not name.
- The update changes the plugin's own copy of the data; a plugin update replaces it.
