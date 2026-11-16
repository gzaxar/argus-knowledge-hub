import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ApiError, workspacesApi } from "../../api/client";
import type { AdminUser, UserRemovalPreview } from "../../api/types";
import { askTyped, notify } from "../../lib/dialogs";
import { getActiveProfile } from "../../api/session";
import { SortHeader, useSort } from "../../components/SortableTable";

export function AdminUsers() {
  const queryClient = useQueryClient();
  const profile = getActiveProfile();
  const selfUserId = profile?.authType === "oidc" ? profile.id : null;

  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: workspacesApi.listUsers,
    retry: false, // a 403 here is permanent, not transient — retrying just delays the message
  });

  const [query, setQuery] = useState("");
  const [adminsOnly, setAdminsOnly] = useState(false);
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return (users.data ?? []).filter((u) => {
      if (adminsOnly && !u.is_admin) return false;
      const text = `${u.email} ${u.name ?? ""}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [users.data, query, adminsOnly]);
  // Last login newest first; people who never signed in go last whichever the direction.
  const { sorted, sort, toggle } = useSort(
    shown,
    {
      email: (u) => u.email,
      name: (u) => u.name,
      last_login: (u) => (u.last_login_at ? new Date(u.last_login_at) : null),
      admin: (u) => u.is_admin,
    },
    { key: "email", dir: "asc" },
    "admin-users",
  );

  const [removing, setRemoving] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // Removing a person (docs/dangerous-actions.md): first what it changes, then their address typed to confirm.
  const removeUser = async (u: AdminUser) => {
    setProblem(null);
    setRemoving(u.id);
    try {
      const p = await workspacesApi.userRemoval(u.id);
      if (p.blocked) { setProblem(p.blocked); return; }
      if (!await askTyped(removalText(p), u.email, "their e-mail address",
                          (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase())) return;
      await workspacesApi.removeUser(u.id, u.email);
      notify(`${u.email} was removed from ARGUS.`, "info");
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (e) {
      setProblem(e instanceof ApiError ? (typeof e.detail === "string" ? e.detail : "Could not remove them.") : "Could not remove them.");
    } finally {
      setRemoving(null);
    }
  };

  const setAdminMutation = useMutation({
    mutationFn: ({ userId, isAdmin }: { userId: string; isAdmin: boolean }) =>
      workspacesApi.setUserAdmin(userId, isAdmin),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  if (users.isError) {
    const forbidden = users.error instanceof ApiError && users.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden ? "Admins only." : "Failed to load users."}
      </p>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Users</h1>
      <p className="mt-1 text-sm text-slate-500">
        Everyone who has signed in at least once. Admins have full rights on every workspace.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <input
          type="search"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find by name or email…"
          className="w-80 max-w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
        />
        <label className="flex items-center gap-1.5 text-sm text-slate-600">
          <input type="checkbox" checked={adminsOnly} onChange={(e) => setAdminsOnly(e.target.checked)} />
          Admins only
        </label>
        {users.data && (
          <span className="text-xs text-slate-500">
            {shown.length === users.data.length ? `${users.data.length} users` : `${shown.length} of ${users.data.length}`}
          </span>
        )}
      </div>

      {users.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}
      {problem && <p role="alert" className="mt-3 text-sm text-red-600">{problem}</p>}

      {users.data && (
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <SortHeader label="Email" column="email" sort={sort} onSort={toggle} />
                <SortHeader label="Name" column="name" sort={sort} onSort={toggle} />
                <SortHeader label="Last login" column="last_login" sort={sort} onSort={toggle} time />
                <SortHeader label="Admin" column="admin" sort={sort} onSort={(k) => toggle(k, "desc")}
                            className="px-4 py-2 text-center" />
                <th className="px-4 py-2"><span className="sr-only">Remove</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {sorted.map((u) => (
                <tr key={u.id} className={u.removed_at ? "bg-slate-50 text-slate-400" : undefined}>
                  <td className="px-4 py-2 font-medium text-slate-900">
                    <span className={u.removed_at ? "text-slate-400 line-through" : undefined}>{u.email}</span>
                    {u.removed_at && <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-xs font-normal text-slate-600">
                      removed {new Date(u.removed_at).toLocaleDateString()}</span>}
                    {!u.removed_at && u.email_verified === false && (
                      <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-normal text-amber-800"
                            title="The identity provider did not say this address is verified: groups by e-mail domain do not count it">
                        address not verified</span>)}
                  </td>
                  <td className="px-4 py-2 text-slate-500">{u.name ?? "—"}</td>
                  <td className="px-4 py-2 text-slate-500">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={u.is_admin}
                      disabled={u.id === selfUserId}
                      title={u.id === selfUserId ? "You can't remove your own admin rights here" : undefined}
                      onChange={(e) =>
                        setAdminMutation.mutate({ userId: u.id, isAdmin: e.target.checked })
                      }
                    />
                  </td>
                  <td className="px-4 py-2 text-right">
                    {!u.removed_at && u.id !== selfUserId && (
                      <button type="button" disabled={removing === u.id} onClick={() => void removeUser(u)}
                              className="text-xs text-red-600 hover:text-red-800 disabled:opacity-50">
                        {removing === u.id ? "…" : "Remove from ARGUS"}</button>
                    )}
                  </td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    {users.data.length === 0 ? "No users yet." : "Nobody matches."}
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

/** What removing this person does, in words, for the first of the two confirmations. */
export function removalText(p: UserRemovalPreview): string {
  const n = (k: number, one: string, many = `${one}s`) => `${k} ${k === 1 ? one : many}`;
  const lines = [`Remove ${p.user.email} from ARGUS?`, "", "They can no longer sign in, from any identity provider."];
  if (p.personal_tokens) lines.push(`Their ${n(p.personal_tokens, "personal token")} stop working (MCP included).`);
  if (p.roles.length) lines.push(`Their own roles go, in: ${p.roles.join(", ")}.`);
  if (p.memberships.length) lines.push(`Their workspace memberships go, in: ${p.memberships.join(", ")}.`);
  if (p.site_administrator_of.length) lines.push(`No longer administrator of the sites: ${p.site_administrator_of.join(", ")}.`);
  if (p.group_administrator_of.length) lines.push(`No longer administrator of the groups: ${p.group_administrator_of.join(", ")}.`);
  if (p.groups_left.length) lines.push(`Taken out of the groups: ${p.groups_left.join(", ")}.`);
  if (p.user.is_admin) lines.push("No longer an administrator of the installation.");
  if (p.open_tickets_count) lines.push(`${n(p.open_tickets_count, "open ticket")} assigned to them left unassigned.`);
  if (p.activities_count) lines.push(`${n(p.activities_count, "planned activity", "planned activities")} they own or were given left without them.`);
  lines.push("", "What stays: their name on what they did (records, tickets, comments, revisions, approvals)" +
    (p.stays.documents_owned ? `, ${n(p.stays.documents_owned, "document")} they own` : "") +
    (p.stays.robot_tokens_made ? `, ${n(p.stays.robot_tokens_made, "robot token")} they made` : "") +
    (p.directory_groups.length ? `, their place in the directory groups ${p.directory_groups.join(", ")}` : "") + ".");
  return lines.join("\n");
}
