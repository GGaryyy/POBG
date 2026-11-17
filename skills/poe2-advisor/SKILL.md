---
name: poe2-advisor
description: Answer Path of Exile 2 questions and write build advice from the local poe2db data with source links, ending with a Path of Building code. Use when the user asks about a PoE2 skill / support / spirit gem, a passive node or keystone, a game term (e.g. Stun, Critical Hit), "which passives give X", the campaign (an act / 章節, area, boss, quest or quest reward), a currency item (an orb, essence, omen, rune or soul core / 通貨, 精髓, 預兆, 符文: what it does, its levels, which items change another), wants a build / 流派 / 配裝 / 開荒 recommendation, or a PoB code / 匯入碼 for one, in English or 繁體中文.
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
   for a Path of Building code of a build use `export_pob`;
   for gear use `get_item` (one base or unique), `items_by` (by class, text or level; add
   `with_lines: true` to list a class with what each item does in one call) and
   `modifiers_for` (what an item class can roll, with tiers);
   for the campaign use `get_area` (an area or a boss: level, bosses and what they grant,
   connected areas, rewards, the community walkthrough, the quests there), `get_quest` (type,
   rewards, objectives) and `campaign_by` (areas, quests, bosses or permanent `reward`s of an act
   or with some words, e.g. `kind: "reward", text: "天賦點"` for "which quests give passive points").
   Boss tactics beyond the walkthrough text are not in the data: say so.
   For currency use `get_currency` (one item: effect lines in both languages, stack size,
   minimum modifier level, required and drop level, and `related`: the items whose effects name
   it, e.g. the omens that change a Chaos Orb) and `currency_by` (by `category`: currency,
   essence, splinter, catalyst, omen, augment = runes and soul cores; by `text` in either
   language; by `max_level`: what drops and can be used by that level). For what an essence
   guarantees on an item class, follow its `note` to `modifiers_for` with the essence group.
   Prices, drop chances and crafting steps are not in the data (`not_in_data`): say so.
3. Quote the returned record and link the returned `sources`. If `fetched_at` looks old and
   the user needs current numbers, call `refresh_gem` (one page, the only network call).
4. Nothing found → say it is not in the local data and show the closest names from `lookup_entity`.

## Cited build advice

1. Read the request (class, skill, playstyle, constraints) and decide the goal. **The default is a
   campaign build**: one that clears the campaign, given stage by stage (Act 1, Act 2, …, the
   Interludes). Make an endgame build (the steps without the campaign parts) only when the user
   names a level above the last stage's level or asks for maps / endgame / 後期. For a campaign
   build call `campaign_stages` first. Each stage's `limits` (level, passive and ascendancy points,
   skill gem level and tiers, support gem tier, support sockets, quest Spirit) come from the data;
   never estimate them yourself.
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
   For a campaign build plan the end of the last stage first, then each earlier stage: pass the
   stage's level as `max_level` to `gems_by`, `supports_for`, `items_by` and `modifiers_for`, so
   every choice can be had by then, and give a skill at most the stage's `support_sockets` supports.
3. Call `verify_build` with **every** gem, passive, item (`items`) and target modifier
   (`affixes`) the draft uses, in **one** call so the answer has one source list (`lang`: `en`
   or `zh-tw`, matching the answer). Lists take 40 entries, `affixes` 60 (ten slots × 6).
   For a build with a whole set of gear, and for every repeat check, pass `detail: "brief"`: it
   returns names and cite numbers only, and you already hold the records from the lookups.
   For a campaign build pass the last stage's level as `character_level`: what comes back in
   `too_early` (with `from_level`) is dropped or moved to a later stage.
4. For each entry in `unverified`: drop the name, or replace it from its `suggestions` or a new
   search, then call `verify_build` again with the final list. At most two rounds; after that,
   drop whatever is still unverified.
5. Call `path_to` with the class (or ascendancy) and the verified passives. Report the points
   it returns against the limits (`points.passive`, `points.ascendancy`) and the allocation
   order. When `over` is true, drop the passives with the largest `added_points` and call it
   again. The route is an approximation: say "about N points", not "exactly".
   For a campaign build list the targets most important first and pass `by_stage: true`:
   `stages` gives each stage's points and the passives reached by its end; targets in
   `after_campaign` are not reached in the campaign.
