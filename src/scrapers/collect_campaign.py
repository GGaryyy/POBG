"""
collect_campaign.py — The campaign, act by act, from poe2db's Act pages and PoB's quest rewards.

    python -m src.scrapers.collect_campaign            # about 26 requests (pages cached)
    python -m src.scrapers.collect_campaign --offline  # cache only

1. The Act index page lists the Act pages in order. An Act page with no areas (a datamined act
   that is not in the game yet) is not a stage. poe2db keeps the Interludes as an Act: the Act
   page whose areas are the Interlude page's areas is named after the Interlude page.
2. Each Act page, in English and Traditional Chinese, gives the area table (level, town,
   waypoint, bosses, what a boss or chest grants), the quest list (type, reward, objective),
   the act map (which areas connect) and the community walkthrough of each area.
3. PoB's QuestRewards.lua gives the permanent rewards (passive points, Spirit, resistances,
   choices), placed in a stage by its Description ("Act 2", "Interlude 1"; anything else, such as
   "Epilog", goes to the last stage).
4. The gem and socket rules: the skill gem level table (required character level per gem level),
   the gemcutting tiers of skill and Spirit gems, the drop level of each Uncut Support Gem level,
   and what each Jeweller's Orb sets the support socket count to, from which drop level.

Writes data/campaign/stages.jsonl, areas.jsonl, quests.jsonl and rules.json. Nothing is written
when a page no longer parses into the expected minimum.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable

import requests
from bs4 import Tag

from src.catalog.spec import INTERLUDE_STAGE, Spec, load_spec
from src.scrapers.common import (
    atomic_write_text,
    cached_fetch,
    clean_text,
    fetch_html,
    make_soup,
    now_iso,
    safe_cache_name,
    slug_from_href,
    write_jsonl,
)
from src.scrapers.item_page import drop_level, item_fields

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / "output" / "cache" / "campaign"
SOURCE = "campaign"
LANGS = ("en", "zh-tw")
AREA_HEADER = "Area"                        # the card header word is English on both languages
QUEST_HEADERS = ("Quest", "任務")
TOWN_ICON = "town"
WAYPOINT_ICON = "waypoint"
BOSS_ICON = "Boss"                          # WorldMapContentBoss / WorldMapContentBossUpgrade
MONSTER_HOVER = "MonsterVarieties"
REWARD_PREFIXES = ("Reward:", "獎勵:", "獎勵：")
JOIN_ARROWS = {"↔"}
STACK_ARROWS = {"↕", "↓", "↑"}
TOWN_SUFFIX = re.compile(r"\s*[(（](?:Town|城鎮)[)）]\s*$")
FIRST_NUMBER = re.compile(r"\d+")
MAX_GUIDE_CHARS = 4000
LUA_FIELD = re.compile(r'\["(\w+)"\]\s*=\s*("(?:[^"\\]|\\.)*"|-?\d+|true|false)')
LUA_OPTIONS_HEAD = re.compile(r'\["Options"\]\s*=\s*\{')
LUA_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
POINTS_STAT = re.compile(r"^\+(\d+) (?:Weapon Set )?Passive Skill Points?$")
SPIRIT_STAT = re.compile(r"^\+(\d+) to Spirit$")
ACT_DESCRIPTION = re.compile(r"^Act (\d+)$")
INTERLUDE_DESCRIPTION = re.compile(r"^Interlude\b")
SOCKETS_TEXT = re.compile(r"(\d+) Support Gem Sockets")
LEVEL_IN_NAME = re.compile(r"\(Level (\d+)\)")
INTERLUDE_MATCH = 0.8                       # share of the Interlude page's areas an Act page must hold
MAX_SUPPORT_PAGES = 10                      # Uncut Support Gem level pages read (there are five)
NOT_FOUND = 404

Fetcher = Callable[[str], str]


class CampaignBuildError(Exception):
    """The pages did not give a usable campaign; nothing is written."""


# ---------------------------------------------------------------------------
# PAGES
# ---------------------------------------------------------------------------


def act_slugs(index_html: str, pattern: str) -> list[str]:
    """The Act page slugs the index links to, in its order, without repeats."""
    wanted = re.compile(pattern)
    found: list[str] = []
    for link in make_soup(index_html).select("a[href]"):
        slug = slug_from_href(link.get("href"))
        if slug and wanted.match(slug) and slug not in found:
            found.append(slug)
    return found


def parse_act_page(html: str) -> dict:
    """{"title", "areas", "quests", "links", "guide"} of one Act (or Interlude) page."""
    soup = make_soup(html)
    cards = soup.select("div.card")
    area_card = _card(cards, (AREA_HEADER,))
    quest_card = _card(cards, QUEST_HEADERS)
    mark = soup.select_one("#markContent")
    title = node_text(mark.select_one("h1")) if mark else None
    return {
        "title": title or _header_label(area_card),
        "areas": parse_areas(area_card) if area_card else [],
        "quests": parse_quests(quest_card) if quest_card else [],
        "links": parse_act_map(mark.select_one("table.actmap")) if mark and mark.select_one("table.actmap") else [],
        "guide": parse_guide(mark) if mark else {},
    }


def _card(cards: list[Tag], words: tuple[str, ...]) -> Tag | None:
    for card in cards:
        header = card.select_one(".card-header")
        text = node_text(header) or ""
        if any(_names(word, text) for word in words) and "Text Audio" not in text:
            return card
    return None


def _names(word: str, text: str) -> bool:
    """An English word must stand alone ("Area", not "Areas"); Chinese has no spaces to look for."""
    if word.isascii():
        return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text) is not None
    return word in text


def _header_label(card: Tag | None) -> str | None:
    text = node_text(card.select_one(".card-header")) if card else None
    return re.sub(rf"\s*{AREA_HEADER}\s*/\d+$", "", text) if text else None


def parse_areas(card: Tag) -> list[dict]:
    """One entry per area slug (the table repeats some areas; the first row wins)."""
    areas: dict[str, dict] = {}
    for row in card.select("table tbody tr"):
        cells = row.select("td")
        link = row.select_one("a.WorldAreas")
        if len(cells) < 3 or link is None:
            continue
        slug = slug_from_href(link.get("href"))
        level = FIRST_NUMBER.search(cells[1].get_text(" ", strip=True))
        if not slug or slug in areas or level is None:
            continue
        icons = " ".join(img.get("alt", "") for img in cells[1].select("img"))
        areas[slug] = {
            "slug": slug,
            "name": node_text(link),
            "level": int(level.group()),
            "town": TOWN_ICON in icons,
            "waypoint": WAYPOINT_ICON in icons,
            **parse_area_content(cells[2]),
        }
    return list(areas.values())


def parse_area_content(cell: Tag) -> dict:
    """Bosses (named in a boss marker), every monster linked, and what the area's content grants."""
    monsters = []
    for link in cell.select("a[href]"):
        if MONSTER_HOVER in (link.get("data-hover") or "") and node_text(link):
            entry = {"name": node_text(link), "slug": slug_from_href(link.get("href"))}
            if entry not in monsters:
                monsters.append(entry)
    bosses, content = [], []
    for block in cell.select(":scope > div"):
        text = node_text(block)
        if not text:
            continue
        content.append(text)
        icon = " ".join(img.get("src", "") for img in block.select("img"))
        named = node_text(block.select_one(".UniqueItem"))
        if BOSS_ICON in icon and named:
            slug = next((m["slug"] for m in monsters if m["name"] == named), None)
            boss = {"name": named, "slug": slug}
            if boss not in bosses:
                bosses.append(boss)
    return {"bosses": bosses, "monsters": monsters, "content": content}


