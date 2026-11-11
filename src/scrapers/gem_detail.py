"""
gem_detail.py — Parse a poe2db gem detail page into one unified record.

The same parser serves skill, spirit and support gems: the canonical popup
(.newItemPopup.GemPopup, index 0) has the same structure for all three.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from src.catalog.spec import Spec
from src.scrapers.common import clean_text, make_soup, node_text, now_iso, parse_range, slug_from_href
from src.scrapers.hover import acronym_slugs, keyword_refs

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SECTION_BY_KIND = {
    "skill_gem": "SkillGemsDetail",
    "spirit_gem": "SpiritGemsDetail",
    "support_gem": "SupportGemsDetail",
}
_RESERVED_PROPERTY_PREFIXES = ("Tier:", "Level:", "Cost:", "Reservation:", "Category")
_LEVEL_REQ_RE = re.compile(r"Level\s*(\([^)]*\)|\d+)")
_MANA_MULT_RE = re.compile(r"Mana\s*:\s*(\d+(?:\.\d+)?\s*%)")
_ATTRIBUTE_FIELDS = ("Id", "BaseType", "Class", "ItemType", "ActiveSkillsCode")

# ---------------------------------------------------------------------------
# PUBLIC
# ---------------------------------------------------------------------------


def parse_detail(html: str, spec: Spec, slug: str, kind: str, lang: str = "en") -> dict:
    """Parse one detail page. Always returns the full schema; missing values are None."""
    if kind not in SECTION_BY_KIND:
        raise ValueError(f"unknown gem kind {kind!r}; expected one of {sorted(SECTION_BY_KIND)}")
    soup = make_soup(html)
    url = spec.resolve_url(slug, lang)
    record = _empty_record(slug, kind, lang, url, spec)
    warnings: list[str] = []

    popups = soup.select(spec.selector("popup"))
    popup_index = spec.source("gem_detail").get("popup_index", 0)
    popup = popups[popup_index] if 0 <= popup_index < len(popups) else None
    if popup is None:
        warnings.append("no_popup")
    else:
        _fill_from_popup(record, popup, spec, kind, warnings)

    level_table = _find_level_table(soup, spec)
    record["level_effects"] = _parse_level_effects(level_table)
    if kind == "support_gem" and record["cost"] is None:
        implicit_table = _find_implicit_table(soup, spec)
        if implicit_table is not None:
            record["cost"] = _mana_multiplier(implicit_table)

    attributes = _parse_attribute_table(soup, spec)
    record["game_id"] = attributes.get("Id")
    record["item_type"] = attributes.get("ItemType")
    record["keyword_slugs"] = _keyword_slugs(popup, soup, spec)
    if kind != "support_gem":
        record["supported_by"] = _supported_by(soup, spec)

    if record["name"] is None:
        record["name"] = slug.replace("_", " ")
        warnings.append("name_from_slug")
    record["parse_warnings"] = warnings
    record["fetched_at"] = now_iso()
    return record


# ---------------------------------------------------------------------------
# POPUP
# ---------------------------------------------------------------------------


def _fill_from_popup(record: dict, popup: Tag, spec: Spec, kind: str, warnings: list[str]) -> None:
    record["name"] = node_text(popup.select_one(spec.selector("popup_name")))
    record["typeline"] = node_text(popup.select_one(spec.selector("popup_typeline")))
    content = popup.select_one(spec.selector("popup_content"))
    if content is None:
        warnings.append("no_popup_content")
        return

    props = content.select(spec.selector("property"))
    record["tags"] = _tags(props, record["typeline"], spec)
    _fill_properties(record, props, kind)

    reqs = content.select(spec.selector("requirements"))
    _fill_requirements(record, reqs, spec)

    record["description"] = node_text(content.select_one(spec.selector("description")))
    visible, hidden = _split_hidden(content.select(spec.selector("explicit_mod")), spec)
    record["extra_properties"] = visible
    record["hidden_stats"] = hidden
    quality = [t for t in (node_text(d) for d in content.select(spec.selector("quality_mod"))) if t]
    record["quality_effects"] = " | ".join(quality) if quality else None


def _split_hidden(mods: list[Tag], spec: Spec) -> tuple[list[str], list[str]]:
    """Separate player-facing stat lines from poe2db's collapsed internal stat ids."""
    hidden_sel = spec.selector("hidden_stat")
    visible: list[str] = []
    hidden: list[str] = []
    for div in mods:
        text = node_text(div)
        if not text:
            continue
        (hidden if div.select_one(hidden_sel) is not None else visible).append(text)
    return visible, hidden


def _tags(props: list[Tag], typeline: str | None, spec: Spec) -> list[str]:
    tags: list[str] = []
    if props:
        tags = [clean_text(a.get_text(" ", strip=True)) for a in props[0].select(spec.selector("gem_tags"))]
    if typeline and typeline not in tags:
        tags.insert(0, typeline)
    return [t for t in tags if t]


def _fill_properties(record: dict, props: list[Tag], kind: str) -> None:
    for div in props:
        raw = node_text(div)
        if not raw or ":" not in raw:
            continue
        label, value = (part.strip() for part in raw.split(":", 1))
        if label == "Tier":
            record["tier"] = _int_or_none(value)
        elif label == "Level":
            record["level_range"] = parse_range(value)
        elif label in ("Cost", "Reservation"):
            record["cost"] = value or None
        elif label == "Category":
            record["category"] = value or None
        elif record["main_stat"] is None and not raw.startswith(_RESERVED_PROPERTY_PREFIXES):
            record["main_stat"] = f"{label}: {value}" if value else None


