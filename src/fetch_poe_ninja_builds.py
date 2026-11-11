"""
fetch_poe_ninja_builds.py
=========================
Fetch PoE2 character build data from poe.ninja's internal API.

API discovery notes
-------------------
poe.ninja serves PoE2 builds via an Astro/React SPA.  The relevant endpoints
were discovered by analysing the JavaScript bundles loaded by the page:

  1. GET /poe2/api/data/index-state
       Returns available leagues with their snapshot version strings and
       snapshotName slugs.

  2. GET /poe2/api/builds/{version}/search?overview={snapshotName}[&sort=field]
       Returns a binary protobuf blob (no standard .proto schema is published)
       containing up to 100 character records.  The same 100 records are always
       returned regardless of filter query params; filters are applied
       client-side.  Different sort keys (dps, level, life, energyshield, etc.)
       give different top-100 subsets, allowing collection of diverse records.

  3. GET /poe2/api/builds/dictionary/{hash}
       Returns a protobuf blob mapping dimension keys to string values
       (class names, gem names, passive keystone names, etc.).  Hash values
       are embedded in the search response.

Protobuf schema (reverse-engineered, field-by-field)
------------------------------------------------------
search response outer wrapper:
  field 1 (bytes)  -> nested result message

nested result message:
  field 1 (varint) -> total character count in league
  field 2 (bytes)  -> filter dimension definition (repeated):
      field 1 (bytes)   -> dimension API key (e.g. "class", "skills")
      field 2 (bytes)   -> display key
      field 3 (bytes)   -> count entry (repeated):
          field 1 (varint) -> dict index (0 if omitted)
          field 2 (varint) -> number of characters with this value
  field 3 (bytes)  -> integer dimension definition (repeated)
  field 12 (bytes) -> column (repeated, one per column; as observed on 2026-11-11 —
                      until early 2026 the columns were in field 5 with one cell message per row):
      field 1 (bytes)   -> column key (e.g. "name", "class", "skills")
      field 2 (bytes)   -> display key
      field 11 (bytes)  -> dictionary the indices refer to ("class", "gem", "keypassive")
      field 13 (varint) -> row count
      string cols  -> field 7 (bytes, repeated) = one UTF-8 string per row
      integer cols -> field 6 (bytes) = packed varints, one per row (a dictionary index for "class")
      list cols    -> field 9 (bytes, repeated) = per row a message whose field 1 holds packed
                      varints (dictionary indices)
  field 6 (bytes)  -> dictionary reference (repeated):
      field 1 (bytes)   -> dimension key
      field 2 (bytes)   -> hex SHA-1 hash of the dictionary blob

dictionary blob (as observed on 2026-11-11; a protobuf with repeated field 2 until early 2026):
  "NDIC" container, little-endian:
    bytes 0-3    magic "NDIC"        bytes 4-7    version (2)
    bytes 12-15  number of strings   bytes 16-23  hash
    bytes 24-27  strings per block   bytes 28-31  number of blocks
    bytes 32-35  number of strings (again)
    then one 8-byte entry per block (offset into the string data, first index),
    then one length per string (a varint; one byte in practice),
    then the strings, concatenated, in index order

Output schema (per record)
--------------------------
Character and account names are used in memory to de-duplicate the sort passes and are
never written to disk (PRIVATE_FIELDS).
{
  "class":          str | null,   # ascendancy name (e.g. "Stormweaver")
  "level":          int | null,
  "main_skill":     str | null,   # the skill the DPS figure is for ("dps.skill"), else the first skill
  "skill_gems":     [str],        # all gems from the 'skills' column
  "keystones":      [str],        # passive keystones from 'keypassives' column
  "league":         str,
  "rank":           int,          # 1-based position in this sort pass
  "source":         "poe.ninja",
  "fetched_at":     str           # ISO-8601 UTC
}

Output: data/community_builds/poe_ninja_builds.jsonl
"""