def parse_quests(card: Tag) -> list[dict]:
    """One entry per quest slug; a quest listed for several steps keeps each step's objective."""
    quests: dict[str, dict] = {}
    for entry in card.select("div.col"):
        link = next((a for a in entry.select("a.Quest") if node_text(a)), None)
        if link is None:
            continue
        slug = slug_from_href(link.get("href"))
        if not slug:
            continue
        props = [node_text(p) for p in entry.select("div.property")]
        props = [p for p in props if p]
        reward = next((_after_prefix(p) for p in props if p.startswith(REWARD_PREFIXES)), None)
        objective = node_text(entry.select_one("div.implicitMod"))
        quest = quests.setdefault(slug, {"slug": slug, "name": node_text(link), "type": props[0] if props else None,
                                         "rewards": [], "objectives": []})
        if reward and reward not in quest["rewards"]:
            quest["rewards"].append(reward)
        if objective and objective not in quest["objectives"]:
            quest["objectives"].append(objective)
    return list(quests.values())


def _after_prefix(text: str) -> str:
    for prefix in REWARD_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def parse_act_map(table: Tag) -> list[list[str]]:
    """[[slug, slug], ...]: areas next to each other on the act map. "↔" joins the nearest areas
    left and right of it in its row; "↕" (or "↓", "↑") the nearest above and below in its column."""
    grid: list[list[tuple[str, str] | None]] = []
    for row in table.select("tr"):
        line = []
        for cell in row.find_all("td", recursive=False):
            link = cell.select_one("a[href]")
            text = cell.get_text(" ", strip=True)
            if link is not None and slug_from_href(link.get("href")):
                line.append(("area", slug_from_href(link.get("href"))))
            elif text in JOIN_ARROWS | STACK_ARROWS:
                line.append(("arrow", text))
            else:
                line.append(None)
        grid.append(line)
    pairs: list[list[str]] = []
    for r, line in enumerate(grid):
        for c, cell in enumerate(line):
            if not cell or cell[0] != "arrow":
                continue
            if cell[1] in JOIN_ARROWS:
                ends = (_nearest(grid, r, c, 0, -1), _nearest(grid, r, c, 0, 1))
            else:
                ends = (_nearest(grid, r, c, -1, 0), _nearest(grid, r, c, 1, 0))
            if all(ends) and ends[0] != ends[1] and list(ends) not in pairs:
                pairs.append(list(ends))
    return pairs


