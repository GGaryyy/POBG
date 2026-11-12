# MCP tools and prompts

**English** | [繁體中文](tools.zh-TW.md)

What the `pobg` server offers an AI client. Players do not call these by hand: the assistant
picks them. The build workflow that ties them together is in
[`src/tools/build_workflow.py`](../src/tools/build_workflow.py) (also the `build_guide` prompt and
the `build_workflow` tool) and, for Claude Code, in
[`skills/poe2-advisor/SKILL.md`](../skills/poe2-advisor/SKILL.md).

## Tools

| Tool | Answers |
|---|---|
| `lookup_entity` | name (English / 繁中) → entity, kind, both poe2db URLs |
| `get_gem`, `get_passive`, `explain_keyword` | one record with its sources |
| `passives_with_stat` | which passives give a stat |
| `gems_by` | gems by tag, tier, class, weapon, kind or free text |
| `supports_for` | every support gem that can support a skill |
| `reference_builds` | what ladder characters run (class, main skill, rank, gems, keystones — no character names); a build answer uses it to show how the generated build differs from the ladder, not to pick the build |
| `verify_build` | checks a draft build's gems, passives, items and target modifiers ("Rings: +#% to Fire Resistance": the whole modifier, at most 3 prefixes and 3 suffixes per item; a partial wording comes back with candidates); returns facts, removed names and a finished source list |
| `path_to` | which passives to allocate, in order, to reach target passives from a class start; points against the 123 / 8 limits and the route's stat totals (approximate route) |
| `export_pob` | a Path of Building build code: class, ascendancy, the `path_to` route, skill groups ("skill: support, support"), gear ("slot: item; modifier; modifier") and PoB Configuration options; names that do not verify, supports that cannot support the skill and modifiers the item cannot roll are listed in `not_exported` instead. See [below](#export_pob) |
| `get_item` | one gear base (properties, requirements, implicit) or unique item (its modifiers), with sources |
| `items_by` | bases and uniques by item class, kind, required level or text |
| `modifiers_for` | what an item class (or a base or unique's class) can roll: modifiers grouped by family, every tier's level and value range, prefix or suffix; also desecrated, essence, corrupted and socketable effects |
| `build_workflow` | the step-by-step workflow for a cited build answer, for clients that cannot use MCP prompts |
| `refresh_gem` | re-fetches one gem page from poe2db and replaces the local record |
| `data_status` | what the local data holds and how old it is; on request, a check of the live sites |
| `update_data` | re-fetches one data set (a scope is required: three gem kinds, passives, items, glossary, ladder), a bounded number of requests per call |

Prompts: `build_guide` (the build workflow), `status` and `update` (the data commands, see
[data.md](data.md#commands)). Only `refresh_gem` and `update_data` change anything; the other
sixteen tools are marked read-only, and of those only `data_status` can reach the network, when
asked to check the live sites.

## `export_pob`

Writes no file and makes no request. Returns `code`, `how_to_import`, `notes` (also written to
PoB's Notes tab), `not_exported` and a `summary`:

| Summary field | Worked out from |
|---|---|
| `level` | the passive points spent, with PoB's own level formula and act table (123 points is level 100), or `character_level` when given |
| gem levels | each skill gem at the highest level-table row the character level allows (at most 20); supports have no level |
| `attributes` | have / need per attribute. Need: the highest of each skill gem's requirement, the supports' "+N" additions summed, and the highest gear requirement. Have: class base plus fixed attributes on passives and gear. The route's attribute passives go to what the gems and gear need first, or to `attribute` when given. % increases and reduced requirements are not counted |
| `spirit` | have / need, as PoB computes it. Need: (each persistent skill's reservation + its supports' additional reservation) × the supports' reservation multipliers, rounded half up; a support that moves reservation to Life counts 0. Skills whose reservation the data gives only as a range over gem levels (minion skills) or not at all are listed in `unknown`. Have: every Spirit quest reward (PoB's default), a sceptre's base Spirit, fixed "+N to Spirit" on gear and passives |
| `config` | each PoB Configuration option switched on, with its evidence (gem, passive, gear line or glossary rule) |

**Gear** is checked like `verify_build`: bases and uniques against the local data, a rare's
modifiers against what the item class can roll (3 prefixes + 3 suffixes, one per family), written
at the upper end of their best tier. Off-hand rules follow PoB's. Flasks and charms are switched
on. Quality, runes and soul cores, sockets and jewels are not exported; 13 bases and 11 uniques
have no PoB counterpart of the same name, and a base or line PoB does not know is skipped or
marked unsupported there. A rare's name is a plain label ("POBG Ring 1"): the game names rares at
random and PoB does not use the name. Without a weapon, attack skills show as disabled.

**Configuration** (`config=True` by default): an option is switched on only when the build itself
gives evidence for it:

- a charge the build gains (not one it only consumes or whose maximum it changes);
- an enemy state it inflicts (not one it only benefits from, consumes, aggravates, or whose
  chance it changes); a "cannot …" line rules the state or charge out for its skill group;
- Shock, Chill or Ignite from a damaging skill of that element, per the glossary rule (not a
  buff, aura, curse or other non-hitting skill), or, for an attack build, the main-hand weapon's
  element;
- Exposure from the text or the gem's tags; Crit Recently when a stat needs it.

Charges are counted at PoB's maximum (the "count if not maximum" box stays empty). The notes
name the options poe.ninja's ladder exports assume for every character that this build has no
source for. The rules are text patterns over the game's wording, audited over every gem and
passive; see `tests/unit/test_config_rules.py` for the sentences they are held to.
