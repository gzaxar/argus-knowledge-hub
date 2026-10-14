import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet } from "react-router-dom";
import { workspacesApi } from "../api/client";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";

export function AdminShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const currentWorkspaceId = useCurrentWorkspaceId();

  const items = [];
  if (currentWorkspaceId) {
    items.push({ to: `/workspaces/${currentWorkspaceId}/access`, label: "Access" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/members`, label: "Members" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/imports`, label: "Imports" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/glpi`, label: "GLPI" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/icons`, label: "Icon library" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/transfer`, label: "Transfer" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/ai`, label: "AI endpoint" });
    items.push({ to: `/workspaces/${currentWorkspaceId}/robot-tokens`, label: "Robot tokens" });
  }
  if (me.data?.is_admin) {
    items.push({ to: "/admin/workspaces", label: "Workspaces" });
    items.push({ to: "/admin/users", label: "Users" });
    items.push({ to: "/admin/settings", label: "Settings" });
    items.push({ to: "/admin/ai", label: "AI" });
    items.push({ to: "/admin/tokens", label: "API tokens" });
    items.push({ to: "/admin/portability", label: "Portability" });
  }

  return (
    <div className="flex min-h-screen bg-slate-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-4">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-700">
            &larr; Back to ARGUS Asset Knowledge Hub
          </Link>
          <p className="mt-1 text-sm font-semibold text-slate-900">Administration</p>
        </div>
        <nav className="space-y-1 p-2">
          {items.map((item) => (
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
          ))}
          {items.length === 0 && (
            <p className="px-3 py-2 text-sm text-slate-400">Nothing to manage here yet.</p>
          )}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
