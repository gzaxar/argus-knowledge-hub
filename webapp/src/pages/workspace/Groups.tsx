import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, directoryApi, rolesApi, workspacesApi } from "../../api/client";
import type { DirectoryGroup } from "../../api/types";

/** The groups people are put in, to give them roles together: those made here, and the directory's (read only). */
export function WorkspaceGroups() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const qc = useQueryClient();
  const groups = useQuery({ queryKey: ["groups", workspaceId ? "all" : "mine"],
    queryFn: workspaceId ? directoryApi.allGroups : directoryApi.myGroups });
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const access = useQuery({ queryKey: ["my-permissions", workspaceId],
    queryFn: () => rolesApi.myPermissions(workspaceId!), enabled: !!workspaceId });
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ofSite, setOfSite] = useState(false);
  const [filter, setFilter] = useState("");
  // The site this workspace belongs to (itself, when it is one): a group can be owned by it (issue #26).
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const here = mine.data?.find((w) => w.id === workspaceId);
  const siteId = here?.role === "site" ? here.id : here?.site_id ?? null;
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["groups"] });
    void qc.invalidateQueries({ queryKey: ["bindings", workspaceId] });
  };
  const create = useMutation({
    mutationFn: () => directoryApi.createGroup({ name, ...(description.trim() ? { description } : {}),
                                                 ...(ofSite && siteId ? { home_site_id: siteId } : {}) }),
    onSuccess: (g) => { setName(""); setDescription(""); setOpen(g.uid); refresh(); },
  });
  const n = filter.trim().toLowerCase();
  const shown = (groups.data ?? []).filter((g) => !n || g.name.toLowerCase().includes(n));
  const local = shown.filter((g) => g.source === "local");
  const directory = shown.filter((g) => g.source !== "local");
  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold text-slate-900">Groups</h1>
      <p className="mt-1 text-sm text-slate-500">
        {workspaceId ? <>Put people in a group and give the group a role on{" "}
          <Link to={`/workspaces/${workspaceId}/access`} className="text-indigo-600 hover:underline">Access</Link>: whoever
          joins it later has the role too. </> : <>Groups assigned to you as an administrator. </>}
        A group can hold roles in several workspaces. Its named administrators manage members; directory groups are changed in the directory.
      </p>

      {workspaceId && (me.data?.is_admin || access.data?.workspace.includes("manage_members")) &&
      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}
            className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New group name" required
               aria-label="New group name" className="w-56 rounded border border-slate-300 px-2 py-1.5" />
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it is for (optional)"
               aria-label="Description" className="min-w-48 flex-1 rounded border border-slate-300 px-2 py-1.5" />
        {siteId && (
          <label className="flex items-center gap-1" title="Owned by the site: its administrators govern it, and it can have roles only at the site and its facilities">
            <input type="checkbox" checked={ofSite} onChange={(e) => setOfSite(e.target.checked)} />
            the site {siteId}&apos;s
          </label>
        )}
        <button type="submit" disabled={create.isPending}
                className="rounded bg-slate-900 px-4 py-1.5 font-medium text-white hover:bg-slate-800 disabled:opacity-50">
          Create group
        </button>
        {create.isError && <span className="text-red-600">{(create.error as ApiError)?.detail ?? "Could not create it."}</span>}
      </form>}

      <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a group"
             aria-label="Find a group" className="mt-4 w-64 rounded border border-slate-300 px-2 py-1.5 text-sm" />

      <h2 className="mt-5 text-sm font-semibold text-slate-900">{workspaceId ? "Made here" : "Assigned to me"} ({local.length})</h2>
      <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {local.map((g) => (
          <GroupRow key={g.uid} group={g} open={open === g.uid} onToggle={() => setOpen(open === g.uid ? null : g.uid)}
                    onChanged={refresh} editable canAppoint={!!workspaceId && (!!me.data?.is_admin || !!access.data?.workspace.includes("manage_members"))}
                    currentUserId={me.data?.user_id} />
        ))}
        {local.length === 0 && <li className="px-4 py-3 text-sm text-slate-400">None yet.</li>}
      </ul>

      {workspaceId && <><h2 className="mt-5 text-sm font-semibold text-slate-900">From the directory ({directory.length})</h2>
      <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {directory.map((g) => (
          <GroupRow key={g.uid} group={g} open={open === g.uid} onToggle={() => setOpen(open === g.uid ? null : g.uid)}
                    onChanged={refresh} editable={false} canAppoint={false} currentUserId={me.data?.user_id} />
        ))}
        {directory.length === 0 && <li className="px-4 py-3 text-sm text-slate-400">None.</li>}
      </ul></>}
    </div>
  );
}

