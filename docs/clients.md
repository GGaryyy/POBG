# Connecting an MCP client

**English** | [繁體中文](clients.zh-TW.md)

POBG is a local **stdio** MCP server. Every client starts it with the same command:

```
uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server
```

- `uv` 0.13.4 or newer must be installed ([instructions](https://docs.astral.sh/uv/getting-started/installation/);
  `uv self update` upgrades it) and found by the client. If the client reports "command not found", put the full path of
  `uv` in `command` (`which uv` on macOS / Linux, `where uv` on Windows).
- The path after `--directory` is where you cloned this repo. On Windows write it with
  doubled backslashes inside JSON: `"C:\\Users\\you\\POBG"`.
- The first start downloads about 40 packages (four direct dependencies) and takes longer
  (seconds on a fast connection, a few minutes on a slow one). If the client gives up, run the command once in a
  terminal, stop it with Ctrl+C when it sits waiting, and restart the client.
- The server never prints to stdout except MCP messages; logs go to stderr.
- The first tool call of each session takes about a second: the data is loaded and the
  knowledge graph is rebuilt in memory (it is not stored in the repo).

## What was tested

| Client | Status (2026-11-11 with 0.7.0, unless a later date is given) |
|---|---|
| Claude Code — plugin | Tested on Linux (WSL): loaded from a local folder with `--plugin-dir`, exactly one `pobg` server, connected; `claude plugin validate --strict` passes. Install from GitHub to be confirmed after the first public release |
| Claude Desktop (Windows) | **Tested in the app on 2026-11-13 (0.10.0)**: with the `pobg` server registered in `claude_desktop_config.json`, chats call the tools (`data_status` answered from the local data folder). The installer (`install_desktop`, 0.11.0) was run against a copy of a real config and in check mode against the real one. Before that: a scripted MCP session through Windows `uv.exe` and Python 3.12 (system code page 950) with Chinese input |
| Plugin uploaded in Claude Desktop or claude.ai (Customize → Plugins) | **Does not give the tools** (tested 2026-11-13, 0.10.0): the plugin's files and skills sync into a cloud sandbox, but its local MCP server is not started there, and the sandbox cannot reach poe2db. Use the Claude Desktop install above |
| MCP Inspector CLI (`npx @modelcontextprotocol/inspector --cli`) | Tested with the twelve lookup and build tools: `tools/list`, `prompts/list`, `tools/call` |
| Cursor, VS Code, Gemini CLI, Codex CLI | Not tested. The configuration below follows each client's documentation as read on 2026-11-11 |
| ChatGPT desktop app (Windows) | **Tested in the app on 2026-11-13 (0.11.0)**: added under Settings → MCPs as a custom STDIO server; "躍擊 10 等的消耗是多少？" called `lookup_entity` and `get_gem` and answered with the cost and the poe2db link. A build request ("Lv90 傭兵 Tactician 擲彈流") ran the whole workflow: verified gems, passives and gear, `path_to`, the source list and an `export_pob` code that imported into PoB 0.23.1. The build itself was thin (43 of 123 points, no ascendancy points, several slots as bare bases, no Configuration option), which is the model's choice of what to ask the tools for, not a tool failure. `status` and `update` were not tried |
| ChatGPT on the web | Not supported: it connects only to remote MCP servers over HTTPS |

Reports from other clients are welcome — open an issue with the client name and version.

## Claude Code

Plugin (server + `/pobg:poe2-advisor` skill):

```
/plugin marketplace add GGaryyy/POBG
/plugin install pobg@pobg
```

The plugin keeps its Python environment in the plugin's own data folder. Working inside a
clone of this repo instead, load the plugin from the folder: `claude --plugin-dir .` (the repo
has no project `.mcp.json`, so the server is never registered twice).

## Claude Desktop

Get the project (the zip from the [latest release](https://github.com/GGaryyy/POBG/releases/latest), or a clone)
into a folder that stays, then register it from that folder:

```
uv run --frozen --no-dev python -m src.tools.install_desktop            # add or update the pobg server
uv run --frozen --no-dev python -m src.tools.install_desktop --check    # say what would change, write nothing
uv run --frozen --no-dev python -m src.tools.install_desktop --remove   # take it out again
```

Quit Claude Desktop completely first (also from the system tray): while it runs it rewrites its config and
could undo the change. On Windows `install_claude_desktop.bat` in the folder runs the first command (options
are passed on). Then start Claude Desktop again.

What the installer does:

- Finds `claude_desktop_config.json` (`%APPDATA%\Claude` on Windows, also the Microsoft Store build's folder;
  `~/Library/Application Support/Claude` on macOS; `~/.config/Claude` on Linux). Pass `--config <file>` when
  it is somewhere else.
- Writes one entry, `mcpServers.pobg`, with the full path of `uv` and of this folder. Other servers and
  settings are left alone and never printed. An `env` you added to the `pobg` entry is kept.
- Copies the file to `claude_desktop_config.json.pobg-backup-<time>` before any change. A file that is not
  valid JSON, or that changed while the installer was working, is refused and left as it is. When the config
  is found in two places (a leftover folder next to the Store build), it asks for `--config`.

A plugin uploaded in Claude Desktop or on claude.ai (Customize → Plugins) brings the skills only: those chats
run in a cloud sandbox, which does not start a plugin's local MCP server (tested 2026-11-13).

By hand instead: Settings → Developer → **Edit Config** opens `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Add the server next to any existing ones, then quit Claude Desktop completely and start it again:

```json
{
  "mcpServers": {
    "pobg": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "C:\\Users\\you\\POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

If Claude Desktop does not find `uv`, write its full path in `command` (the installer does this for you).

The server's stderr is written to `mcp-server-pobg.log` in `%APPDATA%\Claude\logs`
(Windows), `~/Library/Logs/Claude` (macOS) or `~/.config/Claude/logs` (Linux).

If the same folder is also used from WSL or another operating system, keep the environments
apart by adding `"env": { "UV_PROJECT_ENVIRONMENT": "C:\\Users\\you\\AppData\\Local\\pobg\\venv" }`.

## Cursor

`~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "pobg": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

## VS Code (GitHub Copilot)

`.vscode/mcp.json` in a workspace, or the user-profile `mcp.json`. Note the top-level key is
`servers`, not `mcpServers`:

```json
{
  "servers": {
    "pobg": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

## Gemini CLI

`~/.gemini/settings.json` (user) or `.gemini/settings.json` (project) takes the generic
`mcpServers` JSON shown under Claude Desktop. Or from a terminal:

```bash
gemini mcp add -s user pobg uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server
```

## ChatGPT desktop app

Settings → search "MCP" → **MCPs** → connect to a custom MCP, type **STDIO**:

| Field | Value |
|---|---|
| Name | `pobg` |
| Command to launch | the full path of uv, e.g. `C:\Users\you\.local\bin\uv.exe` (`where uv` shows it) |
| Arguments | one per row: `run`, `--frozen`, `--no-dev`, `--directory`, the POBG folder (e.g. `C:\POBG`), `python`, `-m`, `src.tools.mcp_server` |
| Environment variables | none; `UV_PROJECT_ENVIRONMENT` only when the folder is shared with WSL (see Claude Desktop above) |

Paths go in as they are, without quotes or doubled backslashes. Save, start a new chat and ask a question.
The app keeps this in the same `~/.codex/config.toml` the Codex CLI uses (next section), so either way
of adding it serves both.

## Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.pobg]
command = "uv"
args = ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG", "python", "-m", "src.tools.mcp_server"]
```

Or: `codex mcp add pobg -- uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server`

## Any other stdio client

Use the command at the top. Without uv, any Python 3.10+ that has `mcp>=2.3,<3`, `networkx`,
`requests` and `beautifulsoup4` works (the tests need 3.10+ too): start `python -m src.tools.mcp_server` with the repo
folder as the working directory.

## What the server offers a client

| Feature | Detail |
|---|---|
| Tools | Eighteen. Names use only letters, digits and `_`; descriptions are under 1,024 characters; input schemas are flat objects (strings, integers, booleans, string lists) |
| Annotations | Fifteen tools are `readOnlyHint: true`, `openWorldHint: false`. `data_status` is read-only but `openWorldHint: true` (its optional online check). `refresh_gem` and `update_data` are `readOnlyHint: false`, `destructiveHint: true`, `openWorldHint: true`: they fetch from the sources and replace local records, so clients should ask before running them |
| Prompts | `build_guide(request, lang)`, `status()`, `update(scope, names)`. Clients without prompt support call the `build_workflow` tool for the build steps, and can call `data_status` / `update_data` directly |
| Server instructions | A short "how to use these tools" text sent at initialisation; some clients ignore it, which is why `build_workflow` exists |
| Languages | Queries and answers in English and Traditional Chinese; `lang` is `en` or `zh-tw` |

Largest responses measured on the bundled data (characters of JSON):

| Tool | Typical | Largest |
|---|---|---|
| `get_gem` | 3,600 (median) | 28,100 |
| `get_passive`, `explain_keyword` | 1,300 – 2,500 | 7,500 |
| `passives_with_stat` | 20,000 (default `limit` 50) | 72,700 (`limit` 100 with `include_without_page`) |
| `gems_by`, `supports_for` | 11,000 – 12,500 (default `limit` 50) | 45,700 (`limit` 200) |
| `reference_builds` | 2,900 (default `limit` 5) | 14,700 (`limit` 50) |
| `get_item` | 1,000 (median) | 1,500 |
| `items_by` | 7,700 (one class); 12,000 with `with_lines` (25 charms) | 26,800 (`limit` 100) |
| `modifiers_for` | 25,600 (default `limit` 20 families) | 37,200 (`limit` 100) |
| `verify_build` | about 600 per gem, 340 per passive, 320 per modifier (`detail` "brief": about 150 each) | a full build with gear (18 gems, 22 passives, 9 items, 54 modifiers): 46,000, or 22,000 with `detail` "brief" |
| `path_to` | 11,000 (three keystones) | 72,900 (40 targets) |
| `data_status`, `update_data` | 2,700 / under 1,000 | a few thousand |

Durations measured on 2026-11-11: `data_status` 0.4 s locally and 39 s with the online check (19
requests); `update_data` dry run 2–3 s; three named gems 10 s (4 requests); `passives` 17 s (7
requests). A gem update of 20 pages takes roughly a minute, so clients with a short tool
timeout should pass a smaller `max_gems`. `requests` counts pages; a page that answers with a
server error is tried up to three times.

Clients that cap tool output (Claude Code warns above roughly 10,000 tokens) are fine with the
defaults; raise `limit` only when needed.

## Check that it works

Ask these in a new conversation (six checks). The right-hand column is what a correct answer looks like.

| Ask | Expect |
|---|---|
| "What does Leap Slam cost and what are its tags?" (or 「躍擊的消耗和標籤是什麼？」) | The assistant calls `lookup_entity` and `get_gem`; the answer quotes the cost and tags and links `https://poe2db.tw/us/Leap_Slam` (or `/tw/`) |
| 「哪些天賦有攻擊速度？」 | `passives_with_stat`; a list of notables with poe2db links, and a count of small nodes |
| "Explain Critical Hits" | `explain_keyword`; the glossary text with its poe2db link |
| "How many passive points does a Witch need for Blood Magic and Resolute Technique?" | `path_to`; a point total against the 123 limit, described as approximate, and the route |
| The `status` command (or "how old is the poe2db data?") | `data_status`; a table of data sets with record counts, fetch dates and ages; the ladder snapshot flagged as old |
| "Give me a fire Titan build, in Traditional Chinese" | `verify_build` is called (often after `gems_by` / `supports_for`), then `path_to`; the answer ends with a 來源 / Sources list of poe2db links, and any invented name is listed as removed |

If the assistant answers without calling a tool, the server is not connected: check the
client's MCP / connector list and the log file.
