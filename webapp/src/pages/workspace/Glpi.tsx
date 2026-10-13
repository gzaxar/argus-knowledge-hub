import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  glpiApi,
  workspacesApi,
  type GlpiConnection,
  type GlpiConnectionInput,
  type GlpiEntityMapEntry,
  type GlpiPlan,
  type GlpiSchemaProposal,
} from "../../api/client";

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
  }
  return "It could not be done.";
}

const EMPTY: GlpiConnectionInput = {
  name: "GLPI", base_url: "", user_token: "", app_token: "", verify_tls: true, key_prefix: "GLPI",
  documents: true, tickets: true,
};

/** GLPI connections: credentials kept encrypted, the installation discovered, its entities mapped to
 *  workspaces, its own schema reviewed, an import previewed before it runs, and the records GLPI stopped
 *  listing decided on by a person (docs/glpi.md). */
export function GlpiPage() {
  const { workspaceId = "" } = useParams();
  const connections = useQuery({ queryKey: ["glpi", workspaceId], queryFn: () => glpiApi.list(workspaceId) });
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const current = (connections.data ?? []).find((c) => c.uid === open) ?? null;

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">GLPI</h1>
        <p className="mt-1 text-sm text-slate-500">
          Inventory, licences, contracts, tickets, problems, changes and documents from GLPI 10 or 11, read
          through its REST API. ARGUS keeps its own schema: GLPI's custom types and fields come in only once
          you approve them, local edits are kept by the authority policy you choose, and nothing GLPI stops
          listing is retired without a decision. Needs the IT package.{" "}
          <Link to="/help/glpi" className="underline">How it works</Link>
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(connections.data ?? []).map((c) => (
          <button key={c.uid} type="button" onClick={() => { setOpen(c.uid); setCreating(false); }}
                  className={`rounded border px-3 py-1.5 text-sm ${open === c.uid ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300 bg-white"}`}>
            {c.name} <span className="opacity-60">{c.base_url.replace(/^https?:\/\//, "")}</span>
          </button>
        ))}
        <button type="button" onClick={() => { setCreating(true); setOpen(null); }}
                className="rounded border border-dashed border-slate-400 px-3 py-1.5 text-sm text-slate-600">
          + Connect a GLPI
        </button>
      </div>

      {creating && <ConnectionForm workspaceId={workspaceId} onDone={(uid) => { setCreating(false); setOpen(uid); }} />}
      {current && <Connection workspaceId={workspaceId} connection={current} />}
    </div>
  );
}