import re
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from src.scrapers.common import USER_AGENT, write_jsonl

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_URL = "https://poe.ninja"
INDEX_STATE_URL = f"{BASE_URL}/poe2/api/data/index-state"
SEARCH_URL_TMPL = f"{BASE_URL}/poe2/api/builds/{{version}}/search"
DICT_URL_TMPL = f"{BASE_URL}/poe2/api/builds/dictionary/{{hash}}"

# Sort keys to cycle through — each yields a different top-100 subset.
# dps/level are the most informative for build analysis.
SORT_KEYS = [
    "dps",          # default (descending)
    "level",        # level descending
    "life",
    "energyshield",
    "ehp",
    "armour",
    "evasion",
    "spirit",
]
# Extra passes: dps ascending gets low-DPS builds (more variety)
SORT_KEYS_ASC = [
    "dps",
    "level",
]

MAX_RECORDS = 500          # stop after collecting this many unique characters
# Layout of the search response (reverse-engineered; it changed in 2026, see the module docstring)
COLUMN_FIELD = 12          # one message per column in the result message
STRING_CELL_FIELD = 7      # string column: one cell per row
PACKED_INT_FIELD = 6       # integer column: every row in one packed field
LIST_CELL_FIELD = 9        # list column: one cell per row, packed dictionary indices inside
# Layout of a dictionary blob ("NDIC" container, little-endian)
MAX_VARINT_BYTES = 10       # a 64-bit varint; anything longer is malformed input
DICTIONARIES = ("class", "gem", "keypassive")   # the only dictionaries fetched, once each
HASH_PATTERN = re.compile(r"[0-9a-f]{1,64}")
NDIC_MAGIC = b"NDIC"
NDIC_COUNT_OFFSET = 12     # u32: number of strings
NDIC_BLOCKS_OFFSET = 28    # u32: number of entries in the block index that follows the header
NDIC_HEADER_SIZE = 36
NDIC_BLOCK_ENTRY_SIZE = 8  # (u32 offset into the string data, u32 first index)
REQUEST_DELAY = 0.8        # seconds before every HTTP request
REQUEST_TIMEOUT = 30       # seconds

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "community_builds" / "poe_ninja_builds.jsonl"
PRIVATE_FIELDS = ("character_name", "account_name", "sort_key")  # never written to disk

# The fetcher says who it is, like the poe2db scrapers; it does not pose as a browser.
HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def _get_json(url: str) -> dict:
    time.sleep(REQUEST_DELAY)
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _get_binary(url: str) -> bytes:
    time.sleep(REQUEST_DELAY)
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# PROTOBUF DECODING HELPERS
# ---------------------------------------------------------------------------

