import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, indoorApi, type PlanLayout, type PlanLayoutRoom, type PlaceLevel } from "../api/client";

/** "Draw a plan" (docs/plan-drawing.md): when a place has no drawing to upload, its plan is drawn from the building's
 *  size and its rooms. Drag on the plan to add a room, drag a room to move it, type exact metres on the right; a room
 *  can stand for a room record, which is then placed at its centre. ARGUS draws it (the same drawing as the demos). */

const PX = 10;          // pixels a metre, as on every plan drawn here
const ORIGIN = 20;      // the building's corner on the drawing
const BAND = 64;        // the title block under the building
const STEP = 0.5;       // metres the mouse snaps to

const snap = (m: number) => Math.round(m / STEP) * STEP;

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    try {
      const body = JSON.parse(e.message);
      return body?.detail?.error ?? body?.detail ?? e.message;
    } catch { return e.message; }
  }
  return e instanceof Error ? e.message : String(e);
}

function overlaps(a: PlanLayoutRoom, b: PlanLayoutRoom) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.d && b.y < a.y + a.d;
}

/** The first free spot for a room of that size, scanning the building in metres. */
export function freeSpot(layout: PlanLayout, w: number, d: number): { x: number; y: number } | null {
  for (let y = 0; y + d <= layout.depth_m; y += 1) {
    for (let x = 0; x + w <= layout.width_m; x += 1) {
      const room = { name: "", x, y, w, d };
      if (!layout.rooms.some((r) => overlaps(r, room))) return { x, y };
    }
  }
  return null;
}

