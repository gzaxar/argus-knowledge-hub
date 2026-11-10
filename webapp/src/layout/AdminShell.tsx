import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { directoryApi, workspacesApi } from "../api/client";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";

type Item = { to: string; label: string };
type Group = { label?: string; items: Item[] };

/** One section per scope, as access is decided: the current workspace, its site, the whole installation, and
 *  the groups a person administers. Each shows only to someone it is for. */
export function AdminShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const currentWorkspaceId = useCurrentWorkspaceId();

  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const managedGroups = useQuery({ queryKey: ["groups", "mine"], queryFn: directoryApi.myGroups,
    enabled: me.data?.auth_type === "oidc" });
  const location = useLocation();
  const workspaceName = (id: string | null) => mine.data?.find((w) => w.id === id)?.name ?? id;

  const workspaceGroups: Group[] = [];
  if (currentWorkspaceId) {
    const w = (path: string) => `/workspaces/${currentWorkspaceId}/${path}`;
    workspaceGroups.push(
      { label: "People & access", items: [
        { to: w("access"), label: "Access" },
        { to: w("groups"), label: "Groups" },
        { to: w("members"), label: "Area permissions" },
        { to: w("access-reviews"), label: "Access reviews" },
      ] },
      { label: "Content", items: [
        { to: w("imports"), label: "Imports" },
        { to: w("packages"), label: "Packages" },
        { to: w("keys"), label: "Keys" },
        { to: w("icons"), label: "Icon library" },
        { to: w("glpi"), label: "GLPI" },
        { to: w("transfer"), label: "Transfer" },
        { to: "/admin/migration", label: "Migration from Jira" },
        { to: w("integrity"), label: "Data integrity" },
      ] },
      { label: "Integrations", items: [
        { to: w("ai"), label: "AI endpoint" },
        { to: w("robot-tokens"), label: "Robot tokens" },
      ] },
    );
  }

  // The site of the current workspace (itself, if it is one) for an administrator of the installation, every
  // site they were named for to a site administrator, and the one whose page is open.
  const administered = me.data?.administered_sites ?? [];
  const current = mine.data?.find((w) => w.id === currentWorkspaceId);
  const currentSite = current?.role === "site" ? current.id : current?.site_id ?? null;
  const openSite = location.pathname.match(/^\/sites\/([^/]+)/)?.[1] ?? null;
  const sites = administered.filter((s) => me.data?.is_admin
    ? s.id === currentSite || s.id === openSite : true);

  const installation: Item[] = [];
  if (me.data?.is_admin) {
    installation.push(
      { to: "/admin/workspaces", label: "Workspaces" },
      { to: "/admin/users", label: "Users" },
      { to: "/admin/packages", label: "Packages (all workspaces)" },
      { to: "/admin/catalogue", label: "Catalogue" },
      { to: "/admin/ai", label: "AI settings" },
      { to: "/admin/tokens", label: "All tokens" },
      { to: "/admin/portability", label: "Portability" },
      { to: "/admin/type-migrations", label: "Type migrations" },
      { to: "/admin/statistics", label: "Statistics" },
      { to: "/admin/settings", label: "Settings" },
    );
  } else if (me.data?.catalogue_maintainer) {
    installation.push({ to: "/admin/catalogue", label: "Catalogue" });
  }
  const groupsItems: Item[] = (managedGroups.data?.length ?? 0) > 0 ? [{ to: "/admin/my-groups", label: "My groups" }] : [];

  const pageWorkspace = location.pathname.match(/^\/workspaces\/([^/]+)/)?.[1]
    ?? (location.pathname.startsWith("/admin/migration") ? currentWorkspaceId : null);
  const siteName = (id: string) => administered.find((s) => s.id === id)?.name ?? workspaceName(id) ?? id;

  const link = (item: Item) => (
    <NavLink
      key={item.to}
      to={item.to}
      className={({ isActive }) =>
        `block rounded px-3 py-1.5 text-sm font-medium ${
          isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
        }`
      }
    >
      {item.label}
    </NavLink>
  );

  const section = (key: string, title: string, colour: string, subtitle: ReactNode, groups: Group[]) => (
    <div key={key} className="space-y-1" aria-label={title} role="group">
      <p className={`px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide ${colour}`}>{title}</p>
      {subtitle && <p className="truncate px-3 pb-1 text-xs text-slate-500">{subtitle}</p>}
      {groups.map((g, i) => (
        <div key={g.label ?? i} className="space-y-0.5">
          {g.label && <p className="px-3 pt-2 text-[11px] font-medium text-slate-400">{g.label}</p>}
          {g.items.map(link)}
        </div>
      ))}
    </div>
  );

  const nothing = workspaceGroups.length === 0 && sites.length === 0 && installation.length === 0 && groupsItems.length === 0;

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-4">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-700">
            &larr; Back to ARGUS Knowledge Hub
          </Link>
          <p className="mt-1 text-sm font-semibold text-slate-900">Administration</p>
        </div>
        <nav className="space-y-5 overflow-y-auto p-2">
          {workspaceGroups.length > 0 && section("workspace", "Workspace", "text-sky-700",
            <span title={currentWorkspaceId ?? ""}>{workspaceName(currentWorkspaceId)}{" "}
              <code className="text-[11px]">{currentWorkspaceId}</code></span>, workspaceGroups)}
          {sites.map((s) => section(`site-${s.id}`, `Site ${s.name}`, "text-emerald-700",
            "Every facility at this site", [{ items: [
              { to: `/sites/${s.id}/administrators`, label: "Administrators" },
              { to: `/sites/${s.id}/group-access`, label: "Site-wide group access" },
              { to: `/sites/${s.id}/facilities`, label: "Facilities" },
            ] }]))}
          {installation.length > 0 && section("installation", "Installation", "text-amber-700",
            "Applies to every workspace", [{ items: installation }])}
          {groupsItems.length > 0 && section("groups", "Groups you administer", "text-violet-700",
            null, [{ items: groupsItems }])}
          {nothing && <p className="px-3 py-2 text-sm text-slate-400">Nothing to manage here yet.</p>}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        {pageWorkspace ? (
          <p className="mb-4 rounded border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs text-sky-900">
            Workspace <span className="font-semibold">{workspaceName(pageWorkspace)}</span>{" "}
            <code className="rounded bg-sky-100 px-1">{pageWorkspace}</code> — what you change here applies to this workspace only.
          </p>
        ) : openSite ? (
          <p className="mb-4 rounded border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900">
            Site <span className="font-semibold">{siteName(openSite)}</span>{" "}
            <code className="rounded bg-emerald-100 px-1">{openSite}</code> — what you change here applies to every facility at this site.
          </p>
        ) : location.pathname === "/admin/my-groups" ? (
          <p className="mb-4 rounded border border-violet-200 bg-violet-50 px-3 py-1.5 text-xs text-violet-900">
            Group membership changes apply wherever the group has a role.
          </p>
        ) : location.pathname.startsWith("/admin/") ? (
          <p className="mb-4 rounded border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            Whole installation — what you change here applies to every workspace.
          </p>
        ) : null}
        <Outlet />
      </main>
    </div>
  );
}