function GroupRow({ group: g, open, onToggle, onChanged, editable, canAppoint, currentUserId }: {
  group: DirectoryGroup; open: boolean; onToggle: () => void; onChanged: () => void; editable: boolean;
  canAppoint: boolean; currentUserId?: string | null;
}) {
  return (
    <li className="px-4 py-2">
      <button type="button" onClick={onToggle} className="flex w-full items-baseline justify-between gap-3 text-left">
        <span>
          <span className={`font-medium ${g.active ? "text-slate-900" : "text-slate-400 line-through"}`}>{g.name}</span>
          {g.description && <span className="ml-2 text-sm text-slate-500">{g.description}</span>}
        </span>
        <span className="shrink-0 text-xs text-slate-500">
          {g.member_count} member{g.member_count === 1 ? "" : "s"}
          {g.home_site_id ? ` · the site ${g.home_site_id}'s` : g.source === "local" ? " · the installation's" : ""}
          {g.workspaces?.length ? ` · roles in ${g.workspaces.join(", ")}` : ""}
          {g.site_grants?.length ? ` · site-wide: ${g.site_grants.map((s) => `${s.role_name} at ${s.site_id}`).join(", ")}` : ""}
          {!g.workspaces?.length && !g.site_grants?.length ? " · no role yet" : ""}
          {!g.active && " · inactive"}
        </span>
      </button>
      {open && <GroupDetail group={g} onChanged={onChanged} editable={editable}
                            canAppoint={canAppoint} currentUserId={currentUserId} />}
    </li>
  );
}

