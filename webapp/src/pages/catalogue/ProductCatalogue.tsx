import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { catalogueCollectionsApi, glpiMatchesApi, workspacesApi, type CatalogueDomainNode, type GlpiMatchReport } from "../../api/client";
import { problem } from "./catalogueText";

const STATUS: Record<string, string> = { catalogue: "From a collection", local: "Local", retired: "Retired" };

function Facet({ label, value, counts, onChange, names }: {
  label: string; value: string; counts: Record<string, number> | undefined; onChange: (v: string) => void;
  names?: Record<string, string>;
}) {
  const entries = Object.entries(counts ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return (
    <label className="text-xs text-slate-500">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="mt-0.5 block w-44 rounded border border-slate-300 px-2 py-1 text-sm text-slate-900">
        <option value="">All</option>
        {entries.map(([k, n]) => <option key={k} value={k === "—" ? "" : k}>{names?.[k] ?? k} ({n})</option>)}
      </select>
    </label>
  );
}

/** GLPI's devices in the current workspace: propose their catalogue models for review, and list the GLPI
 *  models nothing matches (candidates for new entries). */
export function GlpiMatches({ workspaceId }: { workspaceId?: string } = {}) {
  const [report, setReport] = useState<GlpiMatchReport | null>(null);
  const run = useMutation({ mutationFn: () => glpiMatchesApi.run(workspaceId), onSuccess: setReport });
  const unmatched = report?.unmatched;
  return (
    <section aria-label="GLPI devices" className="rounded border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">GLPI devices in {workspaceId ?? "this workspace"}</h2>
          <p className="text-xs text-slate-500">
            Proposes the catalogue model GLPI's manufacturer and model name, for each device that has none. Each
            proposal waits in the <Link to="/review" className="text-sky-800 underline">review queue</Link> until someone
            accepts or rejects it.
          </p>
        </div>
        <button type="button" disabled={run.isPending} onClick={() => run.mutate()}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
          {run.isPending ? "Matching…" : "Propose models"}
        </button>
      </div>
      {run.isError && <p className="mt-2 whitespace-pre-line text-sm text-red-600">{problem(run.error)}</p>}
      {report && (
        <div className="mt-2 space-y-1 text-sm">
          <p>
            {report.proposals} proposal{report.proposals === 1 ? "" : "s"} ({report.exact} exact, {report.near} near)
            {report.status === "unchanged" && " — the same as last time"}.
          </p>
          {report.ambiguous.length > 0 && (
            <p className="text-amber-800">
              Not proposed, two models fit equally:{" "}
              {report.ambiguous.map((a) => `${a.manufacturer} ${a.model} (${a.candidates.join(" or ")})`).join("; ")}
            </p>
          )}
          {unmatched && unmatched.length > 0 && (
            <div>
              <p className="text-slate-600">No catalogue model matches these — candidates for new entries:</p>
              <ul className="text-xs text-slate-600">
                {unmatched.map((u) => <li key={`${u.manufacturer}|${u.model}`}>{u.manufacturer} {u.model}: {u.units} unit{u.units === 1 ? "" : "s"}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** Browse the models by domain › device class › vendor, with counts; choosing a node filters the list. */
export function ModelNavigator({ nodes, domain, deviceClass, vendor, onPick }: {
  nodes: CatalogueDomainNode[]; domain: string; deviceClass: string; vendor: string;
  onPick: (pick: { domain: string; deviceClass: string; vendor: string }) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set(domain ? [domain] : []));
  const toggle = (k: string) => setOpen((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const row = (active: boolean) =>
    `flex w-full items-center justify-between gap-2 rounded px-1.5 py-0.5 text-left text-xs ${
      active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`;
  return (
    <nav aria-label="Models by domain" className="rounded border border-slate-200 bg-white p-2">
      <p className="mb-1 px-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Domains</p>
      <button type="button" onClick={() => onPick({ domain: "", deviceClass: "", vendor: "" })}
              className={row(!domain && !deviceClass && !vendor)}>
        <span>Every model</span>
      </button>
      <ul className="mt-0.5 space-y-px">
        {nodes.map((d) => {
          const isOpen = open.has(d.domain) || (domain === d.domain);
          return (
            <li key={d.domain}>
              <div className="flex items-center">
                <button type="button" aria-label={`${isOpen ? "Close" : "Open"} ${d.name}`} onClick={() => toggle(d.domain)}
                        className="w-4 shrink-0 text-xs text-slate-400">{isOpen ? "▾" : "▸"}</button>
                <button type="button" onClick={() => { onPick({ domain: d.domain, deviceClass: "", vendor: "" }); setOpen((s) => new Set(s).add(d.domain)); }}
                        className={row(domain === d.domain && !deviceClass && !vendor)}>
                  <span className="truncate">{d.name}</span><span className="tabular-nums opacity-70">{d.count}</span>
                </button>
              </div>
              {isOpen && (
                <ul className="ml-4 space-y-px">
                  {d.classes.map((c) => (
                    <li key={c.device_class}>
                      <button type="button" onClick={() => onPick({ domain: d.domain, deviceClass: c.device_class === "—" ? "" : c.device_class, vendor: "" })}
                              className={row(domain === d.domain && deviceClass === c.device_class && !vendor)}>
                        <span className="truncate">{c.device_class}</span><span className="tabular-nums opacity-70">{c.count}</span>
                      </button>
                      {domain === d.domain && deviceClass === c.device_class && (
                        <ul className="ml-3 space-y-px">
                          {c.vendors.map((v) => (
                            <li key={v.vendor}>
                              <button type="button" onClick={() => onPick({ domain: d.domain, deviceClass: c.device_class, vendor: v.vendor === "—" ? "" : v.vendor })}
                                      className={row(vendor === v.vendor)}>
                                <span className="truncate">{v.vendor}</span><span className="tabular-nums opacity-70">{v.count}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** The shared Product Models: from a collection (with its catalogue id), made here, or retired. */
export function ProductCataloguePage() {
  const [q, setQ] = useState("");
  const [deviceClass, setDeviceClass] = useState("");
  const [vendor, setVendor] = useState("");
  const [status, setStatus] = useState("");
  const [collection, setCollection] = useState("");
  const [domain, setDomain] = useState("");
  const params = { q, device_class: deviceClass, vendor, status, collection, domain };
  // The previous answer stays while the next loads: the navigator and the list do not blink at each choice.
  const found = useQuery({ queryKey: ["catalogue-models", params], queryFn: () => catalogueCollectionsApi.models(params),
                           placeholderData: (previous) => previous });
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });

  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Product catalogue</h1>
          <p className="mt-1 text-sm text-slate-500">
            The Product Models every workspace can point at. A model from a collection carries its catalogue id;
            a local one was made here, and can be proposed for a collection.
          </p>
        </div>
        {(me.data?.is_admin || me.data?.catalogue_maintainer) && (
          <Link to="/admin/catalogue" className="text-sm font-medium text-sky-800 underline">Collections and updates</Link>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded border border-slate-200 bg-white p-3">
        <label className="text-xs text-slate-500">
          Search
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, code, vendor, catalogue id"
                 className="mt-0.5 block w-64 rounded border border-slate-300 px-2 py-1 text-sm text-slate-900" />
        </label>
        <Facet label="Device class" value={deviceClass} onChange={setDeviceClass} counts={found.data?.facets.device_class} />
        <Facet label="Vendor" value={vendor} onChange={setVendor} counts={found.data?.facets.vendor} />
        <Facet label="Source" value={status} onChange={setStatus} counts={found.data?.facets.status} names={STATUS} />
        <Facet label="Collection" value={collection} onChange={setCollection} counts={found.data?.facets.collection} />
        <Facet label="Domain" value={domain} onChange={setDomain} counts={found.data?.facets.domain}
               names={found.data?.domain_names} />
      </div>

      {found.isError && <p className="whitespace-pre-line text-sm text-red-600">{problem(found.error)}</p>}
      {found.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {found.data && (
        <div className="grid gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
          <div className="md:sticky md:top-2 md:self-start">
            <ModelNavigator nodes={found.data.navigator ?? []} domain={domain} deviceClass={deviceClass} vendor={vendor}
                            onPick={(p) => { setDomain(p.domain); setDeviceClass(p.deviceClass); setVendor(p.vendor); }} />
          </div>
          <div className="min-w-0 space-y-2">
          <p className="text-xs text-slate-500">{found.data.total} model{found.data.total === 1 ? "" : "s"}</p>
          <div className="overflow-x-auto">
          <table className="w-full rounded border border-slate-200 bg-white text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2">Model</th><th className="px-3 py-2">Vendor</th>
                <th className="px-3 py-2">Model code</th><th className="px-3 py-2">Device class</th>
                <th className="px-3 py-2">Source</th><th className="px-3 py-2 text-right">Units</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {found.data.models.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-3 text-slate-500">No model matches.</td></tr>
              )}
              {found.data.models.map((m) => (
                <tr key={m.uid}>
                  <td className="px-3 py-2">
                    <Link to={`/catalogue/models/${m.uid}`} className="font-medium text-sky-800 hover:underline">{m.name}</Link>
                    {m.review && <span className="ml-1 text-xs text-amber-700" title="Waiting for review">● review</span>}
                    <span className="block font-mono text-xs text-slate-400">{m.key}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-700">{m.vendor ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{m.model_code ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-700">{m.device_class ?? "—"}</td>
                  <td className="px-3 py-2">
                    {m.catalogue_id
                      ? <><span className="font-mono text-xs">{m.catalogue_id}</span>
                          <span className="block text-xs text-slate-500">{m.collection} {m.version}
                            {m.status === "retired" && <span className="ml-1 text-red-700">retired</span>}</span></>
                      : <span className="text-xs text-slate-500">{m.status === "retired" ? "retired" : "local"}</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{m.units}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          </div>
        </div>
      )}
    </div>
  );
}