def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a varint from bytes at pos.  Returns (value, new_pos)."""
    result = 0
    for shift in range(0, 7 * MAX_VARINT_BYTES, 7):
        if pos >= len(data):
            raise ValueError("varint runs past the end of the data")
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
    raise ValueError("varint is longer than 10 bytes")


def _parse_proto(data: bytes) -> list[tuple[int, str, object]]:
    """
    Minimal protobuf parser.
    Returns list of (field_number, wire_type_name, value) tuples.
    wire_type_name: 'varint' | 'bytes' | 'i32' | 'i64'
    Stops on any parse error rather than raising.
    """
    pos = 0
    fields: list[tuple[int, str, object]] = []
    while pos < len(data):
        try:
            tag_val, pos = _read_varint(data, pos)
            fn = tag_val >> 3
            wt = tag_val & 7
            if wt == 0:  # varint
                val, pos = _read_varint(data, pos)
                fields.append((fn, "varint", val))
            elif wt == 2:  # length-delimited
                length, pos = _read_varint(data, pos)
                val = data[pos : pos + length]
                pos += length
                fields.append((fn, "bytes", val))
            elif wt == 5:  # 32-bit
                fields.append((fn, "i32", data[pos : pos + 4]))
                pos += 4
            elif wt == 1:  # 64-bit
                fields.append((fn, "i64", data[pos : pos + 8]))
                pos += 8
            else:
                break
        except (IndexError, ValueError):
            break
    return fields


def _decode_dict_blob(raw: bytes) -> list[str]:
    """A poe.ninja dictionary as a list of strings (position = index)."""
    if raw.startswith(NDIC_MAGIC):
        return _decode_ndic(raw)
    return _decode_proto_dict(raw)


def _decode_ndic(raw: bytes) -> list[str]:
    """The "NDIC" container poe.ninja serves since 2026 (see the module docstring).

    Returns an empty list when the sizes in the header do not add up, so that a format change
    shows up as missing names instead of wrong ones.
    """
    if len(raw) < NDIC_HEADER_SIZE:
        return []
    count, = struct.unpack_from("<I", raw, NDIC_COUNT_OFFSET)
    blocks, = struct.unpack_from("<I", raw, NDIC_BLOCKS_OFFSET)
    pos = NDIC_HEADER_SIZE + blocks * NDIC_BLOCK_ENTRY_SIZE
    lengths: list[int] = []
    for _ in range(count):
        if pos >= len(raw):
            return []
        try:
            length, pos = _read_varint(raw, pos)
        except ValueError:
            return []
        lengths.append(length)
    if pos + sum(lengths) != len(raw):
        return []
    values: list[str] = []
    for length in lengths:
        values.append(raw[pos : pos + length].decode("utf-8", errors="replace"))
        pos += length
    return values


def _decode_proto_dict(raw: bytes) -> list[str]:
    """The protobuf dictionary served until early 2026: field 2 = value string, repeated."""
    return [v.decode("utf-8", errors="replace") for fn, wt, v in _parse_proto(raw) if fn == 2 and wt == "bytes"]


def _unpack_varints(packed: bytes) -> list[int]:
    values: list[int] = []
    pos = 0
    while pos < len(packed):
        try:
            value, pos = _read_varint(packed, pos)
        except ValueError:
            return []          # malformed: no values rather than shifted ones
        values.append(value)
    return values


def _column(inner: list[tuple[int, str, object]], name: str) -> list[tuple[int, str, object]]:
    """The parsed column message whose key (field 1) is `name`, or an empty list."""
    for fn, wt, value in inner:
        if fn != COLUMN_FIELD or wt != "bytes":
            continue
        sub = _parse_proto(value)
        key = next((v for f, w, v in sub if f == 1 and w == "bytes"), None)
        if key == name.encode("utf-8"):
            return sub
    return []


def _column_strings(column: list[tuple[int, str, object]]) -> list[str]:
    """String column: one UTF-8 cell per row."""
    return [v.decode("utf-8", errors="replace") for f, w, v in column if f == STRING_CELL_FIELD and w == "bytes"]


def _column_ints(column: list[tuple[int, str, object]]) -> list[int]:
    """Integer column: all rows packed into one field."""
    packed = next((v for f, w, v in column if f == PACKED_INT_FIELD and w == "bytes"), b"")
    return _unpack_varints(packed)


def _column_lists(column: list[tuple[int, str, object]], dictionary: list[str]) -> list[list[str]]:
    """List column: per row, packed indices into the column's dictionary."""
    rows: list[list[str]] = []
    for f, w, cell in column:
        if f != LIST_CELL_FIELD or w != "bytes":
            continue
        packed = next((v for sf, sw, v in _parse_proto(cell) if sf == 1 and sw == "bytes"), b"")
        names = [dictionary[i] for i in _unpack_varints(packed) if i < len(dictionary)]
        rows.append([name for name in names if name])
    return rows


def _column_dictionary(column: list[tuple[int, str, object]]) -> str | None:
    """Name of the dictionary a column's indices refer to (field 11)."""
    name = next((v for f, w, v in column if f == 11 and w == "bytes"), None)
    return name.decode("utf-8", errors="replace") if name is not None else None


def _aligned(values: list, rows: int, label: str) -> list:
    """A column must have one value per row; otherwise every later row would get another
    character's value, so the whole column is dropped."""
    if values and len(values) != rows:
        _warn(f"Search response: column {label} has {len(values)} values for {rows} rows; ignoring it")
        return []
    return values


