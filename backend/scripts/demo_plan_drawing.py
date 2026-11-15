"""The demo floor plans, drawn as a room schedule (docs/plan-layers.md, "The demos"): the building's fabric, its column
grid with axis bubbles, each room in the colour of what it is for, with its name in a label that fits inside it, its
number and area, doors, shielding around a bunker, north and a scale bar.

The geometry is the drawing's own and does not move: rooms, the beam axis and north stay at the same plan pixels, so
every point, outline and rack placed on the plan stays where it was. Only how it is drawn changes.

`redraw(svg)` reads either a first-generation demo drawing (a building rectangle, then for each room a rectangle with
its name and number) or one drawn here (the model is kept in its <desc>), so running it again changes nothing.
Synthetic demo plans only: no real building is drawn here.
"""
from __future__ import annotations

import html
import json
import re

MARK = "argus-demo-plan/2"
FONT = "Helvetica, Arial, sans-serif"
PX_PER_M = 10                                             # the demos' scale, written on every drawing

# What a room is for, by its name, and its colour (fill, edge).
USES = [
    (("bunker", "tunnel", "vault", "linac"), ("#f6dede", "#b45f5f")),
    (("klystron", "rf", "modulator"), ("#f4ecc8", "#a08a3c")),
    (("laser",), ("#e6e0f5", "#7c6aa8")),
    (("control", "operations", "noc"), ("#d6eedf", "#4f8a63")),
    (("electrical", "power", "ups", "switchboard"), ("#f3e3a6", "#a1842a")),
    (("server", "data hall", "network", "mdf", "idf", "comms"), ("#d7e4f3", "#55779c")),
    (("plant", "utilities", "cooling", "pump", "chiller", "boiler", "mechanical"), ("#f3dcc8", "#a7764d")),
    (("corridor", "circulation", "lobby", "hall"), ("#e4e8ee", "#7b8794")),
    (("office", "reception", "meeting", "library", "reading", "study", "lab"), ("#dfeaf5", "#6683a3")),
    (("store", "storage", "spares", "workshop"), ("#e9e4dc", "#8b7f6c")),
]
DEFAULT = ("#e8edf3", "#6b7a8c")


def _use(name: str) -> tuple[str, str]:
    n = name.lower()
    for words, colours in USES:
        if any(re.search(rf"\b{re.escape(w)}", n) for w in words):
            return colours
    return DEFAULT


def _num(s: str) -> float:
    return float(s)


def _attrs(tag: str) -> dict[str, str]:
    return dict(re.findall(r'([\w-]+)="([^"]*)"', tag))


