---
name: poe2-advisor
description: Answer Path of Exile 2 questions and write build advice from the local poe2db data with source links. Use when the user asks about a PoE2 skill / support / spirit gem, a passive node or keystone, a game term (e.g. Stun, Critical Hit), "which passives give X", or wants a build / 流派 / 配裝 recommendation, in English or 繁體中文.
---

# PoE2 advisor (pobg tools)

Every fact comes from the `pobg` MCP tools, which read a local copy of poe2db.tw and the
PathOfBuilding-PoE2 passive tree. Do not answer numbers, costs, tags or effects from memory:
the game changes every patch and the tools carry the fetch date of each record.

Answer in the user's language. The tools accept English and 繁體中文 names.

## Cited lookup (one gem, passive or term)

1. `lookup_entity` to turn the name into an entity (it returns the kind and both URLs).
2. One detail call: `get_gem`, `get_passive` or `explain_keyword`.
   For "which passives give X" use `passives_with_stat`; for "which gems …" use `gems_by`
   (tag, tier, class, weapon, kind or free `text`); for "what supports work with X" use `supports_for`;
   for "how many points to reach X" or "how do I path to X" use `path_to`.
3. Quote the returned record and link the returned `sources`. If `fetched_at` looks old and
   the user needs current numbers, call `refresh_gem` (one page, the only network call).
4. Nothing found → say it is not in the local data and show the closest names from `lookup_entity`.

## Cited build advice

1. Read the request (class, skill, playstyle, constraints).
2. Optional: `reference_builds` (class and/or main skill) to see what ladder characters run.
3. Gather candidates with `lookup_entity`, `gems_by`, `supports_for`, `passives_with_stat`,
   `get_gem` and `get_passive`.
4. Call `verify_build` with **every** gem and passive name the draft uses
   (`lang`: `en` or `zh-tw`, matching the answer).
5. For each entry in `unverified`: drop the name, or replace it from its `suggestions` or a new
   search, then call `verify_build` again with the final list. At most two rounds; after that,
   drop whatever is still unverified.
6. Call `path_to` with the class (or ascendancy) and the verified passives. Report the points
   it returns against the limits (`points.passive`, `points.ascendancy`) and the allocation
   order. When `over` is true, drop the passives with the largest `added_points` and call it
   again. The route is an approximation: say "about N points", not "exactly".
7. Write the build from the `verified` facts only. Do not name a gem or passive that was not
   verified. `verify_build` checks that names exist; it does not judge whether a support fits
   a skill (use `supports_for` for that). When the data does not cover something, say so.
8. End the answer with `sources_markdown` from the last `verify_build` call, unchanged — it
   already lists the names that were removed. When step 2 was used, add `source_markdown`
   from `reference_builds` below it.

## Notes

- Ladder summaries never include character names; do not ask for or add them.
- Tool errors carry the fix (for example "run python -m src.kg.build_graph"); pass that on
  instead of guessing an answer.
