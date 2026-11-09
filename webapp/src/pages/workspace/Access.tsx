import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, directoryApi, membersApi, rolesApi, sitesApi, workspacesApi } from "../../api/client";
import { Role } from "../../api/types";

const RESOURCE_LABELS: [string, string][] = [
  ["objects", "Objects & types"],
  ["tickets", "Tickets"],
  ["documents", "Documents"],
  ["workspace", "Workspace"],
];

function PermissionSummary({ role }: { role: Role }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
      {RESOURCE_LABELS.map(([key, label]) => {
        const actions = role.permissions[key];
        if (!actions?.length) return null;
        return (
          <span key={key}>
            <span className="text-slate-400">{label}:</span> {actions.join(", ")}
          </span>
        );
      })}
    </div>
  );
}

export function WorkspaceAccess() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const queryClient = useQueryClient();
  const [subjectType, setSubjectType] = useState<"user" | "group">("group");
  const [subjectId, setSubjectId] = useState("");
  const [roleId, setRoleId] = useState("viewer");
  const [showRoles, setShowRoles] = useState(false);

  const bindings = useQuery({
    queryKey: ["bindings", workspaceId],
    queryFn: () => rolesApi.listBindings(workspaceId!),
    enabled: !!workspaceId,
    retry: false, // a 403 here is permanent, not transient
  });
  const roles = useQuery({ queryKey: ["roles"], queryFn: rolesApi.list });
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => directoryApi.groups() });
  const directory = useQuery({ queryKey: ["directory-status"], queryFn: directoryApi.status });
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const isSite = mine.data?.find((w) => w.id === workspaceId)?.role === "site";
  const people = useQuery({
    queryKey: ["member-directory", workspaceId],
    queryFn: membersApi.directory,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      rolesApi.createBinding(workspaceId!, { subject_type: subjectType, subject_id: subjectId, role_id: roleId }),
    onSuccess: () => {
      setSubjectId("");
      queryClient.invalidateQueries({ queryKey: ["bindings", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["member-directory", workspaceId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (bindingId: number) => rolesApi.deleteBinding(workspaceId!, bindingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bindings", workspaceId] });
      queryClient.invalidateQueries({ queryKey: ["member-directory", workspaceId] });
    },
  });

  const syncMutation = useMutation({
    mutationFn: directoryApi.sync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      queryClient.invalidateQueries({ queryKey: ["directory-status"] });
    },
  });

  if (bindings.isError) {
    const forbidden = bindings.error instanceof ApiError && bindings.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden
          ? "You don't have permission to manage access to this workspace."
          : "Failed to load access."}
      </p>
    );
  }

  const subjectOptions =
    subjectType === "group"
      ? (groups.data ?? []).filter((g) => g.active).map((g) => ({
          id: g.uid,
          label: `${g.name}${g.member_count ? ` · ${g.member_count} member${g.member_count === 1 ? "" : "s"}` : " · empty"}`,
        }))
      : (people.data ?? []).map((p) => ({ id: p.user_id, label: p.name || p.email }));

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">Access</h1>
      <p className="mt-1 text-sm text-slate-500">
        Grant a role to a person or to a whole group. Granting a group is how a service gets
        access in one go — anyone who joins it later inherits the same rights.{" "}
        <Link to={`/workspaces/${workspaceId}/members`} className="text-indigo-600 hover:underline">
          Older per-person permissions
        </Link>{" "}
        still apply and are managed separately. Every grant is re-certified in a signed{" "}
        <Link to={`/workspaces/${workspaceId}/access-reviews`} className="text-indigo-600 hover:underline">
          access review
        </Link>
        .
      </p>

      {directory.data?.is_test_data && (
        <div className="mt-4 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>Built-in test directory.</strong> No LDAP is configured, so the people and groups
          below are fictional examples ({directory.data.active_groups} groups,{" "}
          {directory.data.users} people) meant for trying things out. Granting them access is safe
          but meaningless — they can't sign in.
        </div>
      )}

      <div className="mt-6 rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">Granted roles</h2>
          <button
            onClick={() => setShowRoles((v) => !v)}
            className="text-xs text-indigo-600 hover:text-indigo-800"
          >
            {showRoles ? "Hide" : "What do the roles mean?"}
          </button>
        </div>

        {showRoles && (
          <div className="space-y-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
            {roles.data?.map((role) => (
              <div key={role.id}>
                <p className="text-sm font-medium text-slate-900">
                  {role.name}
                  <span className="ml-2 font-normal text-slate-500">{role.description}</span>
                </p>
                <PermissionSummary role={role} />
              </div>
            ))}
          </div>
        )}

        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-4 py-2">Who</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Role</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {bindings.data?.map((b) => (
              <tr key={b.id} className="hover:bg-slate-50">
                <td className="px-4 py-2 font-medium text-slate-900">
                  {b.subject_label}
                  {!b.subject_active && (
                    <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                      inactive
                    </span>
                  )}
                  {b.subject_pending && (
                    <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700"
                          title="Added by e-mail: the access waits for their first sign-in with that address">
                      not signed in yet
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-slate-500">{b.subject_type}</td>
                <td className="px-4 py-2 text-slate-700">{b.role_name}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => {
                      if (confirm(`Remove ${b.role_name} from ${b.subject_label}?`)) {
                        deleteMutation.mutate(b.id);
                      }
                    }}
                    className="text-xs text-red-500 hover:text-red-700"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {bindings.data?.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                  No roles granted yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {deleteMutation.isError && (
          <p className="border-t border-slate-100 px-4 py-2 text-sm text-red-600">
            {(deleteMutation.error as ApiError)?.detail ?? "Could not remove that role."}
          </p>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (subjectId) createMutation.mutate();
          }}
          className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-4 py-3"
        >
          <select
            value={subjectType}
            onChange={(e) => {
              setSubjectType(e.target.value as "user" | "group");
              setSubjectId("");
            }}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="group">Group</option>
            <option value="user">Person</option>
          </select>
          <select
            value={subjectId}
            onChange={(e) => setSubjectId(e.target.value)}
            required
            className="min-w-64 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">
              {subjectType === "group" ? "Choose a group…" : "Choose a person…"}
            </option>
            {subjectOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            value={roleId}
            onChange={(e) => setRoleId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm"
          >
            {roles.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={createMutation.isPending || !subjectId}
            className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Grant
          </button>
        </form>
        {createMutation.isError && (
          <p className="px-4 pb-3 text-sm text-red-600">
            {(createMutation.error as ApiError)?.detail ?? "Could not grant that role."}
          </p>
        )}
        {subjectType === "group" && subjectOptions.length === 0 && (
          <p className="px-4 pb-3 text-sm text-slate-500">
            No groups yet — run a directory sync below.
          </p>
        )}
      </div>

      <Invite workspaceId={workspaceId!} roles={roles.data ?? []} onDone={() => {
        queryClient.invalidateQueries({ queryKey: ["bindings", workspaceId] });
        queryClient.invalidateQueries({ queryKey: ["member-directory", workspaceId] });
      }} />

      {isSite && <SiteAdministrators siteId={workspaceId!} />}

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Directory</h2>
            <p className="mt-1 text-sm text-slate-500">
              Source: <span className="font-medium text-slate-700">{directory.data?.provider ?? "…"}</span>
              {" · "}
              {directory.data?.active_groups ?? 0} groups, {directory.data?.users ?? 0} people
              {directory.data?.last_synced_at && (
                <> · last synced {new Date(directory.data.last_synced_at).toLocaleString()}</>
              )}
            </p>
          </div>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {syncMutation.isPending ? "Syncing…" : "Sync now"}
          </button>
        </div>
        {syncMutation.isError && (
          <p className="mt-2 text-sm text-red-600">
            {(syncMutation.error as ApiError)?.status === 403
              ? "Only an instance admin can run a directory sync."
              : ((syncMutation.error as ApiError)?.detail ?? "Sync failed.")}
          </p>
        )}
        {syncMutation.isSuccess && (
          <p className="mt-2 text-sm text-green-700">
            Synced. {String(syncMutation.data.groups_created ?? 0)} groups added,{" "}
            {String(syncMutation.data.users_created ?? 0)} people added,{" "}
            {String(syncMutation.data.users_deactivated ?? 0)} deactivated.
          </p>
        )}

        {(groups.data?.length ?? 0) > 0 && (
          <table className="mt-4 w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1">Group</th>
                <th className="py-1">Source</th>
                <th className="py-1 text-right">Members</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {groups.data?.map((g) => (
                <tr key={g.uid}>
                  <td className="py-1.5">
                    <span className="text-slate-900">{g.name}</span>
                    {g.description && (
                      <span className="ml-2 text-xs text-slate-400">{g.description}</span>
                    )}
                  </td>
                  <td className="py-1.5 text-slate-500">{g.source}</td>
                  <td className="py-1.5 text-right tabular-nums text-slate-500">
                    {g.member_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}


function SiteAdministrators({ siteId }: { siteId: string }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const admins = useQuery({ queryKey: ["site-administrators", siteId], queryFn: () => sitesApi.administrators(siteId) });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["site-administrators", siteId] });
                        void qc.invalidateQueries({ queryKey: ["my-workspaces"] }); };
  const add = useMutation({ mutationFn: () => sitesApi.addAdministrator(siteId, email),
    onSuccess: () => { setEmail(""); refresh(); } });
  const remove = useMutation({ mutationFn: (userId: string) => sitesApi.removeAdministrator(siteId, userId),
    onSuccess: refresh });
  return <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
    <h2 className="text-sm font-semibold text-slate-900">Site administrators</h2>
    <p className="mt-1 text-sm text-slate-500">These people can manage access to this site and every workspace currently at it. They can grant roles to people and groups.</p>
    <ul className="mt-3 divide-y divide-slate-100 text-sm">
      {(admins.data ?? []).map((a) => <li key={a.user_id} className="flex justify-between gap-3 py-2">
        <span>{a.name || a.email} {a.name && <span className="text-slate-500">{a.email}</span>}</span>
        <button type="button" onClick={() => remove.mutate(a.user_id)} className="text-xs text-red-600">Remove</button>
      </li>)}
      {admins.data?.length === 0 && <li className="py-2 text-slate-500">No site administrator assigned.</li>}
    </ul>
    <form onSubmit={(e) => { e.preventDefault(); if (email.trim()) add.mutate(); }} className="mt-3 flex flex-wrap gap-2">
      <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
             aria-label="Site administrator email" placeholder="Administrator email"
             className="min-w-48 flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm" />
      <button type="submit" disabled={add.isPending} className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white">Add administrator</button>
    </form>
    {(add.error || remove.error) && <p className="mt-2 text-sm text-red-600">
      {((add.error || remove.error) as ApiError)?.detail ?? "Could not update site administrators."}</p>}
  </section>;
}


/** People given a role here by their e-mail address, before they have ever signed in. */
function Invite({ workspaceId, roles, onDone }: { workspaceId: string; roles: { id: string; name: string }[]; onDone: () => void }) {
  const [emails, setEmails] = useState("");
  const [roleId, setRoleId] = useState("viewer");
  const [sendEmail, setSendEmail] = useState(true);
  const [message, setMessage] = useState("");
  // "" each person gets the role; a group's uid, or NEW for a new group: they join it, and the group gets the role.
  const [into, setInto] = useState("");
  const [newGroup, setNewGroup] = useState("");
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => directoryApi.groups() });
  const local = (groups.data ?? []).filter((g) => g.source === "local" && g.active);
  const invite = useMutation({
    mutationFn: () => rolesApi.invite(workspaceId, {
      emails, role_id: roleId, send_email: sendEmail, ...(message.trim() ? { message } : {}),
      ...(into === "NEW" ? { new_group: newGroup } : into ? { group_uid: into } : {}),
    }),
    onSuccess: () => {
      setEmails("");
      onDone();
    },
  });
  const out = invite.data;
  return (
    <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">Invite by e-mail</h2>
      <p className="mt-1 text-sm text-slate-500">
        Give people a role here before they have ever signed in. Their first sign-in with the same address claims it.
        A different address does not, so use the one they sign in with (for INFN AAI, the address AAI gives them).
      </p>
      <form onSubmit={(e) => { e.preventDefault(); if (emails.trim()) invite.mutate(); }} className="mt-3 space-y-2">
        <textarea value={emails} onChange={(e) => setEmails(e.target.value)} rows={3} required
                  aria-label="E-mail addresses"
                  placeholder="name.surname@infn.it, another@lnf.infn.it — one or more, separated by commas or new lines"
                  className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label>Role{" "}
            <select value={roleId} onChange={(e) => setRoleId(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          </label>
          <label title="Into a group: they join it, and the group (not each person) gets the role here, so whoever joins it later has it too">
            Given to{" "}
            <select value={into} onChange={(e) => setInto(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
              <option value="">each person</option>
              {local.map((g) => <option key={g.uid} value={g.uid}>the group {g.name}</option>)}
              <option value="NEW">a new group…</option>
            </select>
          </label>
          {into === "NEW" && (
            <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} required placeholder="Group name"
                   aria-label="New group name" className="w-44 rounded border border-slate-300 px-2 py-1" />
          )}
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />
            send an invitation e-mail
          </label>
          <button type="submit" disabled={invite.isPending || !emails.trim()}
                  className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
            {invite.isPending ? "Inviting…" : "Invite"}
          </button>
        </div>
        {sendEmail && (
          <input value={message} onChange={(e) => setMessage(e.target.value)} aria-label="A line for the e-mail"
                 placeholder="A line for the e-mail (optional)"
                 className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        )}
      </form>
      {invite.isError && (
        <p className="mt-2 text-sm text-red-600">{(invite.error as ApiError)?.detail ?? "Could not invite them."}</p>
      )}
      {out && (
        <ul className="mt-3 space-y-1 text-sm">
          {out.group_name && (
            <li className="text-slate-700">
              Group <span className="font-medium">{out.group_name}</span>
              {out.role_name ? (out.group_granted ? ` now has ${out.role_name} here` : ` already had ${out.role_name} here`) : ""}
            </li>
          )}
          {out.people.map((p) => (
            <li key={p.email}>
              <span className="font-medium">{p.email}</span>{" "}
              <span className="text-slate-600">
                {p.added ? "added" : "already known"}
                {out.group_name
                  ? (p.joined ? ` · joined ${out.group_name}` : ` · already in ${out.group_name}`)
                  : (p.granted ? ` · ${out.role_name} granted` : ` · already ${out.role_name}`)}
                {p.emailed ? " · e-mailed" : ""}
                {!p.signed_in ? " · waiting for their first sign-in" : ""}
              </span>
              {p.error && <span className="text-amber-700"> · e-mail not sent: {p.error}</span>}
            </li>
          ))}
          {out.not_addresses.length > 0 && (
            <li className="text-red-600">Not e-mail addresses, left out: {out.not_addresses.join(", ")}</li>
          )}
        </ul>
      )}
    </div>
  );
}
