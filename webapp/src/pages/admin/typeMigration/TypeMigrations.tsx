import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { problemText, typeMigrationsApi } from "../../../api/client";
import type { MigrationKind, MigrationSource, MigrationTargetType, TargetResolution, TypeProposal } from "../../../api/client";
import { ActionButton, Empty, Section, when } from "../portability/shared";

const KINDS: { id: MigrationKind; label: string }[] = [
  { id: "objects", label: "Assets and records" }, { id: "tickets", label: "Tickets" }, { id: "documents", label: "Documents" },
];

export function statusBadge(status: string) {
  const tone: Record<string, string> = {
    draft: "bg-slate-100 text-slate-700", applying: "bg-amber-100 text-amber-900", applied: "bg-sky-100 text-sky-800",
    partially_applied: "bg-amber-100 text-amber-900", verified: "bg-green-100 text-green-800", reverted: "bg-slate-200 text-slate-700",
  };
  return <span className={`rounded px-1.5 py-0.5 text-xs ${tone[status] ?? "bg-slate-100 text-slate-700"}`}>{status.replace(/_/g, " ")}</span>;
}

/** Administration → Type migrations: records moved from a custom or shared type to a package's standard type,
 *  in their own workspaces, through a reviewed plan (docs/type-migration.md). Instance administrators only. */
