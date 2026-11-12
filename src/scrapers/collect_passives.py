"""
collect_passives.py — Build the passive tree from PoB2 tree.json joined with poe2db listings.

    python -m src.scrapers.collect_passives            # downloads PoB2 tree + listing pages (cached)
    python -m src.scrapers.collect_passives --offline  # cache only

Structure (every node, connections, flags, class starts, ascendancies, positions) comes from
PathOfBuilding-PoE2 tree.json. poe2db supplies what we cite: slug / URLs, English and Traditional
Chinese names and stat text for keystones and notables, keyword links, and the timeless-jewel
nodes that are not part of the tree. The data file behind poe2db's tree viewer supplies the
Traditional Chinese name and stat lines of every other node, and the class / ascendancy names.
Replaces fetch_passive_tree.py + patch_ascendancy_nodes.py.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

import requests

from src.catalog.spec import Spec, load_spec
from src.scrapers.common import atomic_write_text, cached_fetch, fetch_html, now_iso, write_jsonl
from src.scrapers.passive_listing import PASSIVE_SOURCES, PassiveCard, parse_passive_listing
from src.scrapers.passive_tree_data import align_wrapped, class_names, node_texts

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PAGE_CACHE_DIR = BASE_DIR / "output" / "cache" / "pages"
POB2_CACHE_DIR = BASE_DIR / "output" / "cache" / "pob2"
TREE_DATA_CACHE_DIR = BASE_DIR / "output" / "cache" / "poe2db_tree"
ZH_FROM_PAGE = "poe2db_page"
ZH_FROM_TREE_DATA = "poe2db_tree_data"
LANGS = ("en", "zh-tw")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
NESTED_TABLE = re.compile(r"\{[^{}]*\}")                        # a table inside a quest (e.g. Options)
QUEST_FIELD = re.compile(r'\["(\w+)"\]\s*=\s*"?([^",\n]*)"?')
CRUEL_OFFSET = 3                                                  # Cruel acts follow the three normal ones

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# ERRORS
# ---------------------------------------------------------------------------


class PassiveBuildError(Exception):
    """Raised when the build must not overwrite the existing passive tree files."""


# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------


def load_pob2_tree(spec: Spec, *, fetch: Fetcher, cache_dir: Path = POB2_CACHE_DIR, offline: bool = False) -> dict:
    source = spec.source("pob2_tree")
    version = source["version"]
    url = source["url"].format(version=version)
    text = cached_fetch(url, cache_dir / f"tree_{version}.json", fetch, offline)
    if text is None:
        raise PassiveBuildError(f"PoB2 tree {version} is not cached and --offline was given")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PassiveBuildError(f"PoB2 tree {version} is not valid JSON: {exc}") from exc


def load_quest_acts(spec: Spec, *, fetch: Fetcher, cache_dir: Path = POB2_CACHE_DIR, offline: bool = False) -> list[dict]:
    """PoB's act table for its automatic character level, from its QuestRewards.lua; [] when the
    file is not available offline or does not parse (the export then falls back to level 1)."""
    source = spec.source("pob2_tree")
    url = source.get("quest_rewards_url")
    if not url:
        return []
    try:   # the level table is an extra: without it the tree is still collected
        text = cached_fetch(url, cache_dir / f"QuestRewards_{source['version']}.lua", fetch, offline)
    except requests.RequestException as exc:
        print(f"[WARN] PoB quest rewards not fetched ({type(exc).__name__}); exported codes will say level 1",
              file=sys.stderr)
        return []
    return quest_acts(text) if text else []


def quest_blocks(text: str) -> list[str]:
    """The top-level quest tables of QuestRewards.lua, each without the tables nested in it."""
    blocks, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
            if depth == 2:
                start = index + 1
        elif char == "}":
            if depth == 2:
                block = text[start:index]
                while NESTED_TABLE.search(block):
                    block = NESTED_TABLE.sub("", block)
                blocks.append(block)
            depth -= 1
    return blocks


def quest_acts(text: str) -> list[dict]:
    """[{"level", "quest_points"}] per act, built the way PoB's Build.lua builds `self.acts`:
    the first act is level 1 with no points; each quest with questPoints adds to its act
    (Cruel acts come after the three normal ones), and a new act starts at the quest's area
    level with the points so far."""
    acts = [{"level": 1, "quest_points": 0}]
    for block in quest_blocks(text):
        fields = dict(QUEST_FIELD.findall(block))
        if "questPoints" not in fields:
            continue
        try:
            act = int(fields["Act"]) + (CRUEL_OFFSET if fields.get("Type") == "Cruel" else 0) + 1
            points, level = int(fields["questPoints"]), int(fields["AreaLevel"])
        except (KeyError, ValueError):
            return []
        if act == len(acts) + 1:
            acts.append({"level": level, "quest_points": points + acts[-1]["quest_points"]})
        elif 1 <= act <= len(acts):
            acts[act - 1]["quest_points"] += points
            acts[act - 1]["level"] = max(acts[act - 1]["level"], level)
        else:
            return []          # a gap PoB itself would fail on
    return acts if len(acts) > 1 else []


def load_tree_data(spec: Spec, *, fetch: Fetcher, cache_dir: Path = TREE_DATA_CACHE_DIR, offline: bool = False,
                   version: str | None = None) -> dict:
    """poe2db's tree viewer data in English and Traditional Chinese: {"en", "zh-tw", "version", "urls"}."""
    source = spec.source("passive_tree_data")
    version = version or source["version"]
    out: dict = {"version": version, "urls": {}}
    for lang in LANGS:
        url = source["url"].format(version=version, lang=spec.raw["languages"][lang])
        text = cached_fetch(url, cache_dir / f"data_{version}_{lang}.json", fetch, offline)
        if text is None:
            raise PassiveBuildError(f"poe2db tree data {version}/{lang} is not cached and --offline was given; "
                                    "run python -m src.scrapers.collect_passives once without --offline")
        try:
            tree = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PassiveBuildError(f"poe2db tree data {version}/{lang} is not valid JSON: {exc}") from exc
        found = len(node_texts(tree)) if isinstance(tree, dict) else 0
        if found < source["expect_min"]["nodes"]:
            raise PassiveBuildError(f"poe2db tree data {version}/{lang} has {found} nodes "
                                    f"< {source['expect_min']['nodes']}")
        out[lang], out["urls"][lang] = tree, url
    return out


