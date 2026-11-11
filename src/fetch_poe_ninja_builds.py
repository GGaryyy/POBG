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
  field 5 (bytes)  -> value-list column (repeated, one per requested column):
      field 1 (bytes)   -> column name
      field 2 (bytes)   -> per-row value cell (repeated, 100 items):
          string cols  -> field 1 (bytes) = UTF-8 string
          integer cols -> field 2 (varint) = integer value
          list cols    -> field 3 (bytes) = packed varints (dict indices)
  field 6 (bytes)  -> dictionary reference (repeated):
      field 1 (bytes)   -> dimension key
      field 2 (bytes)   -> hex SHA-1 hash of the dictionary blob

dictionary blob:
  field 1 (bytes)   -> dimension name
  field 2 (bytes)   -> value string (repeated, order = index)

Output schema (per record)
--------------------------
Character and account names are used in memory to de-duplicate the sort passes and are
never written to disk (PRIVATE_FIELDS).
{
  "class":          str | null,   # ascendancy name (e.g. "Stormweaver")
  "level":          int | null,
  "main_skill":     str | null,   # first entry in skills list (primary active)
  "skill_gems":     [str],        # all gems from the 'skills' column
  "keystones":      [str],        # passive keystones from 'keypassives' column
  "league":         str,
  "rank":           int,          # 1-based position in this sort pass
  "source":         "poe.ninja",
  "fetched_at":     str           # ISO-8601 UTC
}

Output: data/community_builds/poe_ninja_builds.jsonl
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from src.scrapers.common import USER_AGENT

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
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result, pos


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
    """
    Parse a poe.ninja dictionary blob into a list of string values.
    field 1 = dimension name (skipped here)
    field 2 = value string (repeated, position = index)
    """
    values: list[str] = []
    fields = _parse_proto(raw)
    for fn, wt, v in fields:
        if fn == 2 and wt == "bytes":
            assert isinstance(v, bytes)
            try:
                values.append(v.decode("utf-8"))
            except UnicodeDecodeError:
                values.append("")
    return values


def _extract_col(f5_items: list[bytes], col_name: str) -> list[bytes]:
    """Return the list of per-row value cells for the named column."""
    for item in f5_items:
        sub = _parse_proto(item)
        name_val = next(
            (v for fn, wt, v in sub if fn == 1 and wt == "bytes"),
            None,
        )
        if name_val is None:
            continue
        try:
            if name_val.decode("utf-8") == col_name:
                return [v for fn, wt, v in sub if fn == 2 and wt == "bytes"]
        except UnicodeDecodeError:
            continue
    return []


def _cell_string(cell: bytes) -> Optional[str]:
    """Extract UTF-8 string from sub-field 1 of a cell."""
    sub = _parse_proto(cell)
    for fn, wt, v in sub:
        if fn == 1 and wt == "bytes":
            assert isinstance(v, bytes)
            try:
                return v.decode("utf-8")
            except UnicodeDecodeError:
                return v.decode("utf-8", errors="replace")
    return None


def _cell_int(cell: bytes, field_num: int = 2) -> Optional[int]:
    """Extract varint from the given sub-field of a cell."""
    sub = _parse_proto(cell)
    for fn, wt, v in sub:
        if fn == field_num and wt == "varint":
            assert isinstance(v, int)
            return v
    return None


