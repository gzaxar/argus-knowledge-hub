import { ask } from "../lib/dialogs";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  apiBaseUrl,
  type ApiTokenCreated,
  type ApiTokenInfo,
  type ApiTokenInput,
  type TokenResource,
  type TokenScope,
} from "../api/client";
import { errorText } from "./hub/LedgerPanels";

const SCOPES: { id: TokenScope; label: string; hint: string }[] = [
  { id: "read", label: "Read", hint: "GET: list and read records" },
  { id: "create", label: "Create", hint: "add records and files" },
  { id: "modify", label: "Modify", hint: "change records, add revisions and attachments" },
  { id: "delete", label: "Delete", hint: "remove records" },
  { id: "approve", label: "Approve", hint: "approve and publish documents, see confidential ones" },
  { id: "admin", label: "Administer", hint: "manage members and roles (robot); administrator rights (personal)" },
];
const RESOURCES: { id: TokenResource; label: string }[] = [
  { id: "objects", label: "Equipment" },
  { id: "tickets", label: "Tickets" },
  { id: "documents", label: "Documents" },
];

export interface Preset {
  label: string;
  scopes: TokenScope[];
  resources: TokenResource[];
}

export const ROBOT_PRESETS: Preset[] = [
  { label: "Daily logbook upload", scopes: ["read", "create", "modify"], resources: ["documents"] },
  { label: "Read only", scopes: ["read"], resources: [] },
  { label: "Data feed (read and write)", scopes: ["read", "create", "modify"], resources: [] },
];
export const PERSONAL_PRESETS: Preset[] = [
  { label: "Read only", scopes: ["read"], resources: [] },
  { label: "Read and write", scopes: ["read", "create", "modify"], resources: [] },
];

const DAYS = [30, 90, 180, 365];

