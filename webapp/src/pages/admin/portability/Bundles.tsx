import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { bundlesApi, problemText, workspacesApi } from "../../../api/client";
import type { BundleApplyBody, BundleReport, BundleSummary } from "../../../api/client";
import { openInWorkspace } from "../../../api/session";
import { useCurrentWorkspaceId } from "../../../api/useCurrentWorkspaceId";
import { ActionButton, bytes, Empty, KV, Section, when } from "./shared";

/** Administration → Portability → Workspace bundles: one workspace as a readable directory (a ZIP), cloned into a
 *  new workspace of any installation with the same packages (docs/workspace-bundle.md). For instance
 *  administrators only — the API enforces it as well. */
export function Bundles() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["bundles"], queryFn: bundlesApi.list });
  const refresh = () => qc.invalidateQueries({ queryKey: ["bundles"] });
  return (
    <div className="space-y-4">
      <div className="rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <p>
          <b>Workspace bundle</b> — one workspace's records, places, floor plans, documents, files, tickets and
          activities as JSON Lines and files, to clone into a <i>new</i> workspace (here or on another installation).
          Secrets are never written; what cannot be carried is listed, never left out silently.
        </p>
        <p className="mt-1">
          <b>Signed portable archive</b> (the other tabs) — the whole installation with its ledger, signed and verified,
          for moving or restoring ARGUS. Use it when the evidence trail must travel too.
        </p>
      </div>
      {list.isError && <p className="text-sm text-rose-700">{problemText(list.error)}</p>}
      <Demos demos={list.data?.demos ?? []} onDone={refresh} />
      <ExportBox onDone={refresh} exports={list.data?.exports ?? []} />
      <ImportBox onDone={refresh} imports={list.data?.imports ?? []} />
    </div>
  );
}

// ------------------------------------------------------------------------------ demos

