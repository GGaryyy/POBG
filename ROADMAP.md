# Roadmap

## Goal

> Let an AI quickly find accurate Path of Exile 2 data, cite the source, and explain it.

The product is a local MCP server and a Claude Code plugin. The user's own AI client is the
interface; there is no web UI and no hosted service. The priority is that any MCP-capable
client connects without friction.

## Done

| Area | What exists |
|---|---|
| Source catalog | `src/catalog/poe2db_sources.json` describes every page, selector and field; `probe.py` detects drift before a crawl |
| Collectors | Gems (listing + detail, incremental updates), passive tree (PathOfBuilding-PoE2 structure + poe2db text), glossary (hover snippets), ladder snapshot (poe.ninja, no names), gear, flasks, charms and jewels (0.8.0: 1,762 bases, 434 uniques, 17,719 modifiers from 69 item class pages) |
| Bilingual index | English and Traditional Chinese names for gems, every passive node, classes, ascendancies and stat families |
| Knowledge graph | Stat index ("which passives give X"), supports ↔ skills, glossary mentions |
| Tools | Eighteen MCP tools: cited lookups, gear (`get_item`, `items_by`, `modifiers_for`), `verify_build` (gems, passives, items, target modifiers), `path_to` (passive route and point cost), `export_pob` (Path of Building code, 0.9.0), `build_workflow`, `data_status`, `update_data` |
| Commands | `status` and `update <scope>` as plugin skills and MCP prompts: see how old the data is and re-fetch one data set at a time (three gem kinds, passives, items, glossary, ninja) from inside the AI client. `update-pob <folder>` (0.9.0) updates the user's Path of Building, alone or in PoeCharm2, into a new folder |
| Packaging | stdio MCP server started with `uv run`; Claude Code plugin with the `poe2-advisor` skill |
| Client readiness (0.7.0) | Tool annotations and titles, tool-only fallback for the workflow, portability tests, Windows launcher tested, client guide |

## Right after going public (listed 2026-11-13)

The repo is private until the user makes it public. The READMEs recommend Claude Code or Codex (the user's
decision on 2026-11-13); other AI apps are tested later, when someone uses them. These tasks wait for the
repo to be public and come first, in this order. Creating a release is done only on the user's word.

| # | Task | Why it waits | Done when |
|---|---|---|---|
| 1 | Install in Claude Code from GitHub: `/plugin marketplace add GGaryyy/POBG`, `/plugin install pobg@pobg` | Never run: the repo was private. Only loading from a local folder was tested | The server connects and a lookup cites poe2db; if the short form fails, use the full git URL in the READMEs |
| 2 | Install in Codex from GitHub without access to the repo: `codex plugin marketplace add GGaryyy/POBG`, `codex plugin add pobg@pobg` | Works with the owner's GitHub access (tested 2026-11-13 while private); a user without access needs the repo public | The server connects, `$pobg:status` works and a build ends with a code that imports into PoB |
| 3 | Record the results of 1 and 2 in `docs/clients.md` and `docs/clients.zh-TW.md` ("What was tested") | The table still says "to be confirmed after the first public release" | Each row has a date and a result |
| 4 | Friends follow the README alone, in Claude Code or Codex | The steps were only followed by the people who wrote them | Notes on where a newcomer got stuck feed back into the README |

Later, when someone needs them (not blocking):

| Task | State |
|---|---|
| A `v0.11.0` release with `pobg-0.11.0.zip` for Claude Desktop (command in `docs/data.md`, "Releasing") | The installer is done and tested on a clone; never installed from a zip. `docs/clients.md` links to the release page, which does not exist yet |
| The release zip uploaded as a plugin in Claude Desktop | The zip has a top-level `POBG` folder; the upload tested on 2026-11-13 had the files at the top |
| The ChatGPT desktop app with the Codex plugin (it shares `~/.codex` with Codex) | Tools tested without the plugin; the build was thin |
| Show the length of a build code, so a code the model retyped wrongly is noticed | Seen in Codex CLI on 2026-11-13; the user chose to leave it: each AI hands the code over in its own way |
| Cursor, VS Code, Gemini CLI | Not tested |
| `items_by` accepts an attribute page name (`Body_Armours_str_dex`) like `modifiers_for` does | Seen 2026-11-13: a Codex build made 8 failed `items_by` calls with such names before finding the class |

Open from the same day: the Microsoft Store build's config location is matched by a pattern that was not
verified on such a machine; `status` and `update` were not tried in the ChatGPT desktop app or Codex; the
project-docs rule says diagrams are Mermaid, while the command flowcharts are now generated SVG.

## Next (in this order, decided 2026-11-11)

