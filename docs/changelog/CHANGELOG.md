# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **The `ladder` update scope is now `ninja`** (`update_data(scope="ninja")`, `/pobg:update ninja`),
  as the user found `ladder` unclear: `ninja` says where the data comes from. The data set's
  `name` and `update_scope` in `data_status` change with it. `ladder` is no longer accepted (no
  alias: the repo had no users yet) and gets the error that lists the seven scopes. The ladder
  snapshot itself, `reference_builds` and the data file are unchanged
  (`docs/plan_data_commands.md`).
- READMEs (English and 繁體中文) rewritten for players who install POBG to use it
  (`docs/plan_readme.md`): a quick start, what a build answer contains, and a new section on
  importing into Path of Building that says which numbers are worked out from the data and
  which are assumptions (ideal gear values, Configuration options from the build's own
  evidence, charges at their maximum, poe.ninja's fixed ladder states). The old README
  example "gear comes in a later version" was out of date since 0.10.0.
- Developer material moved out of the READMEs, unchanged in substance: the tool table and
  `export_pob` details to the new `docs/tools.md`; data sources, request etiquette, update
  scopes, the PoB updater command, the terminal crawl and development to the new
  `docs/data.md`. `docs/data.md` also names PoB's `QuestRewards.lua`, fetched since 0.9.0.
- Traditional Chinese versions of the developer docs: `docs/clients.zh-TW.md`,
  `docs/tools.zh-TW.md`, `docs/data.zh-TW.md`; each doc links to its other language, and the
  Chinese README links to the Chinese docs.
- The Commands section of both READMEs lists the four commands in full again, with the seven
  `update` scopes and examples, and a line thanking the data sources.
- The uv requirement is stated as a version only (0.13.4 or newer) in the READMEs and client
  guides, without the certificate explanation, at the user's request.
- ROADMAP: two next phases named by the user on 2026-11-13: the unique items that make a build
  (unique jewels in the passive tree, uniques that enable a build; scope still open), then gear
  crafting (the former "Crafting and currency").
- The command flowcharts are now SVG images (`docs/flow/img/`, 20 files) instead of Mermaid blocks:
  GitHub drew the Mermaid charts narrow, with the text wrapped into small boxes. The images are
  drawn by `docs/flow/render_charts.py` (standard library only) from `docs/flow/commands_charts.json`,
  which holds each chart's nodes, routes and both languages' text, so they stay editable.
- The English README's example questions are English only.

### Fixed
- The `update_data` tool description said `passives` makes 7 requests; it has made 8 since 0.9.0.

### Added
- `docs/flow/commands.md` and `docs/flow/commands.zh-TW.md`: flowcharts of the four
  commands with every decision and stop: `poe2-advisor` (and what `export_pob` works out),
  `status`, `update` (an overview and one chart each for the gem scopes, `passives`, `items`,
  `glossary`, `ladder`) and `update-pob`. Linked from the READMEs.

## [0.10.0] - 2026-11-12

Path of Building export, part 2: gear (`docs/plan_pob_export.md`, "第二段").

### Added
- `export_pob` takes `gear`: one `"slot: item; modifier; modifier"` entry per item (Weapon 1/2,
  Helmet, Body Armour, Gloves, Boots, Amulet, Ring 1/2, Belt, Charm 1-3, Flask 1/2; English or
  繁體中文 slots, items and modifiers; at most 16 entries). The item is a base or a unique
  checked against the local data. A rare's modifiers are checked like `verify_build`'s affixes
  (what the item class can roll, the whole wording, 3 prefixes + 3 suffixes per item, one per
  family) and written at the **upper end of their best tier**, a stated ideal (decided
  2026-11-12; choosing a tier or value is kept for later). A unique keeps its own modifiers;
  implicits are written too. The code carries PoB's item text (`Rarity`, name, base,
  `Implicits`, one line per modifier) and an item set with the slots. A rare is named
  "POBG <slot>": the game names rares at random and PoB does not use the name.