def load_cards(spec: Spec, *, fetch: Fetcher, cache_dir: Path = PAGE_CACHE_DIR,
               offline: bool = False) -> dict[str, dict[str, PassiveCard]]:
    """{lang: {slug: card}} from the Keystone and Notable listing pages."""
    out: dict[str, dict[str, PassiveCard]] = {}
    for lang in LANGS:
        cards: dict[str, PassiveCard] = {}
        for source in PASSIVE_SOURCES:
            page = spec.source(source)["slug"]
            html = cached_fetch(spec.resolve_url(page, lang), cache_dir / f"{lang}_{page}.html", fetch, offline)
            if html is None:
                raise PassiveBuildError(f"listing page {lang}/{page} is not cached and --offline was given")
            for card in parse_passive_listing(html, spec, source, lang):
                cards.setdefault(card.slug, card)
        out[lang] = cards
    return out


# ---------------------------------------------------------------------------
# STRUCTURE FROM PoB2
# ---------------------------------------------------------------------------


def node_type(node: dict) -> str:
    if "classesStart" in node:
        return "ClassStart"
    if node.get("ascendancyName"):
        return "Ascendancy"
    if node.get("isKeystone"):
        return "Keystone"
    if node.get("isNotable"):
        return "Notable"
    if node.get("isJewelSocket"):
        return "JewelSocket"
    if node.get("isAttribute"):
        return "Attribute"
    return "Small"


def node_position(tree: dict, node: dict) -> dict | None:
    """PoB2 group centre plus orbit offset, in PoB2 tree units.

    PoB2 group ids are 1-based: node["group"] == g refers to tree["groups"][g - 1].
    """
    groups = tree["groups"]
    group_id = node.get("group")
    if not isinstance(group_id, int) or not 1 <= group_id <= len(groups) or groups[group_id - 1] is None:
        return None
    group = groups[group_id - 1]
    constants = tree["constants"]
    orbit = node.get("orbit", 0)
    radius = constants["orbitRadii"][orbit]
    angle = constants["orbitAnglesByOrbit"][orbit][node.get("orbitIndex", 0)]
    return {"x": round(group["x"] + radius * math.sin(angle), 2),
            "y": round(group["y"] - radius * math.cos(angle), 2)}


