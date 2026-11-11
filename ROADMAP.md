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
| Collectors | Gems (listing + detail, incremental updates), passive tree (PathOfBuilding-PoE2 structure + poe2db text), glossary (hover snippets), ladder snapshot (poe.ninja, no names) |
| Bilingual index | English and Traditional Chinese names for gems, every passive node, classes, ascendancies and stat families |
| Knowledge graph | Stat index ("which passives give X"), supports ↔ skills, glossary mentions |
| Tools | Fourteen MCP tools: cited lookups, `verify_build`, `path_to` (passive route and point cost), `build_workflow`, `data_status`, `update_data` |
| Commands | `status` and `update <scope>` as plugin skills and MCP prompts: see how old the data is and re-fetch one data set at a time from inside the AI client |
| Packaging | stdio MCP server started with `uv run`; Claude Code plugin with the `poe2-advisor` skill |
| Client readiness (0.7.0) | Tool annotations and titles, tool-only fallback for the workflow, portability tests, Windows launcher tested, client guide |

## Next

| Item | Why |
|---|---|
| Confirm more clients | Cursor, VS Code, Gemini CLI and Codex CLI configurations are written from their docs but not tested |
| Remote transport | ChatGPT and other hosted clients only reach remote MCP servers. Needs a decision on hosting first |
| Ladder snapshot | It dates from 2026-03-04 and an earlier league. poe.ninja changed its response format, so the fetcher reads no rows; repair the parser (then add a `ladder` update scope) or drop the snapshot |
| Glossary by command | The glossary collector needs cached gem pages and about 700 requests; make it incremental so `update` can cover it |
| New passive tree versions | `status` reports a newer version, but adopting it needs a catalog change and a release; decide whether `update passives` may move to it |
| More data | Items, uniques and ascendancy details beyond the passive tree |
| One-click install for Claude Desktop | An `.mcpb` bundle, once its support for uv projects is verified |

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
