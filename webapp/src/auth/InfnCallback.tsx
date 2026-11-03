import { useEffect, useState } from "react";
import { completeInfnLogin, infnLoginLabel, ownPage } from "../api/infnAuth";
import { addOidcProfile, defaultApiBaseUrl } from "../api/session";

/** The page the identity provider sends the browser back to. Exchanges the
 * one-time code for tokens, saves the signed-in person as a profile, and
 * reloads at the root — a full load, not a client-side navigation, so the
 * router starts from "/" instead of the callback address it was opened on. */
export function InfnCallback() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    completeInfnLogin()
      .then((user) => {
        const state = user.state as { stepUp?: boolean; returnTo?: string } | undefined;
        if (state?.stepUp && state.returnTo?.startsWith("/")) {
          // A step-up: the same person, signed in again just now; back to where they were.
          window.location.replace(state.returnTo);
          return;
        }
        const who = user.profile.email ?? user.profile.preferred_username ?? user.profile.sub;
        addOidcProfile(who, defaultApiBaseUrl(), "infn");
        // Back to the page sign-in started from (a link someone sent), when it is a page of this app.
        window.location.replace(ownPage(state?.returnTo) ?? "/");
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="w-full max-w-md space-y-3 rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        {error ? (
          <>
            <h1 className="text-xl font-semibold text-slate-900">{infnLoginLabel} did not complete</h1>
            <p className="text-sm text-red-600">{error}</p>
            <a href="/" className="text-sm text-slate-600 underline">
              Back to sign-in
            </a>
          </>
        ) : (
          <p className="text-sm text-slate-500">Signing you in…</p>
        )}
      </div>
    </div>
  );
}
