"""
passive_listing.py — Parse the poe2db Keystone / Notable listing cards.

Each card holds one named node: text anchor (slug + hover hash), stat lines and the keyword
links inside them. Works for any language; slugs are language-independent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bs4 import Tag

from src.catalog.spec import Spec
from src.scrapers.common import clean_text, find_section, make_soup, slug_from_href
from src.scrapers.hover import KeywordRef, hover_hash, keyword_refs

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

PASSIVE_SOURCES = {"passive_keystones": "Keystone", "passive_notables": "Notable"}

# ---------------------------------------------------------------------------
# RECORDS
# ---------------------------------------------------------------------------


@dataclass
class PassiveCard:
    slug: str
    name: str
    node_type: str
    timeless: bool
    hover_hash: str | None
    stats: list[str] = field(default_factory=list)
    keywords: list[KeywordRef] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["keywords"] = [k.as_dict() for k in self.keywords]
        return data


# ---------------------------------------------------------------------------
# PARSING
# ---------------------------------------------------------------------------


def parse_passive_listing(html: str, spec: Spec, source: str, lang: str = "en") -> list[PassiveCard]:
    """All cards of the source's list (regular) and timeless sections, first occurrence per slug."""
    soup = make_soup(html)
    node_type = PASSIVE_SOURCES[source]
    cards: dict[str, PassiveCard] = {}
    for section_name, meta in spec.source(source)["sections"].items():
        pane = find_section(soup, meta.get("ids", {}), lang, meta.get("pane_index"))
        if pane is None:
            continue
        timeless = section_name != "list"
        for card in pane.select(spec.selector("passive_card")):
            parsed = _parse_card(card, spec, node_type, timeless)
            if parsed is not None and parsed.slug not in cards:
                cards[parsed.slug] = parsed
    return list(cards.values())


def _parse_card(card: Tag, spec: Spec, node_type: str, timeless: bool) -> PassiveCard | None:
    anchor = _text_anchor(card)
    if anchor is None:
        return None
    slug = slug_from_href(anchor.get("href"))
    name = clean_text(anchor.get_text(" ", strip=True))
    if not slug or not name:
        return None
    stats_nodes = card.select(spec.selector("passive_card_stats"))
    stats = [line for node in stats_nodes for line in _split_lines(node)]
    keywords: list[KeywordRef] = []
    for node in stats_nodes:
        keywords.extend(k for k in keyword_refs(node, spec) if k.slug not in {x.slug for x in keywords})
    return PassiveCard(slug=slug, name=name, node_type=node_type, timeless=timeless,
                       hover_hash=hover_hash(anchor.get("data-hover")), stats=stats, keywords=keywords)


def _text_anchor(card: Tag) -> Tag | None:
    """The anchor that carries the node name (the icon anchor has no text)."""
    for a in card.select("a[data-hover][href]"):
        hover = a.get("data-hover") or ""
        if "PassiveSkills_hover" in hover and clean_text(a.get_text(" ", strip=True)):
            return a
    return None


def _split_lines(node: Tag) -> list[str]:
    for br in node.find_all("br"):
        br.replace_with("\n")
    lines = (clean_text(part) for part in node.get_text("").split("\n"))
    return [line for line in lines if line]