def _at(values: list, index: int):
    return values[index] if index < len(values) else None


def _main_skill(dps_index: int | None, gem_dict: list[str], skill_gems: list[str]) -> str | None:
    """The skill the site computed DPS for, when the character really has it; else the first skill."""
    if dps_index is not None and dps_index < len(gem_dict) and gem_dict[dps_index] in skill_gems:
        return gem_dict[dps_index]
    return skill_gems[0] if skill_gems else None


# ---------------------------------------------------------------------------
# SEARCH RESPONSE PARSING
# ---------------------------------------------------------------------------

def _parse_search_response(
    raw: bytes,
    class_dict: list[str],
    gem_dict: list[str],
    kp_dict: list[str],
    league_name: str,
    sort_key: str,
    sort_asc: bool,
    rank_offset: int,
    fetched_at: str,
) -> list[dict]:
    """
    Parse a protobuf search response blob into a list of build records.

    rank_offset: added to the 1-based position index for uniqueness tracking.
    """
    outer = _parse_proto(raw)
    inner_bytes = next((v for fn, wt, v in outer if fn == 1 and wt == "bytes"), None)
    if inner_bytes is None:
        _warn("Search response: could not find inner message (field 1)")
        return []
    inner = _parse_proto(inner_bytes)

    names = _column_strings(_column(inner, "name"))
    if not names:
        _warn(f"Search response: no name column in field {COLUMN_FIELD}; the response format may have changed")
        return []
    rows = len(names)
    accounts = _aligned(_column_strings(_column(inner, "account")), rows, "account")
    classes = _aligned(_column_ints(_column(inner, "class")), rows, "class")
    levels = _aligned(_column_ints(_column(inner, "level")), rows, "level")
    skills = _aligned(_column_lists(_column(inner, "skills"), gem_dict), rows, "skills")
    keystones = _aligned(_column_lists(_column(inner, "keypassives"), kp_dict), rows, "keypassives")
    dps_column = _column(inner, "dps.skill")
    dps_skills = _aligned(_column_ints(dps_column), rows, "dps.skill") if _column_dictionary(dps_column) == "gem" else []

    records: list[dict] = []
    for i, char_name in enumerate(names):
        if not char_name:
            continue  # skip rows without a character name
        cls_idx = _at(classes, i)
        skill_gems = _at(skills, i) or []
        key_passives = _at(keystones, i) or []
        records.append(
            {
                "character_name": char_name,
                "account_name": _at(accounts, i),
                "class": class_dict[cls_idx] if cls_idx is not None and cls_idx < len(class_dict) else None,
                "level": _at(levels, i),
                "main_skill": _main_skill(_at(dps_skills, i), gem_dict, skill_gems),
                "skill_gems": skill_gems if skill_gems else None,
                "keystones": key_passives if key_passives else None,
                "league": league_name,
                "rank": rank_offset + i + 1,
                "sort_key": f"{sort_key}_{'asc' if sort_asc else 'desc'}",
                "source": "poe.ninja",
                "fetched_at": fetched_at,
            }
        )
    return records


# ---------------------------------------------------------------------------
# DICTIONARY FETCHING
# ---------------------------------------------------------------------------

def _fetch_dictionaries(inner_bytes: bytes, get_binary=None) -> dict[str, list[str]]:
    """
    Fetch the class, gem and keystone dictionaries named in the search response (field 6:
    field 1 = dictionary key, field 2 = hex hash), each at most once. Other dictionaries the
    response lists are not needed and not requested.
    """
    dicts: dict[str, list[str]] = {}
    for fn, wt, value in _parse_proto(inner_bytes):
        if fn != 6 or wt != "bytes":
            continue
        ref = {sfn: sv.decode("utf-8", errors="replace") for sfn, swt, sv in _parse_proto(value) if swt == "bytes"}
        key, hex_hash = ref.get(1), ref.get(2)
        if key not in DICTIONARIES or key in dicts or not hex_hash or not HASH_PATTERN.fullmatch(hex_hash):
            continue
        print(f"  fetching dict: {key!r} ({hex_hash[:12]}…)")
        dicts[key] = _decode_dict_blob((get_binary or _get_binary)(DICT_URL_TMPL.format(hash=hex_hash)))
        print(f"    {len(dicts[key])} entries")
    return dicts


