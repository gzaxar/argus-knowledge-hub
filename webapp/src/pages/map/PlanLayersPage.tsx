import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { indoorApi, type PlanLayerId, type PlanLayerItem, type PlanLayersView } from "../../api/client";
import { PlanView, type PlanPin, type PlanShape } from "../../components/PlanView";

/** One colour per layer; the same in the chips and on the plan. */
export const LAYER_COLOUR: Record<PlanLayerId, string> = {
  places: "#0f766e", beamline: "#dc2626", racks: "#4f46e5", fixed: "#ea580c", devices: "#64748b",
  paths: "#0891b2", zones: "#ca8a04", tickets: "#dc2626", activities: "#7c3aed",
};

const STORE = "argus.plan-layers";

function remembered(): Partial<Record<PlanLayerId, boolean>> {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? "{}");
  } catch {
    return {};
  }
}

/** Which layers are on: the person's last choice, else the plan's defaults. */
export function initialLayers(v: Pick<PlanLayersView, "layers">, saved = remembered()): Set<PlanLayerId> {
  return new Set(v.layers.filter((l) => saved[l.id] ?? l.on).map((l) => l.id));
}

type Pt = [number, number];

/** The pieces of a line inside a box (Liang–Barsky, segment by segment): a cable coming from another building is
 *  drawn from the wall it comes through, not across the drawing's title or the ground around it. */
