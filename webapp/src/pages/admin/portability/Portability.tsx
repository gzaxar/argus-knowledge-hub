import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { portabilityApi, problemText, workspacesApi } from "../../../api/client";
import type { PortabilityConfig } from "../../../api/portabilityTypes";
import { Bundles } from "./Bundles";
import { SchedulesList } from "./Schedules";
import { Setup } from "./Setup";
import { Labels, StateBadge, when } from "./shared";

/** Administration → Portability: portable exports to a Git portability repository, and imports from
 *  one (docs/export-import-design.md). Each export or import has its own page with its steps. */
export function PortabilityPage() {
  const [params, setParams] = useSearchParams();
  const config = useQuery({ queryKey: ["portability-config"], queryFn: portabilityApi.config });
  const wanted = params.get("tab");
  const admin = !!config.data?.is_admin;
  const tab = wanted === "imports" ? "imports" : wanted === "setup" && admin ? "setup"
    : wanted === "bundles" && admin ? "bundles" : "exports";
  const tabs = admin ? (["exports", "imports", "setup", "bundles"] as const) : (["exports", "imports"] as const);

  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Portability</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Signed, verifiable copies of ARGUS — the ledger, records, catalogue and attachments at one watermark —
          published to a Git portability repository, and imported from one through quarantine, a dry run,
          approval and reconciliation. Disaster-recovery backups are separate (Operations).
        </p>
      </div>
      {config.data && <ConfigNotes c={config.data} />}
      {config.isError && <p className="text-sm text-rose-700">{problemText(config.error)}</p>}
      <div className="flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button key={t} type="button" onClick={() => setParams({ tab: t })}
                  className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === t
                    ? "border-slate-900 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
            {t === "exports" ? "Exports" : t === "imports" ? "Imports" : t === "setup" ? "Set-up" : "Workspace bundles"}
          </button>
        ))}
      </div>
      {config.data && (tab === "exports" ? <Exports c={config.data} /> : tab === "imports" ? <Imports c={config.data} />
        : tab === "bundles" ? <Bundles /> : <Setup c={config.data} />)}
    </div>
  );
}

