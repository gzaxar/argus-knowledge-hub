import { useEffect, useState } from "react";
import { workspacesApi } from "../api/client";
import {
  getActiveProfileId,
  listProfiles,
  removeProfile,
  setActiveProfileId,
  updateProfile,
} from "../api/session";
import { MyWorkspace } from "../api/types";
import { AddWorkspaceForm } from "./AddWorkspaceForm";

export function WorkspaceSwitcher() {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [myWorkspaces, setMyWorkspaces] = useState<MyWorkspace[] | null>(null);

  const profiles = listProfiles();
  const activeId = getActiveProfileId();
  const active = profiles.find((p) => p.id === activeId);

  useEffect(() => {
    if (active?.authType === "oidc") {
      workspacesApi.listMine().then(setMyWorkspaces).catch(() => setMyWorkspaces(null));
    }
  }, [active?.id, active?.authType]);

  const switchProfile = (id: string) => {
    setActiveProfileId(id);
    window.location.reload();
  };

  const switchWorkspace = (workspaceId: string) => {
    if (!active) return;
    updateProfile(active.id, { activeWorkspaceId: workspaceId });
    window.location.reload();
  };

  const activeWorkspaceName =
    active?.authType === "oidc"
      ? myWorkspaces?.find((w) => w.id === active.activeWorkspaceId)?.name
      : undefined;

  const label =
    active?.authType === "oidc" && activeWorkspaceName
      ? `${activeWorkspaceName} (${active.name})`
      : active?.name ?? "Select workspace";

  return (
    <div className="relative border-b border-slate-200 px-2 py-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`Workspace: ${label}. Change workspace`}
        title={label}
        className="flex w-full items-center justify-between gap-1 rounded px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
      >
        <span className="min-w-0 truncate font-medium">{label}</span>
        <span aria-hidden className="shrink-0 text-slate-400">⌄</span>
      </button>

      {open && (
        <div className="absolute left-2 right-2 top-full z-20 mt-1 rounded border border-slate-200 bg-white py-1 shadow-lg">
          {active?.authType === "oidc" && myWorkspaces && myWorkspaces.length > 1 && (
            <>
              <p className="px-3 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Workspaces
              </p>
              {myWorkspaces.map((ws) => (
                <button
                  key={ws.id}
                  onClick={() => switchWorkspace(ws.id)}
                  disabled={ws.id === active.activeWorkspaceId}
                  className={`block w-full truncate px-3 py-1.5 text-left text-sm hover:bg-slate-50 ${
                    ws.id === active.activeWorkspaceId
                      ? "font-medium text-slate-900"
                      : "text-slate-600"
                  }`}
                >
                  {ws.name}
                </button>
              ))}
              <div className="my-1 border-t border-slate-100" />
            </>
          )}

          <p className="px-3 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Signed in as
          </p>
          {profiles.map((p) => (
            <div
              key={p.id}
              className={`flex items-center justify-between px-3 py-1.5 text-sm hover:bg-slate-50 ${
                p.id === activeId ? "font-medium text-slate-900" : "text-slate-600"
              }`}
            >
              <button
                onClick={() => switchProfile(p.id)}
                className="flex-1 truncate text-left"
                disabled={p.id === activeId}
              >
                {p.name}
              </button>
              {profiles.length > 1 && (
                <button
                  onClick={() => {
                    if (confirm(`Remove "${p.name}"?`)) {
                      removeProfile(p.id);
                      window.location.reload();
                    }
                  }}
                  className="ml-2 text-xs text-red-400 hover:text-red-600"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            onClick={() => {
              setOpen(false);
              setAdding(true);
            }}
            className="mt-1 w-full border-t border-slate-100 px-3 py-1.5 text-left text-sm text-indigo-600 hover:bg-slate-50"
          >
            + Add a PAT workspace
          </button>
        </div>
      )}

      {adding && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
          onClick={() => setAdding(false)}
        >
          <div
            className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="mb-4 text-sm font-semibold text-slate-900">Add workspace</h2>
            <AddWorkspaceForm
              existingCount={profiles.length}
              onAdded={() => window.location.reload()}
            />
          </div>
        </div>
      )}
    </div>
  );
}
