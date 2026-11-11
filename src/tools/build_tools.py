"""
build_tools.py — Build-advice helpers on top of LookupService.

`verify_build` checks every gem / passive name of a draft build against the local data and
returns the real facts plus a numbered, code-rendered source list. `supports_for` lists the
support gems that can support a skill, `reference_builds` summarises the poe.ninja ladder
snapshot without character names. The MCP server calls these functions; nothing here calls an
LLM or the network.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.catalog.entity_index import PASSIVE_TYPE_TO_KIND, make_aliases
from src.catalog.spec import GEM_KINDS, ITEM_KINDS
from src.scrapers.common import clean_text
from src.tools.items import ITEM_KIND_NAMES, AmbiguousItem, ItemLookup, item_fact_lines
from src.tools.pathing import PassivePathfinder
from src.tools.lookup import (
    BadArgument,
    LookupFailed,
    LookupService,
    TREE_DATA_LABEL,
    NotFound,
    ServiceUnavailable,
    _cap,
    _gem_matches,
    _lang,
    _limit,
    _require,
    _sources,
    is_cjk,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

MAX_NAMES = 40
DETAIL_LEVELS = ("full", "brief")
# brief: enough to know what passed and how to cite it, for a caller that already holds the records
BRIEF_KEYS = ("input", "slug", "id", "kind", "type", "name", "name_zh_tw", "item_class", "affix", "family", "cite")
MAX_AFFIXES = 60     # ten gear slots (two rings) with 3 prefixes + 3 suffixes each, in one call
MAX_NAME_LEN = 120
MAX_SUGGESTIONS = 3
MAX_PER_AFFIX = 3    # a rare item holds at most 3 prefixes and 3 suffixes
AFFIX_SEPARATOR = re.compile(r"\s*[:：]\s*")
MAX_ECHO_LEN = 80
COMMON_TOP = 10
MAX_STAT_LINES = 6     # stat lines of a gem kept in a verified fact
MAX_TEXT_STATS = 40    # rule-like stat lines listed for a route
START_NODE_TYPE = "ClassStart"
START_REASON = "this is a class or ascendancy start node, not a passive to allocate"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
PASSIVE_KINDS = tuple(PASSIVE_TYPE_TO_KIND.values())
BUILDS_FILE = Path("data") / "community_builds" / "poe_ninja_builds.jsonl"
POE_NINJA_URL = "https://poe.ninja/poe2/builds"
POE2DB_LABEL = "poe2db"
GEM_FACT_FIELDS = ("slug", "kind", "name", "tier", "tags", "cost", "main_stat", "requires_weapons", "description",
                   "quality_effects")
BUILD_FIELDS = ("class", "main_skill", "rank", "level", "skill_gems", "keystones")  # never character_name
TEXT = {
    "en": {
        "header": "## Sources",
        "fetched": "{label}, fetched {date}",
        "no_page": "passive nodes without a poe2db page",
        "zh_text": "Traditional Chinese names and stat lines of those nodes",
        "path_note": ("Approximate route: it connects every target from the class start but is not guaranteed "
                      "to use the fewest points. points_alone is each target's cost on its own; added_points is "
                      "what only that target needs. Weapon-set passive points and jewels are not modelled."),
        "removed": "Not found in local data (removed): {names}",
        "replaced": "{name} (replaced by {other})",
        "reference": "Reference builds: [{label}]({url}) — ladder snapshot {date}",
        "matched": ", {total} characters matched",
        "ninja": "poe.ninja PoE2 builds",
    },
    "zh-tw": {
        "header": "## 資料來源",
        "fetched": "{label}，擷取於 {date}",
        "no_page": "沒有 poe2db 頁面的天賦點",
        "zh_text": "這些天賦點的繁體中文名稱與屬性文字",
        "path_note": ("這是近似路線：從職業起點連到每個目標，但不保證點數最少。points_alone 是單獨點該目標的成本，"
                      "added_points 是只有該目標才需要的點數。武器組天賦點與珠寶不在計算內。"),
        "removed": "本地資料查無（已移除）：{names}",
        "replaced": "{name}（改用 {other}）",
        "reference": "參考流派：[{label}]({url})，天梯快照 {date}",
        "matched": "，符合 {total} 個角色",
        "ninja": "poe.ninja PoE2 流派",
    },
}

# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------


class BuildTools:
    """Verification, support listing and ladder summaries for build advice."""

    def __init__(self, lookup: LookupService, builds_path: Path | None = None) -> None:
        self.lookup = lookup
        self.builds_path = builds_path or lookup.base_dir / BUILDS_FILE
        self._builds: tuple[list[dict], int] | None = None
        self._builds_date: str | None = None   # date of the snapshot file, read with the rows
        self._builds_lock = threading.Lock()
        self._finder: PassivePathfinder | None = None
        self.items = ItemLookup(lookup)
        self._stats_by_node: dict[str, list[dict]] | None = None

    # -- verification ---------------------------------------------------------

    def verify_build(self, gems: list[str] | None = None, passives: list[str] | None = None,
                     lang: str | None = None, items: list[str] | None = None,
                     affixes: list[str] | None = None, detail: str = "full") -> dict:
        """Facts and sources for every name that matches local data exactly; the rest is
        reported in `unverified` with close names as suggestions. `affixes` are "item: modifier"
        strings, checked against what that item class can roll."""
        if detail not in DETAIL_LEVELS:
            raise BadArgument(f"detail must be one of {DETAIL_LEVELS}")
        gems, passives = _names(gems, "gems"), _names(passives, "passives")
        items, affixes = _names(items, "items"), _names(affixes, "affixes", MAX_AFFIXES)
        if not (gems or passives or items or affixes):
            raise BadArgument("give at least one gem, passive, item or affix")
        lang = _lang(lang) or ("zh-tw" if any(is_cjk(n) for n in gems + passives + items + affixes) else "en")
        verified_gems, verified_passives, unverified, seen = [], [], [], set()
        for name in gems:
            fact = self.gem_fact(name)
            key = ("gem", fact["slug"]) if fact else ("unknown gem", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self.unverified_entry(name, "gem"))
            else:
                verified_gems.append(fact)
        for name in passives:
            fact = self.passive_fact(name)
            key = ("passive", fact["id"]) if fact else ("unknown passive", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self.unverified_entry(name, "passive"))
            else:
                verified_passives.append(fact)
        verified_items, verified_affixes = self._verify_gear(items, affixes, unverified, seen)
        sources = number_sources(verified_gems + verified_passives + verified_items + verified_affixes)
        verified_affixes = [_compact_affix(fact, lang) for fact in verified_affixes]
        verified = {"gems": verified_gems, "passives": verified_passives}
        if items or affixes:
            verified.update(items=verified_items, affixes=verified_affixes)
        verified = {kind: [_returned_fact(fact, detail) for fact in facts] for kind, facts in verified.items()}
        return {
            "lang": lang,
            "verified": verified,
            "unverified": unverified,
            "sources": sources,
            "sources_markdown": render_sources(sources, unverified, lang),
        }

    def _verify_gear(self, items: list[str], affixes: list[str], unverified: list[dict], seen: set) -> tuple[list, list]:
        verified_items, verified_affixes = [], []
        for name in items:
            try:
                fact = self.item_fact(name)
            except AmbiguousItem as exc:
                unverified.append({"input": name, "expected": "item", "reason": str(exc),
                                   "suggestions": [{"slug": option} for option in exc.options]})
                continue
            key = ("item", fact["slug"]) if fact else ("unknown item", _name_key(name))
            if key in seen:
                continue
            seen.add(key)
            if fact is None:
                unverified.append(self._unknown_item(name))
            else:
                verified_items.append(fact)
        for entry in affixes:
            fact = self.affix_fact(entry)
            if fact.get("expected") == "affix":
                unverified.append(fact)
            else:
                problem = _affix_conflict(fact, verified_affixes)
                if problem:
                    unverified.append({"input": entry, "expected": "affix", "reason": problem, "suggestions": []})
                elif not any(_same_modifier(fact, kept) for kept in verified_affixes):
                    verified_affixes.append(fact)
        return verified_items, verified_affixes

    def _unknown_item(self, name: str) -> dict:
        """An item name with no match; an item class given as an item gets the reason spelled out."""
        entry = self.unverified_entry(name, "item")
        try:
            self.items.resolve_page(name)
        except (NotFound, BadArgument):
            return entry
        return {**entry, "reason": "this is an item class, not an item: `items` takes base or unique names; "
                                   "a class goes before the colon in `affixes`"}

    def item_fact(self, name: str) -> dict | None:
        """Trimmed record of one base or unique item, or None when the name has no local match."""
        try:
            kind, record = self.items._resolve(name)
        except NotFound:
            return None
        return {"input": name, "slug": record["slug"], "kind": ITEM_KIND_NAMES[kind], "name": record["name"],
                "name_zh_tw": record.get("name_zh_tw"), "item_class": record.get("item_class"),
                "base": record.get("base"), "requires_level": record.get("requires_level"),
                "lines": item_fact_lines(kind, record),
                "sources": _sources(record.get("url_en"), record.get("url_zh_tw"), record.get("fetched_at"))}

    def affix_fact(self, entry: str) -> dict:
        """A verified target modifier for an item class, or an `unverified` entry (expected: affix)."""
        parts = AFFIX_SEPARATOR.split(entry, maxsplit=1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise BadArgument(f"an affix must be written as 'item: modifier', e.g. 'Rings: +#% to Fire Resistance'; got {entry!r}")
        item, text = parts
        try:
            check = self.items.check_affix(item, text)
        except AmbiguousItem as exc:
            return {"input": entry, "expected": "affix", "reason": str(exc),
                    "suggestions": [{"item": option} for option in exc.options]}
        except NotFound as exc:
            return {"input": entry, "expected": "affix", "reason": str(exc), "suggestions": []}
        if not check["matched"]:
            return {"input": entry, "expected": "affix", "reason": check["reason"], "suggestions": check["suggestions"]}
        family, page = check["family"], check["item_class"]
        best, lowest = family["tiers"][0], family["tiers"][-1]
        return {"input": entry, "item": clean_text(item), "item_class": page["slug"], "family": family["family"],
                "group": family["group"], "affix": family["affix"], "modifier": family["template"],
                "tiers": len(family["tiers"]),
                "best": {k: best[k] for k in ("text", "text_zh_tw", "level")},
                "lowest": {k: lowest[k] for k in ("text", "text_zh_tw", "level")},
                "name": f"{page['label']} modifiers",
                "name_zh_tw": f"{page['label_zh_tw']}詞綴" if page.get("label_zh_tw") else None,
                "sources": check["sources"]}

    def gem_fact(self, name_or_slug: str) -> dict | None:
        """Trimmed record of one gem, or None when the name has no exact local match."""
        try:
            entity = self.lookup._resolve(name_or_slug, GEM_KINDS)
            record = self.lookup._gem_record(entity["kind"], entity["slug"])
        except NotFound:
            return None
        fact = {"input": name_or_slug, **{k: record.get(k) for k in GEM_FACT_FIELDS}}
        fact["stats"] = _strings(record.get("extra_properties"))[:MAX_STAT_LINES]
        fact["name_zh_tw"] = entity.get("name_zh_tw")
        fact["sources"] = _sources(record.get("source_url"), record.get("url_zh_tw"), record.get("fetched_at"))
        return fact

    def passive_fact(self, name_or_id: str) -> dict | None:
        """Trimmed record of one passive node (by name, slug or tree id), or None. Class and
        ascendancy start nodes are not passives a build allocates, so they do not verify."""
        try:
            node = self.lookup.get_passive(name_or_id)["passive"]
        except NotFound:
            return None
        if _is_start(node):
            return None
        return {
            "input": name_or_id, "id": node["id"], "slug": node.get("slug"), "name": node.get("name"),
            "name_zh_tw": node.get("name_zh_tw"), "type": node.get("type"), "ascendancy": node.get("ascendancy"),
            "stats": node.get("stats") or [], "stats_zh_tw": node.get("stats_zh_tw") or [],
            "sources": self.lookup._passive_sources(node),
        }

    def unverified_entry(self, name: str, expected: str) -> dict:
        kinds = {"gem": GEM_KINDS, "passive": PASSIVE_KINDS, "item": ITEM_KINDS}[expected]
        hits = self.lookup.index.find(clean_text(name), limit=20)
        other = next((h for h in hits if h["match_type"] == "exact" and h["kind"] not in kinds), None)
        reason = (f"this name is a {other['kind']}, not a {expected}" if other
                  else "no exact match in local data")
        if expected == "passive" and self._is_start_node(name):
            reason = START_REASON
        keep = ("slug", "kind", "name_en", "name_zh_tw", "match_type")
        suggestions = [{k: h.get(k) for k in keep} for h in hits if h["kind"] in kinds][:MAX_SUGGESTIONS]
        return {"input": name, "expected": expected, "reason": reason, "suggestions": suggestions}

    def _is_start_node(self, name: str) -> bool:
        try:
            return _is_start(self.lookup.get_passive(name)["passive"])
        except LookupFailed:
            return False

    # -- supports -------------------------------------------------------------

    def supports_for(self, skill: str, tag: str | None = None, limit: int = 50) -> dict:
        """Every support gem with a SUPPORTS edge to the skill, lowest tier first."""
        _cap(tag, "tag")
        entity = self.lookup._resolve(skill, GEM_KINDS)
        if entity["kind"] == "support_gem":
            raise BadArgument(f"{entity['name_en']} is a support gem; use get_gem to see the skills it supports")
        limit = _limit(limit)
        graph = self.lookup.graph
        if graph is None:
            raise ServiceUnavailable("supports need the knowledge graph; run python -m src.kg.build_graph")
        node_id = f"gem:{entity['slug']}"
        edges = graph.in_edges(node_id, data=True) if node_id in graph else []
        slugs = [graph.nodes[u].get("slug") for u, _, d in edges if d.get("type") == "SUPPORTS"]
        records = [self.lookup.gems["support_gem"][s] for s in dict.fromkeys(slugs)
                   if s in self.lookup.gems["support_gem"]]
        records = [r for r in records if _gem_matches(r, tag, None, None)]
        records.sort(key=lambda r: (r.get("tier") is None, r.get("tier") or 0, r.get("name") or ""))
        record = self.lookup._gem_record(entity["kind"], entity["slug"])
        return {
            "skill": {k: entity.get(k) for k in ("slug", "kind", "name_en", "name_zh_tw")},
            "tag": tag,
            "total": len(records),
            "supports": [self._support_row(r) for r in records[:limit]],
            "sources": _sources(record.get("source_url"), record.get("url_zh_tw"), record.get("fetched_at")),
        }

    def _support_row(self, record: dict) -> dict:
        entity = self.lookup.index.get(record["slug"], kind="support_gem")
        return {"slug": record["slug"], "name": record.get("name"),
                "name_zh_tw": entity.name_zh_tw if entity else None, "tier": record.get("tier"),
                "tags": record.get("tags"), "url_en": record.get("source_url"), "url_zh_tw": record.get("url_zh_tw")}

    # -- ladder reference -------------------------------------------------------

    def reference_builds(self, class_name: str | None = None, main_skill: str | None = None,
                         limit: int = 5, lang: str | None = None) -> dict:
        """What ladder characters run, from the local poe.ninja snapshot. No character names."""
        limit = _limit(limit)
        _cap(class_name, "class_name")
        _cap(main_skill, "main_skill")
        class_name = clean_text(class_name) or None if class_name else None   # blank = no filter
        main_skill = clean_text(main_skill) or None if main_skill else None
        lang = _lang(lang) or ("zh-tw" if is_cjk(f"{class_name or ''}{main_skill or ''}") else "en")
        rows, skipped = self._load_builds()
        wanted_class = self.lookup.canonical_class(class_name).lower() if class_name else None
        wanted_skill = self._canonical_skill(main_skill).lower() if main_skill else None
        hits = [r for r in rows
                if (wanted_class is None or str(r.get("class") or "").lower() == wanted_class)
                and (wanted_skill is None or str(r.get("main_skill") or "").lower() == wanted_skill)]
        hits.sort(key=lambda r: (not isinstance(r.get("rank"), int), r.get("rank") if isinstance(r.get("rank"), int) else 0))
        source = self.ladder_source(lang)
        result = {
            "filters": {"class_name": class_name, "main_skill": main_skill},
            "total_matching": len(hits),
            "league": source["league"],
            "builds": [{k: r.get(k) for k in BUILD_FIELDS} for r in hits[:limit]],
            "common": {
                "main_skills": _most_common(r.get("main_skill") for r in hits),
                "other_gems": _most_common(g for r in hits for g in _others(r)),
                "keystones": _most_common(k for r in hits for k in _strings(r.get("keystones"))),
            },
            "source": {k: source[k] for k in ("label", "url", "fetched_at")},
            "source_markdown": render_ladder_source(source, lang, total=len(hits)),
            "skipped_lines": skipped,
        }
        if not hits:
            result["available_classes"] = _most_common((r.get("class") for r in rows), 50)
        return result

    # -- passive pathing ------------------------------------------------------------

    def path_to(self, class_name: str, targets: list[str], ascendancy: str | None = None,
                lang: str | None = None) -> dict:
        """Which passives to allocate, in order, to reach `targets` from a class start, with the
        point cost and what the whole route gives. The route is a good approximation, not a
        guaranteed minimum."""
        names = _names(targets, "targets")
        if not names:
            raise BadArgument("give at least one target passive")
        _require(class_name, "class_name")
        _cap(class_name, "class_name")
        _cap(ascendancy, "ascendancy")
        lang = _lang(lang) or ("zh-tw" if is_cjk("".join([class_name, ascendancy or "", *names])) else "en")
        cls, chosen = self._class_and_ascendancy(class_name, ascendancy)
        facts, unverified = self._path_targets(names)
        nodes = self.lookup.passives
        chosen, inferred = self._settle_ascendancy(cls, chosen, facts, unverified)
        own = [f for f in facts if nodes[f["id"]].get("ascendancy")]
        main = [f for f in facts if not nodes[f["id"]].get("ascendancy")]

        finder = self._pathfinder()
        main_allowed = {i for i, n in nodes.items() if not n.get("ascendancy") and not n.get("timeless")
                        and n.get("unlock_ascendancy") in (None, chosen)}
        main_route = finder.route(self._class_start(cls), [f["id"] for f in main], main_allowed)
        asc_route = None
        if own:
            asc_allowed = {i for i, n in nodes.items() if n.get("ascendancy") == chosen}
            asc_route = finder.route(self._ascendancy_start(chosen), [f["id"] for f in own], asc_allowed)

        routes = [r for r in (main_route, asc_route) if r is not None]
        gone = {t for r in routes for t in r.unreachable}
        reached = [f for f in facts if f["id"] not in gone]
        allocated = [i for r in routes for i in r.order]
        limits = (self.lookup.classes_doc or {}).get("points") or {}
        totals, text_stats = self._stat_totals(allocated, lang)
        sources = number_sources([*reached, {"sources": [self.lookup._passive_sources({"pob2_tree_version":
                                  self.lookup.spec.source("pob2_tree")["version"]})[0]]}] if allocated else reached)
        return {
            "class": cls, "ascendancy": chosen, "ascendancy_inferred": inferred, "lang": lang,
            "points": {"passive": _budget(main_route.points, limits.get("passive")),
                       "ascendancy": _budget(asc_route.points if asc_route else 0, limits.get("ascendancy"))},
            "targets": [self._target_row(f, routes) for f in reached],
            "path": self._path_rows(main_route, {f["id"] for f in main}, lang),
            "ascendancy_path": self._path_rows(asc_route, {f["id"] for f in own}, lang) if asc_route else [],
            "stat_totals": totals, "text_stats": text_stats,
            "unverified": unverified,
            "unreachable": [self._unreachable_row(f, chosen) for f in facts if f["id"] in gone],
            "approximate": True, "note": TEXT[lang]["path_note"],
            "sources": sources, "sources_markdown": render_sources(sources, unverified, lang),
        }

    def _class_and_ascendancy(self, class_name: str, ascendancy: str | None) -> tuple[str, str | None]:
        if self.lookup.classes_doc is None:
            raise ServiceUnavailable("class data missing; run python -m src.scrapers.collect_passives")
        info = self.lookup.class_info(class_name)
        if info is None or info["class"] not in self._class_starts():
            raise BadArgument(f"unknown class {clean_text(class_name)[:MAX_ECHO_LEN]!r}; "
                              f"classes: {', '.join(sorted(self._class_starts()))}")
        chosen = info["ascendancy"]
        if ascendancy and clean_text(ascendancy):
            asked = self.lookup.class_info(ascendancy)
            if asked is None or asked["ascendancy"] is None or asked["class"] != info["class"]:
                raise BadArgument(f"{clean_text(ascendancy)[:MAX_ECHO_LEN]!r} is not an ascendancy of {info['class']}")
            if chosen and chosen != asked["ascendancy"]:
                raise BadArgument(f"class_name names {chosen} but ascendancy names {asked['ascendancy']}")
            chosen = asked["ascendancy"]
        if chosen and chosen not in self._ascendancy_starts():
            raise BadArgument(f"{chosen} has no ascendancy tree in the local data")
        return info["class"], chosen

    def _path_targets(self, names: list[str]) -> tuple[list[dict], list[dict]]:
        facts, unverified, seen = [], [], set()
        for name in names:
            fact = self.passive_fact(name)
            if fact is None:
                key = ("unknown passive", _name_key(name))
                if key not in seen:
                    seen.add(key)
                    unverified.append(self.unverified_entry(name, "passive"))
            elif fact["id"] not in seen:
                seen.add(fact["id"])
                facts.append(fact)
        return facts, unverified

    def _settle_ascendancy(self, cls: str, chosen: str | None, facts: list[dict],
                           unverified: list[dict]) -> tuple[str | None, bool]:
        """Pick the ascendancy when the targets imply exactly one; move targets of any other
        ascendancy from `facts` to `unverified`."""
        nodes = self.lookup.passives
        named = {nodes[f["id"]]["ascendancy"] for f in facts if nodes[f["id"]].get("ascendancy")}
        inferred = False
        if chosen is None and len(named) == 1:
            only = next(iter(named))
            info = self.lookup.class_info(only)
            if info and info["class"] == cls:
                chosen, inferred = only, True
        for fact in list(facts):
            theirs = nodes[fact["id"]].get("ascendancy")
            if theirs and theirs != chosen:
                facts.remove(fact)
                reason = (f"{fact['name']} belongs to the {theirs} ascendancy; pass ascendancy={theirs!r}"
                          if chosen is None else f"{fact['name']} belongs to the {theirs} ascendancy, not {chosen}")
                unverified.append({"input": fact["input"], "expected": "passive", "reason": reason, "suggestions": []})
        return chosen, inferred

    def _pathfinder(self) -> PassivePathfinder:
        if self._finder is None:
            self._finder = PassivePathfinder(self.lookup.passives)
        return self._finder

    def _class_starts(self) -> dict[str, str]:
        return {c: n["id"] for n in self.lookup.passives.values() if n.get("type") == START_NODE_TYPE
                for c in n.get("class_start") or []}

    def _class_start(self, cls: str) -> str:
        return self._class_starts()[cls]

    def _ascendancy_starts(self) -> dict[str, str]:
        return {n["ascendancy"]: n["id"] for n in self.lookup.passives.values()
                if n.get("is_ascendancy_start") and n.get("ascendancy")}

    def _ascendancy_start(self, ascendancy: str) -> str:
        return self._ascendancy_starts()[ascendancy]

    def _target_row(self, fact: dict, routes: list) -> dict:
        route = next(r for r in routes if fact["id"] in r.alone)
        return {"input": fact["input"], "id": fact["id"], "name": fact["name"], "name_zh_tw": fact["name_zh_tw"],
                "type": fact["type"], "cite": fact.get("cite"),
                "points_alone": route.alone[fact["id"]], "added_points": route.exclusive[fact["id"]]}

    def _unreachable_row(self, fact: dict, chosen: str | None) -> dict:
        lock = self.lookup.passives[fact["id"]].get("unlock_ascendancy")
        reason = (f"needs the {lock} ascendancy" if lock and lock != chosen
                  else "not connected to the rest of the tree in the local data")
        return {"input": fact["input"], "id": fact["id"], "name": fact["name"], "name_zh_tw": fact["name_zh_tw"],
                "reason": reason}

    def _path_rows(self, route, targets: set[str], lang: str) -> list[dict]:
        rows = []
        for order, node_id in enumerate(route.order, 1):
            node = self.lookup.passives[node_id]
            zh = node.get("stats_zh_tw") or []
            rows.append({"order": order, "id": node_id, "name": node.get("name"), "name_zh_tw": node.get("name_zh_tw"),
                         "type": node.get("type"),
                         "stats": zh if lang == "zh-tw" and zh else node.get("stats") or [],
                         "target": node_id in targets})
        return rows

    def _stat_totals(self, node_ids: list[str], lang: str) -> tuple[list[dict], list[str]]:
        """What the allocated nodes give together: numeric stats summed per (family, kind);
        lines that are rules rather than numbers are listed once each."""
        if self._stats_by_node is None:
            by_node: dict[str, list[dict]] = {}
            for row in self.lookup.stat_rows:
                by_node.setdefault(str(row["node_id"]), []).append(row)
            self._stats_by_node = by_node
        groups: dict[tuple[str, str], dict] = {}
        texts: list[str] = []
        for node_id in node_ids:
            for row in self._stats_by_node.get(node_id, []):
                if row["kind"] == "text" or row.get("value") is None:
                    line = (row.get("text_zh_tw") if lang == "zh-tw" else None) or row["text"]
                    if line not in texts:
                        texts.append(line)
                    continue
                group = groups.setdefault((row["family"], row["kind"]), {
                    "family": row["family"], "kind": row["kind"], "total": 0.0, "lines": 0,
                    "template": row["template"], "template_zh_tw": row.get("template_zh_tw")})
                group["total"] += row["value"]
                group["lines"] += 1
        totals = sorted(groups.values(), key=lambda g: (-g["lines"], g["family"], g["kind"]))
        for group in totals:
            group["total"] = round(group["total"], 2)
        return totals, texts[:MAX_TEXT_STATS]

    def ladder_source(self, lang: str = "en") -> dict:
        """Where the reference builds come from: label, URL, league and snapshot date."""
        rows, _ = self._load_builds()
        league = _most_common((r.get("league") for r in rows), 1)
        league_name = league[0]["name"] if league else None
        label = TEXT[lang]["ninja"] + (f" ({league_name})" if league_name else "")
        return {"label": label, "url": POE_NINJA_URL, "fetched_at": self._builds_date, "league": league_name}

    def _canonical_skill(self, main_skill: str) -> str:
        _require(main_skill, "main_skill")
        try:
            return self.lookup._resolve(main_skill, GEM_KINDS)["name_en"]
        except NotFound:
            return clean_text(main_skill)

    def _load_builds(self) -> tuple[list[dict], int]:
        with self._builds_lock:
            if self._builds is None:
                if not self.builds_path.exists():
                    raise ServiceUnavailable(
                        "community builds missing; update the ladder data (update_data with scope ladder)")
                try:
                    builds = _read_builds(self.builds_path)
                    modified = self.builds_path.stat().st_mtime
                except OSError as exc:
                    raise ServiceUnavailable(
                        f"community builds unreadable ({type(exc).__name__}): {self.builds_path.name}") from exc
                # When the data was fetched (recorded in the rows), not when the file was copied.
                self._builds_date = (_snapshot_date(builds[0])
                                     or datetime.fromtimestamp(modified, timezone.utc).date().isoformat())
                self._builds = builds
            return self._builds


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def number_sources(facts: list[dict]) -> list[dict]:
    """One numbered row per distinct URL; each fact gets `cite` = the number of its row."""
    rows: list[dict] = []
    by_url: dict[str, dict] = {}
    for fact in facts:
        primary = fact["sources"][0] if fact.get("sources") else None
        if primary is None:
            continue
        row = by_url.get(primary["url"])
        if row is None:
            on_poe2db = primary["label"].startswith(POE2DB_LABEL)
            zh = next((s["url"] for s in fact["sources"][1:] if "zh-TW" in s["label"]), None)
            row = {"n": len(rows) + 1, "label": POE2DB_LABEL if on_poe2db else primary["label"],
                   "name": fact.get("name") if on_poe2db else None,
                   "name_zh_tw": fact.get("name_zh_tw") if on_poe2db else None,
                   "url": primary["url"], "url_zh_tw": zh, "fetched_at": primary.get("fetched_at")}
            by_url[primary["url"]] = row
            rows.append(row)
        fact["cite"] = row["n"]
        for extra in fact["sources"][1:]:  # where a page-less node's Chinese text comes from
            if extra["label"] == TREE_DATA_LABEL and extra["url"] not in by_url:
                by_url[extra["url"]] = {"n": len(rows) + 1, "label": extra["label"], "name": None, "name_zh_tw": None,
                                        "url": extra["url"], "url_zh_tw": None, "fetched_at": extra.get("fetched_at"),
                                        "note": "zh_text"}
                rows.append(by_url[extra["url"]])
    return rows


def render_sources(sources: list[dict], unverified: list[dict], lang: str = "en") -> str:
    """The Sources section as Markdown, in the answer language. Written by code so links and
    names never depend on what the model remembers."""
    text = TEXT[lang]
    lines = [text["header"]]
    for row in sources:
        lines.append(f"{row['n']}. {_source_line(row, lang)}")
    if unverified:
        names = ", ".join(_removed_name(u, text) for u in unverified)
        lines += ["", text["removed"].format(names=names)]
    return "\n".join(lines)


def render_ladder_source(source: dict, lang: str = "en", total: int | None = None) -> str:
    """The poe.ninja line that follows the Sources section when ladder builds were used."""
    text = TEXT[lang]
    line = text["reference"].format(label=_md_text(source["label"]), url=source["url"], date=source["fetched_at"])
    return line + (text["matched"].format(total=total) if total is not None else "")


def _source_line(row: dict, lang: str) -> str:
    text = TEXT[lang]
    if row["label"] != POE2DB_LABEL:  # PoB2 tree: one row for every node without a page
        what = text[row.get("note") or "no_page"]
        date = (row.get("fetched_at") or "")[:10]
        tail = text["fetched"].format(label=what, date=date) if date else what
        return f"[{_md_text(row['label'])}]({_md_url(row['url'])}) — {tail}"
    name = row.get("name") or row.get("name_zh_tw") or str(row["url"]).rsplit("/", 1)[-1]
    links = [f"[{_md_text(name)}]({_md_url(row['url'])})"]
    if row.get("name_zh_tw") and row.get("url_zh_tw"):
        links.append(f"[{_md_text(row['name_zh_tw'])}]({_md_url(row['url_zh_tw'])})")
    if lang == "zh-tw":
        links.reverse()
    date = (row.get("fetched_at") or "")[:10]
    tail = text["fetched"].format(label=row["label"], date=date) if date else row["label"]
    return f"{' · '.join(links)} — {tail}"


def _removed_name(entry: dict, text: dict) -> str:
    name = _md_code(entry["input"])
    if entry.get("replaced_by"):
        return text["replaced"].format(name=name, other=_md_text(entry["replaced_by"]))
    return name


def _md_text(value: str) -> str:
    """Single line, bounded, with the characters that open Markdown links / emphasis escaped."""
    flat = " ".join(str(value).split())[:MAX_ECHO_LEN]
    for ch in ("\\", "[", "]", "(", ")", "<", ">", "`", "*", "_", "|", "!"):
        flat = flat.replace(ch, "\\" + ch)
    return flat


def _md_code(value: str) -> str:
    """Text the caller typed, as an inline code span: nothing in it renders as a link (bare
    URLs included), HTML or heading."""
    flat = " ".join(str(value).split())[:MAX_ECHO_LEN].replace("`", "'")
    return f"`{flat}`"


def _md_url(url: str) -> str:
    return str(url).replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")


def _names(values: list[str] | None, label: str, limit: int = MAX_NAMES) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise BadArgument(f"{label} must be a list of names")
    if len(values) > limit:
        raise BadArgument(f"{label} has {len(values)} names; the limit is {limit}")
    out = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise BadArgument(f"{label} must contain non-empty names")
        if len(value) > MAX_NAME_LEN:
            raise BadArgument(f"a name in {label} is longer than {MAX_NAME_LEN} characters")
        out.append(clean_text(value))
    return out


def _read_builds(path: Path) -> tuple[list[dict], int]:
    """Rows of the ladder file. A line that is not valid UTF-8 JSON (or is nested too deeply to
    parse) is counted in `skipped`; it never fails the whole load."""
    rows, skipped = [], 0
    with path.open("rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):   # ValueError covers JSON and UTF-8 errors
                skipped += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                skipped += 1
    return rows, skipped


def _most_common(values, top: int = COMMON_TOP) -> list[dict]:
    counts = Counter(str(v) for v in values if v)
    return [{"name": name, "count": count} for name, count in counts.most_common(top)]


def _others(row: dict) -> list[str]:
    """The gems of a ladder row besides its main skill."""
    main = str(row.get("main_skill") or "").lower()
    return [g for g in _strings(row.get("skill_gems")) if g.lower() != main]


def _strings(value) -> list[str]:
    """The strings of a list field; anything else (a bare string, a number) counts as empty."""
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _snapshot_date(rows: list[dict]) -> str | None:
    """Latest `fetched_at` day recorded in the rows (ISO dates sort as text)."""
    days = [r["fetched_at"][:10] for r in rows
            if isinstance(r.get("fetched_at"), str) and _DATE_RE.match(r["fetched_at"])]
    return max(days, default=None)


def _budget(used: int, limit: int | None) -> dict:
    return {"used": used, "limit": limit, "over": used > limit if isinstance(limit, int) else None}


def _is_start(node: dict) -> bool:
    return node.get("type") == START_NODE_TYPE or bool(node.get("is_ascendancy_start"))


def _name_key(name: str) -> str:
    """Folded spelling of a name, so 'Mega Slam' and 'mega slam' are reported once."""
    aliases = make_aliases(name)
    return aliases[-1] if aliases else name.casefold()


def _same_modifier(fact: dict, kept: dict) -> bool:
    return (fact["item"].casefold(), fact["family"], fact["group"], fact["modifier"]) == \
        (kept["item"].casefold(), kept["family"], kept["group"], kept["modifier"])


def _affix_conflict(fact: dict, kept: list[dict]) -> str | None:
    """Why this modifier cannot join the ones already verified for the same item, or None.
    Counted per item as written (two rings are two items); a rare item holds at most
    MAX_PER_AFFIX prefixes and MAX_PER_AFFIX suffixes, and one modifier per family."""
    same_item = [k for k in kept if k["item"].casefold() == fact["item"].casefold()]
    for other in same_item:
        if (other["family"], other["group"]) == (fact["family"], fact["group"]) and other["modifier"] != fact["modifier"]:
            return f"same modifier family as {other['input']!r}; an item cannot have both"
    if any(_same_modifier(fact, other) for other in same_item):
        return None
    if fact["affix"] and sum(1 for k in same_item if k["affix"] == fact["affix"]) >= MAX_PER_AFFIX:
        return (f"{fact['item']} already has {MAX_PER_AFFIX} {fact['affix']}es in this list; an item holds at most "
                f"{MAX_PER_AFFIX} prefixes and {MAX_PER_AFFIX} suffixes")
    return None


def _compact_affix(fact: dict, lang: str) -> dict:
    """An affix fact as returned: its page is in the numbered sources (`cite`), and the tier texts
    are given in the answer language only, so a full set of gear fits in one response."""
    key = "text_zh_tw" if lang == "zh-tw" else "text"
    out = {k: v for k, v in fact.items() if k not in ("sources", "name", "name_zh_tw", "best", "lowest")}
    for tier in ("best", "lowest"):
        out[tier] = {"text": fact[tier].get(key) or fact[tier]["text"], "level": fact[tier]["level"]}
    return out


def _returned_fact(fact: dict, detail: str) -> dict:
    """A fact as verify_build returns it. Its page is in the numbered source list (`cite`), so the
    links are not repeated on every fact; `brief` keeps only what names and cites it."""
    if detail == "brief":
        return {k: fact[k] for k in BRIEF_KEYS if k in fact}
    return {k: v for k, v in fact.items() if k != "sources"}
