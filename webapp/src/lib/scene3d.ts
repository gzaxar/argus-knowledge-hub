/** The 3D view's geometry, without WebGL: where each record stands in metres, and the arcs between related ones.
 *  x is the plan's x, z its y (down the drawing), y is up. */
import type { PlanLayerItem, PlanSceneUnit, PlanSceneView } from "../api/client";

export const U_M = 0.04445;              // one rack unit
export const RACK = { w: 0.6, d: 1.0, h: 2.0, base: 0.1 };
export type P3 = [number, number, number];

/** How tall a record stands and where its middle is, by layer. */
export function bodyOf(i: Pick<PlanLayerItem, "layer">): { w: number; h: number; d: number; y: number } {
  switch (i.layer) {
    case "racks": return { w: RACK.w, h: RACK.h, d: RACK.d, y: RACK.h / 2 };
    case "beamline": return { w: 0.35, h: 0.35, d: 0.35, y: 1.2 };
    case "fixed": return { w: 1.0, h: 1.6, d: 1.0, y: 0.8 };
    case "places": return { w: 0.9, h: 2.1, d: 0.1, y: 1.05 };
    default: return { w: 0.3, h: 0.3, d: 0.3, y: 1.0 };
  }
}

export function floorOf(v: Pick<PlanSceneView, "metres_per_px">, x: number, y: number): [number, number] {
  return [x * v.metres_per_px, y * v.metres_per_px];
}

/** A unit inside its rack: its middle, its height, and which face it is on. 0U and shelf units stand at mid-rack. */
export function unitBox(u: PlanSceneUnit): { y: number; h: number; dz: number } {
  const face = u.face === "rear" ? 1 : u.face === "front" ? -1 : 0;
  if (u.start_u == null || !u.height_u) return { y: RACK.base + RACK.h / 2, h: 0.6, dz: face * (RACK.d / 2 - 0.05) };
  const h = u.height_u * U_M;
  return { y: RACK.base + (u.start_u - 1) * U_M + h / 2, h, dz: face * 0.15 };
}

/** Where a relation ends on each record: the middle of its body, or of its units in its rack. */
export function anchors(v: PlanSceneView): Map<string, P3> {
  const out = new Map<string, P3>();
  for (const i of v.items) {
    const [x, z] = floorOf(v, i.x, i.y);
    out.set(i.uid, [x, bodyOf(i).y, z]);
  }
  for (const u of v.units) {
    const rack = out.get(u.rack_uid);
    if (!rack) continue;
    const b = unitBox(u);
    out.set(u.uid, [rack[0], b.y, rack[2] + b.dz]);
  }
  for (const s of [...v.outlines, ...v.routes]) {
    if (out.has(s.uid) || s.points.length === 0) continue;
    const cx = s.points.reduce((a, p) => a + p[0], 0) / s.points.length;
    const cz = s.points.reduce((a, p) => a + p[1], 0) / s.points.length;
    const [x, z] = floorOf(v, cx, cz);
    out.set(s.uid, [x, 0.2, z]);
  }
  return out;
}

/** A relation as an arc over the floor: higher the farther apart its ends are, so lines between neighbours stay
 *  readable. `n` points from one end to the other. */
export function arc(a: P3, b: P3, n = 24): P3[] {
  const dist = Math.hypot(b[0] - a[0], b[2] - a[2]);
  const lift = Math.max(0.4, Math.min(6, dist * 0.35));
  const mid: P3 = [(a[0] + b[0]) / 2, Math.max(a[1], b[1]) + lift, (a[2] + b[2]) / 2];
  return Array.from({ length: n + 1 }, (_, k) => {
    const t = k / n, s = 1 - t;
    return [0, 1, 2].map((i) => s * s * a[i] + 2 * s * t * mid[i] + t * t * b[i]) as P3;
  });
}

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777", "#4f46e5", "#0f766e"];

/** One colour per relation type, the same every time. */
export function relationColour(type: string): string {
  let h = 0;
  for (const c of type) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

/** The relations to draw: of the types chosen, and — with a record selected and `onlySelected` — only its own. */
export function drawnRelations(v: Pick<PlanSceneView, "relations">, types: Set<string>, selected: string | null,
                               onlySelected: boolean) {
  return v.relations.filter((r) => types.has(r.type) &&
    (!onlySelected || !selected || r.from === selected || r.to === selected));
}
