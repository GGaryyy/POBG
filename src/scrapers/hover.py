"""
hover.py — poe2db hover snippets (tiny CDN HTML fragments) and keyword-link extraction.

poe2db decorates every in-text term with <a class="KeywordPopups" href="<Slug>" data-hover=
".../Poe_Data_KeywordPopups_hover/<hash>">. The hover URL returns a ~1 KB fragment with the
official explanation, which is far cheaper than the ~1.7 MB keyword page.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from bs4 import Tag

from src.catalog.spec import Spec
from src.scrapers.common import clean_text, make_soup, slug_from_href

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

_HASH_CHARS = set("0123456789abcdef")

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# KEYWORD REFERENCES
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordRef:
    slug: str
    hash: str | None
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


def hover_hash(url: str | None) -> str | None:
    """Last path segment of a cdn.poe2db.tw hover URL, if it looks like a hex hash."""
    if not url:
        return None
    candidate = url.rstrip("/").rsplit("/", 1)[-1]
    return candidate if candidate and set(candidate) <= _HASH_CHARS else None


def keyword_refs(node: Tag | None, spec: Spec) -> list[KeywordRef]:
    """Glossary links inside node, in document order, de-duplicated by slug.

    GemTags / ItemClasses anchors share the KeywordPopups class but are tags and weapon
    classes, not glossary terms, so they are skipped.
    """
    if node is None:
        return []
    excluded = set(spec.selector("keyword_anchor_exclude_classes"))
    refs: dict[str, KeywordRef] = {}
    for a in node.select(spec.selector("keyword_anchor")):
        if excluded & set(a.get("class", [])):
            continue
        slug = slug_from_href(a.get("href"))
        if not slug or slug in refs:
            continue
        refs[slug] = KeywordRef(slug=slug, hash=hover_hash(a.get("data-hover")), text=clean_text(a.get_text(" ", strip=True)))
    return list(refs.values())


def acronym_slugs(soup, spec: Spec) -> list[str]:
    """Keyword slugs from the gem attribute table's Acronym row (plain /us/<Slug> links)."""
    key = spec.selector("attribute_acronym_key")
    for tr in soup.select("table tr"):
        cells = tr.find_all("td")
        if len(cells) >= 2 and clean_text(cells[0].get_text(" ", strip=True)) == key:
            return [s for s in (slug_from_href(a.get("href")) for a in cells[1].select("a[href]")) if s]
    return []


# ---------------------------------------------------------------------------
# KEYWORD HOVER
# ---------------------------------------------------------------------------


def parse_keyword_hover(html: str, spec: Spec) -> dict | None:
    """{'slug', 'name', 'text', 'refs'} from a KeywordPopups hover fragment, or None if empty."""
    soup = make_soup(html)
    title = soup.select_one(spec.selector("keyword_hover_title"))
    body = soup.select_one(spec.selector("keyword_hover_body"))
    if title is None or body is None:
        return None
    for br in body.find_all("br"):
        br.replace_with("\n")
    text = "\n".join(clean_text(line) for line in body.get_text("").split("\n"))
    text = "\n".join(line for line in text.split("\n") if line) or None
    return {
        "slug": slug_from_href(title.get("href")),
        "name": clean_text(title.get_text(" ", strip=True)) or None,
        "text": text,
        "refs": keyword_refs(body, spec),
    }


def keyword_hover_url(spec: Spec, lang: str, hash_: str) -> str:
    return spec.raw["url_patterns"]["keyword_hover"].format(lang_path=spec.lang_path(lang), hash=hash_)
