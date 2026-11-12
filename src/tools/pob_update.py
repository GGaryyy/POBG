"""
pob_update.py — Update a local Path of Building (PoE2) to the latest release, into a new folder.

    python -m src.tools.pob_update --dir <folder> --check   # versions only, writes nothing
    python -m src.tools.pob_update --dir <folder>           # download into a new folder next to it

<folder> is either a Path of Building folder (it holds manifest.xml) or a PoeCharm2 folder (it
holds PoeCharm3.exe, with Path of Building in PathOfBuildingCommunity-PoE2-Portable). PoB comes
from its GitHub release, checked against the SHA-256 GitHub publishes; PoeCharm2 has no
releases, so its latest commit is downloaded (GitHub publishes no checksum for that).

The old folder is never changed or deleted. Saved builds (Builds/) and PoeCharm2's language
setting are copied into the new folder; PoB's Settings.xml is not, as it holds the account
login. Everything is downloaded and unpacked in a temporary work folder next to the old one,
which is renamed only when every step passed; on any failure it is removed, and work folders
left by an interrupted run are removed at the next start once untouched for an hour (so do
not run two updates of the same place at once).

This is a command-line tool, not an MCP tool: a full update downloads about 400 MB and writes
files, so it runs only when the user asks for it. The result is printed as JSON on stdout;
progress goes to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

import requests

from src.scrapers.common import USER_AGENT

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

POB_REPO = "PathOfBuildingCommunity/PathOfBuilding-PoE2"
POB_ASSET = "PathOfBuildingCommunity-PoE2-Portable.zip"
CHARM_REPO = "Chuanhsing/PoeCharm2"
API = "https://api.github.com/repos/"
POB_RELEASE_URL = f"{API}{POB_REPO}/releases/latest"
CHARM_COMMIT_URL = f"{API}{CHARM_REPO}/commits?per_page=1"
CHARM_ZIP_URL = "https://github.com/" + CHARM_REPO + "/archive/{sha}.zip"
DOWNLOAD_PREFIX = "https://github.com/"   # release files and archives both come from here
POB_DIR = "PathOfBuildingCommunity-PoE2-Portable"
CHARM_EXE = "PoeCharm3.exe"
MANIFEST = "manifest.xml"
BUILDS = "Builds"
CHARM_SETTINGS = Path("Data") / "Settings.conf"
MARKER = "POBG_UPDATE.json"           # what this tool installed, so --check can compare PoeCharm2 too
WORK_PREFIX = ".pobg-update-"
STALE_WORK_SECONDS = 3600             # a work folder untouched this long is from an interrupted run
CHARM_ALLOWANCE = 200 * 1024 ** 2     # PoeCharm2 download cap, and its share of the space check, bytes
SPACE_FACTOR = 3                      # zip + unpacked PoB, against the zip size
MAX_UNPACKED = 4 * 1024 ** 3          # refuse an archive that unpacks past this
REQUEST_TIMEOUT = 60
CHUNK = 1024 * 1024
PROGRESS_EVERY = 50 * 1024 ** 2
RENAME_TRIES = 5                      # Windows virus scanning can hold fresh .exe files for a moment
RENAME_WAIT = 2.0
DIGEST_PREFIX = "sha256:"
VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){0,3})$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNPACK_ERRORS = (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError)


class UpdateError(Exception):
    """A step failed; the message says what and that the old folder is unchanged."""


class Http(Protocol):
    def get_json(self, url: str) -> object: ...
    def download(self, url: str, dest: Path, on_chunk: Callable[[bytes], None]) -> None: ...


@dataclass
class Install:
    folder: Path        # what the user named, made absolute
    kind: str           # "pob" or "poecharm"
    pob_dir: Path       # where manifest.xml is
    version: str | None
    charm_sha: str | None


@dataclass
class Latest:
    version: str
    asset_url: str
    asset_size: int
    sha256: str
    charm_sha: str | None = None
    charm_date: str | None = None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class RequestsHttp:
    """GitHub over requests, with the project User-Agent."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get_json(self, url: str) -> object:
        response = self.session.get(url, timeout=REQUEST_TIMEOUT, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        return response.json()

    def download(self, url: str, dest: Path, on_chunk: Callable[[bytes], None]) -> None:
        with self.session.get(url, timeout=REQUEST_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_content(CHUNK):
                    on_chunk(chunk)          # may raise to stop an oversized download
                    handle.write(chunk)


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def find_install(folder: Path) -> Install:
    """What kind of install the folder is, and its PoB version."""
    folder = Path(os.path.abspath(folder))   # also folds "..", so `parent` is the real parent
    if not folder.is_dir():
        raise UpdateError(f"{folder} is not a folder")
    if folder.parent == folder:
        raise UpdateError(f"{folder} is a drive root; give the Path of Building or PoeCharm2 folder itself")
    if (folder / CHARM_EXE).is_file():
        kind, pob_dir = "poecharm", folder / POB_DIR
    elif (folder.parent / CHARM_EXE).is_file():
        raise UpdateError(f"{folder} is the Path of Building inside a PoeCharm2 folder; "
                          f"give the PoeCharm2 folder instead: {folder.parent}")
    elif (folder / MANIFEST).is_file():
        kind, pob_dir = "pob", folder
    else:
        raise UpdateError(f"{folder} holds neither {MANIFEST} (Path of Building) nor {CHARM_EXE} (PoeCharm2)")
    marker = _read_marker(folder)
    sha = marker.get("charm_sha")
    return Install(folder=folder, kind=kind, pob_dir=pob_dir, version=read_version(pob_dir / MANIFEST),
                   charm_sha=sha if isinstance(sha, str) else None)


def read_version(manifest: Path) -> str | None:
    """The `<Version number="…">` of a PoB manifest.xml; None when missing or unreadable."""
    try:
        root = ET.parse(manifest).getroot()
    except (OSError, ET.ParseError):
        return None
    node = root.find("Version")
    return node.get("number") if node is not None else None


def latest(http: Http, kind: str) -> Latest:
    """The latest PoB release (and PoeCharm2 commit for a PoeCharm2 install). 1–2 requests.
    Every value taken from GitHub is checked before use."""
    release = http.get_json(POB_RELEASE_URL)
    if not isinstance(release, dict):
        raise UpdateError("GitHub returned an unexpected release record")
    match = VERSION_RE.match(str(release.get("tag_name") or ""))
    assets = release.get("assets")
    assets = assets if isinstance(assets, list) else []
    asset = next((a for a in assets if isinstance(a, dict) and a.get("name") == POB_ASSET), None)
    if not match or asset is None:
        raise UpdateError(f"the latest Path of Building release has no {POB_ASSET}")
    url, size, digest = asset.get("browser_download_url"), asset.get("size"), str(asset.get("digest") or "")
    if not (isinstance(url, str) and url.startswith(DOWNLOAD_PREFIX)) or not (isinstance(size, int) and size > 0):
        raise UpdateError("the release file record from GitHub has no usable download link or size")
    sha256 = digest[len(DIGEST_PREFIX):].lower() if digest.startswith(DIGEST_PREFIX) else ""
    if not SHA256_RE.match(sha256):
        raise UpdateError("GitHub publishes no SHA-256 for the release file, so it cannot be checked; "
                          "download it yourself from the release page")
    found = Latest(version=match.group(1), asset_url=url, asset_size=size, sha256=sha256)
    if kind == "poecharm":
        found.charm_sha, found.charm_date = _charm_commit(http.get_json(CHARM_COMMIT_URL))
    return found


def _charm_commit(commits: object) -> tuple[str, str]:
    first = commits[0] if isinstance(commits, list) and commits and isinstance(commits[0], dict) else {}
    sha = str(first.get("sha") or "")
    commit = first.get("commit") if isinstance(first.get("commit"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    date = str(committer.get("date") or "")[:10]
    if not SHA_RE.match(sha) or not DATE_RE.match(date):
        raise UpdateError("GitHub returned no usable PoeCharm2 commit")
    return sha, date


def is_current(install: Install, newest: Latest) -> bool:
    """PoB at the latest release, and PoeCharm2 at the latest commit when its version is known
    (a PoeCharm2 not installed by this tool has no record of its commit)."""
    if install.version is None or _version_key(install.version) < _version_key(newest.version):
        return False
    return install.kind == "pob" or install.charm_sha is None or install.charm_sha == newest.charm_sha


def check(folder: Path, http: Http) -> dict:
    """Installed and latest versions. Reads the folder, writes nothing."""
    install = find_install(folder)
    newest = latest(http, install.kind)
    return {"folder": str(install.folder), "kind": install.kind, "installed": install.version,
            "latest": newest.version,
            "poecharm_installed": install.charm_sha if install.kind == "poecharm" else None,
            "poecharm_latest": newest.charm_sha, "poecharm_latest_date": newest.charm_date,
            "up_to_date": is_current(install, newest), "note": _charm_note(install)}


def update(folder: Path, http: Http) -> dict:
    """Install the latest PoB (and PoeCharm2) into a new folder next to `folder`."""
    install = find_install(folder)
    removed = _sweep_stale_work(install.folder.parent)
    newest = latest(http, install.kind)
    if is_current(install, newest):
        return {"folder": str(install.folder), "kind": install.kind, "installed": install.version, "updated": False,
                "note": " ".join(filter(None, ["already the latest version.", _charm_note(install)])),
                "stale_work_folders_removed": removed}
    target = install.folder.parent / new_folder_name(install.kind, newest)
    if target.exists():
        raise UpdateError(f"{target} already exists; rename or remove it first. Nothing was changed.")
    _check_space(install, newest)
    work = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=install.folder.parent))
    try:
        staged = _stage(install, newest, http, work)
        copied = _carry_over(install, staged, newest)
        _rename(staged, target)
    except (UpdateError, OSError, requests.RequestException, *UNPACK_ERRORS) as exc:
        raise UpdateError(f"{_describe(exc)}. The old folder is unchanged and nothing new was kept.") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
    charm = install.kind == "poecharm"
    return {"folder": str(install.folder), "kind": install.kind, "installed": install.version, "updated": True,
            "new_folder": str(target), "version": newest.version,
            "poecharm_commit": newest.charm_sha, "poecharm_commit_date": newest.charm_date,
            "builds_copied": copied["builds"], "language_copied": copied["language"],
            "stale_work_folders_removed": removed,
            "checksum": "PoB release file matched GitHub's SHA-256"
                        + ("; PoeCharm2 has no published checksum" if charm else ""),
            "next": ("open the new folder's PoeCharm3.exe" if charm
                     else f"open {Path(target.name) / 'Path of Building-PoE2.exe'}")
                    + "; sign in again (Settings.xml was not copied). The old folder can be deleted when "
                      "the new one works."}


def new_folder_name(kind: str, newest: Latest) -> str:
    """Named by PoB's version (and PoeCharm2's commit day), so a new PoB release never lands on
    the folder of the previous one."""
    if kind == "pob":
        return f"{POB_DIR}-{newest.version}"
    return f"PoeCharm2-{(newest.charm_date or '').replace('-', '')}-pob{newest.version}"


def safe_extract(archive: Path, dest: Path) -> None:
    """Unpack a zip into dest, refusing members that would land outside it or unpack too large."""
    root = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if sum(m.file_size for m in members) > MAX_UNPACKED:
            raise UpdateError(f"{archive.name} unpacks past {MAX_UNPACKED // 1024 ** 3} GB")
        for member in members:
            name = PurePosixPath(member.filename.replace("\\", "/"))
            unsafe = name.is_absolute() or ".." in name.parts or (name.parts and ":" in name.parts[0])
            if unsafe or not (root / name).resolve().is_relative_to(root):
                raise UpdateError(f"{archive.name} has an unsafe path: {member.filename[:80]}")
        zf.extractall(root)


def _check_space(install: Install, newest: Latest) -> None:
    needed = newest.asset_size * SPACE_FACTOR + (CHARM_ALLOWANCE if install.kind == "poecharm" else 0)
    free = shutil.disk_usage(install.folder.parent).free
    if free < needed:
        raise UpdateError(f"not enough free space next to {install.folder}: {free // 1024 ** 2} MB free, "
                          f"about {needed // 1024 ** 2} MB needed. Nothing was changed.")


def _stage(install: Install, newest: Latest, http: Http, work: Path) -> Path:
    """Download, check and unpack into work/; returns the folder that becomes the new install."""
    pob_zip = work / POB_ASSET
    digest = hashlib.sha256()
    _download(http, newest.asset_url, pob_zip, newest.asset_size, "Path of Building", digest.update)
    if digest.hexdigest() != newest.sha256:
        raise UpdateError("the downloaded Path of Building file does not match GitHub's SHA-256")
    pob_out = _unpacked(pob_zip, work / "pob")
    if not (pob_out / MANIFEST).is_file():
        raise UpdateError(f"the release file has no {MANIFEST}")
    if install.kind == "pob":
        return pob_out
    charm_zip = work / "poecharm.zip"
    _download(http, CHARM_ZIP_URL.format(sha=newest.charm_sha), charm_zip, CHARM_ALLOWANCE, "PoeCharm2", None)
    charm_out = _unpacked(charm_zip, work / "charm")
    if not (charm_out / CHARM_EXE).is_file():
        raise UpdateError(f"the PoeCharm2 download has no {CHARM_EXE}")
    pob_out.rename(charm_out / POB_DIR)
    return charm_out


def _download(http: Http, url: str, dest: Path, limit: int, label: str,
              on_data: Callable[[bytes], None] | None) -> None:
    """Download with a byte cap (the published size, or an allowance) and progress on stderr."""
    seen = {"bytes": 0, "reported": 0}

    def on_chunk(chunk: bytes) -> None:
        seen["bytes"] += len(chunk)
        if seen["bytes"] > limit:
            raise UpdateError(f"the {label} download is larger than expected ({limit // 1024 ** 2} MB)")
        if on_data:
            on_data(chunk)
        if seen["bytes"] - seen["reported"] >= PROGRESS_EVERY:
            seen["reported"] = seen["bytes"]
            print(f"{label}: {seen['bytes'] // 1024 ** 2} MB", file=sys.stderr, flush=True)

    print(f"{label}: downloading", file=sys.stderr, flush=True)
    http.download(url, dest, on_chunk)


def _unpacked(archive: Path, dest: Path) -> Path:
    """Unpack and return the content folder: the single top folder when the zip has one."""
    dest.mkdir()
    safe_extract(archive, dest)
    archive.unlink()
    entries = list(dest.iterdir())
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else dest


def _carry_over(install: Install, staged: Path, newest: Latest) -> dict:
    """Copy saved builds and PoeCharm2's language setting into the staged folder."""
    new_pob = staged / POB_DIR if install.kind == "poecharm" else staged
    builds = 0
    old_builds = install.pob_dir / BUILDS
    if old_builds.is_dir():
        shutil.copytree(old_builds, new_pob / BUILDS, dirs_exist_ok=True)
        builds = sum(1 for p in old_builds.rglob("*") if p.is_file())
    language = False
    if install.kind == "poecharm" and (install.folder / CHARM_SETTINGS).is_file():
        (staged / CHARM_SETTINGS).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(install.folder / CHARM_SETTINGS, staged / CHARM_SETTINGS)
        language = True
    (staged / MARKER).write_text(json.dumps({"pob_version": newest.version, "charm_sha": newest.charm_sha},
                                            indent=2) + "\n", encoding="utf-8")
    return {"builds": builds, "language": language}


def _rename(staged: Path, target: Path) -> None:
    """Move the finished folder into place, retrying while Windows still holds a fresh file."""
    for attempt in range(RENAME_TRIES):
        try:
            staged.rename(target)
            return
        except PermissionError:
            if attempt == RENAME_TRIES - 1:
                raise
            time.sleep(RENAME_WAIT)


def _sweep_stale_work(parent: Path) -> int:
    """Remove work folders an interrupted run left behind (untouched for an hour)."""
    removed = 0
    for path in parent.glob(WORK_PREFIX + "*"):
        try:
            idle = time.time() - path.stat().st_mtime
        except OSError:
            continue
        if path.is_dir() and idle > STALE_WORK_SECONDS:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def _charm_note(install: Install) -> str | None:
    if install.kind == "pob" or install.charm_sha:
        return None
    return ("the installed PoeCharm2 version is unknown (it was not installed by this tool); "
            "only Path of Building's version is compared")


def _read_marker(folder: Path) -> dict:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _version_key(version: str) -> tuple[int, ...]:
    match = VERSION_RE.match(version.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else (-1,)


def _describe(exc: Exception) -> str:
    """The error without local paths beyond what the user typed."""
    if isinstance(exc, UpdateError):
        return str(exc)
    if isinstance(exc, requests.RequestException):
        return f"download failed ({type(exc).__name__})"
    if isinstance(exc, UNPACK_ERRORS):
        return f"a download could not be unpacked ({type(exc).__name__})"
    return f"{type(exc).__name__} while writing the new folder"


def main(argv: list[str] | None = None, http: Http | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update a local Path of Building (PoE2) into a new folder.")
    parser.add_argument("--dir", required=True, type=Path, help="the Path of Building or PoeCharm2 folder")
    parser.add_argument("--check", action="store_true", help="only compare versions; write nothing")
    args = parser.parse_args(argv)
    http = http or RequestsHttp()
    folder = args.dir.expanduser()
    try:
        result = check(folder, http) if args.check else update(folder, http)
    except UpdateError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    except requests.RequestException as exc:
        print(json.dumps({"error": f"GitHub could not be reached ({type(exc).__name__}). Nothing was changed."}))
        return 1
    except OSError as exc:      # e.g. a folder that cannot be written next to
        print(json.dumps({"error": f"a file or folder could not be read or written ({type(exc).__name__}). "
                                   "Nothing was changed."}))
        return 1
    except ValueError as exc:   # a reply that is not JSON
        print(json.dumps({"error": f"GitHub returned something unexpected ({type(exc).__name__}). "
                                   "Nothing was changed."}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