# ---------------------------------------------------------------------------
# MAIN COLLECTION LOGIC
# ---------------------------------------------------------------------------

def _get_league_info(get_json=None) -> tuple[str, str, str]:
    """
    Fetch index-state and return (league_name, snapshot_version, snapshot_name)
    for the current active PoE2 league.
    """
    print(f"Fetching league info: {INDEX_STATE_URL}")
    state = (get_json or _get_json)(INDEX_STATE_URL)

    build_leagues: list[dict] = state.get("buildLeagues", [])
    snapshot_versions: list[dict] = state.get("snapshotVersions", [])

    # Prefer the first league that is marked indexed=True (active)
    active: Optional[dict] = None
    for league in build_leagues:
        if league.get("indexed"):
            active = league
            break
    if active is None and build_leagues:
        active = build_leagues[0]
    if active is None:
        raise RuntimeError("No build leagues found in index-state")

    league_url = active["url"]
    league_name = active["name"]

    # Find snapshot version for this league
    snapshot = next(
        (sv for sv in snapshot_versions if sv["url"] == league_url),
        None,
    )
    if snapshot is None:
        raise RuntimeError(f"No snapshot version found for league url: {league_url!r}")

    version = snapshot["version"]
    snapshot_name = snapshot["snapshotName"]
    print(f"  Active league: {league_name!r} (url={league_url!r})")
    print(f"  Version: {version}")
    print(f"  Snapshot name: {snapshot_name!r}")
    return league_name, version, snapshot_name


def _fetch_one_page(
    version: str,
    snapshot_name: str,
    sort_key: str,
    sort_asc: bool,
    get_binary=None,
) -> bytes:
    """Fetch one search response binary blob."""
    params: dict[str, str] = {
        "overview": snapshot_name,
        "sort": sort_key,
    }
    if sort_asc:
        params["sort-asc"] = "true"
    url = SEARCH_URL_TMPL.format(version=version)
    # Build query string manually to match what the JS client does
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"
    print(f"  GET {full_url}")
    raw = (get_binary or _get_binary)(full_url)
    print(f"    {len(raw)} bytes")
    return raw