def _cell_packed_indices(cell: bytes, dictionary: list[str]) -> list[str]:
    """
    Extract a list of strings by decoding packed varints from sub-field 3
    as indices into the given dictionary.
    """
    sub = _parse_proto(cell)
    packed = next(
        (v for fn, wt, v in sub if fn == 3 and wt == "bytes"),
        b"",
    )
    assert isinstance(packed, bytes)
    indices: list[int] = []
    p = 0
    while p < len(packed):
        idx, p = _read_varint(packed, p)
        indices.append(idx)
    result: list[str] = []
    for idx in indices:
        if idx < len(dictionary):
            name = dictionary[idx]
            if name:
                result.append(name)
    return result


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
    # Outer wrapper: field 1 = nested message
    outer = _parse_proto(raw)
    inner_bytes = next(
        (v for fn, wt, v in outer if fn == 1 and wt == "bytes"),
        None,
    )
    if inner_bytes is None:
        _warn("Search response: could not find inner message (field 1)")
        return []

    assert isinstance(inner_bytes, bytes)
    inner = _parse_proto(inner_bytes)

    # Field 5 = value-list columns
    f5_items: list[bytes] = [v for fn, wt, v in inner if fn == 5 and wt == "bytes"]  # type: ignore[misc]

    if not f5_items:
        _warn("Search response: no field-5 columns found")
        return []

    # Extract columns
    name_col = _extract_col(f5_items, "name")
    account_col = _extract_col(f5_items, "account")
    class_col = _extract_col(f5_items, "class")
    level_col = _extract_col(f5_items, "level")
    skills_col = _extract_col(f5_items, "skills")
    kp_col = _extract_col(f5_items, "keypassives")

    row_count = max(
        len(name_col),
        len(class_col),
        len(level_col),
    )
    if row_count == 0:
        _warn("Search response: no rows found")
        return []

    records: list[dict] = []
    for i in range(row_count):
        # Character name
        char_name: Optional[str] = None
        if i < len(name_col):
            char_name = _cell_string(name_col[i])

        if not char_name:
            continue  # skip rows without a character name

        # Account name
        acct_name: Optional[str] = None
        if i < len(account_col):
            acct_name = _cell_string(account_col[i])

        # Class (ascendancy) — field 2 = varint index; missing sub-fields = index 0
        cls_name: Optional[str] = None
        if i < len(class_col):
            cell = class_col[i]
            sub = _parse_proto(cell)
            int_fields = [v for fn, wt, v in sub if fn == 2 and wt == "varint"]
            cls_idx = int_fields[0] if int_fields else 0
            if cls_idx < len(class_dict):
                cls_name = class_dict[cls_idx]

        # Level
        level: Optional[int] = None
        if i < len(level_col):
            level = _cell_int(level_col[i], field_num=2)

        # Skill gems
        skill_gems: list[str] = []
        if i < len(skills_col):
            skill_gems = _cell_packed_indices(skills_col[i], gem_dict)

        # Keystones
        keystones: list[str] = []
        if i < len(kp_col):
            keystones = _cell_packed_indices(kp_col[i], kp_dict)

        records.append(
            {
                "character_name": char_name,
                "account_name": acct_name,
                "class": cls_name,
                "level": level,
                "main_skill": skill_gems[0] if skill_gems else None,
                "skill_gems": skill_gems if skill_gems else None,
                "keystones": keystones if keystones else None,
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

def _fetch_dictionaries(inner_bytes: bytes) -> dict[str, list[str]]:
    """
    Parse dictionary hashes from the search response inner message and
    fetch each dictionary.

    Returns mapping: dim_key -> list[str] (index = value).
    """
    inner = _parse_proto(inner_bytes)
    # Field 6 = dictionary reference: field 1 = dim key, field 2 = hex hash
    dicts: dict[str, list[str]] = {}
    for fn, wt, v in inner:
        if fn != 6 or wt != "bytes":
            continue
        assert isinstance(v, bytes)
        sub = _parse_proto(v)
        dim_key: Optional[str] = None
        hex_hash: Optional[str] = None
        for sfn, swt, sv in sub:
            if sfn == 1 and swt == "bytes":
                assert isinstance(sv, bytes)
                try:
                    dim_key = sv.decode("utf-8")
                except UnicodeDecodeError:
                    pass
            elif sfn == 2 and swt == "bytes":
                assert isinstance(sv, bytes)
                try:
                    hex_hash = sv.decode("utf-8")
                except UnicodeDecodeError:
                    pass
        if dim_key and hex_hash:
            url = DICT_URL_TMPL.format(hash=hex_hash)
            print(f"  fetching dict: {dim_key!r} ({hex_hash[:12]}…)")
            try:
                raw = _get_binary(url)
                dicts[dim_key] = _decode_dict_blob(raw)
                print(f"    {len(dicts[dim_key])} entries")
            except requests.HTTPError as exc:
                _warn(f"dict fetch failed: {dim_key}: HTTP {exc.response.status_code}")
            except requests.RequestException as exc:
                _warn(f"dict fetch failed: {dim_key}: {exc}")
    return dicts


# ---------------------------------------------------------------------------
# MAIN COLLECTION LOGIC
# ---------------------------------------------------------------------------

def _get_league_info() -> tuple[str, str, str]:
    """
    Fetch index-state and return (league_name, snapshot_version, snapshot_name)
    for the current active PoE2 league.
    """
    print(f"Fetching league info: {INDEX_STATE_URL}")
    state = _get_json(INDEX_STATE_URL)

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
    raw = _get_binary(full_url)
    print(f"    {len(raw)} bytes")
    return raw


def collect_builds() -> list[dict]:
    """
    Main collection loop.  Cycles through sort keys, collecting up to
    MAX_RECORDS unique character records.
    """
    # Step 1: get league / version info
    league_name, version, snapshot_name = _get_league_info()
    print()

    # Step 2: fetch one search page to get dictionary hashes, then fetch dicts
    print("Fetching initial search page to discover dictionaries…")
    first_raw = _fetch_one_page(version, snapshot_name, "dps", False)

    # Unwrap outer message
    outer = _parse_proto(first_raw)
    inner_bytes = next(
        (v for fn, wt, v in outer if fn == 1 and wt == "bytes"),
        None,
    )
    if inner_bytes is None:
        raise RuntimeError("Could not parse search response (no inner message)")

    print("\nFetching dictionaries…")
    dicts = _fetch_dictionaries(inner_bytes)

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
        try:
            raw = _fetch_one_page(version, snapshot_name, sort_key, sort_asc)
            records = _parse_search_response(
                raw, class_dict, gem_dict, kp_dict,
                league_name, sort_key, sort_asc,
                len(all_records), fetched_at,
            )
            added = _add_records(records)
            print(f"  +{added} unique records (total={len(all_records)})")
        except requests.HTTPError as exc:
            _warn(f"Sort pass {sort_key}/{direction}: HTTP {exc.response.status_code}")
        except requests.RequestException as exc:
            _warn(f"Sort pass {sort_key}/{direction}: {exc}")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(_public(r), ensure_ascii=False) + "\n")
    return len(records)


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

    # Sample record
    if records:
        print("\nSample record (first):")
        sample_json = json.dumps(_public(records[0]), ensure_ascii=True, indent=2)
        sys.stdout.buffer.write((sample_json + "\n").encode("utf-8", errors="replace"))

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