export function clipLine(points: Pt[], [bx, by, bw, bh]: [number, number, number, number]): Pt[][] {
  const pieces: Pt[][] = [];
  let cur: Pt[] = [];
  const close = () => { if (cur.length > 1) pieces.push(cur); cur = []; };
  for (let k = 0; k + 1 < points.length; k++) {
    const [x0, y0] = points[k], [x1, y1] = points[k + 1];
    const dx = x1 - x0, dy = y1 - y0;
    let t0 = 0, t1 = 1, inside = true;
    for (const [p, q] of [[-dx, x0 - bx], [dx, bx + bw - x0], [-dy, y0 - by], [dy, by + bh - y0]]) {
      if (p === 0) { if (q < 0) inside = false; continue; }
      const t = q / p;
      if (p < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
    }
    if (!inside || t0 > t1) { close(); continue; }
    const r = (n: number) => Math.round(n * 10) / 10;
    const a: Pt = [r(x0 + t0 * dx), r(y0 + t0 * dy)], b: Pt = [r(x0 + t1 * dx), r(y0 + t1 * dy)];
    const last = cur[cur.length - 1];
    if (!last || t0 > 0 || last[0] !== a[0] || last[1] !== a[1]) { close(); cur = [a]; }
    cur.push(b);
    if (t1 < 1) close();
  }
  close();
  return pieces;
}

/** The pins and shapes to draw for the layers that are on. A unit held in a rack shows as its rack. */
export function drawn(v: PlanLayersView, on: Set<PlanLayerId>, focus: Set<string>,
                      open: (i: PlanLayerItem) => void, pickShape: (uid: string) => void) {
  const wanted = new Set([...focus].map((u) => v.held[u] ?? u));
  const pins: PlanPin[] = v.items
    .filter((i) => on.has(i.layer) || wanted.has(i.uid))
    .map((i) => ({
      id: i.uid, x: i.x, y: i.y, colour: LAYER_COLOUR[i.layer], square: !!i.rack, highlight: wanted.has(i.uid),
      label: i.rack ? `${i.key || i.name} · rack, ${i.rack.holds} unit${i.rack.holds === 1 ? "" : "s"}` : `${i.key || i.name} · ${i.type}`,
      badges: [
        ...(on.has("tickets") ? [{ n: i.tickets, colour: LAYER_COLOUR.tickets, title: "open tickets" }] : []),
        ...(on.has("activities") ? [{ n: i.activities, colour: LAYER_COLOUR.activities, title: "activities" }] : []),
      ],
      onClick: () => open(i),
    }));
  const box: [number, number, number, number] = v.building ?? [0, 0, v.width_px ?? 0, v.height_px ?? 0];
  const shapes: PlanShape[] = [...v.outlines, ...v.routes]
    .filter((s) => on.has(s.layer))
    .flatMap((s) => (s.layer === "paths" && box[2] > 0 ? clipLine(s.points, box) : [s.points])
      .map((points, k) => ({ id: k ? `${s.uid}#${k}` : s.uid, points, closed: s.layer !== "paths",
                             label: `${s.name} · ${s.type}`, colour: LAYER_COLOUR[s.layer], dashed: s.layer === "zones",
                             ...(s.layer === "paths" && box[2] > 0 ? routeEnds(points, s.name, box) : {}),
                             onClick: () => pickShape(s.uid) })));
  return { pins, shapes, wanted };
}

/** Which wall of the box a point lies on, as the side a label goes to stay inside: a route coming through the right
 *  wall is named to the left of where it enters. */
function wallOf([x, y]: Pt, [bx, by, bw, bh]: [number, number, number, number]): "left" | "right" | "top" | "bottom" | null {
  const near = (a: number, b: number) => Math.abs(a - b) < 0.6;
  if (near(x, bx + bw)) return "left";
  if (near(x, bx)) return "right";
  if (near(y, by)) return "bottom";
  if (near(y, by + bh)) return "top";
  return null;
}

/** A route that comes in from outside is named, and a dot marks where it arrives: without them a line crossing the
 *  plan says neither what it is nor where it goes. The name goes along its longest stretch inside — on a plan drawn
 *  by ARGUS that runs in the free space between rooms, so the name covers no room — over it when the stretch is
 *  level, beside it when it is upright. */
export function routeEnds(points: Pt[], name: string, box: [number, number, number, number]): Pick<PlanShape, "tag" | "end"> {
  const first = points[0], last = points[points.length - 1];
  const inWall = wallOf(first, box), outWall = wallOf(last, box);
  const out: Pick<PlanShape, "tag" | "end"> = {};
  if (inWall || outWall) {
    let best = 0, at: Pt = first, level = true;
    for (let k = 0; k + 1 < points.length; k++) {
      const [x0, y0] = points[k], [x1, y1] = points[k + 1];
      const len = Math.hypot(x1 - x0, y1 - y0);
      if (len > best) { best = len; at = [(x0 + x1) / 2, (y0 + y1) / 2]; level = Math.abs(x1 - x0) >= Math.abs(y1 - y0); }
    }
    out.tag = { x: at[0], y: at[1], text: name, direction: level ? "center" : "right" };
  }
  const arrives = inWall ? (outWall ? null : last) : outWall ? first : null;
  if (arrives) out.end = arrives;
  return out;
}

/** A floor plan with what is on it, by layer: the drawing as it was uploaded, and over it the records — rooms,
 *  beamline, racks (one point each: opening one shows its elevation), fixed plant, other devices, cables and
 *  pipes, zones, open tickets and activities. `?focus=uid,uid` marks records looked for. */
export function PlanLayersPage() {
  const { uid = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const focus = useMemo(() => new Set((params.get("focus") ?? "").split(",").filter(Boolean)), [params]);
  const q = useQuery({ queryKey: ["plan-layers", uid], queryFn: () => indoorApi.layers(uid), enabled: !!uid });
  const [on, setOn] = useState<Set<PlanLayerId> | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  if (q.isLoading) return <p className="p-6 text-sm text-slate-500">Loading the plan…</p>;
  if (q.isError || !q.data) return <p className="p-6 text-sm text-red-600">The plan could not be loaded.</p>;
  const v = q.data;
  const layers = on ?? initialLayers(v);

  const toggle = (id: PlanLayerId) => {
    const next = new Set(layers);
    if (next.has(id)) next.delete(id); else next.add(id);
    setOn(next);
    try {
      localStorage.setItem(STORE, JSON.stringify({ ...remembered(), [id]: next.has(id) }));
    } catch { /* the choice is only not remembered */ }
  };
  const open = (i: PlanLayerItem) => (i.rack ? navigate(`/racks/${i.uid}`) : setPicked(i.uid));
  const { pins, shapes, wanted } = drawn(v, layers, focus, open, setPicked);
  const focusPoints = v.items.filter((i) => wanted.has(i.uid)).map((i) => ({ x: i.x, y: i.y }));
  const heldFocus = [...focus].filter((u) => v.held[u]);

  return (
    <div className="flex flex-col gap-3 p-4 sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{v.name}</h1>
          <p className="text-sm text-slate-600">
            <Link to={`/assets/${v.place.uid}`} className="text-indigo-700 hover:underline">{v.place.name}</Link>
            {v.level && <span> · {v.level.name}</span>}
            {v.in_racks > 0 && <span className="text-slate-500"> · {v.in_racks} unit(s) in racks, shown as their rack</span>}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <p className="text-xs text-slate-500">The drawing is the plan as uploaded; the records are drawn over it.</p>
          <Link to={`/plans/${v.uid}/3d`} className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50">3D view</Link>
        </div>
      </div>

      <fieldset className="flex flex-wrap gap-2" aria-label="Layers">
        <legend className="sr-only">Layers</legend>
        {/* A layer with nothing in it on this plan is not offered: an IT building has no beamline. */}
        {v.layers.filter((l) => l.count > 0).map((l) => (
          <label key={l.id} className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
            layers.has(l.id) ? "border-slate-400 bg-white text-slate-900" : "border-slate-200 bg-slate-50 text-slate-500"}`}>
            <input type="checkbox" className="sr-only" checked={layers.has(l.id)} onChange={() => toggle(l.id)} />
            <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: LAYER_COLOUR[l.id], opacity: layers.has(l.id) ? 1 : 0.35 }} />
            {l.label}
            <span className="text-slate-400">{l.count}</span>
          </label>
        ))}
      </fieldset>

      {heldFocus.length > 0 && (
        <p className="text-sm text-slate-700">
          {heldFocus.map((u) => {
            const rack = v.items.find((i) => i.uid === v.held[u]);
            return rack && (
              <span key={u} className="mr-3">
                In rack <Link to={`/racks/${rack.uid}?unit=${u}`} className="font-medium text-indigo-700 hover:underline">{rack.key || rack.name}</Link> —
                open it to see where.
              </span>
            );
          })}
        </p>
      )}

      <div className="grid gap-3 lg:grid-cols-[1fr_18rem]">
        <PlanView planUid={v.uid} width={v.width_px} height={v.height_px} pins={pins} shapes={shapes} northDeg={v.north_deg}
                  focus={focusPoints.length ? focusPoints : undefined} className="h-[65vh] min-h-[20rem]" />
        <aside className="space-y-3 text-sm">
          <Picked v={v} uid={picked} onClose={() => setPicked(null)} />
          {layers.has("tickets") && (
            <section aria-label="Open tickets">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Open tickets</h2>
              {v.tickets.length === 0 ? <p className="text-slate-500">None on what this plan shows.</p> : (
                <ul className="mt-1 space-y-1">
                  {v.tickets.map((t) => (
                    <li key={t.uid}>
                      <Link to={`/tickets/${t.uid}`} className="text-indigo-700 hover:underline">{t.key ?? "Ticket"}</Link>{" "}
                      {t.title} <span className="text-xs text-slate-500">({t.state})</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
          {layers.has("activities") && (
            <section aria-label="Activities">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Activities, next 30 days</h2>
              {v.activities.length === 0 ? <p className="text-slate-500">None planned on what this plan shows.</p> : (
                <ul className="mt-1 space-y-1">
                  {v.activities.map((a) => (
                    <li key={a.id}>{a.title} <span className="text-xs text-slate-500">
                      {a.planned_start ? new Date(a.planned_start).toLocaleDateString() : ""} · {a.status}</span></li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function Picked({ v, uid, onClose }: { v: PlanLayersView; uid: string | null; onClose: () => void }) {
  if (!uid) return <p className="text-slate-500">Click a point or an area to see what it is. A rack opens its elevation.</p>;
  const item = v.items.find((i) => i.uid === uid);
  const shape = [...v.outlines, ...v.routes].find((s) => s.uid === uid);
  const rec = item ?? shape;
  if (!rec) return null;
  const tickets = v.tickets.filter((t) => t.shown_at === uid);
  return (
    <section aria-label="Selected" className="rounded border border-slate-200 bg-white p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <Link to={`/assets/${rec.uid}`} className="font-medium text-indigo-700 hover:underline">{rec.key || rec.name}</Link>
          <div className="text-xs text-slate-500">{rec.name !== rec.key && rec.key ? `${rec.name} · ` : ""}{rec.type}</div>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-slate-500 hover:underline">Close</button>
      </div>
      {tickets.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {tickets.map((t) => <li key={t.uid}><Link to={`/tickets/${t.uid}`} className="text-red-700 hover:underline">{t.key ?? "Ticket"}</Link> {t.title}</li>)}
        </ul>
      )}
    </section>
  );
}
