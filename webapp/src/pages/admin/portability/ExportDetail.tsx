import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portabilityApi, problemText, workspacesApi } from "../../../api/client";
import type { Dependency, ExportView } from "../../../api/portabilityTypes";
import { ActionButton, bytes, Empty, ErrorBox, EXPORT_STEPS, JobsPanel, KV, Labels, LegalHold, Mono, PolicySummary, Section,
  StateBadge, Steps, UninspectedList, useJob, when } from "./shared";
import { SchedulePanel } from "./Schedules";

const OUTCOME_HELP: Record<string, string> = {
  include_workspace: "add that workspace to the export",
  external_reference: "keep the reference as an id; the importer resolves it or leaves it as a reference",
  exclude_referrers: "leave out the rows that name restricted records",
  block: "do not run this export",
};

/** What each kind of dependency is, in words: the export names something it does not carry. */
const RULE_HELP: Record<string, string> = {
  claim_subject: "history (ledger claims) about records",
  relation_endpoint: "relations to records",
  derived_endpoint: "relations derived by the ledger to records",
  merge_survivor: "merged records pointing to the record they became",
  ticket_subject: "tickets about records",
  ticket_link: "links between tickets",
  ticket_involves: "tickets involving records",
  document_subject: "documents about records",
  document_relation: "documents related to other records",
  foreign_claims: "history recorded by another workspace's sources about exported records",
  restricted_reference: "references to restricted records left out",
};

/** The outcome to suggest: a target that no longer exists here can only stay a reference. */
function recommended(d: Dependency): string | null {
  if (!d.workspace && d.options.includes("external_reference")) return "external_reference";
  if (d.workspace && d.options.includes("include_workspace")) return "include_workspace";
  return null;
}

