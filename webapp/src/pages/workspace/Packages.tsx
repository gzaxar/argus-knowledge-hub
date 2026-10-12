import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, packagesApi, type PackagePlan } from "../../api/client";
import { contentsLine } from "../../components/PackagePicker";

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
  }
  return "It could not be done.";
}

function how(options: Record<string, string> | null): string {
  if (!options?.scope) return "";
  if (options.scope === "global") return "as the catalogue other workspaces hang from";
  if (options.scope === "beamline") return `hanging from ${options.catalogue_workspace_id}`;
  return "self-contained";
}

const ACTIONS: Record<string, string> = {
  install: "installed", upgrade: "upgraded", seeded: "seeded by an import", detected: "found in place",
  unchanged: "unchanged",
};

/** Which template packages this workspace uses — exact versions and checksums, how each was put in, the
 *  history — and adding one, previewed before anything changes. */
export function WorkspacePackages() {
  const { workspaceId = "" } = useParams();
  const queryClient = useQueryClient();
  const mine = useQuery({ queryKey: ["workspace-packages", workspaceId],
                          queryFn: () => packagesApi.ofWorkspace(workspaceId) });
  const all = useQuery({ queryKey: ["packages"], queryFn: packagesApi.list });
  const [chosen, setChosen] = useState("");
  const [plan, setPlan] = useState<PackagePlan | null>(null);
  const preview = useMutation({ mutationFn: () => packagesApi.preview(workspaceId, { packages: [chosen] }),
                                onSuccess: setPlan });
  const install = useMutation({
    mutationFn: () => packagesApi.install(workspaceId, { packages: [chosen] }),
    onSuccess: () => {
      setPlan(null);
      setChosen("");
      queryClient.invalidateQueries({ queryKey: ["workspace-packages", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
    },
  });
  const have = new Set((mine.data?.packages ?? []).map((p) => p.package_id));
  const offer = (all.data ?? []).filter((p) => p.installable && (!have.has(p.id) ||
    mine.data?.packages.find((x) => x.package_id === p.id)?.upgrade_available));

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Packages</h1>
        <p className="mt-1 text-sm text-slate-500">
          The template packages this workspace's types come from, at their exact versions. A package holds
          definitions only — types, fields, enumerations, workflows — never records.
        </p>
      </div>

      <table className="w-full rounded border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-4 py-2">Package</th><th className="px-4 py-2">Version</th>
            <th className="px-4 py-2">Checksum</th><th className="px-4 py-2">How</th><th className="px-4 py-2">Since</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {(mine.data?.packages ?? []).length === 0 && (
            <tr><td colSpan={5} className="px-4 py-3 text-slate-500">None recorded.</td></tr>
          )}
          {(mine.data?.packages ?? []).map((p) => (
            <tr key={p.package_id}>
              <td className="px-4 py-2"><span className="font-medium text-slate-900">{p.name}</span>
                <span className="block font-mono text-xs text-slate-400">{p.package_id}</span></td>
              <td className="px-4 py-2 font-mono">
                {p.version}
                {p.upgrade_available && <span className="ml-1 text-xs text-amber-700">({p.shipped_version} available)</span>}
              </td>
              <td className="px-4 py-2 font-mono text-xs text-slate-500" title={p.checksum}>{p.checksum.slice(0, 12)}</td>
              <td className="px-4 py-2 text-slate-600">{how(p.options)}</td>
              <td className="px-4 py-2 text-slate-500">{p.installed_at ? new Date(p.installed_at).toLocaleDateString() : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {offer.length > 0 && (
        <div className="rounded border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-900">Add a package</h2>
          <div className="mt-2 flex items-center gap-2">
            <select value={chosen} onChange={(e) => { setChosen(e.target.value); setPlan(null); }}
                    className="rounded border border-slate-300 px-2 py-1.5 text-sm">
              <option value="">Choose…</option>
              {offer.map((p) => <option key={p.id} value={p.id}>{p.name} {p.version} — {contentsLine(p)}</option>)}
            </select>
            <button type="button" disabled={!chosen || preview.isPending} onClick={() => preview.mutate()}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
              {preview.isPending ? "Working it out…" : "Preview"}
            </button>
          </div>
          {preview.isError && <p className="mt-2 text-sm text-red-600">{problem(preview.error)}</p>}
          {plan && (
            <div className="mt-3 space-y-2 text-sm">
              {plan.steps.map((s) => {
                const created = (s.result?.created as string[] | undefined) ?? [];
                const extended = (s.result?.extended as string[] | undefined) ?? [];
                return (
                  <p key={s.package_id}>
                    <span className="font-mono">{s.package_id} {s.version}</span>: {ACTIONS[s.action] ?? s.action}
                    {s.action === "install" ? "" : s.from_version ? ` from ${s.from_version}` : ""}
                    {created.length > 0 && ` — creates ${created.length} types`}
                    {extended.length > 0 && `, extends ${extended.length}`}
                    {s.action !== "unchanged" && created.length === 0 && extended.length === 0 && " — nothing new"}
                  </p>
                );
              })}
              {plan.options?.scope && <p className="text-xs text-slate-500">The object catalogue goes in {how(plan.options)}.</p>}
              <button type="button" disabled={!plan.changes || install.isPending} onClick={() => install.mutate()}
                      className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
                {install.isPending ? "Installing…" : plan.changes ? "Install" : "Nothing to install"}
              </button>
              {install.isError && <p className="text-sm text-red-600">{problem(install.error)}</p>}
            </div>
          )}
        </div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-900">History</h2>
        <ul className="space-y-1 text-sm text-slate-600">
          {(mine.data?.history ?? []).slice().reverse().map((h, i) => (
            <li key={i}>
              <span className="text-slate-400">{h.at ? new Date(h.at).toLocaleString() : ""}</span>{" "}
              <span className="font-mono">{h.package_id}</span> {h.from_version ? `${h.from_version} → ` : ""}
              <span className="font-mono">{h.to_version}</span> — {ACTIONS[h.action] ?? h.action}
              {h.actor ? ` by ${h.actor}` : ""}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