function ConnectionForm({ workspaceId, onDone, existing }: { workspaceId: string; onDone: (uid: string) => void;
                                                            existing?: GlpiConnection }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<GlpiConnectionInput>(existing ? {
    name: existing.name, base_url: existing.base_url, verify_tls: existing.verify_tls, key_prefix: existing.key_prefix,
    documents: existing.documents, tickets: existing.tickets, user_token: "", app_token: "" } : EMPTY);
  const save = useMutation({
    mutationFn: () => existing
      ? glpiApi.update(workspaceId, existing.uid, { ...form, user_token: form.user_token || undefined })
      : glpiApi.create(workspaceId, form),
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ["glpi", workspaceId] }); onDone(c.uid); },
  });
  const set = (k: keyof GlpiConnectionInput, v: string | boolean) => setForm({ ...form, [k]: v });
  return (
    <form className="space-y-3 rounded border border-slate-200 bg-white p-4 text-sm"
          onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="grid grid-cols-2 gap-3">
        <label>Name<input className="mt-1 w-full rounded border px-2 py-1" value={form.name}
                          onChange={(e) => set("name", e.target.value)} required /></label>
        <label>GLPI address<input className="mt-1 w-full rounded border px-2 py-1" value={form.base_url}
                                 placeholder="https://glpi.example.org" onChange={(e) => set("base_url", e.target.value)} required /></label>
        <label>User token<input type="password" className="mt-1 w-full rounded border px-2 py-1" value={form.user_token}
                                autoComplete="off" onChange={(e) => set("user_token", e.target.value)}
                                placeholder={existing?.has_credentials ? "kept unless you type a new one" : ""}
                                required={!existing} /></label>
        <label>Application token (if GLPI asks for one)<input type="password" autoComplete="off"
                                className="mt-1 w-full rounded border px-2 py-1" value={form.app_token}
                                onChange={(e) => set("app_token", e.target.value)} /></label>
        <label>Key prefix<input className="mt-1 w-full rounded border px-2 py-1 font-mono" value={form.key_prefix}
                                onChange={(e) => set("key_prefix", e.target.value)} /></label>
        <div className="space-y-1 pt-5">
          <label className="flex gap-2"><input type="checkbox" checked={form.verify_tls}
                                               onChange={(e) => set("verify_tls", e.target.checked)} /> Check GLPI's certificate</label>
          <label className="flex gap-2"><input type="checkbox" checked={form.tickets}
                                               onChange={(e) => set("tickets", e.target.checked)} /> Tickets, problems and changes</label>
          <label className="flex gap-2"><input type="checkbox" checked={form.documents}
                                               onChange={(e) => set("documents", e.target.checked)} /> Documents as attachments</label>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        The tokens are stored encrypted and never shown again. Give ARGUS a GLPI user whose profile can only
        read what is imported, in the entities imported, and an API client limited to ARGUS's address.
      </p>
      {save.isError && <p className="text-red-600">{problem(save.error)}</p>}
      <button className="rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50" disabled={save.isPending}>
        {save.isPending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}

function Connection({ workspaceId, connection: c }: { workspaceId: string; connection: GlpiConnection }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["glpi", workspaceId] });
  const [editing, setEditing] = useState(false);
  const [plan, setPlan] = useState<GlpiPlan | null>(null);
  const [done, setDone] = useState<GlpiPlan | null>(null);
  const discover = useMutation({ mutationFn: () => glpiApi.discover(workspaceId, c.uid), onSuccess: refresh });
  const preview = useMutation({ mutationFn: () => glpiApi.preview(workspaceId, c.uid),
                                onSuccess: (p) => { setPlan(p); setDone(null); refresh(); } });
  const run = useMutation({ mutationFn: () => glpiApi.run(workspaceId, c.uid, plan?.digest),
                            onSuccess: (p) => { setDone(p); setPlan(null); refresh(); } });
  const authority = useMutation({
    mutationFn: (a: { records: string; tickets: string }) => glpiApi.setAuthority(workspaceId, c.uid, a.records, a.tickets),
    onSuccess: refresh,
  });
  const full = useQuery({ queryKey: ["glpi", workspaceId, c.uid], queryFn: () => glpiApi.get(workspaceId, c.uid) });
  const d = c.discovery;

  return (
    <div className="space-y-5">
      <section className="rounded border border-slate-200 bg-white p-4 text-sm">
        <div className="flex items-start justify-between">
          <div>
            <p className="font-medium text-slate-900">{c.name}</p>
            <p className="text-slate-500">{c.base_url} · keys {c.key_prefix}-… ·
              {c.has_credentials ? " credentials stored" : " no credentials"}</p>
          </div>
          <button type="button" className="text-xs underline" onClick={() => setEditing((v) => !v)}>
            {editing ? "Close" : "Edit"}</button>
        </div>
        {editing && <div className="mt-3"><ConnectionForm workspaceId={workspaceId} existing={c}
                                                         onDone={() => setEditing(false)} /></div>}
        <div className="mt-3 flex gap-2">
          <button type="button" className="rounded border px-3 py-1" onClick={() => discover.mutate()} disabled={discover.isPending}>
            {discover.isPending ? "Reading GLPI…" : d ? "Discover again" : "Discover"}</button>
        </div>
        {discover.isError && <p className="mt-2 text-red-600">{problem(discover.error)}</p>}
      </section>

      {d && (
        <section className="rounded border border-slate-200 bg-white p-4 text-sm">
          <h2 className="font-semibold text-slate-900">What this GLPI is</h2>
          <p className="mt-1 text-slate-600">
            GLPI {d.version ?? "?"} · REST API {d.api.legacy ? "available" : "not available"}
            {d.api.high_level ? ` · high-level API ${d.api.high_level} (detected, not used)` : ""}
            {d.plugins.length > 0 && ` · plugins: ${d.plugins.map((p) => `${p.directory} ${p.version}`).join(", ")}`}
          </p>
          <table className="mt-3 w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th>Item type</th><th>Records</th><th>In ARGUS</th></tr></thead>
            <tbody>
              {Object.entries(d.itemtypes).map(([it, v]) => (
                <tr key={it} className="border-t border-slate-100">
                  <td className="py-0.5 font-mono">{it}</td><td>{v.count}</td>
                  <td>{v.status === "mapped" ? v.maps_to : v.status === "unavailable" ? <span className="text-amber-700">not readable: {v.why}</span> : v.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <EntityMap workspaceId={workspaceId} connection={c} />
          <div className="mt-4">
            <h3 className="font-medium text-slate-900">Who wins when a field was edited here and GLPI changes it</h3>
            <div className="mt-1 flex gap-4">
              {(["records", "tickets"] as const).map((k) => (
                <label key={k} className="text-slate-600">{k === "records" ? "Records" : "Tickets"}{" "}
                  <select value={c.authority[k]} className="rounded border px-2 py-0.5"
                          onChange={(e) => authority.mutate({ ...c.authority, [k]: e.target.value })}>
                    <option value="argus">ARGUS: keep the local value, report the difference</option>
                    <option value="glpi">GLPI: apply GLPI's value{k === "records" ? " (a confirmed local edit goes to review)" : ""}</option>
                  </select>
                </label>
              ))}
            </div>
          </div>
        </section>
      )}

      {full.data?.schema?.proposal && (
        <SchemaReview workspaceId={workspaceId} uid={c.uid} proposal={full.data.schema.proposal}
                      status={full.data.schema.status ?? "none"} />
      )}

      {d && (
        <section className="rounded border border-slate-200 bg-white p-4 text-sm">
          <h2 className="font-semibold text-slate-900">Import</h2>
          <div className="mt-2 flex gap-2">
            <button type="button" className="rounded border px-3 py-1" onClick={() => preview.mutate()} disabled={preview.isPending}>
              {preview.isPending ? "Working it out…" : "Preview"}</button>
            {plan && (
              <button type="button" className="rounded bg-slate-900 px-3 py-1 text-white" onClick={() => run.mutate()}
                      disabled={run.isPending}>{run.isPending ? "Importing…" : "Import this"}</button>
            )}
          </div>
          {preview.isError && <p className="mt-2 text-red-600">{problem(preview.error)}</p>}
          {run.isError && <p className="mt-2 text-red-600">{problem(run.error)}</p>}
          {(plan ?? done) && <PlanView plan={(plan ?? done)!} done={!!done} />}
        </section>
      )}

      <Candidates workspaceId={workspaceId} uid={c.uid} />
    </div>
  );
}

function EntityMap({ workspaceId, connection: c }: { workspaceId: string; connection: GlpiConnection }) {
  const qc = useQueryClient();
  const workspaces = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const [rows, setRows] = useState<GlpiEntityMapEntry[]>(c.entity_map);
  const save = useMutation({ mutationFn: () => glpiApi.setEntityMap(workspaceId, c.uid, rows),
                             onSuccess: () => qc.invalidateQueries({ queryKey: ["glpi", workspaceId] }) });
  const entities = c.discovery?.entities ?? [];
  return (
    <div className="mt-4">
      <h3 className="font-medium text-slate-900">Entities → workspaces</h3>
      <p className="text-xs text-slate-500">An entity not sent anywhere is not imported. “With what is under it”
        sends its sub-entities too, unless one of them is mapped itself.</p>
      <table className="mt-1 w-full text-xs">
        <tbody>
          {entities.map((e) => {
            const row = rows.find((r) => String(r.entity_id) === String(e.id));
            return (
              <tr key={e.id} className="border-t border-slate-100">
                <td className="py-1">{e.completename} <span className="text-slate-400">({e.records} records)</span></td>
                <td>
                  <select value={row?.workspace_id ?? ""} className="rounded border px-1"
                          onChange={(ev) => setRows([...rows.filter((r) => String(r.entity_id) !== String(e.id)),
                            ...(ev.target.value ? [{ entity_id: e.id, entity: e.completename, workspace_id: ev.target.value,
                                                     recursive: row?.recursive ?? true }] : [])])}>
                    <option value="">—</option>
                    {(workspaces.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                </td>
                <td>
                  {row && (
                    <label className="flex gap-1"><input type="checkbox" checked={row.recursive}
                      onChange={(ev) => setRows(rows.map((r) => r === row ? { ...r, recursive: ev.target.checked } : r))} />
                      with what is under it</label>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <button type="button" className="mt-2 rounded border px-3 py-1" onClick={() => save.mutate()} disabled={save.isPending}>
        Save the mapping</button>
      {save.isError && <span className="ml-2 text-red-600">{problem(save.error)}</span>}
    </div>
  );
}

function SchemaReview({ workspaceId, uid, proposal, status }: { workspaceId: string; uid: string;
                                                               proposal: GlpiSchemaProposal; status: string }) {
  const qc = useQueryClient();
  const approve = useMutation({ mutationFn: () => glpiApi.approveSchema(workspaceId, uid, proposal.digest),
                                onSuccess: () => qc.invalidateQueries({ queryKey: ["glpi", workspaceId] }) });
  if (!proposal.types.length && !proposal.extensions.length) return null;
  const tone: Record<string, string> = { create: "text-emerald-700", reuse: "text-slate-600",
                                         unsupported: "text-amber-700", conflict: "text-red-700" };
  return (
    <section className="rounded border border-slate-200 bg-white p-4 text-sm">
      <h2 className="font-semibold text-slate-900">GLPI's own schema</h2>
      <p className="mt-1 text-slate-500">
        {status === "approved" ? "Approved: the import uses this mapping." :
          "Awaiting review. Until you approve it, GLPI's custom types are not imported and their fields are kept as GLPI gave them; nothing in ARGUS's schema changes."}
      </p>
      {proposal.types.map((t) => (
        <div key={t.source} className="mt-3">
          <p><span className="font-medium">{t.label}</span> <span className="font-mono text-xs text-slate-400">{t.source}</span>
            {" → "}<span className={tone[t.action]}>{t.action === "create" ? `new type “${t.argus_type}” under ${t.parent}` : `the existing type “${t.argus_type}”`}</span></p>
          <ul className="ml-4 text-xs">
            {t.fields.map((f) => (
              <li key={f.source} className={tone[f.action]}>
                {f.label} ({f.glpi_type.split("\\").pop()}) → {f.action === "unsupported" || f.action === "conflict"
                  ? `kept as GLPI gives it: ${f.note}` : `${f.action === "create" ? "new field" : "field"} ${f.argus_key} (${f.kind})`}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {proposal.extensions.length > 0 && (
        <div className="mt-3">
          <p className="font-medium">Fields added to standard items (fields plugin)</p>
          <ul className="ml-4 text-xs">
            {proposal.extensions.map((e) => (
              <li key={`${e.on_itemtype}:${e.source}`} className={tone[e.action]}>
                {e.on_itemtype} · {e.label} → {e.action === "unsupported" || e.action === "conflict"
                  ? `kept as GLPI gives it: ${e.note}` : `${e.argus_key} on ${e.argus_type}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {status !== "approved" && (
        <button type="button" className="mt-3 rounded bg-slate-900 px-3 py-1 text-white" onClick={() => approve.mutate()}
                disabled={approve.isPending}>Approve: {proposal.changes} change(s) to this workspace's schema</button>
      )}
      {approve.isError && <p className="mt-2 text-red-600">{problem(approve.error)}</p>}
    </section>
  );
}

function PlanView({ plan, done }: { plan: GlpiPlan; done: boolean }) {
  return (
    <div className="mt-3 space-y-3">
      <p className="text-slate-600">
        {done ? "Imported." : "This would happen."} {plan.outside_entity_map > 0 && `${plan.outside_entity_map} items are in entities the mapping sends nowhere. `}
        {plan.awaiting_schema_review.length > 0 && `${plan.awaiting_schema_review.map((a) => `${a.records} ${a.itemtype.split("\\").pop()}`).join(", ")} wait for the schema review.`}
      </p>
      {Object.entries(plan.workspaces).map(([ws, w]) => (
        <div key={ws} className="rounded border border-slate-100 p-3">
          <p className="font-medium text-slate-900">{ws}</p>
          {w.missing_packages.length > 0 && (
            <p className="text-red-600">Missing: {w.missing_packages.join(", ")} — install the IT package first.</p>
          )}
          <p className="text-slate-600">
            {w.creates.length} new · {w.updates.length} updated · {w.unchanged} unchanged · {w.locations} with a position ·
            tickets {w.tickets.creates} new, {w.tickets.updates} updated · {w.documents} documents
          </p>
          {w.conflicts.length > 0 && (
            <details className="mt-1"><summary className="cursor-pointer text-amber-700">{w.conflicts.length} field(s) edited here that GLPI changed too</summary>
              <ul className="ml-4 text-xs">{w.conflicts.map((x) => (
                <li key={`${x.ref}:${x.field}`}>{x.key} · {x.field}: here “{String(x.argus)}”, GLPI “{String(x.glpi)}” — {x.outcome}</li>))}</ul>
            </details>
          )}
          {w.retirement_candidates.length > 0 && (
            <p className="mt-1 text-amber-700">{w.retirement_candidates.length} record(s) GLPI no longer lists: kept, for you to decide below.</p>
          )}
          {w.updates.length > 0 && (
            <details className="mt-1"><summary className="cursor-pointer text-slate-600">What changes</summary>
              <ul className="ml-4 text-xs">{w.updates.map((u) => <li key={u.ref}>{u.key}: {u.fields.join(", ")}</li>)}</ul>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

function Candidates({ workspaceId, uid }: { workspaceId: string; uid: string }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["glpi-candidates", workspaceId, uid], queryFn: () => glpiApi.candidates(workspaceId, uid) });
  const decide = useMutation({
    mutationFn: (x: { ref: string; decision: "retire" | "keep" }) => glpiApi.decide(workspaceId, uid, x.ref, x.decision),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["glpi-candidates", workspaceId, uid] }),
  });
  if (!list.data?.length) return null;
  return (
    <section className="rounded border border-amber-200 bg-amber-50 p-4 text-sm">
      <h2 className="font-semibold text-slate-900">Records GLPI no longer lists</h2>
      <p className="text-slate-600">Nothing was retired. Retire a record (its history stays), or keep it as an
        ARGUS record that GLPI no longer states.</p>
      <ul className="mt-2 space-y-1">
        {list.data.map((x) => (
          <li key={x.ref} className="flex items-center gap-2">
            <Link to={`/assets/${x.uid}`} className="underline">{x.key}</Link> {x.name}
            <span className="text-xs text-slate-500">({x.reason})</span>
            <button type="button" className="ml-auto rounded border px-2 py-0.5" onClick={() => decide.mutate({ ref: x.ref, decision: "keep" })}>Keep</button>
            <button type="button" className="rounded border border-red-300 px-2 py-0.5 text-red-700" onClick={() => decide.mutate({ ref: x.ref, decision: "retire" })}>Retire</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
