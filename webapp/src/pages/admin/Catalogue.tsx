import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { directoryApi, rolesApi, systemCatalogueApi, workspacesApi, type SystemCatalogueStatus } from "../../api/client";
import { getActiveProfile, updateProfile } from "../../api/session";
import { CatalogueCollectionsPage } from "../catalogue/CatalogueCollections";
import { problem } from "../catalogue/catalogueText";
import { GlpiMatches } from "../catalogue/ProductCatalogue";

function count(n: number | undefined, one: string, many = `${one}s`) {
  return `${n ?? 0} ${(n ?? 0) === 1 ? one : many}`;
}

/** Which workspace is the installation's catalogue, what it holds and what depends on it; with none, a way to
 *  designate one. */
function Status({ admin }: { admin: boolean }) {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["system-catalogue"], queryFn: systemCatalogueApi.status });
  const [chosen, setChosen] = useState("");
  const designate = useMutation({
    mutationFn: () => systemCatalogueApi.designate(chosen),
    onSuccess: (s) => {
      queryClient.setQueryData(["system-catalogue"], s);
      queryClient.invalidateQueries({ queryKey: ["catalogue-collections"] });
    },
  });
  const s = status.data;
  if (status.isError) return <p className="text-sm text-red-600">{problem(status.error)}</p>;
  if (!s) return <p className="text-sm text-slate-500">Loading…</p>;

  if (!s.designated) {
    if (!admin) return <p className="text-sm text-slate-500">This installation has no catalogue workspace yet: an administrator designates it.</p>;
    return (
      <section aria-label="Catalogue workspace" className="rounded border border-amber-300 bg-amber-50 p-4 text-sm">
        <h2 className="font-semibold text-amber-950">No catalogue workspace</h2>
        <p className="mt-1 text-amber-900">
          This installation has no catalogue yet. Designate the workspace that holds the shared Vendors and Product
          Models — it must hold nothing else. A new installation gets one by itself when a workspace is given the
          object catalogue as the one others hang from.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select aria-label="Workspace to designate" value={chosen} onChange={(e) => setChosen(e.target.value)}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">Choose…</option>
            {s.candidates.map((c) => <option key={c} value={c}>{c} (holds the shared types)</option>)}
          </select>
          <button type="button" disabled={!chosen || designate.isPending} onClick={() => designate.mutate()}
                  className="rounded bg-slate-900 px-3 py-1 text-sm font-medium text-white disabled:opacity-50">
            Designate
          </button>
        </div>
        {designate.isError && <p className="mt-2 text-red-700">{problem(designate.error)}</p>}
      </section>
    );
  }

  return <Designated s={s} admin={admin} />;
}

/** The catalogue: its name (administrators rename it), what it holds and what depends on it, any record that
 *  does not belong there, and — for administrators — a way into it as a workspace, to clean such a record up. */
