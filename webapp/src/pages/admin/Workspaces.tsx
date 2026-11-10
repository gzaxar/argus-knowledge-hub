import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, sitesApi, workspacesApi, type PlacementEnding } from "../../api/client";
import type { MyWorkspace, SiteMoveAccess } from "../../api/types";
import { problem } from "../catalogue/catalogueText";

/** A workspace's place in a site: a site (whose places its facilities use), the catalogue, or at a site. Leaving
 *  a site first shows the placements on its places that would end. */
function SiteCell({ ws, all }: { ws: MyWorkspace; all: MyWorkspace[] }) {
  const queryClient = useQueryClient();
  const [ending, setEnding] = useState<{ siteId: string | null; list: PlacementEnding[]; access?: SiteMoveAccess } | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["me-workspaces"] });
  const role = useMutation({ mutationFn: (site: boolean) => sitesApi.setRole(ws.id, site), onSuccess: refresh });
  const site = useMutation({
    mutationFn: (v: { siteId: string | null; confirm: boolean }) => sitesApi.setSite(ws.id, v.siteId, v.confirm),
    onSuccess: (r, v) => {
      if (r.preview) setEnding({ siteId: v.siteId, list: r.would_end ?? [], access: r.access });
      else { setEnding(null); refresh(); }
    },
  });
  const error = role.error ?? site.error;
  const sites = all.filter((w) => w.role === "site" && w.id !== ws.id);
  const facilities = all.filter((w) => w.site_id === ws.id).length;
  if (ws.role === "catalogue") return <span className="text-xs text-slate-500">the catalogue</span>;
  return (
    <div className="space-y-1 text-xs">
      {ws.role === "site" ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-sky-50 px-1.5 py-0.5 font-medium text-sky-800">Site</span>
          <span className="text-slate-500">{facilities} facilit{facilities === 1 ? "y" : "ies"}</span>
          <button type="button" disabled={role.isPending || facilities > 0} onClick={() => role.mutate(false)}
                  title={facilities > 0 ? "Its facilities must be at another site, or none, first" : undefined}
                  className="text-slate-500 hover:underline disabled:opacity-50">Stop being a site</button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label={`Site of ${ws.name}`} value={ws.site_id ?? ""} disabled={site.isPending}
                  onChange={(e) => site.mutate({ siteId: e.target.value || null, confirm: false })}
                  className="rounded border border-slate-300 px-1.5 py-0.5">
            <option value="">At no site</option>
            {sites.map((s) => <option key={s.id} value={s.id}>at {s.name}</option>)}
          </select>
          {!ws.site_id && (
            <button type="button" disabled={role.isPending} onClick={() => role.mutate(true)}
                    className="text-sky-800 hover:underline">Make it a site</button>
          )}
        </div>
      )}
      {ending && (
        <div role="alert" className="rounded border border-amber-300 bg-amber-50 p-2 text-amber-950">
          {ending.list.length > 0 && (
            <p>Leaving its site ends {ending.list.length} placement{ending.list.length === 1 ? "" : "s"} of its
              records on the site's places: {ending.list.slice(0, 5).map((x) => x.record.name).join(", ")}
              {ending.list.length > 5 ? "…" : ""}. They keep their position on the map.</p>
          )}
          {ending.access && <MoveAccess access={ending.access} />}
          <button type="button" disabled={!!ending.access?.blocked.length}
                  onClick={() => site.mutate({ siteId: ending.siteId, confirm: true })}
                  className="mt-1 rounded bg-slate-900 px-2 py-0.5 font-medium text-white disabled:opacity-50">
            {ending.siteId ? "Move it" : "Leave the site"}
          </button>
          <button type="button" onClick={() => setEnding(null)} className="ml-2 text-slate-600">Cancel</button>
        </div>
      )}
      {error && <p className="text-red-600">{problem(error)}</p>}
    </div>
  );
}

