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
   for "how many points to reach X" or "how do I path to X" use `path_to`;
   for gear use `get_item` (one base or unique), `items_by` (by class, text or level; add
   `with_lines: true` to list a class with what each item does in one call) and
   `modifiers_for` (what an item class can roll, with tiers).
3. Quote the returned record and link the returned `sources`. If `fetched_at` looks old and
   the user needs current numbers, call `refresh_gem` (one page, the only network call).
4. Nothing found → say it is not in the local data and show the closest names from `lookup_entity`.

## Cited build advice

1. Read the request (class, skill, playstyle, constraints).
2. Generate the build from the data, not from the ladder. Gather candidates with `lookup_entity`, `gems_by`, `supports_for`, `passives_with_stat`,
   `get_gem` and `get_passive`. For gear: pick a base or unique per slot with `items_by` and
   `get_item`, then the target modifiers per slot with `modifiers_for`, in order of
   importance for this build: at most **3 prefixes and 3 suffixes** (a rare item holds 6), one
   per modifier family, written as `"item: modifier"` with the whole modifier as `modifiers_for`
   shows it (numbers may be left out), e.g. `"Rings: +#% to Fire Resistance"`. The item is a
   class, base or unique; for armour use the base or an attribute page such as `Helmets_str`.
   A partly written modifier is not verified: pick the intended one from its `suggestions`.
   Give every choice a reason from these records (what the gem, passive or item does). "Ladder
   characters use it" is not a reason.
3. Call `verify_build` with **every** gem, passive, item (`items`) and target modifier
   (`affixes`) the draft uses, in **one** call so the answer has one source list (`lang`: `en`
   or `zh-tw`, matching the answer). Lists take 40 entries, `affixes` 60 (ten slots × 6).
   For a build with a whole set of gear, and for every repeat check, pass `detail: "brief"`: it
   returns names and cite numbers only, and you already hold the records from the lookups.
4. For each entry in `unverified`: drop the name, or replace it from its `suggestions` or a new
   search, then call `verify_build` again with the final list. At most two rounds; after that,
   drop whatever is still unverified.
5. Call `path_to` with the class (or ascendancy) and the verified passives. Report the points
   it returns against the limits (`points.passive`, `points.ascendancy`) and the allocation
   order. When `over` is true, drop the passives with the largest `added_points` and call it
   again. The route is an approximation: say "about N points", not "exactly".
6. Compare with the ladder: call `reference_builds` (class and/or main skill) now that the
   draft exists. Use it only to say how this build differs from what ladder characters run:
   what is the same, what this build uses that they do not, what they use that it does not,
   with counts ("6 of 14 Deadeyes take X"). The ladder is a sample of top characters with
   endgame gear, not a reason to change the build. When the user asks what is popular,
   `reference_builds` is the answer itself.
7. Write the build from the `verified` facts only, with a short "compared with the ladder"
   section. Do not name a gem, passive, item or
   modifier that was not verified. `verify_build` checks that names exist; it does not judge
   whether a support fits a skill (use `supports_for` for that). When the data does not cover
   something, say so.
   - Modifiers are random (drops, vendors and currency all roll them), so present each slot's
     modifiers as targets in order of importance, not as what the item will have; getting
     all of them usually takes crafting. Quote the tier range from `verify_build`.
   - Damage and defences are not calculated; do not invent totals.
8. End the answer with `sources_markdown` from the last `verify_build` call, unchanged — it
   already lists the names that were removed. Add `source_markdown` from `reference_builds`
   below it.

## Notes

- A mechanic the build depends on (Frenzy / Endurance / Power Charges 狂怒球／耐力球／暴擊球, an
  ailment, a resource) needs a source in the build: `explain_keyword` for the rule, then
  `gems_by` with `text` (Chinese terms are searched by their English name) and
  `passives_with_stat` for what grants or uses it. Say so plainly when none is found.

- Ladder summaries never include character names; do not ask for or add them.
- Tool errors carry the fix (for example "run python -m src.kg.build_graph"); pass that on
  instead of guessing an answer.