def join_wrapped(lines: list[str]) -> list[str]:
    """Re-join stat lines the game wraps mid-sentence (continuations start lower-case)."""
    out: list[str] = []
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        if out and line[0].islower():
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def tree_nodes(tree: dict, version: str) -> dict[str, dict]:
    class_names = {c["name"] for c in tree["classes"]}
    nodes: dict[str, dict] = {}
    for raw in tree["nodes"].values():
        if raw.get("isOnlyImage") or "skill" not in raw:
            continue
        nodes[str(raw["skill"])] = {
            "id": str(raw["skill"]),
            "name": raw.get("name") or "",
            "type": node_type(raw),
            "stats": join_wrapped([s.replace("\n", " ") for s in raw.get("stats", [])]),
            "ascendancy": raw.get("ascendancyName"),
            "class_start": [c for c in raw.get("classesStart", []) if c in class_names],
            "is_ascendancy_start": bool(raw.get("isAscendancyStart")),
            "is_notable": bool(raw.get("isNotable")),
            # allocated without spending a point (PoB's CountAllocNodes skips these)
            "no_point": bool(raw.get("isFreeAllocate")
                             or (raw.get("isMultipleChoiceOption") and raw.get("ascendancyName"))),
            "position": node_position(tree, raw),
            "neighbors": [],
            "slug": None,
            "url_en": None,
            "url_zh_tw": None,
            "name_zh_tw": None,
            "stats_zh_tw": [],
            "zh_source": None,
            "unlock_ascendancy": (raw.get("unlockConstraint") or {}).get("ascendancy"),
            "keyword_slugs": [],
            "timeless": False,
            "stats_source": "pob2",
            "pob2_tree_version": version,
        }
    return nodes


def tree_edges(tree: dict, nodes: dict[str, dict]) -> tuple[list[dict], int]:
    """Undirected, de-duplicated edges between kept nodes, plus the number of connections
    dropped because an endpoint was removed (masteries) or unknown."""
    seen: set[frozenset] = set()
    edges: list[dict] = []
    dropped = 0
    for key, raw in tree["nodes"].items():
        src = str(raw.get("skill", key))
        if src not in nodes:
            continue
        for conn in raw.get("connections", []):
            dst = str(conn["id"])
            pair = frozenset((src, dst))
            if dst not in nodes:
                dropped += 1
                continue
            if src == dst or pair in seen:
                continue
            seen.add(pair)
            edges.append({"from": src, "to": dst, "kind": _edge_kind(nodes[src], nodes[dst])})
    return edges, dropped


def _edge_kind(a: dict, b: dict) -> str:
    if a["ascendancy"] and a["ascendancy"] == b["ascendancy"]:
        return "ascendancy"
    if a["ascendancy"] or b["ascendancy"]:
        return "bridge"
    return "tree"


# ---------------------------------------------------------------------------
# JOIN WITH poe2db
# ---------------------------------------------------------------------------