def collect_builds(get_json=None, get_binary=None) -> list[dict]:
    """
    Main collection loop.  Cycles through sort keys, collecting up to
    MAX_RECORDS unique character records.
    """
    # Step 1: get league / version info
    league_name, version, snapshot_name = _get_league_info(get_json)
    print()

    # Step 2: fetch one search page to get dictionary hashes, then fetch dicts
    print("Fetching initial search page to discover dictionaries…")
    first_raw = _fetch_one_page(version, snapshot_name, "dps", False, get_binary)

    # Unwrap outer message
    outer = _parse_proto(first_raw)
    inner_bytes = next(
        (v for fn, wt, v in outer if fn == 1 and wt == "bytes"),
        None,
    )
    if inner_bytes is None:
        raise RuntimeError("Could not parse search response (no inner message)")

    print("\nFetching dictionaries…")
    dicts = _fetch_dictionaries(inner_bytes, get_binary)

    class_dict = dicts.get("class", [])
    gem_dict = dicts.get("gem", [])
    kp_dict = dicts.get("keypassive", [])

    if not class_dict:
        _warn("class dictionary is empty — class names will be null")
    if not gem_dict:
        _warn("gem dictionary is empty — skill gem names will be null")
    if not kp_dict:
        _warn("keypassive dictionary is empty — keystones will be null")

    print(
        f"\nDictionaries: class={len(class_dict)} "
        f"gem={len(gem_dict)} keypassive={len(kp_dict)}"
    )
    print()

    # Step 3: parse the first page
    fetched_at = now_iso()
    all_records: list[dict] = []
    seen_chars: set[str] = set()  # (character_name, account_name) dedup

    def _add_records(records: list[dict]) -> int:
        added = 0
        for r in records:
            key = (r["character_name"], r.get("account_name"))
            if key not in seen_chars:
                seen_chars.add(key)
                all_records.append(r)
                added += 1
        return added

    print("Pass 1/1: dps_desc (initial page already fetched)…")
    records = _parse_search_response(
        first_raw, class_dict, gem_dict, kp_dict,
        league_name, "dps", False, 0, fetched_at,
    )
    added = _add_records(records)
    print(f"  +{added} unique records (total={len(all_records)})")

    # Step 4: additional sort passes
    pass_num = 2
    passes = (
        [(k, False) for k in SORT_KEYS[1:]]  # skip dps desc (already done)
        + [(k, True) for k in SORT_KEYS_ASC]
    )
    for sort_key, sort_asc in passes:
        if len(all_records) >= MAX_RECORDS:
            print(f"Reached {MAX_RECORDS} records — stopping.")
            break
        direction = "asc" if sort_asc else "desc"
        print(f"Pass {pass_num}/{1 + len(passes)}: {sort_key}_{direction}…")
        # A failed pass raises: a snapshot built from fewer passes would be smaller and skewed.
        raw = _fetch_one_page(version, snapshot_name, sort_key, sort_asc, get_binary)
        records = _parse_search_response(
            raw, class_dict, gem_dict, kp_dict,
            league_name, sort_key, sort_asc,
            len(all_records), fetched_at,
        )
        added = _add_records(records)
        print(f"  +{added} unique records (total={len(all_records)})")
        pass_num += 1

    return all_records


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def _validate(records: list[dict]) -> list[dict]:
    valid: list[dict] = []
    for r in records:
        if not r.get("character_name"):
            _warn(f"Dropping record with no character_name (rank {r.get('rank')})")
            continue
        valid.append(r)
    return valid


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------

def _public(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in PRIVATE_FIELDS}


def _write_jsonl(records: list[dict], path: Path) -> int:
    return write_jsonl(path, (_public(r) for r in records))   # atomic: an interrupted run keeps the old file


def _print_summary(records: list[dict]) -> None:
    print(f"\n{'=' * 60}")
    print(f"Total records collected : {len(records)}")

    # Class distribution
    class_counts: dict[str, int] = {}
    for r in records:
        cls = r.get("class") or "Unknown"
        class_counts[cls] = class_counts.get(cls, 0) + 1

    if class_counts:
        print("\nBuilds by class (ascendancy):")
        for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
            bar = "#" * min(count, 40)
            print(f"  {cls:<28} {count:>5}  {bar}")

    # Field coverage
    has_main = sum(1 for r in records if r.get("main_skill"))
    has_gems = sum(1 for r in records if r.get("skill_gems"))
    has_cls = sum(1 for r in records if r.get("class"))
    has_lvl = sum(1 for r in records if r.get("level") is not None)
    has_ks = sum(1 for r in records if r.get("keystones"))
    n = len(records)
    print(f"\nField coverage ({n} records):")
    print(f"  class       : {has_cls}/{n}")
    print(f"  level       : {has_lvl}/{n}")
    print(f"  main_skill  : {has_main}/{n}")
    print(f"  skill_gems  : {has_gems}/{n}")
    print(f"  keystones   : {has_ks}/{n}")

    print("=" * 60)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main() -> None:
    print("poe.ninja PoE2 build fetcher")
    print(f"Output : {OUTPUT_PATH}")
    print()

    records = collect_builds()
    records = _validate(records)

    if not records:
        print("No records collected.", file=sys.stderr)
        sys.exit(1)

    saved = _write_jsonl(records, OUTPUT_PATH)
    print(f"\nsaved={saved} -> {OUTPUT_PATH}")

    _print_summary(records)


if __name__ == "__main__":
    main()
