# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-11-11

First public release, as `poe2db-mcp`. Earlier versions were developed privately under another
name; this repository starts from that work with a new history.

### Added
- Data commands (`docs/plan_data_commands.md`): `status` and `update <scope>`, as Claude Code
  plugin skills (`/poe2db:status`, `/poe2db:update`, the latter user-invoked only) and as MCP
  prompts for every other client.
- MCP tool `data_status(check_online)`: record counts, fetch dates and ages per data set,
  passive tree versions, ladder snapshot date and league; optionally the catalog probe.
- MCP tool `update_data(scope, names, older_than_days, max_gems, dry_run)`: re-fetches one data
  set (`skill_gems`, `spirit_gems`, `support_gems`, `passives`). A scope is required, gem
  scopes fetch at most `max_gems` pages per call and report what is left, a dry run writes
  nothing, and the server reloads its data afterwards (`src/tools/maintenance.py`).
- `collect_kind(max_targets, dry_run, skip_recent_seconds)`: capped and dry incremental gem
  runs; gems left for later (or whose page failed) keep their previous listing row; a gem
  fetched recently is not selected again by name or age; summaries gain `targets_total`,
  `targets_left`, `reasons`, `recently_fetched`.
- A lock file (`data/.update.lock`) so that `update_data` and `refresh_gem` from two processes
  never write the same data folder at once; a lock older than 15 minutes is taken over.
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
- Names: repository and Python project `poe2db-mcp`, plugin and MCP server `poe2db`
  (skill `/poe2db:poe2-advisor`), scraper User-Agent
  `poe2db-mcp/0.7 (+https://github.com/GGaryyy/poe2db-mcp; research scraper)`.
- Launchers use `uv run --frozen --no-dev` (plugin manifest, `.mcp.json`, documentation), so
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
- Data files are written with LF line endings on every platform (an update run on Windows
  wrote CRLF).
- The poe.ninja ladder fetcher identifies itself with the project User-Agent instead of a
  browser string, drops the `Referer` and waits 0.8 s before each request.

### Fixed
- The ladder fetcher printed one raw record, including its character and account name, in its
  summary; it now prints the stored form without names.
- Over-long `lang` and `kind` arguments are refused instead of being echoed in the error.
- The ladder fetcher's output path no longer depends on the working directory.
- The test suite also collects on Python 3.10 (`tomli` fallback).

### Known issues
- poe.ninja changed its response format: the ladder fetcher receives data but reads no rows,
  so the ladder snapshot (2026-03-04, an earlier league) cannot be refreshed and has no
  update scope.

### Removed
- The local LangGraph / Ollama pipeline, the FastAPI service, the FAISS indexes and
  retrievers, their tests, the legacy notebook and `requirements.txt`. The project is the MCP
  server and the plugin.
- Docker is no longer part of the project rules; there were no Docker files.