- Left out and listed in `not_exported`: unknown or ambiguous items, an item class given as an
  item, an item in a slot it does not fit, a second item in one slot, an off-hand next to a
  two-handed weapon (a bow keeps its quiver), modifiers the class cannot roll or written in
  part, over the 3 + 3 cap or a second of one family, modifiers with no English text, and
  modifiers given for a unique.
- Gear enters the attribute plan: an item's own requirement is one more source of need, its
  fixed attributes ("+33 to Dexterity", "+10 to all Attributes") add to what the build has.
- Notes: gear values are an ideal; an item above the character level; the attack-skill warning
  only when there is no weapon. Flask and charm slots are written switched on.
- The code carries PoB Configuration options (decided 2026-11-12: on by default, each one only
  with a source in the build). Charges (Power, Frenzy, Endurance) when an exported gem or passive
  says the build gains them; enemy Shocked, Ignited, Chilled, Frozen, Bleeding, Poisoned, Blinded,
  Dazed and the three Exposures when the build's text says it inflicts them (lines that only
  consume, benefit from or modify a state, or only change a chance, do not count; a "cannot …"
  line rules the state or charge out for its skill group); Chill, Shock or Ignite also from a
  damaging skill (not a buff or aura) or, for an attack build, the weapon of that element, per the
  glossary; Crit Recently when a stat needs it.
  `summary.config` gives each option with up to three sources; charges count at their maximum;
  the notes name poe.ninja's ladder assumptions this build has no source for; `config: false`
  leaves the Configuration empty. A rule audit over all 1,012 gems and 4,714 passives is in the
  test report.
- Spirit is checked like attributes (`summary.spirit`: have / need, and a note when short).
  Need: as PoB computes it, (each spirit gem's reservation + its supports' "Additional
  Reservation") × the supports' reservation multipliers, rounded; a support that moves the
  reservation to Life counts 0. Skills whose reservation the data gives only as a range over gem
  levels (minion skills) or not at all are listed in `unknown`, not counted. Have: every Spirit
  quest reward (PoB's default; stored as `pob_spirit_quests` with the level table, no extra
  request; the note names the game's area levels), a sceptre's base Spirit, and fixed "+# to
  Spirit" on gear and passives. A level-90 test build reserved 130 of 100, as PoB warned.
- Off-hand rules follow Path of Building: a quiver only behind a bow, nothing behind a two-handed
  weapon (traps included), no weapon behind a wand or sceptre, a sceptre but not a spear or wand
  in the off-hand. "ring" / "charm" without a number take the next free slot.

### Fixed
- A modifier with two stats (481 normal prefixes such as "% increased Physical Damage" with
  "+# to Accuracy Rating", 1,029 modifier texts in all, plus 23 base implicits and 29 uniques'
  lines) was stored as one run-together line, because the collector dropped the page's line
  break. The stats are now separate lines (a line break inside `text`; separate entries in
  `implicits` and `mods`), so `modifiers_for` shows them as the game does and the PoB code
  writes one line per stat. Data re-parsed from the page cache: same records, fetch times kept.
- Lines the game does not show are not written into the code: unique lines marked "(Hidden)" and
  untranslated internal stat lines on bases and uniques (109 lines in the data).

### Changed
- Version 0.10.0; User-Agent `POBG/0.10`. Workflow step 9 and the `poe2-advisor` skill pass the
  verified gear to `export_pob`.

## [0.9.0] - 2026-11-12

Path of Building export, part 1 (`docs/plan_pob_export.md`): class, ascendancy, passive tree
and skill gems. Gear is part 2.

### Added
- MCP tool `export_pob` (eighteen tools in all, read-only, no network, writes no file): a Path of
  Building (PoE2) build code for a class or ascendancy, the `path_to` route to the given target
  passives, and skill groups written `"skill: support, support"` (English or 繁體中文, at most
  12 groups and 5 supports each). Only names that match the local data go in; a support that
  cannot support its skill (per the knowledge graph), an unknown name, a gem whose record has
  no game id, an unreachable passive and an ascendancy PoB has no id for are listed in
  `not_exported` with the reason, as are a skill listed as its own support, a second group for
  the same skill and a `main_skill` with no group. Attribute passives on the route are written
  as PoB's attribute choice (`attribute`: str / dex / int, default the main skill gem's
  attribute); without one PoB gives them no attribute at all. An ascendancy PoB has no id for is
  left out with its passives and the route is made again without it. The answer carries the
  code, `notes` (no gear, skill gems level 20 / quality 0 and supports level 1, attack skills
  disabled until a weapon is added, update PoB first, budget overruns, supports not checked when
  the knowledge graph lacks the skill) and `how_to_import` in the answer language.
- `src/tools/pob_export.py`: builds PoB's XML (Build, Tree, Skills, Notes sections) and the
  code (zlib, base64 with `-` and `_`), and reads a code back (`decode_code`, bounded against
  oversized and cut-off input). Gems are named by PoB's `gemId` (the game's item type) and
  `variantId` (the game id), which match PoB 0.23.1's gem table for every collected gem PoB has
  (946 of 1,012).
