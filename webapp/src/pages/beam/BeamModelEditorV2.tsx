import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, beamModelApi } from "../../api/client";
import type {
  BeamImportReport, BeamModelCheck, BeamModelV2, BeamVocabulary, V2Boundary, V2Component, V2Dataset, V2Definition,
  V2Field, V2Path, V2Placement, V2Profile, V2Provenance, V2StateModel,
} from "../../api/types";

/** The beam model editor for argus.beam-model/2 (docs/beam-model-format.md). It edits the document an import
 *  reads: beams, systems, paths of placements (a component may be on several paths), the connections between
 *  paths, each component — type, capabilities, aliases, supports, fiducials, boundaries, material, states,
 *  measurement model —, the definitions components instantiate, and the datasets: their provenance, every
 *  value (s, reference trajectory, physics, optics) and the fields along a path. What it does not show
 *  (bindings, provenance, a tool's own fields) is passed through untouched, so saving never loses what came in. */
const DATASET_KINDS = ["design", "nominal", "commissioning", "measured", "current_model", "operational", "simulation",
  "snapshot"];
const DATASET_CATEGORIES = ["", "lattice", "optics", "survey", "orbit", "dispersion", "aperture", "field_map",
  "envelope", "vacuum", "measured_optics"];

const SYSTEM_KINDS = ["Storage ring", "Synchrotron", "Accumulator", "Collider", "Linac", "Transfer line",
  "Laser transport", "FEL line", "Injector", "Experimental line", "Other"];
/** The strength a type is usually given, offered as a column. */
const STRENGTH: Record<string, string> = {
  quadrupole: "k1", sextupole: "k2", octupole: "k3", dipole: "angle", corrector: "kick", kicker: "kick",
  rf_cavity: "voltage", accelerating_structure: "voltage", buncher: "voltage", rf_deflector: "voltage",
  crab_cavity: "voltage", solenoid: "ks", lens: "focal_length", beam_splitter: "split_ratio", mirror: "incidence_angle",
};

export function emptyModelV2(): BeamModelV2 {
  return {
    schema_version: "argus.beam-model/2",
    model: { id: "", name: "", source: "argus-editor", version: "1" },
    systems: [{ id: "main", name: "", kind: "Linac", beams: ["beam"] }],
    beams: [{ id: "beam", kind: "particle", species: "electron", systems: ["main"] }],
    paths: [{ id: "line", name: "", system: "main", topology: "open", placements: [] }],
    connections: [],
    components: [],
    datasets: [],
  };
}

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
type Update = (fn: (d: BeamModelV2) => void) => void;

function placements(p: V2Path): V2Placement[] {
  return p.placements.map((x) => (typeof x === "string" ? { component: x } : x));
}

/** Placement ids as the model resolves them: the component, then `ID#2` for a second pass. */
function placementIds(p: V2Path): string[] {
  const seen: Record<string, number> = {};
  return placements(p).map((pl) => {
    seen[pl.component] = (seen[pl.component] ?? 0) + 1;
    return pl.id ?? (seen[pl.component] === 1 ? pl.component : `${pl.component}#${seen[pl.component]}`);
  });
}

function setPlacements(p: V2Path, list: V2Placement[]) {
  p.placements = list.map((pl) => (Object.keys(pl).filter((k) => (pl as unknown as Record<string, unknown>)[k] !== undefined
    && !(k === "reversed" && !pl.reversed)).length === 1 ? pl.component : pl));
}

function familyOf(vocab: BeamVocabulary | undefined, type: string | undefined): string {
  if (!vocab || !type) return "generic";
  return Object.entries(vocab.families).find(([, ts]) => type in ts)?.[0] ?? "generic";
}

function capsOf(vocab: BeamVocabulary | undefined, c: V2Component): string[] {
  if (c.capabilities) return c.capabilities;
  const fam = familyOf(vocab, c.type);
  return vocab?.families[fam]?.[c.type ?? ""] ?? [];
}

function pathDataset(doc: BeamModelV2, pathId: string): V2Dataset | undefined {
  const all = (doc.datasets ?? []).filter((d) => d.path === pathId);
  return all.find((d) => Object.keys(d.values ?? {}).length > 0) ?? all[0];
}

function ensureDataset(d: BeamModelV2, pathId: string, datasetId?: string): V2Dataset {
  d.datasets = d.datasets ?? [];
  let ds = (datasetId ? d.datasets.find((x) => x.id === datasetId) : undefined) ?? pathDataset(d, pathId);
  if (!ds) {
    const p = d.paths.find((x) => x.id === pathId)!;
    ds = { id: `${pathId}-design`, name: `${p.name || p.id} design`, kind: "design", path: pathId, values: {} };
    d.datasets.push(ds);
  }
  ds.values = ds.values ?? {};
  return ds;
}

function newId(d: BeamModelV2, prefix = "E"): string {
  let n = d.components.length + 1;
  while (d.components.some((c) => c.id === `${prefix}${String(n).padStart(3, "0")}`)) n++;
  return `${prefix}${String(n).padStart(3, "0")}`;
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const b = e.body as { detail?: unknown } | undefined;
    const d = b?.detail as { problems?: string[]; models?: BeamModelCheck[] } | string | undefined;
    if (typeof d === "string") return d;
    if (d?.problems) return d.problems.join("; ");
    if (d?.models) return d.models.filter((m) => !m.ok).map((m) => m.problems.join("; ")).join(" · ");
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

/** What is sent: empty names dropped, empty datasets left out, observables used but not built in declared. */
export function tidyV2(doc: BeamModelV2, vocab?: BeamVocabulary): BeamModelV2 {
  const d = clone(doc);
  const strip = (o: { name?: string }) => { if (!o.name) delete o.name; };
  d.systems.forEach(strip);
  d.paths.forEach(strip);
  d.components.forEach(strip);
  d.beams.forEach(strip);
  if (!d.model.name) delete d.model.name;
  d.datasets = (d.datasets ?? []).filter((x) => Object.keys(x.values ?? {}).length > 0 || Object.keys(x).some(
    (k) => !["id", "name", "kind", "path", "values"].includes(k)));
  const builtIn = new Set(Object.keys(vocab?.observables ?? {}));
  const declared = new Set((d.observables ?? []).map((o) => o.quantity));
  for (const q of d.components.flatMap((c) => c.observes ?? [])) {
    if (!declared.has(q) && !builtIn.has(q)) {
      d.observables = [...(d.observables ?? []), { quantity: q }];
      declared.add(q);
    }
  }
  return d;
}

// ------------------------------------------------------------------------- the editor

export function EditorV2({ initial, editing }: { initial: BeamModelV2; editing: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const vocab = useQuery({ queryKey: ["beam-vocabulary"], queryFn: beamModelApi.vocabulary, staleTime: Infinity });
  const [doc, setDoc] = useState<BeamModelV2>(() => normalise(clone(initial)));
  const [pathId, setPathId] = useState(initial.paths[0]?.id ?? "");
  const [selected, setSelectedComponent] = useState<string | null>(null);
  const [selectedDef, setSelectedDef] = useState<string | null>(null);
  const setSelected = (id: string | null) => { setSelectedComponent(id); if (id) setSelectedDef(null); };
  const pickDef = (id: string | null) => { setSelectedDef(id); if (id) setSelectedComponent(null); };
  const [writeTo, setWriteTo] = useState<Record<string, string>>({});     // path → the dataset its table writes
  const update: Update = (fn) => setDoc((d) => { const n = clone(d); fn(n); return n; });
  const check = useMutation({ mutationFn: () => beamModelApi.validate(tidyV2(doc, vocab.data)) });
  const save = useMutation({
    mutationFn: () => beamModelApi.importModels(tidyV2(doc, vocab.data)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["beam-systems"] });
      void qc.invalidateQueries({ queryKey: ["beam-model-export"] });
    },
  });
  const report = save.data && !("models" in save.data) ? (save.data as BeamImportReport) : null;
  const path = doc.paths.find((p) => p.id === pathId);
  const placed = useMemo(() => new Set(doc.paths.flatMap((p) => placements(p).map((pl) => pl.component))), [doc.paths]);
  const offPath = doc.components.filter((c) => !placed.has(c.id));
  const verdict = check.data?.models[0];

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
      <div className="min-w-0 space-y-4">
        <ModelBox doc={doc} update={update} editing={editing} />
        <BeamsBox doc={doc} update={update} />
        <SystemsBox doc={doc} update={update} />

        <Box title="Paths" action={<Small onClick={() => update((d) => {
          let n = d.paths.length + 1;
          while (d.paths.some((p) => p.id === `path${n}`)) n++;
          d.paths.push({ id: `path${n}`, system: d.systems[0]?.id, topology: "open", placements: [] });
          setPathId(`path${n}`);
        })}>+ path</Small>}>
          <div className="flex flex-wrap gap-2">
            {doc.paths.map((p) => (
              <button key={p.id} type="button" onClick={() => setPathId(p.id)}
                      className={`rounded border px-2 py-1 text-sm ${p.id === pathId ? "border-slate-900 bg-slate-900 text-white" : "border-slate-300"}`}>
                {p.name || p.id} · {p.topology} · {p.placements.length}
              </button>
            ))}
          </div>
          {path && (
            <PathEditor doc={doc} path={path} vocab={vocab.data} update={update} selected={selected} onSelect={setSelected}
                        datasetId={writeTo[path.id]} onDataset={(id) => setWriteTo({ ...writeTo, [path.id]: id })}
                        onRenamed={setPathId} onRemoved={() => setPathId(doc.paths.find((p) => p.id !== path.id)?.id ?? "")} />
          )}
        </Box>

        <ConnectionsBox doc={doc} update={update} />

        <Box title="Components not on any path" action={
          <span className="flex gap-1">
            {(["girder", "support", "mover", "fiducial", "alignment_reference"] as const).map((t) => (
              <Small key={t} onClick={() => update((d) => {
                const id = newId(d, t === "fiducial" ? "FID" : t === "girder" ? "GIR" : "SUP");
                d.components.push({ id, type: t });
                setSelected(id);
              })}>+ {t.replace("_", " ")}</Small>
            ))}
          </span>}>
          {offPath.length === 0 ? <p className="text-xs text-slate-400">None: supports, girders and fiducials that carry or locate components live here.</p> : (
            <div className="flex flex-wrap gap-1">
              {offPath.map((c) => (
                <button key={c.id} type="button" onClick={() => setSelected(c.id)}
                        className={`rounded border px-2 py-0.5 text-xs ${selected === c.id ? "border-indigo-500 bg-indigo-50" : "border-slate-300"}`}>
                  <span className="font-mono">{c.id}</span> <span className="text-slate-400">{c.type}</span>
                </button>
              ))}
            </div>
          )}
        </Box>

        <DefinitionsBox doc={doc} vocab={vocab.data} update={update} selected={selectedDef} onSelect={pickDef} />
        <DatasetsBox doc={doc} update={update} vocab={vocab.data} />

        <PassedThrough doc={doc} />

        <div className="flex flex-wrap items-center gap-3">
          <button type="button" disabled={!doc.model.id || save.isPending} onClick={() => save.mutate()}
                  className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300">
            {save.isPending ? "Saving…" : editing ? "Save changes" : "Create model"}
          </button>
          <button type="button" disabled={!doc.model.id || check.isPending} onClick={() => check.mutate()}
                  className="rounded border border-slate-300 px-3 py-2 text-sm">Check</button>
          <button type="button" onClick={() => downloadJson(`${doc.model.id || "beam-model"}.beam.json`, tidyV2(doc, vocab.data))}
                  className="rounded border border-slate-300 px-3 py-2 text-sm">Download .beam.json</button>
          {save.isError && <span className="text-sm text-rose-700">{errorText(save.error)}</span>}
          {report && report.state !== "published" && (
            <span className="text-sm text-amber-800" role="status">
              Not applied yet: this save removes records that need a person&apos;s approval, so nothing has changed.{" "}
              <button type="button" className="underline" onClick={() => navigate("/review")}>Approve it in the review queue</button>
              , then save again.
            </span>
          )}
          {report && report.state === "published" && (
            <span className="text-sm text-emerald-700">
              Saved: {report.elements} components, {report.values} values{report.levels ? ` · ${report.levels.join(", ")}` : ""}.{" "}
              <button type="button" className="underline" onClick={() => navigate("/beam-model")}>Open the beam model</button>
            </span>
          )}
        </div>
        {verdict && (
          <div className={`rounded border p-3 text-sm ${verdict.ok ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50"}`}>
            {verdict.ok ? <>Valid · levels <b>{(verdict.levels ?? []).join(", ")}</b></> : <span className="text-rose-800">{verdict.problems.join("; ")}</span>}
            {verdict.gaps && Object.keys(verdict.gaps).length > 0 && (
              <ul className="mt-1 text-xs text-slate-600">
                {Object.entries(verdict.gaps).map(([lvl, g]) => <li key={lvl}><b>{lvl}</b> needs: {g.slice(0, 8).join(", ")}{g.length > 8 ? "…" : ""}</li>)}
              </ul>
            )}
            {(verdict.warnings ?? []).length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-amber-800">{verdict.warnings!.map((w) => <li key={w}>{w}</li>)}</ul>}
          </div>
        )}
      </div>

      <aside className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-6rem)] xl:self-start xl:overflow-y-auto">
        {selectedDef && (doc.definitions ?? []).some((x) => x.id === selectedDef)
          ? <DefinitionPanel doc={doc} id={selectedDef} vocab={vocab.data} update={update} onRenamed={pickDef} onClose={() => pickDef(null)} />
          : selected && doc.components.some((c) => c.id === selected)
          ? <ComponentPanel doc={doc} id={selected} vocab={vocab.data} update={update} onRenamed={setSelected} onClose={() => setSelected(null)}
                            onDefinition={pickDef} />
          : <p className="rounded border border-dashed border-slate-300 p-4 text-xs text-slate-500">
              Select a component (its row, or a chip above) to edit what a table cannot show: aliases, capabilities,
              supports and fiducials, boundaries, material, states, measurement model, parameters.
            </p>}
      </aside>
    </div>
  );
}