def _nearest(grid: list[list], r: int, c: int, dr: int, dc: int) -> str | None:
    r, c = r + dr, c + dc
    while 0 <= r < len(grid) and c >= 0:
        cell = grid[r][c] if c < len(grid[r]) else None
        if cell and cell[0] == "area":
            return cell[1]
        if dc and (c >= len(grid[r]) or cell and cell[0] == "arrow"):
            return None
        r, c = r + dr, c + dc
    return None


def parse_guide(mark: Tag) -> dict[str, str]:
    """{area heading: walkthrough text}: the community text under each area heading."""
    guide: dict[str, list[str]] = {}
    current = None
    for element in mark.find_all(["h2", "p", "ul", "ol"]):
        if element.find_parent("table") is not None:
            continue
        if element.name == "h2":
            current = TOWN_SUFFIX.sub("", node_text(element) or "")
            guide.setdefault(current, [])
        elif current and element.find_parent(["ul", "ol"]) is None:
            text = node_text(element)
            if text:
                guide[current].append(text)
    return {name: "\n".join(lines)[:MAX_GUIDE_CHARS] for name, lines in guide.items() if name and lines}


def node_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = clean_text(node.get_text(" ", strip=True))
    return text or None


# ---------------------------------------------------------------------------
# PoB QUEST REWARDS
# ---------------------------------------------------------------------------


def quest_rewards(text: str) -> list[dict]:
    """Every reward in QuestRewards.lua: description, area, giver, stat or options, points, level."""
    rewards = []
    for block in _top_blocks(text):
        options_body, flat = _options(block)
        fields = {key: _lua_value(value) for key, value in LUA_FIELD.findall(flat)}
        options = [_lua_text(s) for s in LUA_STRING.findall(options_body)]
        stat = fields.get("Stat")
        rewards.append({
            "description": fields.get("Description"),
            "act": fields.get("Act"),
            "area": fields.get("Area"),
            "giver": fields.get("Info"),
            "stat": stat,
            "options": options,
            "passive_points": _int_from(POINTS_STAT, stat) or fields.get("questPoints") or 0,
            "spirit": _int_from(SPIRIT_STAT, stat) or 0,
            "area_level": fields.get("AreaLevel"),
        })
    return [r for r in rewards if r["description"] or r["act"] is not None]


def _top_blocks(text: str) -> list[str]:
    """The entries of the returned table (depth 2), strings and "--" comments skipped."""
    return [text[start:end] for start, end in _tables(text, 2)]


def _options(block: str) -> tuple[str, str]:
    """(the Options table's body, the block without it); the body is "" when there is none."""
    head = LUA_OPTIONS_HEAD.search(block)
    if not head:
        return "", block
    for start, end in _tables(block[head.end() - 1:], 1):
        return block[head.end():head.end() - 1 + end], block[:head.start()] + block[head.end() + end:]
    return "", block