def attach_tree_text(nodes: dict[str, dict], tree_data: dict) -> dict:
    """Give every tree node its Traditional Chinese name and stat lines from poe2db's tree data.

    Runs before attach_cards, so a listing card (the page we cite) still wins. A node is joined by
    id and only when the file agrees with us on the English name; Chinese stat lines are kept
    only when they line up one-to-one with our English lines.
    """
    en_texts, zh_texts = node_texts(tree_data["en"]), node_texts(tree_data["zh-tw"])
    missing = mismatch = unaligned = 0
    for node in nodes.values():
        en, zh = en_texts.get(node["id"]), zh_texts.get(node["id"])
        if en is None or zh is None:
            missing += 1
            continue
        if _fold(en["name"]) != _fold(node["name"]):
            mismatch += 1
            continue
        if zh["name"]:
            node["name_zh_tw"], node["zh_source"] = zh["name"], ZH_FROM_TREE_DATA
        zh_lines = align_wrapped(en["stats"], zh["stats"])
        if zh_lines and len(zh_lines) == len(node["stats"]):
            node["stats_zh_tw"], node["zh_source"] = zh_lines, ZH_FROM_TREE_DATA
        elif node["stats"]:
            unaligned += 1
    return {"tree_text_missing": missing, "tree_text_name_mismatch": mismatch, "stat_lines_unaligned": unaligned}


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def pob_class_ids(tree: dict) -> dict[str, dict]:
    """PoB's own ids by English class name: the class integerId and each ascendancy's internalId.
    A Path of Building build code names the class and ascendancy by these."""
    out: dict[str, dict] = {}
    for cls in tree.get("classes") or []:
        if cls.get("name") and isinstance(cls.get("integerId"), int):
            base = {key: cls.get(f"base_{key}") for key in ("str", "dex", "int")}
            out[cls["name"]] = {"pob_id": cls["integerId"],
                                **({"base": base} if all(isinstance(v, int) for v in base.values()) else {}),
                                "ascendancies": {a["name"]: a["internalId"] for a in cls.get("ascendancies") or []
                                                 if a.get("name") and a.get("internalId")}}
    return out


def classes_doc(tree_data: dict, nodes: list[dict], fetched_at: str, pob_ids: dict | None = None,
                pob_acts: list[dict] | None = None) -> dict:
    """Classes that start somewhere on our tree, with their ascendancies, in both languages, and
    PoB's ids for them (`pob_id`) where the PoB2 tree has them. `pob_level_acts` is PoB's act
    table for its automatic character level."""
    playable = {c for n in nodes for c in n["class_start"]}
    classes = [c for c in class_names(tree_data["en"], tree_data["zh-tw"]) if c["name"] in playable]
    for cls in classes:
        ids = (pob_ids or {}).get(cls["name"])
        if ids:
            cls["pob_id"] = ids["pob_id"]
            if ids.get("base"):
                cls["base_attributes"] = ids["base"]
            for asc in cls["ascendancies"]:
                if asc["name"] in ids["ascendancies"]:
                    asc["pob_id"] = ids["ascendancies"][asc["name"]]
    points = tree_data["en"].get("points") or {}
    doc = {"version": tree_data["version"], "source_url": tree_data["urls"]["zh-tw"],
           "fetched_at": fetched_at,
           "points": {"passive": points.get("totalPoints"), "ascendancy": points.get("ascendancyPoints")},
           "classes": classes}
    if pob_acts is not None:
        doc["pob_level_acts"] = pob_acts
    return doc


def attach_cards(nodes: dict[str, dict], cards: dict[str, dict[str, PassiveCard]], spec: Spec) -> dict:
    """Give named tree nodes their poe2db slug, URLs, cited stats, zh-TW text and keywords.

    Returns aggregate join statistics. Timeless-jewel cards become extra nodes (id = slug).
    """
    en_cards, zh_cards = cards["en"], cards["zh-tw"]
    by_name: dict[str, list[dict]] = {}
    for node in nodes.values():
        if node["type"] == "Keystone" or node["is_notable"]:  # poe2db lists ascendancy notables too
            by_name.setdefault(node["name"], []).append(node)
    matched = unmatched = ambiguous = 0
    for card in en_cards.values():
        if card.timeless:
            nodes[card.slug] = _timeless_node(card, zh_cards.get(card.slug), spec)
            continue
        targets = [n for n in by_name.get(card.name, []) if not n["slug"]]
        if not targets:
            unmatched += 1
            continue
        matched += 1
        if len(targets) > 1:
            ambiguous += 1
        _apply_card(_best_match(targets, card), card, zh_cards.get(card.slug), spec)
    named = sum(len(v) for v in by_name.values())
    return {"cards_matched": matched, "cards_unmatched": unmatched, "ambiguous_names": ambiguous,
            "named_tree_nodes": named,
            "named_with_page": sum(1 for v in by_name.values() for n in v if n["slug"])}


def _best_match(targets: list[dict], card: PassiveCard) -> dict:
    """Among same-named tree nodes, the one whose PoB2 stats look most like the card's."""
    card_text = " ".join(card.stats).lower()
    card_numbers = sorted(_NUMBER_RE.findall(card_text))

    def score(node: dict) -> tuple[int, int]:
        text = " ".join(node["stats"]).lower()
        same_numbers = int(sorted(_NUMBER_RE.findall(text)) == card_numbers)
        shared_words = len(set(text.split()) & set(card_text.split()))
        return same_numbers, shared_words

    return max(targets, key=score)


