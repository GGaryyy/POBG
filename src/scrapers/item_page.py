"""
item_page.py — The facts box of one poe2db item page (DropLevel, BaseType, Class, Tags, Type, ...).

poe2db shows them as name/value cards (div.card.name-value); older pages used two-cell table rows
inside a card. Both are read, the first value of a name wins.
"""

from __future__ import annotations

from src.scrapers.common import clean_text, make_soup

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

CARD_SELECTOR = "div.card.name-value"
ROW_SELECTOR = "div.card table tbody tr"


def item_fields(html: str) -> dict[str, str]:
    """{name: value} of the page's facts box, e.g. {"DropLevel": "12", "Class": "Stackable Currency"}."""
    soup = make_soup(html)
    fields: dict[str, str] = {}
    for card in soup.select(CARD_SELECTOR):
        name, value = card.select_one(".name"), card.select_one(".value")
        if name is not None and value is not None:
            _keep(fields, name.get_text(" ", strip=True), value.get_text(" ", strip=True))
    for row in soup.select(ROW_SELECTOR):
        cells = row.select("td")
        if len(cells) == 2:
            _keep(fields, cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))
    return fields


def drop_level(fields: dict[str, str]) -> int | None:
    value = fields.get("DropLevel", "")
    return int(value) if value.isascii() and value.isdigit() else None


def _keep(fields: dict[str, str], name: str, value: str) -> None:
    name, value = clean_text(name), clean_text(value)
    if name and value and name not in fields:
        fields[name] = value
