/**
 * A rack surveyed from photos (docs/rack-census.md), on the web as on the phone: the rack (one already in ARGUS, or a
 * new record), a photo of its front whose units are seen top down and taken at once, each unit checked, linked or
 * made, the whole rack reviewed, then saved. What is read is proposed; nothing changes until the rack is saved.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  censusApi, censusProblem, type Census, type CensusItem, type CensusProposal, type CensusValue,
} from "../../api/client";
import type { Asset } from "../../api/types";
import { AuthenticatedImage } from "../../components/AuthenticatedImage";
import { Card } from "../../components/hub/ui";
import { notify } from "../../lib/dialogs";

const btn = "rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50";
const primary = "rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50";
const input = "w-full rounded-md border border-slate-300 px-2 py-1 text-sm";

const valueOf = (v: CensusValue | undefined): unknown => (v && typeof v === "object" ? v.value : v);
const pct = (c?: number | null) => (c == null ? "" : ` · ${Math.round(c * 100)}%`);

/** Records found by name, key, label or serial, to choose one. */
function FindRecord({ types, placeholder, onPick, testid }: {
  types?: string[]; placeholder: string; onPick: (a: Asset) => void; testid?: string;
}) {
  const [q, setQ] = useState("");
  const found = useQuery({ queryKey: ["census-find", q, types?.join()], queryFn: () => censusApi.find(q.trim(), types),
                           enabled: q.trim().length >= 2 });
  return (
    <div className="space-y-1">
      <input className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder}
             data-testid={testid} />
      {found.data && (
        <ul className="max-h-48 overflow-auto rounded-md border border-slate-200 text-sm">
          {found.data.length === 0 && <li className="px-2 py-1 text-slate-500">Nothing found.</li>}
          {found.data.map((a) => (
            <li key={a.uid}>
              <button type="button" className="w-full px-2 py-1 text-left hover:bg-slate-50"
                      onClick={() => { onPick(a); setQ(""); }}>
                {a.name} <span className="text-slate-500">{a.key} · {a.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PhotoButton({ label, onFile, disabled, testid }: {
  label: string; onFile: (f: File) => void; disabled?: boolean; testid?: string;
}) {
  return (
    <label className={`${btn} inline-block cursor-pointer ${disabled ? "pointer-events-none opacity-50" : ""}`}>
      {label}
      <input type="file" accept="image/*" capture="environment" className="hidden" data-testid={testid}
             onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) onFile(f); }} />
    </label>
  );
}

// --------------------------------------------------------------------------- start or resume

export function CensusStart() {
  const navigate = useNavigate();
  const open = useQuery({ queryKey: ["census-open"], queryFn: censusApi.open });
  const start = useMutation({
    mutationFn: (rack_uid?: string) => censusApi.start(rack_uid ? { rack_uid } : {}),
    onSuccess: (c) => navigate(`/racks/census/${c.uid}`),
    onError: (e) => notify(censusProblem(e), "error"),
  });
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <h1 className="text-xl font-semibold">Survey a rack</h1>
      <p className="text-sm text-slate-600">
        Photograph the rack's front: the units seen on it are proposed top down, and the rack itself can be a new
        record. What is read is proposed, never filled in for you; nothing changes in ARGUS until you review the whole
        rack and save it. You can stop and come back, here or on the phone.
      </p>
      <Card title="A rack not recorded yet">
        <button className={primary} onClick={() => start.mutate(undefined)} disabled={start.isPending}
                data-testid="census-new">Start from its photo</button>
      </Card>
      <Card title="A rack already in ARGUS">
        <FindRecord types={["Rack"]} placeholder="Rack name or key…" onPick={(a) => start.mutate(a.uid)}
                    testid="census-existing" />
      </Card>
      <Card title="Left half-way">
        {open.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
        {open.data?.length === 0 && <p className="text-sm text-slate-500">None.</p>}
        <ul className="divide-y divide-slate-100 text-sm">
          {open.data?.map((c) => (
            <li key={c.uid} className="py-2">
              <Link to={`/racks/census/${c.uid}`} className="text-slate-900 hover:underline">
                {c.rack ?? "A rack not identified yet"}
              </Link>
              <span className="text-slate-500"> · {c.items} unit{c.items === 1 ? "" : "s"} · {new Date(c.updated_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- the survey

export function CensusSurvey() {
  const { uid = "" } = useParams<{ uid: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const survey = useQuery({ queryKey: ["census", uid], queryFn: () => censusApi.get(uid) });
  const review = useQuery({ queryKey: ["census-review", uid], queryFn: () => censusApi.review(uid) });
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async <T,>(f: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    try {
      const out = await f();
      await qc.invalidateQueries({ queryKey: ["census", uid] });
      await qc.invalidateQueries({ queryKey: ["census-review", uid] });
      return out;
    } catch (e) {
      notify(censusProblem(e), "error");
      return undefined;
    } finally {
      setBusy(false);
    }
  };

  const c = survey.data;
  if (survey.isLoading) return <p className="p-6 text-sm text-slate-500">Loading the survey…</p>;
  if (!c) return <p className="p-6 text-sm text-red-700">{censusProblem(survey.error)}</p>;
  const editable = c.state === "open";

  const save = async () => {
    const out = await run(() => censusApi.apply(uid));
    if (!out) return;
    qc.invalidateQueries({ queryKey: ["census-open"] });
    notify(`${out.rack.name} saved: ${out.changes.length} unit(s), ${out.created.length} new record(s).`, "info");
    navigate(`/racks/${out.rack.uid}`);
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-xl font-semibold">Rack survey</h1>
        <Link to="/racks/census" className={btn}>Leave it for later</Link>
        {editable && (
          <button className={btn} disabled={busy} data-testid="census-abandon"
                  onClick={() => run(() => censusApi.abandon(uid)).then((r) => r && navigate("/racks/census"))}>
            Abandon
          </button>
        )}
      </div>
      {busy && <p className="text-sm text-slate-500" role="status">Working… reading a photo can take a minute.</p>}
      {!editable && <p className="rounded-md bg-amber-50 p-2 text-sm text-amber-900">This survey is {c.state}.</p>}

      <RackPart c={c} editable={editable && !busy} run={run} />
      <SeenPart c={c} editable={editable && !busy} run={run} />

      <Card title="2 · Its units">
        <div className="grid gap-4 md:grid-cols-[1fr_180px]">
          <ul className="divide-y divide-slate-100" data-testid="census-units">
            {c.items.length === 0 && <li className="py-2 text-sm text-slate-500">No unit yet.</li>}
            {c.items.map((i, n) => (
              <li key={i.id} className="py-2">
                <button type="button" className="flex w-full items-center gap-2 text-left text-sm"
                        onClick={() => setOpen(open === i.id ? null : i.id)} data-testid={`census-unit-${n}`}>
                  <span className="w-5 text-slate-400">{open === i.id ? "▾" : "▸"}</span>
                  <span className="font-medium">{title(i, n)}</span>
                  <span className="text-slate-500">{summary(i)}</span>
                </button>
                {open === i.id && <UnitEditor uid={uid} item={i} editable={editable && !busy} run={run} />}
              </li>
            ))}
          </ul>
          <MiniRack units={review.data?.units ?? (c.rack.record?.units ?? Number(c.rack.values.units ?? 42))} items={c.items}
                    onPick={setOpen} />
        </div>
        {editable && (
          <div className="mt-3">
            <PhotoButton label="Photograph one unit" disabled={busy} testid="census-unit-photo"
                         onFile={(f) => run(() => censusApi.photo(uid, "device", f)).then((r) => r?.item && setOpen(r.item))} />
          </div>
        )}
      </Card>

      <Card title="3 · Review and save">
        {review.data && (
          <div className="space-y-2 text-sm">
            {review.data.missing.map((m, k) => (
              <button key={k} type="button" className="block text-left text-amber-900 hover:underline"
                      onClick={() => m.item && setOpen(m.item)}>• {m.message}</button>
            ))}
            {review.data.problems.map((p, k) => <p key={k} className="text-red-700">• {p.message}</p>)}
            {review.data.ok && (
              <>
                {review.data.new_rack && <p>The rack will be made as a new record.</p>}
                {review.data.changes.map((ch) => <p key={ch}>→ {ch}</p>)}
                {review.data.new_records > 0 && <p>{review.data.new_records} new record(s) will be made.</p>}
              </>
            )}
            <button className={primary} disabled={!review.data.ok || !editable || busy} onClick={save}
                    data-testid="census-save">
              {review.data.ok ? "Save the rack" : "Resolve what is listed first"}
            </button>
          </div>
        )}
      </Card>
    </div>
  );
}

type Run = <T>(f: () => Promise<T>) => Promise<T | undefined>;

function title(i: CensusItem, n: number) {
  return String(valueOf(i.values.name) ?? i.proposals.name?.value ?? `Unit ${n + 1}`);
}

function span(i: CensusItem): [number, number] | null {
  const s = Number(valueOf(i.values.start_u)), h = Number(valueOf(i.values.height_u) ?? 1);
  return Number.isFinite(s) && s > 0 ? [s, s + Math.max(1, h || 1) - 1] : null;
}

function summary(i: CensusItem) {
  const sp = span(i);
  const words: Record<string, string> = { link: "existing record", create: "new record", skip: "left out" };
  const d = words[i.decision ?? ""] ?? "to decide";
  const dup = (i.duplicates ?? []).some((x) => x.strength !== "weak") && !i.duplicate_checked && i.decision !== "link";
  return [sp ? `U${sp[0]}${sp[1] > sp[0] ? `–U${sp[1]}` : ""}` : "U not set", d, dup ? "possible duplicate" : null]
    .filter(Boolean).join(" · ");
}

/** The rack drawn top down, each unit where it is set. */
function MiniRack({ units, items, onPick }: { units: number; items: CensusItem[]; onPick: (id: string) => void }) {
  const rows = Array.from({ length: Math.min(60, Math.max(1, units)) }, (_, k) => units - k);
  return (
    <div className="rounded-md border border-slate-300 bg-slate-50 p-1 text-[10px]" aria-label="The rack, top down">
      {rows.map((u) => {
        const at = items.find((i) => { const s = span(i); return s && s[0] <= u && u <= s[1] && i.decision !== "skip"; });
        const s = at ? span(at) : null;
        return (
          <div key={u} className="flex h-3.5 items-center gap-1">
            <span className="w-5 text-right text-slate-400">{u}</span>
            {at ? (
              <button type="button" onClick={() => onPick(at.id)} title={title(at, items.indexOf(at))}
                      className={`h-full flex-1 truncate bg-sky-200 px-1 text-left text-sky-900 ${s && s[1] === u ? "rounded-t" : ""} ${s && s[0] === u ? "rounded-b" : ""}`}>
                {s && s[1] === u ? title(at, items.indexOf(at)) : ""}
              </button>
            ) : <span className="h-full flex-1 border-b border-dashed border-slate-200" />}
          </div>
        );
      })}
    </div>
  );
}

// --------------------------------------------------------------------------- 1 · the rack

function RackPart({ c, editable, run }: { c: Census; editable: boolean; run: Run }) {
  const r = c.rack;
  const isNew = !r.record;
  const v = r.values;
  const [name, setName] = useState(String(v.name ?? ""));
  const [key, setKey] = useState(String(v.key ?? ""));
  const [units, setUnits] = useState(String(v.units ?? ""));
  const [room, setRoom] = useState<{ uid: string; name: string } | null>(
    v.place_uid ? { uid: String(v.place_uid), name: "the room chosen" } : null);
  const has = (role: string) => r.photos.some((p) => p.role === role);
  const setValues = (values: Record<string, unknown>) => run(() => censusApi.setRack(c.uid, { values }));
  return (
    <Card title="1 · The rack">
      <p className="mb-2 text-sm" data-testid="census-rack">
        {isNew
          ? <><b>{String(v.name || r.proposals.name?.value || "A new rack")}</b> — not recorded yet: it is made as a new record when the survey is saved.</>
          : <><b>{r.record!.name}</b> — in ARGUS, {r.record!.units} U.</>}
      </p>
      {editable && (
        <div className="mb-3 flex flex-wrap gap-2">
          <PhotoButton label={`Photo of the front${has("rack_front") ? " ✓" : ""}`} testid="census-rack-front"
                       onFile={(f) => run(() => censusApi.photo(c.uid, "rack_front", f)).then((o) => o?.reading.note && notify(o.reading.note, "info"))} />
          <PhotoButton label={`Photo of the rear${has("rack_rear") ? " ✓" : ""}`} testid="census-rack-rear"
                       onFile={(f) => run(() => censusApi.photo(c.uid, "rack_rear", f))} />
        </div>
      )}
      {r.photos.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {r.photos.map((p) => (
            <AuthenticatedImage key={p.uid} uid={p.uid} alt={p.role === "rack_rear" ? "Rack rear" : "Rack front"}
                                className="h-28 rounded border border-slate-200 object-cover" />
          ))}
        </div>
      )}
      {isNew && editable && (
        <div className="space-y-3">
          {(["name", "key", "units"] as const).filter((f) => r.proposals[f]).map((f) => (
            <Proposal key={f} field={f} p={r.proposals[f]} onUse={() => {
              const val = r.proposals[f].value;
              if (f === "name") setName(String(val)); else if (f === "key") setKey(String(val)); else setUnits(String(val));
              setValues({ [f]: val });
            }} />
          ))}
          {r.candidates.length > 0 && (
            <div className="text-sm">
              <p className="text-slate-600">It may be one already recorded:</p>
              {r.candidates.map((x) => (
                <div key={x.uid} className="flex items-center gap-2 py-1">
                  <span>{x.name} <span className="text-slate-500">{x.key} · {x.why}</span></span>
                  <button className={btn} onClick={() => run(() => censusApi.setRack(c.uid, { existing: x.uid }))}>It is this one</button>
                </div>
              ))}
            </div>
          )}
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="text-sm">Name<input className={input} value={name} onChange={(e) => setName(e.target.value)} data-testid="census-rack-name" /></label>
            <label className="text-sm">Identifier on its label<input className={input} value={key} onChange={(e) => setKey(e.target.value)} /></label>
            <label className="text-sm">Height in units (U)<input className={input} inputMode="numeric" value={units} onChange={(e) => setUnits(e.target.value)} data-testid="census-rack-units" /></label>
          </div>
          <div className="text-sm">
            <p>Room: <b>{room?.name ?? "not chosen"}</b> <span className="text-slate-500">(its point on the floor plan can be set later, on the plan)</span></p>
            <FindRecord placeholder="Find the room…" onPick={(a) => setRoom({ uid: a.uid, name: a.name })} testid="census-rack-room" />
          </div>
          <button className={primary} data-testid="census-rack-save" onClick={() => setValues({
            name: name.trim() || null, key: key.trim() || null, units: units.trim() ? Number(units) : null,
            place_uid: room?.uid ?? null,
          })}>Keep these values</button>
          <details className="text-sm">
            <summary className="cursor-pointer text-slate-600">It is a rack already in ARGUS</summary>
            <FindRecord types={["Rack"]} placeholder="Rack name or key…"
                        onPick={(a) => run(() => censusApi.setRack(c.uid, { existing: a.uid }))} />
          </details>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- the units seen on the rack photo

function SeenPart({ c, editable, run }: { c: Census; editable: boolean; run: Run }) {
  const seen = c.rack.seen;
  const [chosen, setChosen] = useState<Set<number> | null>(null);
  const [top, setTop] = useState("");
  const [use, setUse] = useState(true);
  const [rack, setRack] = useState(true);
  if (!seen || (seen.units.length === 0 && !seen.note)) return null;
  const taken = new Set(seen.taken);
  const free = seen.units.map((_, k) => k).filter((k) => !taken.has(k));
  const sel = chosen ?? new Set(free);
  const toggle = (k: number) => { const s = new Set(sel); if (s.has(k)) s.delete(k); else s.add(k); setChosen(s); };
  const isNew = !c.rack.record;
  return (
    <Card title={`Seen on the photo of the ${seen.face} — ${seen.units.length} unit${seen.units.length === 1 ? "" : "s"}`}>
      {seen.note && <p className="mb-2 text-sm text-slate-600">{seen.note}</p>}
      {seen.units.length > 0 && (
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <AuthenticatedImage uid={seen.photo} alt="The photo the units were seen on"
                              className="max-h-96 w-full rounded border border-slate-200 object-contain" />
          <div className="space-y-3 text-sm">
            <ol className="divide-y divide-slate-100" data-testid="census-seen">
              {seen.units.map((u, k) => (
                <li key={k} className="flex items-start gap-2 py-1">
                  <input type="checkbox" className="mt-1" disabled={taken.has(k) || !editable} checked={taken.has(k) || sel.has(k)}
                         onChange={() => toggle(k)} aria-label={`Take unit ${k + 1}`} />
                  <span>
                    <b>{k + 1}.</b> {u.label ?? ([u.manufacturer, u.model].filter(Boolean).join(" ") || u.kind || "Unit")}
                    <span className="text-slate-500">
                      {" "}· {u.type ?? (u.kind ? `${u.kind} (not a type here)` : "type not read")} · {u.height_u ?? "?"} U
                      {u.gap_above_u ? ` · ${u.gap_above_u} U empty above` : ""}{u.start_u ? ` · at U${u.start_u}` : ""}{pct(u.confidence)}
                      {taken.has(k) ? " · in the survey" : ""}
                    </span>
                    {u.evidence && <span className="block text-xs text-slate-400">{u.evidence}</span>}
                  </span>
                </li>
              ))}
            </ol>
            {editable && free.length > 0 && (
              <div className="space-y-2 rounded-md bg-slate-50 p-3">
                <label className="block">The top unit of the first one (U), to count the others down
                  <input className={`${input} mt-1 max-w-24`} inputMode="numeric" value={top} onChange={(e) => setTop(e.target.value)}
                         placeholder={String(c.rack.record?.units ?? c.rack.values.units ?? "")} data-testid="census-seen-top" />
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={use} onChange={(e) => setUse(e.target.checked)} />
                  Use what was read as the values (each still to check; a name not written on a unit is made up and says so)
                </label>
                {isNew && (
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={rack} onChange={(e) => setRack(e.target.checked)} data-testid="census-seen-rack" />
                    Record the rack itself too, as a new record
                  </label>
                )}
                <button className={primary} disabled={sel.size === 0} data-testid="census-seen-take"
                        onClick={() => run(() => censusApi.takeSeen(c.uid, {
                          units: [...sel].filter((k) => !taken.has(k)), use, rack: isNew && rack,
                          ...(top.trim() ? { top_u: Number(top) } : {}),
                        })).then(() => setChosen(null))}>
                  Add {sel.size} unit{sel.size === 1 ? "" : "s"} to the survey
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- one unit

const FIELDS: { f: string; label: string; number?: boolean }[] = [
  { f: "name", label: "Name" }, { f: "manufacturer", label: "Manufacturer" }, { f: "model", label: "Model" },
  { f: "serial", label: "Serial number" }, { f: "height_u", label: "Height (U)", number: true },
  { f: "start_u", label: "Lowest unit (U)", number: true },
];

function Proposal({ field, p, onUse }: { field: string; p: CensusProposal; onUse?: () => void }) {
  const weak = p.grounded === false || (p.confidence != null && p.confidence < 0.6);
  return (
    <div className={`flex items-start gap-2 rounded px-2 py-1 text-sm ${weak ? "bg-amber-50" : "bg-sky-50"}`}>
      <span className="flex-1">
        <span className="text-slate-500">{field}:</span> <b>{p.label ?? String(p.value)}</b>
        <span className="text-slate-500"> · {p.source}{pct(p.confidence)}{p.grounded === false ? " · not read" : ""}</span>
        {p.evidence && <span className="block text-xs text-slate-500">“{p.evidence}”</span>}
      </span>
      {onUse && <button type="button" className={btn} onClick={onUse}>Use</button>}
    </div>
  );
}

function UnitEditor({ uid, item, editable, run }: { uid: string; item: CensusItem; editable: boolean; run: Run }) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const set = (body: Parameters<typeof censusApi.setItem>[2]) => run(() => censusApi.setItem(uid, item.id, body));
  const shown = (f: string) => draft[f] ?? (valueOf(item.values[f]) == null ? "" : String(valueOf(item.values[f])));
  const tv = valueOf(item.values.type);
  const typeName = tv == null ? "" : tv === item.proposals.type?.value ? (item.proposals.type.label ?? String(tv)) : String(tv);
  return (
    <div className="ml-7 mt-2 space-y-3">
      {item.note && <p className="text-sm text-slate-600">{item.note}</p>}
      {(item.photos.length > 0 || item.seen_in) && (
        <div className="flex flex-wrap gap-2">
          {item.photos.map((p) => <AuthenticatedImage key={p.uid} uid={p.uid} alt={p.role} className="h-20 rounded border object-cover" />)}
        </div>
      )}
      <div className="space-y-1">
        {Object.entries(item.proposals).map(([f, p]) => (
          <Proposal key={f} field={f === "product_model" ? "catalogue model" : f} p={p}
                    onUse={editable && valueOf(item.values[f]) !== p.value
                      ? () => set({ values: { [f]: { value: p.value, source: p.source, ...(p.confidence ? { confidence: p.confidence } : {}) } } })
                      : undefined} />
        ))}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="text-sm">Type
          <input className={input} value={draft.type ?? typeName} disabled={!editable}
                 onChange={(e) => setDraft({ ...draft, type: e.target.value })}
                 onBlur={() => draft.type !== undefined && set({ values: { type: draft.type.trim() || null } })} />
        </label>
        {FIELDS.map(({ f, label, number }) => (
          <label key={f} className="text-sm">{label}
            <input className={input} value={shown(f)} disabled={!editable} inputMode={number ? "numeric" : undefined}
                   onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
                   onBlur={() => {
                     if (draft[f] === undefined) return;
                     const t = draft[f].trim();
                     setDraft(({ [f]: _gone, ...rest }) => rest);
                     set({ values: { [f]: t === "" ? null : number ? Number(t) : t } });
                   }} />
          </label>
        ))}
        <label className="text-sm">Face
          <select className={input} value={String(valueOf(item.values.face) ?? "front")} disabled={!editable}
                  onChange={(e) => set({ values: { face: e.target.value } })}>
            <option value="front">front</option><option value="rear">rear</option><option value="both">both (through)</option>
          </select>
        </label>
      </div>
      {(item.duplicates ?? []).length > 0 && (
        <div className="text-sm">
          <p className="text-slate-600">It may already be:</p>
          {item.duplicates!.map((d) => (
            <div key={d.uid} className="flex flex-wrap items-center gap-2 py-1">
              <span className={d.strength === "strong" ? "text-red-700" : ""}>
                {d.name} <span className="text-slate-500">{d.key} · {d.why}{d.mounted?.rack ? ` · in ${d.mounted.rack}` : ""}</span>
              </span>
              {editable && <button className={btn} onClick={() => set({ asset_uid: d.uid })}>It is this one</button>}
            </div>
          ))}
          {editable && item.decision === "create" && (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={!!item.duplicate_checked} onChange={(e) => set({ duplicate_checked: e.target.checked })} />
              I checked: it is another unit
            </label>
          )}
        </div>
      )}
      {editable && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-600">Record:</span>
          {(["create", "link", "skip"] as const).map((d) => (
            <button key={d} className={item.decision === d ? primary : btn} onClick={() => set({ decision: d })}>
              {{ create: "Make a new one", link: "An existing one", skip: "Leave it out" }[d]}
            </button>
          ))}
          {item.decision === "link" && (
            <div className="w-full sm:w-80">
              {item.asset_uid && <p className="text-slate-600">Linked.</p>}
              <FindRecord placeholder="Find the record…" onPick={(a) => set({ asset_uid: a.uid })} />
            </div>
          )}
          <PhotoButton label="Its label" onFile={(f) => run(() => censusApi.photo(uid, "label", f, item.id))} />
          <PhotoButton label="Another photo" onFile={(f) => run(() => censusApi.photo(uid, "device", f, item.id))} />
          <button className={`${btn} text-red-700`} onClick={() => run(() => censusApi.removeItem(uid, item.id))}>Remove</button>
        </div>
      )}
    </div>
  );
}
