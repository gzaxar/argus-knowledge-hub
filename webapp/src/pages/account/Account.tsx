import { useQuery, useQueryClient } from "@tanstack/react-query";
import { tokensApi, workspacesApi } from "../../api/client";
import { PERSONAL_PRESETS, TokenForm, TokenTable } from "../../components/ApiTokens";
import { NotificationSettings } from "./Notifications";

/** Who you are to ARGUS: the account, this sign-in, groups, what each workspace lets you do, your notifications
 * and your personal access tokens. */
export function AccountPage() {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ["my-profile"], queryFn: tokensApi.profile });
  const tokens = useQuery({ queryKey: ["my-tokens"], queryFn: tokensApi.mine });
  const workspaces = useQuery({ queryKey: ["my-workspaces-account"], queryFn: workspacesApi.listMine });
  const p = profile.data;
  const u = p?.user;
  const when = (s: string | null | undefined) => (s ? new Date(s).toLocaleString() : "—");
  const epoch = (n: number | null | undefined) => (n ? new Date(n * 1000).toLocaleString() : "—");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["my-tokens"] });
    queryClient.invalidateQueries({ queryKey: ["my-profile"] });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">My account</h1>
        <p className="mt-1 text-sm text-slate-500">Who you are to ARGUS, what you may do where, and the tokens that
          let scripts call the API as you.</p>
      </div>

      {u && (
        <section className="grid gap-4 md:grid-cols-2">
          <div className="rounded border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Account</h2>
            <dl className="mt-2 grid grid-cols-[9rem_1fr] gap-y-1 text-sm">
              <dt className="text-slate-500">Name</dt><dd>{u.name ?? "—"}</dd>
              <dt className="text-slate-500">Email</dt><dd>{u.email}</dd>
              {u.username && (<><dt className="text-slate-500">Username</dt><dd>{u.username}</dd></>)}
              <dt className="text-slate-500">ARGUS id</dt><dd className="font-mono text-xs">{u.id}</dd>
              <dt className="text-slate-500">Administrator</dt><dd>{u.is_admin ? "Yes" : "No"}</dd>
              <dt className="text-slate-500">Account from</dt><dd>{u.source}{u.directory_dn ? ` · ${u.directory_dn}` : ""}</dd>
              <dt className="text-slate-500">Created</dt><dd>{when(u.created_at)}</dd>
              <dt className="text-slate-500">Last sign-in</dt><dd>{when(u.last_login_at)}</dd>
              {u.synced_at && (<><dt className="text-slate-500">Directory sync</dt><dd>{when(u.synced_at)}</dd></>)}
            </dl>
          </div>
          <div className="rounded border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">This sign-in</h2>
            <dl className="mt-2 grid grid-cols-[9rem_1fr] gap-y-1 text-sm">
              <dt className="text-slate-500">Identity provider</dt>
              <dd className="break-all">{p.session.issuer ?? "—"}{p.session.identity_provider ? ` (via ${p.session.identity_provider})` : ""}</dd>
              <dt className="text-slate-500">Subject</dt><dd className="break-all font-mono text-xs">{p.session.subject ?? u.oidc_subject ?? "—"}</dd>
              <dt className="text-slate-500">Client</dt><dd>{p.session.client ?? "—"}</dd>
              <dt className="text-slate-500">Signed in at</dt><dd>{epoch(p.session.auth_time)}</dd>
              <dt className="text-slate-500">Session expires</dt><dd>{epoch(p.session.expires)}</dd>
              <dt className="text-slate-500">Realm roles</dt>
              <dd className="text-xs">{(p.session.realm_roles ?? []).join(", ") || "—"}</dd>
              <dt className="text-slate-500">Field devices</dt><dd>{p.counts.devices ?? 0} registered</dd>
            </dl>
          </div>
        </section>
      )}

      {p && p.groups.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Groups</h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {p.groups.map((g) => (
              <li key={g.uid} className="rounded border border-slate-200 bg-white px-2 py-1 text-xs">
                {g.name} <span className="text-slate-400">· {g.source}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Workspaces and what you may do</h2>
          <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-3 py-2">Workspace</th><th className="px-3 py-2">Roles</th>
                  <th className="px-3 py-2">Equipment</th><th className="px-3 py-2">Tickets</th>
                  <th className="px-3 py-2">Documents</th><th className="px-3 py-2">Workspace</th></tr>
              </thead>
              <tbody>
                {p.workspaces.map((w) => (
                  <tr key={w.id} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2"><div className="font-medium">{w.name}</div>
                      <div className="text-xs text-slate-400">{w.id}{w.is_global ? " · global" : ""}</div></td>
                    <td className="px-3 py-2 text-xs">
                      {w.roles.length ? w.roles.map((r) => (
                        <div key={r.id + r.via}>{r.name}{r.via !== "direct" && <span className="text-slate-400"> · {r.via.replace("group:", "via ")}</span>}</div>
                      )) : u?.is_admin ? "administrator" : "workspace default access"}
                    </td>
                    {["objects", "tickets", "documents", "workspace"].map((k) => (
                      <td key={k} className="px-3 py-2 text-xs">{(w.permissions[k] ?? []).join(", ").replace("manage_members", "manage members") || "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {p?.auth_type === "oidc" && <NotificationSettings />}

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Personal access tokens</h2>
          <p className="mt-1 text-sm text-slate-500">
            For your own scripts and tools calling the API as you: send it as <code>Authorization: Bearer …</code>,
            with <code>X-Workspace-Id</code> unless the token is fixed to one workspace. It never does more than
            your roles allow. For a machine that works for a facility (a logbook uploader), ask the workspace's
            owner for a <i>robot token</i> instead: it keeps working when you leave.
          </p>
        </div>
        {p?.auth_type === "oidc" ? (
          <TokenForm kind="personal" presets={PERSONAL_PRESETS} allowAdmin={!!u?.is_admin}
                     workspaces={(workspaces.data ?? []).map((w) => ({ id: w.id, name: w.name }))}
                     onCreate={async (input) => { const t = await tokensApi.makeMine(input); refresh(); return t; }} />
        ) : p ? <p className="text-sm text-slate-500">Tokens are managed when signed in, not with a token.</p> : null}
        <TokenTable tokens={tokens.data ?? []}
                    onRevoke={(t) => void tokensApi.revokeMine(t.id).then(refresh)} />
      </section>
    </div>
  );
}
