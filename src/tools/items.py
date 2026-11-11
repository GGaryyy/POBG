"""
items.py — Gear lookups on top of LookupService: one base or unique, items of a class, and the
modifiers a slot can roll.

A modifier list says what *can* appear on an item of that class, never what a given item has:
modifiers are random, and their weights are unknown. `check_affix` is how build advice proves
that a modifier it recommends exists for that slot at all. Only a request that names the whole
modifier (every word, in either language; numbers may be left out) counts as that modifier; a
request that names part of one gets the candidates back instead, so "+3 to Level of all Skills"
is never taken for "+3 to Level of all Spell Skills".
"""

from __future__ import annotations

import json
import re
import threading

from src.catalog.spec import ITEM_KINDS
from src.scrapers.collect_items import modifier_template as template
from src.scrapers.common import clean_text, read_jsonl
from src.tools.lookup import (
    BadArgument,
    LookupService,
    NotFound,
    ServiceUnavailable,
    _cap,
    _limit,
    _require,
    _sources,
    is_cjk,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

ITEM_KIND_NAMES = {"base": "item_base", "unique": "item_unique"}
MOD_GROUPS = ("normal", "desecrated", "corrupted", "essence", "perfect_essence", "socketable")
AFFIX_GROUPS = ("normal", "desecrated")          # what a recommended modifier is checked against
AFFIXES = ("prefix", "suffix")
DEFAULT_ITEMS_LIMIT = 30
DEFAULT_FAMILIES_LIMIT = 20
MAX_FAMILIES = 60
MAX_AFFIX_SUGGESTIONS = 3
MAX_ITEM_LINES = 12
WORD_RE = re.compile(r"[a-z]+|[一-鿿]")
NOISE_WORDS = {"to", "of", "the", "a", "an", "with", "your", "you", "per", "is", "are", "and", "的", "點", "至"}
# "adds" / 附加 are not noise: "fire damage" must not pass for "Adds # to # Fire Damage"
MIN_AFFIX_COVERAGE = 0.5   # share of a modifier's words a request must name for the modifier to be a candidate
VALUE_RE = re.compile(r"\d+(?:\.\d+)?")
REBUILD_HINT = "item data missing; update it with update_data scope items, or run python -m src.scrapers.collect_items"


class AmbiguousItem(BadArgument):
    """A name with several matches: an armour class with one modifier page per attribute type, or
    a Chinese name poe2db gives to two items. `options` lists what to use instead."""

    def __init__(self, message: str, options: list[str]) -> None:
        super().__init__(message)
        self.options = options


class ItemLookup:
    """Loads the item files once, on first use."""

    def __init__(self, lookup: LookupService) -> None:
        self.lookup = lookup
        self._loaded = False
        self._lock = threading.Lock()
        self.bases: dict[str, dict] = {}
        self.uniques: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.modifiers: dict[str, list[dict]] = {}

    # -- loading ---------------------------------------------------------------

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            source = self.lookup.spec.source("item_pages")
            base = self.lookup.base_dir
            paths = {key: base / source[f"{key}_file"] for key in ("bases", "uniques", "modifiers", "classes")}
            if not all(p.exists() for p in paths.values()):
                raise ServiceUnavailable(REBUILD_HINT)
            try:
                bases = {r["slug"]: r for r in read_jsonl(paths["bases"])}
                uniques = {r["slug"]: r for r in read_jsonl(paths["uniques"])}
                pages = {p["slug"]: p for p in json.loads(paths["classes"].read_text(encoding="utf-8"))["pages"]}
                modifiers: dict[str, list[dict]] = {}
                for row in read_jsonl(paths["modifiers"]):
                    modifiers.setdefault(row["mod_page"], []).append(row)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise ServiceUnavailable(f"the item data is unreadable ({type(exc).__name__}); "
                                         "update it with update_data scope items") from exc
            self.bases, self.uniques, self.pages, self.modifiers = bases, uniques, pages, modifiers
            self._loaded = True

    # -- items -----------------------------------------------------------------

    def get_item(self, name: str) -> dict:
        """One base or unique with its stats and sources."""
        kind, record = self._resolve(name)
        result = {"kind": kind, "item": record, "sources": _item_sources(record)}
        page = self._page_for_record(kind, record)
        if page:
            result["modifier_page"] = {"slug": page["slug"], "label": page["label"], "label_zh_tw": page.get("label_zh_tw")}
        return result

    def items_by(self, item_class: str | None = None, kind: str | None = None, text: str | None = None,
                 max_level: int | None = None, limit: int = DEFAULT_ITEMS_LIMIT, with_lines: bool = False) -> dict:
        """Bases and / or uniques filtered by class, text in their lines, and required level.
        with_lines adds each item's own lines (properties, effects, implicits or unique modifiers)
        in both languages, so one call answers "what are the items of this class and what do they do"."""
        self._load()
        text = clean_text(text) if text else None
        item_class = clean_text(item_class) if item_class else None
        for label, value in (("item_class", item_class), ("text", text)):
            _cap(value, label)
        if all(v in (None, "") for v in (item_class, kind, text, max_level)):
            raise BadArgument("give at least one filter: item_class, kind, text or max_level")
        if kind not in (None, "", *ITEM_KIND_NAMES):
            raise BadArgument(f"kind must be one of {tuple(ITEM_KIND_NAMES)}")
        classes = self._class_labels(item_class) if item_class else None
        stores = [("base", self.bases), ("unique", self.uniques)]
        hits = []
        for kind_name, store in stores:
            if kind and kind != kind_name:
                continue
            for record in store.values():
                if _item_matches(record, classes, text, max_level):
                    hits.append({**_item_brief(kind_name, record), **(_item_lines(kind_name, record) if with_lines else {})})
        hits.sort(key=lambda h: (h["requires_level"] or 0, h["name"]))
        return {"filters": {"item_class": item_class, "kind": kind or None, "text": text, "max_level": max_level},
                "total": len(hits), "items": hits[:_limit(limit)]}

    def _class_labels(self, item_class: str) -> list[str]:
        """Casefolded English class labels a query names, in English or Chinese (every record
        carries both names of its class). An exact name wins over a partial
        one, so "Bows" is not also "Crossbows"."""
        query = clean_text(item_class).casefold()
        names = {r["item_class"].casefold(): (r.get("item_class_zh_tw") or "")
                 for store in (self.bases, self.uniques) for r in store.values() if r.get("item_class")}
        shown = {r["item_class"]: r.get("item_class_zh_tw") for store in (self.bases, self.uniques)
                 for r in store.values() if r.get("item_class")}
        for matches in (lambda en, zh: query in (en, zh), lambda en, zh: query in en or (zh and query in zh)):
            found = sorted(en for en, zh in names.items() if matches(en, zh))
            if found:
                return found
        listed = ", ".join(sorted(f"{en} ({zh})" for en, zh in shown.items()))
        raise NotFound(f"no item class matches {item_class!r}. Classes: {listed}")

    # -- modifiers ---------------------------------------------------------------

    def modifiers_for(self, item: str, group: str = "normal", affix: str | None = None, text: str | None = None,
                      max_level: int | None = None, limit: int = DEFAULT_FAMILIES_LIMIT) -> dict:
        """What an item class can roll, one entry per modifier family with its tiers (1 = highest)."""
        page = self.resolve_page(item)
        if group not in MOD_GROUPS:
            raise BadArgument(f"group must be one of {MOD_GROUPS}")
        if affix not in (None, "", *AFFIXES):
            raise BadArgument(f"affix must be one of {AFFIXES}")
        _cap(text, "text")
        text = clean_text(text) if text else None
        wanted = template(text) if text else None
        rows = [r for r in self.modifiers.get(page["slug"], []) if r["group"] == group
                and (not affix or r["affix"] == affix) and (max_level is None or (r["level"] or 0) <= max_level)
                and (wanted is None or wanted in template(r["text"]) or wanted in template(r.get("text_zh_tw")))]
        families = _families(rows)
        return {"item_class": _page_brief(page), "group": group, "affix": affix or None, "text": text,
                "max_level": max_level, "total_families": len(families),
                "families": families[:min(_limit(limit), MAX_FAMILIES)],
                "note": "Modifiers are random: this is what can appear on this item class, not what an item has.",
                "sources": _sources(page["url_en"], page["url_zh_tw"], self._page_date(page["slug"]))}

    def check_affix(self, item: str, text: str) -> dict:
        """Does this item class roll a modifier like `text`? Returns the matching family with its
        tier range, or `matched: false` with the closest families."""
        _require(text, "modifier text")
        page = self.resolve_page(item)
        rows = [r for r in self.modifiers.get(page["slug"], []) if r["group"] in AFFIX_GROUPS]
        wanted = template(text)
        families = _families(rows)
        result = {"item": item, "text": text, "item_class": _page_brief(page),
                  "sources": _sources(page["url_en"], page["url_zh_tw"], self._page_date(page["slug"]))}
        exact = [f for f in families if _names_whole(wanted, f)]
        if exact:
            over = _value_above_best(text, exact[0])
            if over is None:
                return {**result, "matched": True, "family": exact[0]}
            return {**result, "matched": False, "reason": f"{over} is above the best tier",
                    "suggestions": [_suggestion(exact[0])]}
        scored = [(_coverage(wanted, f), f) for f in families]
        partial = [f for score, f in sorted(scored, key=lambda pair: (-pair[0], len(pair[1]["template"])))
                   if score >= MIN_AFFIX_COVERAGE]
        if partial:
            return {**result, "matched": False, "reason": "names only part of a modifier; write the whole modifier",
                    "suggestions": [_suggestion(f) for f in partial[:MAX_AFFIX_SUGGESTIONS]]}
        ranked = sorted(families, key=lambda f: -_overlap(wanted, f["template"] + " " + (f["template_zh_tw"] or "")))
        return {**result, "matched": False, "reason": f"{page['label']} does not roll a modifier like this",
                "suggestions": [_suggestion(f) for f in ranked[:MAX_AFFIX_SUGGESTIONS]]}

    def resolve_page(self, item: str) -> dict:
        """The modifier page for a page slug, a class label (English or Chinese), a base or a unique."""
        _require(item, "item")
        _cap(item, "item")
        self._load()
        query = clean_text(item)
        folded = query.casefold().replace(" ", "_")
        for slug, page in self.pages.items():
            if folded == slug.casefold():
                return page
        by_label = [p for p in self.pages.values()
                    if query.casefold() in (p["label"].casefold(), (p.get("label_zh_tw") or "").casefold())]
        if len(by_label) == 1:
            return by_label[0]
        if len(by_label) > 1:
            options = sorted(p["slug"] for p in by_label)
            raise AmbiguousItem(f"{query!r} has several modifier pages by attribute type: {', '.join(options)}; "
                                     "give one of them or a base name", options)
        try:
            kind, record = self._resolve(query)
        except NotFound as exc:
            raise NotFound(f"no item class, base or unique matches {query!r}") from exc
        page = self._page_for_record(kind, record)
        if page is None:
            raise NotFound(f"{record['name']} is on no modifier page in the local data")
        return page

    # -- helpers ---------------------------------------------------------------

    def _resolve(self, name: str) -> tuple[str, dict]:
        _require(name, "item name")
        _cap(name, "item name")
        self._load()
        query = clean_text(name)
        for kind, store in (("unique", self.uniques), ("base", self.bases)):
            if query in store:
                return kind, store[query]
        hits: dict[str, tuple[str, dict]] = {}
        for entity in self.lookup.index.exact(query):
            if entity.kind in ITEM_KINDS:
                kind = "unique" if entity.kind == "item_unique" else "base"
                store = self.uniques if kind == "unique" else self.bases
                if entity.slug in store:
                    hits.setdefault(entity.slug, (kind, store[entity.slug]))
        folded = query.casefold()
        for kind, store in (("unique", self.uniques), ("base", self.bases)):
            for record in store.values():
                if folded in ((record.get("name") or "").casefold(), (record.get("name_zh_tw") or "").casefold()):
                    hits.setdefault(record["slug"], (kind, record))
        if len(hits) > 1:
            raise AmbiguousItem(f"{query!r} names several items: {', '.join(hits)}; give the slug or the English name",
                                list(hits))
        if hits:
            return next(iter(hits.values()))
        raise NotFound(f"no base or unique item matches {query!r}; try items_by or lookup_entity")

    def _page_for_record(self, kind: str, record: dict) -> dict | None:
        base = record if kind == "base" else self.bases.get(record.get("base_slug") or "")
        return self.pages.get((base or {}).get("mod_page") or "")

    def _page_date(self, slug: str) -> str | None:
        rows = self.modifiers.get(slug) or []
        return rows[0].get("fetched_at") if rows else None


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def _families(rows: list[dict]) -> list[dict]:
    """Rows grouped by (group, affix, family, template): one entry per distinct modifier, tiers in
    order, entries in page order."""
    families: dict[tuple, dict] = {}
    for row in rows:
        key = (row["group"], row["affix"], row["family"], template(row["text"]))
        entry = families.setdefault(key, {"family": row["family"], "group": row["group"], "affix": row["affix"],
                                          "tags": row.get("tags") or [], "template": template(row["text"]),
                                          "template_zh_tw": template(row.get("text_zh_tw")) or None, "tiers": []})
        entry["tiers"].append({"tier": row.get("tier"), "name": row.get("name"), "name_zh_tw": row.get("name_zh_tw"),
                               "level": row.get("level"), "text": row.get("text"), "text_zh_tw": row.get("text_zh_tw")})
    for entry in families.values():
        entry["tiers"].sort(key=lambda t: t["tier"] or 0)
        levels = [t["level"] for t in entry["tiers"] if t["level"] is not None]
        entry["levels"] = [min(levels), max(levels)] if levels else None
    return list(families.values())


def _words(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text) if w not in NOISE_WORDS}


