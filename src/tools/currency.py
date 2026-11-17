"""
currency.py — Currency items on top of LookupService: one item with what it does, and items by
category, effect text or level.

Every line comes from poe2db: the listing pages (effects, stack size, minimum modifier level,
limits, required level) and each item's own page (drop level, item class, tags). `related` in
`get_currency` is found in the data too: the other items whose English effect text names this
one ("your next Chaos Orb will ..."). Prices, drop sources and drop chances are not collected:
`not_in_data` says so, so an answer does not guess them.
"""

from __future__ import annotations

import copy
import re
import threading

from src.catalog.spec import CURRENCY_KINDS
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

SOURCE = "currency"
REBUILD_HINT = "currency data missing; update it with update_data scope currency"
DEFAULT_LIST_LIMIT = 30
MAX_RELATED = 40
MAX_BRIEF_LINES = 6
LINE_FIELDS = ("effects", "implicits", "enchants", "bonded")
CATEGORY_WORDS = {   # other words for the categories (the category itself is the English tab name)
    "通貨": "currency", "可堆疊通貨": "currency", "精髓": "essence", "裂片": "splinter", "催化劑": "catalyst",
    "預兆": "omen", "增幅": "augment", "符文": "augment", "魂核": "augment", "靈魂核心": "augment",
    "currencies": "currency", "orb": "currency", "orbs": "currency", "stackable currency": "currency",
    "essences": "essence", "splinters": "splinter", "catalysts": "catalyst", "omens": "omen",
    "augments": "augment", "rune": "augment", "runes": "augment", "soul core": "augment", "soul cores": "augment",
}
ESSENCE_GROUPS = {"essence": "essence", "perfect": "perfect_essence"}
NOT_IN_DATA = {
    "en": ["Prices and exchange rates: not collected.",
           "Where an item drops and how often: not in the local data. drop_level is poe2db's DropLevel, the lowest area "
           "level it can drop in; items that only come from some content (league mechanics, bosses, vendors) can show "
           "a low one.",
           "Crafting steps and strategies: not in the local data; only what each item does."],
    "zh-tw": ["價格與兌換比例：未收集。",
              "掉落來源與機率：本機資料沒有。drop_level 是 poe2db 的 DropLevel，即可能掉落的最低區域等級；"
              "只來自特定內容（聯盟機制、頭目、商人）的物品，這個值可能很低。",
              "製作步驟與策略：本機資料沒有，只有每個通貨的效果。"],
}
ESSENCE_NOTE = {
    "en": "The modifier this essence guarantees on each item class is in modifiers_for (item: the class, group: {group}).",
    "zh-tw": "這個精髓在各裝備類別保證的詞綴，用 modifiers_for 查（item：裝備類別，group：{group}）。",
}


