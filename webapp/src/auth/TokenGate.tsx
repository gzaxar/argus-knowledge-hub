import { ReactNode, useState } from "react";
import { AddWorkspaceForm } from "../components/AddWorkspaceForm";
import { signInWithGoogle } from "../api/firebase";
import { CALLBACK_PATH, infnLoginEnabled, infnLoginLabel, startInfnLogin } from "../api/infnAuth";
import { addOidcProfile, defaultApiBaseUrl, getActiveProfile, Profile } from "../api/session";
import { InfnCallback } from "./InfnCallback";
import { WorkspacePicker } from "./WorkspacePicker";

function InfnSignInButton() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onClick = async () => {
    setError(null);
    setLoading(true);
    try {
      await startInfnLogin(); // navigates away to the identity provider
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  return (
    <div>
      <button
        onClick={onClick}
        disabled={loading}
        className="w-full rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
      >
        {loading ? "Redirecting…" : infnLoginLabel}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

function GoogleSignInButton({ onSignedIn }: { onSignedIn: (profile: Profile) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const baseUrl = defaultApiBaseUrl();

  const onClick = async () => {
    setError(null);
    setLoading(true);
    try {
      const user = await signInWithGoogle();
      const profile = addOidcProfile(user.email ?? user.uid, baseUrl);
      onSignedIn(profile);
    } catch (err) {
      const code = err && typeof err === "object" && "code" in err ? String(err.code) : null;
      const message = err instanceof Error ? err.message : String(err);
      setError(code ? `${code}: ${message}` : message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button
        onClick={onClick}
        disabled={loading}
        className="w-full rounded border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      >
        {loading ? "Signing in…" : "Sign in with Google"}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

export function TokenGate({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState(() => getActiveProfile());

  // Back from the identity provider with a one-time code to exchange.
  if (infnLoginEnabled && window.location.pathname === CALLBACK_PATH) {
    return <InfnCallback />;
  }

  if (!profile) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="w-full max-w-md space-y-4 rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">ARGUS Knowledge Hub</h1>
            <p className="mt-1 text-sm text-slate-500">Sign in to continue.</p>
          </div>
          {infnLoginEnabled && <InfnSignInButton />}
          <GoogleSignInButton onSignedIn={setProfile} />
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <div className="h-px flex-1 bg-slate-200" />
            or use an API token
            <div className="h-px flex-1 bg-slate-200" />
          </div>
          <AddWorkspaceForm existingCount={0} onAdded={setProfile} />
        </div>
      </div>
    );
  }

  if (profile.authType === "oidc" && !profile.activeWorkspaceId) {
    return (
      <WorkspacePicker
        profile={profile}
        onPicked={() => setProfile(getActiveProfile())}
      />
    );
  }

  return <>{children}</>;
}