def _tables(text: str, level: int) -> list[tuple[int, int]]:
    """(start, end) of the bodies of the tables at nesting `level`, in order."""
    spans, depth, start, index = [], 0, 0, 0
    in_string = escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif text.startswith("--", index):
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif char == "{":
            depth += 1
            if depth == level:
                start = index + 1
        elif char == "}":
            if depth == level:
                spans.append((start, index))
            depth -= 1
        index += 1
    return spans


def _lua_value(raw: str):
    if raw.startswith('"'):
        return _lua_text(raw[1:-1])
    if raw in ("true", "false"):
        return raw == "true"
    return int(raw)


def _lua_text(raw: str) -> str:
    text = raw.replace("\\n", "\n").replace("\\t", "").replace('\\"', '"')
    return "\n".join(line.strip() for line in text.split("\n"))


def _int_from(pattern: re.Pattern, text: str | None) -> int | None:
    match = pattern.match(text or "")
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# GEM AND SOCKET RULES
# ---------------------------------------------------------------------------


def parse_gem_levels(html: str) -> list[dict]:
    """[{"level", "required_level"}] from the "Tier Level" table of the Uncut Skill Gem page."""
    card = _card(make_soup(html).select("div.card"), ("Tier Level",))
    rows = []
    for row in card.select("tbody tr") if card else []:
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if len(cells) >= 3 and cells[2].isdigit():
            rows.append({"level": int(cells[2]), "required_level": int(cells[0]) if cells[0].isdigit() else 1,
                         "item_skill_sockets": int(cells[1]) if cells[1].isdigit() else None})
    return rows


def parse_cutting_tiers(html: str) -> list[int]:
    """The gem tiers of a gemcutting table (Skill Gems or Spirit Gems), lowest first."""
    card = _card(make_soup(html).select("div.card"), ("Gemcutting",))
    tiers = set()
    for row in card.select("tbody tr") if card else []:
        cells = [c.get_text(" ", strip=True) for c in row.select("td")]
        if len(cells) >= 2 and cells[1].isdigit():
            tiers.add(int(cells[1]))
    return sorted(tiers)


def parse_listing_slugs(html: str) -> list[str]:
    """Page slugs of the leveled items of a class listing (e.g. "Uncut Support Gem (Level 3)"), in page
    order, at most MAX_SUPPORT_PAGES: other links on the page are not followed."""
    found = []
    for link in make_soup(html).select("div.col a[href]"):
        slug = slug_from_href(link.get("href"))
        if slug and LEVEL_IN_NAME.search(node_text(link) or "") and slug not in found:
            found.append(slug)
    return found[:MAX_SUPPORT_PAGES]


def parse_item_page(html: str) -> dict:
    """{"name", "drop_level", "text"} of one item page (its facts box and its mod lines)."""
    fields = item_fields(html)
    return {"name": fields.get("BaseType"), "drop_level": drop_level(fields),
            "text": [t for t in (node_text(n) for n in make_soup(html).select(".explicitMod")) if t]}


# ---------------------------------------------------------------------------
# ASSEMBLY
# ---------------------------------------------------------------------------


def build_stages(pages: list[dict], interlude: dict | None, rewards: list[dict], spec: Spec,
                 fetched_at: str) -> tuple[list[dict], list[dict], list[dict]]:
    """(stages, areas, quests) from the parsed Act pages ({"slug", "en", "zh-tw"} each) and the
    Interlude page. Pages without areas are left out."""
    interlude_areas = {a["slug"] for a in (interlude or {}).get("en", {}).get("areas", [])}
    stages, areas, quests = [], [], []
    for page in pages:
        en, zh = page["en"], page.get("zh-tw") or {}
        if not en["areas"]:
            continue
        slugs = {a["slug"] for a in en["areas"]}
        is_interlude = bool(interlude_areas) and len(slugs & interlude_areas) >= INTERLUDE_MATCH * len(interlude_areas)
        named = interlude if is_interlude else page
        stage_id = INTERLUDE_STAGE if is_interlude else page["slug"].lower()
        stage = _stage(stage_id, len(stages) + 1, named, en, spec, fetched_at)
        stages.append(stage)
        areas += _areas(stage_id, en, zh, spec, fetched_at)
        quests += _quests(stage_id, en, zh, spec, fetched_at)
    _place_rewards(stages, areas, rewards)
    _mark_trials(stages, areas, spec)
    return stages, areas, quests


