import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  importsApi,
  SHEET_DROP,
  SHEET_KEY,
  SHEET_NAME,
  SHEET_NEW,
  spreadsheetImportApi,
  type SheetAnalysis,
  type SheetColumnPlan,
  type SheetPlan,
  type SheetPreview,
  type SheetRun,
  type SheetTarget,
} from "../../api/client";
import { Card } from "../../components/hub/ui";

const NEW_KINDS = ["string", "text", "integer", "float", "boolean", "date", "datetime", "enumeration"];
const KIND_LABEL: Record<string, string> = {
  string: "Short text",
  text: "Long text",
  integer: "Whole number",
  float: "Number",
  boolean: "Yes / no",
  date: "Date",
  datetime: "Date and time",
  enumeration: "Choice list",
};

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : "It could not be done.";
}

function slug(text: string): string {
  const s = text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return !s ? "column" : /^\d/.test(s) ? `c_${s}` : s;
}

function SourceBadge({ c }: { c: SheetColumnPlan }) {
  if (!c.source) return null;
  const style =
    c.source === "ai"
      ? "bg-violet-50 text-violet-700"
      : c.source === "person"
        ? "bg-slate-100 text-slate-600"
        : "bg-sky-50 text-sky-700";
  const label = c.source === "ai" ? "AI" : c.source === "person" ? "you" : "rule";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${style}`} title={c.reason}>
      {label}
      {c.source !== "person" && c.confidence !== undefined ? ` ${Math.round(c.confidence * 100)}%` : ""}
    </span>
  );
}

/** Records from a spreadsheet: each row a record, each column a property. The type is one the workspace
 *  has, or a new one under one of its types — with every property ARGUS gives records of that kind. Rules
 *  and the AI propose where each column goes; every row is checked before anything is written. */
export function SpreadsheetImportPage() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [sheet, setSheet] = useState<string | undefined>(undefined);
  const [useAi, setUseAi] = useState(true);
  const [analysis, setAnalysis] = useState<SheetAnalysis | null>(null);
  const [plan, setPlan] = useState<SheetPlan | null>(null);
  const [preview, setPreview] = useState<SheetPreview | null>(null);
  const [run, setRun] = useState<SheetRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  const analyse = useMutation({
    mutationFn: (opts: { target?: SheetTarget; sheet?: string }) =>
      spreadsheetImportApi.analyse(file!, { sheet: opts.sheet ?? sheet, useAi, target: opts.target }),
    onSuccess: (out, opts) => {
      setAnalysis(out);
      setSheet(out.file.sheet ?? undefined);
      // A name typed for a new type survives re-proposing its columns.
      const keepName = opts.target?.mode === "new" ? opts.target.name : undefined;
      setPlan(
        keepName && out.plan.target.mode === "new"
          ? { ...out.plan, target: { ...out.plan.target, name: keepName } }
          : out.plan,
      );
      setPreview(null);
      setError(null);
    },
    onError: (e) => setError(problem(e)),
  });
  const check = useMutation({
    mutationFn: () => spreadsheetImportApi.preview(file!, sheet, plan!),
    onSuccess: (out) => {
      setPreview(out);
      setError(null);
    },
    onError: (e) => {
      setPreview(null);
      setError(problem(e));
    },
  });
  const start = useMutation({
    mutationFn: () => spreadsheetImportApi.run(file!, sheet, plan!, analysis!.file.digest),
    onSuccess: (out) => {
      setRun(out);
      setError(null);
    },
    onError: (e) => setError(problem(e)),
  });
  const job = useQuery({
    queryKey: ["import-job", run?.job_uid],
    queryFn: () => importsApi.get(run!.job_uid),
    enabled: !!run,
    refetchInterval: (q) =>
      q.state.data && (q.state.data.status === "succeeded" || q.state.data.status === "failed") ? false : 1500,
  });
  const done = job.data && (job.data.status === "succeeded" || job.data.status === "failed");
  // Once, when the import ends: the lists and the type tree show what it made.
  useEffect(() => {
    if (!done) return;
    void queryClient.invalidateQueries({ queryKey: ["assets"] });
    void queryClient.invalidateQueries({ queryKey: ["schemas"] });
  }, [done, queryClient]);

  const props = analysis?.properties ?? [];
  const typeOptions = useMemo(() => {
    if (!analysis) return [];
    const best = new Set(analysis.candidates.map((c) => c.uid));
    return [
      ...analysis.candidates.map((c) => ({ uid: c.uid, label: `${c.name} — ${Math.round(c.score * 100)}% match` })),
      ...analysis.parents.filter((p) => !p.abstract && !best.has(p.uid)).map((p) => ({ uid: p.uid, label: p.path })),
    ];
  }, [analysis]);

  const reset = () => {
    setAnalysis(null);
    setPlan(null);
    setPreview(null);
    setRun(null);
    setError(null);
  };

  const setColumn = (column: string, change: Partial<SheetColumnPlan>) => {
    if (!plan) return;
    setPreview(null);
    setPlan({
      ...plan,
      columns: plan.columns.map((c) => (c.column === column ? { ...c, ...change, source: "person" } : c)),
    });
  };

  const chooseTarget = (target: SheetTarget) => {
    if (!plan) return;
    setPreview(null);
    // Another type has other properties: the columns are proposed again for it.
    analyse.mutate({ target });
  };

  const profileOf = (column: string) => analysis?.columns.find((c) => c.column === column);
  const taken = new Map<string, string>();
  for (const c of plan?.columns ?? []) if (![SHEET_DROP, SHEET_NEW].includes(c.target)) taken.set(c.target, c.column);

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Import a spreadsheet</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          An Excel (.xlsx) or CSV file: the first row names the columns, each row below becomes a record. The rows
          go into a type this workspace has, or a new one under one of its types — which gives them every property
          ARGUS records of that kind have (description, lifecycle, owner, location, serial number…). Rules and the
          AI propose where each column goes; you check it, and every row is checked before anything is written.
        </p>
      </div>

      <Card title="1 · The file">
        <div className="flex flex-wrap items-end gap-4 py-2">
          <label className="text-sm">
            <span className="block text-xs font-medium text-slate-600">File</span>
            <input
              type="file"
              accept=".xlsx,.xlsm,.csv,.tsv,.txt"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setSheet(undefined);
                reset();
              }}
              className="mt-1 text-sm"
            />
          </label>
          {analysis && analysis.file.sheets.length > 1 && (
            <label className="text-sm">
              <span className="block text-xs font-medium text-slate-600">Sheet</span>
              <select
                value={sheet ?? ""}
                onChange={(e) => {
                  setSheet(e.target.value);
                  analyse.mutate({ sheet: e.target.value });
                }}
                className="mt-1 rounded border border-slate-300 px-2 py-1 text-sm"
              >
                {analysis.file.sheets.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            Use the AI for what the rules cannot place
          </label>
          <button
            type="button"
            disabled={!file || analyse.isPending}
            onClick={() => analyse.mutate({})}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-40"
          >
            {analyse.isPending ? "Reading…" : analysis ? "Read again" : "Read the file"}
          </button>
        </div>
        {analysis && (
          <p className="pb-2 text-xs text-slate-500">
            {analysis.file.rows} rows, {analysis.columns.length} columns
            {analysis.file.sheet ? ` · sheet ${analysis.file.sheet}` : ""}.{" "}
            {analysis.ai.used ? `AI: ${analysis.ai.model ?? "used"}.` : analysis.ai.reason}
          </p>
        )}
      </Card>

      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {analysis && plan && (
        <Card title="2 · What the rows become">
          <div className="space-y-3 py-2 text-sm">
            <label className="flex items-start gap-2">
              <input
                type="radio"
                checked={plan.target.mode === "existing"}
                disabled={typeOptions.length === 0}
                onChange={() => typeOptions[0] && chooseTarget({ mode: "existing", schema_uid: typeOptions[0].uid })}
                className="mt-1"
              />
              <span className="flex-1">
                <span className="font-medium text-slate-800">Records of an existing type</span>
                {plan.target.mode === "existing" && (
                  <select
                    value={plan.target.schema_uid}
                    onChange={(e) => chooseTarget({ mode: "existing", schema_uid: e.target.value })}
                    className="mt-1 block w-full max-w-lg rounded border border-slate-300 px-2 py-1"
                  >
                    {typeOptions.map((o) => (
                      <option key={o.uid} value={o.uid}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                )}
              </span>
            </label>
            <label className="flex items-start gap-2">
              <input
                type="radio"
                checked={plan.target.mode === "new"}
                onChange={() =>
                  chooseTarget({
                    mode: "new",
                    name: analysis.file.title || "Imported record",
                    parent_uid: analysis.parents.find((p) => p.name === "Asset")?.uid ?? analysis.parents[0]?.uid ?? null,
                  })
                }
                className="mt-1"
              />
              <span className="flex-1">
                <span className="font-medium text-slate-800">A new type</span>
                {plan.target.mode === "new" && (
                  <span className="mt-1 flex flex-wrap gap-3">
                    <input
                      value={plan.target.name}
                      onChange={(e) =>
                        plan.target.mode === "new" &&
                        setPlan({ ...plan, target: { ...plan.target, name: e.target.value } })
                      }
                      placeholder="Its name, singular: Chiller"
                      className="w-64 rounded border border-slate-300 px-2 py-1"
                    />
                    <label className="flex items-center gap-1 text-slate-600">
                      under
                      <select
                        value={plan.target.parent_uid ?? ""}
                        onChange={(e) =>
                          plan.target.mode === "new" &&
                          chooseTarget({ ...plan.target, parent_uid: e.target.value || null })
                        }
                        className="max-w-md rounded border border-slate-300 px-2 py-1"
                      >
                        {analysis.parents.map((p) => (
                          <option key={p.uid} value={p.uid}>
                            {p.path}
                          </option>
                        ))}
                      </select>
                    </label>
                  </span>
                )}
              </span>
            </label>
            {plan.target.reason && (
              <p className="text-xs text-slate-500">
                Proposed by {plan.target.source === "ai" ? "the AI" : "the rules"}: {plan.target.reason}
              </p>
            )}
            {analyse.isPending && <p className="text-xs text-slate-400">Proposing the columns for this type…</p>}
          </div>
        </Card>
      )}

      {analysis && plan && (
        <Card title="3 · Where each column goes">
          <div className="overflow-x-auto py-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="py-1 pr-3">Column</th>
                  <th className="py-1 pr-3">Values</th>
                  <th className="py-1 pr-3">Goes to</th>
                  <th className="py-1">Proposed by</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {plan.columns.map((c) => {
                  const p = profileOf(c.column);
                  const clash = taken.get(c.target) && taken.get(c.target) !== c.column;
                  return (
                    <tr key={c.column} className="align-top">
                      <td className="py-2 pr-3 font-medium text-slate-800">{c.column}</td>
                      <td className="max-w-xs py-2 pr-3 text-xs text-slate-500">
                        {p ? (
                          <>
                            <span className="text-slate-600">{KIND_LABEL[p.kind] ?? p.kind}</span> · {p.filled} filled
                            <span className="block truncate" title={p.samples.join(" · ")}>
                              {p.samples.slice(0, 4).join(" · ")}
                            </span>
                          </>
                        ) : null}
                      </td>
                      <td className="py-2 pr-3">
                        <select
                          value={c.target}
                          onChange={(e) => {
                            const target = e.target.value;
                            setColumn(c.column, {
                              target,
                              new:
                                target === SHEET_NEW
                                  ? c.new ?? {
                                      key: slug(c.column),
                                      name: c.column,
                                      type: p && NEW_KINDS.includes(p.kind) ? p.kind : "string",
                                      options: p?.options,
                                    }
                                  : undefined,
                            });
                          }}
                          className={`w-64 rounded border px-2 py-1 ${clash ? "border-red-400" : "border-slate-300"}`}
                        >
                          <option value={SHEET_NAME}>The record's name</option>
                          <option value={SHEET_KEY}>The record's key (to update records already here)</option>
                          <option value={SHEET_NEW}>A new property…</option>
                          <option value={SHEET_DROP}>Not imported</option>
                          <optgroup label="Properties of the type">
                            {props.map((a) => (
                              <option key={a.key} value={a.key}>
                                {a.name} ({KIND_LABEL[a.type] ?? a.type}
                                {a.reference ? ` → ${a.reference}` : ""})
                              </option>
                            ))}
                          </optgroup>
                        </select>
                        {clash && <p className="mt-1 text-xs text-red-600">Also chosen for {taken.get(c.target)}.</p>}
                        {c.target === SHEET_NEW && c.new && (
                          <div className="mt-1 flex flex-wrap gap-2">
                            <input
                              value={c.new.name}
                              onChange={(e) =>
                                setColumn(c.column, { new: { ...c.new!, name: e.target.value, key: slug(e.target.value) } })
                              }
                              className="w-40 rounded border border-slate-300 px-2 py-0.5 text-xs"
                              title={`Stored as ${c.new.key}`}
                            />
                            <select
                              value={c.new.type}
                              onChange={(e) =>
                                setColumn(c.column, {
                                  new: {
                                    ...c.new!,
                                    type: e.target.value,
                                    options: e.target.value === "enumeration" ? p?.options ?? p?.samples : undefined,
                                  },
                                })
                              }
                              className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                            >
                              {NEW_KINDS.map((k) => (
                                <option key={k} value={k}>
                                  {KIND_LABEL[k]}
                                </option>
                              ))}
                            </select>
                            {c.new.type === "enumeration" && (
                              <span className="text-xs text-slate-500" title={(c.new.options ?? []).join(", ")}>
                                {(c.new.options ?? []).length} choices
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-2">
                        <SourceBadge c={c} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-4 border-t border-slate-100 py-3">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={plan.update_existing}
                onChange={(e) => {
                  setPreview(null);
                  setPlan({ ...plan, update_existing: e.target.checked });
                }}
              />
              Update records whose key is already here
            </label>
            <button
              type="button"
              disabled={check.isPending || analyse.isPending}
              onClick={() => check.mutate()}
              className="ml-auto rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-40"
            >
              {check.isPending ? "Checking every row…" : "Check every row"}
            </button>
          </div>
        </Card>
      )}

      {preview && !run && (
        <Card title="4 · Before importing">
          <div className="space-y-3 py-2 text-sm">
            <p className="text-slate-700">
              {preview.type.mode === "new" ? (
                <>
                  A new type <b>{preview.type.name}</b> under {preview.type.parent}
                </>
              ) : (
                <>
                  Records of <b>{preview.type.name}</b>
                </>
              )}
              {preview.type.new_properties.length > 0 &&
                `, with ${preview.type.new_properties.length} new ${
                  preview.type.new_properties.length === 1 ? "property" : "properties"
                }: ${preview.type.new_properties.map((p) => p.name).join(", ")}`}
              .
            </p>
            <div className="flex flex-wrap gap-3">
              {(
                [
                  ["create", "new", "bg-emerald-50 text-emerald-800"],
                  ["update", "updated", "bg-sky-50 text-sky-800"],
                  ["unchanged", "unchanged", "bg-slate-100 text-slate-700"],
                  ["error", "with a problem", "bg-red-50 text-red-800"],
                ] as const
              ).map(([k, label, style]) => (
                <span key={k} className={`rounded-md px-3 py-1.5 ${style}`}>
                  <b className="tabular-nums">{preview.counts[k]}</b> {label}
                </span>
              ))}
            </div>
            {preview.counts.error > 0 && (
              <p className="text-xs text-slate-500">
                Rows with a problem are left out; fix them in the file, or change where their columns go, and check
                again.
              </p>
            )}
            <div className="max-h-96 overflow-auto rounded border border-slate-100">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
                  <tr>
                    <th className="px-2 py-1">Row</th>
                    <th className="px-2 py-1">Record</th>
                    <th className="px-2 py-1">What happens</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.rows.map((r) => (
                    <tr key={r.row} className={r.action === "error" ? "bg-red-50/40" : ""}>
                      <td className="px-2 py-1 tabular-nums text-slate-500">{r.row}</td>
                      <td className="px-2 py-1 text-slate-800">
                        {r.key && <span className="mr-1 font-mono text-slate-500">{r.key}</span>}
                        {r.name}
                      </td>
                      <td className="px-2 py-1">
                        {r.action === "error" ? (
                          <span className="text-red-700">{r.problems.join("; ")}</span>
                        ) : (
                          <span className="text-slate-600">
                            {r.action === "create" ? "created" : r.action === "update" ? "updated" : "unchanged"}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.total_rows > preview.rows.length && (
                <p className="px-2 py-1 text-xs text-slate-400">
                  The first rows and every row with a problem are shown, of {preview.total_rows}.
                </p>
              )}
            </div>
            <button
              type="button"
              disabled={start.isPending || preview.counts.create + preview.counts.update === 0}
              onClick={() => start.mutate()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-40"
            >
              {start.isPending
                ? "Starting…"
                : `Import ${preview.counts.create + preview.counts.update} ${
                    preview.counts.create + preview.counts.update === 1 ? "row" : "rows"
                  }`}
            </button>
          </div>
        </Card>
      )}

      {run && (
        <Card title="Import">
          <div className="space-y-2 py-2 text-sm">
            <p className="text-slate-700">
              {job.data?.status === "succeeded"
                ? "Done."
                : job.data?.status === "failed"
                  ? `It stopped: ${job.data.error}`
                  : `Importing… ${job.data?.progress ?? ""}`}
            </p>
            {job.data && (
              <p className="text-slate-600">
                {Number(job.data.counts.created ?? 0)} created · {Number(job.data.counts.updated ?? 0)} updated ·{" "}
                {Number(job.data.counts.unchanged ?? 0)} unchanged · {Number(job.data.counts.failed ?? 0)} not imported
              </p>
            )}
            {job.data && job.data.warnings.length > 0 && (
              <ul className="max-h-48 list-disc overflow-auto pl-5 text-xs text-red-700">
                {job.data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            {done && (
              <div className="flex gap-3">
                <Link to={`/schemas/${run.type_uid}`} className="text-sm font-medium text-slate-900 underline">
                  Open the type {run.type}
                </Link>
                <Link to="/assets/search" className="text-sm text-slate-600 underline">
                  Browse the records
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setFile(null);
                    reset();
                  }}
                  className="text-sm text-slate-600 underline"
                >
                  Import another file
                </button>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