def _apply_card(node: dict, card: PassiveCard, zh: PassiveCard | None, spec: Spec) -> None:
    node["slug"] = card.slug
    node["url_en"] = spec.resolve_url(card.slug, "en")
    node["url_zh_tw"] = spec.resolve_url(card.slug, "zh-tw")
    node["name"] = card.name
    if card.stats:
        node["stats"] = join_wrapped(card.stats)
        node["stats_source"] = "poe2db"
    node["keyword_slugs"] = [k.slug for k in card.keywords]
    if zh is not None:
        node["name_zh_tw"] = zh.name
        node["stats_zh_tw"] = zh.stats
        node["zh_source"] = ZH_FROM_PAGE
    elif len(node.get("stats_zh_tw") or []) != len(node["stats"]):
        node["stats_zh_tw"] = []  # tree-data lines no longer line up with the card's English lines


def _timeless_node(card: PassiveCard, zh: PassiveCard | None, spec: Spec) -> dict:
    node = {
        "id": card.slug, "name": card.name, "type": card.node_type, "stats": [], "ascendancy": None,
        "class_start": [], "is_ascendancy_start": False, "is_notable": card.node_type == "Notable",
        "position": None, "neighbors": [], "slug": None, "url_en": None, "url_zh_tw": None,
        "name_zh_tw": None, "stats_zh_tw": [], "zh_source": None, "unlock_ascendancy": None,
        "keyword_slugs": [], "timeless": True,
        "stats_source": "poe2db", "pob2_tree_version": None,
    }
    _apply_card(node, card, zh, spec)
    return node


# ---------------------------------------------------------------------------
# VALIDATION / BUILD
# ---------------------------------------------------------------------------


def validate(nodes: dict[str, dict], edges: list[dict], join: dict, spec: Spec) -> dict:
    expect = spec.source("pob2_tree")["expect_min"]
    regular = [n for n in nodes.values() if not n["timeless"]]
    counts = {
        "nodes": len(nodes),
        "keystones": sum(1 for n in regular if n["type"] == "Keystone"),
        "notables": sum(1 for n in regular if n["is_notable"]),
        "class_starts": sum(1 for n in regular if n["type"] == "ClassStart"),
        "ascendancy_starts": sum(1 for n in regular if n["is_ascendancy_start"]),
    }
    ratio = join["cards_matched"] / max(1, join["cards_matched"] + join["cards_unmatched"])
    problems = [f"{k}={v} < {expect[k]}" for k, v in counts.items() if v < expect[k]]
    if ratio < expect["poe2db_name_match_ratio"]:
        problems.append(f"poe2db name match ratio {ratio:.3f} < {expect['poe2db_name_match_ratio']}")
    dangling = sum(1 for e in edges if e["from"] not in nodes or e["to"] not in nodes)
    if dangling:
        problems.append(f"{dangling} dangling edges")
    named = [n for n in regular if n["name"]]
    zh_named = sum(1 for n in named if n["name_zh_tw"])
    zh_ratio = zh_named / max(1, len(named))
    zh_expect = spec.source("passive_tree_data")["expect_min"]["zh_name_ratio"]
    if zh_ratio < zh_expect:
        problems.append(f"zh-TW name ratio {zh_ratio:.3f} < {zh_expect}")
    if problems:
        raise PassiveBuildError("passive tree validation failed: " + "; ".join(problems))
    return {**counts, "poe2db_name_match_ratio": round(ratio, 4), "zh_names": zh_named,
            "zh_name_ratio": round(zh_ratio, 4),
            "zh_stat_nodes": sum(1 for n in regular if n["stats"] and len(n["stats_zh_tw"]) == len(n["stats"])),
            "nodes_with_stats": sum(1 for n in regular if n["stats"])}


