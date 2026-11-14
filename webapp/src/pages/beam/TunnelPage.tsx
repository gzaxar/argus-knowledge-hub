import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { beamModelApi, type TunnelElement, type TunnelView } from "../../api/client";

/** Colour and height of an element's glyph by its kind; anything else is a plain grey block. */
const GLYPH: Record<string, { c: string; h: number }> = {
  quadrupole: { c: "#2563eb", h: 30 }, sextupole: { c: "#7c3aed", h: 28 }, dipole: { c: "#0f766e", h: 34 },
  sbend: { c: "#0f766e", h: 34 }, rbend: { c: "#0f766e", h: 34 }, corrector: { c: "#60a5fa", h: 18 },
  solenoid: { c: "#9333ea", h: 26 }, accelerating_structure: { c: "#dc2626", h: 22 }, rf_cavity: { c: "#dc2626", h: 22 },
  rf_gun: { c: "#b91c1c", h: 28 }, bpm: { c: "#16a34a", h: 12 }, screen: { c: "#16a34a", h: 16 },
  faraday_cup: { c: "#16a34a", h: 16 }, current_transformer: { c: "#16a34a", h: 14 }, beam_dump: { c: "#334155", h: 34 },
  gate_valve: { c: "#a16207", h: 16 }, collimator: { c: "#57534e", h: 24 },
};
const glyph = (k: string | null) => GLYPH[k ?? ""] ?? { c: "#94a3b8", h: 14 };
const BANDS = ["#e0f2fe", "#fef3c7", "#dcfce7", "#ede9fe", "#fee2e2", "#f1f5f9"];

/** Label positions at least `gap` apart, as close as they can be to where they belong. */
export function spreadOut(xs: number[], gap: number): number[] {
  const order = xs.map((x, i) => [x, i] as const).sort((a, b) => a[0] - b[0]);
  const out = new Array<number>(xs.length);
  let last = -Infinity;
  for (const [x, i] of order) {
    out[i] = Math.max(x, last + gap);
    last = out[i];
  }
  return out;
}

/** What a dot under an element says: no hardware, hardware not placed, placed, or with open tickets. */
export function stateOf(e: TunnelElement): "none" | "unplaced" | "placed" | "tickets" {
  if (e.hardware.length === 0) return "none";
  if (e.hardware.some((h) => h.tickets.length > 0)) return "tickets";
  return e.hardware.every((h) => h.room || h.spot) ? "placed" : "unplaced";
}
const DOT = { none: "#cbd5e1", unplaced: "#f59e0b", placed: "#16a34a", tickets: "#dc2626" };

/** The tunnel along a beam path: the model's elements to scale along s, the rooms the path crosses, and for each
 *  element the hardware installed there — where it is, its rack, what powers it, its open tickets. */