export function ExportDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const exp = useQuery({ queryKey: ["portability-export", id], queryFn: () => portabilityApi.getExport(id) });
  const cfg = useQuery({ queryKey: ["portability-config"], queryFn: portabilityApi.config });
  const [confirmed, setConfirmed] = useState(false);
  const generated = !!exp.data?.manifest_sha256;
  const manifest = useQuery({ queryKey: ["portability-manifest", id], queryFn: () => portabilityApi.manifest(id),
                              enabled: generated });
  const [error, setError] = useState<string | null>(null);
  const done = (e: ExportView) => {
    qc.setQueryData(["portability-export", id], e);
    void qc.invalidateQueries({ queryKey: ["portability-exports"] });
    void qc.invalidateQueries({ queryKey: ["portability-manifest", id] });
    setError(null);
  };
  const fail = (e: unknown) => {
    setError(problemText(e));
    void qc.invalidateQueries({ queryKey: ["portability-export", id] });
  };
  const reload = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["portability-export", id] });
    void qc.invalidateQueries({ queryKey: ["portability-exports"] });
    void qc.invalidateQueries({ queryKey: ["portability-manifest", id] });
  }, [qc, id]);
  const { job, setJob, running } = useJob(reload);
  // Approving is quick; generating and publishing run as background jobs the page polls.
  const step = useMutation({
    mutationFn: async (s: "approve" | "generate" | "publish-git") => {
      if (s === "approve") return portabilityApi.exportStep(id, s, { confirm: confirmed });
      const { job: started } = await portabilityApi.exportJob(id, s, { confirm: confirmed });
      setJob(started);
      return null;
    },
    onSuccess: (v) => { if (v) done(v); else setError(null); }, onError: fail });
  const [reason, setReason] = useState("");
  const revoke = useMutation({ mutationFn: () => portabilityApi.revokeExport(id, reason), onSuccess: done, onError: fail });
  const download = useMutation({
    mutationFn: () => portabilityApi.downloadArchive(id),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${id}.tar`;
      a.click();
      URL.revokeObjectURL(url);
    },
    onError: fail,
  });

  if (exp.isError) return <p className="text-sm text-rose-700">{problemText(exp.error)}</p>;
  if (!exp.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const e = exp.data;
  const myEmail = me.data?.email;
  const policy = cfg.data?.policy;
  const selfApproval = e.risk === "high" && myEmail === e.requested_by && !!policy?.separation_of_duties;
  const needsConfirm = e.risk === "high" && policy?.step_up === "session_confirmation";
  const uninspected = e.analysis.blobs?.uninspected ?? [];
  const busy = step.isPending ? step.variables : null;

  return (
    <div className="max-w-6xl space-y-4">
      <Link to="/admin/portability?tab=exports" className="text-xs text-slate-500 hover:text-slate-700">&larr; Portability</Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-mono text-lg font-semibold text-slate-900">{e.id}</h1>
          <p className="text-sm text-slate-600">
            {e.mode === "full" ? "Every workspace" : e.workspaces.join(", ")} · {e.mode}
            {e.risk === "high" && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">high risk</span>}
          </p>
          <div className="mt-2"><Labels labels={e.labels} /></div>
        </div>
        <StateBadge state={e.state} />
      </div>
      <Steps steps={EXPORT_STEPS} state={e.state} />
      <ErrorBox error={error ?? (e.state === "failed" ? e.error : null)} />

      <Section title="Next step">
        <div className="flex flex-wrap items-center gap-3">
          {e.state === "awaiting_approval" && (
            <>
              {needsConfirm && (
                <label className="flex items-center gap-2 text-sm text-slate-700"
                       title="Your identity provider does not report when you last signed in: confirm this step explicitly">
                  <input type="checkbox" checked={confirmed} onChange={(ev) => setConfirmed(ev.target.checked)} />
                  I confirm this high-risk approval
                </label>
              )}
              <ActionButton label="Approve" busy={busy === "approve"} onClick={() => step.mutate("approve")}
                            disabled={!e.analysis.ready || selfApproval}
                            title={selfApproval ? "A high-risk export needs another approver" : undefined}
                            confirm={`Approve this ${e.risk === "high" ? "high-risk " : ""}export?`} />
              {!e.analysis.ready && (
                <ol className="w-full list-decimal space-y-0.5 pl-5 text-sm text-amber-900">
                  <li>Below, under <a href="#dependencies" className="underline">Dependencies</a>, choose an outcome for each
                    highlighted row (the recommended one is marked ★).</li>
                  <li>Press <b>Save outcomes and analyse again</b> (at the top right of that section).</li>
                  <li>Then {needsConfirm ? <>tick <i>I confirm this high-risk approval</i> and </> : ""}press <b>Approve</b> here;
                    next come <b>Generate</b> and {e.destination.repository ? <b>Publish to Git</b> : <b>Download</b>}.</li>
                </ol>
              )}
              {selfApproval && <span className="text-sm text-amber-800">You requested it: another administrator must approve.</span>}
              {uninspected.length > 0 && <span className="text-sm text-amber-800">{uninspected.length} file(s) will travel uninspected.</span>}
            </>
          )}
          {e.state === "approved" && (
            <ActionButton label="Generate" busy={busy === "generate" || (running && job?.action === "generate")}
                          disabled={running} onClick={() => step.mutate("generate")} />
          )}
          {e.state === "ready_to_publish" && (
            <>
              <ActionButton label="Publish to Git" busy={busy === "publish-git" || (running && job?.action === "publish-git")}
                            onClick={() => step.mutate("publish-git")}
                            disabled={!e.destination.repository || running}
                            confirm={`Commit and tag this checkpoint in ${e.destination.repository}? A published tag cannot be withdrawn from history.`} />
              {!e.destination.repository && <span className="text-sm text-slate-500">No repository was chosen: download it instead.</span>}
            </>
          )}
          {(e.state === "ready_to_publish" || e.state === "published") && (
            <button type="button" onClick={() => download.mutate()} disabled={download.isPending}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
              {download.isPending ? "Preparing…" : "Download checkpoint (.tar)"}
            </button>
          )}
          {running && <span className="text-sm text-sky-700">{job?.action.replace("-", " ")} is {job?.state}… this page updates by itself.</span>}
          {job?.state === "failed" && <span className="text-sm text-rose-700">{job.action} failed: {job.error?.error}</span>}
          {e.state === "published" && <span className="text-sm text-emerald-700">Published. Import it elsewhere by its tag.</span>}
          {(e.state === "revoked" || e.state === "expired") && <span className="text-sm text-slate-500">This export is {e.state}.</span>}
          {!["revoked", "expired", "generating", "verifying", "publishing"].includes(e.state) && (
            <span className="ml-auto flex items-center gap-2">
              <input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="Reason to revoke"
                     className="w-48 rounded border border-slate-300 px-2 py-1 text-sm" />
              <ActionButton label="Revoke" danger disabled={!reason.trim()} busy={revoke.isPending}
                            onClick={() => revoke.mutate()} confirm="Revoke this export?" />
            </span>
          )}
        </div>
      </Section>

      <SchedulePanel e={e} isAdmin={!!cfg.data?.is_admin} highRiskNeedsConfirm={needsConfirm} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Request">
          <KV rows={[
            ["Requested by", e.requested_by], ["Approved by", e.approved_by ?? "—"], ["Created", when(e.created_at)],
            ["Repository", e.destination.repository ?? "none"], ["Data", e.destination.artifact_store === (cfg.data?.repository_store ?? "@repository")
                ? "in the repository, with the archive" : e.destination.artifact_store ? `artifact store ${e.destination.artifact_store}` : "none"],
            ["Restricted classes included", e.classifications.length ? `${e.classifications.join(", ")} (encrypted)` : "none"],
            ["Purpose", e.decisions.purpose?.replace(/_/g, " ")],
            ["People", e.identity_profile?.replace(/_/g, " ")],
            ["Generation", e.analysis.metrics ? `${e.analysis.metrics.seconds} s · process peak ${e.analysis.metrics.peak_memory_mb} MB · ${e.analysis.metrics.rows} rows · ${bytes(e.analysis.metrics.artifact_bytes)}` : undefined],
            ["Base export", e.base_export_id ? <Link className="text-indigo-700 hover:underline" to={`/admin/portability/exports/${e.base_export_id}`}>{e.base_export_id}</Link> : undefined],
          ]} />
        </Section>
        <Section title="Estimate and warnings">
          {e.analysis.estimate ? (
            <KV rows={[
              ["Records", e.analysis.estimate.records], ["Tickets", e.analysis.estimate.tickets],
              ["Ledger claim events", e.analysis.estimate.claim_events],
              ["Attachments", `${e.analysis.estimate.attachments} (${bytes(e.analysis.estimate.attachment_bytes)}, ${
                e.destination.artifact_store === (cfg.data?.repository_store ?? "@repository") ? "committed in the repository"
                  : "in the artifact store, outside Git"})`],
              ["Workspaces after closure", e.analysis.closure?.workspaces?.join(", ")],
            ]} />
          ) : <Empty>Not analysed yet.</Empty>}
          {(e.analysis.warnings ?? []).length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-800">
              {e.analysis.warnings!.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}
        </Section>
      </div>

      <JobsPanel subject={e.id} current={job} />

      <Dependencies e={e} onSaved={done} onError={fail} />
      <BlobReview e={e} onSaved={done} onError={fail} />

      {e.watermark && (
        <Section title="Watermark">
          <KV rows={[["Checkpoint", e.watermark.checkpoint_sequence], ["Vector", <Mono>{e.watermark.vector_sha256}</Mono>],
                     ["Taken at", when(e.watermark.snapshot_time)],
                     ["Per table", <span className="font-mono text-xs">{Object.entries(e.watermark.vector).map(([t, n]) => `${t.replace("ledger_", "")} ${n}`).join(" · ")}</span>]]} />
        </Section>
      )}

      {e.git.tag && (
        <Section title="Git">
          <KV rows={[["Repository", e.git.repository], ["Tag", <Mono>{e.git.tag}</Mono>], ["Commit", <Mono>{e.git.commit}</Mono>],
                     ["Parent", <Mono short>{e.git.parent}</Mono>], ["Previous export tag", e.git.previous_tag ? <Mono>{e.git.previous_tag}</Mono> : undefined],
                     ["Repository identity", <Mono>{e.git.repository_id}</Mono>],
                     ["In Git", e.git.files_in_git !== undefined ? `${e.git.files_in_git} files; repository ${bytes(e.git.repository_bytes)} (bulk chunks and blobs are artifacts)` : undefined]]} />
        </Section>
      )}

      {manifest.data && <ManifestView m={manifest.data.manifest} sha={manifest.data.sha256} />}

      <div className="grid gap-4 lg:grid-cols-2">
        {(manifest.data?.manifest.policy ?? policy) && (
          <Section title={manifest.data?.manifest.policy ? "Policy this archive was made under" : "Policy in force"}>
            <PolicySummary policy={(manifest.data?.manifest.policy ?? policy)!} />
          </Section>
        )}
        {cfg.data?.is_admin && (
          <Section title="Retention">
            <p className="mb-2 text-xs text-slate-500">Local archive files are deleted {policy?.retention_days ?? 90} days after the
              request unless held; Git history and the audit trail are kept.</p>
            <LegalHold kind="exports" id={e.id} on={e.legal_hold} reason={e.legal_hold_reason} purgedAt={e.purged_at}
                       onChange={reload} />
          </Section>
        )}
      </div>
    </div>
  );
}

function Dependencies({ e, onSaved, onError }: { e: ExportView; onSaved: (v: ExportView) => void; onError: (x: unknown) => void }) {
  const deps: Dependency[] = e.analysis.closure?.dependencies ?? [];
  const editable = e.state === "awaiting_approval" || e.state === "failed";
  // Rows still without an outcome start on the recommended one, so saving is one press.
  const suggested = useCallback(() => Object.fromEntries(
    deps.filter((d) => !d.outcome && recommended(d)).map((d) => [d.id, recommended(d)!])), [deps]);
  const [draft, setDraft] = useState<Record<string, string>>(() => (editable ? suggested() : {}));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => setDraft(editable ? suggested() : {}), [e.id, e.state, e.analysis]);
  const save = useMutation({ mutationFn: () => portabilityApi.decideExport(e.id, draft), onSuccess: onSaved, onError });
  return (
    <Section title="Dependencies" id="dependencies"
             right={editable && Object.keys(draft).length > 0 && (
               <button type="button" onClick={() => save.mutate()} disabled={save.isPending}
                       className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white">
                 {save.isPending ? "Analysing…" : "Save outcomes and analyse again"}
               </button>)}>
      {deps.length > 0 && editable && (
        <p className="mb-2 text-xs text-slate-500">
          What is exported refers to things it does not carry: say what to do with each, then save. <i>Not found here</i>{" "}
          means the target no longer exists on this installation (deleted or merged): keep it as a reference. Rows without
          an outcome start on the recommended one (★). A scheduled run keeps new dependencies as external references by itself.
        </p>
      )}
      {deps.length === 0 ? <Empty>Nothing outside the scope is referenced.</Empty> : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="py-1">Dependency</th><th>References</th><th>Examples</th><th className="w-72">Outcome</th></tr>
          </thead>
          <tbody>
            {deps.map((d) => {
              const value = draft[d.id] ?? d.outcome ?? "";
              return (
                <tr key={d.id} className="border-t border-slate-100 align-top">
                  <td className="py-2">
                    <div className="font-medium">{RULE_HELP[d.rule] ?? d.rule.replace(/_/g, " ")}</div>
                    <div className="text-xs text-slate-500">{d.workspace ? `in ${d.workspace}` : d.rule === "restricted_reference" ? "restricted records left out" : "not found here"}</div>
                  </td>
                  <td className="py-2">{d.count ?? "—"}</td>
                  <td className="py-2 text-xs text-slate-500">
                    {(d.examples ?? []).slice(0, 3).map((x, i) => <div key={i} className="font-mono">{x.from.slice(0, 18)} → {x.to.slice(0, 18)}</div>)}
                  </td>
                  <td className="py-2">
                    {editable ? (
                      <select value={value} onChange={(ev) => setDraft({ ...draft, [d.id]: ev.target.value })}
                              className={`w-full rounded border px-2 py-1 text-sm ${value ? "border-slate-300" : "border-amber-400 bg-amber-50"}`}>
                        <option value="">Choose an outcome…</option>
                        {d.options.map((o) => (
                          <option key={o} value={o}>
                            {o === recommended(d) ? "★ recommended: " : ""}{o.replace(/_/g, " ")} — {OUTCOME_HELP[o]}
                          </option>
                        ))}
                      </select>
                    ) : <span>{d.outcome?.replace(/_/g, " ") ?? "—"}</span>}
                    {d.problem && <div className="mt-1 text-xs text-rose-700">{d.problem}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {(e.analysis.closure?.automatic ?? []).length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs text-slate-500">
          {e.analysis.closure!.automatic.map((a) => <li key={a.rule}>Automatically included — {a.detail}</li>)}
        </ul>
      )}
    </Section>
  );
}

const BLOB_HELP: Record<string, string> = {
  approve_opaque: "export it as an approved opaque binary",
  accept_classified: "export it: the marking does not make it restricted",
  exclude: "leave this file out of the export",
  classify_encrypt: "export it as restricted content, encrypted",
  block: "do not run this export",
};

function BlobReview({ e, onSaved, onError }: { e: ExportView; onSaved: (v: ExportView) => void; onError: (x: unknown) => void }) {
  const b = e.analysis.blobs;
  const editable = e.state === "awaiting_approval" || e.state === "failed";
  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => setDraft({}), [e.id, e.state]);
  const save = useMutation({ mutationFn: () => portabilityApi.decideExport(e.id, draft), onSuccess: onSaved, onError });
  if (!b) return null;
  return (
    <Section title={`Content inspection (${b.inspected} blob${b.inspected === 1 ? "" : "s"})`}
             right={editable && Object.keys(draft).length > 0 && (
               <button type="button" onClick={() => save.mutate()} disabled={save.isPending}
                       className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white">
                 {save.isPending ? "Inspecting…" : "Save decisions and inspect again"}
               </button>)}>
      {b.secrets.length > 0 && (
        <div className="mb-3 rounded border border-rose-200 bg-rose-50 p-2 text-sm text-rose-800">
          <div className="font-medium">Secrets found inside files — the export is refused until the content is corrected.</div>
          <ul className="mt-1 list-disc pl-5 text-xs">{b.secrets.slice(0, 10).map((f, i) => <li key={i}><span className="font-mono">{f.where}</span>: {f.kind}</li>)}</ul>
        </div>
      )}
      {b.needs_decision.length === 0 && b.secrets.length === 0 ? (
        <Empty>{(b.uninspected ?? []).length > 0
          ? `No secret found, and nothing that needs a decision; ${b.uninspected!.length} file(s) could not be inspected (below).`
          : "Every file was inspected: no secret, and nothing that needs a decision."}</Empty>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {b.needs_decision.map((d) => (
              <tr key={d.id} className="border-t border-slate-100 align-top">
                <td className="py-2">
                  <div className="font-mono text-xs">{d.where}</div>
                  <div className="text-xs text-slate-500">{d.status === "finding" ? d.findings.map((f) => f.kind).join("; ")
                    : d.reason ?? d.status}</div>
                </td>
                <td className="w-80 py-2">
                  {editable ? (
                    <select value={draft[d.id] ?? d.outcome ?? ""} onChange={(ev) => setDraft({ ...draft, [d.id]: ev.target.value })}
                            className="w-full rounded border border-amber-400 bg-amber-50 px-2 py-1 text-sm">
                      <option value="">Choose…</option>
                      {d.options.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")} — {BLOB_HELP[o]}</option>)}
                    </select>
                  ) : <span>{d.outcome ?? "—"}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {b.excluded.length > 0 && <p className="mt-2 text-xs text-slate-500">{b.excluded.length} file(s) left out by decision.</p>}
      {(b.uninspected ?? []).length > 0 && <div className="mt-3"><UninspectedList items={b.uninspected!} /></div>}
    </Section>
  );
}

function ManifestView({ m, sha }: { m: import("../../../api/portabilityTypes").ArchiveManifest; sha: string }) {
  const [raw, setRaw] = useState(false);
  const groups = Object.entries(m.families).reduce<Record<string, [string, typeof m.families[string]][]>>((acc, f) => {
    (acc[f[1].group] ??= []).push(f);
    return acc;
  }, {});
  return (
    <Section title="Manifest" right={<button type="button" className="text-xs text-indigo-700 hover:underline" onClick={() => setRaw((v) => !v)}>{raw ? "Summary" : "Raw JSON"}</button>}>
      {raw ? <pre className="max-h-[32rem] overflow-auto rounded bg-slate-50 p-3 text-xs">{JSON.stringify(m, null, 1)}</pre> : (
        <div className="space-y-4">
          <KV rows={[
            ["Format", m.format], ["SHA-256", <Mono>{sha}</Mono>],
            ["From", `${m.argus.instance_name ?? ""} ${m.argus.instance_id} · ARGUS ${m.argus.application_version} · schema ${m.argus.database_schema ?? "?"}`],
            ["Signed", m.signature ? `${m.signature.algorithm} by ${m.signature.principal} (${m.signature.key_id})` : "no"],
            ["Policy", m.versions.policy], ["Blobs", `${m.blobs.count} (${bytes(m.blobs.bytes)}) in ${m.blobs.stores.join(", ") || "—"}${m.blobs.excluded ? `; ${m.blobs.excluded} left out` : ""}`],
            ["People", m.identity ? `${m.identity.profile.replace(/_/g, " ")} — ${m.identity.identity_columns.join(", ")}` : undefined],
            ["Encryption", m.encryption ? `${m.encryption.algorithm}, for ${m.encryption.recipients.map((r) => r.recipient).join(", ")}` : "none"],
            ["Classes left out", m.classifications.excluded_classes.join(", ") || "none"],
            ["Invariants at export", m.invariants?.ok === null ? "not run" : m.invariants?.ok ? "ok" : `failing: ${(m.invariants?.codes ?? []).join(", ")}`],
          ]} />
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(groups).map(([group, fams]) => (
              <div key={group}>
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{group}{group === "projection" ? " (compared, never loaded)" : ""}</div>
                <table className="mt-1 w-full text-xs">
                  <tbody>
                    {fams.map(([name, f]) => (
                      <tr key={name} className="border-t border-slate-100">
                        <td className="py-0.5">{name}</td>
                        <td className="py-0.5 text-right tabular-nums">{f.rows}</td>
                        <td className="py-0.5 pl-2 text-slate-400">{f.chunks.length} chunk{f.chunks.length === 1 ? "" : "s"}
                          {f.chunks.length > 0 && ` · ${[...new Set(f.chunks.map((c) => c.storage ?? "git"))].join(", ")}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}