export function AdminWorkspaces() {
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

  const workspaces = useQuery({
    queryKey: ["me-workspaces"],
    queryFn: workspacesApi.listMine,
    retry: false,
  });

  const renameMutation = useMutation({
    mutationFn: (vars: { id: string; name: string }) => workspacesApi.update(vars.id, { name: vars.name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me-workspaces"] });
      setEditingId(null);
    },
    onError: () => alert("Rename failed."),
  });

  const toggleGlobalMutation = useMutation({
    mutationFn: (vars: { id: string; is_global: boolean }) =>
      workspacesApi.update(vars.id, { is_global: vars.is_global }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me-workspaces"] }),
    onError: () => alert("Failed to update global flag."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => workspacesApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me-workspaces"] }),
    onError: () => alert("Delete failed."),
  });

  if (workspaces.isError) {
    const forbidden = workspaces.error instanceof ApiError && workspaces.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden ? "Admins only." : "Failed to load workspaces."}
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Workspaces</h1>
          <p className="mt-1 text-sm text-slate-500">
            Every workspace on this instance. Deleting one permanently removes everything in it.
          </p>
        </div>
        <Link
          to="/admin/new-workspace"
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          New workspace
        </Link>
      </div>

      {workspaces.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {workspaces.data && (
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2">Id</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Global</th>
                <th className="px-4 py-2">Site</th>
                <th className="px-4 py-2">Created</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {workspaces.data.map((ws) => (
                <tr key={ws.id}>
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">{ws.id}</td>
                  <td className="px-4 py-2 font-medium text-slate-900">
                    {editingId === ws.id ? (
                      <input
                        autoFocus
                        value={editingName}
                        onChange={(e) => setEditingName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && editingName.trim()) {
                            renameMutation.mutate({ id: ws.id, name: editingName.trim() });
                          }
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        className="rounded border border-slate-300 px-2 py-1 text-sm"
                      />
                    ) : (
                      ws.name
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        checked={ws.is_global}
                        disabled={toggleGlobalMutation.isPending}
                        onChange={(e) => {
                          const next = e.target.checked;
                          if (
                            !next ||
                            confirm(
                              `Make every schema in "${ws.name}" global? This makes every object type (and its objects) in this workspace visible and referenceable from every other workspace.`,
                            )
                          ) {
                            toggleGlobalMutation.mutate({ id: ws.id, is_global: next });
                          }
                        }}
                      />
                      Global
                    </label>
                  </td>
                  <td className="px-4 py-2"><SiteCell ws={ws} all={workspaces.data} /></td>
                  <td className="px-4 py-2 text-slate-500">
                    {new Date(ws.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {editingId === ws.id ? (
                      <>
                        <button
                          onClick={() =>
                            editingName.trim() &&
                            renameMutation.mutate({ id: ws.id, name: editingName.trim() })
                          }
                          disabled={renameMutation.isPending}
                          className="mr-3 text-slate-700 hover:underline"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="mr-3 text-slate-500 hover:underline"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <Link
                          to={`/workspaces/${ws.id}/members`}
                          className="mr-3 text-slate-500 hover:text-slate-900"
                        >
                          Members
                        </Link>
                        <Link
                          to={`/workspaces/${ws.id}/integrity`}
                          className="mr-3 text-slate-500 hover:text-slate-900"
                        >
                          Integrity
                        </Link>
                        <Link
                          to={`/workspaces/${ws.id}/keys`}
                          className="mr-3 text-slate-500 hover:text-slate-900"
                        >
                          Keys
                        </Link>
                        <Link
                          to={`/workspaces/${ws.id}/transfer`}
                          className="mr-3 text-slate-500 hover:text-slate-900"
                        >
                          Transfer
                        </Link>
                        <button
                          onClick={() => {
                            setEditingId(ws.id);
                            setEditingName(ws.name);
                          }}
                          className="mr-3 text-slate-500 hover:text-slate-900"
                        >
                          Rename
                        </button>
                        <button
                          onClick={() => {
                            if (
                              confirm(
                                `Delete workspace "${ws.name}"? This permanently deletes every schema, object, ticket, label, global value and import in it. This cannot be undone.`,
                              )
                            ) {
                              deleteMutation.mutate(ws.id);
                            }
                          }}
                          className="text-red-500 hover:text-red-700"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {workspaces.data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                    No workspaces yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}


/** Who gains and who loses access when a facility changes site, and what must be settled first (issue #26). */
function MoveAccess({ access }: { access: SiteMoveAccess }) {
  const line = (g: SiteMoveAccess["loses"][number]) =>
    `${g.group_name} (${g.role_name}): ${g.people.length} ${g.people.length === 1 ? "person" : "people"}`;
  return (
    <div className="mt-1 space-y-1">
      {access.loses.length > 0 && <p>It stops inheriting from {access.from_site}: {access.loses.map(line).join("; ")}.</p>}
      {access.gains.length > 0 && <p>It starts inheriting from {access.to_site}: {access.gains.map(line).join("; ")}.</p>}
      {access.blocked.length > 0 && (
        <p className="font-medium text-red-700">Settle first: it gives roles to groups of {access.blocked[0].home_site_id}{" "}
          ({[...new Set(access.blocked.map((b) => b.group_name))].join(", ")}). Remove those grants on its Access page.</p>
      )}
    </div>
  );
}