function Demos({ demos, onDone }: { demos: BundleSummary[]; onDone: () => void }) {
  return (
    <Section title="Demo workspaces">
      {demos.length === 0 ? <Empty>No demo bundles are shipped with this installation.</Empty> : (
        <ul className="space-y-3">
          {demos.map((d) => (
            <li key={d.name} className="rounded border border-slate-200 p-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium text-slate-900">{d.demo?.title ?? d.workspace?.name ?? d.name}</span>
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-900">synthetic</span>
                {d.demo?.organisation && <span className="text-xs text-slate-500">{d.demo.organisation}</span>}
              </div>
              {d.demo?.description && <p className="mt-1 text-sm text-slate-600">{d.demo.description}</p>}
              <Contents s={d} />
              <ApplyForm defaults={{ workspace_id: d.name ?? "", name: d.demo?.title ?? d.workspace?.name ?? "" }}
                         preview={(b) => bundlesApi.previewDemo(d.name!, b)} apply={(b) => bundlesApi.applyDemo(d.name!, b)}
                         onDone={onDone} people={false} />
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// ------------------------------------------------------------------------------ export

function ExportBox({ exports, onDone }: { exports: BundleSummary[]; onDone: () => void }) {
  const workspaces = useQuery({ queryKey: ["me-workspaces"], queryFn: workspacesApi.listMine });
  const [ws, setWs] = useState("");
  const run = useMutation({ mutationFn: () => bundlesApi.exportWorkspace(ws), onSuccess: onDone });
  const download = useMutation({
    mutationFn: async (s: BundleSummary) => {
      const blob = await bundlesApi.download(s.id!);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${s.workspace?.id ?? "workspace"}.argus-workspace.zip`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => bundlesApi.remove("exports", id), onSuccess: onDone });
  return (
    <Section title="Export a workspace">
      <div className="flex flex-wrap items-center gap-2">
        <select value={ws} onChange={(e) => setWs(e.target.value)} aria-label="Workspace to export"
                className="rounded border border-slate-300 px-2 py-1.5 text-sm">
          <option value="">Choose a workspace…</option>
          {(workspaces.data ?? []).filter((w) => !w.is_global).map((w) => <option key={w.id} value={w.id}>{w.name} ({w.id})</option>)}
        </select>
        <ActionButton label="Export" busy={run.isPending} disabled={!ws} onClick={() => run.mutate()} />
      </div>
      {run.isError && <p className="mt-2 text-sm text-rose-700">{problemText(run.error)}</p>}
      {download.isError && <p className="mt-2 text-sm text-rose-700">{problemText(download.error)}</p>}
      <ul className="mt-3 space-y-2">
        {exports.map((e) => (
          <li key={e.id} className="rounded border border-slate-200 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm"><b>{e.workspace?.name}</b> <span className="text-slate-500">· {when(e.created_at)} · {e.created_by}</span></span>
              <span className="flex gap-2">
                <ActionButton label="Download ZIP" busy={download.isPending} onClick={() => download.mutate(e)} />
                <ActionButton label="Delete" danger confirm="Delete this export?" onClick={() => remove.mutate(e.id!)} />
              </span>
            </div>
            <Contents s={e} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

// ------------------------------------------------------------------------------ import

function ImportBox({ imports, onDone }: { imports: BundleSummary[]; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({ mutationFn: (f: File) => bundlesApi.upload(f), onSuccess: onDone });
  const remove = useMutation({ mutationFn: (id: string) => bundlesApi.remove("imports", id), onSuccess: onDone });
  return (
    <Section title="Import a bundle">
      <div className="flex items-center gap-2">
        <input ref={input} type="file" accept=".zip,application/zip" className="text-sm" aria-label="Bundle ZIP"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
        {upload.isPending && <span className="text-sm text-slate-500">Uploading and checking…</span>}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        The ZIP is unpacked safely (no paths outside it, no links, size limits) and its checksums are verified.
        Nothing is imported until you preview and apply.
      </p>
      {upload.isError && <p className="mt-2 text-sm text-rose-700">{problemText(upload.error)}</p>}
      <ul className="mt-3 space-y-2">
        {imports.map((u) => (
          <li key={u.id} className="rounded border border-slate-200 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm"><b>{u.workspace?.name}</b> <span className="text-slate-500">· from ARGUS {u.source?.argus_version ?? "?"} · exported {when(u.created_at)}</span></span>
              <ActionButton label="Discard" danger confirm="Discard this upload?" onClick={() => remove.mutate(u.id!)} />
            </div>
            <Contents s={u} />
            <ApplyForm defaults={{ workspace_id: `${u.workspace?.id ?? "copy"}-copy`, name: `${u.workspace?.name ?? "Copy"} (copy)` }}
                       preview={(b) => bundlesApi.preview(u.id!, b)} apply={(b) => bundlesApi.apply(u.id!, b)} onDone={onDone} people />
          </li>
        ))}
      </ul>
    </Section>
  );
}

// ------------------------------------------------------------------------------ shared

function Contents({ s }: { s: BundleSummary }) {
  const rows = s.rows ?? {};
  const pick = ["assets", "relations", "tickets", "documents", "attachments", "activities", "spatial_features", "floor_plans",
                "indoor_placements", "beam_model_values", "people"];
  const bad = (s.packages_status ?? []).filter((p) => p.status !== "ok");
  return (
    <div className="mt-2 space-y-1 text-xs text-slate-600">
      <p>
        {pick.filter((k) => rows[k]).map((k) => `${rows[k]} ${k.replace(/_/g, " ")}`).join(" · ")}
        {" · "}{s.files} files ({bytes(s.bytes)})
      </p>
      <p>Packages: {(s.packages ?? []).map((p) => `${p.id} ${p.version}`).join(", ")}</p>
      {bad.length > 0 && <p className="text-rose-700">Not installable here: {bad.map((p) => `${p.id} ${p.version} (${p.detail ?? p.status})`).join("; ")}</p>}
      {(s.problems ?? []).length > 0 && <p className="text-rose-700">Problems: {s.problems!.map((p) => `${p.path ?? ""} ${p.detail}`).join("; ")}</p>}
      {s.not_reproduced.length > 0 && (
        <p className="text-amber-800">Not carried: {s.not_reproduced.map((n) => `${n.rows} ${n.table} — ${n.reason}`).join("; ")}</p>
      )}
      {s.missing_files.length > 0 && <p className="text-amber-800">{s.missing_files.length} file(s) were missing at the source.</p>}
      {s.external_config.length > 0 && <p>Set up on the target: {s.external_config.map((x) => x.what).join(", ")}</p>}
    </div>
  );
}

function ApplyForm({ defaults, preview, apply, onDone, people }: {
  defaults: { workspace_id: string; name: string };
  preview: (b: BundleApplyBody) => Promise<BundleReport>;
  apply: (b: BundleApplyBody) => Promise<BundleReport>;
  onDone: () => void;
  people: boolean;
}) {
  const current = useCurrentWorkspaceId();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState<BundleApplyBody>({ ...defaults, people_access: false });
  const [report, setReport] = useState<BundleReport | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const dry = useMutation({ mutationFn: () => preview(body), onSuccess: setReport });
  const run = useMutation({
    mutationFn: () => apply(body),
    onSuccess: (r) => { setReport(r); setApplied(body.workspace_id); onDone(); },
  });
  const change = (c: Partial<BundleApplyBody>) => { setBody((b) => ({ ...b, ...c })); setReport(null); };
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="mt-2 text-sm font-medium text-sky-700 hover:underline">Install as a new workspace…</button>;
  }
  return (
    <div className="mt-3 space-y-2 rounded border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex flex-col">New workspace id
          <input value={body.workspace_id} onChange={(e) => change({ workspace_id: e.target.value })}
                 className="rounded border border-slate-300 px-2 py-1 font-mono" /></label>
        <label className="flex flex-col">Name
          <input value={body.name} onChange={(e) => change({ name: e.target.value })}
                 className="w-72 rounded border border-slate-300 px-2 py-1" /></label>
        {people && (
          <label className="flex items-center gap-2 self-end pb-1">
            <input type="checkbox" checked={body.people_access} onChange={(e) => change({ people_access: e.target.checked })} />
            Give the bundle's people their access
          </label>
        )}
      </div>
      <div className="flex gap-2">
        <ActionButton label="Preview" busy={dry.isPending} onClick={() => dry.mutate()} />
        <ActionButton label="Apply" busy={run.isPending} disabled={!report?.ok || !!applied}
                      title={report?.ok ? undefined : "Preview first: apply is offered when nothing blocks it"}
                      confirm={`Create workspace ${body.workspace_id}?`} onClick={() => run.mutate()} />
        {applied && (
          <button type="button" className="rounded px-3 py-1.5 text-sm font-medium text-sky-700 hover:bg-white"
                  onClick={() => { if (!openInWorkspace(applied, "/", current)) window.location.assign("/"); }}>
            Open {applied}
          </button>
        )}
      </div>
      {(dry.isError || run.isError) && <p className="text-sm text-rose-700">{problemText(dry.error ?? run.error)}</p>}
      {report && <ReportView r={report} applied={!!applied} />}
    </div>
  );
}

function ReportView({ r, applied }: { r: BundleReport; applied: boolean }) {
  const count = (o: Record<string, number>) => Object.entries(o).filter(([, n]) => n).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(" · ");
  return (
    <div className="space-y-2 text-sm">
      <p className={r.ok ? "font-medium text-emerald-700" : "font-medium text-rose-700"}>
        {r.ok ? (applied ? "Imported." : "Ready to apply — nothing blocks it (this was a dry run, nothing was written).")
          : "Blocked — nothing can be written:"}
      </p>
      {r.blockers.length > 0 && <ul className="list-disc pl-5 text-rose-700">{r.blockers.map((b, i) => <li key={i}>{b.detail}</li>)}</ul>}
      <KV rows={[
        ["Adds", count(r.added) || "—"],
        ["Updates", count(r.updated) || undefined],
        ["Identifiers renamed", r.renamed_count ? `${r.renamed_count} (already used here)` : undefined],
        ["People", Object.entries(r.people).map(([k, v]) => `${k} ${v}`).join(" · ")],
        ["Files", count(r.files) || "—"],
      ]} />
      {r.warnings.length > 0 && <ul className="list-disc pl-5 text-amber-800">{r.warnings.map((w, i) => <li key={i}>{w.detail}</li>)}</ul>}
      {r.dependencies.length > 0 && <ul className="list-disc pl-5 text-amber-800">{r.dependencies.map((d, i) => <li key={i}>{d.detail}</li>)}</ul>}
      {r.not_reproduced.length > 0 && (
        <ul className="list-disc pl-5 text-amber-800">{r.not_reproduced.map((n, i) => <li key={i}>Not carried: {n.rows} {n.table} — {n.reason}</li>)}</ul>
      )}
      {r.external_config.length > 0 && (
        <ul className="list-disc pl-5 text-slate-600">{r.external_config.map((x, i) => <li key={i}>Set up here: {x.what} — {x.detail}</li>)}</ul>
      )}
    </div>
  );
}
