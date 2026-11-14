import { ask } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { LayoutView, LineView, place } from "./LatticeViews";
import { Link, useSearchParams } from "react-router-dom";
import { beamModelApi } from "../../api/client";
import { downloadJson } from "./BeamModelEditor";
import type { BeamElementContext, BeamNode, BeamPathGraph, BeamRecord } from "../../api/types";

/** The beam model (docs/beam-model.md): a path drawn as the machine is laid out, or unrolled along `s`, with
 *  its branches as edges; and, for a selected position, both what the physics model says and what the facility
 *  knows behind it — hardware installed and its history, power, controls (signal identities, never values),
 *  documentation and tickets. ARGUS is not the viewer of record: this page shows what the API gives one. */

export function BeamModelPage() {
  const [params, setParams] = useSearchParams();
  const systems = useQuery({ queryKey: ["beam-systems"], queryFn: beamModelApi.systems });
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: beamModelApi.removeModel,
    onSuccess: () => {
      setParams({});
      void queryClient.invalidateQueries({ queryKey: ["beam-systems"] });
    },
  });
  // The first system's main path (its largest) when none is chosen: the ring, not its extraction line.
  const pathUid = params.get("path") ?? mainPath(systems.data?.[0]?.paths ?? []) ?? null;
  const [dataset, setDataset] = useState<string | null>(null);
  const [view, setView] = useState<"layout" | "unrolled">("layout");
  const selected = params.get("element");

  const graph = useQuery({
    queryKey: ["beam-graph", pathUid, dataset],
    queryFn: () => beamModelApi.pathGraph(pathUid!, dataset),
    enabled: !!pathUid,
  });
  const datasets = useQuery({
    queryKey: ["beam-datasets", pathUid],
    queryFn: () => beamModelApi.datasets(pathUid!),
    enabled: !!pathUid,
  });
  const context = useQuery({
    queryKey: ["beam-context", selected, dataset],
    queryFn: () => beamModelApi.context(selected!, dataset),
    enabled: !!selected,
  });

  // Laid out from the dataset's geometry, or the survey of its lengths and bends; never from some elements only.
  const placed = useMemo(() => (graph.data ? place(graph.data) : null), [graph.data]);
  const hasLayout = !!placed;
  useEffect(() => {
    setView(hasLayout ? "layout" : "unrolled");
  }, [pathUid, hasLayout]);
  useEffect(() => setDataset(null), [pathUid]);

  const go = (path: string | null, element?: string | null) => {
    const next: Record<string, string> = {};
    if (path) next.path = path;
    if (element) next.element = element;
    setParams(next);
  };

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] min-h-0">
      <aside className="w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-3 text-sm">
        <h1 className="text-base font-semibold text-slate-900">Beam model</h1>
        <p className="mt-1 text-xs text-slate-500">Physics positions linked to the equipment, controls and documentation behind them.</p>
        <div className="mt-2 flex flex-wrap gap-1">
          <Link to="/beam-model/new" className="rounded bg-slate-900 px-2 py-1 text-xs text-white">New / import</Link>
          {(systems.data ?? []).length > 0 && (
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-xs"
                    onClick={() => void beamModelApi.exportAll().then((b) => downloadJson("beam-models.json", b))}>Export all</button>
          )}
        </div>
        {remove.isError && (
          <p className="mt-2 text-xs text-rose-700">{String((remove.error as Error).message ?? remove.error)}</p>
        )}
        {systems.data?.length === 0 && (
          <p className="mt-4 text-xs text-slate-500">
            No beam model in this workspace. Import one with <code>POST /v1/beam-model/import</code>, or try the demo
            workspace (<code>scripts/beam_model_demo.py</code>).
          </p>
        )}
        {(systems.data ?? []).map((s) => (
          <div key={s.uid} className="mt-4">
            <div className="flex items-baseline justify-between gap-1">
              <span className="font-medium text-slate-900">{s.name}</span>
              {s.model_id && (
                <span className="flex gap-1 text-[11px]">
                  <Link to={`/beam-model/edit/${encodeURIComponent(s.model_id)}`} className="text-indigo-700 hover:underline">edit</Link>
                  <Link to={`/beam-model/${encodeURIComponent(s.model_id)}/assets`} className="text-indigo-700 hover:underline"
                        title="Match the model's components to physical assets">assets</Link>
                  <button type="button" className="text-indigo-700 hover:underline"
                          onClick={() => void beamModelApi.exportModel(s.model_id!).then((m) => downloadJson(`${s.model_id}.json`, m))}>export</button>
                  <button type="button" className="text-rose-700 hover:underline" disabled={remove.isPending}
                          title="Remove the whole model from this workspace"
                          onClick={async () => {
                            if (await ask(`Remove the beam model ${s.model_id} from this workspace?\n\n` +
                                "Its systems, paths, elements and datasets are retired (their history, tickets and " +
                                "installations stay); its values, stored documents and asset bindings are deleted. " +
                                "Importing the model again brings it back.")) remove.mutate(s.model_id!);
                          }}>remove</button>
                </span>
              )}
            </div>
            <div className="text-xs text-slate-500">
              {s.system_kind}
              {s.beams.map((b) => ` · ${beamLabel(b)}`).join("")}
            </div>
            <ul className="mt-1">
              {s.paths.map((p) => (
                <li key={p.uid}>
                  <button type="button" onClick={() => go(p.uid)}
                          className={`w-full rounded px-2 py-1 text-left ${p.uid === pathUid ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                    {p.name} <span className={p.uid === pathUid ? "text-slate-300" : "text-slate-400"}>· {p.topology}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-slate-50">
        {graph.data && (
          <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2 text-sm">
            <span className="font-medium text-slate-900">{graph.data.path.name}</span>
            <Link to={`/tunnel/${graph.data.path.uid}`} className="text-xs text-indigo-700 hover:underline">Tunnel with the hardware →</Link>
            <span className="text-xs text-slate-500">
              {graph.data.topology} · {graph.data.nodes.length} elements
              {graph.data.length ? ` · ${graph.data.topology === "closed" ? "circumference" : "length"} ${graph.data.length} m` : ""}
            </span>
            <div className="flex rounded border border-slate-300 text-xs">
              {(["layout", "unrolled"] as const).map((v) => (
                <button key={v} type="button" disabled={v === "layout" && !hasLayout} onClick={() => setView(v)}
                        className={`px-2 py-1 ${view === v ? "bg-slate-900 text-white" : "text-slate-600 disabled:text-slate-300"}`}>
                  {v === "layout" ? "Layout" : "Unrolled"}
                </button>
              ))}
            </div>
            <select value={dataset ?? graph.data.dataset_uid ?? ""} onChange={(e) => setDataset(e.target.value || null)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs">
              {(datasets.data ?? []).length === 0 && <option value="">no dataset</option>}
              {(datasets.data ?? []).map((d) => <option key={d.uid} value={d.uid}>{d.name} ({d.dataset_kind})</option>)}
            </select>
          </div>
        )}
        <div className="relative min-h-0 flex-1">
          {graph.data && (view === "layout" && hasLayout
            ? <LayoutView g={graph.data} placed={placed!} selected={selected} onPick={(u) => go(pathUid, u)} />
            : <LineView g={graph.data} selected={selected} onPick={(u) => go(pathUid, u)} />)}
        </div>
        {graph.data && (graph.data.branches_out.length > 0 || graph.data.branches_in.length > 0) && (
          <div className="flex flex-wrap gap-3 border-t border-slate-200 bg-white px-4 py-2 text-xs">
            {graph.data.branches_out.map((b) => (
              <button key={`o${b.to}`} type="button" onClick={() => b.to_path && go(b.to_path.uid)}
                      className="rounded border border-violet-300 bg-violet-50 px-2 py-1 text-violet-800">
                {nodeName(graph.data!, b.from)} branches to → {b.to_path?.name}
              </button>
            ))}
            {graph.data.branches_in.map((b) => (
              <button key={`i${b.from}`} type="button" onClick={() => b.from_path && go(b.from_path.uid)}
                      className="rounded border border-violet-300 bg-violet-50 px-2 py-1 text-violet-800">
                ← branched from {b.from_path?.name}
              </button>
            ))}
          </div>
        )}
      </section>

      <aside className="w-96 shrink-0 overflow-y-auto border-l border-slate-200 bg-white p-4 text-sm">
        {!selected && <p className="text-slate-500">Select an element to see its physics and what the facility knows behind it.</p>}
        {context.isLoading && <p className="text-slate-400">Loading…</p>}
        {context.data && <ElementPanel c={context.data} onPick={(u) => go(pathUid, u)} />}
      </aside>
    </div>
  );
}

function mainPath(paths: BeamRecord[]): string | undefined {
  // Paths carry no element count here; a closed path is a ring's main path, otherwise the first listed.
  return (paths.find((p) => p.topology === "closed") ?? paths[0])?.uid;
}

function beamLabel(b: BeamRecord) {
  const a = b.attributes ?? {};
  if (b.type === "Photon Beam") return `${a.wavelength ?? "?"} nm photons`;
  return `${a.species ?? "particles"}${a.reference_energy ? ` ${a.reference_energy} GeV` : ""}`;
}

function nodeName(g: BeamPathGraph, uid: string) {
  return g.nodes.find((n) => n.uid === uid)?.name ?? "";
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <div className="mt-1 space-y-1 text-xs text-slate-700">{children}</div>
    </div>
  );
}

function KV({ data }: { data: Record<string, unknown> }) {
  const rows = Object.entries(data ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!rows.length) return <div className="text-slate-400">—</div>;
  return (
    <table className="w-full">
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}><td className="w-1/2 text-slate-500">{k}</td><td className="font-mono">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function AssetLink({ a }: { a: BeamRecord | null }) {
  if (!a) return <span className="text-slate-400">—</span>;
  return (
    <Link to={`/assets/${a.uid}`} className="text-indigo-700 hover:underline">
      {a.name}{a.serial ? ` · s/n ${a.serial}` : ""}
    </Link>
  );
}

function when(v: unknown): string {
  if (!v || typeof v !== "object") return "";
  const o = v as Record<string, unknown>;
  if (o.kind === "open") return "now";
  return String(o.nominal ?? o.bound ?? o.kind ?? "").slice(0, 10);
}

function ElementPanel({ c, onPick }: { c: BeamElementContext; onPick: (uid: string) => void }) {
  const e = c.element;
  const p = c.physics;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">{e.name}</h2>
        <Link to={`/assets/${e.uid}`} className="text-xs text-indigo-700 hover:underline">record</Link>
      </div>
      <div className="text-xs text-slate-500">{e.type} · {e.element_kind}{c.path ? ` · ${c.path.name}` : ""}</div>
      {e.capabilities && (
        <div className="mt-1 flex flex-wrap gap-1">
          {e.capabilities.map((k) => <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">{k}</span>)}
        </div>
      )}

      <Section title={`Physics${p ? ` · ${p.name}` : ""}`}>
        {p ? <KV data={{ s: p.s, ...p.physics, ...(p.geometry ?? {}) }} /> : <div className="text-slate-400">no dataset has values for it</div>}
        {p?.native?.type && (
          <div className="text-[11px] text-slate-500">native {p.native.source}: <span className="font-mono">{p.native.type} {JSON.stringify(p.native.parameters ?? {})}</span></div>
        )}
      </Section>
      {p && Object.keys(p.optics ?? {}).length > 0 && <Section title="Optics"><KV data={p.optics} /></Section>}

      <Section title="Physical asset">
        {(c.asset_bindings ?? []).filter((b) => b.status !== "confirmed" || b.relation !== "implemented_by").map((b, n) => (
          <div key={n}>
            {b.relation.replace(/_/g, " ")}: {b.asset && "uid" in b.asset ? <AssetLink a={b.asset as BeamRecord} /> : b.target.name}
            <span className={`ml-1 rounded px-1 text-[10px] ${b.status === "confirmed" ? "bg-emerald-100 text-emerald-800" : "bg-sky-100 text-sky-800"}`}>
              {b.status}{b.confidence != null ? ` ${Math.round(b.confidence * 100)}%` : ""}</span>
          </div>
        ))}
        {(c.asset_bindings ?? []).filter((b) => b.status === "confirmed" && b.relation === "implemented_by").map((b, n) => (
          <div key={`c${n}`} className="text-[11px] text-slate-500">binding: CONFIRMED · {b.authority?.replace(/_/g, " ")}
            {b.source?.matcher ? ` · ${b.source.matcher} ${b.source.matcher_version ?? ""}` : ""}</div>
        ))}
        {c.equipment.installed.length === 0 && <div className="text-slate-400">nothing confirmed installed</div>}
        {c.equipment.installed.map((i, n) => <div key={n}>installed: <AssetLink a={i.asset} /> since {when(i.valid_from)}</div>)}
        {c.equipment.history.length > 1 && (
          <div className="text-slate-500">history:
            <ul className="ml-3 list-disc">
              {c.equipment.history.map((h, n) => (
                <li key={n}><AssetLink a={h.asset} /> {when(h.valid_from)} → {when(h.valid_until) || "now"} <span className="text-slate-400">({h.status})</span></li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {c.power.length > 0 && <Section title="Power">{c.power.map((x) => <div key={x.uid}><AssetLink a={x} /></div>)}</Section>}

      <Section title="Control">
        {c.controls.connected_electronics.map((x) => <div key={x.uid}>electronics: <AssetLink a={x} /></div>)}
        {c.controls.control_devices.map((x) => <div key={x.uid}>device: <AssetLink a={x} /></div>)}
        {c.controls.iocs.map((x) => <div key={x.uid}>IOC: <AssetLink a={x} /></div>)}
        {c.controls.signals.length > 0 && (
          <table className="mt-1 w-full">
            <tbody>
              {c.controls.signals.map((s) => (
                <tr key={s.uid}><td className="text-slate-500">{s.role}</td><td className="font-mono">{s.address}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {c.controls.signals.length > 0 && <div className="text-[11px] text-slate-400">signal identities; values stay in the control system</div>}
        {!c.controls.control_devices.length && !c.controls.signals.length && <div className="text-slate-400">—</div>}
      </Section>

      {c.observables.length > 0 && (
        <Section title="Observes">
          {c.observables.map((o) => (
            <div key={o.uid}><span className="font-mono">{o.name}</span>{o.measured_by.length > 0 && <> ← <span className="font-mono">{o.measured_by.map((s) => s.address).join(", ")}</span></>}</div>
          ))}
        </Section>
      )}

      <Section title="Documentation">
        {c.documentation.length === 0 ? <div className="text-slate-400">—</div> : c.documentation.map((d) => (
          <div key={d.uid}><Link to={`/documents/${d.uid}`} className="text-indigo-700 hover:underline">{d.code} {d.title}</Link> <span className="text-slate-400">({d.for})</span></div>
        ))}
      </Section>
      <Section title="Tickets">
        {c.tickets.length === 0 ? <div className="text-slate-400">—</div> : c.tickets.map((t) => (
          <div key={t.uid}><Link to={`/tickets/${t.uid}`} className="text-indigo-700 hover:underline">{t.title}</Link> <span className="text-slate-400">{t.state}</span></div>
        ))}
      </Section>

      <Section title="Along the beam">
        <div className="flex flex-wrap gap-1">
          {c.upstream.map((u) => <button key={u.uid} type="button" onClick={() => onPick(u.uid)} className="rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50">← {u.name}</button>)}
          {c.downstream.map((d) => <button key={d.uid} type="button" onClick={() => onPick(d.uid)} className="rounded border border-slate-300 px-1.5 py-0.5 hover:bg-slate-50">{d.name}{d.via === "branches to" ? " (branch)" : ""} →</button>)}
        </div>
      </Section>
    </div>
  );
}
