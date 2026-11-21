import { useEffect, useState } from "react";
import { portabilityApi, problemText } from "../../../api/client";
import type { ArchiveLabels, PortabilityError, PortabilityJob, PortabilityPolicy, UninspectedBlob }
  from "../../../api/portabilityTypes";

/** Pieces shared by the export and import pages (docs/export-import-design.md §17). */

export const EXPORT_STEPS = ["requested", "analysing", "awaiting_approval", "approved", "generating", "verifying",
  "ready_to_publish", "publishing", "published"];
export const IMPORT_STEPS = ["created", "fetching", "quarantined", "verifying", "dry_run_ready", "awaiting_approval",
  "approved", "importing", "rebuilding", "reconciling", "ready_to_finalize", "finalized"];
const BAD = new Set(["failed", "invalid", "revoked", "expired", "discarded"]);

export function human(state: string): string {
  return state.replace(/_/g, " ").replace("publish git", "publish to Git");
}

export function StateBadge({ state }: { state: string }) {
  const tone = BAD.has(state) ? "bg-rose-100 text-rose-800"
    : state === "published" || state === "finalized" ? "bg-emerald-100 text-emerald-800"
      : state.startsWith("awaiting") || state === "dry_run_ready" || state === "ready_to_publish" ||
        state === "ready_to_finalize" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${tone}`}>{human(state)}</span>;
}

const LABELS: [keyof ArchiveLabels, string, string][] = [
  ["complete", "complete", "partial"],
  ["incremental", "incremental", "checkpoint"],
  ["signed", "signed", "unsigned"],
  ["encrypted", "encrypted", "not encrypted"],
  ["git_published", "Git-published", "not in Git"],
  ["artifact_complete", "artifact-complete", "artifacts not checked"],
  ["verified", "verified", "not verified"],
  ["restorable", "restorable", "not restorable"],
  ["evidence_only", "evidence only", ""],
];

/** Every label a person must see about an archive, the absent ones too. */
export function Labels({ labels, compact }: { labels: ArchiveLabels; compact?: boolean }) {
  return (
    <span className="flex flex-wrap gap-1">
      {LABELS.map(([key, yes, no]) => {
        const on = labels[key];
        if (compact && !on) return null;
        if (!on && !no) return null;
        if (key === "complete" && !on && labels.selective) return null;   // "selective" says it, once
        const good = on && key !== "evidence_only" && key !== "incremental";
        return (
          <span key={key} className={`rounded border px-1.5 py-0.5 text-[11px] ${on ? good
            ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-sky-300 bg-sky-50 text-sky-800"
            : "border-slate-200 bg-white text-slate-400"}`}>
            {on ? yes : no}
          </span>
        );
      })}
      {labels.full && <span className="rounded border border-sky-300 bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-800">full</span>}
      {labels.selective && <span className="rounded border border-sky-300 bg-sky-50 px-1.5 py-0.5 text-[11px] text-sky-800">selective</span>}
      {labels.uninspected_content && (
        <span className="rounded border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-900"
              title="Some files travelled without content inspection (opaque or unreadable)">uninspected content</span>
      )}
    </span>
  );
}

/** Where a lifecycle is, as a row of steps. */
export function Steps({ steps, state }: { steps: string[]; state: string }) {
  const at = steps.indexOf(state);
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]">
      {steps.map((s, i) => (
        <li key={s} className="flex items-center gap-1">
          <span className={`rounded-full px-2 py-0.5 ${i < at || (i === at && (s === "published" || s === "finalized"))
            ? "bg-emerald-600 text-white" : i === at ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500"}`}>
            {human(s)}
          </span>
          {i < steps.length - 1 && <span className="text-slate-300">›</span>}
        </li>
      ))}
      {at < 0 && <li className="ml-2"><StateBadge state={state} /></li>}
    </ol>
  );
}

export function ErrorBox({ error }: { error: PortabilityError | string | null | undefined }) {
  if (!error) return null;
  const e = typeof error === "string" ? { error, code: "" } : error;
  const extra = typeof e === "object" ? Object.entries(e).filter(([k]) => !["error", "code"].includes(k)) : [];
  return (
    <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
      <div className="font-medium">{e.error}{e.code ? <span className="ml-2 font-mono text-xs">{e.code}</span> : null}</div>
      {extra.length > 0 && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(Object.fromEntries(extra), null, 1)}</pre>
      )}
    </div>
  );
}

