import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { problemText, reshapeApi, schemasApi, templatesApi } from "../../api/client";
import type { ReshapeResult, TemplateListing, TemplateProblem } from "../../api/types";
import { MarkdownView } from "../../components/MarkdownView";

const SCOPE: Record<string, { label: string; tone: string }> = {
  official: { label: "official", tone: "bg-slate-100 text-slate-700" },
  workspace: { label: "workspace", tone: "bg-sky-100 text-sky-800" },
  personal: { label: "mine", tone: "bg-violet-100 text-violet-800" },
};

function Scope({ scope }: { scope: string }) {
  const s = SCOPE[scope] ?? SCOPE.official;
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${s.tone}`}>{s.label}</span>;
}

/** The templates documents are reworked with: the official ones (read-only), the workspace's variants and your
 * personal copies. */
export function DocumentTemplates() {
  const navigate = useNavigate();
  const list = useQuery({ queryKey: ["templates"], queryFn: () => templatesApi.list() });
  const [error, setError] = useState<string | null>(null);
  const make = useMutation({
    mutationFn: (v: { base: string; scope: "workspace" | "personal" }) => templatesApi.create(v.base, v.scope),
    onSuccess: (t) => navigate(`/documents/templates/${encodeURIComponent(t.ref)}`),
    onError: (e) => setError(problemText(e)),
  });
  const byType = useMemo(() => {
    const m = new Map<string, TemplateListing[]>();
    for (const t of list.data ?? []) m.set(t.document_type, [...(m.get(t.document_type) ?? []), t]);
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [list.data]);

  return (
    <div className="max-w-5xl space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Document templates</h1>
          <p className="mt-1 text-sm text-slate-500">
            What <Link to="/documents/reshape" className="text-indigo-600 hover:underline">Rework from raw text</Link>{" "}
            produces for each type. Official templates ship with ARGUS and cannot be changed; a workspace variant
            (made by those who approve documents) or your own copy starts from one and keeps where it came from.
            Every publication is a new version; documents record the exact version that made them.
          </p>
        </div>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      {list.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {byType.map(([type, rows]) => (
          <div key={type} className="px-4 py-3">
            <div className="text-sm font-semibold text-slate-900">{type}</div>
            <ul className="mt-1 space-y-1">
              {rows.map((t) => (
                <li key={t.ref} className="flex flex-wrap items-center gap-2 text-sm">
                  <Scope scope={t.scope} />
                  <Link to={`/documents/templates/${encodeURIComponent(t.ref)}`} className="text-indigo-700 hover:underline">
                    {t.name}
                  </Link>
                  <span className="text-xs text-slate-500">{t.published ? `v${t.version}` : "not published"}</span>
                  {t.active && <span className="rounded bg-emerald-100 px-1.5 text-[11px] text-emerald-800">default</span>}
                  {t.official_update && (
                    <span className="rounded bg-amber-100 px-1.5 text-[11px] text-amber-900">official v{t.official_update} available</span>
                  )}
                  {t.scope === "official" && (
                    <span className="ml-auto flex gap-2 text-xs">
                      <button type="button" className="text-slate-600 hover:underline"
                              onClick={() => make.mutate({ base: t.ref, scope: "workspace" })}>Make a workspace variant</button>
                      <button type="button" className="text-slate-600 hover:underline"
                              onClick={() => make.mutate({ base: t.ref, scope: "personal" })}>Make my copy</button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

/** One template: an official one to read, or a variant to edit, check, try, publish and compare. */
export function DocumentTemplatePage() {
  const { ref = "" } = useParams();
  return ref.startsWith("official:") ? <OfficialTemplateView refName={ref} /> : <VariantEditor refName={ref} />;
}

function OfficialTemplateView({ refName }: { refName: string }) {
  const navigate = useNavigate();
  const t = useQuery({ queryKey: ["template", refName], queryFn: () => templatesApi.official(refName) });
  const make = useMutation({
    mutationFn: (scope: "workspace" | "personal") => templatesApi.create(refName, scope),
    onSuccess: (v) => navigate(`/documents/templates/${encodeURIComponent(v.ref)}`),
  });
  if (t.isError) return <p className="text-sm text-rose-700">{problemText(t.error)}</p>;
  if (!t.data) return <p className="text-sm text-slate-500">Loading…</p>;
  return (
    <div className="max-w-5xl space-y-3">
      <Link to="/documents/templates" className="text-xs text-slate-500">&larr; Templates</Link>
      <div className="flex flex-wrap items-baseline gap-2">
        <h1 className="text-xl font-semibold text-slate-900">{t.data.name}</h1>
        <Scope scope="official" /> <span className="text-sm text-slate-500">v{t.data.latest_version} · {t.data.document_type}</span>
      </div>
      <p className="text-sm text-slate-600">Shipped with ARGUS; it cannot be changed. Make a variant to adapt it.</p>
      <div className="flex gap-2">
        <button type="button" onClick={() => make.mutate("workspace")} className="rounded border border-slate-300 px-3 py-1.5 text-sm">Make a workspace variant</button>
        <button type="button" onClick={() => make.mutate("personal")} className="rounded border border-slate-300 px-3 py-1.5 text-sm">Make my copy</button>
      </div>
      {make.isError && <p className="text-sm text-rose-700">{problemText(make.error)}</p>}
      <pre className="overflow-auto rounded border border-slate-200 bg-white p-3 text-xs">{t.data.source}</pre>
    </div>
  );
}

const SAMPLE = `Da: Marco Rossi <mrossi@lnf.infn.it>
Inviato: martedì 14 ottobre 2025 17:42
Oggetto: riunione vuoto linac

Presenti: Marco Rossi, Laura Ferrari.
Abbiamo deciso di sostituire la pompa IP-02 durante lo stop di novembre.
Azione: Paolo ordina la pompa di ricambio entro domani.`;

function VariantEditor({ refName }: { refName: string }) {
  const qc = useQueryClient();
  const v = useQuery({ queryKey: ["template", refName], queryFn: () => templatesApi.variant(refName) });
  const [source, setSource] = useState("");
  const [problems, setProblems] = useState<TemplateProblem[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (v.data) { setSource(v.data.draft_source); setProblems(v.data.draft_problems); } }, [v.data]);
  // Checked as it is typed, nothing saved.
  useEffect(() => {
    if (!source) return;
    const timer = window.setTimeout(() => {
      templatesApi.validate(source).then((r) => setProblems(r.problems)).catch(() => undefined);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [source]);
  const refresh = (data: unknown) => { qc.setQueryData(["template", refName], data); setError(null); };
  const save = useMutation({ mutationFn: () => templatesApi.save(refName, source), onSuccess: refresh,
                             onError: (e) => setError(problemText(e)) });
  const publish = useMutation({
    mutationFn: async () => { await templatesApi.save(refName, source); return templatesApi.publish(refName, note); },
    onSuccess: (d) => { refresh(d); setNote(""); }, onError: (e) => setError(problemText(e)) });
  const active = useMutation({ mutationFn: (on: boolean) => templatesApi.setActive(refName, on), onSuccess: refresh,
                               onError: (e) => setError(problemText(e)) });
  const rebase = useMutation({ mutationFn: () => templatesApi.rebase(refName), onSuccess: refresh,
                               onError: (e) => setError(problemText(e)) });
  const [showCompare, setShowCompare] = useState(false);
  const compare = useQuery({ queryKey: ["template-compare", refName, v.data?.latest_version, showCompare],
                             queryFn: () => templatesApi.compare(refName), enabled: showCompare });

  if (v.isError) return <p className="text-sm text-rose-700">{problemText(v.error)}</p>;
  if (!v.data) return <p className="text-sm text-slate-500">Loading…</p>;
  const t = v.data;
  const errors = problems.filter((p) => p.severity === "error");
  const dirty = source !== t.draft_source;

  return (
    <div className="max-w-[1400px] space-y-3">
      <Link to="/documents/templates" className="text-xs text-slate-500">&larr; Templates</Link>
      <div className="flex flex-wrap items-baseline gap-2">
        <h1 className="text-xl font-semibold text-slate-900">{t.name}</h1>
        <Scope scope={t.scope} />
        <span className="text-sm text-slate-500">{t.document_type} · {t.latest_version ? `v${t.latest_version} published` : "not published"}
          {" "}· from official {t.base.id} v{t.base.version}</span>
        {t.active && <span className="rounded bg-emerald-100 px-1.5 text-[11px] text-emerald-800">default {t.scope === "personal" ? "for you" : "in the workspace"}</span>}
      </div>
      {t.official_update && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          ARGUS ships official v{t.official_update}. Your variant is unchanged: open <b>Compare</b> to see what changed,
          bring what you want into the draft, then{" "}
          <button type="button" onClick={() => rebase.mutate()} className="underline">mark it as following v{t.official_update}</button>.
        </p>
      )}
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <div>
          <textarea value={source} onChange={(e) => setSource(e.target.value)} spellCheck={false} rows={32}
                    className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs" />
          <ul className="mt-1 space-y-0.5 text-xs">
            {problems.map((p, i) => (
              <li key={i} className={p.severity === "error" ? "text-rose-700" : "text-amber-700"}>
                {p.line ? `Line ${p.line}: ` : ""}{p.message}
              </li>
            ))}
            {problems.length === 0 && <li className="text-emerald-700">Valid.</li>}
          </ul>
          <p className="mt-2 text-[11px] text-slate-500">
            Placeholders: <code>{"{{field:key}}"}</code>, <code>{"{{section:key}}"}</code>, <code>{"{{meta:title}}"}</code>{" "}
            (also document_date, source_date, event_date, template_id, template_version, reference_notice);{" "}
            <code>{"{{#section:key}} … {{/section:key}}"}</code> for what is left out when empty. The rules every
            template is applied under (nothing invented, sources quoted, no approval) cannot be changed here.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => save.mutate()} disabled={!dirty || save.isPending}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40">Save draft</button>
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed (for the version)"
                   className="min-w-56 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" />
            <button type="button" onClick={() => publish.mutate()} disabled={errors.length > 0 || publish.isPending}
                    className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40">
              Publish v{t.latest_version + 1}
            </button>
            <button type="button" onClick={() => active.mutate(!t.active)} disabled={!t.latest_version}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40">
              {t.active ? "Stop using by default" : t.scope === "personal" ? "Use it by default (me)" : "Use it by default (workspace)"}
            </button>
            <button type="button" onClick={() => setShowCompare((s) => !s)} className="text-sm text-indigo-600 hover:underline">
              {showCompare ? "Hide comparison" : "Compare"}
            </button>
          </div>
          {showCompare && compare.data && (
            <div className="mt-3 space-y-2">
              <Diff title={`Against official ${compare.data.base.id} v${compare.data.base.version}`} text={compare.data.against_base} />
              {compare.data.official_update && (
                <Diff title={`What the official template changed in v${compare.data.official_update.version}`}
                      text={compare.data.official_update.changes} />
              )}
            </div>
          )}
          <div className="mt-3 text-xs text-slate-600">
            <div className="font-medium">Versions</div>
            <ul>{t.versions.map((x) => (
              <li key={x.version}>v{x.version} · {new Date(x.created_at).toLocaleString()}{x.note ? ` — ${x.note}` : ""}</li>
            ))}{t.versions.length === 0 && <li className="text-slate-400">None yet.</li>}</ul>
          </div>
        </div>
        <TryTemplate source={source} documentType={t.document_type} disabled={errors.length > 0} />
      </div>
    </div>
  );
}

function Diff({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-100 px-2 py-1 text-xs font-medium text-slate-700">{title}</div>
      <pre className="max-h-80 overflow-auto p-2 text-[11px] leading-4">
        {(text || "No differences.").split("\n").map((l, i) => (
          <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "bg-emerald-50 text-emerald-900"
            : l.startsWith("-") && !l.startsWith("---") ? "bg-rose-50 text-rose-900" : l.startsWith("@@") ? "text-slate-400" : ""}>{l}</div>
        ))}
      </pre>
    </div>
  );
}

/** The template as edited, tried on sample text — through the workspace's AI, nothing saved. */
function TryTemplate({ source, documentType, disabled }: { source: string; documentType: string; disabled: boolean }) {
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const typeUid = (schemas.data ?? []).find((s) => s.applies_to === "documents" && s.name === documentType)?.uid;
  const [sample, setSample] = useState(SAMPLE);
  const [out, setOut] = useState<ReshapeResult | null>(null);
  const run = useMutation({
    mutationFn: () => reshapeApi.preview({ source: { text: sample, kind: "paste" }, document_type_uid: typeUid!,
                                           template_source: source }),
    onSuccess: setOut,
  });
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-slate-900">Try it on sample text</div>
      <textarea value={sample} onChange={(e) => setSample(e.target.value)} rows={8}
                className="w-full rounded border border-slate-300 px-2 py-1.5 font-mono text-xs" />
      <button type="button" onClick={() => run.mutate()} disabled={disabled || !typeUid || run.isPending}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-40">
        {run.isPending ? "Trying…" : "Try (nothing saved)"}
      </button>
      {run.isError && <p className="text-xs text-rose-700">{problemText(run.error)}</p>}
      {out && (
        <div className="rounded border border-slate-200 bg-white p-3">
          <MarkdownView markdown={out.markdown} />
          {out.missing.length > 0 && <p className="mt-2 text-xs text-amber-800">To confirm: {out.missing.join(", ")}</p>}
        </div>
      )}
    </div>
  );
}
