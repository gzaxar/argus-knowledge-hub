import { useQuery } from "@tanstack/react-query";
import { packagesApi, workspacesApi, type PackageInfo } from "../api/client";

const CONTENT_LABELS: Record<string, string> = {
  object_types: "object types",
  enumerations: "enumerations",
  ticket_types: "ticket types",
  document_types: "document types",
  workflows: "workflows",
  equipment_classes: "equipment classes",
  map_layers: "map layers",
};

export function contentsLine(p: Pick<PackageInfo, "contents">): string {
  return Object.entries(p.contents)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} ${CONTENT_LABELS[k] ?? k}`)
    .join(" · ");
}

/** Which template packages a new workspace starts from: core-facility always, others by choice — with what
 *  each brings in, its dependencies included, before anything is created. */
export function PackagePicker({
  chosen,
  onChange,
  catalogue,
  onCatalogue,
}: {
  chosen: string[];
  onChange: (ids: string[]) => void;
  catalogue: string;
  onCatalogue: (id: string) => void;
}) {
  const all = useQuery({ queryKey: ["packages"], queryFn: packagesApi.list });
  const resolved = useQuery({
    queryKey: ["packages-resolve", chosen],
    queryFn: () => packagesApi.resolve(chosen),
  });
  const workspaces = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine,
                                enabled: chosen.length > 0 });
  const optional = (all.data ?? []).filter((p) => p.id !== "core-facility" && p.installable);

  return (
    <div>
      <label className="block text-sm font-medium text-slate-700">Starts from</label>
      <div className="mt-1 space-y-1 rounded border border-slate-200 bg-white p-3 text-sm">
        <label className="flex items-start gap-2 text-slate-500">
          <input type="checkbox" checked disabled className="mt-1" />
          <span><span className="font-medium text-slate-700">Core facility</span> — ticket and document types,
            status and priority, the default workflow (always)</span>
        </label>
        {optional.map((p) => (
          <label key={p.id} className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={chosen.includes(p.id)}
                   onChange={(e) => onChange(e.target.checked ? [...chosen, p.id] : chosen.filter((x) => x !== p.id))} />
            <span>
              <span className="font-medium text-slate-900">{p.name}</span> <span className="text-slate-400">{p.version}</span>
              <span className="block text-xs text-slate-500">{p.description}</span>
            </span>
          </label>
        ))}
      </div>
      {chosen.length > 0 && (
        <div className="mt-2">
          <label className="block text-xs text-slate-600">
            Shared types from
            <select value={catalogue} onChange={(e) => onCatalogue(e.target.value)}
                    className="ml-2 rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="">nowhere: all of their types in this workspace</option>
              {(workspaces.data ?? []).map((w) => (
                <option key={w.id} value={w.id}>{w.name} (its catalogue)</option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-xs text-slate-400">
            Hanging from a catalogue workspace, this one shares its equipment, product and place types with the
            others; only an accelerator's machine-specific types (functions, control, engineering) are its own.
          </p>
        </div>
      )}
      {resolved.data && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-500">
          {resolved.data.map((p) => (
            <li key={p.id}>
              <span className="font-mono text-slate-700">{p.id} {p.version}</span>
              {!p.requested && " (needed by another)"} — {contentsLine(p)}
            </li>
          ))}
        </ul>
      )}
      {resolved.isError && <p className="mt-1 text-xs text-red-600">These packages cannot be combined.</p>}
    </div>
  );
}