export function TypeMigrationsPage() {
  const list = useQuery({ queryKey: ["type-migrations"], queryFn: typeMigrationsApi.list });
  const [open, setOpen] = useState(false);
  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Type migrations</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Move records from a custom type, or one a shared catalogue defines, to a standard type of a versioned
            package — in the workspaces that own them, keeping their identity, history, files, links and places.
            Each migration is a plan: map, preview (nothing is written), apply in batches, verify.
          </p>
        </div>
        <button type="button" onClick={() => setOpen((v) => !v)}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
          {open ? "Close" : "New migration"}
        </button>
      </div>
      {open && <NewMigration />}
      <Section title="Migrations">
        {list.isError && <p className="text-sm text-rose-700">{problemText(list.error)}</p>}
        {(list.data ?? []).length === 0 ? <Empty>None yet.</Empty> : (
          <table className="w-full table-fixed text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="py-1">From</th><th className="py-1">To</th><th className="w-40 py-1">Workspaces</th>
                <th className="w-36 py-1">Status</th><th className="w-40 py-1">Created</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(list.data ?? []).map((m) => (
                <tr key={m.id}>
                  <td className="truncate py-1.5"><Link to={`/admin/type-migrations/${m.id}`} className="font-medium text-sky-800 hover:underline">
                    {m.source.name}</Link> <span className="text-xs text-slate-500">({m.source.workspace_id})</span></td>
                  <td className="truncate py-1.5">{m.target.type} <span className="font-mono text-xs text-slate-500">{m.target.package_id} {m.target.version}</span></td>
                  <td className="truncate py-1.5 text-xs text-slate-600" title={m.workspaces.join(", ")}>{m.workspaces.join(", ")}</td>
                  <td className="py-1.5">{statusBadge(m.status)}</td>
                  <td className="py-1.5 text-xs text-slate-500">{when(m.created_at)} · {m.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}

function NewMigration() {
  const navigate = useNavigate();
  const [kind, setKind] = useState<MigrationKind>("objects");
  const [source, setSource] = useState<MigrationSource | null>(null);
  const [below, setBelow] = useState(false);
  const [workspaces, setWorkspaces] = useState<string[]>([]);
  const [target, setTarget] = useState<MigrationTargetType | null>(null);
  const [reason, setReason] = useState("");
  const [filter, setFilter] = useState("");
  const [homeChoice, setHome] = useState(false);
  // A shared package type is migrated only to bring it home.
  const home: "installed" | "own" = source?.package_type || homeChoice ? "own" : "installed";
  const sources = useQuery({ queryKey: ["tm-sources", kind], queryFn: () => typeMigrationsApi.sources(kind) });
  const targets = useQuery({ queryKey: ["tm-targets", kind], queryFn: () => typeMigrationsApi.targets(kind) });
  const counts = useMemo(() => {
    if (!source) return {} as Record<string, number>;
    const out: Record<string, number> = { ...source.records };
    if (below) for (const [w, n] of Object.entries(source.records_below)) out[w] = (out[w] ?? 0) + n;
    return out;
  }, [source, below]);
  const resolve = useQuery({
    queryKey: ["tm-resolve", kind, target?.package_id, target?.type, workspaces.join(","), home],
    queryFn: () => typeMigrationsApi.resolve(kind, target!.package_id, target!.type, workspaces, home),
    enabled: !!target && workspaces.length > 0,
  });
  const create = useMutation({
    mutationFn: () => typeMigrationsApi.create({ kind, source_schema_uid: source!.uid,
      target: { package_id: target!.package_id, type: target!.type, home }, workspaces, include_descendants: below, reason }),
    onSuccess: (m) => navigate(`/admin/type-migrations/${m.id}`),
  });
  const shown = (targets.data ?? []).filter((t) => !filter || `${t.type} ${t.package_id}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-4">
      <Section title="1 · Source: the type the records have now">
        <div className="mb-2 flex flex-wrap gap-2">
          {KINDS.map((k) => (
            <button key={k.id} type="button" aria-pressed={kind === k.id}
                    onClick={() => { setKind(k.id); setSource(null); setTarget(null); setWorkspaces([]); }}
                    className={`rounded px-3 py-1 text-sm ${kind === k.id ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"}`}>
              {k.label}
            </button>
          ))}
        </div>
        {sources.isLoading && <p className="text-sm text-slate-500">Looking for types…</p>}
        <div className="max-h-72 overflow-y-auto rounded border border-slate-200">
          <table className="w-full table-fixed text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr><th className="w-8" /><th className="py-1">Type</th><th className="w-44 py-1">Defined in</th><th className="py-1">Records by owning workspace</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(sources.data ?? []).map((s) => (
                <tr key={s.uid} className={source?.uid === s.uid ? "bg-sky-50" : ""}>
                  <td className="px-2"><input type="radio" name="source" aria-label={`Source ${s.name} (${s.workspace_id})`}
                    checked={source?.uid === s.uid}
                    onChange={() => { setSource(s); setWorkspaces(Object.keys({ ...s.records })); }} /></td>
                  <td className="truncate py-1.5" title={s.uid}>{s.name}
                    {s.deprecated && <span className="ml-1 rounded bg-slate-200 px-1 text-[11px]">deprecated</span>}
                    {s.package_type && <span className="ml-1 rounded bg-sky-100 px-1 text-[11px] text-sky-800" title="A shared package type: its records can be given their workspace's own copy">shared package type</span>}</td>
                  <td className="truncate py-1.5 text-xs text-slate-600">{s.workspace_id}{s.is_global && " · shared"}</td>
                  <td className="truncate py-1.5 text-xs text-slate-600">
                    {Object.entries(s.records).map(([w, n]) => `${w}: ${n}`).join(" · ") || "—"}
                    {Object.keys(s.records_below).length > 0 && <span className="text-slate-400"> (+ below: {Object.values(s.records_below).reduce((a, b) => a + b, 0)})</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {source && (
          <div className="mt-3 space-y-2 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={below} onChange={(e) => {
                setBelow(e.target.checked);
                const all = { ...source.records, ...(e.target.checked ? source.records_below : {}) };
                setWorkspaces(Object.keys(all));
              }} />
              Include the records of the types below it ({Object.values(source.records_below).reduce((a, b) => a + b, 0)})
            </label>
            <fieldset>
              <legend className="text-xs font-medium uppercase text-slate-500">Owning workspaces — each record is migrated where it lives</legend>
              <div className="mt-1 flex flex-wrap gap-3">
                {Object.entries(counts).map(([w, n]) => (
                  <label key={w} className="flex items-center gap-1">
                    <input type="checkbox" checked={workspaces.includes(w)}
                           onChange={(e) => setWorkspaces(e.target.checked ? [...workspaces, w] : workspaces.filter((x) => x !== w))} />
                    {w} <span className="text-slate-500">({n})</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        )}
      </Section>

      {source && (
        <Section title="2 · Target: a standard type of a versioned package">
          <p className="mb-2 text-xs text-slate-500">
            Types are listed by package. The target is that package's type in each owning workspace (or in the shared
            catalogue it hangs from) — never a type that merely has the same name.
          </p>
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter types…"
                 aria-label="Filter target types" className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm" />
          <div className="max-h-60 overflow-y-auto rounded border border-slate-200">
            <ul className="divide-y divide-slate-100 text-sm">
              {shown.map((t) => (
                <li key={`${t.package_id}/${t.type}`}>
                  <label className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 ${target === t ? "bg-sky-50" : ""}`}>
                    <input type="radio" name="target" checked={target?.package_id === t.package_id && target?.type === t.type}
                           onChange={() => setTarget(t)} />
                    <span className="font-medium">{t.type}</span>
                    <span className="font-mono text-xs text-slate-500">{t.package_id} {t.version}</span>
                    <span className="truncate text-xs text-slate-500" title={t.description}>{t.description}</span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
          {kind === "objects" && (
            <label className="mt-2 flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={home === "own"} disabled={!!source.package_type}
                     onChange={(e) => setHome(e.target.checked)} />
              <span>
                <b>Bring the type home</b> — each owning workspace gets its own copy of the package type (the same
                package, version and type, owned by it) instead of using its shared catalogue's.
                <span className="block text-xs text-slate-500">
                  {source.package_type
                    ? "Always, for a shared package type: its records move to their workspace's own copy."
                    : "Use it when a workspace should keep the type as its own."}
                  {" "}The copy is made when you apply; it is upgraded with the workspace's packages and no longer follows the catalogue's edits.
                </span>
              </span>
            </label>
          )}
          {target && resolve.data && <Resolution rows={resolve.data} />}
          <ProposeInstead source={source} />
        </Section>
      )}

      {source && target && (
        <Section title="Why">
          <label className="block text-sm">
            <span className="text-slate-600">Reason — kept with the plan and every record it moves</span>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                      className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm" />
          </label>
          <div className="mt-2 flex items-center gap-2">
            <ActionButton label="Create the plan" busy={create.isPending}
                          disabled={!reason.trim() || workspaces.length === 0} onClick={() => create.mutate()} />
            <span className="text-xs text-slate-500">A mapping is proposed next; nothing changes until you apply it.</span>
          </div>
          {create.isError && <p className="mt-2 text-sm text-rose-700">{problemText(create.error)}</p>}
        </Section>
      )}
    </div>
  );
}

/** Where the package type is, for each owning workspace; what is missing, and what installing it would do. */
export function Resolution({ rows }: { rows: TargetResolution[] }) {
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const install = useMutation({
    mutationFn: (r: TargetResolution) => typeMigrationsApi.installPreview(r.home, r.package_id),
    onSuccess: (p) => setPreview(p as unknown as Record<string, unknown>),
  });
  return (
    <div className="mt-3 space-y-2">
      <table className="w-full table-fixed text-sm">
        <thead className="text-left text-xs uppercase text-slate-500">
          <tr><th className="py-1">Records of</th><th className="py-1">Type lives in</th><th className="w-28 py-1">Package</th><th className="py-1">Status</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.workspace_id}>
              <td className="truncate py-1.5">{r.workspace_id}</td>
              <td className="truncate py-1.5">{r.home}{r.home !== r.workspace_id && <span className="text-xs text-slate-500"> (shared catalogue)</span>}</td>
              <td className="py-1.5 font-mono text-xs">{r.installed_version ?? "—"}</td>
              <td className="py-1.5">
                {r.status === "ok" ? <span className="text-green-800">✓ available{r.brought_home ? ` — ${r.brought_home}` : ""}</span>
                  : r.status === "will_create" ? <span className="text-sky-800"><span aria-hidden>+ </span>{r.detail} (made when applied)</span> : (
                  <span className="flex flex-wrap items-center gap-2 text-amber-900">
                    <span><span aria-hidden>! </span>{r.detail}</span>
                    {["package_missing", "package_older", "definition_unknown"].includes(r.status) && (
                      <>
                        <button type="button" onClick={() => install.mutate(r)} className="text-xs text-sky-800 underline">Preview the install</button>
                        <Link to={`/workspaces/${encodeURIComponent(r.home)}/packages`} className="text-xs text-sky-800 underline">Open {r.home}'s packages</Link>
                      </>
                    )}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {install.isError && <p className="text-sm text-rose-700">{problemText(install.error)}</p>}
      {preview && (
        <div className="rounded border border-slate-200 bg-slate-50 p-2 text-xs">
          {preview.ok ? (
            <>
              <p className="font-medium">Installing in {String(preview.workspace_id)} would:</p>
              <ul className="list-disc pl-5">
                {((preview.plan as { steps: { package_id: string; action: string; version: string; from_version: string | null }[] }).steps)
                  .filter((s) => s.action !== "unchanged")
                  .map((s) => <li key={s.package_id}>{s.action} {s.package_id} {s.from_version ? `${s.from_version} → ` : ""}{s.version}</li>)}
              </ul>
              <p className="mt-1 text-slate-500">Nothing was installed. Install it from that workspace's Packages page, then come back.</p>
            </>
          ) : <p className="text-amber-900">{String(preview.error)}</p>}
        </div>
      )}
    </div>
  );
}

/** When no package has the type yet: the custom type written as package YAML, checked, for review and a release. */
function ProposeInstead({ source }: { source: MigrationSource }) {
  const [open, setOpen] = useState(false);
  const [pkg, setPkg] = useState("");
  const [name, setName] = useState(source.name);
  const [result, setResult] = useState<TypeProposal | null>(null);
  const run = useMutation({ mutationFn: () => typeMigrationsApi.propose(source.uid, pkg, name), onSuccess: setResult });
  return (
    <div className="mt-3 border-t border-slate-100 pt-3 text-sm">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="text-sky-800 hover:underline">
        <span aria-hidden>{open ? "▾" : "▸"}</span> No package has the type you need? Propose this one as a package type
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-slate-500">
            Writes the type as package YAML and checks it. Nothing is installed or changed here: the YAML goes into
            the package's files through code review, with a new package version, and a release.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col text-xs">Package
              <input value={pkg} onChange={(e) => setPkg(e.target.value)} placeholder="e.g. it"
                     className="rounded border border-slate-300 px-2 py-1 font-mono text-sm" /></label>
            <label className="flex flex-col text-xs">Type name in the package
              <input value={name} onChange={(e) => setName(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" /></label>
            <ActionButton label="Check the proposal" disabled={!pkg} busy={run.isPending} onClick={() => run.mutate()} />
          </div>
          {run.isError && <p className="text-rose-700">{problemText(run.error)}</p>}
          {result && (
            <div className="space-y-2">
              {result.problems.length > 0
                ? <ul className="list-disc pl-5 text-rose-700">{result.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                : <p className="text-green-800">✓ No problems found. Version {result.current_version} → {result.next_version}.</p>}
              {result.notes.length > 0 && <ul className="list-disc pl-5 text-amber-900">{result.notes.map((p) => <li key={p}>{p}</li>)}</ul>}
              <pre className="max-h-64 overflow-auto rounded bg-slate-900 p-2 text-xs text-slate-100">{result.yaml}</pre>
              <button type="button" className="text-xs text-sky-800 underline" onClick={() => {
                const a = document.createElement("a");
                a.href = URL.createObjectURL(new Blob([result.yaml], { type: "text/yaml" }));
                a.download = `${result.package_id}-${result.type.replace(/\s+/g, "-").toLowerCase()}.yaml`;
                a.click();
              }}>Download the YAML</button>
              <ol className="list-decimal pl-5 text-xs text-slate-600">{result.checklist.map((c) => <li key={c}>{c}</li>)}</ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
