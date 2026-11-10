import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, beamModelApi } from "../../api/client";
import type { BeamConversionReport, BeamImportReport, BeamModelCheck, BeamModelV2, CanonicalBeamModel } from "../../api/types";
import { downloadJson, EditorV2, emptyModelV2 } from "./BeamModelEditorV2";

/** Bringing beam models into ARGUS (docs/beam-model.md): upload canonical JSON or simulator files — several models
 *  at once, checked before anything is written — or write one here. The editor writes the same argus.beam-model/2
 *  document an import reads, so editing a model is exporting it, changing it and importing it again: its history
 *  stays. */

const download = downloadJson;
export { downloadJson };

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const b = e.body as { detail?: unknown } | undefined;
    const d = b?.detail as { problems?: string[]; models?: BeamModelCheck[] } | string | undefined;
    if (typeof d === "string") return d;
    if (d?.problems) return d.problems.join("; ");
    if (d?.models) return d.models.filter((m) => !m.ok).map((m) => `${m.model ?? `#${m.index + 1}`}: ${m.problems.join("; ")}`).join(" · ");
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export function BeamModelEditorPage() {
  const { modelId } = useParams();
  const [tab, setTab] = useState<"upload" | "edit">(modelId ? "edit" : "upload");
  const existing = useQuery({
    queryKey: ["beam-model-export", modelId],
    queryFn: () => beamModelApi.exportV2(modelId!),
    enabled: !!modelId,
  });
  const [seed, setSeed] = useState<BeamModelV2 | null>(null);
  useEffect(() => {
    if (existing.data) setSeed(existing.data);
  }, [existing.data]);

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{modelId ? `Edit beam model ${modelId}` : "New beam model"}</h1>
          <p className="mt-1 text-sm text-slate-500">
            Machine models in the canonical <code>argus.beam-model/2</code> format (v1 files are read too), uploaded as
            they are or converted from MAD-X, TFS, Elegant, Bmad, Xsuite and Accelerator Toolbox files. What is along
            the beam, where, how it is connected, and what it does to or measures from the beam — never the hardware,
            which is bound to the components afterwards.
          </p>
        </div>
        <Link to="/beam-model" className="text-sm text-indigo-700 hover:underline">← Beam model</Link>
      </div>
      {!modelId && (
        <div className="flex rounded border border-slate-300 text-sm w-fit">
          {([["upload", "Upload files"], ["edit", "Write a model"]] as const).map(([k, label]) => (
            <button key={k} type="button" onClick={() => setTab(k)}
                    className={`px-3 py-1.5 ${tab === k ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{label}</button>
          ))}
        </div>
      )}
      {tab === "upload" && <Upload onEdit={(m) => { setSeed(m); setTab("edit"); }} />}
      {tab === "edit" && (modelId && !seed ? <p className="text-sm text-slate-400">{existing.isError ? errorText(existing.error) : "Loading the model…"}</p>
        : <EditorV2 key={seed?.model.id ?? "new"} initial={seed ?? emptyModelV2()} editing={!!modelId} />)}
    </div>
  );
}

// ------------------------------------------------------------------------- upload

interface ConvertOptions { topology: string; keep_markers: boolean; system_kind: string; beamline: string; same_element_suffixes: string }
interface UploadedFile { name: string; models: CanonicalBeamModel[]; error?: string; via?: string; report?: BeamConversionReport }

function Upload({ onEdit }: { onEdit: (m: BeamModelV2) => void }) {
  const qc = useQueryClient();
  const [raw, setRaw] = useState<{ name: string; text: string }[]>([]);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [opts, setOpts] = useState<ConvertOptions>({ topology: "auto", keep_markers: true, system_kind: "", beamline: "", same_element_suffixes: "" });
  const formats = useQuery({ queryKey: ["beam-formats"], queryFn: beamModelApi.formats });
  const docs = files.flatMap((f) => f.models);
  const check = useQuery({
    queryKey: ["beam-validate", JSON.stringify(docs.map((d) => [d.model?.id, (d as { elements?: unknown[] }).elements?.length,
                                                               (d as { components?: unknown[] }).components?.length]))],
    queryFn: () => beamModelApi.validate(docs),
    enabled: docs.length > 0,
  });
  const run = useMutation({
    mutationFn: () => beamModelApi.importModels(docs),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["beam-systems"] }),
  });
  const reports: BeamImportReport[] = run.data ? ("models" in run.data ? run.data.models : [run.data]) : [];
  const allOk = check.data?.models.every((m) => m.ok);

  const read = async (list: FileList | null) => {
    setRaw(await Promise.all(Array.from(list ?? []).map(async (f) => ({ name: f.name, text: await f.text() }))));
    run.reset();
  };
  // Canonical JSON is read as it is; any other file goes through the converter for its simulator, again
  // whenever the options change. Nothing is written until Import.
  useEffect(() => {
    let live = true;
    void Promise.all(raw.map(async ({ name, text }): Promise<UploadedFile> => {
      if (name.toLowerCase().endsWith(".json")) {
        try {
          const parsed = JSON.parse(text);
          const bundle = parsed?.format === "argus.beam-model-bundle/1" || parsed?.schema_version === "argus.beam-model-bundle/2";
          const models: CanonicalBeamModel[] = Array.isArray(parsed) ? parsed : bundle ? parsed.models : [parsed];
          return { name, models, via: "argus" };
        } catch (e) {
          return { name, models: [], error: `not JSON: ${e instanceof Error ? e.message : e}` };
        }
      }
      try {
        const out = await beamModelApi.convert(name, text, {
          topology: opts.topology, keep_markers: opts.keep_markers, ...(opts.system_kind ? { system_kind: opts.system_kind } : {}),
          ...(opts.beamline ? { beamline: opts.beamline } : {}),
          ...(opts.same_element_suffixes.trim() ? { same_element_suffixes: opts.same_element_suffixes } : {}),
        });
        return { name, models: [out.model], via: out.report.converter, report: out.report };
      } catch (e) {
        return { name, models: [], error: errorText(e) };
      }
    })).then((r) => { if (live) setFiles(r); });
    return () => { live = false; };
  }, [raw, opts]);
  const simulators = raw.some((f) => !f.name.toLowerCase().endsWith(".json"));
  const sequences = [...new Set(files.flatMap((f) => f.report?.sequences ?? []))];

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
      <label className="block text-sm text-slate-700">
        Model files — ARGUS canonical JSON (one model, or a bundle as exported here) or simulator files, converted on
        upload and shown before anything is imported
        <input type="file" multiple onChange={(e) => void read(e.target.files)} className="mt-2 block text-sm"
               accept={(formats.data ?? []).flatMap((f) => f.extensions).join(",") || ".json"} />
      </label>
      <p className="text-xs text-slate-500">
        Read: {(formats.data ?? []).map((f) => f.label).join(" · ")}. The format is described in{" "}
        <button type="button" className="text-indigo-700 hover:underline"
                onClick={() => void beamModelApi.schema().then((x) => download("argus.beam-model-2.schema.json", x))}>its JSON Schema</button>{" "}
        and docs/beam-model-format.md.
      </p>
      {simulators && (
        <div className="flex flex-wrap items-end gap-3 rounded bg-slate-50 p-2 text-xs">
          <span className="font-medium text-slate-600">Simulator files:</span>
          <label>Topology{" "}
            <select value={opts.topology} onChange={(e) => setOpts({ ...opts, topology: e.target.value })} className="rounded border border-slate-300 px-1 py-0.5">
              <option value="auto">from the bends (a full turn is a ring)</option><option value="closed">closed (ring)</option><option value="open">open (line)</option>
            </select>
          </label>
          <label>System kind{" "}
            <input value={opts.system_kind} placeholder="e.g. Accumulator" onChange={(e) => setOpts({ ...opts, system_kind: e.target.value })}
                   className="w-36 rounded border border-slate-300 px-1 py-0.5" />
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={opts.keep_markers} onChange={(e) => setOpts({ ...opts, keep_markers: e.target.checked })} />
            keep markers
          </label>
          {sequences.length > 1 && (
            <label>Sequences{" "}
              <select value={opts.beamline} onChange={(e) => setOpts({ ...opts, beamline: e.target.value })} className="rounded border border-slate-300 px-1 py-0.5">
                <option value="">all, a path each</option>
                {sequences.map((s) => <option key={s} value={s}>only {s.toUpperCase()}</option>)}
              </select>
            </label>
          )}
          <label title="Name endings that mark one physical element in several configurations: DHPTT001_IN and DHPTT001_OUT become DHPTT001, each path keeping its own values.">
            Same element, name endings{" "}
            <input value={opts.same_element_suffixes} placeholder="e.g. _IN, _OUT" onChange={(e) => setOpts({ ...opts, same_element_suffixes: e.target.value })}
                   className="w-28 rounded border border-slate-300 px-1 py-0.5" />
          </label>
        </div>
      )}
      {files.some((f) => f.error) && (
        <ul className="text-sm text-rose-700">{files.filter((f) => f.error).map((f) => <li key={f.name}>{f.name}: {f.error}</li>)}</ul>
      )}
      {files.some((f) => f.report) && (
        <ul className="space-y-0.5 text-xs text-slate-600">
          {files.filter((f) => f.report).map((f) => (
            <li key={f.name}>
              <span className="font-medium">{f.name}</span> read as {f.via}: {f.report!.elements} elements
              {f.report!.paths ? `, placed ${f.report!.placements} times on ${f.report!.paths.length} paths` : f.report!.ring ? `, a ring (bends total ${(f.report!.total_bend * 180 / Math.PI).toFixed(1)}°, layout closes within ${f.report!.survey_closure_m?.toFixed(3)} m)` : ", a line"}
              {f.report!.chosen && f.report!.sequences ? <span className="text-amber-700"> · only {f.report!.chosen.toUpperCase()} of {f.report!.sequences.length} sequences</span> : null}
              {f.report!.conflicts?.length ? <span className="text-rose-700"> · {f.report!.conflicts.length} name(s) with two types, the first stays: {f.report!.conflicts.slice(0, 5).map((c) => `${c.component} (${c.kept}, ${c.also})`).join("; ")}</span> : null}
              {f.report!.differs?.length ? <span className="text-amber-700"> · {new Set(f.report!.differs.map((d) => d.component)).size} element(s) with different values per path: {[...new Set(f.report!.differs.map((d) => d.component))].slice(0, 8).join(", ")}</span> : null}
              {f.report!.not_executed?.length ? <span className="text-amber-700"> · not executed: {f.report!.not_executed.join("; ")}</span> : null}
            </li>
          ))}
        </ul>
      )}
      {check.data && (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-slate-500"><th>Model</th><th>Systems</th><th>Paths</th><th>Components</th><th>Datasets</th><th>Check</th><th /></tr></thead>
          <tbody>
            {check.data.models.map((m) => (
              <tr key={m.index} className="border-t border-slate-100 align-top">
                <td className="py-1 font-medium">{m.model ?? `#${m.index + 1}`}</td>
                <td>{m.summary?.systems ?? "—"}</td><td>{m.summary?.paths ?? "—"}</td>
                <td>{m.summary?.elements ?? "—"}</td><td>{m.summary?.datasets ?? "—"}</td>
                <td className={m.ok ? "text-emerald-700" : "text-rose-700"}>
                  {m.ok ? `ok${m.levels ? ` · ${m.levels.join(", ")}` : ""}${m.format === "1" ? " · v1, upgraded" : ""}` : m.problems.join("; ")}
                  {(m.warnings ?? []).length > 0 && <div className="text-xs text-amber-700">{m.warnings!.length} warning(s): {m.warnings!.slice(0, 2).join("; ")}</div>}
                </td>
                <td>
                  <button type="button" onClick={() => void beamModelApi.upgrade(docs[m.index]).then(onEdit)}
                          className="text-xs text-indigo-700 hover:underline">open in editor</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {docs.length > 0 && (
        <div className="flex items-center gap-3">
          <button type="button" disabled={!allOk || run.isPending || reports.length > 0} onClick={() => run.mutate()}
                  className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300">
            {run.isPending ? "Importing…" : `Import ${docs.length} model${docs.length > 1 ? "s" : ""}`}
          </button>
          {!allOk && check.data && <span className="text-xs text-slate-500">All must pass: nothing is imported while one fails.</span>}
          {run.isError && <span className="text-sm text-rose-700">{errorText(run.error)}</span>}
        </div>
      )}
      <ImportReports reports={reports} />
    </div>
  );
}

export function ImportReports({ reports }: { reports: BeamImportReport[] }) {
  if (!reports.length) return null;
  return (
    <div className="rounded bg-emerald-50 p-3 text-sm text-emerald-900">
      {reports.map((r) => (
        <div key={r.model}>
          <b>{r.model}</b>: {r.state === "published"
            ? <>{r.state} — {r.elements} elements, {r.values} dataset values</>
            : <span className="text-amber-800">not applied yet — it removes records that need a person&apos;s approval,
                so nothing has changed. <Link to="/review" className="underline">Approve it in the review queue</Link>, then import again.</span>}
          {r.awaiting_policy && <span className="text-amber-800"> · waiting for the authority policy to cover this source</span>}
        </div>
      ))}
      <Link to="/beam-model" className="mt-1 inline-block text-indigo-700 hover:underline">Open the beam model →</Link>
    </div>
  );
}

// The editor itself is BeamModelEditorV2.tsx (argus.beam-model/2).