- Command `/pobg:update-pob <folder>` (plugin skill, user-invoked) and
  `python -m src.tools.pob_update --dir <folder> [--check]`: updates a local Path of Building,
  alone or inside a PoeCharm2 (中文化) folder, into a new folder next to the old one. The PoB
  release file is checked against GitHub's published SHA-256; PoeCharm2 has no releases, so its
  latest commit is used (no checksum). Saved builds and PoeCharm2's language setting are copied,
  `Settings.xml` (account login) is not; the old folder is never changed. The new folder is
  named by PoB's version (`PathOfBuildingCommunity-PoE2-Portable-0.23.1`,
  `PoeCharm2-20260728-pob0.23.1`). Unsafe archive paths, archives over 4 GB unpacked, downloads
  larger than published, odd GitHub replies (checked link host, size, SHA-256, commit sha and
  date) and too little disk space stop the update before anything is kept; work folders left by
  an interrupted run are removed after an hour; progress goes to stderr.
- The code carries the character level PoB's automatic mode would set (`pob_level`, PoB's own
  formula; 123 points is level 100). PoB sets that level only after calculating, so a code saying
  level 1 showed level-1 life and mana (seen in a real import: 65 life instead of 242).
  `character_level` (1–100) asks for a level instead; a route that needs more gets a note.
- Levels and attributes are worked out by code from the data, not by the model. Each skill gem is
  written at the highest level the character can use, from the gem's level table (it was always
  20, which a level-15 character cannot use). The attributes the gems require (combined as
  PoB does: the highest of each skill gem at that level and of all support additions together)
  are compared with what the build has (class base
  attributes plus fixed attributes on the route), each attribute passive goes to the attribute
  furthest below its requirement, and the rest to the main skill's attribute.
  `summary.attributes` gives have / need; what the tree cannot cover is noted as needing gear.
- `path_to` no longer routes through another class's start node, and passives that are
  allocated for free (`no_point`) no longer count as points.
- The passive collector stores PoB's class `integerId` and ascendancy `internalId` as `pob_id`,
  and PoB's act table for its level estimate (`pob_level_acts`, from PathOfBuilding-PoE2
  `src/Data/QuestRewards.lua`) and each class's base attributes, in
  `data/passive_tree/classes.json`. A failed download of the quest file no longer stops the update. `update passives` now makes
  8 requests (was 7); re-collected, no node changed. The entity index rebuilt with it picked
  up nine gem names poe2db has since changed in Traditional Chinese (seven skill gems, one
  spirit gem, one support gem).
- Build workflow, server instructions and the `poe2-advisor` skill: a ninth step gives the
  Path of Building code after the sources.

### Changed
- Version 0.9.0; User-Agent `POBG/0.9`.