def build(spec: Spec, *, fetch: Fetcher, offline: bool = False,
          pob2_cache: Path = POB2_CACHE_DIR, page_cache: Path = PAGE_CACHE_DIR,
          tree_data_cache: Path = TREE_DATA_CACHE_DIR, tree_data: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    version = spec.source("pob2_tree")["version"]
    tree = load_pob2_tree(spec, fetch=fetch, cache_dir=pob2_cache, offline=offline)
    cards = load_cards(spec, fetch=fetch, cache_dir=page_cache, offline=offline)
    if tree_data is None:
        tree_data = load_tree_data(spec, fetch=fetch, cache_dir=tree_data_cache, offline=offline)
    nodes = tree_nodes(tree, version)
    edges, dropped = tree_edges(tree, nodes)
    text_join = attach_tree_text(nodes, tree_data)
    join = attach_cards(nodes, cards, spec)
    for edge in edges:
        nodes[edge["from"]]["neighbors"].append(edge["to"])
        nodes[edge["to"]]["neighbors"].append(edge["from"])
    summary = validate(nodes, edges, join, spec)
    summary.update(join)
    summary.update(text_join)
    summary["zh_sources"] = dict(Counter(n["zh_source"] or "none" for n in nodes.values()))
    summary["unlock_ascendancy"] = dict(Counter(n["unlock_ascendancy"] for n in nodes.values() if n["unlock_ascendancy"]))
    summary["unlock_other"] = sum(1 for raw in tree["nodes"].values()
                                  if raw.get("unlockConstraint") and not raw["unlockConstraint"].get("ascendancy"))
    summary["types"] = dict(Counter(n["type"] for n in nodes.values()))
    summary["edge_kinds"] = dict(Counter(e["kind"] for e in edges))
    summary["connections_dropped"] = dropped
    summary["built_at"] = now_iso()
    summary["pob_classes"] = pob_class_ids(tree)
    summary["pob_level_acts"] = load_quest_acts(spec, fetch=fetch, cache_dir=pob2_cache, offline=offline)
    for node in nodes.values():   # every source of the node was read in this build
        node["fetched_at"] = summary["built_at"]
    return list(nodes.values()), edges, summary


def write_passives(spec: Spec, out_dir: Path, nodes: list[dict], edges: list[dict], tree_data: dict,
                   built_at: str, pob_ids: dict | None = None, pob_acts: list[dict] | None = None) -> dict:
    """Write nodes, edges and classes.json under out_dir. Returns the paths and the class counts."""
    source = spec.source("pob2_tree")
    nodes_path = out_dir / Path(source["nodes_file"]).relative_to("data")
    edges_path = out_dir / Path(source["edges_file"]).relative_to("data")
    classes_path = out_dir / Path(spec.source("passive_tree_data")["classes_file"]).relative_to("data")
    classes = classes_doc(tree_data, nodes, built_at, pob_ids, pob_acts)
    write_jsonl(nodes_path, nodes)
    write_jsonl(edges_path, edges)
    atomic_write_text(classes_path, json.dumps(classes, ensure_ascii=False, indent=2) + "\n")
    return {"paths": [nodes_path, edges_path, classes_path], "classes": len(classes["classes"]),
            "ascendancies": sum(len(c["ascendancies"]) for c in classes["classes"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the passive tree from PoB2 + poe2db.")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=BASE_DIR / "data")
    parser.add_argument("--tree-data-version", help="poe2db tree data version (default: the catalog's pinned one)")
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["polite_delay_seconds"]
    fetch = lambda url: fetch_html(url, delay=delay)  # noqa: E731
    try:
        tree_data = load_tree_data(spec, fetch=fetch, cache_dir=TREE_DATA_CACHE_DIR, offline=args.offline,
                                   version=args.tree_data_version)
        nodes, edges, summary = build(spec, fetch=fetch, offline=args.offline, tree_data=tree_data)
    except (PassiveBuildError, requests.RequestException) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    except (KeyError, IndexError, TypeError) as exc:
        print(f"[ERROR] PoB2 tree schema changed? {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    written = write_passives(spec, args.out_dir, nodes, edges, tree_data, summary["built_at"],
                             summary.pop("pob_classes"), summary.pop("pob_level_acts"))
    summary["classes"], summary["ascendancies"] = written["classes"], written["ascendancies"]
    print("=== collect_passives summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("\n".join(f"wrote: {path}" for path in written["paths"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