class CurrencyLookup:
    """Loads the currency file once, on first use."""

    def __init__(self, lookup: LookupService) -> None:
        self.lookup = lookup
        self._loaded = False
        self._lock = threading.Lock()
        self.records: dict[str, dict] = {}

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            path = self.lookup.base_dir / self.lookup.spec.source(SOURCE)["currency_file"]
            if not path.exists():
                raise ServiceUnavailable(REBUILD_HINT)
            try:
                records = {r["slug"]: r for r in read_jsonl(path)}
                if any(not r.get("name") or not r.get("category") for r in records.values()):
                    raise ValueError("a row has no name or category")
            except (ValueError, KeyError, TypeError, OSError) as exc:
                raise ServiceUnavailable(f"the currency data is unreadable ({type(exc).__name__}); "
                                         "update it with update_data scope currency") from exc
            self.records = records
            self._loaded = True

    # -- one item ----------------------------------------------------------------

    def get_currency(self, name: str) -> dict:
        """One currency item, the items whose effects name it, and its sources."""
        record = self._resolve(name)
        lang = "zh-tw" if is_cjk(name) else "en"
        related = self.related(record, lang)
        result = {"currency": copy.deepcopy(record), "related": related[:MAX_RELATED],
                  "not_in_data": NOT_IN_DATA[lang], "sources": _currency_sources(record)}
        if len(related) > MAX_RELATED:
            result["related_total"] = len(related)
        group = essence_group(record)
        if group:
            result["note"] = ESSENCE_NOTE[lang].format(group=group)
        return result

    def related(self, record: dict, lang: str = "en") -> list[dict]:
        """Other items whose English effect lines name this item as a whole name: "Chaos Orb" is
        found in "your next Chaos Orb", not inside "Greater Chaos Orb". A line naming a kind of
        item ("your next Perfect Essence") is not linked to each item of that kind."""
        self._load()
        pattern = _name_pattern(record["name"])
        folded = record["name"].casefold()
        longer = [_name_pattern(r["name"]) for r in self.records.values()
                  if r["slug"] != record["slug"] and folded in r["name"].casefold()]
        out = []
        for other in self.records.values():
            if other["slug"] == record["slug"]:
                continue
            shown = [_shown_line(other, field, i, lang) for field in LINE_FIELDS
                     for i, line in enumerate(other.get(field) or []) if _names_item(line, pattern, longer)]
            if shown:
                out.append({**_brief_head(other), "lines": shown})
        return out

    # -- lists -------------------------------------------------------------------

    def currency_by(self, category: str | None = None, text: str | None = None, max_level: int | None = None,
                    limit: int = DEFAULT_LIST_LIMIT) -> dict:
        """Items by category, by words in their names, effects, tags or type (either language), and
        by level: drop level and required level at most max_level. With no filter, the categories."""
        self._load()
        for label, value in (("category", category), ("text", text)):
            _cap(value, label)
        category = clean_text(category) if isinstance(category, str) else category
        text = clean_text(text) if isinstance(text, str) else text
        if max_level is not None and (isinstance(max_level, bool) or not isinstance(max_level, int) or max_level < 1):
            raise BadArgument("max_level must be a whole number of at least 1")
        if category in (None, "") and text in (None, "") and max_level is None:
            return {"categories": self.categories(), "not_in_data": NOT_IN_DATA["en"],
                    "note": "give category, text or max_level to list items"}
        chosen = self._category(category) if category not in (None, "") else None
        wanted = clean_text(text).casefold() if text else None
        lang = "zh-tw" if (text and is_cjk(text)) or (category and is_cjk(category)) else "en"
        hits, undated = [], 0
        for record in self.records.values():
            if chosen and record["category"] != chosen:
                continue
            if wanted and not _found(wanted, record):
                continue
            if max_level is not None:
                if record.get("drop_level") is None:
                    undated += 1
                    continue
                if record["drop_level"] > max_level or (record.get("requires_level") or 0) > max_level:
                    continue
            hits.append(_brief(record, lang))
        result = {"filters": {"category": chosen, "text": text, "max_level": max_level}, "total": len(hits),
                  "results": hits[:_limit(limit)], "not_in_data": NOT_IN_DATA[lang]}
        if undated:
            result["without_drop_level"] = undated
        return result

    def categories(self) -> dict[str, int]:
        self._load()
        counts: dict[str, int] = {}
        for record in self.records.values():
            counts[record["category"]] = counts.get(record["category"], 0) + 1
        return counts

    def _category(self, category: str) -> str:
        wanted = clean_text(category).casefold()
        known = self.categories()
        found = CATEGORY_WORDS.get(wanted, wanted)
        if found not in known:
            found = found.rstrip("s") if found.rstrip("s") in known else found
        if found not in known:
            raise BadArgument(f"category must be one of {', '.join(known)} (or 通貨, 精髓, 裂片, 催化劑, 預兆, 符文), "
                              f"not {category!r}")
        return found

    # -- helpers -----------------------------------------------------------------

    def _resolve(self, name: str) -> dict:
        _require(name, "currency name")
        _cap(name, "currency name")
        self._load()
        query = clean_text(name)
        if query in self.records:
            return self.records[query]
        for entity in self.lookup.index.exact(query):
            if entity.kind in CURRENCY_KINDS and entity.slug in self.records:
                return self.records[entity.slug]
        folded = query.casefold()
        for record in self.records.values():
            if folded in ((record.get("name") or "").casefold(), (record.get("name_zh_tw") or "").casefold()):
                return record
        close = [hit["name_en"] for hit in self.lookup.index.find(query, kind="currency", limit=5)]
        hint = f" Close names: {', '.join(close)}." if close else ""
        raise NotFound(f"no currency item matches {query!r}.{hint} Try currency_by with text.")


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def essence_group(record: dict) -> str | None:
    """The modifiers_for group of an essence: perfect essences have their own."""
    if record.get("category") != "essence" or "Essence" not in record.get("name", ""):
        return None
    return ESSENCE_GROUPS["perfect"] if record["name"].startswith("Perfect ") else ESSENCE_GROUPS["essence"]


def _name_pattern(name: str) -> re.Pattern:
    """The name as whole words, also as "Chaos Orbs" and "Chaos Orb's", in any case."""
    return re.compile(rf"(?<![\w'’]){re.escape(name)}(?:s|['’]s)?(?![\w'’])", re.IGNORECASE)


def _names_item(line: str, pattern: re.Pattern, longer: list[re.Pattern]) -> bool:
    """The line names the item somewhere that is not part of a longer item name."""
    covered = [m.span() for p in longer for m in p.finditer(line)]
    return any(not any(start <= m.start() and m.end() <= end for start, end in covered)
               for m in pattern.finditer(line))


def _shown_line(record: dict, field: str, index: int, lang: str) -> str:
    """The line in the answer language: the Chinese line of the same field and place, when that
    field has as many lines in both languages; the English line otherwise."""
    english = record.get(field) or []
    chinese = record.get(f"{field}_zh_tw") or []
    if lang == "zh-tw" and len(chinese) == len(english):
        return chinese[index]
    return english[index]


def _lines(record: dict, lang: str) -> list[str]:
    suffix = "_zh_tw" if lang == "zh-tw" else ""
    return [line for field in LINE_FIELDS for line in record.get(f"{field}{suffix}") or []]


def _found(wanted: str, record: dict) -> bool:
    fields = [record.get("name"), record.get("name_zh_tw"), record.get("type"), record.get("item_class"),
              *(record.get("tags") or []), *_lines(record, "en"), *_lines(record, "zh-tw"),
              *(record.get("properties") or []), *(record.get("properties_zh_tw") or [])]
    return any(wanted in str(field).casefold() for field in fields if field)


def _brief_head(record: dict) -> dict:
    return {"slug": record["slug"], "name": record["name"], "name_zh_tw": record.get("name_zh_tw"),
            "category": record["category"]}


def _brief(record: dict, lang: str) -> dict:
    row = {**_brief_head(record)}
    for key in ("drop_level", "min_modifier_level", "max_item_level", "requires_level", "limit"):
        if record.get(key) is not None:
            row[key] = record[key]
    row["lines"] = _lines(record, lang)[:MAX_BRIEF_LINES] or _lines(record, "en")[:MAX_BRIEF_LINES]
    row["url_en"], row["url_zh_tw"] = record.get("url_en"), record.get("url_zh_tw")
    return row


def _currency_sources(record: dict) -> list[dict]:
    return _sources(record.get("url_en"), record.get("url_zh_tw"), record.get("fetched_at"))
