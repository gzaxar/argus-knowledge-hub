/**
 * A rack drawn as it stands: one face, units numbered from the bottom, what is mounted as blocks. Read-only by
 * default; with `onDrop` a block can be dragged to another unit (the row it is dropped on becomes its lowest).
 */
import { useSyncExternalStore } from "react";
import type { RackElevationView, RackMountingView, RackProblem } from "../api/client";

const ROW = 22;

/** Where a block being dragged would land: shared by both faces, since a block can cross from one to the other. */
/** A drag ends with a click on the block: that click is not a selection. */
let suppressClick = false;
let landing: { face: string; u: number; height: number } | null = null;
const watchers = new Set<() => void>();
const setLanding = (v: typeof landing) => { landing = v; watchers.forEach((w) => w()); };
const watch = (w: () => void) => { watchers.add(w); return () => { watchers.delete(w); }; };

/** The face and unit under a point of the screen, if a rack face is there. */
function unitAt(x: number, y: number, units: number): { face: "front" | "rear"; u: number } | null {
  const el = document.elementFromPoint(x, y)?.closest<HTMLElement>("[data-rack-face]");
  if (!el) return null;
  const row = Math.floor((y - el.getBoundingClientRect().top - 2) / ROW);
  return { face: el.dataset.rackFace as "front" | "rear", u: Math.min(units, Math.max(1, units - row)) };
}

const TONE: Record<string, string> = {
  device: "border-sky-400 bg-sky-100 text-sky-950",
  shelf: "border-amber-400 bg-amber-50 text-amber-950",
  reserved: "border-slate-400 border-dashed bg-slate-100 text-slate-600",
};

export function nameOf(m: RackMountingView): string {
  return m.asset?.name ?? m.label ?? (m.kind === "shelf" ? "Shelf" : m.kind === "reserved" ? "Reserved" : m.kind);
}

export function spanOf(m: RackMountingView): string {
  if (m.shelf_uid) return "on a shelf";
  if (m.kind === "zero_u" || m.start_u == null) return "0U";
  return m.height_u <= 1 ? `U${m.start_u}` : `U${m.start_u}–U${m.start_u + m.height_u - 1}`;
}

export function RackFace({ view, face, selected, onSelect, onDrop, problems = [], staged }: {
  view: RackElevationView;
  face: "front" | "rear";
  selected?: string | null;
  onSelect?: (m: RackMountingView) => void;
  /** A block (its mounting uid) dropped with its lowest unit on `u` of this face. */
  onDrop?: (mountingUid: string, u: number, face: "front" | "rear") => void;
  problems?: RackProblem[];
  /** Mountings a preview would make or move: drawn as pending. */
  staged?: Set<string>;
}) {
  const land = useSyncExternalStore(watch, () => landing);
  const units = view.rack.units;

  /** Dragging with the pointer (mouse, pen or finger): the row under it becomes the block's lowest unit. */
  const startDrag = (m: RackMountingView, down: React.PointerEvent) => {
    if (!onDrop || down.button !== 0) return;
    const from = { x: down.clientX, y: down.clientY };
    let moved = false;
    const move = (e: PointerEvent) => {
      if (!moved && Math.hypot(e.clientX - from.x, e.clientY - from.y) < 5) return;
      moved = true;
      const at = unitAt(e.clientX, e.clientY, units);
      setLanding(at ? { ...at, height: m.height_u } : null);
    };
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setLanding(null);
      const at = moved ? unitAt(e.clientX, e.clientY, units) : null;
      if (at) { suppressClick = true; setTimeout(() => { suppressClick = false; }, 0); onDrop(m.uid, at.u, at.face); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const here = view.mountings.filter((m) => m.top_u != null && (m.face === face || m.face === "both"));
  const wrong = new Set(problems.flatMap((p) => [p.mounting, p.with]).filter(Boolean) as string[]);
  const carried = (shelf: RackMountingView) => view.mountings.filter((m) => m.shelf_uid === shelf.uid);
  return (
    <div className="min-w-0 flex-1">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="font-semibold uppercase tracking-wide text-slate-600">{face}</span>
        <span className="text-slate-400">{view.used_units[face]} of {units} U used</span>
      </div>
      <div data-rack-face={face} className="relative rounded border-2 border-slate-700 bg-white" style={{ height: units * ROW + 4 }}
           role="img" aria-label={`${view.rack.name}, ${face}: ${here.map((m) => `${nameOf(m)} ${spanOf(m)}`).join("; ") || "empty"}`}>
        {Array.from({ length: units }, (_, i) => units - i).map((u) => (
          <div key={u}
               className={`flex items-center border-b border-slate-100 text-[10px] text-slate-400 ${
                 land && land.face === face && u >= land.u && u < land.u + land.height ? "bg-emerald-100" : ""}`}
               style={{ height: ROW }}>
            <span className="w-7 shrink-0 border-r border-slate-200 text-center font-mono">{u}</span>
          </div>
        ))}
        {here.map((m) => {
          const pending = staged?.has(m.uid) || m.since == null;
          const on = m.kind === "shelf" ? carried(m) : [];
          return (
            <button key={m.uid} type="button"
                    onPointerDown={(e) => startDrag(m, e)}
                    onClick={() => { if (!suppressClick) onSelect?.(m); }}
                    title={`${nameOf(m)} · ${spanOf(m)} · ${m.face}${m.asset?.key ? ` · ${m.asset.key}` : ""}`}
                    className={`absolute left-8 right-1 overflow-hidden rounded border px-1.5 text-left text-[11px] leading-tight
                      ${TONE[m.kind] ?? TONE.device} ${m.face === "both" ? "border-l-4" : ""}
                      ${wrong.has(m.uid) ? "!border-red-500 !bg-red-100 !text-red-900" : ""}
                      ${pending ? "ring-2 ring-emerald-400" : ""} ${selected === m.uid ? "outline outline-2 outline-slate-900" : ""}
                      ${onDrop ? "cursor-grab touch-none select-none" : "cursor-pointer"}`}
                    style={{ top: (units - (m.top_u as number)) * ROW + 1, height: m.height_u * ROW - 2 }}>
              <span className="block truncate font-medium">{nameOf(m)}</span>
              {m.height_u > 1 && (
                <span className="block truncate text-[10px] opacity-70">
                  {m.kind === "shelf" && on.length ? `carries ${on.map(nameOf).join(", ")}`
                    : m.asset ? `${m.asset.type}${m.asset.key ? ` · ${m.asset.key}` : ""}` : spanOf(m)}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Both faces side by side, and what takes no unit under them. */
export function RackElevation(props: Omit<Parameters<typeof RackFace>[0], "face">) {
  const zero = props.view.mountings.filter((m) => m.kind === "zero_u");
  return (
    <div>
      <div className="flex gap-4">
        <RackFace {...props} face="front" />
        <RackFace {...props} face="rear" />
      </div>
      {zero.length > 0 && (
        <p className="mt-2 text-xs text-slate-600">
          <span className="font-semibold">0U:</span>{" "}
          {zero.map((m, i) => (
            <button key={m.uid} type="button" onClick={() => props.onSelect?.(m)}
                    className={`mr-1 rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50 ${props.selected === m.uid ? "outline outline-2 outline-slate-900" : ""}`}>
              {nameOf(m)} ({m.face}){i < zero.length - 1 ? "" : ""}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}