6. Compare with the ladder: call `reference_builds` (class and/or main skill) now that the
   draft exists. Use it only to say how this build differs from what ladder characters run:
   what is the same, what this build uses that they do not, what they use that it does not,
   with counts ("6 of 14 Deadeyes take X"). The ladder is a sample of top characters with
   endgame gear, not a reason to change the build: for a campaign build compare the main skill
   and ascendancy only, and when it has no matching characters (a new league) say so. When the
   user asks what is popular, `reference_builds` is the answer itself.
7. Write the build from the `verified` facts only, with a short "compared with the ladder"
   section. Do not name a gem, passive, item or
   modifier that was not verified. `verify_build` checks that names exist; it does not judge
   whether a support fits a skill (use `supports_for` for that). When the data does not cover
   something, say so.
   - For a campaign build, one section per stage, in this order: level and points; skills and
     supports (what to use, and when to switch to the main skill); passives reached; gear
     (bases, and target modifiers that level can roll); Spirit and persistent skills;
     ascendancy (trial and points); the stage's permanent quest `rewards` and `bosses`. What
     `campaign_stages` lists in `not_in_data` (boss tactics, the resistance penalty) is not in
     the local data: say so instead of guessing.
   - Modifiers are random (drops, vendors and currency all roll them), so present each slot's
     modifiers as targets in order of importance, not as what the item will have; getting
     all of them usually takes crafting. Quote the tier range from `verify_build`.
   - Damage and defences are not calculated; do not invent totals.
8. End the answer with `sources_markdown` from the last `verify_build` call, unchanged — it
   already lists the names that were removed. Add `source_markdown` from `reference_builds`
   below it, and for a campaign build the stage pages from `campaign_stages`.
9. Give a Path of Building code: call `export_pob` with the class (or ascendancy), the verified
   passives as `targets` (the same as for `path_to`, most important first) and one
   `"skill: support, support"` entry per skill group, main skill first, and the verified gear in
   `gear`: one `"slot: item; modifier; modifier"` per item, e.g. `"Ring 1: Ruby Ring; +# to maximum Life"`
   (slots: Weapon 1/2, Helmet, Body Armour, Gloves, Boots, Amulet, Ring 1/2, Belt, Charm 1-3,
   Flask 1/2; a unique takes no modifiers). For a campaign build pass `stage` = the last stage's
   `id` (not `character_level`): level, passive and ascendancy points, gem tiers, support sockets,
   item levels, modifier tiers and quest Spirit then follow that stage, and the code holds one
   passive tree per stage (PoB lists them at the top of the Tree tab). For an endgame build pass
   `character_level` when the user asked for a build at a level (123 passive points is level 100).
   Each modifier is written at the top of its best tier (for a stage, the best tier its level can
   roll), so say the PoB numbers are a goal: real items roll lower. The tool works out from the
   data, and you must not: the character level (from the points spent, or the stage), each skill
   gem's level (the highest that level can use, from the gem's level table) and which attribute
   each attribute passive gets (toward the gems' requirements first). Put `code` in a code block
   after the sources, followed by `how_to_import` and `notes`. Say what `not_exported` left out
   and why. Report `summary.attributes`:
   where `need` is above `have`, the Strength / Dexterity / Intelligence the gems and gear
   require is not met by the tree and the exported gear, so say what is missing and where it
   could come from (more attribute modifiers on gear, other gems). `summary.spirit` works the
   same way for persistent skills: each spirit gem reserves Spirit and some supports add to it;
   when `need` is above `have`, drop a persistent skill or such a support (or add Spirit on
   gear) and export again, so the code does not open in PoB with a warning.
   The code also switches on PoB Configuration options (charges, enemy Shocked / Bleeding /
   Exposure and so on) for which the build itself has evidence; `summary.config` names each with
   its source gem, passive or item. List them: PoB's damage figure assumes these states. When
   comparing with a ladder character, say which of poe.ninja's assumed states this build lacks. An older
   PoB skips or refuses what it does not have: suggest the `pobg:update-pob` command
   (`/pobg:update-pob` in Claude Code, `$pobg:update-pob` in Codex).

## Notes

- A mechanic the build depends on (Frenzy / Endurance / Power Charges 狂怒球／耐力球／暴擊球, an
  ailment, a resource) needs a source in the build: `explain_keyword` for the rule, then
  `gems_by` with `text` (Chinese terms are searched by their English name) and
  `passives_with_stat` for what grants or uses it. Say so plainly when none is found.

- Ladder summaries never include character names; do not ask for or add them.
- Tool errors carry the fix (for example "run python -m src.kg.build_graph"); pass that on
  instead of guessing an answer.
