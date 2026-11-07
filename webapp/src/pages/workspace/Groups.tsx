import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, directoryApi } from "../../api/client";
import type { DirectoryGroup } from "../../api/types";

/** The groups people are put in, to give them roles together: those made here, and the directory's (read only). */
export function WorkspaceGroups() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const qc = useQueryClient();
  const groups = useQuery({ queryKey: ["groups", "all"], queryFn: directoryApi.allGroups });
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [filter, setFilter] = useState("");
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["groups"] });
    void qc.invalidateQueries({ queryKey: ["bindings", workspaceId] });
  };
  const create = useMutation({
    mutationFn: () => directoryApi.createGroup({ name, ...(description.trim() ? { description } : {}) }),
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
        Put people in a group and give the group a role on{" "}
        <Link to={`/workspaces/${workspaceId}/access`} className="text-indigo-600 hover:underline">Access</Link>: whoever
        joins it later has the role too. A group can hold roles in several workspaces, so its members are changed by
        an administrator, or by someone who manages every workspace where it holds one. The directory&apos;s groups are
        shown for reference and are changed in the directory.
      </p>

      <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}
            className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-sm">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New group name" required
               aria-label="New group name" className="w-56 rounded border border-slate-300 px-2 py-1.5" />
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it is for (optional)"
               aria-label="Description" className="min-w-48 flex-1 rounded border border-slate-300 px-2 py-1.5" />
        <button type="submit" disabled={create.isPending}
                className="rounded bg-slate-900 px-4 py-1.5 font-medium text-white hover:bg-slate-800 disabled:opacity-50">
          Create group
        </button>
        {create.isError && <span className="text-red-600">{(create.error as ApiError)?.detail ?? "Could not create it."}</span>}
      </form>

      <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a group"
             aria-label="Find a group" className="mt-4 w-64 rounded border border-slate-300 px-2 py-1.5 text-sm" />

      <h2 className="mt-5 text-sm font-semibold text-slate-900">Made here ({local.length})</h2>
      <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {local.map((g) => (
          <GroupRow key={g.uid} group={g} open={open === g.uid} onToggle={() => setOpen(open === g.uid ? null : g.uid)}
                    onChanged={refresh} editable />
        ))}
        {local.length === 0 && <li className="px-4 py-3 text-sm text-slate-400">None yet.</li>}
      </ul>

      <h2 className="mt-5 text-sm font-semibold text-slate-900">From the directory ({directory.length})</h2>
      <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {directory.map((g) => (
          <GroupRow key={g.uid} group={g} open={open === g.uid} onToggle={() => setOpen(open === g.uid ? null : g.uid)}
                    onChanged={refresh} editable={false} />
        ))}
        {directory.length === 0 && <li className="px-4 py-3 text-sm text-slate-400">None.</li>}
      </ul>
    </div>
  );
}

function GroupRow({ group: g, open, onToggle, onChanged, editable }: {
  group: DirectoryGroup; open: boolean; onToggle: () => void; onChanged: () => void; editable: boolean;
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
          {g.workspaces?.length ? ` · roles in ${g.workspaces.join(", ")}` : " · no role yet"}
          {!g.active && " · inactive"}
        </span>
      </button>
      {open && <GroupDetail group={g} onChanged={onChanged} editable={editable} />}
    </li>
  );
}

function GroupDetail({ group: g, onChanged, editable }: { group: DirectoryGroup; onChanged: () => void; editable: boolean }) {
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["group-members", g.uid], queryFn: () => directoryApi.groupMembers(g.uid) });
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
  const error = [add, remove, update].find((m) => m.isError)?.error as ApiError | undefined;
  return (
    <div className="mt-2 space-y-3 rounded bg-slate-50 p-3 text-sm">
      <ul className="space-y-1">
        {(members.data ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center justify-between gap-2">
            <span>{m.name ? `${m.name} · ` : ""}<span className="text-slate-600">{m.email}</span>
              {!m.active && <span className="ml-2 text-xs text-slate-400">inactive</span>}</span>
            {editable && (
              <button type="button" className="text-xs text-red-500 hover:text-red-700"
                      onClick={() => { if (confirm(`Take ${m.email} out of ${g.name}?`)) remove.mutate(m.user_id); }}>
                Remove
              </button>
            )}
          </li>
        ))}
        {members.data?.length === 0 && <li className="text-slate-400">Nobody in it yet.</li>}
      </ul>
      {editable && (
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
          <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-2">
            <input value={rename} onChange={(e) => setRename(e.target.value)} aria-label="Group name"
                   className="w-56 rounded border border-slate-300 px-2 py-1" />
            <button type="button" disabled={!rename.trim() || rename === g.name} onClick={() => update.mutate({ name: rename })}
                    className="rounded border border-slate-300 px-3 py-1 hover:bg-white disabled:opacity-50">Rename</button>
            <button type="button" onClick={() => update.mutate({ active: !g.active })}
                    className="rounded border border-slate-300 px-3 py-1 hover:bg-white">
              {g.active ? "Deactivate" : "Reactivate"}
            </button>
            <span className="text-xs text-slate-500">A deactivated group keeps its members; its roles stop applying.</span>
          </div>
        </>
      )}
      {error && <p className="text-red-600">{error.detail ?? "Could not do that."}</p>}
    </div>
  );
}
