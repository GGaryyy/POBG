"""
gem_listing.py — Parse poe2db gem listing pages (Skill_Gems / Spirit_Gems / Support_Gems).

Works for any language path: names come out in the page language, slugs and tag slugs are
language-independent.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from bs4 import Tag

from src.catalog.spec import Spec
from src.scrapers.common import clean_text, find_section, make_soup, slug_from_href

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

_TIER_RE = re.compile(r"^\s*\((\d+)\)")
_COLOUR_BY_CLASS = {"gem_red": "str", "gem_green": "dex", "gem_blue": "int", "gem_white": "none"}
_GEM_ANCHOR_ANY = "a[data-hover*='GemEffects_hover']"
_NAV_SLUGS = {"Skill_Gems", "Spirit_Gems", "Support_Gems", "Gem", "Meta_Skill_Gem", "Lineage_Supports"}

# ---------------------------------------------------------------------------
# RECORDS
# ---------------------------------------------------------------------------


@dataclass
class ListingRow:
    slug: str
    name: str
    tier: int | None
    attribute_colour: str | None
    tag_slugs: list[str] = field(default_factory=list)
    tag_names: list[str] = field(default_factory=list)
    row_text: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GemcuttingRow:
    class_name: str
    tier: int
    gem_name: str
    gem_slug: str
    class_slug: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# LISTING
# ---------------------------------------------------------------------------


def parse_listing(html: str, spec: Spec, source: str, lang: str = "en") -> list[ListingRow]:
    """Return one ListingRow per distinct gem slug across the source's universe sections.

    The 'list' section always counts; other sections flagged ``universe: true`` (e.g. the
    support GemTags pane) add gems that the list pane omits. The first occurrence wins, so
    tier/tags come from the list pane whenever it has the gem.
    """
    soup = make_soup(html)
    anchor_sel = spec.selector("gem_anchor", lang)
    tag_sel = spec.selector("tag_anchor", lang)
    rows: dict[str, ListingRow] = {}
    for section_name in _universe_sections(spec, source):
        meta = spec.section(source, section_name)
        section = find_section(soup, meta.get("ids", {}), lang, meta.get("pane_index"))
        if section is None:
            continue
        for anchor in section.select(anchor_sel):
            row = _row_from_anchor(anchor, tag_sel)
            if row is None or row.slug in _NAV_SLUGS or row.slug in rows:
                continue
            rows[row.slug] = row
    return list(rows.values())


def _universe_sections(spec: Spec, source: str) -> list[str]:
    sections = spec.source(source).get("sections", {})
    names = ["list"] if "list" in sections else []
    names += [n for n, meta in sections.items() if n != "list" and isinstance(meta, dict) and meta.get("universe")]
    return names


def _row_from_anchor(anchor: Tag, tag_sel: str) -> ListingRow | None:
    """Build a row from a text anchor plus the siblings that follow it.

    poe2db's listing HTML nests cells irregularly, so the only reliable unit is:
    <a class="gem_*">Name</a> (tier) <div class="gem_tags">tag anchors</div>, read as siblings
    until the next gem anchor.
    """
    slug = slug_from_href(anchor.get("href"))
    if not slug:
        return None
    name = clean_text(anchor.get_text(" ", strip=True))
    if not name:
        return None  # icon-only duplicate anchor; the text anchor follows
    trailing_text, tag_block = _following_siblings(anchor)
    tier_match = _TIER_RE.search(trailing_text)
    tag_anchors = tag_block.select(tag_sel) if tag_block is not None else []
    return ListingRow(
        slug=slug,
        name=name,
        tier=int(tier_match.group(1)) if tier_match else None,
        attribute_colour=_colour(anchor),
        tag_slugs=_dedupe(slug_from_href(a.get("href")) for a in tag_anchors),
        tag_names=_dedupe(clean_text(a.get_text(" ", strip=True)) for a in tag_anchors),
        row_text=_summary_text(trailing_text, tier_match),
    )


def _following_siblings(anchor: Tag) -> tuple[str, Tag | None]:
    """Text after the anchor (up to the next gem anchor) and the first gem_tags block."""
    texts: list[str] = []
    tag_block: Tag | None = None
    for sib in anchor.next_siblings:
        if isinstance(sib, Tag):
            if _is_gem_anchor(sib) or sib.select_one(_GEM_ANCHOR_ANY) is not None:
                break
            if tag_block is None and "gem_tags" in sib.get("class", []):
                tag_block = sib
                continue
            texts.append(sib.get_text(" ", strip=True))
        else:
            texts.append(str(sib))
    return clean_text(" ".join(texts)), tag_block


def _summary_text(after_name: str, tier_match: re.Match | None) -> str | None:
    text = after_name[tier_match.end():] if tier_match else after_name
    text = clean_text(text.strip(" ,"))
    return text or None


def _is_gem_anchor(node: Tag) -> bool:
    return node.name == "a" and "GemEffects_hover" in (node.get("data-hover") or "")


def _colour(anchor: Tag) -> str | None:
    for cls in anchor.get("class", []):
        if cls in _COLOUR_BY_CLASS:
            return _COLOUR_BY_CLASS[cls]
    return None


def _dedupe(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


# ---------------------------------------------------------------------------
# GEMCUTTING
# ---------------------------------------------------------------------------


def parse_gemcutting(html: str, spec: Spec, source: str, lang: str = "en") -> list[GemcuttingRow]:
    """Rows of the Gemcutting table: (class, tier, gems...) → one GemcuttingRow per gem."""
    soup = make_soup(html)
    try:
        section_meta = spec.section(source, "gemcutting")
    except ValueError:
        return []
    section = find_section(soup, section_meta.get("ids", {}), lang, section_meta.get("pane_index"))
    if section is None:
        return []
    anchor_sel = spec.selector("gem_anchor", lang)

    out: list[GemcuttingRow] = []
    seen: set[tuple[str, int, str]] = set()
    for tr in section.select("tr"):
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue
        class_name = clean_text(cells[0].get_text(" ", strip=True))
        tier_text = clean_text(cells[1].get_text(" ", strip=True))
        if not class_name or cells[0].find("a") is None or not tier_text.isdecimal():
            continue  # class rows link to the class page; weapon-set rows do not (any language)
        tier = int(tier_text)
        class_slug = slug_from_href(cells[0].find("a").get("href"))
        for anchor in cells[2].select(anchor_sel):
            name = clean_text(anchor.get_text(" ", strip=True))
            slug = slug_from_href(anchor.get("href"))
            if not name or not slug:
                continue
            key = (class_name, tier, slug)
            if key in seen:
                continue
            seen.add(key)
            out.append(GemcuttingRow(class_name=class_name, tier=tier, gem_name=name, gem_slug=slug,
                                     class_slug=class_slug))
    return out