def _coverage(wanted: str, family: dict) -> float:
    """How much of a family's wording the request names, in whichever language matches better.
    Every requested word must appear in the modifier; 0 otherwise."""
    asked = _words(wanted)
    best = 0.0
    for candidate in (family["template"], family["template_zh_tw"] or ""):
        words = _words(candidate)
        if asked and words and asked <= words:
            best = max(best, len(asked) / len(words))
    return best


def _names_whole(wanted: str, family: dict) -> bool:
    """The request is this modifier: the same wording, or the same words, in either language."""
    for candidate in (family["template"], family["template_zh_tw"] or ""):
        if wanted == candidate or (_words(wanted) and _words(wanted) == _words(candidate)):
            return True
    return False


def _value_above_best(text: str, family: dict) -> str | None:
    """A number in the request larger than any number in the family's tiers, or None."""
    asked = [float(v) for v in VALUE_RE.findall(text)]
    ceiling = max((float(v) for tier in family["tiers"] for v in VALUE_RE.findall(tier["text"] or "")), default=None)
    if ceiling is None:
        return None
    above = [v for v in asked if v > ceiling]
    return f"{above[0]:g}" if above else None


def _suggestion(family: dict) -> dict:
    best = family["tiers"][0]
    return {"family": family["family"], "affix": family["affix"], "group": family["group"],
            "text": best["text"], "text_zh_tw": best["text_zh_tw"]}