/** Older documents may hold systems without beam lists or paths without connections: fill the gaps once. */
function normalise(d: BeamModelV2): BeamModelV2 {
  d.systems = d.systems ?? [];
  d.beams = d.beams ?? [];
  d.paths = (d.paths ?? []).map((p) => ({ ...p, placements: p.placements ?? [], topology: p.topology ?? "open" }));
  d.connections = d.connections ?? [];
  d.components = d.components ?? [];
  return d;
}

// ------------------------------------------------------------------------- model, beams, systems

function ModelBox({ doc, update, editing }: { doc: BeamModelV2; update: Update; editing: boolean }) {
  return (
    <Box title="Model">
      <div className="grid gap-2 sm:grid-cols-5">
        <Field label="Id" value={doc.model.id} disabled={editing} placeholder="e.g. sparc-linac" onChange={(v) => update((d) => { d.model.id = v.trim(); })} />
        <Field label="Name" value={doc.model.name ?? ""} onChange={(v) => update((d) => { d.model.name = v; })} />
        <Field label="Version" value={doc.model.version ?? ""} onChange={(v) => update((d) => { d.model.version = v; })} />
        <Field label="Source" value={doc.model.source ?? ""} onChange={(v) => update((d) => { d.model.source = v; })} />
        <Field label="Simulator" value={doc.model.simulator ?? ""} placeholder="madx, xsuite, bmad…" onChange={(v) => update((d) => { d.model.simulator = v || undefined; })} />
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-4">
        <Field label="Facility id" value={doc.facility?.id ?? ""} placeholder="e.g. dafne" onChange={(v) => update((d) => {
          if (!v.trim()) { delete d.facility; return; }
          d.facility = { ...(d.facility ?? {}), id: v.trim() };
        })} />
        <Field label="Facility name" value={doc.facility?.name ?? ""} disabled={!doc.facility} onChange={(v) => update((d) => { if (d.facility) d.facility.name = v || undefined; })} />
        <Field label="Namespace" value={doc.facility?.namespace ?? ""} disabled={!doc.facility} placeholder="dafne/accumulator" onChange={(v) => update((d) => { if (d.facility) d.facility.namespace = v || undefined; })} />
        <Field label="Site" value={doc.facility?.site ?? ""} disabled={!doc.facility} onChange={(v) => update((d) => { if (d.facility) d.facility.site = v || undefined; })} />
      </div>
      <JsonField label="Provenance of the document (JSON: converter, source files, a tool's notes)" value={doc.provenance}
                 onChange={(v) => update((d) => { if (v && Object.keys(v).length) d.provenance = v; else delete d.provenance; })} />
    </Box>
  );
}

function num(v: string): number | undefined {
  return v.trim() === "" || Number.isNaN(Number(v)) ? undefined : Number(v);
}