def _fill_requirements(record: dict, reqs: list[Tag], spec: Spec) -> None:
    item_class_sel = spec.selector("item_classes")
    for div in reqs:
        text = node_text(div)
        if not text:
            continue
        level_match = _LEVEL_REQ_RE.search(text)
        if level_match:
            record["requires_level"] = _level_requirement(level_match.group(1))
            rest = text[level_match.end():].strip(" ,")
            record["requires_stats"] = _strip_weapon_names(rest, div, item_class_sel) or None
        elif text.startswith("Support Requirements"):
            record["requires_stats"] = text.partition(":")[2].strip() or None
        weapons = [clean_text(a.get_text(" ", strip=True)) for a in div.select(item_class_sel)]
        if weapons:
            record["requires_weapons"] = weapons
        elif level_match is None and text.startswith("Requires:"):
            plain = text.partition(":")[2].strip()
            record["requires_weapons"] = [w.strip() for w in plain.split(",") if w.strip()] or None


def _strip_weapon_names(text: str, div: Tag, item_class_sel: str) -> str:
    """Drop weapon-class names when they share a requirements div with the level/stat text."""
    for a in div.select(item_class_sel):
        text = text.replace(clean_text(a.get_text(" ", strip=True)), "")
    return clean_text(text.strip(" ,"))


# ---------------------------------------------------------------------------
# TABLES
# ---------------------------------------------------------------------------


def _keyword_slugs(popup: Tag | None, soup: BeautifulSoup, spec: Spec) -> list[str]:
    """Glossary terms from the popup text plus the attribute table's Acronym row."""
    slugs = [ref.slug for ref in keyword_refs(popup, spec)]
    slugs += [s for s in acronym_slugs(soup, spec) if s not in slugs]
    return slugs


def _supported_by(soup: BeautifulSoup, spec: Spec) -> list[str]:
    pane = soup.select_one(spec.selector("supported_by_pane"))
    if pane is None:
        return []
    slugs: list[str] = []
    for a in pane.select(spec.selector("gem_anchor")):
        slug = slug_from_href(a.get("href"))
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def _find_level_table(soup: BeautifulSoup, spec: Spec) -> Tag | None:
    wanted = list(spec.selector("level_table_headers"))
    for table in soup.select("table"):
        headers = [clean_text(th.get_text(" ", strip=True)) for th in table.select("th")]
        if headers[: len(wanted)] == wanted:
            return table
    return None


def _find_implicit_table(soup: BeautifulSoup, spec: Spec) -> Tag | None:
    wanted = spec.selector("implicit_table_header")
    for table in soup.select("table"):
        headers = [clean_text(th.get_text(" ", strip=True)) for th in table.select("th")]
        if headers == [wanted]:
            return table
    return None


def _parse_level_effects(table: Tag | None) -> list[dict]:
    if table is None:
        return []
    headers = [clean_text(th.get_text(" ", strip=True)) for th in table.select("th")]
    rows: list[dict] = []
    for tr in table.select("tr"):
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all("td")]
        if len(cells) < 2 or not cells[0].isdecimal():
            continue
        rows.append({headers[i] if i < len(headers) else f"col{i}": cells[i] for i in range(len(cells))})
    return rows


def _mana_multiplier(table: Tag) -> str | None:
    """Support gems show their mana multiplier as the first cell of the 'Implicit' table."""
    for td in table.select("td"):
        match = _MANA_MULT_RE.match(clean_text(td.get_text(" ", strip=True)))
        if match:
            return f"Mana: {match.group(1).replace(' ', '')}"
    return None


def _parse_attribute_table(soup: BeautifulSoup, spec: Spec) -> dict[str, str]:
    key_name = spec.selector("attribute_table_key")
    for table in soup.select("table"):
        pairs: dict[str, str] = {}
        for tr in table.select("tr"):
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and cells[0] in _ATTRIBUTE_FIELDS:
                pairs[cells[0]] = cells[1]
        if key_name in pairs:
            return pairs
    return {}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _level_requirement(token: str) -> list[int | float] | None:
    """'(1 — 90)' → [1, 90]; a bare '65' (fixed-level gems) → [65, 65]."""
    if token.startswith("("):
        return parse_range(token)
    return [int(token), int(token)]


def _int_or_none(text: str) -> int | None:
    match = re.match(r"\d+", text)
    return int(match.group(0)) if match else None


def _empty_record(slug: str, kind: str, lang: str, url: str, spec: Spec) -> dict:
    return {
        "name": None,
        "href": url,
        "tags": [],
        "tier": None,
        "level_range": None,
        "cost": None,
        "main_stat": None,
        "requires_level": None,
        "requires_stats": None,
        "requires_weapons": None,
        "description": None,
        "extra_properties": [],
        "hidden_stats": [],
        "quality_effects": None,
        "summary": None,
        "section": SECTION_BY_KIND[kind],
        "source_url": url,
        "fetched_at": None,
        "slug": slug,
        "kind": kind,
        "lang": lang,
        "url_zh_tw": spec.resolve_url(slug, "zh-tw"),
        "typeline": None,
        "tag_slugs": [],
        "attribute_colour": None,
        "game_id": None,
        "item_type": None,
        "category": None,
        "level_effects": [],
        "keyword_slugs": [],
        "supported_by": [],
        "parse_warnings": [],
    }