def _overlap(wanted: str, candidate: str) -> int:
    return len(_words(wanted) & _words(candidate))


def _item_matches(record: dict, classes: list[str] | None, text: str | None, max_level: int | None) -> bool:
    """classes: casefolded class labels the record's class must be one of (None: any class)."""
    if classes is not None and (record.get("item_class") or "").casefold() not in classes:
        return False
    if max_level is not None and (record.get("requires_level") or 0) > max_level:
        return False
    if text:
        lines = [*record.get("mods", []), *record.get("mods_zh_tw", []), *record.get("implicits", []),
                 *record.get("effects", []), *record.get("effects_zh_tw", []),
                 *record.get("implicits_zh_tw", []), *record.get("properties", []), *record.get("properties_zh_tw", [])]
        needle = text.casefold() if not is_cjk(text) else text
        if not any(needle in (line.casefold() if not is_cjk(text) else line) for line in lines):
            return False
    return True


def _item_brief(kind: str, record: dict) -> dict:
    brief = {"slug": record["slug"], "kind": ITEM_KIND_NAMES[kind], "name": record["name"],
             "name_zh_tw": record.get("name_zh_tw"), "item_class": record.get("item_class"),
             "requires_level": record.get("requires_level"), "url_en": record.get("url_en"),
             "url_zh_tw": record.get("url_zh_tw")}
    if kind == "unique":
        brief["base"] = record.get("base")
    return brief


def _item_lines(kind: str, record: dict) -> dict:
    if kind == "unique":
        return {"lines": list(record.get("mods") or [])[:MAX_ITEM_LINES],
                "lines_zh_tw": list(record.get("mods_zh_tw") or [])[:MAX_ITEM_LINES]}
    fields = ("properties", "effects", "implicits")
    return {"lines": [line for f in fields for line in record.get(f) or []][:MAX_ITEM_LINES],
            "lines_zh_tw": [line for f in fields for line in record.get(f"{f}_zh_tw") or []][:MAX_ITEM_LINES]}


def _page_brief(page: dict) -> dict:
    return {"slug": page["slug"], "label": page["label"], "label_zh_tw": page.get("label_zh_tw"),
            "attributes": page.get("attributes", [])}


def _item_sources(record: dict) -> list[dict]:
    return _sources(record.get("url_en"), record.get("url_zh_tw"), record.get("fetched_at"))


def item_fact_lines(kind: str, record: dict) -> list[str]:
    """The lines a build answer may quote for an item, capped."""
    lines = record.get("mods") if kind == "unique" else [*record.get("properties", []), *record.get("effects", []),
                                                         *record.get("implicits", [])]
    return list(lines or [])[:MAX_ITEM_LINES]