function GroupDetail({ group: g, onChanged, editable, canAppoint, currentUserId }: {
  group: DirectoryGroup; onChanged: () => void; editable: boolean;
  canAppoint: boolean; currentUserId?: string | null;
}) {
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["group-members", g.uid], queryFn: () => directoryApi.groupMembers(g.uid) });
  const administrators = useQuery({ queryKey: ["group-administrators", g.uid],
    queryFn: () => directoryApi.groupAdministrators(g.uid), enabled: editable });
  const canEditMembers = editable && (canAppoint || !!administrators.data?.some((a) => a.user_id === currentUserId));
  const [administratorEmail, setAdministratorEmail] = useState("");
  const [emails, setEmails] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [rename, setRename] = useState(g.name);
  const done = () => { void qc.invalidateQueries({ queryKey: ["group-members", g.uid] }); onChanged(); };
  const add = useMutation({
    mutationFn: () => directoryApi.addGroupMembers(g.uid, { emails, send_email: sendEmail }),
    onSuccess: () => { setEmails(""); done(); },
  });
  const remove = useMutation({ mutationFn: (userId: string) => directoryApi.removeGroupMember(g.uid, userId), onSuccess: done });
  const update = useMutation({
    mutationFn: (input: { name?: string; active?: boolean }) => directoryApi.updateGroup(g.uid, input),
    onSuccess: done,
  });
  const appoint = useMutation({ mutationFn: () => directoryApi.addGroupAdministrator(g.uid, administratorEmail),
    onSuccess: () => { setAdministratorEmail(""); void qc.invalidateQueries({ queryKey: ["group-administrators", g.uid] }); } });
  const revoke = useMutation({ mutationFn: (userId: string) => directoryApi.removeGroupAdministrator(g.uid, userId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["group-administrators", g.uid] }) });
  const error = [add, remove, update, appoint, revoke].find((m) => m.isError)?.error as ApiError | undefined;
  return (
    <div className="mt-2 space-y-3 rounded bg-slate-50 p-3 text-sm">
      {editable && <section className="rounded border border-slate-200 bg-white p-3">
        <h3 className="font-medium text-slate-900">Group administrators</h3>
        <p className="mt-1 text-xs text-slate-500">They manage this group&apos;s members. Membership changes affect every workspace listed above.</p>
        <ul className="mt-2 space-y-1">
          {(administrators.data ?? []).map((a) => <li key={a.user_id} className="flex justify-between gap-2">
            <span>{a.name || a.email} <span className="text-slate-500">{a.name ? a.email : ""}</span></span>
            {canAppoint && <button type="button" className="text-xs text-red-600" onClick={() => revoke.mutate(a.user_id)}>Remove</button>}
          </li>)}
          {administrators.data?.length === 0 && <li className="text-slate-500">No group administrator assigned.</li>}
        </ul>
        {canAppoint && <form onSubmit={(e) => { e.preventDefault(); if (administratorEmail.trim()) appoint.mutate(); }}
                               className="mt-2 flex gap-2">
          <input type="email" required value={administratorEmail} onChange={(e) => setAdministratorEmail(e.target.value)}
                 placeholder="Administrator email" aria-label="Group administrator email"
                 className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1" />
          <button type="submit" disabled={appoint.isPending} className="rounded border border-slate-300 px-3 py-1">Add administrator</button>
        </form>}
      </section>}
      <ul className="space-y-1">
        {(members.data ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center justify-between gap-2">
            <span>{m.name ? `${m.name} · ` : ""}<span className="text-slate-600">{m.email}</span>
              {!m.active && <span className="ml-2 text-xs text-slate-400">inactive</span>}</span>
            {canEditMembers && (
              <button type="button" className="text-xs text-red-500 hover:text-red-700"
                      onClick={() => { if (confirm(`Take ${m.email} out of ${g.name}?`)) remove.mutate(m.user_id); }}>
                Remove
              </button>
            )}
          </li>
        ))}
        {members.data?.length === 0 && <li className="text-slate-400">Nobody in it yet.</li>}
      </ul>
      {canEditMembers && (
        <>
          <form onSubmit={(e) => { e.preventDefault(); if (emails.trim()) add.mutate(); }} className="space-y-2">
            <textarea value={emails} onChange={(e) => setEmails(e.target.value)} rows={2} aria-label="Addresses to add"
                      placeholder="Add people by e-mail: one or more, separated by commas or new lines"
                      className="w-full rounded border border-slate-300 px-2 py-1.5" />
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />
                tell them by e-mail
              </label>
              <button type="submit" disabled={add.isPending || !emails.trim()}
                      className="rounded bg-slate-900 px-3 py-1 font-medium text-white disabled:opacity-50">Add</button>
            </div>
          </form>
          {add.data && (
            <ul className="text-xs text-slate-600">
              {add.data.people.map((p) => (
                <li key={p.email}>{p.email}: {p.joined ? "joined" : "already in it"}{p.added ? ", new to ARGUS" : ""}
                  {p.emailed ? ", e-mailed" : ""}{p.error ? <span className="text-amber-700"> (e-mail not sent: {p.error})</span> : null}</li>
              ))}
              {add.data.not_addresses.length > 0 && <li className="text-red-600">Not addresses: {add.data.not_addresses.join(", ")}</li>}
            </ul>
          )}
          {canAppoint && <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-2">
            <input value={rename} onChange={(e) => setRename(e.target.value)} aria-label="Group name"
                   className="w-56 rounded border border-slate-300 px-2 py-1" />
            <button type="button" disabled={!rename.trim() || rename === g.name} onClick={() => update.mutate({ name: rename })}
                    className="rounded border border-slate-300 px-3 py-1 hover:bg-white disabled:opacity-50">Rename</button>
            <button type="button" onClick={() => update.mutate({ active: !g.active })}
                    className="rounded border border-slate-300 px-3 py-1 hover:bg-white">
              {g.active ? "Deactivate" : "Reactivate"}
            </button>
            <span className="text-xs text-slate-500">A deactivated group keeps its members; its roles stop applying.</span>
          </div>}
        </>
      )}
      {error && <p className="text-red-600">{error.detail ?? "Could not do that."}</p>}
    </div>
  );
}