function Designated({ s, admin }: { s: SystemCatalogueStatus; admin: boolean }) {
  const queryClient = useQueryClient();
  const [naming, setNaming] = useState<string | null>(null);
  const rename = useMutation({
    mutationFn: (name: string) => workspacesApi.update(s.designated!, { name }),
    onSuccess: () => {
      setNaming(null);
      queryClient.invalidateQueries({ queryKey: ["system-catalogue"] });
      queryClient.invalidateQueries({ queryKey: ["my-workspaces"] });
    },
  });
  function openAsWorkspace() {
    // The profile in use (with one sign-in, no profile is marked active: the first is the one).
    const profile = getActiveProfile();
    if (!profile) return;
    updateProfile(profile.id, { activeWorkspaceId: s.designated! });
    window.location.assign("/");
  }
  const units = Object.entries(s.units ?? {});
  const hanging = Object.entries(s.hanging ?? {});
  const others = Object.entries(s.other_records ?? {});
  return (
    <section aria-label="Catalogue workspace" className="rounded border border-slate-200 bg-white p-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {naming === null ? (
          <h2 className="font-semibold text-slate-900">
            {s.name} <span className="font-mono text-xs font-normal text-slate-400">{s.designated}</span>
            {admin && (
              <button type="button" onClick={() => setNaming(s.name ?? "")}
                      className="ml-2 text-xs font-normal text-sky-800 hover:underline">Rename</button>
            )}
          </h2>
        ) : (
          <form className="flex flex-wrap items-center gap-2"
                onSubmit={(e) => { e.preventDefault(); if (naming.trim()) rename.mutate(naming.trim()); }}>
            <input aria-label="Catalogue name" value={naming} onChange={(e) => setNaming(e.target.value)}
                   className="w-64 rounded border border-slate-300 px-2 py-1 text-sm" />
            <button type="submit" disabled={!naming.trim() || rename.isPending}
                    className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50">Save</button>
            <button type="button" onClick={() => setNaming(null)} className="text-xs text-slate-500">Cancel</button>
            <span className="text-xs text-slate-500">The id and the record keys stay: they are printed on labels.</span>
          </form>
        )}
        <Link to="/catalogue/models" className="text-xs text-sky-800 underline">Browse the models</Link>
      </div>
      {rename.isError && <p className="text-red-700">{problem(rename.error)}</p>}
      <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <div><dt className="inline text-slate-500">Holds </dt>
          <dd className="inline">{count(s.records?.["Product Model"], "Product Model")}, {count(s.records?.Vendor, "Vendor")}</dd></div>
        <div><dt className="inline text-slate-500">Types </dt>
          <dd className="inline">{s.shared_types} shared, {s.own_types} its own</dd></div>
        <div><dt className="inline text-slate-500">Units pointing at its models </dt>
          <dd className="inline">{units.reduce((n, [, k]) => n + k, 0)}
            {units.length > 0 && <span className="text-slate-500"> ({units.map(([w, n]) => `${w} ${n}`).join(", ")})</span>}</dd></div>
        <div><dt className="inline text-slate-500">Hanging from it </dt>
          <dd className="inline">{hanging.length ? hanging.map(([w]) => w).join(", ") : "none"}</dd></div>
        <div><dt className="inline text-slate-500">Collections </dt>
          <dd className="inline">{Object.entries(s.collections ?? {}).map(([c, v]) => `${c} ${v}`).join(", ") || "none installed yet"}</dd></div>
      </dl>
      {(others.length > 0 || (s.not_shared ?? 0) > 0) && (
        <p role="alert" className="mt-2 text-amber-800">
          {others.length > 0 && <>It also holds {others.map(([t, n]) => `${n} ${t}`).join(", ")}
            {(s.other_record_list ?? []).length > 0 && <> ({(s.other_record_list ?? []).map((r) => `${r.key} “${r.name}”`).join(", ")})</>}
            : these belong in a workspace. Copy each to the workspace it belongs in and delete it here
            {admin ? <>, from the catalogue opened as a workspace (below)</> : <>; an administrator can</>}. </>}
          {(s.not_shared ?? 0) > 0 && <>{count(s.not_shared, "record")} not shared with the other workspaces.</>}
        </p>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Protected: it holds Vendors and Product Models only, and cannot be deleted, transferred, exported as a
        workspace bundle or made to hang from another workspace. Its models are edited from any workspace (the
        edit is made here, by its maintainers); its shared types are upgraded on Administration › Packages.
      </p>
      {admin && (
        <p className="mt-1 text-xs text-slate-500">
          Rarely needed:{" "}
          <button type="button" onClick={openAsWorkspace} className="text-sky-800 hover:underline">
            open the catalogue as a workspace
          </button>{" "}
          (its record pages, access and imports), to clean up what does not belong in it.
        </p>
      )}
    </section>
  );
}

const MAINTAINER_ROLES: Record<string, string> = {
  curator: "edits Vendors and Product Models, installs collections, decides the review",
  owner: "also grants access to the catalogue",
};

/** Who maintains the catalogue: its workspace's Curators and Owners, granted and removed here. Everyone else
 *  reads it. Administrators only. */
