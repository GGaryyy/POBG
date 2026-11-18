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
| `lookup_entity` | name (English / 繁中) → entity, kind, both poe2db URLs (gems, passives, glossary terms, items, campaign areas, quests and bosses, currency) |
| `get_gem`, `get_passive`, `explain_keyword` | one record with its sources |
| `passives_with_stat` | which passives give a stat |
| `gems_by` | gems by tag, tier, class, weapon, kind or free text; `max_level` keeps only gems that can be had by that level |
| `supports_for` | every support gem that can support a skill; `max_level` as in `gems_by` |
| `reference_builds` | what ladder characters run (class, main skill, rank, gems, keystones — no character names); a build answer uses it to show how the generated build differs from the ladder, not to pick the build |
| `verify_build` | checks a draft build's gems, passives, items and target modifiers ("Rings: +#% to Fire Resistance": the whole modifier, at most 3 prefixes and 3 suffixes per item; a partial wording comes back with candidates); returns facts, removed names and a finished source list; `character_level` moves what cannot be had yet to `too_early` and gives each modifier the best tier that level rolls |
| `path_to` | which passives to allocate, in order, to reach target passives from a class start; points against the 123 / 8 limits and the route's stat totals (approximate route); `by_stage` takes the targets in the order listed and cuts the route at each stage's points (acts and map stages) |
| `export_pob` | a Path of Building build code: class, ascendancy, the `path_to` route, skill groups ("skill: support, support"), gear ("slot: item; modifier; modifier") and PoB Configuration options; names that do not verify, supports that cannot support the skill and modifiers the item cannot roll are listed in `not_exported` instead; `stage` holds the code to a stage (an act or a map stage such as `maps_t16` / `T16`), with one passive tree per stage. See [below](#export_pob) |
| `get_item` | one gear base (properties, requirements, implicit) or unique item (its modifiers), with sources |
| `items_by` | bases and uniques by item class, kind, required level or text |
| `modifiers_for` | what an item class (or a base or unique's class) can roll: modifiers grouped by family, every tier's level and value range, prefix or suffix; also desecrated, essence, corrupted and socketable effects |
| `campaign_stages` | the stages of a build: the acts, then the map stages (waystone Tier 1, 10, 16; `maps: false` leaves them out), each with the limits a build has by its end (level, passive and ascendancy points, quest Spirit, skill gem level and tiers, support gem tier, support sockets, resistance penalty), an act's permanent quest rewards, trials and bosses, and what the data does not hold. See [below](#campaign-stages) |
| `get_area` | one campaign area, or the area of a boss: level, bosses and what they grant, connected areas, permanent rewards, the community walkthrough and the quests that name it |
| `get_quest` | one campaign quest: type, rewards and objectives in both languages, its act |
| `campaign_by` | campaign areas, quests, bosses or permanent rewards by act and / or words in either language |
| `get_currency` | one currency item (orb, essence, splinter, catalyst, omen, rune or soul core): effect lines in both languages (runes per item class), stack size, minimum modifier level, required and drop level, tags, and `related`: the items whose effects name it. See [below](#currency) |
| `currency_by` | currency items by category, words in either language, or `max_level` (drop and required level); no filter lists the categories |
| `waystone_mods` | the modifiers a waystone can have, one entry per modifier with its tiers, lines in both languages; by words or prefix / suffix. See [below](#map-stages-and-search-strings) |
| `search_string` | an in-game search string worked out from the data, in English and 繁中: gear with any of the wanted modifiers of an item class lights up, or waystones with any of the named modifiers stay dark. See [below](#map-stages-and-search-strings) |
| `build_workflow` | the step-by-step workflow for a cited build answer, for clients that cannot use MCP prompts |
| `refresh_gem` | re-fetches one gem page from poe2db and replaces the local record |
| `data_status` | what the local data holds and how old it is; on request, a check of the live sites |
| `update_data` | re-fetches one data set (a scope is required: three gem kinds, passives, items, glossary, ninja, campaign, currency, atlas), a bounded number of requests per call |

Prompts: `build_guide` (the build workflow), `status` and `update` (the data commands, see
[data.md](data.md#commands)). Only `refresh_gem` and `update_data` change anything; the other
twenty-four tools are marked read-only, and of those only `data_status` can reach the network, when
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

## Campaign stages

A build answer is by default a staged build: one that clears the campaign and then runs maps up to
Tier 16 waystones, given stage by stage (the acts, then Tier 1, 10 and 16 maps). `campaign_stages`
gives each stage's limits, cumulative up to its end, all from the data:

| Limit | Worked out from |
|---|---|
| `level` | an act: the highest area level of the stage on poe2db's Act page (towns left out); a map stage: the waystone tier's area level on poe2db's Waystones page (Tier 1 = 65, Tier 10 = 74, Tier 16 = 80 in 0.5.5) |
| `passive_points` | `level` − 1, plus the quest passive points of PoB's QuestRewards.lua up to the stage (PoB counts them as passive and as weapon-set points) |
| `ascendancy_points` | 2 for each campaign trial (Trial of the Sekhemas, the Trial of Chaos) whose area level the stage reaches; map stages add the endgame trials the catalog lists (`atlas.endgame_trials`: the third set at level 60, the fourth at 80, hand-checked on poe2db's Ascendancy_class page) |
| `quest_spirit` | the "+N to Spirit" quest rewards up to the stage |
| `skill_gem_level`, `skill_gem_tiers`, `spirit_gem_tiers` | the highest gem level the level allows (Uncut Skill Gem's level table) and the gemcutting tiers up to it |
| `support_gem_tier` | the highest Uncut Support Gem level that drops by the stage's area level |
| `support_sockets` | what the Jeweller's Orbs that drop by then set a skill to (2 before any) |
| `resistance_penalty` | the elemental resistance penalty from the stage's level on (the Waystones page's Level Resist Penalty table: −10 from 16 … −60 from 65); only with the atlas data |

poe2db keeps the Interludes as an Act: the Act page whose areas are the Interlude page's is named
after it, and an Act page without areas (a datamined act not yet in the game) is not a stage, so new
acts follow the data. `not_in_data` lists what answers must not guess: boss tactics beyond the area
walkthroughs, drop chances, Spirit from gear, and with the map stages: monster damage by area level, map
bosses and pinnacle fights, how Tier 16 waystones are obtained. Without the atlas data the stages are
the acts only, and `maps_note` says to run `update atlas`. `find_stage` (and `stage` on `export_pob`)
takes `maps_t16`, `T16`, `tier 16`, `第 16 階`.

With `stage`, `export_pob` holds the code to those limits: the level, the route taken in the order the
targets are listed and cut at the stage's points (targets beyond it go to `not_exported`), skill and
support gems of later tiers, more supports than the sockets, items that need a higher level and
modifiers whose every tier needs a higher item level are left out, and each modifier is written at
the best tier that level can roll. The code holds one passive tree per stage up to the chosen one.

## Currency

`get_currency` and `currency_by` answer what a currency item does. The categories are poe2db's tabs:

| Category | Holds |
|---|---|
| `currency` | the Stackable Currency tab: orbs (with their Greater / Perfect tiers), shards, abyss bones, liquid emotions, expedition and league items |
| `essence` | essences |
| `splinter` | splinters |
| `catalyst` | catalysts |
| `omen` | omens |
| `augment` | runes and soul cores (their effect lines are per item class, `implicits`, with `bonded` lines) |

A record carries what the listing page shows (stack size, `min_modifier_level` of Greater and Perfect
orbs, `max_item_level`, `limit`, `requires_level`, the effect lines in both languages) and what the item's
own page shows (`drop_level`: the lowest area level it drops in, `item_class`, `tags`, `type`).
`related` is found in the data: the items whose English effect lines name this one as a whole name, so
"Chaos Orb" finds the omens that change a Chaos Orb and not a line about a Greater Chaos Orb. What an
essence guarantees on each item class is in `modifiers_for` (group `essence` or `perfect_essence`).
`drop_level` is poe2db's DropLevel; an item that only comes from some content (a league mechanic, a boss, a
vendor) can show a low one, such as 1. Prices, drop sources and chances, and crafting steps are not in the
data; `not_in_data` says so.

## Map stages and search strings

`waystone_mods` lists the 106 waystone modifiers of poe2db's Waystones page grouped by wording (a
modifier's tiers differ only in their numbers), with every line in both languages: what makes monsters
harder and what the map gives for it. A build answer names only the modifiers whose lines work against
what the verified build relies on, quoting them; it never calls the others safe.

`search_string` works out a string for the in-game search box (stash and vendor windows) instead of the
model writing one:

| Kind | Input | String |
|---|---|---|
| `gear` | an item class (as for `modifiers_for`) and whole modifiers | `"piece|piece"`: items with any of them light up; several strings when over the limit, each usable on its own |
| `maps` | the waystone modifiers to leave out: a `waystone_mods` entry's `text` or `id`, one of its lines, or its words (numbers may be left out) | `"!piece|piece"`: waystones with any of them stay dark; pieces that do not fit the limit are in `left_out` |

Each piece is a piece of a modifier's wording that no other text of that item class holds: every modifier
group (also corrupted, essence and rune lines), and the names, implicits and property labels of its bases;
for waystones, every other waystone modifier and the tier names and property labels from the Waystones
page. Several English words come before one, and a lone word is never "from" or "increased"; Chinese pieces
are runs of Chinese characters, preferably three and at the start or end of a run, not starting or ending
with 的, 上 and the like. Pieces hold no numbers and never cross a line, so one string serves every tier and
stage. A piece that is shared anyway is listed in `also_matches`; a modifier with no wording in a language
is in that language's `missing` (the string is then not complete); each row says which modifier it
`matched`. The syntax (quotes, `|`, `!`) and the 250-character limit come from community guides, not
from GGG (`atlas.search` in the catalog); the game also searches an item's name and other lines, so a
string should be tried in the game, in the client's language.
