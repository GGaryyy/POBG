# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

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