def _stage(stage_id: str, order: int, named: dict, en: dict, spec: Spec, fetched_at: str) -> dict:
    levels = [a["level"] for a in en["areas"] if not a["town"]] or [a["level"] for a in en["areas"]]
    return {
        "id": stage_id, "order": order, "page": named["slug"],
        "name": named["en"].get("title") or named["slug"].replace("_", " "),
        "name_zh_tw": (named.get("zh-tw") or {}).get("title"),
        "area_level_min": min(levels), "area_level_max": max(levels),
        "areas": [a["slug"] for a in en["areas"]],
        "bosses": [b["name"] for a in en["areas"] for b in a["bosses"]],
        "rewards": [], "trials": [],
        "url_en": spec.resolve_url(named["slug"], "en"), "url_zh_tw": spec.resolve_url(named["slug"], "zh-tw"),
        "fetched_at": fetched_at,
    }


def _areas(stage_id: str, en: dict, zh: dict, spec: Spec, fetched_at: str) -> list[dict]:
    zh_areas = {a["slug"]: a for a in zh.get("areas", [])}
    out = []
    for area in en["areas"]:
        other = zh_areas.get(area["slug"], {})
        zh_bosses = {b["slug"]: b["name"] for b in other.get("bosses", []) if b.get("slug")}
        out.append({
            "slug": area["slug"], "stage": stage_id, "name": area["name"], "name_zh_tw": other.get("name"),
            "level": area["level"], "town": area["town"], "waypoint": area["waypoint"],
            "bosses": [{**b, "name_zh_tw": zh_bosses.get(b["slug"])} for b in area["bosses"]],
            "monsters": [m["name"] for m in area["monsters"]],
            "content": area["content"], "content_zh_tw": other.get("content", []),
            "connects": sorted({b for a, b in en["links"] if a == area["slug"]}
                               | {a for a, b in en["links"] if b == area["slug"]}),
            "guide": en["guide"].get(area["name"]), "guide_zh_tw": zh.get("guide", {}).get(other.get("name")),
            "rewards": [],
            "url_en": spec.resolve_url(area["slug"], "en"), "url_zh_tw": spec.resolve_url(area["slug"], "zh-tw"),
            "fetched_at": fetched_at,
        })
    return out


def _quests(stage_id: str, en: dict, zh: dict, spec: Spec, fetched_at: str) -> list[dict]:
    zh_quests = {q["slug"]: q for q in zh.get("quests", [])}
    out = []
    for quest in en["quests"]:
        other = zh_quests.get(quest["slug"], {})
        out.append({
            "slug": quest["slug"], "stage": stage_id, "name": quest["name"], "name_zh_tw": other.get("name"),
            "type": quest["type"], "type_zh_tw": other.get("type"),
            "rewards": quest["rewards"], "rewards_zh_tw": other.get("rewards", []),
            "objectives": quest["objectives"], "objectives_zh_tw": other.get("objectives", []),
            "url_en": spec.resolve_url(quest["slug"], "en"), "url_zh_tw": spec.resolve_url(quest["slug"], "zh-tw"),
            "fetched_at": fetched_at,
        })
    return out


def _place_rewards(stages: list[dict], areas: list[dict], rewards: list[dict]) -> None:
    """Each PoB reward goes to the stage its Description names and to the area of that name."""
    if not stages:
        return
    by_id = {s["id"]: s for s in stages}
    by_name = {_area_key(a["name"]): a for a in areas}
    for reward in rewards:
        description = reward["description"] or ""
        act = ACT_DESCRIPTION.match(description)
        if act:
            stage = by_id.get(f"act_{act.group(1)}")
        elif INTERLUDE_DESCRIPTION.match(description):
            stage = by_id.get(INTERLUDE_STAGE)
        else:
            stage = None
        entry = {k: reward[k] for k in ("description", "giver", "area", "stat", "options", "passive_points",
                                        "spirit", "area_level")}
        if stage is None:
            stage = stages[-1]                  # "Epilog" and anything newer than these pages
            entry["placed"] = "last stage: its description names no stage on these pages"
        area = by_name.get(_area_key(reward["area"] or ""))
        entry["area_slug"] = area["slug"] if area else None
        stage["rewards"].append(entry)
        if area is not None:
            area["rewards"].append(entry)