The data covers gems, the passive tree, the glossary and (0.8.0) gear, flask, charm and jewel
bases, uniques and modifiers. Phase 1 is done; Path of Building export part 1 (class, ascendancy,
passive tree, skill gems) is in 0.9.0 and part 2 (gear) in 0.10.0. Next are the unique items that
make a build, jewels in the passive tree and build-enabling uniques (added 2026-11-13), then gear crafting.

| # | Phase | What | Why |
|---|---|---|---|
| 1 | Gear and modifier data (done in 0.8.0) | Equipment bases, modifiers and tiers (incl. desecrated, essence, corrupted, socketable effects), unique items, jewels, flasks and charms | Gear and its modifiers decide damage and defences; it changes every league |
| 1 | Gem and ascendancy gaps (checked in 0.8.0) | Lineage supports were already covered (77 of 77); socketables came with the modifiers; ascendancy pages add nothing the tree data lacks; 13 gems on the meta gem page are on no gem listing and were left out | Completes what a build can name |
| 2 | Export to Path of Building, part 1 (done in 0.9.0) | `export_pob`: class, ascendancy, passive route from `path_to` and skill groups as a Path of Building code; `update-pob` keeps the user's PoB current | The advice can be opened, checked and continued in PoB. The passive node ids are already PoB's |
| 2 | Export to Path of Building, part 2: gear (done in 0.10.0) | Bases, uniques and target modifiers as PoB items, each modifier at the upper end of its best tier (a stated ideal) | PoB's damage and defence figures need gear |
| 3 | Unique items that make a build (added 2026-11-13; scope still open) | Two cases named by the user: (a) unique jewels socketed in the passive tree, which many builds add late in the game; (b) builds that only start working once a certain slot holds a certain unique. What exactly to cover is hard to pin down and is decided when the phase starts | Today a unique can be named for a slot and is checked and exported, but the workflow does not look for a unique that enables the build, and jewels are left out altogether: `path_to` does not plan jewel sockets and `export_pob` does not export jewels |
| 4 | Gear crafting | How to make the target gear: crafting methods, currency, essences, catalysts, omens, liquid emotions, and which of them give the modifiers a build names | How to obtain the gear, after the gear itself is known. Build answers name target modifiers but not how to get them |

Also open:

| Item | Why |
|---|---|
| Patch notes as an update signal | poe2db's version pages list the gems and uniques each patch changed; a plain `update` cannot see number-only changes |
| Confirm more clients | Cursor, VS Code, Gemini CLI and Codex CLI configurations are written from their docs but not tested |
| Remote transport | ChatGPT on the web, claude.ai on the web and chats in Claude Desktop that only have the uploaded plugin reach remote MCP servers only (a plugin's local server is not started in their cloud sandbox, tested 2026-11-13). Needs a decision on hosting first; the user chose to stay local for now |
| Ladder depth | The snapshot is about 600 characters from the top of several rankings; poe.ninja's layout is undocumented and has changed once already, so the fetcher needs watching |
| New passive tree versions | `status` reports a newer version, but adopting it needs a catalog change and a release; the 1.0 release will add classes, weapons and acts |
| One-click install for Claude Desktop | 0.11.0 has an install command (`install_desktop`, a `.bat` on Windows) that registers the local server from a release zip or a clone. An `.mcpb` bundle would remove the uv and unzip steps, once its support for uv projects is verified |
| Choose gear values | Let the user pick a modifier tier or value for exported gear instead of the best tier's upper end (kept for later, 2026-11-12) |
| Save a build into PoB's folder | An opt-in command that writes the build into a PoB `Builds` folder the user names, so it appears in PoB's build list without pasting. Not done in 0.9.0: some users do not want files written (decided 2026-11-12) |
| Open PoB from a link | `pob2://` links open a build in PoB, but only from an upload to a build site (pobb.in, poe2db), which makes the build public |

Out of scope for the data: endgame mechanics, monsters, quests, lore and cosmetics.

## Not planned

A web UI, a hosted public instance, and the earlier local LangGraph / Ollama pipeline.

## Key decisions

| Decision | Choice | Reason |
|---|---|---|
| Source of truth | poe2db.tw pages described by a versioned catalog | Provenance per field; drift is detectable |
| Entity resolution | Exact alias index, no fuzzy matching | Deterministic, explainable, bilingual |
| Build advice | The model searches freely; only names verified by exact match may appear; the source list is rendered by code | Stops invented gems and passives |
| Passive routes | Steiner-tree approximation, stated as approximate | Exact answers are not computable at tree size |
| Scraping etiquette | 0.8 s before each page (from the catalog), identifying User-Agent, at most three attempts | Be a polite, identifiable client |
| Privacy | Ladder character and account names are never written or returned | Only build shape matters |
