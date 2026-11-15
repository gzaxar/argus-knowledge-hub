"""Inside a building, a demo cable or pipe runs along the gaps between rooms to the room it serves (used by
scripts/rack_demos.py, docs/plan-layers.md "Cables and pipes").

A route of the demos was drawn on the map as a few straight strokes: outside that is a fair sketch of a trench, but
inside a building the last stroke crossed rooms diagonally and stopped anywhere, so on the floor plan it said
neither where it came in nor what it served. Here, for each building a route ends in (the building's floor plan
drawn by ARGUS knows its walls and rooms), the part inside is replaced by an orthogonal run: from where the route
comes through the wall, along the free space between rooms (a corridor, the gap between two rows of rooms), to the
room its end is in. What lies outside the building is kept as it was.

Plain functions over plan pixels; the caller converts to and from longitude and latitude with the plan's transform.
"""
import heapq
from typing import Optional

Pt = tuple[float, float]
Box = tuple[float, float, float, float]          # x, y, width, height

CELL = 5.0          # half a metre at the demos' 1 m = 10 px
WALL = 4.0          # a run keeps this far inside the building's walls
CLEAR = 6.0         # and prefers to keep this far from a room's walls
INTO = 12.0         # how far inside the walls of the room it serves it stops (or the room's middle, if narrower)


def inside(p: Pt, b: Box, pad: float = 0.0) -> bool:
    return b[0] + pad <= p[0] <= b[0] + b[2] - pad and b[1] + pad <= p[1] <= b[1] + b[3] - pad


def entry(outside: Pt, into: Pt, b: Box) -> Pt:
    """Where the segment from a point outside the box to one inside crosses its edge (Liang–Barsky)."""
    (x0, y0), (x1, y1) = outside, into
    dx, dy = x1 - x0, y1 - y0
    t0 = 0.0
    for p, q in ((-dx, x0 - b[0]), (dx, b[0] + b[2] - x0), (-dy, y0 - b[1]), (dy, b[1] + b[3] - y0)):
        if p < 0:
            t0 = max(t0, q / p)
    return (round(x0 + t0 * dx, 3), round(y0 + t0 * dy, 3))


def _room_of(p: Pt, rooms: list[Box]) -> Box:
    for r in rooms:
        if inside(p, r):
            return r
    return min(rooms, key=lambda r: (max(r[0] - p[0], 0, p[0] - r[0] - r[2]) ** 2
                                     + max(r[1] - p[1], 0, p[1] - r[1] - r[3]) ** 2))


def run(wall: Pt, end: Pt, building: Box, rooms: list[Box]) -> Optional[list[Pt]]:
    """The orthogonal run from `wall` (on the building's edge) to the room `end` is in, as its corners: the first
    is `wall`, the last a point INTO px inside that room. None when no free way is found."""
    target = _room_of(end, rooms)
    others = [r for r in rooms if r is not target]
    bx, by, bw, bh = building
    nx, ny = int(bw // CELL), int(bh // CELL)
    centre = lambda i, j: (bx + (i + 0.5) * CELL, by + (j + 0.5) * CELL)

    def free(i: int, j: int) -> bool:
        if not (0 <= i < nx and 0 <= j < ny):
            return False
        c = centre(i, j)
        return inside(c, building, WALL) and not any(inside(c, r, -1.0) for r in others)

    def near_room(i: int, j: int) -> bool:
        c = centre(i, j)
        return any(inside(c, r, -CLEAR) for r in others) or (inside(c, target, -CLEAR) and not inside(c, target))

    cell = lambda p: (min(nx - 1, max(0, int((p[0] - bx) // CELL))), min(ny - 1, max(0, int((p[1] - by) // CELL))))
    # Step in from the wall to the first free cell.
    si, sj = cell(wall)
    step = (1 if wall[0] <= bx + 0.6 else -1 if wall[0] >= bx + bw - 0.6 else 0,
            1 if wall[1] <= by + 0.6 else -1 if wall[1] >= by + bh - 0.6 else 0)
    for _ in range(4):
        if free(si, sj):
            break
        si, sj = si + step[0], sj + step[1]
    if not free(si, sj):
        return None
    pad = min(INTO, target[2] / 2 - CELL / 2, target[3] / 2 - CELL / 2)
    goal = lambda i, j: inside(centre(i, j), target, pad)

    # A*: one per step, more near a room's walls, and a turn costs as much as a few steps (few, clean corners).
    start = (si, sj, step if step != (0, 0) else (0, 1))
    tx, ty = target[0] + target[2] / 2, target[1] + target[3] / 2
    h = lambda i, j: (abs(centre(i, j)[0] - tx) + abs(centre(i, j)[1] - ty)) / CELL
    seen: dict = {}
    todo = [(h(si, sj), 0.0, start, None)]
    came: dict = {}
    while todo:
        _f, g, node, prev = heapq.heappop(todo)
        if node in seen:
            continue
        seen[node] = g
        came[node] = prev
        i, j, d = node
        if goal(i, j):
            path = []
            while node is not None:
                path.append(node)
                node = came[node]
            return _corners(wall, step, [centre(i, j) for i, j, _ in reversed(path)])
        for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + nd[0], j + nd[1]
            if not (free(ni, nj) or goal(ni, nj)):
                continue
            cost = g + 1 + (3 if near_room(ni, nj) and not goal(ni, nj) else 0) + (6 if nd != d else 0)
            nxt = (ni, nj, nd)
            if nxt not in seen:
                heapq.heappush(todo, (cost + h(ni, nj), cost, nxt, node))
    return None


def _corners(wall: Pt, step: tuple[int, int], cells: list[Pt]) -> list[Pt]:
    """The run through the cells' centres as its corners, leaving the wall at a right angle."""
    first = cells[0]
    w = (wall[0], first[1]) if step[0] else (first[0], wall[1])
    pts = [w] + cells
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[k], pts[k + 1]
        if not ((a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1])):
            out.append(b)
    out.append(pts[-1])
    return [(round(x, 1), round(y, 1)) for x, y in out]


def reroute(points: list[Pt], building: Box, rooms: list[Box]) -> Optional[list[Pt]]:
    """The route (plan pixels) with its part inside the building replaced by an orthogonal run to the room its end
    is in, when exactly one end is inside; None when there is nothing to change. The end that is inside may be either."""
    if len(points) < 2 or not rooms:
        return None
    points = [(round(x, 1), round(y, 1)) for x, y in points]      # back from the map: no float dust on the walls
    a, z = inside(points[0], building), inside(points[-1], building)
    if a == z:
        return None
    pts = list(points) if z else list(reversed(points))
    k = next(i for i in range(len(pts)) if inside(pts[i], building))      # the first point inside
    if k == 0:
        return None
    wall = entry(pts[k - 1], pts[k], building)
    bx, by, bw, bh = building
    on_side = abs(wall[0] - bx) < 0.6 or abs(wall[0] - bx - bw) < 0.6
    on_end = abs(wall[1] - by) < 0.6 or abs(wall[1] - by - bh) < 0.6
    if on_side and on_end:
        # Through a corner: in through the side wall, a little along it, so a second run finds the same wall.
        wall = (wall[0], wall[1] + 2 * CELL if abs(wall[1] - by) < 0.6 else wall[1] - 2 * CELL)
    inner = run(wall, pts[-1], building, rooms)
    if inner is None:
        return None
    new = pts[:k] + inner                     # inner[0] is on the wall, square to the run
    new = [(round(x, 1), round(y, 1)) for x, y in new]
    return new if z else list(reversed(new))
