import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, askEvalApi, type AskEvalRow, type AskEvalRun } from "../../api/client";

const pct = (v?: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const sec = (v?: number | null) => (v == null ? "—" : v.toFixed(1));

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : "It did not work.";
}

/** The release table: one row per model, every number traceable to the cases below it. */
export function EvalTable({ rows }: { rows: AskEvalRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-slate-200 text-left text-slate-500">
            {["Model", "Runs", "Pass", "Facts", "Evidence", "Citation support", "Abstention", "Critical", "Incomplete",
              "p50 s", "p95 s", "Tokens/case"].map((h) => <th key={h} className="px-2 py-1 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => r.status ? (
            <tr key={r.model} className="border-b border-slate-100">
              <td className="px-2 py-1 font-medium">{r.model}</td>
              <td colSpan={11} className="px-2 py-1 text-amber-700"><b>{r.status}</b>{r.reason ? `: ${r.reason}` : ""}</td>
            </tr>
          ) : (
            <tr key={r.model} className="border-b border-slate-100">
              <td className="px-2 py-1 font-medium">{r.model}{r.served_models?.length ? <span className="block text-[10px] text-slate-400">{r.served_models.join(", ")}</span> : null}</td>
              <td className="px-2 py-1">{r.runs}{r.skipped ? ` (+${r.skipped} skipped)` : ""}</td>
              <td className="px-2 py-1">{pct(r.pass_rate)}</td>
              <td className="px-2 py-1">{pct(r.factual_pass_rate)}</td>
              <td className="px-2 py-1">{pct(r.evidence_retrieval)}</td>
              <td className="px-2 py-1">{pct(r.citation_support)}</td>
              <td className="px-2 py-1">{pct(r.correct_abstention)}</td>
              <td className={`px-2 py-1 ${r.critical_failures ? "font-semibold text-red-700" : ""}`}>{r.critical_failures}</td>
              <td className="px-2 py-1">{r.completion_failures}</td>
              <td className="px-2 py-1">{sec(r.latency_p50_s)}</td>
              <td className="px-2 py-1">{sec(r.latency_p95_s)}</td>
              <td className="px-2 py-1">{r.tokens_mean ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Status({ run }: { run: AskEvalRun | { status: string } }) {
  if (!("id" in run)) return <span className="text-slate-500">not run</span>;
  const p = run.progress;
  return (
    <span>
      <span className={run.status === "finished" ? "text-emerald-700" : run.status === "failed" ? "text-red-700" : "text-amber-700"}>
        {run.status}
      </span>
      {run.status === "running" && p?.total ? ` ${p.done ?? 0}/${p.total}` : ""}
    </span>
  );
}

/** One run's drill-down: each case, each model's answer, lookups and the reasons for its grade. */
function RunDetail({ id }: { id: string }) {
  const run = useQuery({ queryKey: ["ask-eval-run", id], queryFn: () => askEvalApi.run(id),
                         refetchInterval: (q) => (["queued", "running"].includes(q.state.data?.status ?? "") ? 4000 : false) });
  const [busy, setBusy] = useState("");
  if (!run.data) return <p className="text-sm text-slate-500">Loading the run…</p>;
  const r = run.data;
  const save = async (fmt: "json" | "md" | "html", isPublic: boolean) => {
    setBusy(fmt);
    try {
      const url = await askEvalApi.download(r.id, fmt, isPublic);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ask-eval-${r.release}-${r.id}${isPublic ? "-public" : ""}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setBusy("");
    }
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cases: any[] = r.report?.cases ?? [];
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        {r.kind} · ARGUS {r.release} · commit {r.commit?.slice(0, 12) ?? "?"} · {r.source}
        {r.report_sha256 && <> · SHA-256 <code>{r.report_sha256.slice(0, 16)}…</code></>}
      </p>
      {r.error && <pre className="whitespace-pre-wrap rounded bg-red-50 p-2 text-xs text-red-800">{r.error}</pre>}
      {r.summary && <EvalTable rows={r.summary} />}
      {r.report && (
        <div className="flex flex-wrap gap-2 text-xs">
          {(["json", "md", "html"] as const).map((f) => (
            <button key={f} type="button" disabled={!!busy} onClick={() => void save(f, false)}
                    className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">Full .{f}</button>
          ))}
          {(["json", "md"] as const).map((f) => (
            <button key={`p${f}`} type="button" disabled={!!busy} onClick={() => void save(f, true)}
                    className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50">Public .{f}</button>
          ))}
        </div>
      )}
      {cases.map((c) => (
        <details key={c.id} className="rounded border border-slate-200 p-2 text-sm">
          <summary className="cursor-pointer">
            <span className="font-medium">{c.id}</span>{" "}
            <span className="text-xs text-slate-500">{c.language} · {c.domain} · {c.severity} · as {c.role}</span>{" "}
            {Object.entries(c.results as Record<string, any[]>).map(([m, rs]) => ( // eslint-disable-line @typescript-eslint/no-explicit-any
              <span key={m} className="ml-1 text-xs">
                {m}: {rs.map((x) => (x.skipped ? "skip" : x.scores.passed ? "✓" : x.scores.critical.length ? "‼" : "✗")).join("")}
              </span>
            ))}
          </summary>
          <blockquote className="my-2 border-l-2 border-slate-300 pl-2 text-slate-700">{c.question}</blockquote>
          {Object.entries(c.results as Record<string, any[]>).map(([m, rs]) => rs.map((x) => ( // eslint-disable-line @typescript-eslint/no-explicit-any
            <div key={`${m}-${x.attempt}`} className="mt-2 rounded bg-slate-50 p-2">
              <p className="text-xs font-semibold">{m} #{x.attempt + 1}{x.skipped ? ` — skipped: ${x.skipped}` : ` — ${x.seconds} s`}</p>
              {!x.skipped && (
                <>
                  <ul className="ml-4 list-disc text-xs text-slate-700">
                    {x.scores.reasons.length ? x.scores.reasons.map((w: string) => <li key={w}>{w}</li>) : <li>passed every check</li>}
                  </ul>
                  <pre className="mt-1 whitespace-pre-wrap text-xs">{x.answer}</pre>
                  <details className="text-xs">
                    <summary className="cursor-pointer text-slate-500">{x.steps.length} lookups</summary>
                    <ol className="ml-4 list-decimal">
                      {x.steps.map((s: { tool: string; arguments?: unknown; result?: string }, i: number) => (
                        <li key={i}><code>{s.tool}</code> {JSON.stringify(s.arguments ?? {})}
                          <pre className="max-h-40 overflow-auto whitespace-pre-wrap text-[11px] text-slate-500">{s.result}</pre></li>
                      ))}
                    </ol>
                  </details>
                </>
              )}
            </div>
          )))}
        </details>
      ))}
    </div>
  );
}

/** Answers people rated down, exported as draft cases for the evaluation dataset. */
function FeedbackDrafts() {
  const [since, setSince] = useState("");
  const [note, setNote] = useState("");
  const get = async () => {
    setNote("");
    try {
      const { url, count } = await askEvalApi.feedbackDrafts(since || undefined);
      if (count === 0) {
        setNote("No answer has been rated down" + (since ? " since then." : " yet."));
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = "ask-feedback-drafts.yaml";
        a.click();
        setNote(`${count} draft case${count === 1 ? "" : "s"} saved.`);
      }
      URL.revokeObjectURL(url);
    } catch (e) {
      setNote(problem(e));
    }
  };
  return (
    <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">From feedback to cases</h2>
      <p className="text-xs text-slate-500">Answers people rated down, as draft cases (YAML): the question, the answer,
        the comment and the lookups, with secrets redacted. They come from real workspaces — rewrite each onto a
        synthetic fixture before it enters the dataset.</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="text-xs">Since <input type="date" value={since} onChange={(e) => setSince(e.target.value)}
               className="rounded border border-slate-300 px-2 py-0.5" /></label>
        <button type="button" onClick={() => void get()} className="rounded border border-slate-300 px-3 py-1">
          Export answers rated down</button>
        {note && <span className="text-xs text-slate-600">{note}</span>}
      </div>
    </section>
  );
}

/** Administration › Ask evaluation: the model server, the history per release ("not run" when a release has no
 *  run), starting a run, and each run's report and drill-down. */
export function AskEvaluationPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["ask-eval-settings"], queryFn: askEvalApi.settings });
  const releases = useQuery({ queryKey: ["ask-eval-releases"], queryFn: askEvalApi.releases, refetchInterval: 8000 });
  const runs = useQuery({ queryKey: ["ask-eval-runs"], queryFn: askEvalApi.runs, refetchInterval: 8000 });
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState<{ base_url?: string; api_key?: string; models?: string; release_model?: string;
                                     approved_hosts?: string; judge_model?: string; repeats?: string }>({});
  const [chosen, setChosen] = useState<string[]>([]);
  const refresh = () => {
    for (const k of ["ask-eval-settings", "ask-eval-releases", "ask-eval-runs"]) queryClient.invalidateQueries({ queryKey: [k] });
  };
  const save = useMutation({
    mutationFn: () => askEvalApi.saveSettings({
      ...(form.base_url !== undefined ? { base_url: form.base_url } : {}),
      ...(form.api_key ? { api_key: form.api_key } : {}),
      ...(form.models !== undefined ? { models: form.models.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
      ...(form.release_model !== undefined ? { release_model: form.release_model || null } : {}),
      ...(form.judge_model !== undefined ? { judge_model: form.judge_model || null } : {}),
      ...(form.approved_hosts !== undefined ? { approved_hosts: form.approved_hosts.split(",").map((s) => s.trim()).filter(Boolean) } : {}),
      ...(form.repeats ? { repeats: Number(form.repeats) } : {}),
    }),
    onSuccess: () => { setForm({}); refresh(); },
  });
  const start = useMutation({
    mutationFn: (v: { kind: "release" | "benchmark" | "simulated"; models?: string[] }) => askEvalApi.start(v),
    onSuccess: (r) => { setOpen(r.id); refresh(); },
  });
  const s = settings.data;
  const field = "w-full rounded border border-slate-300 px-2 py-1 text-sm";

  return (
    <div className="max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Ask evaluation</h1>
        <p className="mt-1 text-sm text-slate-500">
          Whether this version of ARGUS still answers a reviewed set of questions correctly and safely, and how the
          approved chat models compare on them. Questions are asked through the real Ask flow in synthetic
          workspaces, in the evaluation's own database. A release without a run says <i>not run</i>.
        </p>
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-900">Releases</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="px-2 py-1">Release</th><th className="px-2 py-1">Release quality</th>
              <th className="px-2 py-1">Model benchmark</th><th className="px-2 py-1">Runs</th></tr></thead>
            <tbody>
              {(releases.data?.releases ?? []).map((r) => (
                <tr key={r.release} className="border-b border-slate-100">
                  <td className="px-2 py-1 font-medium">{r.release}{r.current && <span className="ml-1 text-xs text-slate-400">(this one)</span>}</td>
                  {([r.release_quality, r.benchmark]).map((x, i) => (
                    <td key={i} className="px-2 py-1">
                      {"id" in x ? <button type="button" className="text-indigo-700 underline" onClick={() => setOpen(x.id)}>
                        <Status run={x} /></button> : <Status run={x} />}
                    </td>
                  ))}
                  <td className="px-2 py-1 text-xs text-slate-500">{r.runs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Run</h2>
        {s && !s.database_configured && (
          <p className="text-xs text-amber-700">No evaluation database is configured (ASK_EVAL_DATABASE_URL): runs can only be
            made from a CI job or a cluster job and uploaded (docs/ask-eval.md).</p>
        )}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button type="button" disabled={start.isPending || !s?.base_url}
                  onClick={() => start.mutate({ kind: "release" })}
                  className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40">Release quality</button>
          <span className="text-slate-400">·</span>
          {(s?.models ?? []).map((m) => (
            <label key={m} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={chosen.includes(m)}
                     onChange={(e) => setChosen(e.target.checked ? [...chosen, m] : chosen.filter((x) => x !== m))} />{m}
            </label>
          ))}
          <button type="button" disabled={start.isPending || chosen.length < 2}
                  onClick={() => start.mutate({ kind: "benchmark", models: chosen })}
                  className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40">Benchmark the selected models</button>
          <button type="button" disabled={start.isPending} onClick={() => start.mutate({ kind: "simulated" })}
                  className="rounded border border-slate-300 px-3 py-1 text-xs">Dry run (stand-ins)</button>
        </div>
        {start.isError && <p className="text-xs text-red-700">{problem(start.error)}</p>}
      </section>

      {open && (
        <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">Run {open}</h2>
            <button type="button" className="text-xs text-slate-500 underline" onClick={() => setOpen(null)}>close</button>
          </div>
          <RunDetail id={open} />
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-900">All runs</h2>
        <ul className="text-sm">
          {(runs.data ?? []).map((r) => (
            <li key={r.id} className="flex flex-wrap gap-2 border-b border-slate-100 py-1">
              <button type="button" className="font-mono text-xs text-indigo-700 underline" onClick={() => setOpen(r.id)}>{r.id}</button>
              <span>{r.kind}</span><span className="text-slate-500">ARGUS {r.release}</span><Status run={r} />
              <span className="text-xs text-slate-400">{r.models.join(", ")} · {r.source}</span>
            </li>
          ))}
        </ul>
      </section>

      <FeedbackDrafts />

      <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-900">Model server</h2>
        <p className="text-xs text-slate-500">An OpenAI-compatible server. The key is stored encrypted and never shown;
          leave it empty to keep the saved one. Cases asked as a person with restricted classes go only to the
          approved hosts.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="text-xs">Server base URL<input className={field} placeholder={s?.base_url ?? "https://…/v1"}
                 value={form.base_url ?? ""} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></label>
          <label className="text-xs">API key {s?.api_key_set ? "(saved)" : "(not set)"}<input type="password" autoComplete="off"
                 className={field} value={form.api_key ?? ""} onChange={(e) => setForm({ ...form, api_key: e.target.value })} /></label>
          <label className="text-xs">Approved chat models (comma-separated)<input className={field} placeholder={(s?.models ?? []).join(", ")}
                 value={form.models ?? ""} onChange={(e) => setForm({ ...form, models: e.target.value })} /></label>
          <label className="text-xs">Production candidate<input className={field} placeholder={s?.release_model ?? ""}
                 value={form.release_model ?? ""} onChange={(e) => setForm({ ...form, release_model: e.target.value })} /></label>
          <label className="text-xs">Judge model (optional)<input className={field} placeholder={s?.judge_model ?? ""}
                 value={form.judge_model ?? ""} onChange={(e) => setForm({ ...form, judge_model: e.target.value })} /></label>
          <label className="text-xs">Hosts approved for restricted content<input className={field} placeholder={(s?.approved_hosts ?? []).join(", ")}
                 value={form.approved_hosts ?? ""} onChange={(e) => setForm({ ...form, approved_hosts: e.target.value })} /></label>
          <label className="text-xs">Repeats per case<input className={field} type="number" min={1} max={10} placeholder={String(s?.repeats ?? 3)}
                 value={form.repeats ?? ""} onChange={(e) => setForm({ ...form, repeats: e.target.value })} /></label>
        </div>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}
                className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-40">Save</button>
        {save.isError && <p className="text-xs text-red-700">{problem(save.error)}</p>}
      </section>
    </div>
  );
}
