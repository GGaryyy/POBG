# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

## [0.15.0] - 2026-11-17

Builds that reach Tier 16 maps (`docs/plan_atlas_stages.md`). A league starter has to lead from the
acts straight into maps, so a build answer now goes on after the acts with map stages Tier 1, 10 and
16, and gives in-game search strings for the gear it names and for the waystones it can run. Boss
fights beyond maps are not planned; whether a build clears Tier 16 is not proven (damage and survival
are not calculated).

### Added
- `atlas` data and update scope (`src/scrapers/collect_atlas.py`, 2 requests): poe2db's `Waystones` page in
  English and Chinese — the waystone tiers and their area levels (Tier 1 = 65 … Tier 16 = 80), the Level
  Resist Penalty table, and the 106 waystone modifiers with their lines in both languages (Chinese rows
  joined by place, checked by level and prefix / suffix). Nothing is written when a stage tier is missing,
  rows are too few or too little Chinese is found. `data_status` reports it.
- Map stages in `campaign_stages` (`src/tools/atlas.py`): `maps_t1`, `maps_t10`, `maps_t16` after the acts
  (catalog `atlas.stage_tiers`), each held to the same rules: level = the tier's area level, passive points
  and gem limits as for the acts, and ascendancy points with the third and fourth sets at levels 60 and 80
  (hand-checked on poe2db's Ascendancy_class page, catalog `atlas.endgame_trials`). `path_to(by_stage)`,
  `verify_build(character_level)` and `export_pob(stage)` take them as they take the acts: a code for
  `stage="T16"` holds one passive tree per stage at level 80. `maps: false` lists the acts only;
  `find_stage` takes `T16`, `tier 16`, `第 16 階`.
- `resistance_penalty` in every stage's limits (from the penalty table), so "the resistance penalty after
  the acts" is no longer listed as missing.
- Tool `waystone_mods`: waystone modifiers grouped by wording with their tiers, by words in either language
  or by prefix / suffix.
- Tool `search_string` (`src/tools/search_string.py`): a string for the in-game search box, worked out from
  the data in English and Chinese. `gear`: the shortest piece of each wanted modifier that no other modifier
  of the item class (nor a base name) holds, joined with `|`. `maps`: the waystone modifiers to leave out,
  after `!`. English pieces are whole words (not a lone word such as "from" or "increased"), Chinese pieces
  are runs of Chinese characters not starting or ending with 的, 上 and the like; pieces hold no numbers, so
  one string serves every tier. `also_matches`, `left_out` and `unmatched` say what could not be placed
  cleanly. The 250-character limit and the syntax come from community guides (catalog `atlas.search`).
- Tests: `tests/atlas_support.py` (synthetic Waystones page), `tests/unit/test_collect_atlas.py` (19),
  `tests/unit/test_search_string.py` (15), `tests/integration/test_atlas_tools.py` (63).
- `docs/flow/img/update-atlas.{en,zh-TW}.svg`.
- READMEs: how to update an installed plugin in Claude Code and Codex.

### Changed
- The default build is a staged build up to Tier 16: the workflow (`build_workflow.py`, `poe2-advisor`
  skill, server instructions) plans the last map stage first, writes the resistance penalty for each
  stage, gives one search string per gear slot, and for the map stages names only the waystone modifiers
  whose lines work against the verified build and gives a string that leaves them out. A campaign-only
  build is made when asked; the ladder comparison covers the whole build at Tier 16.
- `export_pob`'s first note says "Stage …" ("階段 …") instead of "Campaign stage …", as a stage can be a
  map stage. A campaign-only build otherwise differs from 0.14.0 only by each stage's `kind` and
  `resistance_penalty` (with the atlas data) and by the penalty no longer being listed as missing.
- Search-string pieces prefer several English words (or three Chinese characters at a run's edge) over
  one word, as a lone word is more likely to match text the data does not have.

### Removed
- `CampaignLookup.stage_for_level`, which nothing called.
- `update_data`, the `update` and `status` skills and prompts list the `atlas` scope; 26 tools.
- READMEs, `docs/tools*.md` (new section on map stages and search strings), `docs/data*.md`,
  `docs/flow/` (advisor and update charts, a chart for `update atlas`, system flow), ROADMAP.
- READMEs and `docs/clients*.md`: Claude Code is installed from a terminal (`claude plugin marketplace add`,
  `claude plugin install`), the same way as Codex; the in-app `/plugin` lines are kept as a note.
- Version 0.15.0; User-Agent `POBG/0.15`.

### Fixed
- `collect_atlas.main` passes its cache folder at call time (found by a test: a default argument would
  have kept the folder chosen at import).
- Found by the independent review (`docs/reports/code_review_2026-11-17_02.md`), before release:
  a `waystone_mods` entry's `text` was refused by `search_string` (it now takes the `text`, the `id`, a
  line or words); atlas files that parse but have the wrong shape broke every campaign tool (they now
  leave the acts and say why); a modifier without Chinese lines was dropped silently from the zh-tw string
  (now in `missing`); gear pieces could cross a line break; gear pieces were checked against two
  modifier groups and base names only (now every group and the bases' implicits and property labels);
  the waystone labels were hand-written, with an invented Chinese word (now the tier names and property
  labels from the page); the area level was the first number of a tier entry (now its labelled line,
  with checks that levels rise and penalties fall); a typographic minus; non-text arguments; avoid
  entries of one or two letters; T1's area range now starts after the last act.

## [0.14.0] - 2026-11-17

Currency items (`docs/plan_currency.md`): the first step toward gear crafting. What each orb,
essence, splinter, catalyst, omen, rune and soul core does can now be looked up and cited, in both
languages. Prices and crafting steps are not part of this release.

### Added
- `currency` data and update scope (`src/scrapers/collect_currency.py`): poe2db's `Stackable_Currency`,
  `Omen` and `Augment` listing pages in English and Chinese (category from the English tab, effect lines
  by kind, stack size, minimum modifier level, maximum item level, limit, required level) and each item's
  own page (drop level, item class, tags, internal type). An update reads the six listing pages and only
  the item pages not read yet (`older_than_days` reads older ones again; 0 reads all), at most 50
  requests per call, resumed by the next call; a first update reads about 620 item pages. Nothing is
  written below the catalog's minimums (per category, Chinese names, item pages read).
- Two MCP tools: `get_currency` (one item, its sources, and `related`: the items whose effect lines
  name it as a whole name, e.g. the omens that change a Chaos Orb; an essence points to its
  `modifiers_for` group) and `currency_by` (by category in English or Chinese, words in either language,
  or `max_level` on drop and required level; with no filter, the categories). Both say what is not in
  the data (prices, drop chances, crafting steps). Currency items are in the name index (`lookup_entity`).
- `src/scrapers/item_page.py`: one reader for the facts box of a poe2db item page, used by the currency
  and campaign collectors.
- Flowchart of `update currency`; tests on a synthetic currency site (`tests/currency_support.py`).

### Fixed
- The campaign collector read an item page's drop level from table rows; poe2db now shows it as
  name/value cards, so the next `update campaign` would have found no Jeweller's Orb drop levels and
  refused to write. Both layouts are read now.
- The `update_data` description and the `update` prompt did not list the `campaign` scope;
  `lookup_entity`'s description named only gem, passive and glossary kinds.

### Changed
- Server instructions, the `poe2-advisor`, `update` and `status` skills, READMEs, `docs/tools*.md`,
  `docs/data*.md`, `docs/clients*.md` (24 tools, 21 read-only), the system and command flowcharts and
  ROADMAP describe the currency data. User-Agent `POBG/0.14`.
- Batched updates (items, glossary, currency): a page that answers 404 no longer counts toward the
  "five failures in a row: the site is down" stop, since the site did answer.

## [0.13.0] - 2026-11-14

Campaign builds (`docs/plan_campaign_build.md`): a build answer now aims, by default, at clearing the
campaign, act by act, with every limit worked out from the data; and the campaign itself can be
asked about. A finished endgame build is still made when a level above the campaign's end, or maps /
late game, is asked for.

### Added
- `campaign` data and update scope (`src/scrapers/collect_campaign.py`, about 26 requests): poe2db's
  Act pages in English and Chinese (areas with level, town, waypoint, bosses and what they grant, the
  act map, the community walkthrough of each area; quests with type, reward and objectives), PoB's
  QuestRewards.lua (permanent rewards placed in their stage), and the gem and socket rules (the skill
  gem level table, gemcutting tiers, the drop level of each Uncut Support Gem level, what each
  Jeweller's Orb sets the support sockets to and from which drop level). An Act page without areas is
  not a stage, and the Act page holding the Interlude page's areas is named Interlude, so the stages
  follow the data when 1.0 adds Acts 5 and 6. Nothing is written below the catalog's minimums.
- Four MCP tools: `campaign_stages` (each stage's limits: level, passive points, ascendancy points,
  quest Spirit, skill gem level and tiers, support gem tier, support sockets; its rewards, trials,
  bosses; and `not_in_data`), `get_area` (an area or a boss's area), `get_quest`, `campaign_by`
  (areas, quests, bosses or permanent rewards by act or words; rewards are tagged in both languages,
  e.g. "天賦點"). Areas, quests and bosses are in the name index (`lookup_entity`).
- `gems_by` and `supports_for` take `max_level`; `verify_build` takes `character_level` and returns
  `too_early` (with `from_level`), with each modifier's `best` tier the one that level can roll;
  `path_to` takes `by_stage` (targets in the order listed, cut at each stage's points);
  `export_pob` takes `stage`: level, points, gem tiers, support sockets, item and modifier levels and
  quest Spirit follow the stage, and the code holds one passive tree per stage up to it.
- Flowchart of `update campaign`; tests on a synthetic campaign site (`tests/campaign_support.py`).

### Changed
- The build workflow (server instructions, `build_workflow`, the `poe2-advisor` skill): campaign build
  by default, with the steps above; the ladder comparison for a campaign build covers the main skill
  and ascendancy only. READMEs, `docs/tools*.md`, `docs/data*.md`, flowcharts and ROADMAP describe it.
- `docs/clients*.md` and the 0.12.0 test report: the Codex plugin tested from a clean state in the
  user's Codex (an earlier check had been answered by a hand-added server). ROADMAP lists `items_by`
  not accepting attribute page names as a follow-up.
- The repo is public. The READMEs say to type the two Claude Code `/plugin` lines one at a time
  (pasted together, Claude Code reads them as one marketplace source); Claude Code and Codex on macOS
  both installed from the public repo and is recorded in `docs/clients*.md` and ROADMAP.

### Fixed
- Found while testing: `get_quest` read the quest table before loading it, so the first lookup in a
  session never matched.

## [0.12.0] - 2026-11-13

A Codex plugin next to the Claude Code one (`docs/plan_codex_plugin.md`), so both are installed
the same way and use the same commands.

### Added
- `.codex-plugin/plugin.json`, `.codex-plugin/mcp.json` and `.agents/plugins/marketplace.json`:
  `codex plugin marketplace add GGaryyy/POBG` then `codex plugin add pobg@pobg` installs the
  MCP server and the four skills in one step, as the two `/plugin` commands do in Claude Code.
  The user wanted one way of working: install the plugin, ask in plain words, use a `pobg`
  command to check or update the data. Tested by installing from a local folder into an isolated
  Codex home (Codex 0.168.0): the server starts from the plugin's folder with 18 tools and the
  skills are named `pobg:poe2-advisor`, `pobg:status`, `pobg:update`, `pobg:update-pob`, the same
  names as in Claude Code; Codex calls them with `$` (`$pobg:status`), Claude Code with `/`. The
  user then installed it in their Codex, where `$pobg:status` ran the skill and its tool.
  The server file sits in `.codex-plugin/` because a root `.mcp.json` would register a second
  server in Claude Code.

### Changed
- READMEs: Codex installs as a plugin with two commands (the manual `codex mcp add` and copying
  skill folders are gone); the Commands table gives each command for Claude Code and Codex.
- Skills name their commands for both hosts. `update-pob` no longer relies on a Claude-only path
  variable alone: in Codex it runs from the folder two levels above its `SKILL.md`.
- Local test installs come from a clean clone: Codex copies a whole folder, `.venv` and `output/`
  included, ignoring `.gitignore`.
- The ChatGPT desktop app is no longer listed as unsupported: added as a custom STDIO MCP server it
  called `lookup_entity` and `get_gem` and answered with the poe2db link, and a build request ran
  the whole workflow to a code that imported into PoB (tested by the user on 2026-11-13 with 0.11.0). `docs/clients*.md` gain the steps and the test result; only ChatGPT on
  the web remains unsupported.
- READMEs: the quick start recommends Claude Code or Codex CLI (the user's decision: these gave the
  tools and the skills, and complete builds). Claude Desktop, the ChatGPT desktop app and the other
  clients move to one paragraph that points to `docs/clients*.md`, where the Claude Desktop steps
  now also say that the server plus the uploaded plugin is the complete setup there. They state
  that both were tested in WSL: Windows users are pointed to WSL, and Codex CLI in PowerShell or
  cmd is marked as not tested.
- `docs/clients*.md`: Codex CLI tested in WSL with the skills copied to `~/.codex/skills` (complete
  build, code imports); noted that the model can mangle a long code when it retypes it to the terminal.
- ROADMAP: a "Right after going public" list (release with the zip, install from the zip, the zip as
  a plugin, the Claude Code install from GitHub, skills in the ChatGPT desktop app, recording the results).

## [0.11.0] - 2026-11-13

Installing in Claude Desktop (`docs/plan_desktop_install.md`), the `ninja` update scope, and the
documentation rewritten for players.

### Added
- `python -m src.tools.install_desktop` registers this folder's MCP server in Claude Desktop: it
  finds `claude_desktop_config.json` (Windows incl. the Microsoft Store build, macOS, Linux; or
  `--config`), writes the one entry `mcpServers.pobg` with the full paths of uv and the folder,
  and leaves every other server and setting alone. The file is backed up before any change, a
  file that is not valid JSON is refused, the write goes through a temporary file, an `env` the
  user added to the entry is kept, and nothing of the other servers is ever printed. `--check`
  writes nothing, `--remove` takes the entry out. `install_claude_desktop.bat` runs it on Windows.
  uv is written by the path the user reaches it (links are not followed, so a Homebrew or scoop
  upgrade does not break the entry); a config that changed while the tool ran, or that holds
  values that are not JSON, is refused; a linked config keeps its link and its file mode.
- READMEs: a Claude Desktop quick start (release zip or clone → install command → restart), next
  to the Claude Code plugin. `docs/data.md` says how the release zip is made.

### Changed
- The READMEs and client guides no longer suggest that uploading the plugin is enough outside
  Claude Code. Tested on 2026-11-13 with the 0.10.0 plugin uploaded to a workspace: chats in
  Claude Desktop and on claude.ai run in a cloud sandbox where the plugin's local MCP server is
  not started (skills only), while a server registered in Claude Desktop's own config works.
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