### Security
- The READMEs and `docs/clients.md` now require uv 0.13.4 or newer. Older uv versions still
  trust the eMudhra / emSign intermediate certificates whose private keys were exposed in
  October 2026, so the packages uv downloads from PyPI at first start could be intercepted.
  Checked on 2026-11-12: the locked `certifi` (2026.10.23) and the server's own connections
  reject those certificates, and every file hash in `uv.lock` matches PyPI. No code or
  dependency changed.

## [0.8.0] - 2026-11-11

Gear data (Phase 16a, `docs/plan_gear_data.md`).

### Added
- Collector `src/scrapers/collect_items.py`: 69 poe2db item class pages (English and
  Chinese, 138 requests, 0.8 s apart): weapons, armour, jewellery, belts, flasks, charms and
  jewels. Writes `data/items/bases.jsonl` (1,762 bases: properties, requirements, implicits),
  `uniques.jsonl` (434 uniques and their modifier text; other versions of the same unique,
  such as the three Grand Spectrum jewels, are kept as `variants`), `modifiers.jsonl` (17,719
  modifiers from the page's embedded modifier data: group, prefix / suffix, name, level,
  family, text, tags, tier) and `classes.json` (63 modifier pages). Jewel modifiers come from
  each jewel's own page; class names come from the page title where the page has no modifier
  data. What a charm grants when used (`effects`, e.g. "+25% to Fire Resistance") is collected
  with its base. Lineage supports were already covered (77 of 77); ascendancy pages add nothing the
  passive tree data lacks. Chinese
  names join by slug, modifiers by family, level and affix; a page whose tab count and parsed
  cards differ, or that has no modifier data, stops the collection. Spawn weights are not stored.
- MCP tools `get_item`, `items_by` and `modifiers_for` (`src/tools/items.py`), seventeen tools in
  all. Bases and uniques are in the bilingual name index (`item_base`, `item_unique`).