function BeamsBox({ doc, update }: { doc: BeamModelV2; update: Update }) {
  return (
    <Box title="Beams" action={<Small onClick={() => update((d) => {
      let n = d.beams.length + 1;
      while (d.beams.some((b) => b.id === `beam${n}`)) n++;
      d.beams.push({ id: `beam${n}`, kind: "particle", systems: [] });
    })}>+ beam</Small>}>
      {doc.beams.length === 0 && <p className="text-xs text-slate-400">No beam: a model may describe topology alone.</p>}
      <table className="w-full text-xs">
        {doc.beams.length > 0 && (
          <thead><tr className="text-left text-slate-500"><th>Id</th><th>Kind</th><th>Species</th><th>Charge (e)</th>
            <th>Energy (GeV)</th><th>Wavelength (nm)</th><th>Other parameters</th><th /></tr></thead>
        )}
        <tbody>
          {doc.beams.map((b, i) => (
            <tr key={i} className="border-t border-slate-100">
              <td><Cell value={b.id} mono onCommit={(v) => update((d) => renameBeam(d, i, v.trim()))} /></td>
              <td>
                <select value={b.kind ?? "particle"} onChange={(e) => update((d) => { d.beams[i].kind = e.target.value as "particle" | "photon"; })}
                        className="rounded border border-slate-300 px-1 py-0.5">
                  <option value="particle">particle</option><option value="photon">photon</option>
                </select>
              </td>
              <td><Cell value={b.species ?? ""} placeholder={b.kind === "photon" ? "photon" : "electron"} onCommit={(v) => update((d) => { d.beams[i].species = v || undefined; })} narrow /></td>
              <td><Cell value={b.charge?.toString() ?? ""} onCommit={(v) => update((d) => { d.beams[i].charge = num(v); })} narrow /></td>
              <td><Cell value={b.reference_energy?.toString() ?? ""} onCommit={(v) => update((d) => { d.beams[i].reference_energy = num(v); })} narrow /></td>
              <td><Cell value={b.wavelength?.toString() ?? ""} onCommit={(v) => update((d) => { d.beams[i].wavelength = num(v); })} narrow /></td>
              <td><Cell value={kv(b.parameters ?? {})} placeholder="pulse_duration_fs=30" onCommit={(v) => update((d) => { d.beams[i].parameters = parseKv(v); })} /></td>
              <td><Icon title="remove" onClick={() => update((d) => {
                const id = d.beams[i].id;
                d.beams.splice(i, 1);
                d.systems.forEach((s) => { s.beams = (s.beams ?? []).filter((x) => x !== id); });
                d.paths.forEach((p) => { if (p.beams) p.beams = p.beams.filter((x) => x !== id); });
              })}>✕</Icon></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Box>
  );
}

function renameBeam(d: BeamModelV2, i: number, v: string) {
  if (!v || d.beams.some((b, j) => j !== i && b.id === v)) return;
  const old = d.beams[i].id;
  d.beams[i].id = v;
  d.systems.forEach((s) => { s.beams = (s.beams ?? []).map((x) => (x === old ? v : x)); });
  d.paths.forEach((p) => { if (p.beams) p.beams = p.beams.map((x) => (x === old ? v : x)); });
}

function SystemsBox({ doc, update }: { doc: BeamModelV2; update: Update }) {
  return (
    <Box title="Systems" action={<Small onClick={() => update((d) => {
      let n = d.systems.length + 1;
      while (d.systems.some((s) => s.id === `system${n}`)) n++;
      d.systems.push({ id: `system${n}`, kind: "Other", beams: [] });
    })}>+ system</Small>}>
      <datalist id="system-kinds">{SYSTEM_KINDS.map((k) => <option key={k} value={k} />)}</datalist>
      {doc.systems.map((s, i) => (
        <div key={i} className="mb-2 grid gap-2 rounded border border-slate-100 p-2 sm:grid-cols-4">
          <Field label="Id" value={s.id} onChange={(v) => update((d) => {
            const old = d.systems[i].id;
            d.systems[i].id = v;
            d.paths.forEach((p) => { if (p.system === old) p.system = v; });
            d.beams.forEach((b) => { if (b.systems) b.systems = b.systems.map((x) => (x === old ? v : x)); });
          })} />
          <Field label="Name" value={s.name ?? ""} onChange={(v) => update((d) => { d.systems[i].name = v; })} />
          <label className="block text-xs text-slate-500">Kind
            <input list="system-kinds" value={s.kind ?? ""} onChange={(e) => update((d) => { d.systems[i].kind = e.target.value; })}
                   className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900" />
          </label>
          <div className="text-xs text-slate-500">Beams
            <div className="mt-1 flex flex-wrap items-center gap-1">
              {doc.beams.map((b) => {
                const on = (s.beams ?? []).includes(b.id);
                return (
                  <button key={b.id} type="button" onClick={() => update((d) => {
                    const sys = d.systems[i];
                    sys.beams = on ? (sys.beams ?? []).filter((x) => x !== b.id) : [...(sys.beams ?? []), b.id];
                  })} className={`rounded-full px-2 py-0.5 ${on ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>{b.id}</button>
                );
              })}
              {doc.systems.length > 1 && <Small danger onClick={() => update((d) => {
                const id = d.systems[i].id;
                d.systems.splice(i, 1);
                d.paths.forEach((p) => { if (p.system === id) delete p.system; });
              })}>remove</Small>}
            </div>
          </div>
        </div>
      ))}
    </Box>
  );
}

// ------------------------------------------------------------------------- one path

function PathEditor({ doc, path, vocab, update, selected, onSelect, onRenamed, onRemoved, datasetId, onDataset }: {
  doc: BeamModelV2; path: V2Path; vocab?: BeamVocabulary; update: Update; selected: string | null;
  onSelect: (id: string) => void; onRenamed: (id: string) => void; onRemoved: () => void;
  datasetId?: string; onDataset: (id: string) => void;
}) {
  const byId = useMemo(() => new Map(doc.components.map((c) => [c.id, c])), [doc.components]);
  const pls = placements(path);
  const pids = placementIds(path);
  const ds = (datasetId ? (doc.datasets ?? []).find((x) => x.id === datasetId && x.path === path.id) : undefined)
    ?? pathDataset(doc, path.id);
  const forPath = (doc.datasets ?? []).filter((x) => x.path === path.id);
  const [adding, setAdding] = useState("");
  const withPath = (fn: (p: V2Path, d: BeamModelV2) => void) => update((d) => fn(d.paths.find((x) => x.id === path.id)!, d));
  const otherPaths = (cid: string) => doc.paths.filter((p) => p.id !== path.id && placements(p).some((pl) => pl.component === cid)).map((p) => p.name || p.id);

  const setValue = (pid: string, key: string, raw: string) => update((d) => {
    const dataset = ensureDataset(d, path.id, ds?.id);
    const v = (dataset.values![pid] = dataset.values![pid] ?? {});
    const n = num(raw);
    if (key === "s") v.s = n ?? null;
    else {
      v.physics = { ...(v.physics ?? {}) };
      if (n === undefined) delete v.physics[key];
      else v.physics[key] = n;
    }
  });
  const insert = (after: number, component: string, create?: string) => update((d) => {
    const p = d.paths.find((x) => x.id === path.id)!;
    let cid = component;
    if (create) {
      cid = newId(d);
      d.components.push({ id: cid, type: create });
    }
    const list = placements(p);
    list.splice(after + 1, 0, { component: cid });
    setPlacements(p, list);
    onSelect(cid);
  });
  const move = (i: number, by: number) => withPath((p) => {
    const list = placements(p);
    const j = i + by;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    setPlacements(p, list);
  });
  const remove = (i: number) => update((d) => {
    const p = d.paths.find((x) => x.id === path.id)!;
    const list = placements(p);
    const pid = placementIds(p)[i];
    const [gone] = list.splice(i, 1);
    setPlacements(p, list);
    (d.datasets ?? []).filter((x) => x.path === path.id).forEach((x) => { if (x.values) delete x.values[pid]; });
    if (p.reference === pid || p.reference === gone.component) delete p.reference;
    const stillPlaced = d.paths.some((q) => placements(q).some((pl) => pl.component === gone.component));
    const referenced = d.components.some((c) => c.mounted_on === gone.component || c.contained_in === gone.component
      || (c.fiducials ?? []).includes(gone.component));
    d.connections = d.connections.filter((c) => !((c.from.path === path.id && (c.from.component === pid || c.from.component === gone.component))
      || (c.to.path === path.id && (c.to.component === pid || c.to.component === gone.component))));
    if (!stillPlaced && !referenced) {
      d.components = d.components.filter((c) => c.id !== gone.component);
      (d.datasets ?? []).forEach((x) => { if (x.values) delete x.values[gone.component]; });
    }
  });
  const editComponent = (id: string, fn: (c: V2Component) => void) => update((d) => { fn(d.components.find((c) => c.id === id)!); });

  return (
    <div className="mt-3 space-y-3">
      <div className="grid gap-2 sm:grid-cols-6">
        <Field label="Path id" value={path.id} onChange={(v) => {
          if (!v || doc.paths.some((p) => p.id === v)) return;
          update((d) => renamePath(d, path.id, v));
          onRenamed(v);
        }} />
        <Field label="Name" value={path.name ?? ""} onChange={(v) => withPath((p) => { p.name = v; })} />
        <Select label="System" value={path.system ?? ""} options={["", ...doc.systems.map((s) => s.id)]} onChange={(v) => withPath((p) => { if (v) p.system = v; else delete p.system; })} />
        <Select label="Topology" value={path.topology} options={["open", "closed"]} onChange={(v) => withPath((p) => { p.topology = v as "open" | "closed"; })} />
        <Field label="Length (m)" value={path.length?.toString() ?? ""} onChange={(v) => withPath((p) => { const n = num(v); if (n === undefined) delete p.length; else p.length = n; })} />
        <Select label="Reference (s = 0)" value={path.reference ?? ""} options={["", ...pids]} onChange={(v) => withPath((p) => { if (v) p.reference = v; else delete p.reference; })} />
      </div>
      {doc.beams.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 text-xs text-slate-500">Carries:
          {doc.beams.map((b) => {
            const on = (path.beams ?? []).includes(b.id);
            return <button key={b.id} type="button" onClick={() => withPath((p) => { p.beams = on ? (p.beams ?? []).filter((x) => x !== b.id) : [...(p.beams ?? []), b.id]; })}
                           className={`rounded-full px-2 py-0.5 ${on ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>{b.id}</button>;
          })}
        </div>
      )}
      <div className="text-xs text-slate-500">
        Values go into dataset{" "}
        {forPath.length > 1 ? (
          <select value={ds?.id ?? ""} onChange={(e) => onDataset(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5">
            {forPath.map((x) => <option key={x.id} value={x.id}>{x.name ?? x.id} ({x.kind ?? "design"})</option>)}
          </select>
        ) : <b>{ds?.name ?? ds?.id ?? `${path.id}-design`} ({ds?.kind ?? "design"})</b>}
        ; the others are kept as they are (edit any of them under Datasets).
        {doc.paths.length > 1 && <> <Small danger onClick={() => {
          update((d) => {
            const p = d.paths.find((x) => x.id === path.id)!;
            const mine = new Set(placements(p).map((pl) => pl.component));
            d.paths = d.paths.filter((x) => x.id !== path.id);
            const still = new Set(d.paths.flatMap((q) => placements(q).map((pl) => pl.component)));
            d.components = d.components.filter((c) => !mine.has(c.id) || still.has(c.id));
            d.datasets = (d.datasets ?? []).filter((x) => x.path !== path.id);
            d.connections = d.connections.filter((c) => c.from.path !== path.id && c.to.path !== path.id);
            if (d.boundaries) { d.boundaries = d.boundaries.filter((b) => b.path !== path.id); if (!d.boundaries.length) delete d.boundaries; }
          });
          onRemoved();
        }}>remove this path</Small></>}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="w-6">#</th><th>Component</th><th>Name</th><th>Type</th><th>s (m)</th><th>Length (m)</th>
              <th>Strength</th><th>Observes</th><th title="passed backwards on this path">Rev</th><th>Also on</th><th />
            </tr>
          </thead>
          <tbody>
            {pls.map((pl, i) => {
              const c = byId.get(pl.component);
              const pid = pids[i];
              const v = ds?.values?.[pid] ?? {};
              const strength = c?.type ? STRENGTH[c.type] : undefined;
              const diagnostic = c ? capsOf(vocab, c).includes("diagnostic") : false;
              const also = otherPaths(pl.component);
              return (
                <tr key={`${pid}-${i}`} onClick={() => onSelect(pl.component)}
                    className={`cursor-pointer border-t border-slate-100 align-top ${selected === pl.component ? "bg-indigo-50" : "hover:bg-slate-50"}`}>
                  <td className="py-1 text-slate-400">{i + 1}</td>
                  <td><Cell value={pl.component} mono onCommit={(x) => update((d) => renameComponent(d, pl.component, x.trim()))} />
                    {pid !== pl.component && <div className="text-[10px] text-slate-400">{pid}</div>}</td>
                  <td><Cell value={c?.name ?? ""} onCommit={(x) => editComponent(pl.component, (el) => { el.name = x; })} /></td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <TypeSelect vocab={vocab} value={c?.type ?? ""} onChange={(t) => editComponent(pl.component, (el) => {
                      el.type = t;
                      delete el.capabilities;
                    })} />
                  </td>
                  <td><Cell value={v.s?.toString() ?? ""} onCommit={(x) => setValue(pid, "s", x)} narrow /></td>
                  <td><Cell value={(v.physics?.length as number | undefined)?.toString() ?? ""} onCommit={(x) => setValue(pid, "length", x)} narrow /></td>
                  <td>{strength ? (
                    <span className="flex items-center gap-1"><span className="text-slate-400">{strength}</span>
                      <Cell value={(v.physics?.[strength] as number | undefined)?.toString() ?? ""} onCommit={(x) => setValue(pid, strength, x)} narrow /></span>
                  ) : <span className="text-slate-300">—</span>}</td>
                  <td>{diagnostic ? (
                    <Cell value={(c?.observes ?? []).join(", ")} placeholder="beam.position.x, beam.position.y"
                          onCommit={(x) => editComponent(pl.component, (el) => { el.observes = x.split(",").map((q) => q.trim()).filter(Boolean); })} />
                  ) : <span className="text-slate-300">—</span>}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={!!pl.reversed} onChange={(e) => withPath((p) => {
                      const list = placements(p);
                      list[i] = { ...list[i], reversed: e.target.checked || undefined };
                      setPlacements(p, list);
                    })} />
                  </td>
                  <td className="text-[11px] text-violet-700">{also.join(", ")}</td>
                  <td className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <Icon onClick={() => move(i, -1)} title="move up">↑</Icon>
                    <Icon onClick={() => move(i, 1)} title="move down">↓</Icon>
                    <Icon onClick={() => insert(i, "", "drift")} title="add a new component below">+</Icon>
                    <Icon onClick={() => remove(i)} title="remove from this path (the component goes when it is on no other path)">✕</Icon>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Small onClick={() => insert(pls.length - 1, "", "drift")}>+ new component at the end</Small>
        <span className="text-xs text-slate-500">or place an existing one (shared with another path):</span>
        <select value={adding} onChange={(e) => setAdding(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5 text-xs">
          <option value="">choose…</option>
          {doc.components.map((c) => <option key={c.id} value={c.id}>{c.id}{c.type ? ` (${c.type})` : ""}</option>)}
        </select>
        <Small onClick={() => { if (adding) { insert(pls.length - 1, adding); setAdding(""); } }}>place at the end</Small>
      </div>
      <p className="text-xs text-slate-500">
        Order is beam order: each placement follows the one above it{path.topology === "closed" ? ", and the last closes to the first" : ""}.
        A component on several paths (an interaction region) keeps one identity; tick <i>Rev</i> where a beam passes it backwards.
        How paths join is under Connections. Capabilities follow the type unless set in the component's panel.
      </p>
      <PathBoundaries doc={doc} path={path} vocab={vocab} list={doc.boundaries} title="Boundaries along this path"
                      hint="an aperture no single component produces, or one a simulator gives as its own element; s along this path"
                      change={(fn) => update((d) => { d.boundaries = d.boundaries ?? []; fn(d.boundaries); if (!d.boundaries.length) delete d.boundaries; })} />
    </div>
  );
}

function renamePath(d: BeamModelV2, old: string, v: string) {
  d.paths.find((p) => p.id === old)!.id = v;
  (d.datasets ?? []).forEach((ds) => {
    if (ds.path === old) ds.path = v;
    ((ds.fields as { path?: string }[] | undefined) ?? []).forEach((f) => { if (f.path === old) f.path = v; });
    ((ds.boundaries as V2Boundary[] | undefined) ?? []).forEach((b) => { if (b.path === old) b.path = v; });
  });
  d.connections.forEach((c) => { if (c.from.path === old) c.from.path = v; if (c.to.path === old) c.to.path = v; });
  (d.boundaries ?? []).forEach((b) => { if (b.path === old) b.path = v; });
}

function renameComponent(d: BeamModelV2, old: string, v: string) {
  if (!v || v === old || d.components.some((c) => c.id === v)) return;
  d.components.find((c) => c.id === old)!.id = v;
  const swap = (x?: string) => (x === old ? v : x?.startsWith(`${old}#`) ? `${v}${x.slice(old.length)}` : x);
  d.paths.forEach((p) => {
    setPlacements(p, placements(p).map((pl) => ({ ...pl, component: pl.component === old ? v : pl.component, id: swap(pl.id) })));
    p.reference = swap(p.reference);
    if (!p.reference) delete p.reference;
  });
  d.connections.forEach((c) => { c.from.component = swap(c.from.component); c.to.component = swap(c.to.component); });
  d.components.forEach((c) => {
    if (c.mounted_on === old) c.mounted_on = v;
    if (c.contained_in === old) c.contained_in = v;
    if (c.fiducials) c.fiducials = c.fiducials.map((f) => (f === old ? v : f));
    (c.boundaries ?? []).forEach((b) => { if (b.component === old) b.component = v; });
  });
  (d.boundaries ?? []).forEach((b) => { if (b.component === old) b.component = v; });
  (d.datasets ?? []).forEach((ds) => {
    for (const k of Object.keys(ds.values ?? {})) {
      const nk = swap(k)!;
      if (nk !== k) { ds.values![nk] = ds.values![k]; delete ds.values![k]; }
    }
  });
  ((d.external_bindings as { component: string }[] | undefined) ?? []).forEach((b) => { if (b.component === old) b.component = v; });
}

// ------------------------------------------------------------------------- connections

function ConnectionsBox({ doc, update }: { doc: BeamModelV2; update: Update }) {
  const opts = (pathId: string) => {
    const p = doc.paths.find((x) => x.id === pathId);
    return p ? placementIds(p) : [];
  };
  return (
    <Box title="Connections between paths" action={doc.paths.length > 1 ? <Small onClick={() => update((d) => {
      d.connections.push({ kind: "branch", from: { path: d.paths[0].id }, to: { path: d.paths[1].id } });
    })}>+ connection</Small> : undefined}>
      {doc.connections.length === 0 ? (
        <p className="text-xs text-slate-400">
          None. A <b>branch</b> leaves a component (a septum, a beam splitter) for the start of another path; a <b>merge</b>{" "}
          brings a path's end into a component of another (injection); <b>continue</b> joins a path's end to the next one's start.
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th>Kind</th><th>From path</th><th>From</th><th /><th>To path</th><th>To</th><th /></tr></thead>
          <tbody>
            {doc.connections.map((c, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td><select value={c.kind} onChange={(e) => update((d) => { d.connections[i].kind = e.target.value as "branch" | "merge" | "continue"; })} className="rounded border border-slate-300 px-1 py-0.5">
                  <option value="branch">branch</option><option value="merge">merge</option><option value="continue">continue</option></select></td>
                <td><PathPick doc={doc} value={c.from.path} onChange={(v) => update((d) => { d.connections[i].from = { path: v }; })} /></td>
                <td><select value={c.from.component ?? ""} onChange={(e) => update((d) => { d.connections[i].from.component = e.target.value || undefined; })} className="rounded border border-slate-300 px-1 py-0.5">
                  <option value="">its end</option>{opts(c.from.path).map((o) => <option key={o} value={o}>{o}</option>)}</select></td>
                <td className="text-slate-400">→</td>
                <td><PathPick doc={doc} value={c.to.path} onChange={(v) => update((d) => { d.connections[i].to = { path: v }; })} /></td>
                <td><select value={c.to.component ?? ""} onChange={(e) => update((d) => { d.connections[i].to.component = e.target.value || undefined; })} className="rounded border border-slate-300 px-1 py-0.5">
                  <option value="">its start</option>{opts(c.to.path).map((o) => <option key={o} value={o}>{o}</option>)}</select></td>
                <td><Icon title="remove" onClick={() => update((d) => { d.connections.splice(i, 1); })}>✕</Icon></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Box>
  );
}

function PathPick({ doc, value, onChange }: { doc: BeamModelV2; value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5">
      {doc.paths.map((p) => <option key={p.id} value={p.id}>{p.name || p.id}</option>)}
    </select>
  );
}

// ------------------------------------------------------------------------- one component

function ComponentPanel({ doc, id, vocab, update, onRenamed, onClose, onDefinition }: {
  doc: BeamModelV2; id: string; vocab?: BeamVocabulary; update: Update; onRenamed: (id: string) => void; onClose: () => void;
  onDefinition: (id: string) => void;
}) {
  const c = doc.components.find((x) => x.id === id)!;
  const edit = (fn: (el: V2Component) => void) => update((d) => { fn(d.components.find((x) => x.id === id)!); });
  const defaults = vocab?.families[familyOf(vocab, c.type)]?.[c.type ?? ""] ?? [];
  const caps = c.capabilities ?? defaults;
  const fam = familyOf(vocab, c.type);
  const supports = doc.components.filter((x) => x.id !== id && capsOf(vocab, x).includes("mechanical_support"));
  const fiducials = doc.components.filter((x) => x.id !== id && capsOf(vocab, x).includes("survey_reference"));
  const typeStates = c.type ? vocab?.states[c.type] : undefined;
  const stateNames = (c.states?.states ?? []).map((s) => s.name);
  // Boundaries may name a state of the type's default set when the component declares none of its own.
  const boundaryStates = stateNames.length ? stateNames : Object.keys(typeStates ?? {});
  const placedOn = doc.paths.filter((p) => placements(p).some((pl) => pl.component === id)).map((p) => p.name || p.id);

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-mono text-sm font-semibold text-slate-900">{c.id}</div>
          <div className="text-slate-500">{c.type ?? "no type"} · {fam}{placedOn.length ? ` · on ${placedOn.join(", ")}` : " · on no path"}</div>
        </div>
        <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Id" value={c.id} onChange={() => undefined} disabled />
        <label className="block text-xs text-slate-500">Rename to
          <Cell value="" placeholder="new id" onCommit={(v) => { const n = v.trim(); if (n && !doc.components.some((x) => x.id === n)) { update((d) => renameComponent(d, id, n)); onRenamed(n); } }} />
        </label>
        <Field label="Name" value={c.name ?? ""} onChange={(v) => edit((el) => { el.name = v || undefined; })} />
        <label className="block text-xs text-slate-500">Type
          <div className="mt-0.5"><TypeSelect vocab={vocab} value={c.type ?? ""} onChange={(t) => edit((el) => { el.type = t; delete el.capabilities; })} /></div>
        </label>
        <Field label="Model family" value={c.family ?? ""} placeholder="QF" onChange={(v) => edit((el) => { el.family = v || undefined; })} />
        <Select label="Definition" value={c.definition ?? ""} options={["", ...(doc.definitions ?? []).map((x) => x.id)]} onChange={(v) => edit((el) => { el.definition = v || undefined; })} />
      </div>
      <div className="flex flex-wrap gap-2">
        {c.definition && <button type="button" className="text-indigo-700 hover:underline" onClick={() => onDefinition(c.definition!)}>open definition {c.definition}</button>}
        {!c.definition && c.type && <button type="button" className="text-indigo-700 hover:underline" onClick={() => {
          const defId = (c.family || c.id).replace(/#\d+$/, "");
          update((d) => makeDefinition(d, id, defId));
          onDefinition((doc.definitions ?? []).some((x) => x.id === defId) ? `${defId}_DEF` : defId);
        }} title="Copy its type, parameters, length, boundaries, material and states into a definition other components can use">
          make a definition from this component</button>}
      </div>
      <Field label="Aliases (asset tags, control names — evidence for asset matching)" value={(c.aliases ?? []).join(", ")}
             onChange={(v) => edit((el) => { el.aliases = v.split(",").map((x) => x.trim()).filter(Boolean); if (!el.aliases.length) delete el.aliases; })} />

      <Group title="Capabilities" hint={c.capabilities ? "set for this component" : "the type's defaults"}
             action={c.capabilities ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((el) => { delete el.capabilities; })}>use the type's</button> : undefined}>
        <div className="flex flex-wrap gap-1">
          {Object.keys(vocab?.capabilities ?? {}).map((k) => {
            const on = caps.includes(k);
            return (
              <button key={k} type="button" title={vocab?.capabilities[k]} onClick={() => edit((el) => {
                const cur = el.capabilities ?? [...defaults];
                el.capabilities = on ? cur.filter((x) => x !== k) : [...cur, k];
              })} className={`rounded px-1.5 py-0.5 text-[11px] ${on ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500"}`}>{k}</button>
            );
          })}
        </div>
      </Group>

      {caps.includes("diagnostic") && (
        <Group title="Diagnostic">
          <Field label="Observes" value={(c.observes ?? []).join(", ")} placeholder="beam.position.x, beam.position.y"
                 onChange={(v) => edit((el) => { el.observes = v.split(",").map((x) => x.trim()).filter(Boolean); })} />
          <datalist id="observables">{Object.keys(vocab?.observables ?? {}).map((q) => <option key={q} value={q} />)}</datalist>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <Select label="Measurement model" value={c.measurement_model?.type ?? ""} options={["", ...(vocab?.measurement_models ?? [])]}
                    onChange={(v) => edit((el) => { if (v) el.measurement_model = { ...(el.measurement_model ?? {}), type: v, observables: el.measurement_model?.observables ?? el.observes ?? [] }; else delete el.measurement_model; })} />
            {c.measurement_model && <Field label="Derives" value={(c.measurement_model.observables ?? []).join(", ")}
                                           onChange={(v) => edit((el) => { el.measurement_model!.observables = v.split(",").map((x) => x.trim()).filter(Boolean); })} />}
          </div>
        </Group>
      )}

      <Group title="Supports and alignment">
        <div className="grid grid-cols-2 gap-2">
          <Select label="Mounted on" value={c.mounted_on ?? ""} options={["", ...supports.map((x) => x.id)]} onChange={(v) => edit((el) => { el.mounted_on = v || undefined; })} />
          <Select label="Contained in" value={c.contained_in ?? ""} options={["", ...doc.components.filter((x) => x.id !== id).map((x) => x.id)]} onChange={(v) => edit((el) => { el.contained_in = v || undefined; })} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1 text-slate-500">Fiducials:
          {fiducials.length === 0 && <span className="text-slate-400">none in the model</span>}
          {fiducials.map((f) => {
            const on = (c.fiducials ?? []).includes(f.id);
            return <button key={f.id} type="button" onClick={() => edit((el) => { el.fiducials = on ? (el.fiducials ?? []).filter((x) => x !== f.id) : [...(el.fiducials ?? []), f.id]; })}
                           className={`rounded-full px-2 py-0.5 ${on ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>{f.id}</button>;
          })}
        </div>
        <Field label="Length (m, of the object)" value={c.geometry?.length?.toString() ?? ""} onChange={(v) => edit((el) => {
          const n = num(v);
          el.geometry = { ...(el.geometry ?? {}) };
          if (n === undefined) delete el.geometry.length; else el.geometry.length = n;
          if (!Object.keys(el.geometry).length) delete el.geometry;
        })} />
      </Group>

      <BoundariesGroup c={c} vocab={vocab} stateNames={boundaryStates} edit={edit} />
      {(doc.boundaries ?? []).some((b) => b.component === id && !b.path) && (
        <Group title="More boundaries from the model's list" hint="tied to this component, kept in the document's boundaries">
          {(doc.boundaries ?? []).map((b, i) => ({ b, i })).filter(({ b }) => b.component === id && !b.path).map(({ b, i }) => (
            <BoundaryCard key={i} b={b} vocab={vocab} stateNames={boundaryStates}
                          onChange={(fn) => update((d) => { fn(d.boundaries![i]); })}
                          onRemove={() => update((d) => { d.boundaries!.splice(i, 1); if (!d.boundaries!.length) delete d.boundaries; })} />
          ))}
        </Group>
      )}
      <AlignmentGroup c={c} edit={edit} />

      <Group title="Material" action={!c.material ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((el) => { el.material = { material: "" }; })}>add</button>
        : <button type="button" className="text-rose-700 hover:underline" onClick={() => edit((el) => { delete el.material; })}>remove</button>}>
        {c.material && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Material" value={c.material.material} placeholder="YAG:Ce, tungsten…" onChange={(v) => edit((el) => { el.material!.material = v; })} />
            <Field label="Thickness (m)" value={c.material.thickness?.toString() ?? ""} onChange={(v) => edit((el) => { el.material!.thickness = num(v); })} />
            <Field label="Density (g/cm³)" value={c.material.density?.toString() ?? ""} onChange={(v) => edit((el) => { el.material!.density = num(v); })} />
            <Field label="Radiation length (m)" value={c.material.radiation_length?.toString() ?? ""} onChange={(v) => edit((el) => { el.material!.radiation_length = num(v); })} />
          </div>
        )}
      </Group>

      <StatesGroup model={c.states} typeStates={typeStates}
                   onChange={(m) => edit((el) => { if (m) el.states = m; else delete el.states; })} />

      <Group title="Parameters" hint="normalised, not configuration-dependent (those go in a dataset)">
        <Cell value={kv(c.parameters ?? {})} placeholder="length=0.3, gradient=12" onCommit={(v) => edit((el) => { el.parameters = parseKv(v); if (!Object.keys(el.parameters).length) delete el.parameters; })} />
      </Group>
      <ProvenanceGroup prov={c.provenance} keys={["length", ...Object.keys(c.parameters ?? {})]}
                       hint="where its parameters came from"
                       onChange={(pv) => edit((el) => { if (pv) el.provenance = pv; else delete el.provenance; })} />
      <Field label="Description" value={c.description ?? ""} onChange={(v) => edit((el) => { el.description = v || undefined; })} />
      {c.native && (
        <p className="text-[11px] text-slate-400">Native: {c.native.format} {c.native.type} {c.native.name ? `“${c.native.name}”` : ""} {c.native.file ? `· ${c.native.file}` : ""} — kept as it came.</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------- definitions

/** A component's own description moved into a definition it then instantiates (others can share it). */
function makeDefinition(d: BeamModelV2, componentId: string, wanted: string) {
  const c = d.components.find((x) => x.id === componentId)!;
  d.definitions = d.definitions ?? [];
  const id = d.definitions.some((x) => x.id === wanted) ? `${wanted}_DEF` : wanted;
  const def: V2Definition = { id, type: c.type ?? "generic" };
  if (c.capabilities) def.capabilities = c.capabilities;
  if (c.parameters && Object.keys(c.parameters).length) def.parameters = c.parameters;
  if (c.geometry?.length !== undefined) def.geometry = { length: c.geometry.length };
  for (const k of ["boundaries", "material", "states"] as const) {
    if (c[k] !== undefined) (def as Record<string, unknown>)[k] = c[k];
    delete c[k];
  }
  delete c.capabilities;
  delete c.parameters;
  if (c.geometry) { delete c.geometry.length; if (!Object.keys(c.geometry).length) delete c.geometry; }
  c.definition = id;
  d.definitions.push(def);
}

function renameDefinition(d: BeamModelV2, old: string, v: string) {
  if (!v || v === old || (d.definitions ?? []).some((x) => x.id === v)) return;
  d.definitions!.find((x) => x.id === old)!.id = v;
  d.components.forEach((c) => { if (c.definition === old) c.definition = v; });
}

function DefinitionsBox({ doc, vocab, update, selected, onSelect }: {
  doc: BeamModelV2; vocab?: BeamVocabulary; update: Update; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const defs = doc.definitions ?? [];
  const uses = (id: string) => doc.components.filter((c) => c.definition === id).length;
  return (
    <Box title="Definitions" action={<Small onClick={() => update((d) => {
      d.definitions = d.definitions ?? [];
      let n = d.definitions.length + 1;
      while (d.definitions.some((x) => x.id === `DEF${n}`)) n++;
      d.definitions.push({ id: `DEF${n}`, type: "quadrupole" });
      onSelect(`DEF${n}`);
    })}>+ definition</Small>}>
      {defs.length === 0 ? (
        <p className="text-xs text-slate-400">
          None. A definition is what a simulator reuses (a magnet family: type, length, bore, material); components name
          it and override what differs. Make one from a component in its panel, or add one here.
        </p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {defs.map((x) => (
            <button key={x.id} type="button" onClick={() => onSelect(x.id)}
                    className={`rounded border px-2 py-0.5 text-xs ${selected === x.id ? "border-indigo-500 bg-indigo-50" : "border-slate-300"}`}>
              <span className="font-mono">{x.id}</span> <span className="text-slate-400">{x.type} · {uses(x.id)} use{uses(x.id) === 1 ? "" : "s"}</span>
            </button>
          ))}
        </div>
      )}
      {vocab && defs.some((x) => !Object.values(vocab.families).some((ts) => x.type in ts)) && (
        <p className="mt-1 text-xs text-amber-700">Some definitions have a type outside the vocabulary; they are kept as they are.</p>
      )}
    </Box>
  );
}

function DefinitionPanel({ doc, id, vocab, update, onRenamed, onClose }: {
  doc: BeamModelV2; id: string; vocab?: BeamVocabulary; update: Update; onRenamed: (id: string | null) => void; onClose: () => void;
}) {
  const def = (doc.definitions ?? []).find((x) => x.id === id)!;
  const edit = (fn: (x: V2Definition) => void) => update((d) => { fn(d.definitions!.find((x) => x.id === id)!); });
  const users = doc.components.filter((c) => c.definition === id).map((c) => c.id);
  const defaults = vocab?.families[familyOf(vocab, def.type)]?.[def.type] ?? [];
  const caps = def.capabilities ?? defaults;
  const typeStates = vocab?.states[def.type];
  const stateNames = (def.states?.states ?? []).map((x) => x.name);
  const asComponent = def as unknown as V2Component;
  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-400">Definition</div>
          <div className="font-mono text-sm font-semibold text-slate-900">{def.id}</div>
          <div className="text-slate-500">{def.type} · used by {users.length ? users.join(", ") : "no component"}</div>
        </div>
        <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block text-xs text-slate-500">Rename to
          <Cell value="" placeholder="new id" onCommit={(v) => { const n = v.trim(); if (n && !(doc.definitions ?? []).some((x) => x.id === n)) { update((d) => renameDefinition(d, id, n)); onRenamed(n); } }} />
        </label>
        <label className="block text-xs text-slate-500">Type
          <div className="mt-0.5"><TypeSelect vocab={vocab} value={def.type} onChange={(t) => edit((x) => { x.type = t; delete x.capabilities; })} /></div>
        </label>
        <Field label="Name" value={def.name ?? ""} onChange={(v) => edit((x) => { x.name = v || undefined; })} />
        <Field label="Length (m)" value={def.geometry?.length?.toString() ?? ""} onChange={(v) => edit((x) => {
          const n = num(v);
          x.geometry = { ...(x.geometry ?? {}) };
          if (n === undefined) delete x.geometry.length; else x.geometry.length = n;
          if (!Object.keys(x.geometry).length) delete x.geometry;
        })} />
      </div>
      <Group title="Parameters" hint="shared by every instance unless it overrides them">
        <Cell value={kv(def.parameters ?? {})} placeholder="length=0.3, k1=4.3" onCommit={(v) => edit((x) => { x.parameters = parseKv(v); if (!Object.keys(x.parameters).length) delete x.parameters; })} />
      </Group>
      <Group title="Capabilities" hint={def.capabilities ? "set for this definition" : "the type's defaults"}
             action={def.capabilities ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((x) => { delete x.capabilities; })}>use the type's</button> : undefined}>
        <div className="flex flex-wrap gap-1">
          {Object.keys(vocab?.capabilities ?? {}).map((k) => {
            const on = caps.includes(k);
            return <button key={k} type="button" title={vocab?.capabilities[k]} onClick={() => edit((x) => {
              const cur = x.capabilities ?? [...defaults];
              x.capabilities = on ? cur.filter((y) => y !== k) : [...cur, k];
            })} className={`rounded px-1.5 py-0.5 text-[11px] ${on ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500"}`}>{k}</button>;
          })}
        </div>
      </Group>
      <BoundariesGroup c={asComponent} vocab={vocab} stateNames={stateNames.length ? stateNames : Object.keys(typeStates ?? {})}
                       edit={(fn) => edit((x) => fn(x as unknown as V2Component))} />
      <Group title="Material" action={!def.material ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((x) => { x.material = { material: "" }; })}>add</button>
        : <button type="button" className="text-rose-700 hover:underline" onClick={() => edit((x) => { delete x.material; })}>remove</button>}>
        {def.material && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Material" value={def.material.material} onChange={(v) => edit((x) => { x.material!.material = v; })} />
            <Field label="Thickness (m)" value={def.material.thickness?.toString() ?? ""} onChange={(v) => edit((x) => { x.material!.thickness = num(v); })} />
          </div>
        )}
      </Group>
      <StatesGroup model={def.states} typeStates={typeStates}
                   onChange={(m) => edit((x) => { if (m) x.states = m; else delete x.states; })} />
      <ProvenanceGroup prov={def.provenance} keys={["length", ...Object.keys(def.parameters ?? {})]}
                       hint="where its parameters came from"
                       onChange={(pv) => edit((x) => { if (pv) x.provenance = pv; else delete x.provenance; })} />
      {def.native && <p className="text-[11px] text-slate-400">Native: {def.native.format} {def.native.type} {def.native.name ? `“${def.native.name}”` : ""} — kept as it came.</p>}
      <div className="border-t border-slate-100 pt-2">
        <button type="button" className="text-rose-700 hover:underline" onClick={() => {
          update((d) => {
            d.definitions = (d.definitions ?? []).filter((x) => x.id !== id);
            // Instances keep what the definition gave them, so removing it changes no component.
            d.components.forEach((c) => {
              if (c.definition !== id) return;
              delete c.definition;
              c.type = c.type ?? def.type;
              if (!c.parameters && def.parameters) c.parameters = clone(def.parameters);
              if (!c.boundaries && def.boundaries) c.boundaries = clone(def.boundaries);
              if (!c.material && def.material) c.material = clone(def.material);
              if (!c.states && def.states) c.states = clone(def.states);
              if (!c.capabilities && def.capabilities) c.capabilities = clone(def.capabilities);
              if (def.geometry?.length !== undefined && c.geometry?.length === undefined) c.geometry = { ...(c.geometry ?? {}), length: def.geometry.length };
            });
          });
          onClose();
        }}>remove definition</button>
        <span className="ml-1 text-slate-400">(its instances keep what it gave them)</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------- datasets

function renameDataset(d: BeamModelV2, old: string, v: string) {
  if (!v || v === old || (d.datasets ?? []).some((x) => x.id === v)) return;
  d.datasets!.find((x) => x.id === old)!.id = v;
  if (d.model.dataset === old) d.model.dataset = v;
}

const GEOMETRY_KEYS = ["x", "y", "z", "yaw", "pitch", "roll"];

function DatasetsBox({ doc, update, vocab }: { doc: BeamModelV2; update: Update; vocab?: BeamVocabulary }) {
  const datasets = doc.datasets ?? [];
  const [sel, setSel] = useState<string | null>(datasets[0]?.id ?? null);
  const ds = datasets.find((x) => x.id === sel);
  return (
    <Box title="Datasets" action={<Small onClick={() => update((d) => {
      d.datasets = d.datasets ?? [];
      let n = d.datasets.length + 1;
      while (d.datasets.some((x) => x.id === `dataset${n}`)) n++;
      d.datasets.push({ id: `dataset${n}`, kind: "design", path: d.paths[0]?.id, values: {} });
      setSel(`dataset${n}`);
    })}>+ dataset</Small>}>
      <p className="mb-2 text-xs text-slate-500">
        What depends on a configuration — positions, strengths, optics, the reference trajectory, fields along a path —
        so a design lattice, a measurement and next year's version sit side by side on the same components.
      </p>
      <div className="flex flex-wrap gap-1">
        {datasets.map((x) => (
          <button key={x.id} type="button" onClick={() => setSel(x.id)}
                  className={`rounded border px-2 py-0.5 text-xs ${sel === x.id ? "border-indigo-500 bg-indigo-50" : "border-slate-300"}`}>
            <span className="font-mono">{x.id}</span> <span className="text-slate-400">{x.kind ?? "design"}{x.path ? ` · ${x.path}` : ""}
              {" · "}{Object.keys(x.values ?? {}).length} values{(x.fields ?? []).length ? ` · ${x.fields!.length} fields` : ""}</span>
          </button>
        ))}
      </div>
      {ds && <DatasetEditor key={ds.id} doc={doc} ds={ds} update={update} vocab={vocab} onRenamed={setSel} onRemoved={() => setSel(null)} />}
    </Box>
  );
}

function DatasetEditor({ doc, ds, update, onRenamed, onRemoved, vocab }: {
  doc: BeamModelV2; ds: V2Dataset; update: Update; onRenamed: (id: string) => void; onRemoved: () => void;
  vocab?: BeamVocabulary;
}) {
  const edit = (fn: (x: V2Dataset) => void) => update((d) => { fn(d.datasets!.find((x) => x.id === ds.id)!); });
  const path = doc.paths.find((p) => p.id === ds.path);
  const values = ds.values ?? {};
  const rows = path ? placementIds(path) : Object.keys(values);
  const [showGeometry, setShowGeometry] = useState(() => Object.values(values).some((v) => v.geometry));
  const [extra, setExtra] = useState<{ physics: string[]; optics: string[] }>({ physics: [], optics: [] });
  const [newCol, setNewCol] = useState("");
  const keysOf = (part: "physics" | "optics") => {
    const seen = new Set<string>(extra[part]);
    Object.values(values).forEach((v) => Object.entries(v[part] ?? {}).forEach(([k, x]) => {
      if (typeof x === "number" || typeof x === "string" || typeof x === "boolean") seen.add(k);
    }));
    if (part === "physics") seen.add("length");
    return [...seen].sort((a, b) => (a === "length" ? -1 : b === "length" ? 1 : a.localeCompare(b)));
  };
  const physicsKeys = keysOf("physics");
  const opticsKeys = keysOf("optics");
  const setCell = (row: string, part: "s" | "geometry" | "physics" | "optics", key: string, raw: string) => edit((x) => {
    x.values = x.values ?? {};
    const v = (x.values[row] = x.values[row] ?? {});
    const n = raw.trim() === "" ? undefined : Number.isNaN(Number(raw)) ? raw.trim() : Number(raw);
    if (part === "s") { if (n === undefined) delete v.s; else v.s = typeof n === "number" ? n : null; }
    else {
      const bag = { ...((v[part] as Record<string, unknown> | null | undefined) ?? {}) };
      if (n === undefined) delete bag[key]; else bag[key] = n;
      if (Object.keys(bag).length) (v as Record<string, unknown>)[part] = bag; else delete (v as Record<string, unknown>)[part];
    }
    if (!Object.keys(v).length) delete x.values[row];
  });
  const freeRows = !path;
  const [addRow, setAddRow] = useState("");
  const [provRow, setProvRow] = useState<string | null>(null);

  return (
    <div className="mt-3 space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <Field label="Id" value={ds.id} onChange={() => undefined} disabled />
        <label className="block text-xs text-slate-500">Rename to
          <Cell value="" placeholder="new id" onCommit={(v) => { const n = v.trim(); if (n && !(doc.datasets ?? []).some((x) => x.id === n)) { update((d) => renameDataset(d, ds.id, n)); onRenamed(n); } }} />
        </label>
        <Field label="Name" value={ds.name ?? ""} onChange={(v) => edit((x) => { x.name = v || undefined; })} />
        <label className="block text-xs text-slate-500">Kind
          <input list="dataset-kinds" value={ds.kind ?? ""} onChange={(e) => edit((x) => { x.kind = e.target.value || undefined; })}
                 className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900" />
          <datalist id="dataset-kinds">{DATASET_KINDS.map((k) => <option key={k} value={k} />)}</datalist>
        </label>
        <label className="block text-xs text-slate-500">Category
          <input list="dataset-categories" value={ds.category ?? ""} onChange={(e) => edit((x) => { x.category = e.target.value || undefined; })}
                 className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900" />
          <datalist id="dataset-categories">{DATASET_CATEGORIES.filter(Boolean).map((k) => <option key={k} value={k} />)}</datalist>
        </label>
        <Select label="Path" value={ds.path ?? ""} options={["", ...doc.paths.map((p) => p.id)]} onChange={(v) => edit((x) => {
          if (v && x.path !== v && Object.keys(x.values ?? {}).length) {
            // Values are keyed by placement: keep only those the new path has.
            const keep = new Set(placementIds(doc.paths.find((p) => p.id === v)!));
            x.values = Object.fromEntries(Object.entries(x.values ?? {}).filter(([k]) => keep.has(k)));
          }
          if (v) x.path = v; else delete x.path;
        })} />
        <Field label="Source" value={ds.source ?? ""} placeholder="LOCO, survey 2026…" onChange={(v) => edit((x) => { x.source = v || undefined; })} />
        <Field label="Version" value={ds.version ?? ""} onChange={(v) => edit((x) => { x.version = v || undefined; })} />
        <Field label="Simulator" value={ds.simulator ?? ""} onChange={(v) => edit((x) => { x.simulator = v || undefined; })} />
        <Field label="Simulator version" value={ds.simulator_version ?? ""} onChange={(v) => edit((x) => { x.simulator_version = v || undefined; })} />
        <Field label="Git commit" value={ds.git_commit ?? ""} onChange={(v) => edit((x) => { x.git_commit = v || undefined; })} />
        <Field label="Generated at" value={ds.generated_at ?? ""} placeholder="2026-05-12" onChange={(v) => edit((x) => { x.generated_at = v || undefined; })} />
        <Field label="Valid from" value={ds.valid_from ?? ""} onChange={(v) => edit((x) => { x.valid_from = v || undefined; })} />
        <Field label="Valid until" value={ds.valid_until ?? ""} onChange={(v) => edit((x) => { x.valid_until = v || undefined; })} />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-slate-700">Values</span>
        <label className="flex items-center gap-1 text-slate-500"><input type="checkbox" checked={showGeometry} onChange={(e) => setShowGeometry(e.target.checked)} /> reference trajectory (x y z yaw pitch roll)</label>
        <input value={newCol} onChange={(e) => setNewCol(e.target.value)} placeholder="new column, e.g. k1 or beta_x"
               className="w-48 rounded border border-slate-300 px-1 py-0.5" />
        <Small onClick={() => { if (newCol.trim()) { setExtra({ ...extra, physics: [...extra.physics, newCol.trim()] }); setNewCol(""); } }}>+ physics</Small>
        <Small onClick={() => { if (newCol.trim()) { setExtra({ ...extra, optics: [...extra.optics, newCol.trim()] }); setNewCol(""); } }}>+ optics</Small>
      </div>
      <div className="max-h-[28rem] overflow-auto rounded border border-slate-100">
        <table className="text-xs">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left text-slate-500">
              <th className="px-1">{path ? "Placement" : "Component"}</th><th>s (m)</th>
              {showGeometry && GEOMETRY_KEYS.map((k) => <th key={`g${k}`} className="text-sky-700">{k}</th>)}
              {physicsKeys.map((k) => <th key={`p${k}`}>{k}</th>)}
              {opticsKeys.map((k) => <th key={`o${k}`} className="text-violet-700">{k}</th>)}
              <th className="text-slate-400">native</th>
              <th className="text-slate-400" title="where each value came from">prov</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const v = values[r] ?? {};
              const cellOf = (part: "geometry" | "physics" | "optics", k: string) => {
                const x = ((v[part] as Record<string, unknown> | null | undefined) ?? {})[k];
                return x === undefined || x === null ? "" : String(x);
              };
              return (
                <tr key={r} className="border-t border-slate-100">
                  <td className="whitespace-nowrap px-1 font-mono">{r}</td>
                  <td><Cell value={v.s?.toString() ?? ""} onCommit={(x) => setCell(r, "s", "s", x)} narrow /></td>
                  {showGeometry && GEOMETRY_KEYS.map((k) => <td key={`g${k}`}><Cell value={cellOf("geometry", k)} onCommit={(x) => setCell(r, "geometry", k, x)} narrow /></td>)}
                  {physicsKeys.map((k) => <td key={`p${k}`}><Cell value={cellOf("physics", k)} onCommit={(x) => setCell(r, "physics", k, x)} narrow /></td>)}
                  {opticsKeys.map((k) => <td key={`o${k}`}><Cell value={cellOf("optics", k)} onCommit={(x) => setCell(r, "optics", k, x)} narrow /></td>)}
                  <td className="whitespace-nowrap px-1 text-slate-400">{v.native ? `${v.native.type ?? ""} (${Object.keys(v.native.parameters ?? {}).length})` : ""}</td>
                  <td className="px-1">
                    <button type="button" onClick={() => setProvRow(provRow === r ? null : r)}
                            className={`rounded px-1 ${provRow === r ? "bg-indigo-600 text-white" : Object.keys(v.provenance ?? {}).length ? "bg-indigo-50 text-indigo-700" : "text-slate-300 hover:text-slate-600"}`}>
                      {Object.keys(v.provenance ?? {}).length || "+"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {freeRows && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">This dataset is on no path: its values are per component.</span>
          <select value={addRow} onChange={(e) => setAddRow(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5">
            <option value="">add a component…</option>
            {doc.components.filter((c) => !(c.id in values)).map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
          </select>
          <Small onClick={() => { if (addRow) { edit((x) => { x.values = { ...(x.values ?? {}), [addRow]: { s: null } }; }); setAddRow(""); } }}>add</Small>
        </div>
      )}
      {provRow && (
        <div className="rounded border border-indigo-200 bg-indigo-50/40 p-2">
          <ProvenanceGroup prov={values[provRow]?.provenance} hint={`of ${provRow}'s values in ${ds.id}`}
                           keys={["s", ...physicsKeys, ...opticsKeys, ...(showGeometry ? GEOMETRY_KEYS : [])]}
                           onChange={(pv) => edit((x) => {
                             x.values = x.values ?? {};
                             const v = (x.values[provRow] = x.values[provRow] ?? {});
                             if (pv) v.provenance = pv; else delete v.provenance;
                             if (!Object.keys(v).length) delete x.values[provRow];
                           })} />
        </div>
      )}
      <p className="text-[11px] text-slate-500">
        Empty a cell to remove the value. The simulator's native parameters of each value are kept as they came. A
        component on this path with no row values has nothing in this dataset — normal for a measured dataset that
        covers only the BPMs.
      </p>

      <FieldsEditor doc={doc} ds={ds} edit={edit} />
      {path && (
        <PathBoundaries doc={doc} path={path} vocab={vocab} list={ds.boundaries} title="Aperture model of this dataset"
                        hint="boundaries that hold for this configuration only"
                        change={(fn) => edit((x) => { x.boundaries = x.boundaries ?? []; fn(x.boundaries); if (!x.boundaries.length) delete x.boundaries; })} />
      )}

      <div className="border-t border-slate-100 pt-2 text-xs">
        <button type="button" className="text-rose-700 hover:underline" onClick={() => { update((d) => {
          d.datasets = (d.datasets ?? []).filter((x) => x.id !== ds.id);
          if (d.model.dataset === ds.id) delete d.model.dataset;
        }); onRemoved(); }}>remove dataset {ds.id}</button>
      </div>
    </div>
  );
}

/** Quantities along a path — pressure, temperature, loss, field — as [s, value] samples. */
function FieldsEditor({ doc, ds, edit }: { doc: BeamModelV2; ds: V2Dataset; edit: (fn: (x: V2Dataset) => void) => void }) {
  const fields = ds.fields ?? [];
  const setF = (i: number, fn: (f: V2Field) => void) => edit((x) => { fn(x.fields![i]); });
  const parse = (text: string): number[][] => text.split("\n").map((l) => l.trim().split(/[\s,;]+/).map(Number))
    .filter((p) => p.length === 2 && p.every((n) => !Number.isNaN(n))).sort((a, b) => a[0] - b[0]);
  return (
    <Group title="Fields along a path" hint="model or snapshot data, never a telemetry stream"
           action={doc.paths.length > 0 ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((x) => {
             x.fields = [...(x.fields ?? []), { quantity: "vacuum.pressure", unit: "mbar", path: x.path ?? doc.paths[0].id, samples: [] }];
           })}>+ field</button> : undefined}>
      {fields.length === 0 && <p className="text-xs text-slate-400">None.</p>}
      {fields.map((f, i) => (
        <div key={i} className="mb-2 grid gap-2 rounded border border-slate-100 p-2 sm:grid-cols-4">
          <Field label="Quantity" value={f.quantity} placeholder="vacuum.pressure" onChange={(v) => setF(i, (x) => { x.quantity = v; })} />
          <Field label="Unit" value={f.unit ?? ""} onChange={(v) => setF(i, (x) => { x.unit = v || undefined; })} />
          <Select label="Path" value={f.path} options={doc.paths.map((p) => p.id)} onChange={(v) => setF(i, (x) => { x.path = v; })} />
          <Select label="Interpolation" value={f.interpolation ?? "linear"} options={["linear", "step", "none"]} onChange={(v) => setF(i, (x) => { x.interpolation = v as V2Field["interpolation"]; })} />
          <label className="block text-xs text-slate-500 sm:col-span-3">Samples (one “s value” per line, s in metres)
            <SamplesArea value={f.samples.map((p) => p.join(" ")).join("\n")} onCommit={(t) => setF(i, (x) => { x.samples = parse(t); })} />
          </label>
          <div className="flex items-end text-xs"><button type="button" className="text-rose-700 hover:underline" onClick={() => edit((x) => {
            x.fields!.splice(i, 1);
            if (!x.fields!.length) delete x.fields;
          })}>remove</button>
            <span className="ml-2 text-slate-400">{f.samples.length} samples</span></div>
        </div>
      ))}
    </Group>
  );
}

function SamplesArea({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <textarea value={v} rows={4} onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onCommit(v)}
                   className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs text-slate-900" />;
}

// ------------------------------------------------------------------------- states and provenance

const MEANINGS: [string, string][] = [["beam_passes", "beam passes"], ["intercepts", "intercepts"],
  ["limits_aperture", "limits aperture"], ["acts", "acts on the beam"]];

/** The states a component can be in and what each means for the beam, the one the static model assumes, and
 *  how a value read from an external signal maps to a state. Never the live state: the control system has it. */
function StatesGroup({ model, typeStates, onChange }: {
  model: V2StateModel | undefined; typeStates?: Record<string, Record<string, unknown>>; onChange: (m: V2StateModel | undefined) => void;
}) {
  const set = (fn: (m: V2StateModel) => void) => { const m = clone(model!); fn(m); onChange(m); };
  const names = (model?.states ?? []).map((x) => x.name);
  return (
    <Group title="States" hint="what each means for the beam; never the live state"
           action={!model ? (typeStates
             ? <button type="button" className="text-indigo-700 hover:underline" onClick={() => onChange({
               states: Object.entries(typeStates).map(([name, meaning]) => ({ name, meaning })), default: Object.keys(typeStates)[0] })}>use the type's</button>
             : <button type="button" className="text-indigo-700 hover:underline" onClick={() => onChange({ states: [{ name: "ON" }, { name: "OFF" }], default: "ON" })}>add</button>)
             : <button type="button" className="text-rose-700 hover:underline" onClick={() => onChange(undefined)}>remove</button>}>
      {model && (
        <div className="space-y-2">
          {model.states.map((st, i) => (
            <div key={i} className="rounded border border-slate-100 p-1.5 text-[11px]">
              <div className="flex items-end gap-1">
                <label className="block w-28 text-[10px] text-slate-400">state
                  <Cell value={st.name} fill mono onCommit={(v) => set((m) => {
                    const n = v.trim().toUpperCase();
                    if (!n || m.states.some((x, j) => j !== i && x.name === n)) return;
                    const old = m.states[i].name;
                    m.states[i].name = n;
                    if (m.default === old) m.default = n;
                    (m.mappings ?? []).forEach((mp) => { if (mp.state === old) mp.state = n; });
                  })} />
                </label>
                <label className="block min-w-0 flex-1 text-[10px] text-slate-400">description
                  <Cell value={st.description ?? ""} fill onCommit={(v) => set((m) => { m.states[i].description = v || undefined; })} />
                </label>
                <Icon title="remove this state" onClick={() => set((m) => {
                  const gone = m.states[i].name;
                  m.states.splice(i, 1);
                  if (m.default === gone) m.default = m.states[0]?.name;
                  m.mappings = (m.mappings ?? []).filter((mp) => mp.state !== gone);
                })}>✕</Icon>
              </div>
              <div className="mt-1 grid grid-cols-4 gap-1">
                {MEANINGS.map(([k, label]) => {
                  const v = st.meaning?.[k];
                  return (
                    <label key={k} className="block text-[10px] text-slate-400">{label}
                      <select value={v === true ? "yes" : v === false ? "no" : v === null ? "unknown" : ""} onChange={(e) => set((m) => {
                        const mean = { ...(m.states[i].meaning ?? {}) };
                        const x = e.target.value;
                        if (!x) delete mean[k]; else mean[k] = x === "yes" ? true : x === "no" ? false : null;
                        m.states[i].meaning = mean;
                      })} className="w-full rounded border border-slate-300 px-0.5 py-0.5 text-[11px] text-slate-900">
                        <option value="">—</option><option value="yes">yes</option><option value="no">no</option><option value="unknown">unknown</option>
                      </select>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-end gap-2">
            <button type="button" className="text-indigo-700 hover:underline" onClick={() => set((m) => {
              let n = m.states.length + 1;
              while (m.states.some((x) => x.name === `STATE${n}`)) n++;
              m.states.push({ name: `STATE${n}` });
            })}>+ state</button>
            <div className="w-40"><Select label="Assumed (normal operation)" value={model.default ?? ""} options={["", ...names]} onChange={(v) => set((m) => { m.default = v || undefined; })} /></div>
          </div>
          <div>
            <div className="text-[11px] text-slate-500">Signal mappings · a value read from the control system → the state it means (the signal's identity is the Knowledge Hub's)</div>
            <table className="mt-1 w-full text-[11px]">
              {(model.mappings ?? []).length > 0 && <thead><tr className="text-left text-slate-400"><th>Signal (role or id)</th><th>Value</th><th>State</th><th /></tr></thead>}
              <tbody>
                {(model.mappings ?? []).map((mp, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td><Cell value={mp.signal ?? ""} placeholder="status" fill onCommit={(v) => set((m) => { m.mappings![i].signal = v || undefined; })} /></td>
                    <td><Cell value={mp.value === undefined || mp.value === null ? "" : String(mp.value)} fill onCommit={(v) => set((m) => {
                      m.mappings![i].value = v.trim() !== "" && !Number.isNaN(Number(v)) ? Number(v) : v === "true" ? true : v === "false" ? false : v;
                    })} /></td>
                    <td><select value={mp.state} onChange={(e) => set((m) => { m.mappings![i].state = e.target.value; })} className="rounded border border-slate-300 px-0.5 py-0.5">
                      {names.map((n) => <option key={n} value={n}>{n}</option>)}</select></td>
                    <td><Icon title="remove" onClick={() => set((m) => { m.mappings!.splice(i, 1); if (!m.mappings!.length) delete m.mappings; })}>✕</Icon></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {names.length > 0 && <button type="button" className="mt-1 text-indigo-700 hover:underline" onClick={() => set((m) => {
              m.mappings = [...(m.mappings ?? []), { signal: "status", value: m.mappings?.length ?? 0, state: names[0] }];
            })}>+ mapping</button>}
          </div>
        </div>
      )}
    </Group>
  );
}

const PROV_FIELDS: [keyof V2Provenance, string][] = [["source", "source"], ["file", "file"], ["symbol", "symbol"],
  ["expression", "expression"], ["line", "line"], ["note", "note"]];

/** Where values came from, one entry per value name: `k1` ← MAD-X, strengths.str, symbol qk1, line 12. */
function ProvenanceGroup({ prov, keys, hint, onChange }: {
  prov: Record<string, V2Provenance> | undefined; keys: string[]; hint: string;
  onChange: (p: Record<string, V2Provenance> | undefined) => void;
}) {
  const entries = Object.entries(prov ?? {});
  const [adding, setAdding] = useState("");
  const free = [...new Set(keys)].filter((k) => !(k in (prov ?? {})));
  const put = (key: string, fn: (e: V2Provenance) => void) => {
    const next = clone(prov ?? {});
    next[key] = { ...(next[key] ?? {}) };
    fn(next[key]);
    Object.keys(next[key]).forEach((k) => { if (next[key][k] === undefined) delete next[key][k]; });
    onChange(next);
  };
  return (
    <Group title="Provenance" hint={hint}>
      {entries.length === 0 && <p className="text-[11px] text-slate-400">None recorded.</p>}
      {entries.map(([key, e]) => (
        <div key={key} className="mb-1 rounded border border-slate-100 p-1.5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] font-semibold text-slate-700">{key}</span>
            <button type="button" className="text-[11px] text-rose-700 hover:underline" onClick={() => {
              const next = clone(prov ?? {});
              delete next[key];
              onChange(Object.keys(next).length ? next : undefined);
            }}>remove</button>
          </div>
          <div className="mt-1 grid grid-cols-3 gap-1">
            {PROV_FIELDS.map(([f, label]) => (
              <label key={f} className="block text-[10px] text-slate-400">{label}
                <Cell value={e[f] === undefined ? "" : String(e[f])} fill placeholder={f === "source" ? "madx, survey, person" : ""}
                      onCommit={(v) => put(key, (x) => { x[f] = v.trim() === "" ? undefined : f === "line" ? Number(v) || undefined : v; })} />
              </label>
            ))}
          </div>
        </div>
      ))}
      <div className="flex items-center gap-1">
        <input list={`prov-keys-${hint.length}`} value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="value name, e.g. k1"
               className="w-40 rounded border border-slate-300 px-1 py-0.5 text-[11px]" />
        <datalist id={`prov-keys-${hint.length}`}>{free.map((k) => <option key={k} value={k} />)}</datalist>
        <button type="button" className="text-[11px] text-indigo-700 hover:underline" onClick={() => {
          const k = adding.trim();
          if (!k || (prov ?? {})[k]) return;
          put(k, (x) => { x.source = ""; delete x.source; });
          setAdding("");
        }}>+ provenance</button>
      </div>
    </Group>
  );
}

/** A small JSON object edited as text, refused (and said so) when it does not parse to an object. */
function JsonField({ label, value, onChange }: { label: string; value: unknown; onChange: (v: Record<string, unknown> | undefined) => void }) {
  const text = value && Object.keys(value as object).length ? JSON.stringify(value, null, 1) : "";
  const [v, setV] = useState(text);
  const [bad, setBad] = useState(false);
  useEffect(() => { setV(text); setBad(false); }, [text]);
  return (
    <label className="mt-2 block text-xs text-slate-500">{label}
      <textarea value={v} rows={Math.min(8, Math.max(2, v.split("\n").length))} onChange={(e) => setV(e.target.value)}
                onBlur={() => {
                  if (v === text) return;
                  if (!v.trim()) { onChange(undefined); return; }
                  try {
                    const parsed = JSON.parse(v);
                    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
                    setBad(false);
                    onChange(parsed);
                  } catch { setBad(true); }
                }}
                className={`mt-0.5 w-full rounded border px-2 py-1 font-mono text-xs text-slate-900 ${bad ? "border-rose-400 bg-rose-50" : "border-slate-300"}`} />
      {bad && <span className="text-rose-700">Not a JSON object: not saved.</span>}
    </label>
  );
}

const SHAPE_FIELDS: Record<string, [keyof V2Profile, string][]> = {
  circle: [["radius", "radius"]],
  ellipse: [["semi_axis_x", "semi-axis x"], ["semi_axis_y", "semi-axis y"]],
  rectangle: [["half_width_x", "half width x"], ["half_height_y", "half height y"]],
  racetrack: [["half_width_x", "half width x"], ["half_height_y", "half height y"], ["corner_radius", "corner radius"]],
  polygon: [], custom: [],
};

function BoundariesGroup({ c, vocab, stateNames, edit }: {
  c: V2Component; vocab?: BeamVocabulary; stateNames: string[]; edit: (fn: (el: V2Component) => void) => void;
}) {
  const list = c.boundaries ?? [];
  return (
    <Group title="Beam boundaries" hint="the space this component leaves the beam, in metres from the axis"
           action={<button type="button" className="text-indigo-700 hover:underline" onClick={() => edit((el) => {
             el.boundaries = [...(el.boundaries ?? []), { profile: { shape: "circle", radius: 0.02 } }];
           })}>+ boundary</button>}>
      {list.map((b, i) => (
        <BoundaryCard key={i} b={b} vocab={vocab} stateNames={stateNames}
                      onChange={(fn) => edit((el) => { fn(el.boundaries![i]); })}
                      onRemove={() => edit((el) => { el.boundaries!.splice(i, 1); if (!el.boundaries!.length) delete el.boundaries; })} />
      ))}
    </Group>
  );
}

/** States a boundary may be limited to: the source component's own, else its type's defaults. */
function statesOf(doc: BeamModelV2, vocab: BeamVocabulary | undefined, componentId?: string): string[] {
  const c = componentId ? doc.components.find((x) => x.id === componentId) : undefined;
  if (!c) return [];
  const own = (c.states?.states ?? []).map((x) => x.name);
  return own.length ? own : Object.keys((c.type && vocab?.states[c.type]) || {});
}

/** One boundary. `along` edits one that lies along a path (its own s range, its source component, its kind);
 *  otherwise the range is relative to the owning component's entry. */
function BoundaryCard({ b, vocab, stateNames, onChange, onRemove, along }: {
  b: V2Boundary; vocab?: BeamVocabulary; stateNames: string[]; onChange: (fn: (b: V2Boundary) => void) => void;
  onRemove: () => void; along?: { components: string[]; label: string };
}) {
  const setB = onChange;
  return (
    <div className="mb-2 rounded border border-slate-100 p-2">
      <div className="grid grid-cols-3 gap-2">
        {along && <Field label="Id" value={b.id ?? ""} placeholder="optional" onChange={(v) => setB((x) => { x.id = v || undefined; })} />}
        {along && <Select label="Produced by" value={b.component ?? ""} options={["", ...along.components]} onChange={(v) => setB((x) => { x.component = v || undefined; })} />}
        {along && <Select label="Kind" value={b.kind ?? "physical"} options={["physical", "model"]} onChange={(v) => setB((x) => { x.kind = v === "physical" ? undefined : "model"; })} />}
        <Select label="Shape" value={b.profile.shape} options={vocab?.shapes ?? ["circle", "ellipse", "rectangle", "racetrack", "polygon"]}
                onChange={(v) => setB((x) => { x.profile = { shape: v as V2Profile["shape"] }; })} />
        {SHAPE_FIELDS[b.profile.shape]?.map(([k, label]) => (
          <Field key={k} label={`${label} (m)`} value={(b.profile[k] as number | undefined)?.toString() ?? ""}
                 onChange={(v) => setB((x) => { (x.profile as Record<string, unknown>)[k] = num(v); })} />
        ))}
        {(b.profile.shape === "polygon" || b.profile.shape === "custom") && (
          <label className="col-span-2 block text-xs text-slate-500">Points (x y; x y; …)
            <Cell value={(b.profile.points ?? []).map((p) => p.join(" ")).join("; ")} placeholder="0.02 0.01; -0.02 0.01; -0.02 -0.01; 0.02 -0.01"
                  onCommit={(v) => setB((x) => { x.profile.points = v.split(";").map((p) => p.trim().split(/[\s,]+/).map(Number)).filter((p) => p.length === 2 && p.every((n) => !Number.isNaN(n))); })} />
          </label>
        )}
        <Field label="Offset x" value={b.profile.offset_x?.toString() ?? ""} onChange={(v) => setB((x) => { x.profile.offset_x = num(v); })} />
        <Field label="Offset y" value={b.profile.offset_y?.toString() ?? ""} onChange={(v) => setB((x) => { x.profile.offset_y = num(v); })} />
        <Select label="Only when" value={b.when_state ?? ""} options={["", ...new Set([...stateNames, ...(b.when_state ? [b.when_state] : [])])]}
                onChange={(v) => setB((x) => { x.when_state = v || undefined; })} />
        <Field label={along ? `From s (m, ${along.label})` : "From (m, from entry)"} value={b.s_start?.toString() ?? ""} onChange={(v) => setB((x) => { x.s_start = num(v); })} />
        <Field label={along ? "To s (m)" : "To (m)"} value={b.s_end?.toString() ?? ""} onChange={(v) => setB((x) => { x.s_end = num(v); })} />
        <div className="flex items-end"><button type="button" className="text-rose-700 hover:underline" onClick={onRemove}>remove</button></div>
      </div>
      {along && b.note && <div className="mt-1 text-[11px] text-slate-400">{b.note}</div>}
    </div>
  );
}

/** Boundaries that lie along a path rather than belonging to one component: a model aperture, an aperture
 *  element of a simulator, a restriction a survey found. Kept in the document's (or a dataset's) list. */
function PathBoundaries({ doc, path, vocab, list, change, title, hint }: {
  doc: BeamModelV2; path: V2Path; vocab?: BeamVocabulary; list: V2Boundary[] | undefined;
  change: (fn: (list: V2Boundary[]) => void) => void; title: string; hint: string;
}) {
  const items = (list ?? []).map((b, i) => ({ b, i })).filter(({ b }) => b.path === path.id);
  const comps = [...new Set(placements(path).map((pl) => pl.component))];
  return (
    <Group title={title} hint={hint}
           action={<button type="button" className="text-indigo-700 hover:underline" onClick={() => change((l) => {
             l.push({ path: path.id, s_start: 0, s_end: 0, kind: "model", profile: { shape: "circle", radius: 0.02 } });
           })}>+ boundary</button>}>
      {items.length === 0 && <p className="text-xs text-slate-400">None.</p>}
      {items.map(({ b, i }) => (
        <BoundaryCard key={i} b={b} vocab={vocab} stateNames={statesOf(doc, vocab, b.component)}
                      along={{ components: comps, label: `along ${path.name || path.id}` }}
                      onChange={(fn) => change((l) => { fn(l[i]); })} onRemove={() => change((l) => { l.splice(i, 1); })} />
      ))}
    </Group>
  );
}

const POSE_KEYS = ["x", "y", "z", "yaw", "pitch", "roll"] as const;
type Pose = Partial<Record<(typeof POSE_KEYS)[number], number>> & Record<string, unknown>;

function PoseRow({ label, value, onChange, unitHint }: {
  label: string; value: Pose | undefined; onChange: (p: Pose | undefined) => void; unitHint?: string;
}) {
  const set = (k: string, raw: string) => {
    const next: Pose = { ...(value ?? {}) };
    const n = num(raw);
    if (n === undefined) delete next[k]; else next[k] = n;
    onChange(Object.keys(next).length ? next : undefined);
  };
  return (
    <div>
      <div className="text-[11px] text-slate-500">{label}{unitHint ? <span className="text-slate-400"> · {unitHint}</span> : null}</div>
      <div className="mt-0.5 grid grid-cols-6 gap-1">
        {POSE_KEYS.map((k) => (
          <label key={k} className="block text-[10px] text-slate-400">{k}
            <Cell value={value?.[k]?.toString() ?? ""} onCommit={(v) => set(k, v)} fill />
          </label>
        ))}
      </div>
    </div>
  );
}

/** Where the physical object is: its pose in the hall, and design, surveyed and offset (all optional). The
 *  reference trajectory at the component is a dataset value; this is the object itself. */
function AlignmentGroup({ c, edit }: { c: V2Component; edit: (fn: (el: V2Component) => void) => void }) {
  const geo = (c.geometry ?? {}) as Record<string, unknown>;
  const al = (geo.alignment ?? {}) as Record<string, unknown>;
  const setGeo = (k: string, v: unknown) => edit((el) => {
    const g = { ...((el.geometry ?? {}) as Record<string, unknown>) };
    if (v === undefined || v === "") delete g[k]; else g[k] = v;
    if (Object.keys(g).length) el.geometry = g as V2Component["geometry"]; else delete el.geometry;
  });
  const setAl = (k: string, v: unknown) => edit((el) => {
    const g = { ...((el.geometry ?? {}) as Record<string, unknown>) };
    const a = { ...((g.alignment ?? {}) as Record<string, unknown>) };
    if (v === undefined || v === "") delete a[k]; else a[k] = v;
    if (Object.keys(a).length) g.alignment = a; else delete g.alignment;
    if (Object.keys(g).length) el.geometry = g as V2Component["geometry"]; else delete el.geometry;
  });
  const design = al.design as Pose | undefined;
  const surveyed = al.surveyed as Pose | undefined;
  const offset = al.offset as Record<string, number> | undefined;
  const canDiff = !!design && !!surveyed && POSE_KEYS.some((k) => design[k] !== undefined && surveyed[k] !== undefined);
  return (
    <Group title="Alignment" hint="the physical object; all optional"
           action={canDiff ? <button type="button" className="text-indigo-700 hover:underline" title="offset = surveyed − design" onClick={() => {
             const o: Record<string, number> = {};
             POSE_KEYS.forEach((k) => {
               if (design![k] !== undefined && surveyed![k] !== undefined) o[`d${k}`] = Number((surveyed![k]! - design![k]!).toPrecision(12));
             });
             setAl("offset", o);
           }}>offset from survey</button> : undefined}>
      <div className="space-y-2">
        <Select label="Reference point" value={(geo.reference_point as string) ?? ""} options={["", "entry", "centre", "exit"]}
                onChange={(v) => setGeo("reference_point", v || undefined)} />
        <PoseRow label="Placement in the hall" unitHint="m, rad" value={geo.placement as Pose | undefined} onChange={(p) => setGeo("placement", p)} />
        <PoseRow label="Design" value={design} onChange={(p) => setAl("design", p)} />
        <PoseRow label="Surveyed" value={surveyed} onChange={(p) => setAl("surveyed", p)} />
        <div>
          <div className="text-[11px] text-slate-500">Offset</div>
          <div className="mt-0.5 grid grid-cols-6 gap-1">
            {POSE_KEYS.map((k) => (
              <label key={k} className="block text-[10px] text-slate-400">d{k}
                <Cell value={offset?.[`d${k}`]?.toString() ?? ""} fill onCommit={(v) => {
                  const o: Record<string, number> = { ...(offset ?? {}) };
                  const n = num(v);
                  if (n === undefined) delete o[`d${k}`]; else o[`d${k}`] = n;
                  setAl("offset", Object.keys(o).length ? o : undefined);
                }} />
              </label>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Surveyed at" value={(al.surveyed_at as string) ?? ""} placeholder="2026-04-02" onChange={(v) => setAl("surveyed_at", v || undefined)} />
          <Field label="Survey" value={(al.survey as string) ?? ""} placeholder="campaign or dataset" onChange={(v) => setAl("survey", v || undefined)} />
        </div>
      </div>
    </Group>
  );
}

function TypeSelect({ vocab, value, onChange }: { vocab?: BeamVocabulary; value: string; onChange: (v: string) => void }) {
  const known = vocab ? Object.values(vocab.families).some((ts) => value in ts) : true;
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="max-w-[11rem] rounded border border-slate-300 px-1 py-0.5 text-xs">
      {!value && <option value="">—</option>}
      {!known && value && <option value={value}>{value} (not in the vocabulary)</option>}
      {Object.entries(vocab?.families ?? {}).map(([fam, ts]) => (
        <optgroup key={fam} label={fam.replace(/_/g, " ")}>
          {Object.keys(ts).map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

/** What the editor keeps without showing: listed, so a person knows it is there and travels with a save. */
function PassedThrough({ doc }: { doc: BeamModelV2 }) {
  const items: string[] = [];
  if ((doc.external_bindings ?? []).length) items.push(`${doc.external_bindings!.length} asset bindings`);
  if ((doc.observables ?? []).length) items.push(`${doc.observables!.length} declared observables`);
  const orphan = (doc.boundaries ?? []).filter((b) => b.path && !doc.paths.some((p) => p.id === b.path)).length;
  if (orphan) items.push(`${orphan} boundaries along paths that no longer exist`);
  if (!items.length) return null;
  return <p className="text-xs text-slate-500">Kept as they are and saved with the model: {items.join(" · ")}.</p>;
}

// ------------------------------------------------------------------------- small pieces

export function downloadJson(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function kv(o: Record<string, unknown>): string {
  return Object.entries(o ?? {}).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
}

function parseKv(s: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const part of s.split(",")) {
    const [k, ...rest] = part.split("=");
    if (!k?.trim() || !rest.length) continue;
    const raw = rest.join("=").trim();
    out[k.trim()] = raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
  }
  return out;
}

function Box({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Group({ title, hint, action, children }: { title: string; hint?: string; action?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="border-t border-slate-100 pt-2">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{title}
          {hint && <span className="ml-1 font-normal normal-case tracking-normal text-slate-400">· {hint}</span>}</span>
        {action}
      </div>
      {children}
    </div>
  );
}

function Field({ label, value, onChange, placeholder, disabled }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean;
}) {
  return (
    <label className="block text-xs text-slate-500">
      {label}
      <input value={value} placeholder={placeholder} disabled={disabled} onChange={(e) => onChange(e.target.value)}
             className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900 disabled:bg-slate-50" />
    </label>
  );
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <label className="block text-xs text-slate-500">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900">
        {options.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
      </select>
    </label>
  );
}

/** Edited in place and committed on blur or Enter, so a rename does not happen per keystroke. */
function Cell({ value, onCommit, mono, narrow, fill, placeholder }: {
  value: string; onCommit: (v: string) => void; mono?: boolean; narrow?: boolean; fill?: boolean; placeholder?: string;
}) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input value={v} placeholder={placeholder} onChange={(e) => setV(e.target.value)} onClick={(e) => e.stopPropagation()}
           onBlur={() => v !== value && onCommit(v)} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
           className={`rounded border border-slate-200 px-1 py-0.5 ${mono ? "font-mono" : ""} ${fill ? "w-full min-w-0" : narrow ? "w-20" : "w-full min-w-[7rem]"}`} />
  );
}

function Small({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" onClick={onClick}
            className={`rounded border px-2 py-0.5 text-xs ${danger ? "border-rose-200 text-rose-700 hover:bg-rose-50" : "border-slate-300 text-slate-700 hover:bg-slate-50"}`}>
      {children}
    </button>
  );
}

function Icon({ children, onClick, title }: { children: React.ReactNode; onClick: () => void; title: string }) {
  return <button type="button" title={title} onClick={onClick} className="px-1 text-slate-500 hover:text-slate-900">{children}</button>;
}
