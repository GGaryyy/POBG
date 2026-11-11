# Plan: Phase 15 — Public release as `poe2db-mcp` and client onboarding

Approved 2026-11-11. This repository was created from an earlier private project; that
project's folder and repository are not modified by this plan.

## Context

The project is now an MCP server + Claude Code plugin; the UI phase is cancelled and the
priority is that other LLM clients connect smoothly. The user will test it in their own Claude
Desktop (new session) and wants the project ready to open-source, with the README reworked.

Decisions (user answers, 2026-11-11):

| Topic | Decision |
|---|---|
| Git history | A **new repo** with fresh history. The earlier private repository keeps the old history and is never made public |
| Repo name | `GGaryyy/poe2db-mcp` |
| Local location | A new folder, fresh `git init` |
| Contents | Only the MCP / plugin path. No LangGraph, Ollama, FastAPI, FAISS indexes, retrievers, legacy tests, notebook |
| Author email | The GitHub noreply address (set in the new repo's local git config only) |
| Scope | MCP + plugin only. No Docker, no HTTP transport, no `.mcpb`, no CI, no contribution docs |
| README | `README.md` in English, `README.zh-TW.md` full Chinese version, linked to each other; `README.en.md` dropped |

Facts found while exploring:

| Fact | Consequence |
|---|---|
| There is no `Dockerfile`, `docker-compose.yaml` or `.dockerignore` in the repo; Docker appears only as a rule in `CLAUDE.md` and one line of the `project-docs` skill | Nothing to delete. In the new repo those rule lines are removed (see step 2) |
| The MCP server imports only `src.catalog`, `src.scrapers`, `src.kg`, `src.tools` | The lean copy is self-contained |
| The development machine is Windows with WSL; Windows has `uv.exe` and Claude Desktop | The Claude Desktop test can run the real Windows path, not WSL |
| A Windows `uv run` in a folder whose `.venv` was made by WSL would replace it | The Desktop entry sets `UV_PROJECT_ENVIRONMENT` to a folder outside the repo |
| `uv run` installs the dev dependency group by default | The plugin launcher and all documented commands add `--no-dev` |
| Tools carry no annotations and no titles; the workflow exists only as an MCP *prompt* | Clients that support tools only (e.g. Cursor) cannot reach the workflow; clients cannot tell read-only tools from `refresh_gem` |
| No Codex / Gemini / Cursor CLI on this machine; `npx` is available | The neutral second client for automated checks is the MCP Inspector CLI |

## Names in the new repo

| Thing | Name |
|---|---|
| GitHub repo / marketplace | `GGaryyy/poe2db-mcp` / `poe2db-mcp` |
| Plugin and MCP server name | `poe2db` (descriptions say "unofficial") |
| Skill | `/poe2db:poe2-advisor` |
| Python project | `poe2db-mcp` 0.7.0 (continues from the private 0.6.0) |
| Scraper User-Agent | `poe2db-mcp/0.7 (+https://github.com/GGaryyy/poe2db-mcp; research scraper)` |

## Steps

### 1. Create the lean folder
- `git archive HEAD` of the current repo → new folder, then remove what is out of scope:
  `src/agents/`, `src/api/`, `src/retrievers/`, `src/graph.py`, `src/state.py`,
  `src/run_build.py`, `src/build_*_index.py`, `src/build_passive_graph.py`, `indexes/`,
  `test/`, `get_data.ipynb`, `requirements.txt`, `README.en.md`, legacy tests
  (`tests/test_*.py`, `tests/agent_support.py`, agent / graph / API tests), old plans, reports
  and issues under `docs/`, the `metrics-interface` skill.
- Kept: `src/catalog`, `src/scrapers`, `src/kg`, `src/tools`, `src/fetch_poe_ninja_builds.py`,
  `data/`, `skills/`, `.claude-plugin/`, `.claude/` (agents, settings, the three other skills),
  `CLAUDE.md`, `LICENSE`, `tests/` for the kept code, `tests/fixtures/`.
- `git init -b main`, local git identity = noreply address. `.gitattributes` with
  `* text=auto eol=lf` so Windows clones get the same bytes.
- `pyproject.toml`: name / version, `[dependency-groups] dev = [pytest, pytest-cov, ruff]`;
  `uv lock`; `.venv` via `uv sync`. `.mcp.json` becomes `uv run --frozen --no-dev …` (works on
  every OS).

### 2. Rules and docs that no longer fit
- `CLAUDE.md` (new repo only): remove the Docker section and the Docker file names in "Root
  files"; describe `data/` as public game data.
- `.claude/settings.json`: drop the `Read(./data/**)` deny (the user said data should be
  readable); commit / push `ask` rules and the force-push deny stay.
- `project-docs` skill: the deployment line points to `docs/clients.md` instead of Docker.
- `ROADMAP.md` rewritten short: what exists, what is next. `docs/changelog/CHANGELOG.md` starts
  at `[0.7.0]` "first public release" (old changelog stays in the private repo).
  `docs/flow/system_flow.md` trimmed to the kept parts.

### 3. Rename (table above)
`plugin.json`, `marketplace.json`, `src/tools/mcp_server.py` (server name),
`src/scrapers/common.py` (User-Agent), `src/__init__.py`, skill text, `build_workflow.py`,
tests that assert these strings.

### 4. Make the server easier for other clients (`src/tools/mcp_server.py`)
- **Annotations and titles** on every tool: read-only + closed-world for the ten lookup /
  build tools; `refresh_gem` marked as writing and open-world. (API checked against the
  installed `mcp` 2.3 SDK before use.)
- **New tool `build_workflow(lang)`**: returns the same eight-step text as the `build_guide`
  prompt (reuses `build_guide_text` in `src/tools/build_workflow.py`), so tool-only clients
  can fetch it. Server instructions mention it in one line. Twelve tools.
- **Client-neutral wording**: server instructions and tool descriptions name no Claude-only
  feature.
- **Portability test** (`tests/unit/test_tool_portability.py`): every tool name matches
  `^[a-zA-Z0-9_-]{1,64}$`, every description is 1–1,024 characters, every input schema is a
  plain object without `$ref` / `$defs`, every tool has annotations and a title.
- **Windows**: start the server with the Windows `uv.exe` from the `D:\` path, run the stdio
  handshake and calls with Chinese arguments; fix whatever breaks (encoding, paths).
- **Response size**: measure the largest response of each tool on real data. If any exceeds
  ~80,000 characters, add a compact option to that tool; otherwise only document the sizes.

### 5. Client documentation
- `docs/clients.md`: one section per client — Claude Code (plugin), Claude Desktop (Windows /
  macOS config paths), Cursor, VS Code, Gemini CLI, Codex CLI, any stdio client; ChatGPT listed
  as not supported (needs a remote server). Each config is written from that client's current
  official docs and labelled **tested** (Claude Code, Claude Desktop, MCP Inspector) or
  **from the docs, not tested**. Ends with "check it works": five prompts and what a correct
  answer looks like.
- `README.md` (English) and `README.zh-TW.md`: what it is and example questions → install
  (plugin command, generic JSON, link to `docs/clients.md`) → tools table (twelve) → data
  sources, snapshot dates and how to refresh → development (tests) → limits → license and
  disclaimer (unofficial; not affiliated with Grinding Gear Games, poe2db.tw or poe.ninja;
  game data belongs to GGG and is not covered by MIT).

### 6. Claude Desktop test (the user, new session)
- One entry `poe2db` is added to `claude_desktop_config.json` (backup copy first, existing
  servers untouched): the Windows `uv.exe` with
  `run --frozen --no-dev --directory <repo folder> python -m src.tools.mcp_server`, and
  `UV_PROJECT_ENVIRONMENT` pointing outside the repo folder.
- The user restarts Claude Desktop and runs the five check prompts (given in Chinese in my
  report). If something fails I read `%APPDATA%\Claude\logs\mcp-server-poe2db.log` and fix it.

### 7. Before the first commit
- Counts only: zero occurrences of `character_name`, `account_name`, the gmail address, and
  common secret patterns in the whole new tree; no file over 5 MB.
- Offline suite, `ruff`, `claude plugin validate .`, plugin launcher start, MCP Inspector CLI
  (`tools/list`, `prompts/list`, three calls).
- Reports (`docs/reports/`), changelog, floorplan copied and refreshed in the new folder,
  project memory copied to the new folder's Claude Code project.

### 8. Publish — only when the user says so
First commit, `gh repo create GGaryyy/poe2db-mcp --public --source . --push`, repo description
and topics. Then a real `/plugin marketplace add GGaryyy/poe2db-mcp` install from GitHub.
Nothing is committed, pushed or created on GitHub before that instruction.

## Error handling

| Case | Behaviour |
|---|---|
| A kept test imports a removed module | The test is removed if it only tested removed code; otherwise the import is fixed. Final count reported |
| Windows start fails (encoding, path, uv) | Fixed in code where it is our bug; documented where it is a client requirement |
| `claude_desktop_config.json` is not valid JSON or changes while editing | No write; the snippet is handed to the user instead |
| The name scan finds a hit | Stop, report the count and file, no commit |
| Client docs disagree with what I remember | The official doc wins; the section is labelled "not tested" |

## Tests

| File | Key cases |
|---|---|
| `tests/unit/test_tool_portability.py` (new) | name pattern, description length, flat schema, annotations (`refresh_gem` is the only non-read-only tool), titles |
| `tests/integration/test_mcp_server.py` (extend) | twelve tools; `build_workflow` returns the same text as the prompt in `en` and `zh-TW`; bad `lang` → ToolError; server name `poe2db` |
| `tests/unit/test_plugin_manifest.py` (update) | new names, repo URL, `--no-dev` in the launcher, README / skill tool lists equal the server's |
| existing unit + integration tests of the kept modules | pass unchanged apart from renamed strings |

End-to-end: plugin launcher on Linux; Windows `uv.exe` stdio session with Chinese input; MCP
Inspector CLI; the user's Claude Desktop session; after publishing, install from GitHub.

## Acceptance criteria

1. The new folder holds no legacy pipeline code, no FAISS indexes, no ladder names, no gmail
   address; the old folder is byte-for-byte unchanged.
2. Offline suite passes in the new folder; coverage of `src/tools` ≥ 90 %.
3. The server starts from Windows `uv.exe` and from Linux, lists twelve tools with
   annotations, and answers Chinese and English queries.
4. `docs/clients.md` covers the listed clients with honest tested / untested labels.
5. `README.md` and `README.zh-TW.md` describe only what the new repo contains.
6. The user's Claude Desktop shows the `poe2db` server and answers the five check prompts
   with poe2db source links.
7. No commit, push or GitHub repo creation until the user asks.

## Out of scope

HTTP / remote transport and ChatGPT support, Docker, `.mcpb` bundle, CI, CONTRIBUTING / issue
templates, PyPI publishing, new game data, changes to the earlier private repository.

## Result (2026-11-11)

| Criterion | Result |
|---|---|
| Lean folder | Only catalog, scrapers, kg, tools, plugin, skill, data and their tests were exported; nothing was deleted from the earlier project |
| Tests | See `docs/reports/test_report_2026-11-11.md` |
| Windows | A scripted MCP session through Windows `uv.exe` (Python 3.12, code page 950) ran all twelve tools with Chinese input; no code change was needed |
| Second client | MCP Inspector CLI: `tools/list`, `prompts/list` and three `tools/call` requests |
| Response sizes | Measured; listed in `docs/clients.md` |

Deviations from the plan:

- Out-of-scope files were left out of the export instead of being deleted afterwards.
- Response sizes: `passives_with_stat` passed 140,000 characters at `limit` 200, so its limit
  is capped at 100 (72,700). `verify_build` reaches 89,800 characters only with 40 gems and 40
  passives, about 1,000 per name with nothing redundant to cut, so no compact option was added.
- `tests/conftest.py` only held fixtures of the removed pipeline and was not exported.
- The plan named "bad `lang` → ToolError" for `build_workflow`; the `build_guide` prompt keeps
  its earlier behaviour of falling back to English.