def _area_key(name: str) -> str:
    return re.sub(r"^the ", "", name.strip().casefold())


def _mark_trials(stages: list[dict], areas: list[dict], spec: Spec) -> None:
    trials = {t["slug"]: t["points"] for t in spec.source(SOURCE)["ascendancy_trials"]}
    for area in areas:
        if area["slug"] in trials:
            stage = next((s for s in stages if s["id"] == area["stage"]), None)
            if stage is None:
                continue
            stage["trials"].append({"area": area["slug"], "name": area["name"], "name_zh_tw": area["name_zh_tw"],
                                    "area_level": area["level"], "ascendancy_points": trials[area["slug"]]})


def build_rules(skill_html: str, spirit_html: str, support_pages: list[tuple[str, dict]],
                orb_pages: list[tuple[str, dict]], spec: Spec, fetched_at: str) -> dict:
    """The gem and socket rules the stages are judged by, each with its source page."""
    source = spec.source(SOURCE)
    gem_levels = parse_gem_levels(skill_html)
    supports = []
    for slug, page in support_pages:
        level = LEVEL_IN_NAME.search(page["name"] or slug.replace("_", " ").replace("%28", "(").replace("%29", ")"))
        if level and page["drop_level"] is not None:
            supports.append({"level": int(level.group(1)), "drop_level": page["drop_level"], "page": slug})
    orbs = []
    for slug, page in orb_pages:
        sockets = next((int(m.group(1)) for t in page["text"] for m in [SOCKETS_TEXT.search(t)] if m), None)
        if sockets and page["drop_level"] is not None:
            orbs.append({"name": page["name"], "page": slug, "sockets": sockets, "drop_level": page["drop_level"]})
    base_sockets = next((row["item_skill_sockets"] for row in gem_levels if row["item_skill_sockets"]), None)
    return {
        "skill_gem_levels": [{k: row[k] for k in ("level", "required_level")} for row in gem_levels],
        "skill_gem_tiers": parse_cutting_tiers(skill_html),
        "spirit_gem_tiers": parse_cutting_tiers(spirit_html),
        "support_gem_levels": sorted(supports, key=lambda s: s["level"]),
        "base_support_sockets": base_sockets,
        "socket_orbs": sorted(orbs, key=lambda o: o["sockets"]),
        "ascendancy_trials": source["ascendancy_trials"],
        "sources": {
            "skill_gem_levels": spec.resolve_url(source["skill_gem_slug"], "en"),
            "spirit_gem_tiers": spec.resolve_url(source["spirit_gem_slug"], "en"),
            "support_gem_levels": spec.resolve_url(source["support_listing_slug"], "en"),
            "socket_orbs": [spec.resolve_url(slug, "en") for slug in source["socket_orbs"]],
            "ascendancy_trials": [spec.resolve_url(t["slug"], "en") for t in source["ascendancy_trials"]],
            "quest_rewards": spec.source("pob2_tree")["quest_rewards_url"],
        },
        "fetched_at": fetched_at,
    }