export function Section({ title, children, right, id }: { title: string; children: React.ReactNode; right?: React.ReactNode;
                                                          id?: string }) {
  return (
    <section id={id} className="scroll-mt-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

export function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="min-w-0 break-all text-slate-900">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, short }: { children: string | null | undefined; short?: boolean }) {
  if (!children) return <span className="text-slate-400">—</span>;
  return <code className="font-mono text-xs" title={children}>{short ? children.slice(0, 12) : children}</code>;
}

/** A button for an action that changes state, with an inline confirmation instead of a dialog. */
export function ActionButton({ label, onClick, busy, disabled, confirm, danger, title }: {
  label: string; onClick: () => void; busy?: boolean; disabled?: boolean; confirm?: string; danger?: boolean;
  title?: string;
}) {
  const [asking, setAsking] = useState(false);
  const base = danger ? "bg-rose-600 hover:bg-rose-700" : "bg-slate-900 hover:bg-slate-800";
  if (asking) {
    return (
      <span className="flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
        {confirm}
        <button type="button" className={`rounded px-2 py-1 text-white ${base}`}
                onClick={() => { setAsking(false); onClick(); }}>Yes, {label.charAt(0).toLowerCase() + label.slice(1)}</button>
        <button type="button" className="rounded px-2 py-1 text-slate-600 hover:bg-white" onClick={() => setAsking(false)}>Cancel</button>
      </span>
    );
  }
  return (
    <button type="button" disabled={disabled || busy} title={title}
            onClick={() => (confirm ? setAsking(true) : onClick())}
            className={`rounded px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-slate-300 ${base}`}>
      {busy ? `${label}…` : label}
    </button>
  );
}

export function bytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-slate-500">{children}</p>;
}


