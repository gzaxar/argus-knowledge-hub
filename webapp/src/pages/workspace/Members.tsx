import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError, workspacesApi } from "../../api/client";
import { DefaultAccess, Member, MemberCandidate, MemberInput } from "../../api/types";

const OBJECT_FLAGS = [
  ["can_read", "Read"],
  ["can_create", "Create"],
  ["can_modify", "Modify"],
  ["can_delete", "Delete"],
] as const;

const TICKET_FLAGS = [
  ["can_read_tickets", "Read"],
  ["can_create_tickets", "Create"],
  ["can_modify_tickets", "Modify"],
  ["can_delete_tickets", "Delete"],
] as const;

const DOCUMENT_FLAGS = [
  ["can_read_documents", "Read"],
  ["can_create_documents", "Create"],
  ["can_modify_documents", "Modify"],
  ["can_delete_documents", "Delete"],
  ["can_approve_documents", "Approve"],
] as const;

const DEFAULT_OBJECT_FLAGS = [
  "default_can_read",
  "default_can_create",
  "default_can_modify",
  "default_can_delete",
] as const;

const DEFAULT_TICKET_FLAGS = [
  "default_can_read_tickets",
  "default_can_create_tickets",
  "default_can_modify_tickets",
  "default_can_delete_tickets",
] as const;

const DEFAULT_DOCUMENT_FLAGS = [
  "default_can_read_documents",
  "default_can_create_documents",
  "default_can_modify_documents",
  "default_can_delete_documents",
  "default_can_approve_documents",
] as const;

type FlagEntry = typeof OBJECT_FLAGS[number] | typeof TICKET_FLAGS[number] | typeof DOCUMENT_FLAGS[number];
type DefaultFlagName =
  | typeof DEFAULT_OBJECT_FLAGS[number]
  | typeof DEFAULT_TICKET_FLAGS[number]
  | typeof DEFAULT_DOCUMENT_FLAGS[number];

interface Group {
  key: "assets" | "tickets" | "documents";
  label: string;
  flags: readonly FlagEntry[];
  defaultFlags: readonly DefaultFlagName[];
}

const GROUPS: readonly Group[] = [
  { key: "assets", label: "Objects & Types", flags: OBJECT_FLAGS, defaultFlags: DEFAULT_OBJECT_FLAGS },
  { key: "tickets", label: "Tickets", flags: TICKET_FLAGS, defaultFlags: DEFAULT_TICKET_FLAGS },
  { key: "documents", label: "Documents", flags: DOCUMENT_FLAGS, defaultFlags: DEFAULT_DOCUMENT_FLAGS },
];

function toInput(m: Member): MemberInput {
  return {
    email: m.email,
    can_read: m.can_read,
    can_create: m.can_create,
    can_modify: m.can_modify,
    can_delete: m.can_delete,
    can_read_tickets: m.can_read_tickets,
    can_create_tickets: m.can_create_tickets,
    can_modify_tickets: m.can_modify_tickets,
    can_delete_tickets: m.can_delete_tickets,
    can_read_documents: m.can_read_documents,
    can_create_documents: m.can_create_documents,
    can_modify_documents: m.can_modify_documents,
    can_delete_documents: m.can_delete_documents,
    can_approve_documents: m.can_approve_documents,
  };
}

function toDefaultInput(w: DefaultAccess): DefaultAccess {
  return {
    default_can_read: w.default_can_read,
    default_can_create: w.default_can_create,
    default_can_modify: w.default_can_modify,
    default_can_delete: w.default_can_delete,
    default_can_read_tickets: w.default_can_read_tickets,
    default_can_create_tickets: w.default_can_create_tickets,
    default_can_modify_tickets: w.default_can_modify_tickets,
    default_can_delete_tickets: w.default_can_delete_tickets,
    default_can_read_documents: w.default_can_read_documents,
    default_can_create_documents: w.default_can_create_documents,
    default_can_modify_documents: w.default_can_modify_documents,
    default_can_delete_documents: w.default_can_delete_documents,
    default_can_approve_documents: w.default_can_approve_documents,
  };
}

