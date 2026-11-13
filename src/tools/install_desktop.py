"""
install_desktop.py — Register this folder's MCP server in Claude Desktop.

    python -m src.tools.install_desktop            # add or update the "pobg" server
    python -m src.tools.install_desktop --check    # say what would change, write nothing
    python -m src.tools.install_desktop --remove   # take the "pobg" server out again
    ... --config <file>                            # when Claude Desktop's config is somewhere else

Claude Desktop starts local MCP servers listed under "mcpServers" in claude_desktop_config.json.
This writes one entry there, "pobg", that starts the server from the folder this file is in with
the full path of uv (Claude Desktop does not always find uv on PATH). Nothing else in the file is
changed: other servers and settings stay as they are, and their content is never printed, since
it can hold keys. An "env" the user added to the "pobg" entry (for example UV_PROJECT_ENVIRONMENT,
when the folder is shared with WSL) is kept: this tool owns the command and its arguments only.

Quit Claude Desktop before running this: the app rewrites its config while it runs and could
undo the change. Before any change the file is copied to "<name>.pobg-backup-<time>". A file that
is not valid JSON is left alone, and so is one that changed while this tool was working. The new
content is written to a temporary file first and then moved into place. The result is printed as
JSON on stdout. No network, and data/ is not touched.

This is a command-line tool, not an MCP tool: it edits a file of another application, so it
runs only when the user starts it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent.parent
SERVER_NAME = "pobg"
SERVERS_KEY = "mcpServers"
CONFIG_NAME = "claude_desktop_config.json"
APP_FOLDER = "Claude"
STORE_PACKAGES = "Packages"                    # Windows: the Microsoft Store build keeps its files here
STORE_PATTERN = "*Claude*"
STORE_SUBFOLDER = Path("LocalCache") / "Roaming" / APP_FOLDER
SERVER_MODULE = "src.tools.mcp_server"
UV_ENV = "UV"                                  # set by `uv run` to the uv that started this program
UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
OWNED_KEYS = ("command", "args")                # what this tool writes in the entry; the rest is the user's
BACKUP_MARK = ".pobg-backup-"
RESTART = ("Start Claude Desktop again. If it was running during this, quit it completely first (also from the "
           "system tray) and check with --check that the entry is still there.")
SEVERAL = ("Claude Desktop's config was found in more than one place ({found}). Pass --config with the one "
           "your Claude Desktop uses.")
NOT_FOUND = ("Claude Desktop's folder was not found ({tried}). Install and start Claude Desktop once, "
             "or pass --config with the path of claude_desktop_config.json.")


class InstallError(Exception):
    """A step failed; the message says what, and the config file is unchanged."""


def config_candidates(platform: str, env: dict[str, str], home: Path) -> list[Path]:
    """Where Claude Desktop keeps its config on this system, most likely first."""
    if platform.startswith("win"):
        found = []
        if env.get("APPDATA"):
            found.append(Path(env["APPDATA"]) / APP_FOLDER)
        if env.get("LOCALAPPDATA"):
            packages = Path(env["LOCALAPPDATA"]) / STORE_PACKAGES
            if packages.is_dir():
                found += sorted(folder / STORE_SUBFOLDER for folder in packages.glob(STORE_PATTERN))
        return [folder / CONFIG_NAME for folder in found]
    if platform == "darwin":
        return [home / "Library" / "Application Support" / APP_FOLDER / CONFIG_NAME]
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return [base / APP_FOLDER / CONFIG_NAME]


def find_config(given: str | None, platform: str, env: dict[str, str], home: Path) -> Path:
    if given:
        config = Path(given).expanduser().absolute()
        if config.is_dir():
            config = config / CONFIG_NAME
        if not config.parent.is_dir():
            raise InstallError(f"the folder of {config} does not exist")
        return config
    candidates = config_candidates(platform, env, home)
    existing = [config for config in candidates if config.is_file()]
    if len(existing) > 1:                                # e.g. a leftover folder next to the Store build
        raise InstallError(SEVERAL.format(found=", ".join(str(c) for c in existing)))
    if existing:
        return existing[0]
    for config in candidates:
        if config.parent.is_dir():
            return config
    tried = ", ".join(str(c.parent) for c in candidates) or "no known location on this system"
    raise InstallError(NOT_FOUND.format(tried=tried))


def find_uv(env: dict[str, str]) -> str:
    """The full path of uv, as the user reaches it. Links are not followed: package managers point a
    stable path (Homebrew's bin, scoop's "current") at a versioned folder that an upgrade removes."""
    named = env.get(UV_ENV)
    on_path = shutil.which("uv", path=env.get("PATH", ""))
    if named and Path(named).is_file():
        named, linked = str(Path(named).absolute()), str(Path(on_path).absolute()) if on_path else None
        same_spelling = linked is not None and os.path.normcase(linked) == os.path.normcase(named)
        if linked and not same_spelling and os.path.samefile(linked, named):
            return linked                                # the same uv, by its stable name
        return named                                     # Windows finds "uv.EXE" on PATH: keep the plain spelling
    if on_path:
        return str(Path(on_path).absolute())
    raise InstallError(f"uv was not found. Install it first ({UV_INSTALL_URL}), then run this again.")


def server_entry(uv: str, root: Path) -> dict:
    return {"command": uv,
            "args": ["run", "--frozen", "--no-dev", "--directory", str(root), "python", "-m", SERVER_MODULE]}


def read_config(config: Path) -> dict:
    """The config as a dict; {} when there is no file yet. Anything else than a JSON object is refused."""
    if not config.exists():
        return {}
    try:
        text = config.read_text(encoding="utf-8-sig")
        doc = json.loads(text, parse_constant=_not_json) if text.strip() else {}
    except (ValueError, RecursionError) as exc:          # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise InstallError(f"{config} is not valid JSON ({type(exc).__name__}); it was left unchanged. "
                           "Fix or remove it, then run this again.") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get(SERVERS_KEY) or {}, dict):
        raise InstallError(f"{config} does not have the expected shape (an object with an optional "
                           f'"{SERVERS_KEY}" object); it was left unchanged.')
    return doc


def _not_json(name: str) -> None:
    """NaN and Infinity are not JSON: written back, Claude Desktop could not read the file."""
    raise ValueError(f"{name} is not a JSON value")


def backup(config: Path, stamp: str) -> Path | None:
    """A copy of the config next to it; None when there is no file to copy."""
    if not config.exists():
        return None
    target = config.with_name(f"{config.name}{BACKUP_MARK}{stamp}")
    count = 1
    while target.exists():
        count += 1
        target = config.with_name(f"{config.name}{BACKUP_MARK}{stamp}-{count}")
    shutil.copy2(config, target)
    return target


def state(config: Path) -> tuple[int, int] | None:
    """Size and modification time, to notice a file that another program changed meanwhile."""
    if not config.exists():
        return None
    info = config.stat()
    return info.st_size, info.st_mtime_ns


def save(config: Path, doc: dict, seen: tuple[int, int] | None, stamp: str) -> Path | None:
    """Write the config through a temporary file and return the backup of the old one. The file a
    link points at is the one replaced; its mode is kept. Nothing is left behind on a failure."""
    try:
        text = json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        data = text.encode("utf-8")
    except ValueError as exc:
        raise InstallError(f"{config} holds a value that cannot be written back ({type(exc).__name__}); "
                           "it was left unchanged.") from exc
    target = config.resolve()
    handle, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    saved = None
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        if target.exists():
            shutil.copymode(target, name)
        if state(config) != seen:
            raise InstallError(f"{config} changed while this was running, so it was left as it is. "
                               "Quit Claude Desktop completely, then run this again.")
        saved = backup(target, stamp)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        if saved is not None:
            saved.unlink(missing_ok=True)
        raise
    return saved


def shown(entry: object) -> object:
    """What may be printed of a server entry: its command and arguments, never its environment."""
    if isinstance(entry, dict):
        return {key: entry[key] for key in OWNED_KEYS if key in entry}
    return None


def install(config: Path, entry: dict, check: bool, stamp: str) -> dict:
    seen = state(config)
    doc = read_config(config)
    servers = doc.get(SERVERS_KEY) or {}
    previous = servers.get(SERVER_NAME)
    result = {"config": str(config), "server": entry}
    if shown(previous) == entry:
        return {"action": "unchanged", **result, "note": "Claude Desktop already starts POBG from this folder."}
    if previous is not None:
        result["previous"] = shown(previous)
    if isinstance(previous, dict):                       # the user's own additions (env ...) stay, in place
        entry = {**previous, **entry}
    action = "updated" if previous is not None else "installed"
    if check:
        return {"action": f"would be {action}", **result, "note": "Nothing was written (--check)."}
    doc[SERVERS_KEY] = {**servers, SERVER_NAME: entry}
    saved = save(config, doc, seen, stamp)
    return {"action": action, **result, "backup": str(saved) if saved else None, "next": RESTART}


def remove(config: Path, check: bool, stamp: str) -> dict:
    seen = state(config)
    doc = read_config(config)
    servers = doc.get(SERVERS_KEY) or {}
    if SERVER_NAME not in servers:
        return {"action": "unchanged", "config": str(config), "note": "POBG is not registered in Claude Desktop."}
    result = {"config": str(config), "previous": shown(servers[SERVER_NAME])}
    if check:
        return {"action": "would be removed", **result, "note": "Nothing was written (--check)."}
    doc[SERVERS_KEY] = {name: value for name, value in servers.items() if name != SERVER_NAME}
    saved = save(config, doc, seen, stamp)
    return {"action": "removed", **result, "backup": str(saved) if saved else None, "next": RESTART}


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, platform: str | None = None,
         home: Path | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Register this folder's POBG server in Claude Desktop.")
    parser.add_argument("--check", action="store_true", help="say what would change, write nothing")
    parser.add_argument("--remove", action="store_true", help="remove the POBG server from Claude Desktop")
    parser.add_argument("--config", help="path of claude_desktop_config.json, when it is not found")
    args = parser.parse_args(argv)
    env = dict(os.environ) if env is None else env
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        config = find_config(args.config, platform or sys.platform, env, home or Path.home())
        if args.remove:
            result = remove(config, args.check, stamp)
        else:
            result = install(config, server_entry(find_uv(env), root), args.check, stamp)
    except InstallError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except OSError as exc:
        print(json.dumps({"error": f"the config file could not be read or written ({type(exc).__name__}). "
                                   "It was left unchanged."}))
        return 1
    print(json.dumps(result, indent=2))                  # ASCII only: any console code page can show it
    return 0


if __name__ == "__main__":
    sys.exit(main())