function Maintainers({ catalogue }: { catalogue: string }) {
  const queryClient = useQueryClient();
  const bindings = useQuery({ queryKey: ["bindings", catalogue], queryFn: () => rolesApi.listBindings(catalogue) });
  const users = useQuery({ queryKey: ["admin-users"], queryFn: workspacesApi.listUsers });
  const groups = useQuery({ queryKey: ["groups"], queryFn: () => directoryApi.groups() });
  const [subjectType, setSubjectType] = useState<"user" | "group">("user");
  const [subjectId, setSubjectId] = useState("");
  const [roleId, setRoleId] = useState("curator");
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["bindings", catalogue] });
  const grant = useMutation({
    mutationFn: () => rolesApi.createBinding(catalogue, { subject_type: subjectType, subject_id: subjectId, role_id: roleId }),
    onSuccess: () => { setSubjectId(""); refresh(); },
  });
  const remove = useMutation({ mutationFn: (id: number) => rolesApi.deleteBinding(catalogue, id), onSuccess: refresh });
  const maintainers = (bindings.data ?? []).filter((b) => b.role_id in MAINTAINER_ROLES);
  const options = subjectType === "user"
    ? (users.data ?? []).filter((u) => !u.is_admin).map((u) => ({ id: u.id, label: u.name ? `${u.name} (${u.email})` : u.email }))
    : (groups.data ?? []).filter((g) => g.active).map((g) => ({ id: g.uid, label: g.name }));
  return (
    <section aria-label="Maintainers" className="space-y-2">
      <h2 className="text-sm font-semibold text-slate-900">Maintainers</h2>
      <p className="text-xs text-slate-500">
        Administrators maintain the catalogue. So do the people and groups given here: a <b>Curator</b>{" "}
        {MAINTAINER_ROLES.curator}; an <b>Owner</b> {MAINTAINER_ROLES.owner}. Everyone else reads it.
      </p>
      {bindings.isError && <p className="text-sm text-red-600">{problem(bindings.error)}</p>}
      <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white text-sm">
        {maintainers.length === 0 && <li className="px-3 py-2 text-slate-500">Only administrators, so far.</li>}
        {maintainers.map((b) => (
          <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
            <span>
              {b.subject_label}
              <span className="ml-1 text-xs text-slate-500">{b.subject_type === "group" ? "group" : "person"} · {b.role_name}</span>
              {!b.subject_active && <span className="ml-1 text-xs text-amber-700">inactive</span>}
            </span>
            <button type="button" onClick={() => remove.mutate(b.id)} disabled={remove.isPending}
                    aria-label={`Remove ${b.subject_label}`} className="text-xs text-red-700 hover:underline">Remove</button>
          </li>
        ))}
      </ul>
      <form onSubmit={(e) => { e.preventDefault(); if (subjectId) grant.mutate(); }}
            className="flex flex-wrap items-center gap-2">
        <select aria-label="Person or group" value={subjectType}
                onChange={(e) => { setSubjectType(e.target.value as "user" | "group"); setSubjectId(""); }}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="user">Person</option>
          <option value="group">Group</option>
        </select>
        <select aria-label="Who" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}
                className="min-w-0 max-w-full flex-1 rounded border border-slate-300 px-2 py-1 text-sm sm:max-w-xs">
          <option value="">{subjectType === "user" ? "Choose a person…" : "Choose a group…"}</option>
          {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
        <select aria-label="Role" value={roleId} onChange={(e) => setRoleId(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-sm">
          <option value="curator">Curator</option>
          <option value="owner">Owner</option>
        </select>
        <button type="submit" disabled={!subjectId || grant.isPending}
                className="rounded bg-slate-900 px-3 py-1 text-sm font-medium text-white disabled:opacity-50">Add</button>
      </form>
      {grant.isError && <p className="text-sm text-red-600">{problem(grant.error)}</p>}
    </section>
  );
}

/** GLPI's devices in a chosen workspace, matched to the catalogue's models through review. */
function GlpiSection({ catalogue }: { catalogue: string | null }) {
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const [ws, setWs] = useState("");
  const choices = (mine.data ?? []).filter((w) => w.id !== catalogue);
  return (
    <section aria-label="GLPI matching" className="space-y-2">
      <h2 className="text-sm font-semibold text-slate-900">Matching GLPI's devices</h2>
      <label className="block text-xs text-slate-500">
        Workspace with GLPI devices
        <select value={ws} onChange={(e) => setWs(e.target.value)}
                className="mt-0.5 block w-64 rounded border border-slate-300 px-2 py-1 text-sm text-slate-900">
          <option value="">Choose…</option>
          {choices.map((w) => <option key={w.id} value={w.id}>{w.name} ({w.id})</option>)}
        </select>
      </label>
      {ws && <GlpiMatches key={ws} workspaceId={ws} />}
    </section>
  );
}

/** Administration › Catalogue: the installation's catalogue of Vendors and Product Models — its workspace, its
 *  collections and their upgrades, the corrections for Git, and matching GLPI's devices to its models. */
export function AdminCataloguePage() {
  const status = useQuery({ queryKey: ["system-catalogue"], queryFn: systemCatalogueApi.status });
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Catalogue</h1>
        <p className="mt-1 text-sm text-slate-500">
          The installation's shared Vendors and Product Models, for every domain. Every workspace reads them; their
          units point at them. They come from versioned collections kept in Git, installed and upgraded here.
        </p>
      </div>
      <Status admin={!!me.data?.is_admin} />
      {status.data?.designated && (
        <>
          <section aria-label="Collections">
            <h2 className="mb-2 text-lg font-semibold text-slate-900">Collections</h2>
            <CatalogueCollectionsPage embedded />
          </section>
          {me.data?.is_admin && <Maintainers catalogue={status.data.designated} />}
          <GlpiSection catalogue={status.data.designated} />
        </>
      )}
    </div>
  );
}