def read(svg: str) -> dict:
    """The drawing's model: size, building, rooms, beam lines, north, title."""
    kept = re.search(r"<desc>(.*?)</desc>", svg, re.S)
    if kept and MARK in svg:
        return json.loads(html.unescape(kept.group(1)))
    root = _attrs(re.search(r"<svg[^>]*>", svg).group(0))
    w, h = (_num(v) for v in root["viewBox"].split()[2:])
    model: dict = {"width": w, "height": h, "rooms": [], "lines": [], "north": None, "title": "", "note": ""}
    items = re.findall(r"(<rect[^>]*/>|<text[^>]*>[^<]*</text>|<polyline[^>]*/>|<g transform=\"translate\([^)]*\)\">)", svg)
    i = 0
    while i < len(items):
        it = items[i]
        if it.startswith("<rect"):
            a = _attrs(it)
            if a.get("stroke") == "#0f172a":
                model["building"] = [_num(a["x"]), _num(a["y"]), _num(a["width"]), _num(a["height"])]
            elif a.get("stroke") == "#334155":
                texts = []
                while i + 1 < len(items) and items[i + 1].startswith("<text") and len(texts) < 2:
                    i += 1
                    texts.append(html.unescape(re.sub(r"<[^>]*>", "", items[i])))
                model["rooms"].append({"box": [_num(a["x"]), _num(a["y"]), _num(a["width"]), _num(a["height"])],
                                       "name": texts[0] if texts else "", "number": texts[1] if len(texts) > 1 else ""})
        elif it.startswith("<polyline"):
            a = _attrs(it)
            pts = [[_num(v) for v in p.split(",")] for p in a["points"].split()]
            label = ""
            if i + 1 < len(items) and items[i + 1].startswith("<text") and _attrs(items[i + 1]).get("fill") == a["stroke"]:
                i += 1
                label = html.unescape(re.sub(r"<[^>]*>", "", items[i]))
            model["lines"].append({"points": pts, "colour": a["stroke"], "dashed": bool(a.get("stroke-dasharray")),
                                   "label": label})
        elif it.startswith("<g transform"):
            x, y = (_num(v) for v in re.search(r"translate\(([^)]*)\)", it).group(1).split(","))
            model["north"] = [x, y]
            i += 1                                               # its N
        elif it.startswith("<text"):
            t = html.unescape(re.sub(r"<[^>]*>", "", it))
            a = _attrs(it)
            if a.get("font-weight") == "bold" and not model["title"]:
                model["title"] = t
            elif not model["note"]:
                model["note"] = t
        i += 1
    model.setdefault("building", [2, 2, w - 4, h - 64])
    return model


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _fit(name: str, width: float, height: float) -> tuple[float, list[str]]:
    """The largest size (5.5–10) at which the name fits the room in at most three lines."""
    words = name.upper().split()
    for fs in (10, 9, 8, 7, 6.5, 6, 5.5):
        per = fs * 0.64                                         # a bold capital's width, roughly
        room = max(width - 12, 10)
        lines: list[str] = []
        for wd in words:
            if lines and len(lines[-1] + " " + wd) * per <= room:
                lines[-1] += " " + wd
            else:
                lines.append(wd)
        if len(lines) <= 3 and all(len(ln) * per <= room for ln in lines) and len(lines) * fs * 1.2 + 8 <= height * 0.7:
            return fs, lines
    return 5.5, [name.upper()]


def _crosses(points: list, x: float, y: float, w: float, h: float) -> bool:
    """Whether a polyline passes through a box (sampled along each segment)."""
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        for k in range(21):
            px, py = x0 + (x1 - x0) * k / 20, y0 + (y1 - y0) * k / 20
            if x <= px <= x + w and y <= py <= y + h:
                return True
    return False


