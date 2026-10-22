import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { workspacesApi } from "../api/client";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";

export function AdminShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const currentWorkspaceId = useCurrentWorkspaceId();

  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const location = useLocation();

  // Two kinds of page: those about the current workspace only, and those about the whole installation.
  const workspaceItems: { to: string; label: string }[] = [];
  if (currentWorkspaceId) {
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/access`, label: "Access" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/members`, label: "Members" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/packages`, label: "Packages" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/keys`, label: "Keys" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/imports`, label: "Imports" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/glpi`, label: "GLPI" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/icons`, label: "Icon library" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/transfer`, label: "Transfer" });
    workspaceItems.push({ to: "/admin/migration", label: "Migration from Jira" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/ai`, label: "AI endpoint" });
    workspaceItems.push({ to: `/workspaces/${currentWorkspaceId}/robot-tokens`, label: "Robot tokens" });
  }
  const globalItems: { to: string; label: string }[] = [];
  if (me.data?.is_admin) {
    globalItems.push({ to: "/admin/workspaces", label: "Workspaces" });
    globalItems.push({ to: "/admin/users", label: "Users" });
    globalItems.push({ to: "/admin/settings", label: "Settings" });
    globalItems.push({ to: "/admin/ai", label: "AI" });
    globalItems.push({ to: "/admin/tokens", label: "API tokens" });
    globalItems.push({ to: "/admin/portability", label: "Portability" });
    globalItems.push({ to: "/admin/statistics", label: "Statistics" });
  }

  const pageWorkspace = location.pathname.match(/^\/workspaces\/([^/]+)/)?.[1]
    ?? (location.pathname.startsWith("/admin/migration") ? currentWorkspaceId : null);
  const workspaceName = (id: string | null) => mine.data?.find((w) => w.id === id)?.name ?? id;

  const link = (item: { to: string; label: string }) => (
    <NavLink
      key={item.to}
      to={item.to}
      className={({ isActive }) =>
        `block rounded px-3 py-2 text-sm font-medium ${
          isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
        }`
      }
    >
      {item.label}
    </NavLink>
  );

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-4">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-700">
            &larr; Back to ARGUS Asset Knowledge Hub
          </Link>
          <p className="mt-1 text-sm font-semibold text-slate-900">Administration</p>
        </div>
        <nav className="space-y-4 p-2">
          {workspaceItems.length > 0 && (
            <div className="space-y-1">
              <p className="px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide text-sky-700">This workspace</p>
              <p className="truncate px-3 pb-1 text-xs text-slate-500" title={currentWorkspaceId ?? ""}>
                {workspaceName(currentWorkspaceId)} <code className="text-[11px]">{currentWorkspaceId}</code>
              </p>
              {workspaceItems.map(link)}
            </div>
          )}
          {globalItems.length > 0 && (
            <div className="space-y-1">
              <p className="px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide text-amber-700">Whole installation</p>
              <p className="px-3 pb-1 text-xs text-slate-500">Every workspace, administrators only</p>
              {globalItems.map(link)}
            </div>
          )}
          {workspaceItems.length === 0 && globalItems.length === 0 && (
            <p className="px-3 py-2 text-sm text-slate-400">Nothing to manage here yet.</p>
          )}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        {pageWorkspace ? (
          <p className="mb-4 rounded border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs text-sky-900">
            Workspace <span className="font-semibold">{workspaceName(pageWorkspace)}</span>{" "}
            <code className="rounded bg-sky-100 px-1">{pageWorkspace}</code> — what you change here applies to this workspace only.
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