export function TunnelPage() {
  const { pathUid = "" } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const selected = params.get("element");
  const systems = useQuery({ queryKey: ["beam-systems"], queryFn: () => beamModelApi.systems() });
  const t = useQuery({ queryKey: ["tunnel", pathUid], queryFn: () => beamModelApi.tunnel(pathUid), enabled: !!pathUid });
  const paths = (systems.data ?? []).flatMap((s) => s.paths.map((p) => ({ ...p, system: s.name })));

  useEffect(() => {
    if (!pathUid && paths.length > 0) navigate(`/tunnel/${paths[0].uid}`, { replace: true });
  }, [pathUid, paths.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (uid: string | null) => {
    const next = new URLSearchParams(params);
    if (uid) next.set("element", uid); else next.delete("element");
    setParams(next, { replace: true });
  };

  return (
    <div className="flex flex-col gap-3 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Tunnel</h1>
          <p className="text-sm text-slate-600">The beam model along s, and the hardware installed at each element: where it is, its rack, what powers it.</p>
        </div>
        <label className="text-sm">
          <span className="sr-only">Beam path</span>
          <select value={pathUid} onChange={(e) => navigate(`/tunnel/${e.target.value}`)}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-sm">
            {paths.length === 0 && <option value="">no beam path</option>}
            {paths.map((p) => <option key={p.uid} value={p.uid}>{p.system} · {p.name}</option>)}
          </select>
        </label>
      </div>
      {systems.isSuccess && paths.length === 0 && (
        <p className="text-sm text-slate-500">No beam model in this workspace. <Link to="/beam-model/new" className="text-indigo-700 underline">Import one</Link>.</p>
      )}
      {t.isLoading && <p className="text-sm text-slate-500">Loading the tunnel…</p>}
      {t.isError && <p className="text-sm text-red-600">The tunnel could not be loaded.</p>}
      {t.data && (
        <div className="grid gap-3 xl:grid-cols-[1fr_22rem]">
          <div className="min-w-0 space-y-2">
            <Strip v={t.data} selected={selected} onPick={pick} />
            <Legend />
            {!t.data.with_s && <p className="text-xs text-amber-700">Some elements have no s in this dataset: they are listed, not drawn.</p>}
            <Rooms v={t.data} />
          </div>
          <Detail v={t.data} uid={selected} onClose={() => pick(null)} />
        </div>
      )}
    </div>
  );
}

function Strip({ v, selected, onPick }: { v: TunnelView; selected: string | null; onPick: (uid: string) => void }) {
  const go = useNavigate();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth || 1000));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const drawn = v.elements.filter((e) => e.s != null);
  const total = Math.max(v.length ?? 0, ...drawn.map((e) => e.s! + (e.length ?? 0)), 1e-6);
  const M = 40;
  const W = Math.max(width, 360) * zoom;
  const k = (W - 2 * M) / total;
  const X = (s: number) => M + s * k;
  const ROOM = 10, TOP = 52, AXIS = 82, BOTTOM = 112, LBL = 128, DOTS = 214, TICKS = 236;
  const lx = spreadOut(drawn.map((e) => X(e.s! + (e.length ?? 0) / 2)), 13);
  const ticks = useMemo(() => {
    const target = total / Math.max(4, W / 110);
    const p10 = 10 ** Math.floor(Math.log10(target));
    const step = [1, 2, 5, 10].map((x) => x * p10).find((x) => x >= target) ?? p10;
    return Array.from({ length: Math.floor(total / step) + 1 }, (_, i) => +(i * step).toFixed(9));
  }, [total, W]);
  const H = TICKS + 22;
  const tool = "rounded border border-slate-300 bg-white px-2 py-0.5 text-xs hover:bg-slate-50";
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={tool} onClick={() => setZoom((z) => Math.min(z * 1.6, 40))} aria-label="Zoom in">＋</button>
        <button type="button" className={tool} onClick={() => setZoom((z) => Math.max(z / 1.6, 1))} aria-label="Zoom out">－</button>
        <button type="button" className={tool} onClick={() => setZoom(1)}>Whole path</button>
        <span className="text-xs text-slate-500">{v.path.name} · {total.toFixed(1)} m · {v.elements.length} elements</span>
      </div>
      <div ref={wrap} className="overflow-x-auto rounded border border-slate-200 bg-white">
        <svg width={W} height={H} role="img" aria-label={`Tunnel of ${v.path.name} along s`} style={{ display: "block" }}>
          {v.rooms.map((r, i) => (
            <g key={`${r.uid}-${i}`}>
              <rect x={X(r.from_s)} y={ROOM} width={Math.max((r.to_s - r.from_s) * k, 2)} height={TOP - ROOM - 8}
                    fill={BANDS[i % BANDS.length]} stroke="#94a3b8" strokeWidth={0.6} />
              <text x={X(r.from_s) + 4} y={ROOM + 21} fontSize={11} fill="#0f172a" className="cursor-pointer"
                    onClick={() => go(`/assets/${r.uid}`)}>{r.name}</text>
            </g>
          ))}
          <rect x={M - 6} y={TOP} width={total * k + 12} height={BOTTOM - TOP} fill="#f8fafc" stroke="#475569" strokeWidth={1.2} rx={4} />
          <line x1={M} y1={AXIS} x2={M + total * k} y2={AXIS} stroke="#ef4444" strokeWidth={1} strokeDasharray="4 3" />
          {drawn.map((e, i) => {
            const g = glyph(e.element_kind);
            const x = X(e.s!);
            const w = Math.max((e.length ?? 0) * k, 3);
            const cx = x + w / 2;
            const sel = e.uid === selected;
            const st = stateOf(e);
            return (
              <g key={e.uid} className="cursor-pointer" onClick={() => onPick(e.uid)} role="button" tabIndex={0}
                 aria-label={`${e.name}, s ${e.s} m`} onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") onPick(e.uid); }}>
                <rect x={x} y={AXIS - g.h / 2} width={w} height={g.h} fill={g.c} stroke={sel ? "#0f172a" : "#fff"}
                      strokeWidth={sel ? 2 : 0.8} rx={1.5} />
                <polyline points={`${cx},${BOTTOM + 2} ${cx},${LBL - 6} ${lx[i]},${LBL - 2}`} fill="none" stroke="#cbd5e1" strokeWidth={0.8} />
                <text x={lx[i]} y={LBL} fontSize={11} fontWeight={sel ? 700 : 500} fill={sel ? "#1d4ed8" : "#334155"}
                      transform={`rotate(90 ${lx[i]} ${LBL})`} dominantBaseline="middle">{e.name}</text>
                <circle cx={lx[i]} cy={DOTS} r={4} fill={DOT[st]}>
                  <title>{st === "none" ? "no hardware installed" : st === "unplaced" ? "hardware not placed in a room" :
                          st === "tickets" ? "open tickets" : "hardware placed"}</title>
                </circle>
              </g>
            );
          })}
          {ticks.map((s) => (
            <g key={s}>
              <line x1={X(s)} y1={TICKS - 8} x2={X(s)} y2={TICKS - 3} stroke="#94a3b8" />
              <text x={X(s)} y={TICKS + 10} fontSize={10} textAnchor="middle" fill="#64748b">{s} m</text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {(Object.keys(DOT) as (keyof typeof DOT)[]).map((k) => (
        <li key={k} className="flex items-center gap-1">
          <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: DOT[k] }} />
          {k === "none" ? "no hardware installed" : k === "unplaced" ? "hardware without a room" : k === "tickets" ? "open tickets" : "hardware placed"}
        </li>
      ))}
    </ul>
  );
}

