import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portabilityApi, problemText, workspacesApi } from "../../../api/client";
import type { DryRunReport, ImportView, ReconciliationReport } from "../../../api/portabilityTypes";
import { ActionButton, bytes, Details, Empty, ErrorBox, ExplanationPanel, FailedItem, IMPORT_STEPS, JobProgress, JobsPanel, KV, Labels,
  LegalHold, Mono, PolicySummary, Section, StateBadge, Steps, UninspectedList, useJob, when } from "./shared";
import { DRY_RUN_OUTCOMES, familyExplanation, invariantExplanation, projectionExplanation } from "./explain";

type Step = "fetch-git" | "verify" | "approve" | "execute" | "resume" | "finalize";

export function ImportDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const imp = useQuery({ queryKey: ["portability-import", id], queryFn: () => portabilityApi.getImport(id) });
  const cfg = useQuery({ queryKey: ["portability-config"], queryFn: portabilityApi.config });
  const [accepted, setAccepted] = useState(false);
  const state = imp.data?.state;
  const reconciled = !!state && ["ready_to_finalize", "finalized", "failed"].includes(state) && imp.data?.reconciliation_passed !== null;
  const rec = useQuery({ queryKey: ["portability-reconciliation", id], queryFn: () => portabilityApi.reconciliation(id),
                         enabled: reconciled, retry: false });
  const prov = useQuery({ queryKey: ["portability-provenance", id], queryFn: () => portabilityApi.provenance(id) });
  const [error, setError] = useState<string | null>(null);
  const refresh = (v?: ImportView) => {
    if (v) qc.setQueryData(["portability-import", id], v);
    for (const k of ["portability-imports", "portability-import", "portability-reconciliation", "portability-provenance"]) {
      void qc.invalidateQueries({ queryKey: k === "portability-imports" ? [k] : [k, id] });
    }
  };
  const reload = useCallback(() => {
    for (const k of ["portability-imports", "portability-import", "portability-reconciliation", "portability-provenance"]) {
      void qc.invalidateQueries({ queryKey: k === "portability-imports" ? [k] : [k, id] });
    }
  }, [qc, id]);
  const { job, setJob, running } = useJob(reload);
  // Coming back to the page while a step still runs: follow it again.
  useEffect(() => {
    portabilityApi.jobs(id).then((js) => {
      const live = js.find((j) => j.state === "queued" || j.state === "running");
      if (live) setJob(live);
    }).catch(() => undefined);
  }, [id, setJob]);
  // Approving is quick; fetching, verifying, executing and finalizing run as background jobs the page polls.
  const step = useMutation({
    mutationFn: async (s: Step) => {
      if (s === "approve") return portabilityApi.importStep(id, s, { acknowledge_uninspected: accepted });
      const { job: started } = await portabilityApi.importJob(id, s);
      setJob(started);
      return undefined;
    },
    onSuccess: (v) => { setError(null); refresh(v); },
    onError: (e) => { setError(problemText(e)); refresh(); },
  });
  const [reason, setReason] = useState("");
  const discard = useMutation({
    mutationFn: () => portabilityApi.discardImport(id, reason),
    onSuccess: (v) => { setError(null); refresh(v); },
    onError: (e) => { setError(problemText(e)); refresh(); },
  });
  const chain = useQuery({ queryKey: ["portability-origin-chain", id], queryFn: () => portabilityApi.originChain(id),
                           enabled: imp.data?.state === "finalized" && imp.data?.mode !== "evidence", retry: false });
  const dry = useMutation({
    // A background job the page follows: on a full archive the dry run checks every row and takes minutes.
    mutationFn: async (decisions: Record<string, unknown>) => {
      const { job: started } = await portabilityApi.dryRunJob(id, decisions);
      setJob(started);
    },
    onSuccess: () => { setError(null); refresh(); },
    onError: (e) => { setError(problemText(e)); refresh(); },
  });

  if (imp.isError) return <p className="text-sm text-rose-700">{problemText(imp.error)}</p>;
  if (!imp.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const i = imp.data;
  const dryRunning = dry.isPending || (running && job?.action === "dry-run");
  const busy = step.isPending ? step.variables : dryRunning ? "dry-run" : null;
  const report = i.dry_run as DryRunReport;
  const hasDryRun = !!report && "ready" in report;
  const policy = cfg.data?.policy;
  const needsSecond = !!policy?.separation_of_duties &&
    (i.mode === "merge" || i.mode === "restore" || (i.manifest?.classifications?.included ?? []).length > 0);
  const selfApproval = needsSecond && me.data?.email === i.requested_by;
  const uninspected = report?.uninspected_content ?? (i.manifest?.blobs?.inspection?.uninspected
    ? { count: i.manifest.blobs.inspection.uninspected, warning: "", items: i.manifest.blobs.uninspected ?? [] } : undefined);
  const stepBusy = (s: Step) => busy === s || (running && job?.action === s);
  const final = i.state === "finalized" || i.state === "discarded";

  return (
    <div className="max-w-6xl space-y-4">
      <Link to="/admin/portability?tab=imports" className="text-xs text-slate-500 hover:text-slate-700">&larr; Portability</Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-mono text-lg font-semibold text-slate-900">{i.id}</h1>
          <p className="text-sm text-slate-600">
            {i.mode} · {i.source.repository ? <>from <b>{i.source.repository}</b> <Mono>{i.source.ref}</Mono></> : "uploaded checkpoint"}
          </p>
          <div className="mt-2">
            {i.manifest ? <Labels labels={i.labels} />
              : <span className="text-xs text-slate-500">Labels appear once the checkpoint is verified.</span>}
          </div>
        </div>
        <StateBadge state={i.state} />
      </div>
      <Steps steps={IMPORT_STEPS} state={i.state} />
      <ErrorBox error={error ?? (["failed", "invalid"].includes(i.state) || i.error?.code === "interrupted" ? i.error : null)} />

      <Section title="Next step">
        <div className="flex flex-wrap items-center gap-3">
          {running && job && <JobProgress job={job} />}
          {!running && hasDryRun && !report.ready && (i.state === "dry_run_ready" || i.state === "awaiting_approval") && (
            <Blocked report={report} />
          )}
          {i.state === "created" && i.source.repository && (
            <ActionButton label="Fetch into quarantine" busy={stepBusy("fetch-git")} disabled={running} onClick={() => step.mutate("fetch-git")} />
          )}
          {i.state === "created" && !i.source.repository && <span className="text-sm text-slate-500">Waiting for the uploaded checkpoint.</span>}
          {i.state === "quarantined" && (
            <ActionButton label="Verify" busy={stepBusy("verify")} disabled={running} onClick={() => step.mutate("verify")} />
          )}
          {(i.state === "dry_run_ready" || i.state === "awaiting_approval") && (
            <ActionButton label={hasDryRun ? "Run the dry run again" : "Dry run"} busy={busy === "dry-run"}
                          disabled={running} onClick={() => dry.mutate({})} />
          )}
          {i.state === "awaiting_approval" && (
            <>
              {uninspected && (
                <label className="flex items-center gap-2 text-sm text-amber-900">
                  <input type="checkbox" checked={accepted} onChange={(ev) => setAccepted(ev.target.checked)} />
                  I accept that {uninspected.count} file(s) were not inspected for secrets or classified content
                </label>
              )}
              <ActionButton label="Approve" busy={busy === "approve"} onClick={() => step.mutate("approve")}
                            disabled={selfApproval || (!!uninspected && !accepted)}
                            confirm="Approve this import as shown by the dry run?" />
              {selfApproval && <span className="text-sm text-amber-800">You registered it: another administrator must approve.</span>}
            </>
          )}
          {i.state === "approved" && (
            <ActionButton label="Execute" busy={stepBusy("execute")} disabled={running} onClick={() => step.mutate("execute")}
                          confirm={i.mode === "evidence" ? "Store this archive as read-only evidence?" :
                            "Load the archive into staged workspaces, rebuild and reconcile?"} />
          )}
          {(i.state === "importing" || i.state === "failed") && (
            <ActionButton label={`Resume in staging (${i.checkpoints.done} steps done)`} busy={stepBusy("resume")} disabled={running} onClick={() => step.mutate("resume")} />
          )}
          {i.state === "ready_to_finalize" && (
            <ActionButton label="Finalize" busy={stepBusy("finalize")} disabled={running} onClick={() => step.mutate("finalize")}
                          confirm={i.mode === "evidence" ? "Finalize: keep this archive as read-only evidence."
                            : "Finalize: promote the reconciled import into this instance in one transaction — all of it becomes visible at once, as permanent history."} />
          )}
          {i.state === "finalized" && <span className="text-sm text-emerald-700">Finalized {i.reconciliation_sha256 ? <>— reconciliation <Mono short>{i.reconciliation_sha256}</Mono></> : null}.</span>}
          {i.state === "discarded" && <span className="text-sm text-slate-500">Discarded: nothing it loaded remains.</span>}
          {running && <span className="text-sm text-sky-700">{job?.action.replace("-", " ")} is {job?.state}… this page updates by itself.</span>}
          {job?.state === "failed" && <span className="text-sm text-rose-700">{job.action} failed: {job.error?.error}</span>}
          {!final && (
            <span className="ml-auto flex items-center gap-2">
              <input value={reason} onChange={(ev) => setReason(ev.target.value)} placeholder="Reason to discard"
                     className="w-48 rounded border border-slate-300 px-2 py-1 text-sm" />
              <ActionButton label="Discard" danger busy={discard.isPending} onClick={() => discard.mutate()}
                            confirm="Discard: drop its staging database and quarantine. Active data was never touched; the audit trail stays." />
            </span>
          )}
        </div>
      </Section>

      {uninspected && uninspected.items.length > 0 && <UninspectedList items={uninspected.items} total={uninspected.count} />}

      {(i.state === "dry_run_ready" || i.state === "awaiting_approval") && i.mode !== "evidence" && (
        <DecisionsForm i={i} running={dryRunning || running} onRun={(d) => dry.mutate(d)} />
      )}
      {hasDryRun && (
        <DryRun r={report} resolving={dryRunning || running}
                current={(i.decisions as { catalogue_conflicts?: Record<string, string> }).catalogue_conflicts ?? {}}
                onResolve={(catalogue_conflicts) => dry.mutate({ ...(i.decisions as Record<string, unknown>), catalogue_conflicts })} />
      )}
      {rec.data && <Reconciliation r={rec.data.report} sha={rec.data.sha256} />}
      {chain.data && !chain.data.ok && (
        <p className="text-sm text-rose-700">The origin chain no longer verifies: open the details below (Origin chain).</p>
      )}
      {i.state === "finalized" && i.mode === "evidence" && <Evidence id={i.id} />}
      <Details label="Show details: source and signature, verification, archive, jobs, origin chain, audit, retention">
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Source and signature">
              <KV rows={[
                ["Registered by", i.requested_by], ["Approved by", i.approved_by ?? "—"], ["Created", when(i.created_at)],
                ["Tag", i.verification.git?.tag ? <Mono>{i.verification.git.tag}</Mono> : undefined],
                ["Commit", <Mono>{i.commit}</Mono>],
                ["Signed by", i.verification.git?.signed_by ?? i.verification.checkpoint?.signed_by ?? undefined],
                ["Repository identity", i.verification.git ? <Mono>{i.verification.git.repository_id}</Mono> : undefined],
                ["Previous export tag", i.verification.git?.previous_tag ? <Mono>{i.verification.git.previous_tag}</Mono> : undefined],
                ["Upload", i.verification.upload ? `${bytes(i.verification.upload.bytes)}, sha256 ${i.verification.upload.sha256.slice(0, 12)}` : undefined],
                ["Staging", i.staging?.database ? `${i.staging.database} — isolated; nothing is visible here before finalization` : undefined],
              ]} />
            </Section>
            <Section title="Verification">
              {i.verification.checkpoint ? (
                <KV rows={[
                  ["Files", i.verification.checkpoint.files], ["Chunks", i.verification.checkpoint.chunks],
                  ["Rows", i.verification.checkpoint.rows],
                  ["Artifacts", `${i.verification.checkpoint.blobs} (${bytes(i.verification.checkpoint.blob_bytes)})${i.verification.checkpoint.artifact_complete ? ", all present" : ""}`],
                  ["External chunks", i.verification.checkpoint.external_chunks ?? undefined],
                  ["Content", i.verification.checkpoint.content_verified ? "verified" + (i.manifest?.labels?.encrypted ? " (decrypted for this session)" : "") : "not verified"],
                  ["Manifest", <Mono>{i.verification.checkpoint.manifest_sha256}</Mono>],
                ]} />
              ) : <Empty>Not verified yet: checksums, signature, chunks and artifacts are checked in quarantine.</Empty>}
            </Section>
          </div>

          {i.manifest && (
            <Section title="Archive">
              <KV rows={[
                ["Export", i.manifest.export_id], ["Mode", i.manifest.mode],
                ["Workspaces", i.manifest.workspaces.join(", ")],
                ["Watermark", <>checkpoint {i.manifest.watermark.checkpoint_sequence} · <Mono short>{i.manifest.watermark.vector_sha256}</Mono> at {when(i.manifest.watermark.snapshot_time)}</>],
                ["People", i.manifest.identity?.profile.replace(/_/g, " ")],
                ["Base export", i.manifest.base?.export_id],
                ["From", `${i.manifest.argus.instance_name ?? ""} ${i.manifest.argus.instance_id} · ARGUS ${i.manifest.argus.application_version}`],
                ["Restricted classes included", (i.manifest.classifications.included ?? []).join(", ") || "none"],
                ["Classes left out", (i.manifest.classifications.excluded_classes ?? []).join(", ") || "none"],
                ["Purpose", i.manifest.purpose?.replace(/_/g, " ")],
              ]} />
              {i.manifest.policy && (
                <div className="mt-3 border-t border-slate-100 pt-3">
                  <div className="mb-1 text-xs text-slate-500">Made under</div>
                  <PolicySummary policy={i.manifest.policy} />
                </div>
              )}
            </Section>
          )}

          <JobsPanel subject={i.id} current={job} />
          {chain.data && (
            <Section title="Origin chain" right={<span className={`text-sm font-medium ${chain.data.ok ? "text-emerald-700" : "text-rose-700"}`}>
              {chain.data.ok ? "Verifies" : "Changed"}</span>}>
              <KV rows={[["Chain", <Mono>{chain.data.origin_chain_sha256}</Mono>], ["Ingestion event", chain.data.ingestion_event],
                         ["Problems", chain.data.problems?.length ? chain.data.problems.map((p) => `${p.family} ${p.key}: ${p.problem}`).join("; ") : undefined]]} />
              <p className="mt-2 text-xs text-slate-500">Every imported ledger row, recomputed from what is here, against the hash of the archive line it came from.</p>
            </Section>
          )}
          {prov.data && (
            <Section title="Provenance and audit">
              <ol className="space-y-1 text-xs">
                {prov.data.events.map((e) => (
                  <li key={e.seq} className="flex flex-wrap gap-2">
                    <span className="w-40 shrink-0 text-slate-500">{when(e.at)}</span>
                    <span className="w-32 shrink-0 font-medium">{e.kind.replace(/_/g, " ")}</span>
                    <span className="text-slate-500">{e.from && e.to ? `${e.from} → ${e.to}` : e.to ?? ""}</span>
                    <span className="ml-auto text-slate-500">{e.actor}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
          {cfg.data?.is_admin && (
            <Section title="Retention">
              <p className="mb-2 text-xs text-slate-500">Quarantine, staging and evidence copies are deleted {policy?.retention_days ?? 90} days
                after registration unless held; the import's record and audit are kept.</p>
              <LegalHold kind="imports" id={i.id} on={i.legal_hold} reason={i.legal_hold_reason} purgedAt={i.purged_at}
                         onChange={reload} />
            </Section>
          )}
      </Details>
    </div>
  );
}

function DecisionsForm({ i, onRun, running }: { i: ImportView; onRun: (d: Record<string, unknown>) => void; running: boolean }) {
  const current = i.decisions as { workspace_map?: Record<string, string>; unresolved_references?: string; governance?: string;
                                   projections?: string };
  const [map, setMap] = useState<Record<string, string>>(current.workspace_map ?? {});
  const [refs, setRefs] = useState(current.unresolved_references ?? "block");
  const [gov, setGov] = useState(current.governance === "load");
  const [proj, setProj] = useState(current.projections ?? "verify");
  const archiveRelease = (i.manifest as { argus?: { application_version?: string } } | undefined)?.argus?.application_version;
  const [chosen, setChosen] = useState<string[]>((i.decisions as { select_workspaces?: string[] }).select_workspaces ?? []);
  return (
    <Section title="Decisions for the dry run">
      <div className="space-y-3 text-sm">
        <div>
          <span className="block text-xs font-medium text-slate-600">Workspace ids here (leave as is to keep the archive's)</span>
          <div className="mt-1 grid gap-2 md:grid-cols-2">
            {(i.manifest?.workspaces ?? []).map((w) => (
              <label key={w} className="flex items-center gap-2">
                <span className="w-40 truncate font-mono text-xs">{w}</span> →
                <input value={map[w] ?? w} onChange={(e) => setMap({ ...map, [w]: e.target.value })}
                       className="flex-1 rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
              </label>
            ))}
          </div>
        </div>
        {i.mode === "selective" && (
          <div>
            <span className="block text-xs font-medium text-slate-600">Workspaces to import</span>
            <div className="mt-1 flex flex-wrap gap-3">
              {(i.manifest?.workspaces ?? []).map((w) => (
                <label key={w} className="flex items-center gap-1 font-mono text-xs">
                  <input type="checkbox" checked={chosen.includes(w)}
                         onChange={() => setChosen(chosen.includes(w) ? chosen.filter((x) => x !== w) : [...chosen, w])} />
                  {w}
                </label>
              ))}
            </div>
          </div>
        )}
        <label className="flex items-center gap-2">
          References the archive and this instance both lack:
          <select value={refs} onChange={(e) => setRefs(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
            <option value="block">block the import</option>
            <option value="defer">leave unresolved and list them in the reconciliation</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          Projections (facts, derived relations, conflicts, ticket links):
          <select value={proj} onChange={(e) => setProj(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
            <option value="verify">must equal the archive's</option>
            <option value="accept_rebuilt">accept what this release rebuilds from the archive's ledger{archiveRelease ? ` (archive from ${archiveRelease})` : ""}</option>
          </select>
        </label>
        {proj === "accept_rebuilt" && (
          <p className="text-xs text-amber-800">Only when every authoritative row equals the archive's. The differences, and any invariant
            failing on the archive's data, are listed in the signed reconciliation; new conflicts stay open for review.</p>
        )}
        {(i.mode === "merge" || i.mode === "selective") && (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={gov} onChange={(e) => setGov(e.target.checked)} />
            Load the archive's authority policies and rulesets (otherwise they are listed, not loaded)
          </label>
        )}
        <button type="button" disabled={running}
                onClick={() => onRun({ workspace_map: Object.fromEntries(Object.entries(map).filter(([k, v]) => v && v !== k)),
                                       unresolved_references: refs, ...(gov ? { governance: "load" } : {}),
                                       projections: proj,
                                       ...(i.mode === "selective" ? { select_workspaces: chosen } : {}) })}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:bg-slate-300">
          {running ? "Running…" : "Run the dry run with these decisions"}
        </button>
      </div>
    </Section>
  );
}

const OUTCOMES = ["create", "identical", "update_same_origin", "known_identity", "unresolved_reference", "divergent"];
const RED_OUTCOMES = ["divergent", "unresolved_reference"];

function DryRun({ r, current, onResolve, resolving }: { r: DryRunReport; current: Record<string, string>;
    onResolve: (decisions: Record<string, string>) => void; resolving: boolean }) {
  const resolvable = (r.blocking ?? []).filter((b) => b.resolvable);
  const otherBlocking = (r.blocking ?? []).filter((b) => !b.resolvable);
  const [open, setOpen] = useState<string | null>(null);
  const flagged = RED_OUTCOMES.map((o) => [o, Object.values(r.families ?? {}).reduce((n, c) => n + (c[o] ?? 0), 0)] as const)
    .filter(([, n]) => n > 0);
  return (
    <Section title="Dry run" right={<span className={`text-sm font-medium ${r.ready ? "text-emerald-700" : "text-rose-700"}`}>
      {r.ready ? "Ready for approval" : "Blocked"}</span>}>
      {r.note && <p className="mb-2 text-sm text-slate-600">{r.note}</p>}
      {r.chain && <p className="mb-2 text-sm text-slate-600">Chain: <b>{r.chain.status.replace(/_/g, " ")}</b>
        {r.chain.applied !== undefined && ` · ${r.chain.applied} export(s) from this origin applied here`}</p>}
      {flagged.length > 0 && (
        <p className="mb-2 text-sm">
          {flagged.map(([o, n], k) => (
            <span key={o}>{k > 0 && " · "}<FailedItem label={`${n} ${o.replace(/_/g, " ")}`} selected={open === o}
                                                     onSelect={() => setOpen(open === o ? null : o)} /></span>
          ))}
        </p>
      )}
      {open && DRY_RUN_OUTCOMES[open] && <ExplanationPanel e={DRY_RUN_OUTCOMES[open]} onClose={() => setOpen(null)} />}
      {r.families && (
        <Details label="Show the outcome of every family" className="mb-3">
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr><th className="py-1">Family</th>{OUTCOMES.map((o) => <th key={o} className="px-2 text-right">{o.replace(/_/g, " ")}</th>)}</tr>
            </thead>
            <tbody>
              {Object.entries(r.families).map(([f, c]) => (
                <tr key={f} className="border-t border-slate-100">
                  <td className="py-0.5">{f}</td>
                  {OUTCOMES.map((o) => (
                    <td key={o} className="px-2 text-right tabular-nums">
                      {c[o] && RED_OUTCOMES.includes(o)
                        ? <FailedItem label={c[o]} selected={open === o} onSelect={() => setOpen(open === o ? null : o)} />
                        : c[o] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Details>
      )}
      {resolvable.length > 0 && <DivergentCatalogue items={resolvable} current={current} onResolve={onResolve} running={resolving} />}
      <Issues title="Blocking" items={otherBlocking.map((b) => `${b.family} ${b.key}: ${b.reason}`)} tone="rose" />
      <Issues title="Catalogue conflicts (never overwritten; review the type here)" tone="rose"
              items={(r.catalogue_conflicts ?? []).map((c) => `${c.key}: ${c.reason}`)} />
      <Issues title="Identity candidates (opened for review after import, never merged)" tone="amber"
              items={(r.identity_candidates ?? []).map((c) => `${c.identifier} ${c.value}: archive ${c.archive.slice(0, 8)} ↔ here ${c.here.slice(0, 8)}`)} />
      <Issues title={`Unresolved references (${r.unresolved_reference_count ?? 0}; outcome: ${r.unresolved_references_outcome})`} tone="amber"
              items={(r.unresolved_references ?? []).map((u) => `${u.family} ${u.key} → ${u.missing.map((m) => m[1]).join(", ")}`)} />
      <Issues title="Over a workspace's quota once loaded (an import loads anyway; raise the quota in Administration → Quotas, or the workspace will refuse new records and files)" tone="amber"
              items={(r.quota_warnings ?? []).map((w) => w.message)} />
      <Issues title="Governance not loaded" tone="amber" items={r.governance_not_loaded ?? []} />
      <Issues title="People already known here (kept as they are)" tone="slate" items={(r.identities ?? []).map((x) => x.user)} />
      {r.workspaces && (
        <p className="mt-2 text-xs text-slate-500">
          Workspaces: {r.workspaces.map((w) => `${w.archive}${w.local !== w.archive ? ` → ${w.local}` : ""}${w.exists ? " (exists here)" : ""}`).join(", ")}
        </p>
      )}
    </Section>
  );
}

/** A divergent row in a catalogue family with no access or ledger history riding on it (icons,
 * equipment classes, equipment class reviews — see CATALOGUE_RESOLVABLE in importer.py): choosing
 * what to do with it here, instead of only ever blocking the import, since there is nowhere else in
 * the product to make that call before the import's own next run. */
function DivergentCatalogue({ items, current, onResolve, running }: {
  items: NonNullable<DryRunReport["blocking"]>;
  current: Record<string, string>;
  onResolve: (decisions: Record<string, string>) => void;
  running: boolean;
}) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const pending = { ...current, ...choices };
  const unchosen = items.filter((it) => !pending[`${it.family}:${it.key}`]);
  return (
    <div className="mb-3 rounded border border-amber-200 bg-amber-50 p-3">
      <p className="text-xs font-semibold text-amber-900">
        {items.length} record(s) already exist here with different content, made here rather than by this
        archive's origin. Choose what to do with each one, then apply.
      </p>
      <div className="mt-2 space-y-2">
        {items.map((it) => {
          const id = `${it.family}:${it.key}`;
          const choice = pending[id];
          return (
            <div key={id} className="rounded border border-amber-200 bg-white p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-medium text-slate-800">{it.family} · {it.key}</span>
                <div className="flex gap-1">
                  <button type="button" onClick={() => setChoices({ ...choices, [id]: "keep_local" })}
                          className={`rounded px-2 py-0.5 ${choice === "keep_local" ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-700 hover:bg-slate-50"}`}>
                    Keep what's here
                  </button>
                  <button type="button" onClick={() => setChoices({ ...choices, [id]: "use_archive" })}
                          className={`rounded px-2 py-0.5 ${choice === "use_archive" ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-700 hover:bg-slate-50"}`}>
                    Use the archive's version
                  </button>
                </div>
              </div>
              {(it.fields ?? []).length > 0 && (
                <table className="mt-1.5 w-full text-[11px]">
                  <thead className="text-slate-400"><tr><th className="text-left font-normal">Field</th><th className="text-left font-normal">Here</th><th className="text-left font-normal">Archive</th></tr></thead>
                  <tbody>
                    {it.fields!.map((f) => (
                      <tr key={f} className="border-t border-slate-100">
                        <td className="py-0.5 pr-2 text-slate-500">{f}</td>
                        <td className="py-0.5 pr-2 font-mono text-slate-700">{String(it.local?.[f] ?? "—")}</td>
                        <td className="py-0.5 font-mono text-slate-700">{String(it.archive?.[f] ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
      <button type="button" disabled={running || Object.keys(choices).length === 0}
              onClick={() => onResolve({ ...current, ...choices })}
              className="mt-2 rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:bg-slate-300">
        {running ? "Running…" : unchosen.length > 0 && Object.keys(choices).length > 0
          ? `Apply ${Object.keys(choices).length} of ${items.length} and re-run the dry run`
          : "Apply and re-run the dry run"}
      </button>
    </div>
  );
}

function Issues({ title, items, tone }: { title: string; items: string[]; tone: "rose" | "amber" | "slate" }) {
  if (items.length === 0) return null;
  const c = tone === "rose" ? "text-rose-800" : tone === "amber" ? "text-amber-800" : "text-slate-600";
  return (
    <div className="mt-2">
      <div className={`text-xs font-semibold ${c}`}>{title}</div>
      <ul className={`mt-1 max-h-40 list-disc overflow-auto pl-5 text-xs ${c}`}>
        {items.slice(0, 50).map((x, k) => <li key={k} className="font-mono">{x}</li>)}
      </ul>
    </div>
  );
}

type Selected = { kind: "family" | "projection" | "invariant"; name: string } | null;

function Reconciliation({ r, sha }: { r: ReconciliationReport; sha: string }) {
  const fams = Object.entries(r.families ?? {});
  const projs = Object.entries(r.projections ?? {});
  const events = Object.entries(r.rebuild?.events_written_by_rebuild ?? {});
  const failing = r.invariants && !r.invariants.ok ? r.invariants.failing ?? [] : [];
  const [sel, setSel] = useState<Selected>(null);
  const pick = (kind: NonNullable<Selected>["kind"], name: string) =>
    setSel(sel?.kind === kind && sel.name === name ? null : { kind, name });
  const is = (kind: NonNullable<Selected>["kind"], name: string) => sel?.kind === kind && sel.name === name;
  const badFams = fams.filter(([, v]) => !v.ok);
  const badProjs = projs.filter(([, v]) => !v.ok);
  const blocked = badFams.length + (r.accepted ? 0 : badProjs.length + (r.invariants?.acceptable ? 0 : failing.length));

  let panel: React.ReactNode = null;
  if (sel?.kind === "family" && r.families?.[sel.name]) {
    const v = r.families[sel.name];
    panel = (
      <ExplanationPanel e={familyExplanation(sel.name, v)} onClose={() => setSel(null)}>
        <Sample title={`First ${v.mismatches.length} of ${v.mismatch_count}`} rows={v.mismatches} />
      </ExplanationPanel>
    );
  } else if (sel?.kind === "projection" && r.projections?.[sel.name]) {
    const v = r.projections[sel.name];
    panel = (
      <ExplanationPanel e={projectionExplanation(sel.name, v)} onClose={() => setSel(null)}>
        <Sample title="Only in the export (first 5)" rows={v.only_in_export ?? []} />
        <Sample title="Only rebuilt here (first 5)" rows={v.only_rebuilt ?? []} />
      </ExplanationPanel>
    );
  } else if (sel?.kind === "invariant") {
    const ex = r.invariants?.examples?.[sel.name] ?? [];
    panel = (
      <ExplanationPanel e={invariantExplanation(sel.name, ex)} onClose={() => setSel(null)}>
        <Sample title="Examples" rows={ex} />
      </ExplanationPanel>
    );
  }

  return (
    <Section title="Reconciliation" right={<span className={`text-sm font-medium ${r.passed ? "text-emerald-700" : "text-rose-700"}`}>
      {r.passed ? "Passed" : "Failed — finalization blocked"}</span>}>
      {r.evidence_only && <p className="text-sm text-slate-600">Evidence only: no projection to rebuild.</p>}
      {r.already_applied && <p className="text-sm text-slate-600">This export was already applied here: nothing changed.</p>}
      {fams.length > 0 && (
        <p className="text-sm text-slate-700">
          {fams.length - badFams.length} of {fams.length} authoritative families equal the archive;{" "}
          {projs.length - badProjs.length} of {projs.length} projections rebuilt as exported
          {r.invariants && <>; invariants {r.invariants.ok ? "hold" : "fail"}</>}.
          {!r.passed && blocked > 0 && <> Click a red item to see what it means and what to do.</>}
        </p>
      )}
      {(badFams.length > 0 || badProjs.length > 0 || failing.length > 0) && (
        <ul className="mt-2 space-y-1 text-sm">
          {badFams.map(([f, v]) => (
            <li key={`f-${f}`}><FailedItem label={`${f}: ${v.mismatch_count} row(s) differ from the archive`}
                                           selected={is("family", f)} onSelect={() => pick("family", f)} /></li>
          ))}
          {badProjs.map(([f, v]) => (
            <li key={`p-${f}`}><FailedItem label={`${f}: rebuilt ${v.rebuilt}, exported ${v.exported}${r.accepted ? " (accepted by decision)" : ""}`}
                                           selected={is("projection", f)} onSelect={() => pick("projection", f)} /></li>
          ))}
          {failing.map((c) => (
            <li key={`i-${c}`}><FailedItem label={`invariant ${c} fails${r.accepted?.invariants.includes(c) ? " (on the archive's data, accepted)" : ""}`}
                                           selected={is("invariant", c)} onSelect={() => pick("invariant", c)} /></li>
          ))}
        </ul>
      )}
      {panel}
      {r.accepted && (
        <p className="mt-2 text-sm text-amber-800">
          Accepted by decision: the projections this release rebuilds{r.accepted.record_fields?.count
            ? `, and ${r.accepted.record_fields.count} record(s) whose ledger-managed fields were rebuilt` : ""}{" "}
          (archive from {r.accepted.archive_release ?? "?"}, here {r.accepted.this_release}).
        </p>
      )}
      <Details label="Show details: signature, every family and projection" className="mt-3">
        <KV rows={[["Report", <Mono>{sha}</Mono>], ["Signed", r.signature ? `${r.signature.algorithm} by ${r.signature.principal}` : "no"],
                   ["Invariants", r.invariants ? `${r.invariants.ok ? "ok" : `failing here (${failing.join(", ")})`}; ${
                     r.invariants.exported_ok === null || r.invariants.exported_ok === undefined ? "not checked" : r.invariants.exported_ok ? "ok" : "failing"} at the source` : undefined],
                   ["Kept", r.rebuild?.relations_kept_without_ledger_facts ? `${r.rebuild.relations_kept_without_ledger_facts} ledger relation(s) of records with no ledger facts, as the source had them` : undefined],
                   ["Rebuild wrote", events.length ? events.map(([k, n]) => `${k} ${n}`).join(", ") : undefined]]} />
        {fams.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Authoritative, row by row</div>
              <table className="mt-1 w-full text-xs"><tbody>
                {fams.map(([f, v]) => (
                  <tr key={f} className="border-t border-slate-100">
                    <td className="py-0.5">{f}</td>
                    <td className="text-right tabular-nums">{v.rows}/{v.expected_rows}</td>
                    <td className="pl-2">{v.ok ? <span className="text-emerald-700">equal</span>
                      : <FailedItem label={`${v.mismatch_count} differ`} selected={is("family", f)} onSelect={() => pick("family", f)} />}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Projections rebuilt here vs exported</div>
              <table className="mt-1 w-full text-xs"><tbody>
                {projs.map(([f, v]) => (
                  <tr key={f} className="border-t border-slate-100">
                    <td className="py-0.5">{f}</td>
                    <td className="text-right tabular-nums">{v.rebuilt}/{v.exported}</td>
                    <td className="pl-2">{v.ok ? <span className="text-emerald-700">equal</span>
                      : <FailedItem label="differ" selected={is("projection", f)} onSelect={() => pick("projection", f)} />}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
          </div>
        )}
        {(r.deferred_references ?? []).length > 0 && (
          <p className="text-xs text-amber-800">{r.deferred_references!.length} reference(s) left unresolved by decision.</p>
        )}
      </Details>
    </Section>
  );
}

function Sample({ title, rows }: { title: string; rows: unknown[] }) {
  if (!rows.length) return null;
  return (
    <div className="mt-2">
      <div className="font-semibold text-slate-700">{title}</div>
      <pre className="mt-0.5 max-h-48 overflow-auto rounded bg-white p-2 text-[11px] text-slate-700">{JSON.stringify(rows, null, 1)}</pre>
    </div>
  );
}

function Evidence({ id }: { id: string }) {
  const [chosen, setFamily] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const fams = useQuery({ queryKey: ["portability-evidence-families", id], queryFn: () => portabilityApi.evidenceFamilies(id) });
  const families = (fams.data ?? []).map((f) => f.family);
  // Start on assets when the archive has them, else on the first family it does have.
  const family = chosen ?? (families.includes("assets") ? "assets" : families[0] ?? null);
  const rows = useQuery({ queryKey: ["portability-evidence", id, family, offset],
                          queryFn: () => portabilityApi.evidence(id, family!, offset, 25), enabled: !!family, retry: false });
  return (
    <Section title="Evidence (read-only, from the archive)">
      <p className="mb-2 text-xs text-slate-500">Browsed only — not searched, indexed or downloadable. Restricted rows appear only for the
        institution's evidence readers; counts are of what you may see. Every read is audited.</p>
      <div className="mb-2 flex items-center gap-2 text-sm">
        <select value={family ?? ""} onChange={(e) => { setFamily(e.target.value); setOffset(0); }} className="rounded border border-slate-300 px-2 py-1">
          {families.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        {rows.data && <span className="text-xs text-slate-500">{rows.data.total === 0 ? "no rows" :
          `${offset + 1}–${Math.min(offset + 25, rows.data.total)} of ${rows.data.total}`}</span>}
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))} className="rounded border px-2 py-0.5 text-xs disabled:opacity-40">‹</button>
        <button type="button" disabled={!rows.data || offset + 25 >= rows.data.total} onClick={() => setOffset(offset + 25)} className="rounded border px-2 py-0.5 text-xs disabled:opacity-40">›</button>
      </div>
      {rows.isError ? <p className="text-sm text-slate-500">{problemText(rows.error)}</p> : (
        <div className="max-h-[28rem] space-y-1 overflow-auto">
          {(rows.data?.rows ?? []).map((r) => (
            <details key={r.key} className="rounded border border-slate-100 px-2 py-1 text-xs">
              <summary className="cursor-pointer font-mono">{String(r.row.name ?? r.row.title ?? r.row.predicate ?? r.key)}</summary>
              <pre className="mt-1 overflow-auto whitespace-pre-wrap">{JSON.stringify(r.row, null, 1)}</pre>
            </details>
          ))}
        </div>
      )}
    </Section>
  );
}

/** Why the dry run is blocked, and what to do about each kind of problem. */
function Blocked({ report }: { report: DryRunReport }) {
  const unresolved = (report.unresolved_reference_count ?? 0) > 0 && report.unresolved_references_outcome !== "defer";
  const byFamily = new Map<string, number>();
  for (const b of report.blocking ?? []) byFamily.set(b.family, (byFamily.get(b.family) ?? 0) + 1);
  const divergent = (report.blocking ?? []).filter((b) => b.reason.startsWith("same key, different content"));
  const other = (report.blocking ?? []).filter((b) => !b.reason.startsWith("same key, different content"));
  return (
    <div className="w-full rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
      <p className="font-medium">The dry run found what stops this import. To go on:</p>
      <ol className="mt-1 list-decimal space-y-1 pl-5">
        {unresolved && (
          <li>
            <b>{report.unresolved_reference_count} reference(s)</b> point to records neither the archive nor this installation
            has. Below, under <i>Decisions for the dry run</i>, set <i>References the archive and this instance both lack</i> to
            <b> leave unresolved and list them in the reconciliation</b>, then <b>Run the dry run with these decisions</b>.
          </li>
        )}
        {divergent.length > 0 && (
          <li>
            <b>{divergent.length} record(s)</b> ({[...new Set(divergent.map((d) => d.family))].join(", ")}) already exist here
            with different content, made here rather than by this archive's origin. ARGUS never overwrites them: change or
            remove them here first, or discard this import. They are listed under <i>Blocking</i> in the dry run below.
          </li>
        )}
        {other.map((b, n) => <li key={n}>{b.family}: {b.reason}</li>)}
        {(report.catalogue_conflicts ?? []).length > 0 && (
          <li><b>{report.catalogue_conflicts!.length} type(s)</b> exist here with a different definition: listed in the dry run below.</li>
        )}
        {!unresolved && byFamily.size === 0 && (report.catalogue_conflicts ?? []).length === 0 && (
          <li>See the dry run below for what it reports.</li>
        )}
      </ol>
    </div>
  );
}