export function PlanDrawer({ placeUid, placeName = "", levels, planUid, roomsHere, onDone }: {
  placeUid: string; placeName?: string; levels: PlaceLevel[];
  /** A plan drawn here to change; none: a new one. */
  planUid?: string;
  /** Room records in this place, to stand for rooms of the plan. */
  roomsHere: { uid: string; key: string; name: string; type: string }[];
  onDone: () => void;
}) {
  const existing = useQuery({ queryKey: ["plan-layout", planUid], queryFn: () => indoorApi.planLayout(planUid!),
                              enabled: !!planUid });
  const [layout, setLayout] = useState<PlanLayout>({ title: placeName ? `${placeName} — plan` : "Ground floor plan", width_m: 40, depth_m: 20, rooms: [], north: true });
  const [level, setLevel] = useState("");
  const [placeRooms, setPlaceRooms] = useState(true);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => { if (existing.data?.layout) setLayout(existing.data.layout); }, [existing.data]);

  // The drawing, from the server, a moment after the last change.
  const [preview, setPreview] = useState<{ url: string | null; error: string | null }>({ url: null, error: null });
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      indoorApi.drawingPreview(layout)
        .then((url) => { if (alive) setPreview((p) => { if (p.url) URL.revokeObjectURL(p.url); return { url, error: null }; }); })
        .catch((e) => { if (alive) setPreview((p) => ({ url: p.url, error: problem(e) })); });
    }, 350);
    return () => { alive = false; clearTimeout(t); };
  }, [layout]);

  const save = useMutation({
    mutationFn: () => planUid
      ? indoorApi.setPlanLayout(planUid, { layout, place_rooms: placeRooms })
      : indoorApi.drawPlan(placeUid, { layout, level_uid: level || null, place_rooms: placeRooms }),
    onSuccess: onDone,
  });

  const setRoom = (i: number, patch: Partial<PlanLayoutRoom>) =>
    setLayout((l) => ({ ...l, rooms: l.rooms.map((r, k) => (k === i ? { ...r, ...patch } : r)) }));
  const removeRoom = (i: number) => { setLayout((l) => ({ ...l, rooms: l.rooms.filter((_, k) => k !== i) })); setSelected(null); };
  const addRoom = (room: Omit<PlanLayoutRoom, "x" | "y">) => {
    const spot = freeSpot(layout, room.w, room.d);
    if (!spot) return;
    setLayout((l) => ({ ...l, rooms: [...l.rooms, { ...room, ...spot }] }));
    setSelected(layout.rooms.length);
  };

  // Drawing and moving on the plan, in metres.
  const W = layout.width_m * PX + 2 * ORIGIN, H = layout.depth_m * PX + 2 * ORIGIN + BAND;
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ kind: "new" | "move"; from: { x: number; y: number }; at: { x: number; y: number };
                                     room?: number; start?: { x: number; y: number } } | null>(null);
  const metres = (e: React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W, y = ((e.clientY - r.top) / r.height) * H;
    return { x: (x - ORIGIN) / PX, y: (y - ORIGIN) / PX };
  };
  const inside = (p: { x: number; y: number }) => p.x >= 0 && p.y >= 0 && p.x <= layout.width_m && p.y <= layout.depth_m;
  const ghost = drag?.kind === "new" ? {
    x: snap(Math.min(drag.from.x, drag.at.x)), y: snap(Math.min(drag.from.y, drag.at.y)),
    w: snap(Math.abs(drag.at.x - drag.from.x)), d: snap(Math.abs(drag.at.y - drag.from.y)),
  } : null;
  const onDown = (e: React.PointerEvent, room?: number) => {
    const p = metres(e);
    if (!inside(p)) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    if (room != null) {
      setSelected(room);
      setDrag({ kind: "move", from: p, at: p, room, start: { x: layout.rooms[room].x, y: layout.rooms[room].y } });
    } else {
      setSelected(null);
      setDrag({ kind: "new", from: p, at: p });
    }
    e.stopPropagation();
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const p = metres(e);
    if (drag.kind === "move" && drag.room != null && drag.start) {
      const r = layout.rooms[drag.room];
      const x = Math.max(0, Math.min(layout.width_m - r.w, snap(drag.start.x + p.x - drag.from.x)));
      const y = Math.max(0, Math.min(layout.depth_m - r.d, snap(drag.start.y + p.y - drag.from.y)));
      setRoom(drag.room, { x, y });
    }
    setDrag({ ...drag, at: p });
  };
  const onUp = () => {
    if (drag?.kind === "new" && ghost && ghost.w >= 1 && ghost.d >= 1) {
      const room = { name: `Room ${layout.rooms.length + 1}`, number: "", ...ghost,
                     w: Math.min(ghost.w, layout.width_m - ghost.x), d: Math.min(ghost.d, layout.depth_m - ghost.y) };
      if (!layout.rooms.some((r) => overlaps(r, room))) {
        setLayout((l) => ({ ...l, rooms: [...l.rooms, room] }));
        setSelected(layout.rooms.length);
      }
    }
    setDrag(null);
  };

  if (planUid && existing.data && !existing.data.editable) {
    return <p className="text-sm text-slate-600">This plan is an uploaded drawing, not one drawn in ARGUS: it cannot be
      changed here. Upload a new drawing, or draw a plan.</p>;
  }
  const used = new Set(layout.rooms.map((r) => r.record).filter(Boolean));
  const num = (v: string) => (v.trim() === "" ? 0 : Number(v));
  const sel = selected != null ? layout.rooms[selected] : null;
  return (
    <div className="grid gap-4 text-sm lg:grid-cols-[1fr_22rem]">
      <div>
        <p className="mb-1 text-xs text-slate-500">Drag on the plan to add a room; drag a room to move it. Half a metre a step.</p>
        <div className="relative w-full rounded border border-slate-200 bg-slate-50" style={{ aspectRatio: `${W} / ${H}` }}>
          {preview.url && <img src={preview.url} alt="The plan as it will be drawn" className="absolute inset-0 h-full w-full" />}
          <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 h-full w-full touch-none select-none"
               data-testid="plan-drawer" onPointerDown={(e) => onDown(e)} onPointerMove={onMove} onPointerUp={onUp}>
            {layout.rooms.map((r, i) => (
              <rect key={i} x={ORIGIN + r.x * PX} y={ORIGIN + r.y * PX} width={r.w * PX} height={r.d * PX}
                    fill="transparent" stroke={i === selected ? "#4f46e5" : "transparent"} strokeWidth={2}
                    className="cursor-move" onPointerDown={(e) => onDown(e, i)}>
                <title>{r.name}</title>
              </rect>
            ))}
            {ghost && <rect x={ORIGIN + ghost.x * PX} y={ORIGIN + ghost.y * PX} width={ghost.w * PX} height={ghost.d * PX}
                            fill="#4f46e5" fillOpacity={0.12} stroke="#4f46e5" strokeDasharray="4 3" />}
          </svg>
        </div>
        {preview.error && <p className="mt-1 text-xs text-red-600">{preview.error}</p>}
      </div>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <label className="col-span-2">Title
            <input value={layout.title} onChange={(e) => setLayout({ ...layout, title: e.target.value })}
                   className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1" /></label>
          <label>Building width (m)
            <input type="number" min={2} value={layout.width_m} onChange={(e) => setLayout({ ...layout, width_m: num(e.target.value) })}
                   className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1" /></label>
          <label>Depth (m)
            <input type="number" min={2} value={layout.depth_m} onChange={(e) => setLayout({ ...layout, depth_m: num(e.target.value) })}
                   className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1" /></label>
          {!planUid && (
            <label className="col-span-2">Floor
              <select value={level} onChange={(e) => setLevel(e.target.value)} className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1">
                <option value="">the whole place</option>
                {levels.map((l) => <option key={l.uid} value={l.uid}>{l.name}</option>)}
              </select></label>
          )}
        </div>

        {sel && selected != null && (
          <div className="space-y-1 rounded border border-indigo-200 bg-indigo-50/40 p-2 text-xs" aria-label="The selected room">
            <input value={sel.name} onChange={(e) => setRoom(selected, { name: e.target.value })} aria-label="Room name"
                   className="w-full rounded border border-slate-300 px-2 py-1 font-medium" />
            <div className="grid grid-cols-5 gap-1">
              <input value={sel.number ?? ""} onChange={(e) => setRoom(selected, { number: e.target.value })} placeholder="no."
                     aria-label="Room number" className="rounded border border-slate-300 px-1 py-1" />
              {(["x", "y", "w", "d"] as const).map((k) => (
                <input key={k} type="number" step={STEP} value={sel[k]} aria-label={`Room ${k}`} title={{ x: "from the left, m", y: "from the top, m", w: "width, m", d: "depth, m" }[k]}
                       onChange={(e) => setRoom(selected, { [k]: num(e.target.value) })} className="rounded border border-slate-300 px-1 py-1" />
              ))}
            </div>
            <div className="flex items-center gap-2">
              <select value={sel.record ?? ""} onChange={(e) => setRoom(selected, { record: e.target.value || null })}
                      aria-label="The room record it stands for" className="min-w-0 flex-1 rounded border border-slate-300 px-1 py-1">
                <option value="">— no room record —</option>
                {roomsHere.filter((r) => r.uid === sel.record || !used.has(r.uid)).map((r) => (
                  <option key={r.uid} value={r.uid}>{r.key || r.name} · {r.name}</option>
                ))}
              </select>
              <button type="button" onClick={() => removeRoom(selected)} className="text-red-600 underline">remove</button>
            </div>
          </div>
        )}

        <div className="text-xs">
          <p className="font-semibold uppercase text-slate-500">Rooms ({layout.rooms.length})</p>
          <ul className="mt-1 max-h-48 space-y-0.5 overflow-auto">
            {layout.rooms.map((r, i) => (
              <li key={i}>
                <button type="button" onClick={() => setSelected(i)}
                        className={`w-full rounded px-1 text-left ${i === selected ? "bg-indigo-100" : "hover:bg-slate-100"}`}>
                  {r.name} <span className="text-slate-500">{r.number} · {r.w} × {r.d} m{r.record ? " · record" : ""}</span>
                </button>
              </li>
            ))}
          </ul>
          {roomsHere.some((r) => !used.has(r.uid)) && (
            <div className="mt-2">
              <p className="text-slate-500">Rooms recorded in this place — add one:</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {roomsHere.filter((r) => !used.has(r.uid)).map((r) => (
                  <button key={r.uid} type="button" onClick={() => addRoom({ name: r.name, number: "", record: r.uid, w: 6, d: 5 })}
                          className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">+ {r.name}</button>
                ))}
              </div>
            </div>
          )}
          <button type="button" onClick={() => addRoom({ name: `Room ${layout.rooms.length + 1}`, number: "", w: 6, d: 5 })}
                  className="mt-2 rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50">+ a room</button>
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={placeRooms} onChange={(e) => setPlaceRooms(e.target.checked)} />
          Place the room records at their room's centre
        </label>
        <div className="flex items-center gap-2">
          <button type="button" disabled={save.isPending || !!preview.error || !layout.title.trim()} onClick={() => save.mutate()}
                  className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-40">
            {save.isPending ? "Saving…" : planUid ? "Save the plan" : "Create the plan"}</button>
          {save.isError && <span className="text-xs text-red-600">{problem(save.error)}</span>}
        </div>
        <p className="text-xs text-slate-500">A schematic plan at 1 m = 10 px, not a survey. Records are then placed on it like on
          any other plan; redrawing it keeps their points.</p>
      </div>
    </div>
  );
}
