"""
render_charts.py — Draw the command flowcharts in docs/flow/img/ from commands_charts.json.

Run from the repo root (standard library only):

    python docs/flow/render_charts.py

Each chart is a grid: a main column (col 0) and a side column (col 1) for branches. An edge
names its route: "v" straight down, "h" across to the same row, "hv" across then up or down,
"vh" down or up then across, "loop-l" / "loop-r" around the outside of the column.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

HERE = Path(__file__).parent
DATA = HERE / "commands_charts.json"
OUT = HERE / "img"
LANGS = {"zh-TW": "zh", "en": "en"}          # file suffix -> text key in the data
FONT = ('"Segoe UI", "Helvetica Neue", Arial, "Microsoft JhengHei", "PingFang TC", '
        '"Noto Sans TC", "Noto Sans CJK TC", sans-serif')
FONT_SIZE = 14
LABEL_SIZE = 12.5
LINE_HEIGHT = 20
PAD_X = 16
PAD_Y = 10
POINT = 14                                   # how far a decision's left and right points stick out
SIDE_WRAP = 280                              # widest text line in the side column, px
MAIN_WRAP = (380, 560)                       # the main column's text takes what is left, within these
MAX_WIDTH = 1000                             # the whole chart aims to stay within this
GAP_Y = 38
MIN_GAP_X = 64
MARGIN = 20
LANE = 26                                    # distance of a loop's vertical run from the column
WIDE_SCALE = 1.04                            # safety factor on the estimated text width
STYLES = {                                   # kind -> (fill, stroke)
    "start": ("#ddf4ff", "#0969da"),
    "action": ("#f6f8fa", "#8c959f"),
    "decision": ("#fff8c5", "#bf8700"),
    "end": ("#dafbe1", "#1a7f37"),
    "stop": ("#ffebe9", "#cf222e"),
}
TEXT_COLOUR = "#1f2328"
EDGE_COLOUR = "#57606a"
BACKGROUND = "#ffffff"
BORDER = "#d0d7de"
NARROW = set("ilI.,:;'|!")
WIDE = set("mwMW")
THIN = set("-()[]{}/\\\"`")
NO_LINE_START = set("，。、；：？！）」』,.;:?!)")
PHRASE_END = set("，。、；：？！")               # a line prefers to break after one of these,
PHRASE_END_SPACED = set(",.;:?!")             # or after one of these when a space follows


@dataclass
class Box:
    kind: str
    row: int
    col: int
    lines: list[str]
    align: str
    w: float = 0.0
    h: float = 0.0
    x: float = 0.0
    y: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


def char_width(char: str) -> float:
    """Estimated width of one character, in em."""
    if ord(char) >= 0x2E80:
        return 1.0
    if char == " ":
        return 0.3
    if char in NARROW:
        return 0.28
    if char in WIDE:
        return 0.85
    if char in THIN:
        return 0.36
    if char.isupper():
        return 0.66
    return 0.55


def text_width(text: str, size: float = FONT_SIZE) -> float:
    return sum(char_width(c) for c in text) * size * WIDE_SCALE


def tokens(paragraph: str) -> list[str]:
    """Pieces a line may break between: one CJK character, or a run of other characters up to a space."""
    out, word = [], ""
    for char in paragraph:
        if ord(char) >= 0x2E80:
            if word:
                out.append(word)
                word = ""
            out.append(char)
        elif char == " ":
            out.append(word + " ")
            word = ""
        else:
            word += char
    if word:
        out.append(word)
    return out


def wrap(paragraph: str, limit: float) -> list[str]:
    """Lines no wider than the limit, evened out so the last line is not a stray word."""
    lines = fill(paragraph, limit)
    whole = [text_width(phrase.rstrip()) for phrase in phrases(paragraph)]
    low, high = max((w for w in whole if w <= limit), default=0.0), limit     # never split a phrase that fits
    while high - low > 4:                    # the narrowest width that still needs no extra line
        middle = (low + high) / 2
        if len(fill(paragraph, middle)) == len(lines):
            high = middle
        else:
            low = middle
    return fill(paragraph, high)


def phrases(paragraph: str) -> list[str]:
    """The paragraph cut after punctuation, so a line can end where a reader pauses."""
    out, phrase = [], ""
    for index, char in enumerate(paragraph):
        phrase += char
        spaced = char == " " and index > 0 and paragraph[index - 1] in PHRASE_END_SPACED
        if char in PHRASE_END or spaced:
            out.append(phrase)
            phrase = ""
    if phrase:
        out.append(phrase)
    return out


def fill(paragraph: str, limit: float) -> list[str]:
    """Greedy lines of whole phrases; a phrase wider than the limit is broken between words or characters."""
    pieces = []
    for phrase in phrases(paragraph):
        pieces += [phrase] if text_width(phrase.rstrip()) <= limit else tokens(phrase)
    lines, line = [], ""
    for piece in pieces:
        fits = text_width((line + piece).rstrip()) <= limit
        if line and not fits and piece[0] not in NO_LINE_START:
            lines.append(line.rstrip())
            line = piece
        else:
            line += piece
    lines.append(line.rstrip())
    return lines


def box(node: dict, lang: str, limit: float) -> Box:
    lines = [line for part in node[lang].split("\n") for line in wrap(part, limit)]
    out = Box(node["kind"], node["row"], node["col"], lines, node.get("align", "center"))
    extra = POINT if out.kind == "decision" else 0
    out.w = max(text_width(line) for line in lines) + 2 * (PAD_X + extra)
    out.h = len(lines) * LINE_HEIGHT + 2 * PAD_Y
    return out


def boxes(chart: dict, lang: str, taken: float) -> dict[str, Box]:
    """Side column first; the main column's text then gets the width that is left of MAX_WIDTH."""
    side = {n["id"]: box(n, lang, SIDE_WRAP) for n in chart["nodes"] if n["col"] > 0}
    side_width = max((b.w for b in side.values()), default=0.0)
    room = MAX_WIDTH - taken - side_width - 2 * (PAD_X + POINT)
    limit = min(max(room, MAIN_WRAP[0]), MAIN_WRAP[1])
    main = {n["id"]: box(n, lang, limit) for n in chart["nodes"] if n["col"] == 0}
    return {n["id"]: (main | side)[n["id"]] for n in chart["nodes"]}