/** Files that travel, or travelled, without content inspection: always listed, never hidden. */
export function UninspectedList({ items, total }: { items: UninspectedBlob[]; total?: number }) {
  if (!items.length) return null;
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <div className="font-medium">
        {total ?? items.length} file(s) not inspected: their content could not be read, so secrets or classified
        material in them would not have been detected.
      </div>
      <ul className="mt-2 max-h-48 space-y-0.5 overflow-auto text-xs">
        {items.map((u) => (
          <li key={`${u.where}-${u.sha256}`} className="flex flex-wrap gap-2">
            <span className="font-mono">{u.where}</span>
            <span>{u.status}{u.reason ? ` — ${u.reason}` : ""}</span>
            <span className="text-amber-700">{u.by === "policy" ? "allowed by policy" : "approved by decision"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const JOB_TONE: Record<PortabilityJob["state"], string> = {
  queued: "bg-slate-100 text-slate-700", running: "bg-sky-100 text-sky-800",
  completed: "bg-emerald-100 text-emerald-800", failed: "bg-rose-100 text-rose-800",
};

/** Polls a background job until it ends, then tells the page to reload. */
export function useJob(onDone: () => void, subject?: string) {
  const [job, setJob] = useState<PortabilityJob | null>(null);
  const [pollError, setPollError] = useState(false);
  // Reattach on navigation or refresh, including a job that finished before this page loaded.
  useEffect(() => {
    if (!subject) return;
    let live = true;
    setJob(null);
    let timer: number;
    const discover = async () => {
      try {
        const items = await portabilityApi.jobs(subject);
        if (!live) return;
        setPollError(false);
        const latest = items.find((j) => j.state === "queued" || j.state === "running") ?? items[0];
        if (latest) setJob(latest);
        onDone();
      } catch {
        if (!live) return;
        setPollError(true);
        timer = window.setTimeout(discover, 2000);
      }
    };
    void discover();
    return () => { live = false; window.clearTimeout(timer); };
  }, [subject, onDone]);
  useEffect(() => {
    if (!job || job.state === "completed" || job.state === "failed") return;
    let live = true;
    let timer: number;
    const poll = async () => {
      try {
        const next = await portabilityApi.job(job.id);
        if (!live) return;
        setPollError(false);
        setJob(next);
        if (next.state === "completed" || next.state === "failed") { onDone(); return; }
      } catch {
        if (!live) return;
        setPollError(true);
      }
      // A failed request must also schedule another poll.
      if (live) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 1000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [job?.id, job?.state, onDone]);
  return { job, setJob, pollError, running: !!job && (job.state === "queued" || job.state === "running") };
}

const STEP_WORDS: Record<string, string> = {
  "fetch-git": "Fetching from Git into quarantine", verify: "Verifying the signature, checksums and every data file",
  "dry-run": "Dry run: checking every row of the archive against this installation",
  execute: "Loading into staging, then rebuilding and reconciling there",
  resume: "Loading into staging, then rebuilding and reconciling there",
  finalize: "Moving it into the real database, then rebuilding and reconciling", generate: "Generating the archive",
  "publish-git": "Committing and pushing to Git", analyse: "Analysing content for export",
};

/** A running job, as it goes: what it is doing, how far it has got, and for how long. */
export function JobProgress({ job, pollError = false }: { job: PortabilityJob; pollError?: boolean }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  const p = job.metrics?.progress;
  const since = Math.max(0, Math.round((now - new Date(job.started_at ?? job.created_at ?? now).getTime()) / 1000));
  const elapsed = since >= 60 ? `${Math.floor(since / 60)} min ${since % 60} s` : `${since} s`;
  return (
    <div role="status" aria-live="polite" className="w-full space-y-1 rounded border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{STEP_WORDS[job.action] ?? job.action}{job.state === "queued" ? " — queued" : "…"}</span>
        <span className="text-xs">{elapsed}</span>
      </div>
      {p && (
        <>
          <div role="progressbar" aria-label={p.stage} aria-valuemin={0} aria-valuemax={100}
               aria-valuenow={p.percent == null ? undefined : Math.max(0, Math.min(100, p.percent))}
               className="h-2 w-full overflow-hidden rounded bg-indigo-100">
            <div className={`h-2 rounded bg-indigo-500 transition-all ${p.percent == null ? "w-1/3 animate-pulse" : ""}`}
                 style={p.percent != null ? { width: `${Math.max(0, Math.min(100, p.percent))}%` } : undefined} />
          </div>
          <div className="flex flex-wrap justify-between gap-2 text-xs">
            <span>{p.stage.replace(/_/g, " ")}</span>
            {p.done != null && (
              <span>{p.done.toLocaleString()}{p.total != null ? ` of ${p.total.toLocaleString()}` : " processed"}
                {p.percent != null ? ` · ${p.percent}%` : ""}</span>
            )}
          </div>
        </>
      )}
      {!p && <div role="progressbar" aria-label="Waiting for progress" className="h-2 w-full overflow-hidden rounded bg-indigo-100">
        <div className="h-2 w-1/3 animate-pulse rounded bg-indigo-300" />
      </div>}
      {pollError && <p className="text-xs text-amber-800">Connection interrupted. Retrying progress updates…</p>}
      <p className="text-xs text-indigo-700">You can leave this page: the step goes on, and its result shows when you come back.</p>
    </div>
  );
}

/** The jobs of an export or import: queued, running, completed or failed, refreshed by polling. */
export function JobsPanel({ subject, current }: { subject: string; current: PortabilityJob | null }) {
  const [jobs, setJobs] = useState<PortabilityJob[]>([]);
  useEffect(() => {
    let live = true;
    portabilityApi.jobs(subject).then((j) => live && setJobs(j)).catch(() => undefined);
    return () => { live = false; };
  }, [subject, current?.state, current?.id]);
  if (!jobs.length) return null;
  return (
    <Section title="Jobs">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr><th className="py-1">Step</th><th>State</th><th>By</th><th>Started</th><th>Duration</th><th /></tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className="border-t border-slate-100 align-top">
              <td className="py-1">{human(j.action)}</td>
              <td><span className={`rounded px-2 py-0.5 text-xs ${JOB_TONE[j.state]}`}>{j.state}</span></td>
              <td className="text-xs">{j.requested_by}</td>
              <td className="text-xs">{when(j.started_at ?? j.created_at)}</td>
              <td className="text-xs">{j.metrics?.seconds !== undefined ? `${j.metrics.seconds} s` : "—"}</td>
              <td className="text-xs text-rose-700">{j.error?.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}

/** Suspend (or resume) automatic deletion. Administrators only; audited. */
export function LegalHold({ kind, id, on, reason, purgedAt, onChange }: {
  kind: "exports" | "imports"; id: string; on: boolean; reason: string | null; purgedAt: string | null;
  onChange: () => void;
}) {
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const act = async (next: boolean) => {
    setBusy(true); setErr(null);
    try { await portabilityApi.legalHold(kind, id, next, text); setText(""); onChange(); }
    catch (e) { setErr(problemText(e)); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-2 text-sm">
      {purgedAt && <p className="text-slate-600">Local files deleted by retention on {when(purgedAt)}; the record and its
        audit remain.</p>}
      {on ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800">legal hold</span>
          <span className="text-slate-700">{reason}</span>
          <ActionButton label="Release hold" busy={busy} onClick={() => act(false)}
                        confirm="Automatic deletion will apply again." />
        </div>
      ) : !purgedAt && (
        <div className="flex flex-wrap items-center gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Reason (e.g. audit reference)"
                 className="min-w-64 rounded border border-slate-300 px-2 py-1 text-sm" />
          <ActionButton label="Place legal hold" busy={busy} disabled={!text.trim()} onClick={() => act(true)} />
        </div>
      )}
      {err && <ErrorBox error={err} />}
    </div>
  );
}

/** The policy in force, with every relaxed choice spelled out. */
export function PolicySummary({ policy }: { policy: PortabilityPolicy }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${policy.profile === "strict"
          ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-900"}`}>{policy.profile} policy</span>
        <span className="text-slate-600">retention {policy.retention_days} days · readers {policy.blob_readers.join(", ")}</span>
      </div>
      {policy.relaxations.length > 0 && (
        <div className="text-xs text-slate-600">
          Relaxed compared with the strict policy:
          <ul className="mt-1 flex flex-wrap gap-1">
            {policy.relaxations.map((r) => (
              <li key={r} className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-mono text-[11px] text-amber-900">{r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Secondary information, folded away until asked for. */
export function Details({ label = "Show details", children, className = "" }: { label?: string; children: React.ReactNode;
                                                                                 className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={className}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
              className="text-xs font-medium text-slate-600 hover:text-slate-900">
        {open ? "▾ Hide details" : `▸ ${label}`}
      </button>
      {open && <div className="mt-3 space-y-4">{children}</div>}
    </div>
  );
}

/** A failed item: red, and clicking it says what it means (explain.ts). */
export function FailedItem({ label, selected, onSelect }: { label: React.ReactNode; selected: boolean; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected} title="What does this mean?"
            className={`text-rose-700 underline decoration-dotted underline-offset-2 hover:text-rose-900 ${selected ? "font-semibold" : ""}`}>
      {label} <span aria-hidden>ⓘ</span>
    </button>
  );
}

export function ExplanationPanel({ e, onClose, children }: {
  e: import("./explain").Explanation; onClose: () => void; children?: React.ReactNode }) {
  return (
    <div role="region" aria-label={e.title} className="mt-3 rounded border border-rose-200 bg-rose-50 p-3 text-xs text-slate-800">
      <div className="flex items-start justify-between gap-2">
        <div className="font-semibold text-rose-900">{e.title}</div>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-800" aria-label="Close">✕</button>
      </div>
      <p className="mt-1">{e.what}</p>
      {e.why && e.why.length > 0 && (
        <>
          <div className="mt-2 font-semibold text-slate-700">Why it can happen</div>
          <ul className="mt-0.5 list-disc pl-5">{e.why.map((w, k) => <li key={k}>{w}</li>)}</ul>
        </>
      )}
      {e.todo && e.todo.length > 0 && (
        <>
          <div className="mt-2 font-semibold text-slate-700">What to do</div>
          <ul className="mt-0.5 list-disc pl-5">{e.todo.map((w, k) => <li key={k}>{w}</li>)}</ul>
        </>
      )}
      {children}
    </div>
  );
}
