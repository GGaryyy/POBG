"""Synthetic poe.ninja responses in the layout the ladder fetcher reads (no real character data)."""

from __future__ import annotations

import struct

CLASSES = ["Blood Mage", "Deadeye", "Titan"]
GEMS = ["Arc", "Comet", "Fireball", "Leap Slam", "Spark"]
KEYSTONES = ["Blood Magic", "Mind Over Matter", "Resolute Technique"]
LEAGUE = "Test League"
INDEX_STATE = {"buildLeagues": [{"url": "test", "name": LEAGUE, "indexed": True}],
               "snapshotVersions": [{"url": "test", "version": "v1", "snapshotName": "test-snap"}]}
DICT_HASHES = {"class": "c1a55", "gem": "9e3", "keypassive": "4e9"}
DICTIONARIES = {"class": CLASSES, "gem": GEMS, "keypassive": KEYSTONES}


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(number: int, payload: bytes | str) -> bytes:
    payload = payload.encode("utf-8") if isinstance(payload, str) else payload
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def packed(values: list[int]) -> bytes:
    return b"".join(varint(v) for v in values)


def ndic(strings: list[str]) -> bytes:
    """A dictionary in the "NDIC" container."""
    encoded = [s.encode("utf-8") for s in strings]
    blocks = (len(strings) + 15) // 16
    header = (b"NDIC" + struct.pack("<II", 2, 0) + struct.pack("<I", len(strings)) + b"\x00" * 8
              + struct.pack("<III", 16, blocks, len(strings)))
    table = b"".join(struct.pack("<II", 0, block * 16) for block in range(blocks))
    return header + table + b"".join(varint(len(e)) for e in encoded) + b"".join(encoded)


def column(key: str, *, strings=None, ints=None, lists=None, dictionary=None) -> bytes:
    body = field(1, key) + field(2, key.split(".")[0])
    rows = strings if strings is not None else ints if ints is not None else lists
    if strings is not None:
        body += b"".join(field(7, s) for s in strings)
    if ints is not None:
        body += field(6, packed(ints))
    if lists is not None:
        body += b"".join(field(9, field(1, packed(row))) for row in lists)
    if dictionary:
        body += field(11, dictionary)
    return body + varint(13 << 3) + varint(len(rows))


def characters(count: int, prefix: str = "SecretHero") -> list[dict]:
    """Rows that cover every class, a main skill that is not the first skill, and an empty keystone list."""
    return [{"name": f"{prefix}{i}", "account": f"SecretAccount{i}", "class": i % len(CLASSES), "level": 80 + i % 20,
             "skills": [(i + 1) % len(GEMS), i % len(GEMS)], "dps_skill": i % len(GEMS),
             "keystones": [i % len(KEYSTONES)] if i % 4 else []} for i in range(count)]


def search_page(rows: list[dict], *, with_dps_skill: bool = True, with_dictionaries: bool = True) -> bytes:
    columns = [
        column("name", strings=[r["name"] for r in rows]),
        column("account", strings=[r["account"] for r in rows]),
        column("class", ints=[r["class"] for r in rows], dictionary="class"),
        column("level", ints=[r["level"] for r in rows]),
        column("skills", lists=[r["skills"] for r in rows], dictionary="gem"),
        column("keypassives", lists=[r["keystones"] for r in rows], dictionary="keypassive"),
    ]
    if with_dps_skill:
        columns.append(column("dps.skill", ints=[r["dps_skill"] for r in rows], dictionary="gem"))
    inner = b"".join(field(12, c) for c in columns)
    if with_dictionaries:
        inner += b"".join(field(6, field(1, key) + field(2, hash_)) for key, hash_ in DICT_HASHES.items())
        # what the real site also lists: dictionaries the fetcher does not need, a repeat, and a hash that is not hex
        inner += field(6, field(1, "item") + field(2, "1234")) + field(6, field(1, "gem") + field(2, DICT_HASHES["gem"]))
        inner += field(6, field(1, "anointed") + field(2, "../../etc"))
    return field(1, inner)


class FakeNinja:
    """The three endpoints, a request log, and switches for the failures the fetcher must survive."""

    def __init__(self, rows: list[dict] | None = None, *, dictionaries: dict | None = None, index_state: dict | None = None):
        self.rows = characters(120) if rows is None else rows
        self.dictionaries = DICTIONARIES if dictionaries is None else dictionaries
        self.index_state = INDEX_STATE if index_state is None else index_state
        self.calls: list[str] = []

    def get_json(self, url: str) -> dict:
        self.calls.append(url)
        return self.index_state

    def get_binary(self, url: str) -> bytes:
        self.calls.append(url)
        if "/dictionary/" in url:
            key = next(k for k, h in DICT_HASHES.items() if url.endswith(h))
            return ndic(self.dictionaries.get(key, []))
        return search_page(self.rows)