function ConfigNotes({ c }: { c: PortabilityConfig }) {
  const notes = [];
  const where = c.ui_config?.enabled ? "add one under Set-up" : "set in the deployment";
  if (!c.signing.configured) notes.push(`No signing key: exports cannot be generated (${where}).`);
  if (!c.trusted_keys) notes.push(`No trusted keys: imports cannot be verified (${where}).`);
  if (c.repositories.length === 0) notes.push(`No portability repository is registered (${where}).`);
  if (c.artifact_stores.length === 0 && c.repositories.length === 0) notes.push(`No artifact store or repository: an export has nowhere to put its data (${where}).`);
  return (
    <div className="flex flex-wrap items-start gap-4 rounded border border-slate-200 bg-white p-3 text-xs text-slate-600">
      <span>Repositories: <b>{c.repositories.join(", ") || "none"}</b></span>
      <span>Artifact stores: <b>{c.artifact_stores.join(", ") || "none"}</b></span>
      <span>Signing key: <b>{c.signing.configured ? `${c.signing.principal} · ${c.signing.key_id}` : "none"}</b></span>
      <span>Trusted keys: <b>{c.trusted_keys ? "configured" : "none"}</b></span>
      <span title={c.policy.relaxations.join("\n")}>Policy: <b>{c.policy.profile}</b>
        {c.policy.relaxations.length > 0 && ` (${c.policy.relaxations.length} relaxation${c.policy.relaxations.length === 1 ? "" : "s"})`}
        {" · "}retention <b>{c.policy.retention_days} days</b></span>
      {notes.length > 0 && (
        <ul className="w-full list-disc pl-5 text-amber-800">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------ exports

function Exports({ c }: { c: PortabilityConfig }) {
  const list = useQuery({ queryKey: ["portability-exports"], queryFn: portabilityApi.exports });
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button type="button" onClick={() => setOpen((v) => !v)}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
          {open ? "Close" : "New export"}
        </button>
      </div>
      {open && <NewExport c={c} exports={list.data ?? []} />}
      {c.is_admin && <SchedulesList />}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Export</th><th className="px-3 py-2">Scope</th><th className="px-3 py-2">State</th>
              <th className="px-3 py-2">Labels</th><th className="px-3 py-2">Requested</th></tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((e) => (
              <tr key={e.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-2">
                  <Link to={`/admin/portability/exports/${e.id}`} className="font-mono text-xs text-indigo-700 hover:underline">{e.id}</Link>
                  <div className="text-xs text-slate-500">{e.mode}{e.risk === "high" ? " · high risk" : ""}</div>
                </td>
                <td className="px-3 py-2 text-xs">{e.mode === "full" ? "every workspace" : e.workspaces.join(", ")}
                  {e.git.tag && <div className="font-mono text-[11px] text-slate-500">{e.git.tag}</div>}</td>
                <td className="px-3 py-2"><StateBadge state={e.state} /></td>
                <td className="px-3 py-2"><Labels labels={e.labels} compact /></td>
                <td className="px-3 py-2 text-xs text-slate-500">{e.requested_by}<div>{when(e.created_at)}</div></td>
              </tr>
            ))}
            {list.data?.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-500">No export yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {list.isError && <p className="text-sm text-rose-700">{problemText(list.error)}</p>}
    </div>
  );
}

function NewExport({ c, exports }: { c: PortabilityConfig; exports: { id: string; state: string; git: { tag?: string } }[] }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const workspaces = useQuery({ queryKey: ["me-workspaces"], queryFn: workspacesApi.listMine });
  const [mode, setMode] = useState("workspace");
  const [chosen, setChosen] = useState<string[]>([]);
  const [classes, setClasses] = useState<string[]>([]);
  const [repository, setRepository] = useState(c.repositories[0] ?? "");
  // With no store of its own, an export keeps its data in the repository it is published to.
  const inRepo = c.repository_store ?? "@repository";
  const [store, setStore] = useState(c.artifact_stores[0] ?? (c.repositories[0] ? inRepo : ""));
  const [base, setBase] = useState("");
  const [profile, setProfile] = useState(c.default_identity_profile);
  const [purpose, setPurpose] = useState("");
  const [recipients, setRecipients] = useState<string[]>([]);
  const choosePurpose = (p: string) => {
    setPurpose(p);
    const implied = c.purpose_profiles[p];
    if (implied && (implied !== "full_identity" || c.is_admin)) setProfile(implied);
  };
  const available = c.recipients[repository] ?? [];
  const approvedClasses = c.restricted_destinations[repository] ?? [];
  const canEncrypt = c.encryption_recipients.includes(repository);
  const published = exports.filter((e) => e.state === "published");
  const create = useMutation({
    mutationFn: () => portabilityApi.createExport({
      mode, workspaces: mode === "workspace" || mode === "evidence-only" ? chosen : [],
      classifications: classes, repository: repository || null, artifact_store: store || null,
      base_export_id: mode === "incremental" ? base : null, identity_profile: profile,
      purpose: purpose || null, recipients: classes.length ? recipients : [],
    }),
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["portability-exports"] });
      navigate(`/admin/portability/exports/${e.id}`);
    },
  });
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const needsWorkspaces = mode === "workspace" || mode === "evidence-only";
  const highRisk = mode === "full" || mode === "evidence-only" || classes.length > 0 ||
    (profile === "full_identity" && c.policy.full_identity_high_risk);
  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm">
          <span className="block text-xs font-medium text-slate-600">What</span>
          <select value={mode} onChange={(e) => setMode(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
            <option value="workspace">Selected workspaces (a selective package)</option>
            {c.is_admin && <option value="full">Everything (a full archive)</option>}
            <option value="incremental">An increment of a published export</option>
            <option value="evidence-only">Evidence only (read-only copy)</option>
          </select>
        </label>
        {mode === "incremental" ? (
          <label className="text-sm">
            <span className="block text-xs font-medium text-slate-600">Base export (published)</span>
            <select value={base} onChange={(e) => setBase(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
              <option value="">Choose…</option>
              {published.map((e) => <option key={e.id} value={e.id}>{e.id} · {e.git.tag}</option>)}
            </select>
          </label>
        ) : <div />}
        <label className="text-sm">
          <span className="block text-xs font-medium text-slate-600">Git portability repository</span>
          <select value={repository} onChange={(e) => {
                    setRepository(e.target.value); setClasses([]); setRecipients([]);
                    if (!e.target.value && store === inRepo) setStore(c.artifact_stores[0] ?? "");
                  }}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
            <option value="">None (generate only)</option>
            {c.repositories.map((r) => (
              <option key={r} value={r}>{r}{c.restricted_destinations[r] ? ` — approved for ${c.restricted_destinations[r].join(", ")}` : ""}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-xs font-medium text-slate-600">Where the data goes (records, attachments)</span>
          <select value={store} onChange={(e) => setStore(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
            {!store && <option value="">Choose…</option>}
            {repository && <option value={inRepo}>In the repository, with the archive</option>}
            {c.artifact_stores.map((r) => <option key={r} value={r}>artifact store {r}</option>)}
          </select>
          <span className="mt-1 block text-xs text-slate-500">
            {store === inRepo ? "Committed with the archive: the importing installation needs only the repository. Each file must stay under the provider's size limit (100 MB on GitHub)."
              : "A separate store: the importing installation needs a copy of it, under the same name."}
          </span>
        </label>
      </div>
      {needsWorkspaces && (
        <div>
          <span className="block text-xs font-medium text-slate-600">Workspaces</span>
          <div className="mt-1 flex max-h-48 flex-wrap gap-2 overflow-auto rounded border border-slate-200 p-2">
            {(workspaces.data ?? []).map((w) => (
              <label key={w.id} className={`flex cursor-pointer items-center gap-1 rounded border px-2 py-1 text-xs ${chosen.includes(w.id)
                ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 text-slate-700"}`}>
                <input type="checkbox" className="hidden" checked={chosen.includes(w.id)} onChange={() => setChosen(toggle(chosen, w.id))} />
                {w.name} <span className="opacity-60">({w.id})</span>
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-slate-500">Dependencies outside these workspaces are listed next, each needing an outcome.</p>
        </div>
      )}
      {mode !== "incremental" && (
        <label className="block text-sm">
          <span className="block text-xs font-medium text-slate-600">Purpose</span>
          <select value={purpose} onChange={(e) => choosePurpose(e.target.value)} className="mt-1 w-full max-w-md rounded border border-slate-300 px-2 py-1.5">
            <option value="">Not stated</option>
            {c.purposes.map((p) => <option key={p} value={p}>{PURPOSE_HELP[p] ?? p}</option>)}
          </select>
          <span className="mt-1 block text-xs text-slate-500">Backup, restore and migration between trusted ARGUS installations keep
            full identities; analysis and external sharing are pseudonymized.</span>
        </label>
      )}
      {mode !== "incremental" && (
        <label className="block text-sm">
          <span className="block text-xs font-medium text-slate-600">People in the archive (identity profile)</span>
          <select value={profile} onChange={(e) => setProfile(e.target.value)} className="mt-1 w-full max-w-md rounded border border-slate-300 px-2 py-1.5">
            {c.identity_profiles.map((p) => (
              <option key={p} value={p} disabled={p === "full_identity" && !c.is_admin}>
                {PROFILE_HELP[p] ?? p}{p === "full_identity" && c.policy.full_identity_high_risk ? " (high risk)" : ""}
              </option>))}
          </select>
        </label>
      )}
      {mode !== "incremental" && (
        <div>
          <span className="block text-xs font-medium text-slate-600">Restricted classes to include</span>
          <div className="mt-1 flex flex-wrap gap-3 text-sm">
            {c.restricted_classes.map((k) => {
              const allowed = c.is_admin && approvedClasses.includes(k) && canEncrypt;
              return (
                <label key={k} className={`flex items-center gap-1 ${allowed ? "" : "text-slate-400"}`}
                       title={allowed ? "" : "Only to a destination approved for this class, with encryption recipients"}>
                  <input type="checkbox" checked={classes.includes(k)} onChange={() => setClasses(toggle(classes, k))} disabled={!allowed} />
                  {k.replace(/_/g, " ")}
                </label>
              );
            })}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Records of the classes not ticked are left out with everything that names them. A restricted class can be
            included only towards a destination approved for it, and the export is then encrypted for that
            destination's recipients. Unencrypted restricted exports are not available.
          </p>
          {classes.length > 0 && (
            <div className="mt-2">
              <span className="block text-xs font-medium text-slate-600">Approved recipients who may decrypt it</span>
              <div className="mt-1 flex flex-wrap gap-3 text-sm">
                {available.map((r) => (
                  <label key={r} className="flex items-center gap-1">
                    <input type="checkbox" checked={recipients.includes(r)} onChange={() => setRecipients(toggle(recipients, r))} />
                    {r}
                  </label>
                ))}
                {available.length === 0 && <span className="text-xs text-amber-800">No recipients are configured for {repository}.</span>}
              </div>
            </div>
          )}
        </div>
      )}
      {highRisk && (
        <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-900">
          High-risk export: {c.policy.separation_of_duties ? "another administrator must approve it" : "it needs an administrator's approval with a recent sign-in"}.
        </p>
      )}
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => create.mutate()}
                disabled={create.isPending || (needsWorkspaces && chosen.length === 0) || (mode === "incremental" && !base) ||
                          (classes.length > 0 && recipients.length === 0)}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300">
          {create.isPending ? "Analysing…" : "Request and analyse"}
        </button>
        {create.isError && <span className="text-sm text-rose-700">{problemText(create.error)}</span>}
      </div>
    </div>
  );
}

const PURPOSE_HELP: Record<string, string> = {
  backup: "Backup — full identities",
  restore: "Restore — full identities",
  migration: "Migration to another trusted ARGUS — full identities",
  analysis: "Analysis — pseudonymized",
  external_sharing: "External sharing — pseudonymized",
  evidence: "Evidence — institutional references",
};

const PROFILE_HELP: Record<string, string> = {
  institutional_reference: "Institutional reference (default): user ids and subjects; no e-mail, DN or names",
  pseudonymized: "Pseudonymized: an institutional pseudonym per person",
  anonymous_historical_actor: "Anonymous: actions grouped by actor, nothing links to a person",
  full_identity: "Full identity: e-mail, names, directory DN",
};

// ------------------------------------------------------------------------------ imports

function Imports({ c }: { c: PortabilityConfig }) {
  const list = useQuery({ queryKey: ["portability-imports"], queryFn: portabilityApi.imports, enabled: c.is_admin });
  const [open, setOpen] = useState(false);
  if (!c.is_admin) return <p className="text-sm text-slate-500">Imports are for instance administrators.</p>;
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button type="button" onClick={() => setOpen((v) => !v)}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">
          {open ? "Close" : "New import"}
        </button>
      </div>
      {open && <NewImport c={c} />}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="px-3 py-2">Import</th><th className="px-3 py-2">Source</th><th className="px-3 py-2">State</th>
              <th className="px-3 py-2">Labels</th><th className="px-3 py-2">Requested</th></tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((i) => (
              <tr key={i.id} className="border-t border-slate-100 align-top">
                <td className="px-3 py-2">
                  <Link to={`/admin/portability/imports/${i.id}`} className="font-mono text-xs text-indigo-700 hover:underline">{i.id}</Link>
                  <div className="text-xs text-slate-500">{i.mode}</div>
                </td>
                <td className="px-3 py-2 text-xs">{i.source.repository ? `${i.source.repository}` : "uploaded"}
                  {i.source.ref && <div className="font-mono text-[11px] text-slate-500">{i.source.ref}</div>}
                  {i.manifest && <div className="text-slate-500">export {i.manifest.export_id}</div>}</td>
                <td className="px-3 py-2"><StateBadge state={i.state} /></td>
                <td className="px-3 py-2">{i.manifest ? <Labels labels={i.labels} compact /> : <span className="text-xs text-slate-400">not verified</span>}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{i.requested_by}<div>{when(i.created_at)}</div></td>
              </tr>
            ))}
            {list.data?.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-500">No import yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const MODE_HELP: Record<string, string> = {
  clone: "Keep every uid and its history; this instance keeps its own identity.",
  merge: "Into this instance alongside its own work, in new workspaces or this origin's own. Never replaces anything.",
  restore: "Rebuild the exporting instance here: an empty instance and a full-identity archive; this instance takes the archive's identity.",
  selective: "Only the workspaces you choose (in the dry run's decisions), into an instance that has other work.",
  evidence: "Keep a verified, read-only copy to consult. Nothing is loaded into active data.",
};

function NewImport({ c }: { c: PortabilityConfig }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [mode, setMode] = useState("clone");
  const [source, setSource] = useState<"git" | "upload">(c.repositories.length ? "git" : "upload");
  const [repository, setRepository] = useState(c.repositories[0] ?? "");
  const [ref, setRef] = useState("");
  const [expected, setExpected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const create = useMutation({
    mutationFn: async () => {
      const imp = await portabilityApi.createImport({
        mode, repository: source === "git" ? repository : null, ref: source === "git" ? ref.trim() : null,
        expected_commit: source === "git" && expected.trim() ? expected.trim() : null,
      });
      if (source === "upload" && file) await portabilityApi.upload(imp.id, file);
      return imp;
    },
    onSuccess: (i) => {
      void qc.invalidateQueries({ queryKey: ["portability-imports"] });
      navigate(`/admin/portability/imports/${i.id}`);
    },
  });
  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm">
          <span className="block text-xs font-medium text-slate-600">Mode</span>
          <select value={mode} onChange={(e) => setMode(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
            {c.import_modes.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <span className="mt-1 block text-xs text-slate-500">{MODE_HELP[mode]}</span>
        </label>
        <div className="text-sm">
          <span className="block text-xs font-medium text-slate-600">From</span>
          <div className="mt-1 flex gap-3">
            <label className="flex items-center gap-1"><input type="radio" checked={source === "git"} onChange={() => setSource("git")} /> a signed tag in a portability repository</label>
            <label className="flex items-center gap-1"><input type="radio" checked={source === "upload"} onChange={() => setSource("upload")} /> an uploaded checkpoint</label>
          </div>
        </div>
      </div>
      {source === "git" ? (
        <div className="grid gap-4 md:grid-cols-3">
          <label className="text-sm">
            <span className="block text-xs font-medium text-slate-600">Repository</span>
            <select value={repository} onChange={(e) => setRepository(e.target.value)} className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5">
              {c.repositories.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="text-sm">
            <span className="block text-xs font-medium text-slate-600">Signed export tag, or a signed commit hash</span>
            <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="export/full/2026-10-03@cp184-1a2b3c4d5e6f"
                   className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-xs" />
            <span className="mt-1 block text-xs text-slate-500">Never a branch: a branch head moves.</span>
          </label>
          <label className="text-sm">
            <span className="block text-xs font-medium text-slate-600">Expected commit (optional)</span>
            <input value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="40 hex digits from the reviewed release"
                   className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-xs" />
          </label>
        </div>
      ) : (
        <label className="block text-sm">
          <span className="block text-xs font-medium text-slate-600">Checkpoint (a .tar of the checkpoint's files, as downloaded from an export)</span>
          <input type="file" accept=".tar,application/x-tar" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block text-sm" />
          <span className="mt-1 block text-xs text-slate-500">Its signature is verified against the trusted keys, as for Git.</span>
        </label>
      )}
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => create.mutate()}
                disabled={create.isPending || (source === "git" ? !repository || !ref.trim() : !file)}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300">
          {create.isPending ? "Registering…" : "Register import"}
        </button>
        {create.isError && <span className="text-sm text-rose-700">{problemText(create.error)}</span>}
      </div>
    </div>
  );
}
