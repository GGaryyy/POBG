# Test Report — 2026-11-13 (0.11.0, Claude Desktop installer)

Scope: `src/tools/install_desktop.py`, `install_claude_desktop.bat`, the `ladder` → `ninja` scope rename,
version 0.11.0. Tier: new feature — unit, integration, end-to-end. Plan: `docs/plan_desktop_install.md`.

## Execution summary

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| **Total (`uv run pytest`)** | **1,677** | 0 | 0 |
| of which `tests/unit/test_install_desktop.py` (new) | 43 | 0 | 0 |

1,634 before this work. All tests are offline; the installer's tests edit configs in temporary folders
only. `uv run ruff check .`: no findings.

## Coverage (line + branch)

| Module | Cover |
|---|---|
| `src/tools/install_desktop.py` | 99 % (182 statements, 1 missed; 64 branches, 2 partial) |
| **Total** | **96 %** (6,215 statements, 2,204 branches) |

coverage.py does not report function coverage.

## What the new tests check

| Area | Cases |
|---|---|
| Install | A new config holds only `pobg`; other servers, other settings and key order kept; the old file backed up byte for byte; a second run is `unchanged` with no backup; a different `pobg` entry replaced and reported without its `env`; an `env` the user added is kept in place and is not a change; a `pobg` that is not an object; `mcpServers: null` |
| `--check`, `--remove` | Nothing written; only `pobg` removed; nothing registered; no secret in either output |
| Refusals (file byte-identical, no backup, no temporary file) | Truncated JSON, an array, a string, `mcpServers` as a list, `Infinity`, `NaN`, a 5,000-digit number, 100,000 nested brackets, a lone surrogate; no Claude folder; no uv; a write failure; a config changed while the tool ran |
| uv | From `UV`, from PATH, the stable link kept instead of the versioned file behind it, the plain spelling when Windows finds `uv.EXE`, no fall-back to the real PATH |
| Config location | `--config` as file, folder, relative path, missing folder; macOS, Linux, `XDG_CONFIG_HOME`, Windows with the Store build; the place that holds a file wins; two configs ask for `--config` |
| Files | A linked config keeps its link, the target is updated and keeps mode 0640; two changes in one second get two backups; paths with spaces and backslashes survive the JSON; a byte order mark and an empty file are read |

## End-to-end runs on the user's Windows machine

| Run | Result |
|---|---|
| `install_claude_desktop.bat --check` through `cmd.exe`, against the real Claude Desktop config | Found `%APPDATA%\Claude\claude_desktop_config.json` and `uv.exe`; reported `unchanged` (the existing entry differs only by the user's `env`); the file's SHA-256 was the same before and after |
| Real install on a copy of that config whose `pobg` entry was made outdated | `updated`; the two other servers and the other settings identical to the real file; the `env` kept; one backup written |
| The command the installer writes, started with Windows `uv.exe` | Server 0.11.0, 18 tools, every call ok |
| `claude plugin validate --strict` on the files that would be committed | Passed |

Not done here: writing the real Claude Desktop config and asking a question in the app (the user's step),
and an install from a release zip in a clean folder (there is no release yet).

## Failures fixed during the run

| Failure | Fix |
|---|---|
| The real config's entry has an `env`; the first version saw it as different and would have dropped it | The tool owns `command` and `args` only; other keys stay |
| On Windows `shutil.which` returns `uv.EXE`, so an identical entry was reported as an update | The spelling `uv run` gave is kept when it is the same path |
| Review findings (see `code_review_2026-11-13.md`) | Fixed with tests |
