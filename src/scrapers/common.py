"""
common.py — Shared HTTP, text and file helpers for the poe2db scrapers.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

USER_AGENT = "POBG/0.11 (+https://github.com/GGaryyy/POBG; research scraper)"
REQUEST_TIMEOUT = 30
DEFAULT_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.5
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_EXCEPTIONS = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)
MAX_RETRY_AFTER_SECONDS = 60
DATA_LOCK_FILE = ".update.lock"     # inside data/: one writer per data folder, across processes

_CJK_SPACE_RE = re.compile(r"(?<=[^\x00-\x7F]) +(?=[^\x00-\x7F])")
_RANGE_RE = re.compile(r"^\(\s*(-?\d+(?:\.\d+)?)\s*[—–-]\s*(-?\d+(?:\.\d+)?)\s*\)")
_TAB_PANE_SELECTOR = "div.tab-pane[id]"
_SAFE_NAME_RE = re.compile(r"^[\w%.,'()!+\-]+$")
MIN_CACHEABLE_BYTES = 64

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def fetch_html(
    url: str,
    *,
    timeout: int = REQUEST_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    delay: float = 0.0,
    session: requests.Session | None = None,
) -> str:
    """GET a page and return its text, retrying on 429/5xx with backoff.

    Raises requests.HTTPError after the last failed attempt.
    """
    if retries < 1:
        raise ValueError("retries must be >= 1")
    getter = session.get if session is not None else requests.get
    last_error: requests.RequestException = requests.ConnectionError(f"no attempt made for {url}")
    wait = 0.0
    for attempt in range(1, retries + 1):
        if delay or wait:
            time.sleep(max(delay, wait))
        try:
            resp = getter(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        except RETRY_EXCEPTIONS as exc:
            last_error = exc
            _warn(f"{type(exc).__name__} for {url} (attempt {attempt}/{retries}): {exc}")
        else:
            if resp.status_code in RETRY_STATUS:
                last_error = requests.HTTPError(f"{resp.status_code} for {url}", response=resp)
                _warn(f"HTTP {resp.status_code} for {url} (attempt {attempt}/{retries})")
            else:
                resp.raise_for_status()
                if "charset" not in resp.headers.get("content-type", "").lower():
                    resp.encoding = "utf-8"
                return resp.text
        wait = _retry_wait(attempt, getattr(getattr(last_error, "response", None), "headers", {}) or {})
    raise last_error


def _retry_wait(attempt: int, headers) -> float:
    """Exponential backoff, or the server's Retry-After when it sends one (capped)."""
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    if retry_after and str(retry_after).isdigit():
        return min(int(retry_after), MAX_RETRY_AFTER_SECONDS)
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------


def clean_text(raw: str) -> str:
    """Collapse whitespace and drop spaces between CJK characters."""
    text = re.sub(r"\s+", " ", raw).strip()
    return _CJK_SPACE_RE.sub("", text)


def node_text(node: Tag | None) -> str | None:
    """Clean text of a BeautifulSoup node, or None when the node is missing/empty."""
    if node is None:
        return None
    text = clean_text(node.get_text(" ", strip=True))
    return text or None


def parse_range(text: str | None) -> list[int | float] | None:
    """Parse '(1 — 20)' / '(1—20)' / '(0.5 - 1.5)' at the start of text into [a, b].

    Returns None when the text does not start with a parenthesised range.
    """
    if not text:
        return None
    match = _RANGE_RE.match(text.strip())
    if not match:
        return None
    return [_to_number(match.group(1)), _to_number(match.group(2))]


def _to_number(token: str) -> int | float:
    return float(token) if "." in token else int(token)


def slug_from_href(href: str | None) -> str | None:
    """'/us/Leap_Slam' or 'https://poe2db.tw/tw/Leap_Slam' or 'Leap_Slam' -> 'Leap_Slam'."""
    if not href:
        return None
    path = href.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    slug = path.rsplit("/", 1)[-1]
    if not slug or slug in (".", ".."):
        return None
    return slug


# ---------------------------------------------------------------------------
# SECTIONS
# ---------------------------------------------------------------------------


def find_section(
    soup: BeautifulSoup,
    ids: dict[str, str],
    lang: str,
    pane_index: int | None = None,
) -> Tag | None:
    """Locate a tab-pane by its per-language id, falling back to its position.

    ids maps language codes (e.g. 'en', 'zh-tw') to element ids.
    """
    wanted = ids.get(lang) or ids.get("en")
    if wanted:
        node = soup.find(id=wanted)
        if node is not None:
            return node
    if pane_index is None:
        return None
    panes = soup.select(_TAB_PANE_SELECTOR)
    if 0 <= pane_index < len(panes):
        return panes[pane_index]
    return None


def make_soup(html: str) -> BeautifulSoup:
    """Parse HTML and strip script/style so text extraction is clean."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style"):
        tag.decompose()
    return soup


# ---------------------------------------------------------------------------
# FILES
# ---------------------------------------------------------------------------


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    """Write records atomically (unique temp file in the same folder, then replace). Returns the count."""
    lines: list[str] = []
    for rec in records:
        lines.append(json.dumps(rec, ensure_ascii=False) + "\n")
    atomic_write_text(Path(path), "".join(lines))
    return len(lines)


def atomic_write_text(path: Path, text: str) -> None:
    """Write text via a uniquely named temp file so concurrent writers never share it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:   # same bytes on every OS
            fh.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def safe_cache_name(slug: str) -> str:
    """A slug usable as a file name; rejects separators, '.' / '..' and anything unusual."""
    if not slug or slug in (".", "..") or not _SAFE_NAME_RE.match(slug):
        raise ValueError(f"unsafe cache name: {slug!r}")
    return slug


def file_time_iso(path: Path) -> str:
    return datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL not found: {path}")
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc
    return records


def cached_fetch(url: str, cache_file: Path, fetch, offline: bool = False) -> str | None:
    """Return cache_file's text, fetching url and caching it atomically when missing.

    Returns None when offline and the file is not cached.
    """
    cache_file = Path(cache_file)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    if offline:
        return None
    html = fetch(url)
    if len(html.encode("utf-8")) >= MIN_CACHEABLE_BYTES:  # never pin an empty/error body forever
        atomic_write_text(cache_file, html)
    return html


class LockBusy(Exception):
    """Another process holds the data lock."""


@contextlib.contextmanager
def file_lock(path: Path):
    """Cross-process lock held through the operating system (flock / msvcrt): it is released when
    the holder exits, even after a crash, so no lock is ever taken over by age. The lock file
    itself stays in place; only the lock on it matters."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        _lock_fd(fd)
    except OSError:
        os.close(fd)
        raise LockBusy(f"{path.name} is held by another process") from None
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()} {now_iso()}\n".encode("utf-8"))   # for a human looking at the file
        yield
    finally:
        try:
            _unlock_fd(fd)
        finally:
            os.close(fd)


if os.name == "nt":
    import msvcrt

    def _lock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock_fd(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)