function Rooms({ v }: { v: TunnelView }) {
  if (v.rooms.length === 0) return <p className="text-xs text-slate-500">No room known for the hardware along this path.</p>;
  return (
    <p className="text-xs text-slate-600">
      Crosses:{" "}
      {v.rooms.map((r, i) => (
        <span key={`${r.uid}-${i}`}>{i > 0 && " → "}<Link to={`/assets/${r.uid}`} className="text-indigo-700 hover:underline">{r.name}</Link>
          {" "}<span className="text-slate-400">({r.from_s.toFixed(1)}–{r.to_s.toFixed(1)} m)</span></span>
      ))}
    </p>
  );
}

function Detail({ v, uid, onClose }: { v: TunnelView; uid: string | null; onClose: () => void }) {
  const e = v.elements.find((x) => x.uid === uid);
  if (!e) return <p className="text-sm text-slate-500">Click an element to see the hardware installed there and where it is.</p>;
  return (
    <section aria-label="Element" className="space-y-2 rounded border border-slate-200 bg-white p-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <Link to={`/assets/${e.uid}`} className="font-semibold text-indigo-700 hover:underline">{e.name}</Link>
          <div className="text-xs text-slate-500">
            {e.element_kind ?? "element"}{e.s != null && ` · s ${e.s} m`}{e.length ? ` · ${e.length} m long` : ""}
          </div>
        </div>
        <button type="button" onClick={onClose} className="text-xs text-slate-500 hover:underline">Close</button>
      </div>
      {e.hardware.length === 0 && <p className="text-slate-500">No hardware is installed at this position.</p>}
      {e.hardware.map((h) => (
        <div key={h.uid} className="space-y-1 border-t border-slate-100 pt-2">
          <div>
            <Link to={`/assets/${h.uid}`} className="font-medium text-indigo-700 hover:underline">{h.key || h.name}</Link>
            <span className="text-xs text-slate-500"> · {h.type}{h.serial ? ` · s/n ${h.serial}` : ""}</span>
          </div>
          <ul className="space-y-0.5 text-xs text-slate-700">
            <li>Room: {h.room ? <Link to={`/assets/${h.room.uid}`} className="text-indigo-700 hover:underline">{h.room.name}</Link>
                                 : <span className="text-amber-700">not known</span>}</li>
            {h.rack && <li>Rack: <Link to={`/racks/${h.rack.uid}?unit=${h.uid}`} className="text-indigo-700 hover:underline">{h.rack.key || h.rack.name}</Link></li>}
            <li>Plan: {h.spot ? <Link to={`/plans/${h.spot.plan.uid}?focus=${h.uid}`} className="text-indigo-700 hover:underline">
                         {h.spot.plan.name}{h.spot.via ? ` (where its ${h.spot.via.type.toLowerCase()} is)` : ""}</Link>
                               : <span className="text-slate-500">not on a floor plan</span>}</li>
            {h.supplies.map((s) => (
              <li key={s.uid}>Powered by <Link to={`/assets/${s.uid}`} className="text-indigo-700 hover:underline">{s.key || s.name}</Link>
                {s.rack && <> in rack <Link to={`/racks/${s.rack.uid}?unit=${s.uid}`} className="text-indigo-700 hover:underline">{s.rack.key || s.rack.name}</Link></>}
                {s.room && <span className="text-slate-500"> ({s.room.name})</span>}
              </li>
            ))}
            {h.tickets.map((tk) => (
              <li key={tk.uid}><Link to={`/tickets/${tk.uid}`} className="text-red-700 hover:underline">{tk.key ?? "Ticket"}</Link> {tk.title}
                <span className="text-slate-500"> ({tk.state})</span></li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