def label_width(chart: dict, lang: str, routes: tuple[str, ...]) -> float:
    widths = [text_width(e[lang], LABEL_SIZE) for e in chart["edges"] if e["route"] in routes and e.get(lang)]
    return max(widths, default=0.0)


def place(chart: dict, lang: str) -> tuple[dict[str, Box], float, float, float]:
    """Give every box its position. Returns the boxes, the canvas size and the x of the left loop lane."""
    has_left_loop = any(e["route"] == "loop-l" for e in chart["edges"])
    left = MARGIN + (LANE + label_width(chart, lang, ("loop-l",)) + 14 if has_left_loop else 0)
    gap_x = max(MIN_GAP_X, label_width(chart, lang, ("h", "hv", "loop-r")) + 28)
    has_side = any(n["col"] > 0 for n in chart["nodes"])
    nodes = boxes(chart, lang, left + MARGIN + (gap_x if has_side else 0))
    columns = sorted({b.col for b in nodes.values()})
    widths = {c: max(b.w for b in nodes.values() if b.col == c) for c in columns}
    x_of, x = {}, left
    for column in columns:
        x_of[column] = x
        x += widths[column] + gap_x
    y = MARGIN
    for row in sorted({b.row for b in nodes.values()}):
        in_row = [b for b in nodes.values() if b.row == row]
        height = max(b.h for b in in_row)
        for box in in_row:
            box.w = widths[box.col]
            box.x = x_of[box.col]
            box.y = y + (height - box.h) / 2
        y += height + GAP_Y
    last = columns[-1]
    return nodes, x_of[last] + widths[last] + MARGIN, y - GAP_Y + MARGIN, left - LANE


