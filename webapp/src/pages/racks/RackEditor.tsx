/**
 * The rack editor (docs/rack-elevation.md): the rack front and rear, what is mounted dragged or placed by a form,
 * and every change shown as a preview — in words and on the drawing — before it is confirmed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { problemText, racksApi, type RackCandidate, type RackElevationView, type RackMountingView, type RackOp } from "../../api/client";
import { RackElevation, nameOf, spanOf } from "../../components/RackElevation";
import { Card } from "../../components/hub/ui";
import { notify } from "../../lib/dialogs";

type Face = "front" | "rear" | "both";

/** The lowest unit where `height` units are free on a face (both faces for a unit through the rack). */
function firstFree(view: RackElevationView, height: number, face: Face): number | undefined {
  const fits = (f: "front" | "rear") => view.free[f].filter((r) => r.units >= height);
  if (face !== "both") return fits(face)[0]?.from_u;
  for (const r of fits("front")) {
    for (let u = r.from_u; u + height - 1 <= r.to_u; u++) {
      if (view.free.rear.some((b) => b.from_u <= u && u + height - 1 <= b.to_u)) return u;
    }
  }
  return undefined;
}

export default function RackEditor() {
  const { uid } = useParams<{ uid: string }>();
  const queryClient = useQueryClient();
  const [ops, setOps] = useState<RackOp[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  // `?unit=` — the unit looked for (from the floor plan, through its rack): selected until another is chosen.
  const [params] = useSearchParams();
  const [lookedFor, setLookedFor] = useState<string | null>(params.get("unit"));
  const [search, setSearch] = useState("");
  const [draft, setDraft] = useState<{ c: RackCandidate; start: string; height: string; face: Face; kind: "device" | "zero_u"; shelf: string } | null>(null);
  const [space, setSpace] = useState<{ what: "shelf" | "reserve"; start: string; height: string; face: Face; label: string }>(
    { what: "reserve", start: "", height: "1", face: "front", label: "" });
  const [showHistory, setShowHistory] = useState(false);

  const stored = useQuery({ queryKey: ["rack", uid], queryFn: () => racksApi.get(uid!), enabled: !!uid });
  const preview = useQuery({
    queryKey: ["rack-preview", uid, JSON.stringify(ops)], queryFn: () => racksApi.preview(uid!, ops),
    enabled: !!uid && ops.length > 0, placeholderData: (prev) => prev,
  });
  const found = useQuery({ queryKey: ["rack-candidates", search], queryFn: () => racksApi.candidates(search.trim()),
                           enabled: search.trim().length >= 2 });
  const history = useQuery({ queryKey: ["rack-history", uid], queryFn: () => racksApi.history(uid!), enabled: !!uid && showHistory });
  const apply = useMutation({
    mutationFn: () => racksApi.apply(uid!, ops),
    onSuccess: (r) => {
      setOps([]);
      setSelected(null);
      queryClient.invalidateQueries({ queryKey: ["rack", uid] });
      queryClient.invalidateQueries({ queryKey: ["rack-history", uid] });
      queryClient.invalidateQueries({ queryKey: ["relations"] });
      notify(`Rack saved: ${r.changes.length} change${r.changes.length === 1 ? "" : "s"}.${r.notes?.length ? `\n${r.notes.join("\n")}` : ""}`, "info");
    },
  });

  if (stored.isError) return <p className="text-sm text-rose-700">{problemText(stored.error)}</p>;
  if (!stored.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const staged = ops.length > 0 && preview.data ? preview.data : null;
  const view = staged?.elevation ?? stored.data;
  const problems = staged?.problems ?? stored.data.problems;
  const sel = view.mountings.find((m) => m.uid === selected)
    ?? (selected === null && lookedFor ? view.mountings.find((m) => m.asset?.uid === lookedFor) : undefined) ?? null;
  const staging = new Set(ops.map((o) => o.asset_uid).filter(Boolean));
  const waiting = (stored.data.unplaced ?? []).filter((c) => !staging.has(c.uid));
  const lostUnit = lookedFor && selected === null && !sel && !waiting.some((c) => c.uid === lookedFor) ? lookedFor : null;
  const shelves = view.mountings.filter((m) => m.kind === "shelf");

  /** The staged operation that made or moved this block, if it is not a stored one. */
  const opOf = (m: RackMountingView) => ops.findIndex((o) => (m.asset ? o.asset_uid === m.asset.uid && o.op !== "remove"
    : (o.op === "shelf" || o.op === "reserve" || o.op === "update") && o.start_u === m.start_u
      && (o.height_u ?? m.height_u) === m.height_u && (o.face ?? m.face) === m.face && (o.label ?? null) === (m.label ?? null)));

  const stage = (op: RackOp, replaceAt = -1) => setOps((all) => {
    const rest = all.filter((o, i) => i !== replaceAt
      && !(op.asset_uid && o.asset_uid === op.asset_uid) && !(op.mounting_uid && o.mounting_uid === op.mounting_uid));
    return [...rest, op];
  });

  const move = (m: RackMountingView, to: { start_u?: number; height_u?: number; face?: Face }) => {
    const next = { start_u: to.start_u ?? m.start_u ?? 1, height_u: to.height_u ?? m.height_u, face: to.face ?? m.face };
    if (m.asset) {
      stage({ op: "place", asset_uid: m.asset.uid, kind: m.kind === "zero_u" ? "zero_u" : "device", ...next });
    } else {
      const at = opOf(m);
      if (at >= 0) setOps((all) => all.map((o, i) => (i === at ? { ...o, ...next } : o)));
      else stage({ op: "update", mounting_uid: m.uid, label: m.label ?? undefined, ...next });
    }
  };

  const drop = (mountingUid: string, u: number, face: "front" | "rear") => {
    const m = view.mountings.find((x) => x.uid === mountingUid);
    if (m) move(m, { start_u: u, face: m.face === "both" ? "both" : face });
  };

  const takeOut = (m: RackMountingView) => {
    const at = opOf(m);
    if (m.since == null && at >= 0) setOps((all) => all.filter((_, i) => i !== at));   // never stored: just not done
    else stage(m.asset ? { op: "remove", asset_uid: m.asset.uid } : { op: "remove", mounting_uid: m.uid });
    setSelected(null);
  };

  const choose = (c: RackCandidate) => {
    const height = c.suggested_height_u ?? 1;
    setDraft({ c, height: String(height), face: "front", kind: "device", shelf: "", start: String(firstFree(view, height, "front") ?? "") });
  };

  const input = "w-full rounded border border-slate-300 px-2 py-1 text-sm";
  const small = "rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{view.rack.name}</h1>
          <p className="text-sm text-slate-500">
            <span className="font-mono">{view.rack.key}</span> · {view.rack.units} U ·{" "}
            <Link to={`/assets/${view.rack.uid}`} className="text-indigo-600 hover:underline">the rack's record</Link>
            {" · "}<Link to={`/floor-plan?show=${view.rack.uid}`} className="text-indigo-600 hover:underline">on the floor plan</Link>
            {view.plan && <>{" · "}<Link to={`/plans/${view.plan.uid}?focus=${view.rack.uid}`} className="text-indigo-600 hover:underline">plan with layers</Link></>}
          </p>
        </div>
        <p className="text-xs text-slate-500">Drag a block to another unit, or use the forms. Nothing is saved until you confirm.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card title="Elevation" action={<span className="text-xs text-slate-400">U1 at the bottom</span>}>
          <RackElevation view={view} selected={sel?.uid ?? null} problems={problems}
                         onSelect={(m) => { setLookedFor(null); setSelected(m.uid); }} onDrop={drop} />
          {lostUnit && (
            <p className="mt-2 text-xs text-amber-700">
              The unit looked for is in this rack but has no position in it yet: <Link to={`/assets/${lostUnit}`}
              className="underline">open its record</Link>, or mount it here.
            </p>
          )}
        </Card>

        <div className="space-y-4">
          {(ops.length > 0 || problems.length > 0) && (
            <Card title={ops.length > 0 ? "Changes to confirm" : "What is wrong now"}>
              {staged?.changes.map((c, i) => <p key={i} className="text-sm text-slate-800">{c.text}</p>)}
              {problems.map((p, i) => <p key={i} className="mt-1 text-sm text-red-700">{p.message}</p>)}
              {apply.isError && <p className="mt-1 text-sm text-red-700">{problemText(apply.error)}</p>}
              {ops.length > 0 && (
                <div className="mt-3 flex gap-2">
                  <button type="button" disabled={apply.isPending || !staged?.ok} onClick={() => apply.mutate()}
                          title={staged && !staged.ok ? "Resolve what is wrong first" : undefined}
                          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40">
                    Confirm {ops.length} change{ops.length === 1 ? "" : "s"}
                  </button>
                  <button type="button" onClick={() => { setOps([]); setSelected(null); }} className={small}>Discard</button>
                </div>
              )}
            </Card>
          )}

          {sel && (
            <Card title={nameOf(sel)} action={<button type="button" onClick={() => setSelected(null)} className="text-xs text-slate-400">close</button>}>
              <p className="text-xs text-slate-500">
                {spanOf(sel)} · {sel.face}{sel.asset ? ` · ${sel.asset.type}` : ""}{sel.since ? ` · since ${new Date(sel.since).toLocaleDateString()}` : " · not saved yet"}
              </p>
              {sel.asset && (
                <p className="mt-1 text-xs">
                  <Link to={`/assets/${sel.asset.uid}`} className="text-indigo-600 hover:underline">Open {sel.asset.key ?? "the record"}</Link>
                  <span className="text-slate-400"> — its ports, cables, tickets, documents and photos</span>
                </p>
              )}
              {sel.top_u != null && (
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <label>First unit<input type="number" min={1} max={view.rack.units} value={sel.start_u ?? 1} className={input}
                                          onChange={(e) => move(sel, { start_u: Number(e.target.value) || 1 })} /></label>
                  <label>Height (U)<input type="number" min={1} max={view.rack.units} value={sel.height_u} className={input}
                                          onChange={(e) => move(sel, { height_u: Number(e.target.value) || 1 })} /></label>
                  <label>Side<select value={sel.face} className={input} onChange={(e) => move(sel, { face: e.target.value as Face })}>
                    <option value="front">front</option><option value="rear">rear</option><option value="both">both</option>
                  </select></label>
                </div>
              )}
              {sel.evidence && <p className="mt-2 text-xs text-slate-500">Read from a photograph: {JSON.stringify(sel.evidence)}</p>}
              <button type="button" onClick={() => takeOut(sel)} className="mt-3 rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50">
                Take it out of the rack
              </button>
            </Card>
          )}

          {waiting.length > 0 && (
            <Card title="In this rack, no position yet">
              <p className="text-xs text-slate-500">Said to be in this rack, but not on its drawing: give each its units.</p>
              <ul className="mt-1 max-h-56 divide-y divide-slate-100 overflow-auto">
                {waiting.map((c) => (
                  <li key={c.uid} className={`flex items-center justify-between gap-2 py-1 text-xs ${c.uid === lookedFor ? "bg-amber-50" : ""}`}>
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-slate-800">{c.name}</span>
                      <span className="block truncate text-slate-500">{c.type}{c.serial ? ` · s/n ${c.serial}` : ""}
                        {c.suggested_height_u ? ` · ${c.suggested_height_u} U suggested` : ""}</span>
                    </span>
                    <button type="button" onClick={() => choose(c)} className={small}>Mount…</button>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Mount a unit" action={<Link to="/assets/new" target="_blank" className="text-xs text-indigo-600 hover:underline">New record…</Link>}>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, key or serial…" className={input} aria-label="Find a record to mount" />
            {search.trim().length >= 2 && found.data?.length === 0 && (
              <p className="mt-1 text-xs text-slate-500">Nothing by that name here. Make it with “New record…”, then find it.</p>
            )}
            <ul className="mt-1 max-h-48 divide-y divide-slate-100 overflow-auto">
              {found.data?.map((c) => (
                <li key={c.uid} className="flex items-center justify-between gap-2 py-1 text-xs">
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-800">{c.name}</span>
                    <span className="block truncate text-slate-500">
                      {c.type}{c.key ? ` · ${c.key}` : ""}{c.serial ? ` · s/n ${c.serial}` : ""}
                      {c.mounted ? ` · now in ${c.mounted.rack ?? "a rack"}${c.mounted.start_u ? ` U${c.mounted.start_u}` : ""}` : ""}
                    </span>
                  </span>
                  <button type="button" onClick={() => choose(c)} className={small}>{c.mounted ? "Move here" : "Mount"}</button>
                </li>
              ))}
            </ul>
            {draft && (
              <form className="mt-2 space-y-2 rounded border border-slate-200 bg-slate-50 p-2 text-xs"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const zero = draft.kind === "zero_u";
                      stage({ op: "place", asset_uid: draft.c.uid, kind: draft.kind, face: draft.face,
                              ...(draft.shelf ? { shelf_uid: draft.shelf } : zero ? {} : { start_u: Number(draft.start) }),
                              ...(zero ? {} : { height_u: Number(draft.height) || 1 }) });
                      setDraft(null);
                      setSearch("");
                    }}>
                <p className="font-medium text-slate-800">{draft.c.name}</p>
                <div className="grid grid-cols-2 gap-2">
                  <label>How<select value={draft.kind} className={input} onChange={(e) => setDraft({ ...draft, kind: e.target.value as "device" | "zero_u" })}>
                    <option value="device">in rack units</option><option value="zero_u">0U (on the post)</option>
                  </select></label>
                  <label>Side<select value={draft.face} className={input}
                                     onChange={(e) => { const face = e.target.value as Face; setDraft({ ...draft, face, start: String(firstFree(view, Number(draft.height) || 1, face) ?? draft.start) }); }}>
                    <option value="front">front</option><option value="rear">rear</option><option value="both">both (full depth)</option>
                  </select></label>
                  {draft.kind === "device" && !draft.shelf && (
                    <label>First unit<input type="number" required min={1} max={view.rack.units} value={draft.start} className={input}
                                            onChange={(e) => setDraft({ ...draft, start: e.target.value })} /></label>
                  )}
                  {draft.kind === "device" && (
                    <label>Height (U){draft.c.suggested_height_u ? <span className="text-slate-400"> · model says {draft.c.suggested_height_u}</span> : null}
                      <input type="number" required min={1} max={view.rack.units} value={draft.height} className={input}
                             onChange={(e) => setDraft({ ...draft, height: e.target.value })} /></label>
                  )}
                  {draft.kind === "device" && shelves.length > 0 && (
                    <label className="col-span-2">Standing on<select value={draft.shelf} className={input} onChange={(e) => setDraft({ ...draft, shelf: e.target.value })}>
                      <option value="">the rails (its own units)</option>
                      {shelves.filter((s) => s.since != null).map((s) => <option key={s.uid} value={s.uid}>{nameOf(s)} ({spanOf(s)})</option>)}
                    </select></label>
                  )}
                </div>
                <div className="flex gap-2">
                  <button type="submit" className="rounded bg-slate-900 px-2 py-1 text-white">Add to the changes</button>
                  <button type="button" onClick={() => setDraft(null)} className={small}>Cancel</button>
                </div>
              </form>
            )}
          </Card>

          <Card title="Shelf or reserved space">
            <form className="grid grid-cols-2 gap-2 text-xs"
                  onSubmit={(e) => {
                    e.preventDefault();
                    stage({ op: space.what, start_u: Number(space.start), height_u: Number(space.height) || 1, face: space.face,
                            label: space.label.trim() || undefined });
                    setSpace({ ...space, start: "", label: "" });
                  }}>
              <label>What<select value={space.what} className={input} onChange={(e) => setSpace({ ...space, what: e.target.value as "shelf" | "reserve" })}>
                <option value="reserve">reserved space</option><option value="shelf">shelf</option>
              </select></label>
              <label>Side<select value={space.face} className={input} onChange={(e) => setSpace({ ...space, face: e.target.value as Face })}>
                <option value="front">front</option><option value="rear">rear</option><option value="both">both</option>
              </select></label>
              <label>First unit<input type="number" required min={1} max={view.rack.units} value={space.start} className={input}
                                      onChange={(e) => setSpace({ ...space, start: e.target.value })} /></label>
              <label>Height (U)<input type="number" required min={1} max={view.rack.units} value={space.height} className={input}
                                      onChange={(e) => setSpace({ ...space, height: e.target.value })} /></label>
              <label className="col-span-2">{space.what === "reserve" ? "Kept for" : "Name"}
                <input value={space.label} className={input} onChange={(e) => setSpace({ ...space, label: e.target.value })}
                       placeholder={space.what === "reserve" ? "the second core switch" : "shelf for small boxes"} /></label>
              <button type="submit" className="col-span-2 justify-self-start rounded bg-slate-900 px-2 py-1 text-white">Add to the changes</button>
            </form>
          </Card>

          <Card title="History" action={<button type="button" onClick={() => setShowHistory((v) => !v)} className="text-xs text-indigo-600">{showHistory ? "hide" : "show"}</button>}>
            {!showHistory ? <p className="text-xs text-slate-500">Every mounting this rack has had, and who changed it.</p> : (
              <ul className="max-h-64 space-y-1 overflow-auto text-xs">
                {history.data?.length === 0 && <li className="text-slate-500">Nothing yet.</li>}
                {history.data?.map((h) => (
                  <li key={h.uid} className="border-l-2 border-slate-100 pl-2">
                    <span className="text-slate-800">{nameOf(h)}</span> · {spanOf(h)} {h.face}
                    <span className="block text-slate-400">
                      {h.from ? new Date(h.from).toLocaleString() : ""}{h.until ? ` → ${new Date(h.until).toLocaleString()} (${h.state === "removed" ? "taken out" : "moved"})` : " → now"}
                      {h.by ? ` · ${h.by}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