- `verify_build(items, affixes)`: item names are checked like gems and passives;
  each affix ("Bows: #% increased Attack Speed", 「戒指：+#%火焰抗性」) is checked against what that item
  class can roll and returns its family, prefix / suffix, tier count and the best and lowest
  tier. Only the whole modifier verifies (every word, in either language; numbers optional, but
  not above the best tier); a partial wording is unverified and returns the candidate
  modifiers. Per item at most 3 prefixes and 3 suffixes (the most a rare item holds) and one
  modifier per family; an entry over that, an armour class with several attribute pages, or a
  Chinese name poe2db gives to two items is reported as unverified instead of failing the call.
  Item class pages appear in the source list. `affixes` takes 60 entries (ten slots × 6) so a
  whole build is checked in one call with one source list; a modifier fact gives its tier texts
  in the answer language and cites its page by number instead of repeating the links.
- `update_data` scope `items`: at most 20 requests (10 class pages) per call, resumable for 30
  minutes from a cache under `output/cache/items_update/` (one folder per set of pages,
  abandoned ones removed), written once when every page is fetched and validates. Every page
  must still yield items or modifiers, and at least 90 % of modifiers must have Chinese text.
  `names` limits it to some classes (`Body Armours` or `胸甲` covers its attribute pages, a page
  slug only that page) and merges them into the stored data by the page each item came from
  (`item_page`), so a partial update writes what a full run would. `data_status` lists the
  items data set; the online check parses one item class page.
- Build workflow, server instructions and the `poe2-advisor` skill gain a gear step: pick bases
  or uniques, then per slot the target modifiers in order of importance, presented as targets
  because modifiers are random; damage is not calculated.

- Frenzy, Endurance and Power Charges (狂怒球、耐力球、暴擊球) resolve to the Charges glossary
  entry in `lookup_entity` and `explain_keyword` (`keyword_subterms` in the catalog), and
  `gems_by(text)` searches a Chinese glossary name or charge name by its English name
  (`text_searched`), since gem descriptions are stored in English; a Chinese text with no
  known term says so instead of returning nothing silently.

- `verify_build(detail)`: `brief` returns names and cite numbers only, for a caller that
  already holds the records (a build with a whole set of gear, a repeat check): 22,000
  characters for 18 gems, 22 passives, 9 items and 54 modifiers, against 46,000 in full.
- `items_by(with_lines)`: each item with its own lines in both languages, so "which charms
  exist and what do they do" is one call instead of one `get_item` per item.

### Changed
- `verify_build` facts no longer repeat their source links (the numbered source list and
  `cite` carry them), and the MCP tool no longer returns the structured `sources` rows next
  to `sources_markdown`, which holds the same rows. A measured build answer had taken 8
  minutes because the 55,000-character response was saved to a file and parsed by the client.
- Build workflow: the build is generated from the poe2db records, with a reason from the data
  for every choice; `reference_builds` is called after the draft, only to state how the build
  differs from what ladder characters run (it used to be an optional first step, and answers
  chose a skill "because the ladder uses it").
- Version 0.8.0; the scrapers' User-Agent says `POBG/0.8`.
- READMEs, client guide, ROADMAP and flow diagrams describe the gear data, the new tools, the
  `items` scope and the item class pages as a data source.

## [0.7.0] - 2026-11-11

First public release. Earlier versions were developed privately; this repository starts from
that work with a new history.

### Added
- Data commands (`docs/plan_data_commands.md`): `status` and `update <scope>`, as Claude Code
  plugin skills (`/pobg:status`, `/pobg:update`, the latter user-invoked only) and as MCP
  prompts for every other client.
- MCP tool `data_status(check_online)`: record counts, fetch dates and ages per data set,
  passive tree versions, ladder snapshot date and league; optionally the catalog probe.
- MCP tool `update_data(scope, names, older_than_days, max_gems, dry_run)`: re-fetches one data
  set (`skill_gems`, `spirit_gems`, `support_gems`, `passives`, `glossary`, `ladder`). A scope is required, gem
  scopes fetch at most `max_gems` pages per call and report what is left, a dry run writes
  nothing, and the server reloads its data afterwards (`src/tools/maintenance.py`).
- `glossary` scope: at most 50 requests per call, resumable for 30 minutes from a cache under
  `output/cache/`, written once when the whole glossary is fetched and at least 90 % of the
  known terms were reached. Terms are merged field by field, so a term never loses text the
  crawl did not get; a crawl that finds Chinese text for fewer than half of the terms that
  had it is refused; five hover failures in a row end the call with its progress kept.
- `ladder` scope: a new poe.ninja snapshot (about 14 requests), refused when it has fewer than
  100 characters, mostly lacks class or skill names, has no keystones, is much smaller than
  the previous snapshot of the same league, or when any result page failed.
- `collect_kind(max_targets, dry_run, skip_recent_seconds)`: capped and dry incremental gem
  runs; gems left for later (or whose page failed) keep their previous listing row; a gem
  fetched recently is not selected again by name or age; summaries gain `targets_total`,
  `targets_left`, `reasons`, `recently_fetched`.
- A cross-process lock on `data/.update.lock` (an OS lock: `flock` / `msvcrt`, released when the
  holder exits or crashes) so that `update_data`, `refresh_gem` and the online check from two
  processes never run on the same data folder at once.
- MCP tool `build_workflow(lang)`: the cited-build steps for clients that cannot use MCP
  prompts. The server instructions point to it. Fourteen tools in total.
- Tool titles and annotations: twelve tools are read-only (`data_status` can reach the network
  on request); `refresh_gem` and `update_data` are marked as destructive and open-world.
- `tests/unit/test_tool_portability.py`: tool names, description length, flat input schemas,
  annotations and titles, as other MCP clients require them.
- `docs/clients.md`: configuration for Claude Code, Claude Desktop, Cursor, VS Code, Gemini CLI
  and Codex CLI, with tested / not tested labels, measured response sizes and five check prompts.
- `README.zh-TW.md`; a "Data sources and scope of use" section in both READMEs.
- `.gitattributes` (LF everywhere), a `dev` dependency group (`pytest`, `pytest-cov`, `ruff`).

### Changed
- Names: repository `GGaryyy/POBG`, Python project, plugin and MCP server `pobg`
  (skill `/pobg:poe2-advisor`), scraper User-Agent
  `POBG/0.7 (+https://github.com/GGaryyy/POBG; research scraper)`.
- Launchers use `uv run --frozen --no-dev` (plugin manifest and documentation), so
  the server environment never includes the test tools.
- `passives_with_stat` returns at most 100 nodes per list (was 200): 200 rows with
  `include_without_page` exceeded 140,000 characters.
- `README.md` is English only and describes only what this repository contains.
- The probe, the entity index and the passive collector wait the catalog's
  `polite_delay_seconds` (0.8 s) before each request; they used 0.5 s.
- `refresh_gem` waits the same delay, caches the fetched page before it replaces the record,
  and is annotated as a destructive update.
- `passives_with_stat` lists `available_kinds` when no stat has the requested `kind`.
- Each gem is stored once: poe2db's Skill Gems page also lists every spirit gem, and the gem
  collector now skips skill-listing rows that the spirit gem data already holds
  (`stored_elsewhere` in its summary). The 53 duplicate records were removed from the skill
  gem data (347 skill, 53 spirit, 612 support gems). Should a gem still exist under two
  kinds, `get_gem` answers from the newer copy.
- The project rules moved from `CLAUDE.md` to `.claude/CLAUDE.md`, so the plugin root holds no
  `CLAUDE.md` and `claude plugin validate --strict` passes.
- One detail page that fails to download no longer aborts an incremental gem run; it is
  reported in `skipped`. More than one (or more than 2 %) still aborts.
- `stat_families.json` is written atomically.
- A gem page that stays unparsable no longer blocks its scope: pages that were already broken do
  not count as markup drift, and one is not fetched again within 15 minutes. A run stops as soon
  as too many pages failed. Stale gems are fetched oldest first.
- Glossary: gem pages used to find terms are optional (a dead one no longer stops the run); tiny
  hover bodies are asked once per run; a term that keeps old text keeps its old date; the index
  is rebuilt before the run cache is removed.
- Every passive node stores when it was built (`fetched_at`), so the sources of passives in
  `get_passive`, `verify_build` and `path_to` show a date like gems do, also for nodes without a
  poe2db page.
- Data files are written with LF line endings on every platform (an update run on Windows
  wrote CRLF).
- The poe.ninja ladder fetcher identifies itself with the project User-Agent instead of a
  browser string, drops the `Referer` and waits 0.8 s before each request.
- The ladder fetcher reads poe.ninja's current response layout (columns in protobuf field 12,
  dictionaries in the binary "NDIC" container) and takes the main skill from the site's DPS
  skill column instead of the first listed skill. The snapshot was refreshed: 593 characters
  of the league "Runes of Aldur" (it was 588 of "Fate of the Vaal", 2026-03-04).

### Fixed
- The ladder fetcher printed one raw record, including its character and account name, in its
  summary; it now prints the stored form without names.
- Over-long `lang` and `kind` arguments are refused instead of being echoed in the error.
- The ladder fetcher's output path no longer depends on the working directory.
- The test suite also collects on Python 3.10 (`tomli` fallback).

### Removed
- The project `.mcp.json`: the plugin registers the server; a second registration gave Claude
  Code two identical tool sets when both were active. Develop with `claude --plugin-dir .`.
- The local LangGraph / Ollama pipeline, the FastAPI service, the FAISS indexes and
  retrievers, their tests, the legacy notebook and `requirements.txt`. The project is the MCP
  server and the plugin.
- Docker is no longer part of the project rules; there were no Docker files.