def route(edge: dict, s: Box, d: Box, left_lane: float) -> tuple[list[tuple[float, float]], tuple[float, float, str]]:
    """The edge's corner points, and where its label goes: (x, y, text-anchor)."""
    kind = edge["route"]
    if kind == "v":
        return [(s.cx, s.bottom), (d.cx, d.y)], (s.cx + 8, s.bottom + 16, "start")
    if kind == "h":
        return [(s.right, s.cy), (d.x, d.cy)], ((s.right + d.x) / 2, s.cy - 7, "middle")
    if kind == "hv":
        end = d.y if d.cy > s.cy else d.bottom
        return [(s.right, s.cy), (d.cx, s.cy), (d.cx, end)], (s.right + 8, s.cy - 7, "start")
    if kind == "vh":
        down = d.cy > s.cy
        start = s.bottom if down else s.y
        side = d.right if s.cx > d.cx else d.x
        return [(s.cx, start), (s.cx, d.cy), (side, d.cy)], (s.cx + 8, start + 16 if down else start - 8, "start")
    if kind == "loop-l":
        return ([(s.x, s.cy), (left_lane, s.cy), (left_lane, d.cy), (d.x, d.cy)],
                (left_lane - 8, s.cy + 4, "end"))
    if kind == "loop-r":
        lane = max(s.right, d.right) + LANE
        return ([(s.right, s.cy), (lane, s.cy), (lane, d.cy), (d.right, d.cy)],
                (lane + 8, s.cy + 4, "start"))
    raise ValueError(f"unknown route {kind!r}")


def shape(box: Box) -> str:
    fill, stroke = STYLES[box.kind]
    look = f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"'
    if box.kind == "decision":
        x, y, w, h = box.x, box.y, box.w, box.h
        points = [(x + POINT, y), (x + w - POINT, y), (x + w, y + h / 2), (x + w - POINT, y + h),
                  (x + POINT, y + h), (x, y + h / 2)]
        return f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in points)}" {look}/>'
    radius = min(box.h / 2, 22) if box.kind in ("start", "end", "stop") else 6
    return (f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="{radius:.1f}" {look}/>')


def text(box: Box) -> str:
    left = box.align == "left"
    x = box.x + PAD_X if left else box.cx
    anchor = "start" if left else "middle"
    first = box.y + PAD_Y + LINE_HEIGHT * 0.72
    return "".join(f'<text x="{x:.1f}" y="{first + i * LINE_HEIGHT:.1f}" text-anchor="{anchor}">{escape(line)}</text>'
                   for i, line in enumerate(box.lines))


def svg(chart: dict, lang: str) -> str:
    nodes, width, height, left_lane = place(chart, lang)
    lines, labels = [], []
    for edge in chart["edges"]:
        points, (x, y, anchor) = route(edge, nodes[edge["from"]], nodes[edge["to"]], left_lane)
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        lines.append(f'<polyline points="{path}" fill="none" stroke="{EDGE_COLOUR}" stroke-width="1.5" '
                     f'stroke-linejoin="round" marker-end="url(#arrow)"/>')
        if edge.get(lang):
            labels.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-size="{LABEL_SIZE}" '
                          f'font-weight="600" fill="{EDGE_COLOUR}" stroke="{BACKGROUND}" stroke-width="4" '
                          f'stroke-linejoin="round" paint-order="stroke">{escape(edge[lang])}</text>')
    body = "".join(shape(box) + text(box) for box in nodes.values())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}" font-family=\'{FONT}\' font-size="{FONT_SIZE}" '
            f'fill="{TEXT_COLOUR}">\n'
            f'<title>{escape(chart["title"][lang])}</title>\n'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{EDGE_COLOUR}"/></marker></defs>\n'
            f'<rect x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1:.0f}" rx="8" '
            f'fill="{BACKGROUND}" stroke="{BORDER}"/>\n'
            f'{"".join(lines)}\n{body}\n{"".join(labels)}\n</svg>\n')


def main() -> None:
    charts = json.loads(DATA.read_text(encoding="utf-8"))["charts"]
    OUT.mkdir(exist_ok=True)
    for chart in charts:
        for suffix, lang in LANGS.items():
            target = OUT / f'{chart["id"]}.{suffix}.svg'
            target.write_text(svg(chart, lang), encoding="utf-8", newline="\n")
    print(f"{len(charts) * len(LANGS)} charts written to {OUT}")


if __name__ == "__main__":
    main()