export function TokenForm({
  kind,
  presets,
  workspaces,
  allowAdmin,
  onCreate,
}: {
  kind: "personal" | "robot";
  presets: Preset[];
  /** Personal tokens may be fixed to one workspace. */
  workspaces?: { id: string; name: string }[];
  allowAdmin: boolean;
  onCreate: (input: ApiTokenInput) => Promise<ApiTokenCreated>;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<TokenScope[]>(presets[0].scopes);
  const [resources, setResources] = useState<TokenResource[]>(presets[0].resources);
  const [workspace, setWorkspace] = useState("");
  const [days, setDays] = useState<string>(kind === "personal" ? "90" : "365");
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);
  const make = useMutation({
    mutationFn: () =>
      onCreate({
        name: name.trim(), scopes, resources, workspace_id: workspace || null,
        expires_in_days: days === "never" ? null : Number(days),
      }),
    onSuccess: (t) => {
      setCreated(t);
      setName("");
    },
  });
  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <div className="space-y-3 rounded border border-slate-200 bg-white p-4">
      {created && <Reveal token={created} onDone={() => setCreated(null)} />}
      <div className="flex flex-wrap gap-2">
        {presets.map((p) => (
          <button key={p.label} type="button"
                  onClick={() => { setScopes(p.scopes); setResources(p.resources); if (!name) setName(p.label); }}
                  className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">
            {p.label}
          </button>
        ))}
      </div>
      <div>
        <label className="block text-sm font-medium text-slate-700">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder={kind === "robot" ? "Logbook uploader — SPARC control room" : "My analysis scripts"}
               className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm" />
      </div>
      <fieldset>
        <legend className="text-sm font-medium text-slate-700">May</legend>
        <div className="mt-1 grid gap-1 sm:grid-cols-2">
          {SCOPES.filter((s) => s.id !== "admin" || allowAdmin).map((s) => (
            <label key={s.id} className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={scopes.includes(s.id)}
                     onChange={() => setScopes(toggle(scopes, s.id))} />
              <span>{s.label} <span className="text-xs text-slate-500">— {s.hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="text-sm font-medium text-slate-700">On</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {RESOURCES.map((r) => (
            <label key={r.id} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={resources.includes(r.id)}
                     onChange={() => setResources(toggle(resources, r.id))} />
              {r.label}
            </label>
          ))}
          <span className="text-xs text-slate-500">{resources.length === 0 ? "none ticked: all of them" : ""}</span>
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-4">
        {workspaces && (
          <div>
            <label className="block text-sm font-medium text-slate-700">Workspace</label>
            <select aria-label="Workspace" value={workspace} onChange={(e) => setWorkspace(e.target.value)}
                    className="mt-1 rounded border border-slate-300 px-2 py-2 text-sm">
              <option value="">All my workspaces</option>
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}
        <div>
          <label className="block text-sm font-medium text-slate-700">Expires after</label>
          <select aria-label="Expires after" value={days} onChange={(e) => setDays(e.target.value)}
                  className="mt-1 rounded border border-slate-300 px-2 py-2 text-sm">
            {DAYS.map((d) => <option key={d} value={String(d)}>{d} days</option>)}
            {kind === "robot" && <option value="730">2 years</option>}
            {kind === "robot" && <option value="never">Never (not recommended)</option>}
          </select>
        </div>
      </div>
      {kind === "personal" && (
        <p className="text-xs text-slate-500">
          The token acts as you: it can never do more than your own roles allow, whatever is ticked here.
          {allowAdmin && !scopes.includes("admin") && (
            <> As an administrator: without <i>Administer</i>, it reaches only the workspaces where you hold a
              role, not those you reach as administrator.</>
          )}
        </p>
      )}
      {make.isError && <p className="text-sm text-red-600">{errorText(make.error)}</p>}
      <button type="button" disabled={!name.trim() || scopes.length === 0 || make.isPending}
              onClick={() => make.mutate()}
              className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
        {make.isPending ? "Generating…" : kind === "robot" ? "Generate robot token" : "Generate token"}
      </button>
    </div>
  );
}

function Reveal({ token, onDone }: { token: ApiTokenCreated; onDone: () => void }) {
  const base = useQuery({ queryKey: ["api-base-url"], queryFn: apiBaseUrl });
  const [copied, setCopied] = useState(false);
  const header = token.kind === "personal" && !token.workspace_id ? ' \\\n  -H "X-Workspace-Id: <workspace>"' : "";
  return (
    <div className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
      <p className="font-medium">Copy this token now: it is shown only once.</p>
      <div className="flex items-center gap-2">
        <code className="flex-1 break-all rounded bg-white px-2 py-1 font-mono text-xs">{token.token}</code>
        <button type="button" className="rounded border border-amber-400 bg-white px-2 py-1 text-xs"
                onClick={() => { void navigator.clipboard.writeText(token.token); setCopied(true); }}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="text-xs">Try it:</p>
      <pre className="overflow-x-auto rounded bg-white p-2 text-xs">
{`curl -H "Authorization: Bearer $ARGUS_TOKEN"${header} \\
  ${base.data || "https://<argus-api>"}/v1/me/profile`}
      </pre>
      <button type="button" onClick={onDone} className="text-xs underline">I have stored it</button>
    </div>
  );
}

export function TokenTable({
  tokens,
  onRevoke,
  showOwner,
}: {
  tokens: ApiTokenInfo[];
  onRevoke: (t: ApiTokenInfo) => void;
  showOwner?: boolean;
}) {
  if (tokens.length === 0) return <p className="text-sm text-slate-500">No tokens yet.</p>;
  const date = (s: string | null) => (s ? new Date(s).toLocaleDateString() : "—");
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-500">
          <tr>
            <th className="px-3 py-2">Name</th>
            {showOwner && <th className="px-3 py-2">Kind · owner</th>}
            <th className="px-3 py-2">Workspace</th>
            <th className="px-3 py-2">May</th>
            <th className="px-3 py-2">Expires</th>
            <th className="px-3 py-2">Last used</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {tokens.map((t) => (
            <tr key={t.id} className={`border-t border-slate-100 ${t.status !== "active" ? "text-slate-400" : ""}`}>
              <td className="px-3 py-2">
                <div className="font-medium">{t.name ?? "(unnamed)"}</div>
                <div className="font-mono text-xs text-slate-400">{t.prefix ? `${t.prefix}…` : `#${t.id}`}</div>
              </td>
              {showOwner && (
                <td className="px-3 py-2 text-xs">{t.kind}{t.owner_email ? ` · ${t.owner_email}` : t.created_by ? ` · by ${t.created_by}` : ""}</td>
              )}
              <td className="px-3 py-2 text-xs">{t.workspace_id ?? "all"}</td>
              <td className="px-3 py-2 text-xs">
                {t.scopes.join(", ")}
                {t.resources.length > 0 && <span className="text-slate-400"> on {t.resources.join(", ")}</span>}
              </td>
              <td className="px-3 py-2 text-xs">{t.status === "active" ? (t.expires_at ? date(t.expires_at) : "never") : t.status}</td>
              <td className="px-3 py-2 text-xs">{date(t.last_used_at)}</td>
              <td className="px-3 py-2 text-right">
                {t.status === "active" && (
                  <button type="button" onClick={async () => { if (await ask(`Revoke “${t.name}”? Anything using it stops working.`)) onRevoke(t); }}
                          className="text-xs text-red-600 hover:text-red-800">
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