export function WorkspaceMembers() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");

  const sectionParam = searchParams.get("section");
  const scoped = GROUPS.some((g) => g.key === sectionParam);
  const groups = scoped ? GROUPS.filter((g) => g.key === sectionParam) : GROUPS;
  const colCount = groups.reduce<number>((n, g) => n + g.flags.length, 0);

  const members = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => workspacesApi.listMembers(workspaceId!),
    enabled: !!workspaceId,
    retry: false, // a 403 here is permanent, not transient — retrying just delays the message
  });

  const workspace = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => workspacesApi.get(workspaceId!),
    enabled: !!workspaceId,
    retry: false,
  });

  const upsertMutation = useMutation({
    mutationFn: (input: MemberInput) => workspacesApi.upsertMember(workspaceId!, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members", workspaceId] }),
  });

  const defaultAccessMutation = useMutation({
    mutationFn: (input: DefaultAccess) => workspacesApi.setDefaultAccess(workspaceId!, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId] }),
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => workspacesApi.removeMember(workspaceId!, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members", workspaceId] }),
  });

  const add = (address: string) => {
    upsertMutation.mutate({
      email: address.trim(),
      can_read: true,
      can_create: false,
      can_modify: false,
      can_delete: false,
      can_read_tickets: true,
      can_create_tickets: false,
      can_modify_tickets: false,
      can_delete_tickets: false,
      can_read_documents: true,
      can_create_documents: false,
      can_modify_documents: false,
      can_delete_documents: false,
      can_approve_documents: false,
    });
    setEmail("");
  };

  const [filter, setFilter] = useState("");
  const filterWords = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shownMembers = (members.data ?? []).filter((m) => {
    const text = `${m.email} ${m.name ?? ""}`.toLowerCase();
    return filterWords.every((w) => text.includes(w));
  });

  if (members.isError) {
    const forbidden = members.error instanceof ApiError && members.error.status === 403;
    return (
      <p className="text-sm text-red-600">
        {forbidden
          ? "You don't have permission to manage members of this workspace."
          : "Failed to load members."}
      </p>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">
        Members of {workspace.data?.name ?? workspaceId}{" "}
        <code className="rounded bg-slate-100 px-1.5 py-0.5 align-middle text-sm font-normal text-slate-600">{workspaceId}</code>
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {scoped ? (
          <>
            Showing {groups[0].label} permissions only.{" "}
            <Link to={`/workspaces/${workspaceId}/members`} className="text-indigo-600 hover:underline">
              View all permissions
            </Link>
          </>
        ) : (
          "Objects & types, tickets and documents have independent rights per member."
        )}
      </p>

      <div className="mt-6 flex flex-wrap items-start gap-3">
        <AddMember workspaceId={workspaceId!} value={email} onChange={setEmail} onAdd={add}
                   busy={upsertMutation.isPending} />
        {(members.data?.length ?? 0) > 8 && (
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter members…"
            className="w-56 rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
        )}
      </div>
      {upsertMutation.isError && (
        <p className="mt-2 text-sm text-red-600">
          {upsertMutation.error instanceof ApiError
            ? JSON.stringify(upsertMutation.error.body)
            : "Failed to add member"}
        </p>
      )}

      {members.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}

      {members.data && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2" rowSpan={2}>Email</th>
                <th className="px-4 py-2" rowSpan={2}>Name</th>
                {groups.map((g) => (
                  <th
                    key={g.key}
                    className="border-l border-slate-200 px-4 py-1 text-center"
                    colSpan={g.flags.length}
                  >
                    {g.label}
                  </th>
                ))}
                <th className="px-4 py-2" rowSpan={2} />
              </tr>
              <tr>
                {groups.map((g) =>
                  g.flags.map(([flag, label]) => (
                    <th
                      key={flag}
                      className="border-l border-slate-100 px-4 py-1 text-center font-normal"
                    >
                      {label}
                    </th>
                  )),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {workspace.data && (
                <tr className="bg-amber-50/60">
                  <td className="px-4 py-2 font-medium italic text-slate-700">Anonymous</td>
                  <td className="px-4 py-2 text-xs italic text-slate-500">
                    Any authenticated user not listed below
                  </td>
                  {groups.flatMap((g) => g.defaultFlags).map((flag) => (
                    <td key={flag} className="border-l border-slate-100 px-4 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={workspace.data[flag]}
                        onChange={(e) =>
                          defaultAccessMutation.mutate({
                            ...toDefaultInput(workspace.data),
                            [flag]: e.target.checked,
                          })
                        }
                      />
                    </td>
                  ))}
                  <td className="px-4 py-2" />
                </tr>
              )}
              {shownMembers.map((m) => (
                <tr key={m.user_id}>
                  <td className="px-4 py-2 font-medium text-slate-900">{m.email}</td>
                  <td className="px-4 py-2 text-slate-500">{m.name ?? "—"}</td>
                  {groups.flatMap((g) => g.flags).map(([flag]) => (
                    <td key={flag} className="border-l border-slate-100 px-4 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={m[flag]}
                        onChange={(e) =>
                          upsertMutation.mutate({ ...toInput(m), [flag]: e.target.checked })
                        }
                      />
                    </td>
                  ))}
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Remove ${m.email} from ${workspace.data?.name ?? workspaceId}?`)) {
                          removeMutation.mutate(m.user_id);
                        }
                      }}
                      className="text-red-500 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
              {members.data.length === 0 && (
                <tr>
                  <td colSpan={colCount + 3} className="px-4 py-6 text-center text-slate-400">
                    No members yet.
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

/** Add a member: type part of a name or an e-mail and pick among the people who have signed in. */
function AddMember({ workspaceId, value, onChange, onAdd, busy }: {
  workspaceId: string;
  value: string;
  onChange: (v: string) => void;
  onAdd: (email: string) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [debounced, setDebounced] = useState(value);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value.trim()), 200);
    return () => window.clearTimeout(t);
  }, [value]);
  const candidates = useQuery({
    queryKey: ["member-candidates", workspaceId, debounced],
    queryFn: () => workspacesApi.memberCandidates(workspaceId, debounced),
    enabled: open && debounced.length >= 2,
    staleTime: 30_000,
  });
  const list: MemberCandidate[] = candidates.data ?? [];
  useEffect(() => setActive(0), [debounced]);

  const pick = (c: MemberCandidate) => {
    if (c.member) return;
    onAdd(c.email);
    setOpen(false);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const chosen = open ? list[active] : undefined;
        if (chosen && !chosen.member) pick(chosen);
        else if (value.includes("@")) onAdd(value);
      }}
      className="flex gap-3"
    >
      <div className="relative">
        <input
          value={value}
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, list.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
            if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Add a member: type a name or an e-mail…"
          autoComplete="off"
          className="w-96 rounded border border-slate-300 px-3 py-1.5 text-sm"
        />
        {open && debounced.length >= 2 && (
          <ul className="absolute z-20 mt-1 max-h-80 w-full overflow-auto rounded border border-slate-200 bg-white py-1 text-sm shadow-lg">
            {candidates.isLoading && <li className="px-3 py-1.5 text-slate-400">Searching…</li>}
            {candidates.data && list.length === 0 && (
              <li className="px-3 py-1.5 text-slate-500">
                Nobody who has signed in matches. People appear here after their first sign-in to ARGUS.
              </li>
            )}
            {list.map((c, i) => (
              <li key={c.user_id}>
                <button
                  type="button"
                  disabled={c.member}
                  onMouseDown={(e) => { e.preventDefault(); pick(c); }}
                  onMouseEnter={() => setActive(i)}
                  className={`flex w-full items-baseline justify-between gap-3 px-3 py-1.5 text-left ${
                    c.member ? "cursor-default text-slate-400" : i === active ? "bg-slate-100" : "hover:bg-slate-50"}`}
                >
                  <span className="truncate">
                    <span className="font-medium">{c.name || c.email}</span>
                    {c.name && <span className="ml-2 text-xs text-slate-500">{c.email}</span>}
                  </span>
                  {c.member && <span className="shrink-0 text-xs">already a member</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <button
        type="submit"
        disabled={busy || !value.trim()}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        Add
      </button>
    </form>
  );
}
