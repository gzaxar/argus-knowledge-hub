import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { problemText, typeMigrationsApi } from "../../../api/client";
import type { AttributeRule, MigrationFields, MigrationPreview, TypeMigrationView } from "../../../api/client";
import { ActionButton, KV, Section, when } from "../portability/shared";
import { Resolution, statusBadge } from "./TypeMigrations";

const ACTIONS: { id: AttributeRule["action"]; label: string }[] = [
  { id: "copy", label: "Copy to" }, { id: "transform", label: "Transform to" },
  { id: "provenance", label: "Keep in provenance" }, { id: "review", label: "Hold for review" },
];
const STATUS_ORDER = ["ready", "review", "blocked", "hidden", "already", "applied"];
const STATUS_TEXT: Record<string, string> = {
  ready: "✓ ready", review: "◐ review", blocked: "✕ blocked", hidden: "◌ not visible to you", already: "= already there",
  applied: "✓ applied",
};

/** One migration: map (3), preview (4), apply (5), verify (6) — and its audit log. */
export function TypeMigrationDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ["type-migration", id], queryFn: () => typeMigrationsApi.get(id) });
  const fields = useQuery({ queryKey: ["type-migration-fields", id], queryFn: () => typeMigrationsApi.fields(id) });
  const [preview, setPreview] = useState<MigrationPreview | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["type-migration", id] }); qc.invalidateQueries({ queryKey: ["type-migrations"] }); };
  if (m.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (m.isError || !m.data) return <p className="text-sm text-rose-700">{problemText(m.error)}</p>;
  const plan = m.data;
  const closed = plan.status === "verified" || plan.status === "reverted";
  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <Link to="/admin/type-migrations" className="text-sm text-sky-800 hover:underline">← Type migrations</Link>
        <h1 className="mt-1 flex flex-wrap items-center gap-2 text-2xl font-semibold text-slate-900">
          {plan.source.name} → {plan.target.type} {statusBadge(plan.status)}
        </h1>
        <KV rows={[
          ["Source", `${plan.source.name} (${plan.source.workspace_id}${plan.source.is_global ? ", shared" : ""})` +
            (plan.include_descendants ? `, with ${plan.source.family.length - 1} type(s) below it` : "")],
          ["Target", `${plan.target.type} — package ${plan.target.package_id} ${plan.target.version}`],
          ["Owning workspaces", plan.workspaces.join(", ")],
          ["Reason", plan.reason ?? ""],
          ["Created", `${when(plan.created_at)} by ${plan.created_by}`],
        ]} />
      </div>
      {fields.data && !closed && <Mapping plan={plan} fields={fields.data} onSaved={() => { refresh(); setPreview(null); }} />}
      <PreviewStep plan={plan} preview={preview} setPreview={setPreview} onApplied={refresh} closed={closed} />
      <VerifyStep plan={plan} onDone={refresh} />
      <Section title="Log">
        <ol className="space-y-1 text-xs text-slate-600">
          {(plan.log ?? []).slice().reverse().map((e, i) => (
            <li key={i}><span className="tabular-nums text-slate-400">{when(e.at)}</span> · <b>{e.event.replace(/_/g, " ")}</b> · {e.actor}
              {Object.entries(e).filter(([k]) => !["at", "actor", "event"].includes(k)).map(([k, v]) =>
                <span key={k} className="ml-1 text-slate-500">{k}: {typeof v === "object" ? JSON.stringify(v).slice(0, 120) : String(v)}</span>)}
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}

function Mapping({ plan, fields, onSaved }: { plan: TypeMigrationView; fields: MigrationFields; onSaved: () => void }) {
  const [rules, setRules] = useState<Record<string, AttributeRule>>(plan.mapping.attributes ?? {});
  const [defaults, setDefaults] = useState<Record<string, unknown>>(plan.mapping.defaults ?? {});
  const [states, setStates] = useState<Record<string, string | null>>(plan.mapping.states ?? {});
  useEffect(() => { setRules(plan.mapping.attributes ?? {}); setDefaults(plan.mapping.defaults ?? {}); setStates(plan.mapping.states ?? {}); }, [plan]);
  const save = useMutation({
    mutationFn: () => typeMigrationsApi.change(plan.id, { attributes: rules, defaults, states }),
    onSuccess: onSaved,
  });
  const target = Object.fromEntries(fields.target.map((t) => [t.key, t]));
  const set = (key: string, r: Partial<AttributeRule>) => setRules({ ...rules, [key]: { ...(rules[key] ?? { action: "provenance" }), ...r } });
  const covered = new Set(Object.values(rules).filter((r) => r.action === "copy" || r.action === "transform").map((r) => r.to));
  const required = fields.target.filter((t) => t.required && !covered.has(t.key));
  return (
    <Section title="3 · Map the data" right={<ActionButton label="Save the mapping" busy={save.isPending} onClick={() => save.mutate()} />}>
      {save.isError && <p className="mb-2 text-sm text-rose-700">{problemText(save.error)}</p>}
      <p className="mb-2 text-xs text-slate-500">
        Each field of the old type: copied to a field of the target (choices mapped value by value), transformed,
        kept in provenance (removed from the record, kept with this migration), or held for review (a record with a
        value there is left until decided). The record's classification is never changed.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[42rem] table-fixed text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr><th className="w-48 py-1">Old field</th><th className="w-44 py-1">Decision</th><th className="w-48 py-1">Target field</th><th className="py-1">Values</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {fields.source.map((f) => {
              const r = rules[f.key] ?? { action: "provenance" };
              const to = r.to ? target[r.to] : undefined;
              return (
                <tr key={f.key}>
                  <td className="py-1.5"><span className="font-medium">{f.name}</span> <span className="font-mono text-xs text-slate-500">{f.key}</span>
                    <div className="text-xs text-slate-500">{f.type} · {r.records_with_value ?? f.values.length} with a value</div></td>
                  <td className="py-1.5">
                    <select aria-label={`Decision for ${f.name}`} value={r.action} onChange={(e) => set(f.key, { action: e.target.value as AttributeRule["action"] })}
                            className="w-full rounded border border-slate-300 px-1 py-1 text-sm">
                      {ACTIONS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                    </select>
                  </td>
                  <td className="py-1.5">
                    {(r.action === "copy" || r.action === "transform") && (
                      <select aria-label={`Target field for ${f.name}`} value={r.to ?? ""} onChange={(e) => set(f.key, { to: e.target.value || null })}
                              className="w-full rounded border border-slate-300 px-1 py-1 text-sm">
                        <option value="">Choose…</option>
                        {fields.target.map((t) => <option key={t.key} value={t.key}>{t.name}{t.required ? " *" : ""} ({t.type})</option>)}
                      </select>
                    )}
                    {r.action === "transform" && (
                      <select aria-label={`Convert ${f.name} to`} value={r.cast ?? ""} onChange={(e) => set(f.key, { cast: e.target.value || null })}
                              className="mt-1 w-full rounded border border-slate-300 px-1 py-1 text-xs">
                        <option value="">No conversion</option>
                        {["string", "integer", "float", "boolean"].map((c) => <option key={c} value={c}>as {c}</option>)}
                      </select>
                    )}
                  </td>
                  <td className="py-1.5">
                    {(r.action === "copy" || r.action === "transform") && to?.options.length ? (
                      <div className="space-y-1">
                        {f.values.map((v) => (
                          <label key={v} className="flex items-center gap-2 text-xs">
                            <span className="w-28 truncate font-mono" title={v}>{v}</span>→
                            <select value={r.values?.[v] ?? ""} onChange={(e) => set(f.key, { values: { ...(r.values ?? {}), [v]: e.target.value || null } })}
                                    className="flex-1 rounded border border-slate-300 px-1 py-0.5" aria-label={`${f.name} value ${v} becomes`}>
                              <option value="">— unmapped —</option>
                              {to.options.map((o) => <option key={o} value={o}>{o}</option>)}
                            </select>
                          </label>
                        ))}
                      </div>
                    ) : <span className="text-xs text-slate-500">{f.values.slice(0, 5).join(", ")}{f.values.length > 5 ? "…" : ""}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {required.length > 0 && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-sm">
          <p className="font-medium text-amber-900">Required by the target, filled by no field: give a value for the records without one</p>
          {required.map((t) => (
            <label key={t.key} className="mt-1 flex items-center gap-2">
              <span className="w-48">{t.name}</span>
              {t.options.length ? (
                <select value={String(defaults[t.key] ?? "")} onChange={(e) => setDefaults({ ...defaults, [t.key]: e.target.value || null })}
                        className="rounded border border-slate-300 px-1 py-0.5" aria-label={`Default for ${t.name}`}>
                  <option value="">—</option>{t.options.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : <input value={String(defaults[t.key] ?? "")} onChange={(e) => setDefaults({ ...defaults, [t.key]: e.target.value || null })}
                         className="rounded border border-slate-300 px-1 py-0.5" aria-label={`Default for ${t.name}`} />}
            </label>
          ))}
        </div>
      )}
      {plan.kind === "tickets" && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase text-slate-500">Workflow states</p>
          {fields.source_states.map((s) => (
            <label key={s} className="mt-1 flex items-center gap-2 text-sm">
              <span className="w-40 font-mono">{s}</span>→
              <select value={states[s] ?? ""} onChange={(e) => setStates({ ...states, [s]: e.target.value || null })}
                      className="rounded border border-slate-300 px-1 py-0.5" aria-label={`State ${s} becomes`}>
                <option value="">— unmapped —</option>
                {fields.target_states.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}
              </select>
            </label>
          ))}
        </div>
      )}
    </Section>
  );
}

function PreviewStep({ plan, preview, setPreview, onApplied, closed }: {
  plan: TypeMigrationView; preview: MigrationPreview | null; setPreview: (p: MigrationPreview | null) => void;
  onApplied: () => void; closed: boolean;
}) {
  const qc = useQueryClient();
  const [batch, setBatch] = useState(100);
  const run = useMutation({ mutationFn: () => typeMigrationsApi.preview(plan.id), onSuccess: setPreview });
  const apply = useMutation({
    mutationFn: () => typeMigrationsApi.apply(plan.id, preview!.token, batch),
    onSuccess: () => { setPreview(null); onApplied(); },
  });
  const leave = useMutation({
    mutationFn: (v: { uid: string; decision: "migrate" | "skip" }) => typeMigrationsApi.change(plan.id, { records: { [v.uid]: v.decision } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["type-migration", plan.id] }); run.mutate(); },
  });
  const ready = preview?.total.ready ?? 0;
  return (
    <Section title="4 · Preview — nothing is written" right={!closed && <ActionButton label="Preview" busy={run.isPending} onClick={() => run.mutate()} />}>
      {run.isError && <p className="text-sm text-rose-700">{problemText(run.error)}</p>}
      {!preview ? <p className="text-sm text-slate-500">Run the preview after each change to the mapping.</p> : (
        <div className="space-y-3 text-sm">
          <Resolution rows={preview.targets} />
          <table className="w-full table-fixed text-sm">
            <thead className="text-left text-xs uppercase text-slate-500"><tr><th className="py-1">Owning workspace</th>
              {STATUS_ORDER.map((s) => <th key={s} className="py-1">{s}</th>)}</tr></thead>
            <tbody>
              {Object.entries(preview.counts).map(([ws, c]) => (
                <tr key={ws}><td className="truncate py-1">{ws}</td>{STATUS_ORDER.map((s) => <td key={s} className="tabular-nums">{c[s] ?? 0}</td>)}</tr>
              ))}
            </tbody>
          </table>
          {Object.keys(preview.unmapped_values).length > 0 && (
            <div className="rounded border border-amber-200 bg-amber-50 p-2">
              <p className="font-medium text-amber-900">Values without a decision</p>
              {Object.entries(preview.unmapped_values).map(([k, vs]) => <p key={k} className="text-xs"><b>{k}</b>: {vs.join(", ")}</p>)}
            </div>
          )}
          {!preview.deprecation.possible && (
            <p className="text-xs text-slate-500">After this migration the old type stays (not deprecated): {preview.deprecation.blocking.map((b) => `${b.what}: ${b.detail}`).join("; ")}</p>
          )}
          <details open>
            <summary className="cursor-pointer text-sm font-medium">Records ({preview.records_listed} of {preview.records_total} listed)</summary>
            <ul className="mt-2 divide-y divide-slate-100">
              {preview.records.map((r) => (
                <li key={r.uid} className="py-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`w-36 shrink-0 text-xs ${r.status === "blocked" ? "text-rose-700" : r.status === "ready" ? "text-green-800" : "text-amber-900"}`}>{STATUS_TEXT[r.status] ?? r.status}</span>
                    <span className="font-medium">{r.name}</span>
                    {r.key && <span className="font-mono text-xs text-slate-500">{r.key}</span>}
                    <span className="text-xs text-slate-500">{r.workspace_id}</span>
                    {!closed && (r.status === "ready" || r.reasons.includes("left out by an individual decision")) && (
                      <button type="button" className="ml-auto text-xs text-sky-800 underline"
                              onClick={() => leave.mutate({ uid: r.uid, decision: r.status === "ready" ? "skip" : "migrate" })}>
                        {r.status === "ready" ? "Leave out" : "Include again"}
                      </button>
                    )}
                  </div>
                  {r.reasons.length > 0 && <ul className="ml-36 list-disc pl-5 text-xs text-slate-700">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
                  {r.changes.length > 0 && (
                    <p className="ml-36 text-xs text-slate-500">
                      {r.changes.map((c) => `${c.field}: ${JSON.stringify(c.before)} → ${c.provenance ? "(provenance)" : JSON.stringify(c.after)}`).join(" · ")}
                      {r.state && r.state.before !== r.state.after && ` · state ${r.state.before} → ${r.state.after}`}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </details>
          {!closed && (
            <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
              <label className="text-xs text-slate-600">Batch size <input type="number" min={1} max={1000} value={batch}
                onChange={(e) => setBatch(Number(e.target.value) || 100)} className="w-20 rounded border border-slate-300 px-1 py-0.5" /></label>
              <ActionButton label={`5 · Apply to ${ready} record${ready === 1 ? "" : "s"}`} busy={apply.isPending} disabled={ready === 0}
                            confirm={`Move ${ready} record(s) to ${plan.target.type}, in batches of ${batch}?`} onClick={() => apply.mutate()} />
              <span className="text-xs text-slate-500">Only records shown as ready are moved. Applying again later does only what is left.</span>
            </div>
          )}
          {apply.isError && <p className="text-sm text-rose-700">{problemText(apply.error)}</p>}
        </div>
      )}
    </Section>
  );
}

function VerifyStep({ plan, onDone }: { plan: TypeMigrationView; onDone: () => void }) {
  const [deprecate, setDeprecate] = useState(false);
  const verify = useMutation({ mutationFn: () => typeMigrationsApi.verify(plan.id, deprecate), onSuccess: onDone });
  const revert = useMutation({ mutationFn: () => typeMigrationsApi.revert(plan.id), onSuccess: onDone });
  const failed = useQuery({ queryKey: ["type-migration-failed", plan.id, plan.updated_at], queryFn: () => typeMigrationsApi.items(plan.id, "failed") });
  const report = verify.data ?? plan.verification;
  if (plan.status === "draft") return null;
  return (
    <Section title="6 · Verify">
      {(failed.data ?? []).length > 0 && (
        <div className="mb-2 rounded border border-rose-200 bg-rose-50 p-2 text-sm">
          <p className="font-medium text-rose-800">{failed.data!.length} record(s) failed — preview and apply again to retry them</p>
          <ul className="list-disc pl-5 text-xs">{failed.data!.slice(0, 20).map((f) => <li key={f.record_uid}>{f.record_uid} ({f.workspace_id}): {f.error}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={deprecate} onChange={(e) => setDeprecate(e.target.checked)} />
          Deprecate the old type if nothing depends on it any more (it is never deleted)</label>
        <ActionButton label="Verify" busy={verify.isPending} onClick={() => verify.mutate()} />
        {plan.status !== "reverted" && (
          <ActionButton label="Revert" danger busy={revert.isPending} confirm="Put every applied record back as it was?" onClick={() => revert.mutate()} />
        )}
      </div>
      {(verify.isError || revert.isError) && <p className="mt-2 text-sm text-rose-700">{problemText(verify.error ?? revert.error)}</p>}
      {revert.data && <p className="mt-2 text-sm">{revert.data.reverted} record(s) put back{revert.data.failed ? `, ${revert.data.failed} could not be` : ""}.</p>}
      {report && (
        <div className="mt-3 space-y-2 text-sm">
          <p>Records: {Object.entries(report.records).map(([k, v]) => `${v} ${k}`).join(" · ")}</p>
          {report.exceptions.length === 0
            ? <p className="text-green-800">✓ Every applied record is on the target with its uid, key, comments, files, links, map positions, placements, activities and revisions as before.</p>
            : <ul className="list-disc pl-5 text-rose-700">{report.exceptions.map((x, i) => <li key={i}>{x.uid} ({x.workspace_id}): {x.problem}</li>)}</ul>}
          <p className="text-xs text-slate-600">
            Old type {report.deprecation.type}: {report.deprecation.deprecated ? "deprecated" : report.deprecation.possible
              ? "nothing depends on it — it can be deprecated" : `still needed (${report.deprecation.blocking.map((b) => `${b.what}: ${b.detail}`).join("; ")})`}
          </p>
        </div>
      )}
    </Section>
  );
}