def draw(m: dict) -> str:
    W, H = m["width"], m["height"]
    bx, by, bw, bh = m["building"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:g} {H:g}" width="{W:g}" height="{H:g}">',
           f"<desc>{_esc(json.dumps(m, separators=(',', ':')))}</desc>",
           f"<!-- {MARK}: synthetic demo plan, redrawn by backend/scripts/demo_plan_drawing.py -->",
           "<defs>"
           '<pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
           '<rect width="5" height="5" fill="#d9d4cc"/><line x1="0" y1="0" x2="0" y2="5" stroke="#8f8578" stroke-width="1.4"/>'
           "</pattern>"
           '<pattern id="ground" width="8" height="8" patternUnits="userSpaceOnUse">'
           '<rect width="8" height="8" fill="#f3f5f8"/><circle cx="1" cy="1" r="0.5" fill="#dde3ea"/></pattern>'
           "</defs>",
           f'<rect x="0" y="0" width="{W:g}" height="{H:g}" fill="url(#ground)"/>']
    # The building: its fabric, a double outer wall.
    out.append(f'<rect x="{bx:g}" y="{by:g}" width="{bw:g}" height="{bh:g}" fill="#eceff3" stroke="#1f2937" stroke-width="4"/>')
    out.append(f'<rect x="{bx + 3.5:g}" y="{by + 3.5:g}" width="{bw - 7:g}" height="{bh - 7:g}" fill="none" '
               'stroke="#1f2937" stroke-width="0.8"/>')
    # The column grid every 5 m, with its axes: numbers along the top, letters up the left side.
    step = 5 * PX_PER_M
    grid = []
    xs = [bx + step * k for k in range(1, int(bw // step) + 1) if bx + step * k < bx + bw - 4]
    ys = [by + step * k for k in range(1, int(bh // step) + 1) if by + step * k < by + bh - 4]
    for x in xs:
        grid.append(f'<line x1="{x:g}" y1="{by + 4:g}" x2="{x:g}" y2="{by + bh - 4:g}"/>')
    for y in ys:
        grid.append(f'<line x1="{bx + 4:g}" y1="{y:g}" x2="{bx + bw - 4:g}" y2="{y:g}"/>')
    out.append('<g stroke="#c7cfd9" stroke-width="0.5" stroke-dasharray="3 3">' + "".join(grid) + "</g>")
    for x in xs:
        for y in ys:
            out.append(f'<rect x="{x - 1.6:g}" y="{y - 1.6:g}" width="3.2" height="3.2" fill="#9aa5b1"/>')
    bubbles = []
    for k, x in enumerate(xs, start=1):
        bubbles.append(f'<circle cx="{x:g}" cy="{by + 9:g}" r="5"/><text x="{x:g}" y="{by + 11.3:g}">{k}</text>')
    for k, y in enumerate(reversed(ys)):
        bubbles.append(f'<circle cx="{bx + 9:g}" cy="{y:g}" r="5"/><text x="{bx + 9:g}" y="{y + 2.3:g}">{chr(65 + k)}</text>')
    out.append(f'<g fill="#fff" stroke="#94a3b8" stroke-width="0.6" font-family="{FONT}" font-size="6.5" '
               'text-anchor="middle">' + "".join(bubbles).replace("<text", '<text fill="#64748b" stroke="none"') + "</g>")
    cy = by + bh / 2
    # Shielding first, around the rooms that need it.
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        if re.search(r"\b(bunker|tunnel|vault)", r["name"].lower()):
            out.append(f'<rect x="{x - 6:g}" y="{y - 6:g}" width="{w + 12:g}" height="{h + 12:g}" fill="url(#hatch)" '
                       'stroke="#6b6358" stroke-width="0.8"/>')
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        fill, edge = _use(r["name"])
        out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}" stroke="#334155" stroke-width="2.2"/>')
        out.append(f'<rect x="{x + 2:g}" y="{y + 2:g}" width="{w - 4:g}" height="{h - 4:g}" fill="none" stroke="{edge}" '
                   'stroke-width="0.6" stroke-opacity="0.7"/>')
        # A door on the side facing the middle of the building, near a corner: a gap in the wall and its swing.
        if w >= 30 and h >= 24:
            d = min(10.0, w / 5)
            dx = x + 6
            if y + h / 2 < cy:                                    # the room is in the upper half: door below
                wy, sy, sweep = y + h, -1, 0
            else:
                wy, sy, sweep = y, 1, 1
            out.append(f'<line x1="{dx:g}" y1="{wy:g}" x2="{dx + d:g}" y2="{wy:g}" stroke="{fill}" stroke-width="3"/>')
            out.append(f'<path d="M{dx:g},{wy:g} L{dx:g},{wy + sy * d:g} A{d:g},{d:g} 0 0 {sweep} {dx + d:g},{wy:g}" '
                       'fill="none" stroke="#475569" stroke-width="0.6"/>')
    # The beam axis and any other line the drawing had.
    for ln in m["lines"]:
        pts = " ".join(f"{px:g},{py:g}" for px, py in ln["points"])
        dash = ' stroke-dasharray="7 4"' if ln["dashed"] else ""
        width = 2.5 if not ln["dashed"] else 2
        out.append(f'<polyline points="{pts}" fill="none" stroke="{ln["colour"]}" stroke-width="{width}" '
                   f'stroke-linecap="round"{dash}/>')
        if ln["label"]:
            (x0, y0) = ln["points"][0]
            out.append(f'<text x="{x0:g}" y="{y0 + 11:g}" font-family="{FONT}" font-size="7" fill="{ln["colour"]}" '
                       f'font-weight="bold" letter-spacing="0.3" paint-order="stroke" stroke="#ffffff" stroke-width="2.5">'
                       f'{_esc(ln["label"])}</text>')
    # Room labels, last, over everything of the drawing.
    for r in m["rooms"]:
        x, y, w, h = r["box"]
        fs, lines = _fit(r["name"], w, h)
        lh = fs * 1.2
        widest = max(len(s) for s in lines) * fs * 0.64
        pw, ph = min(widest + 10, w - 4), len(lines) * lh + 5
        px, py = x + (w - pw) / 2, y + max(5.0, min(h * 0.18, h - ph - 16))
        if any(_crosses(ln["points"], x, py - 3, w, ph + 14) for ln in m["lines"]):
            py = y + h - ph - 14                                   # the beam runs through the top: the label goes below
        out.append(f'<rect x="{px:g}" y="{py:g}" width="{pw:g}" height="{ph:g}" rx="3" fill="#ffffff" fill-opacity="0.94" '
                   'stroke="#94a3b8" stroke-width="0.6"/>')
        for k, s in enumerate(lines):
            out.append(f'<text x="{x + w / 2:g}" y="{py + 2.5 + lh * (k + 1) - lh * 0.25:g}" font-family="{FONT}" '
                       f'font-size="{fs:g}" font-weight="bold" letter-spacing="0.2" text-anchor="middle" '
                       f'fill="#0f172a">{_esc(s)}</text>')
        area = w * h / PX_PER_M ** 2
        sub = f"{r['number']} · {area:.0f} m²" if r["number"] else f"{area:.0f} m²"
        sfs = 6 if w >= 48 else 5
        if len(sub) * sfs * 0.55 > w - 6:
            sub = r["number"]
        if py + ph + 3 + sfs < y + h - 2 and sub:
            out.append(f'<text x="{x + w / 2:g}" y="{py + ph + 2 + sfs:g}" font-family="{FONT}" font-size="{sfs:g}" '
                       f'text-anchor="middle" fill="#475569">{_esc(sub)}</text>')
    # The title block under the building: title and the synthetic note on the left; north and a scale bar on the right.
    top = by + bh + 4
    band = H - top
    if band >= 24:
        right = 10 * PX_PER_M + 40                                  # the scale bar and north
        avail = bw - 18 - right
        title = m["title"]
        note = "Synthetic demo plan · not a real building"
        tfs = max(7.0, min(15.0, band * 0.28, avail / max(len(title) * 0.56, 1)))
        nfs = max(5.5, min(tfs * 0.62, avail / max(len(note) * 0.5, 1)))
        out.append(f'<text x="{bx + 6:g}" y="{top + tfs + 3:g}" font-family="{FONT}" font-size="{tfs:g}" font-weight="bold" '
                   f'fill="#0f172a">{_esc(title)}</text>')
        out.append(f'<text x="{bx + 6:g}" y="{top + tfs + 5 + nfs * 1.25:g}" font-family="{FONT}" font-size="{nfs:g}" '
                   f'fill="#b91c1c">{_esc(note)}</text>')
        sx, sy = bx + bw - 6 - 10 * PX_PER_M, top + band * 0.3
        bar = []
        for k in range(2):
            bar.append(f'<rect x="{sx + k * 5 * PX_PER_M:g}" y="{sy:g}" width="{5 * PX_PER_M:g}" height="3" '
                       f'fill="{"#1f2937" if k == 0 else "#ffffff"}" stroke="#1f2937" stroke-width="0.6"/>')
        for k, label in enumerate(("0", "5", "10 m")):
            bar.append(f'<text x="{sx + k * 5 * PX_PER_M:g}" y="{sy + 10:g}" font-family="{FONT}" font-size="6" '
                       f'text-anchor="middle" fill="#334155">{label}</text>')
        out.append("".join(bar))
        if m["north"]:
            nx, ny = sx - 30, top + band * 0.45
            out.append(f'<g transform="translate({nx:g},{ny:g})"><circle r="9" fill="#ffffff" stroke="#334155" stroke-width="0.8"/>'
                       '<polygon points="0,-7 3.5,3.5 0,1.2 -3.5,3.5" fill="#0f172a"/>'
                       f'<text x="12" y="3" font-family="{FONT}" font-size="7" font-weight="bold" fill="#0f172a">N</text></g>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def redraw(svg: str) -> str:
    return draw(read(svg))


if __name__ == "__main__":                                       # redraw files in place: demo_plan_drawing.py a.svg b.svg
    import sys
    from pathlib import Path
    for p in map(Path, sys.argv[1:]):
        p.write_text(redraw(p.read_text()))
