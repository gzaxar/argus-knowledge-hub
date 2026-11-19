import { useEffect, useState } from "react";
import { workspacesApi } from "../api/client";
import { MyWorkspace } from "../api/types";
import { forgetRememberedWorkspace, getRememberedWorkspaceId, Profile, updateProfile } from "../api/session";
import { signOut } from "../api/signOut";

export function WorkspacePicker({
  profile,
  onPicked,
}: {
  profile: Profile;
  onPicked: () => void;
}) {
  const [workspaces, setWorkspaces] = useState<MyWorkspace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // An administrator on an instance with no workspace yet makes the first one here: there is nowhere else.
  const [isAdmin, setIsAdmin] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    workspacesApi.me().then((me) => setIsAdmin(me.is_admin)).catch(() => setIsAdmin(false));
  }, [profile.id]);

  const createFirst = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError(null);
    try {
      const ws = await workspacesApi.create(name);
      updateProfile(profile.id, { activeWorkspaceId: ws.id });
      onPicked();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    let live = true;
    workspacesApi
      .listMine()
      .then((ws) => {
        if (!live) return;
        const remembered = getRememberedWorkspaceId(profile);
        const previous = ws.find((w) => w.id === remembered);
        if (remembered && !previous) forgetRememberedWorkspace(profile);
        // A remembered id is never sent as the active workspace before access is checked.
        const target = previous ?? (ws.length === 1 ? ws[0] : undefined);
        if (target) {
          updateProfile(profile.id, { activeWorkspaceId: target.id });
          onPicked();
        } else {
          setWorkspaces(ws);
        }
      })
      .catch((err) => { if (live) setError(err instanceof Error ? err.message : String(err)); });
    return () => { live = false; };
  }, [profile.id, onPicked]);

  const signOutAndRetry = () => void signOut();
  const loading = !error && workspaces === null;
  const returning = !!getRememberedWorkspaceId(profile);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="w-full max-w-md space-y-4 rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            {loading ? returning ? "Returning to your last workspace…" : "Loading your workspaces…" : "Choose a workspace"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">Signed in as {profile.name}.</p>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {loading && (
          <div role="status" aria-live="polite" className="flex items-center gap-3 text-sm text-slate-500">
            <span aria-hidden="true"
                  className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-slate-200 border-t-slate-700 motion-reduce:animate-none" />
            <span>{returning ? "Please wait while we open your workspace." : "Please wait a moment."}</span>
          </div>
        )}
        {workspaces?.length === 0 && !isAdmin && (
          <p className="text-sm text-slate-500">
            You don't have access to any workspace yet — ask an admin to add{" "}
            {profile.name} to one.
          </p>
        )}
        {workspaces?.length === 0 && isAdmin && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void createFirst();
            }}
            className="space-y-2"
          >
            <p className="text-sm text-slate-600">
              You are an administrator and have no workspace yet. Create one to start; you can import
              data into it, or create more, from inside.
            </p>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Workspace name, e.g. SPARC"
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
              autoFocus
            />
            <button
              type="submit"
              disabled={!newName.trim() || creating}
              className="w-full rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300"
            >
              {creating ? "Creating…" : "Create workspace"}
            </button>
            {createError && <p className="text-sm text-red-600">{createError}</p>}
          </form>
        )}
        {workspaces && workspaces.length > 0 && (
          <div className="space-y-2">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                onClick={() => {
                  updateProfile(profile.id, { activeWorkspaceId: ws.id });
                  onPicked();
                }}
                className="block w-full rounded border border-slate-200 px-4 py-2 text-left text-sm hover:border-slate-400 hover:bg-slate-50"
              >
                {ws.name}
              </button>
            ))}
          </div>
        )}

        {(error || workspaces?.length === 0) && (
          <button
            onClick={signOutAndRetry}
            className="text-sm text-slate-500 underline hover:text-slate-700"
          >
            Sign out and try a different account
          </button>
        )}
      </div>
    </div>
  );
}