def check(stages: list[dict], areas: list[dict], quests: list[dict], rules: dict, spec: Spec,
          interlude_page: bool = False) -> None:
    """Raise CampaignBuildError when the result is below the catalog's minimums, or when the
    Interlude page has areas but no Act page holds them."""
    expect = spec.source(SOURCE)["expect_min"]
    problems = []
    if interlude_page and not any(s["id"] == INTERLUDE_STAGE for s in stages):
        problems.append("no Act page holds the Interlude page's areas")
    if len(stages) < expect["stages"]:
        problems.append(f"{len(stages)} stages (expected at least {expect['stages']})")
    for stage in stages:
        if len(stage["areas"]) < expect["areas_per_stage"]:
            problems.append(f"{stage['id']} has {len(stage['areas'])} areas")
    if len(quests) < expect["quests"]:
        problems.append(f"{len(quests)} quests (expected at least {expect['quests']})")
    if len(rules["skill_gem_levels"]) < expect["skill_gem_levels"]:
        problems.append(f"{len(rules['skill_gem_levels'])} skill gem levels")
    if len(rules["support_gem_levels"]) < expect["support_gem_levels"]:
        problems.append(f"{len(rules['support_gem_levels'])} support gem levels")
    if not rules["base_support_sockets"] or not rules["socket_orbs"]:
        problems.append("no support socket rule")
    if problems:
        raise CampaignBuildError("the campaign pages did not parse as expected: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# COLLECT
# ---------------------------------------------------------------------------


def collect(spec: Spec, *, fetch: Fetcher, cache_dir: Path = CACHE_DIR, offline: bool = False) -> dict:
    """Fetch and parse everything; {"stages", "areas", "quests", "rules"}. Raises CampaignBuildError."""
    source = spec.source(SOURCE)

    def page(slug: str, lang: str = "en") -> str:
        url = spec.resolve_url(slug, lang)
        html = cached_fetch(url, cache_dir / lang / f"{safe_cache_name(slug)}.html", fetch, offline)
        if html is None:
            raise CampaignBuildError(f"{url} is not cached and offline was given")
        return html

    fetched_at = now_iso()
    pages = []
    for slug in act_slugs(page(source["index_slug"]), source["act_slug_pattern"]):
        parsed = {"slug": slug, "en": parse_act_page(page(slug))}
        if parsed["en"]["areas"]:
            parsed["zh-tw"] = parse_act_page(page(slug, "zh-tw"))
        pages.append(parsed)
    interlude = {"slug": source["interlude_slug"], "en": _optional_page(page, source["interlude_slug"])}
    if interlude["en"]["areas"]:
        interlude["zh-tw"] = parse_act_page(page(source["interlude_slug"], "zh-tw"))
    else:
        interlude = None
    rewards_url = spec.source("pob2_tree")["quest_rewards_url"]
    lua = cached_fetch(rewards_url, cache_dir / "QuestRewards.lua", fetch, offline)
    if lua is None:
        raise CampaignBuildError("PoB's QuestRewards.lua is not cached and offline was given")
    stages, areas, quests = build_stages(pages, interlude, quest_rewards(lua), spec, fetched_at)
    supports = [(slug, parse_item_page(page(slug)))
                for slug in parse_listing_slugs(page(source["support_listing_slug"]))]
    orbs = [(slug, parse_item_page(page(slug))) for slug in source["socket_orbs"]]
    rules = build_rules(page(source["skill_gem_slug"]), page(source["spirit_gem_slug"]), supports, orbs, spec,
                        fetched_at)
    check(stages, areas, quests, rules, spec, interlude_page=interlude is not None)
    return {"stages": stages, "areas": areas, "quests": quests, "rules": rules}


def _optional_page(page, slug: str) -> dict:
    """A page that may be gone (1.0 removes the Interludes): parsed, or empty when the site answers 404."""
    try:
        return parse_act_page(page(slug))
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) == NOT_FOUND:
            return {"title": None, "areas": [], "quests": [], "links": [], "guide": {}}
        raise


def write(spec: Spec, base_dir: Path, result: dict) -> None:
    source = spec.source(SOURCE)
    write_jsonl(base_dir / source["stages_file"], result["stages"])
    write_jsonl(base_dir / source["areas_file"], result["areas"])
    write_jsonl(base_dir / source["quests_file"], result["quests"])
    atomic_write_text(base_dir / source["rules_file"], json.dumps(result["rules"], ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the campaign from poe2db and PoB.")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["polite_delay_seconds"]
    try:
        result = collect(spec, fetch=lambda url: fetch_html(url, delay=delay), offline=args.offline)
    except (CampaignBuildError, requests.RequestException) as exc:
        print(f"[ERROR] {exc}; nothing was written", file=sys.stderr)
        return 1
    write(spec, BASE_DIR, result)
    print("=== collect_campaign summary ===")
    for stage in result["stages"]:
        print(f"  {stage['id']}: {stage['name']} / {stage['name_zh_tw']}, areas {len(stage['areas'])}, "
              f"level {stage['area_level_min']}-{stage['area_level_max']}, rewards {len(stage['rewards'])}, "
              f"trials {len(stage['trials'])}")
    print(f"  areas {len(result['areas'])}, quests {len(result['quests'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
