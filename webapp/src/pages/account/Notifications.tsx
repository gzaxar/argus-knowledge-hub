import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { problemText, workflowApi } from "../../api/client";
import type { EmailPreferences, WorkspaceSubscription } from "../../api/ledgerTypes";

const MODES: [EmailPreferences["email"], string][] = [
  ["instant", "Each one as it happens"],
  ["digest", "Once a day, in a digest"],
  ["off", "Never: only in the app"],
];

/** What reaches this person by e-mail, and what they hear about in each workspace. */
export function NotificationSettings() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["email-preferences"], queryFn: workflowApi.emailPreferences, retry: false });
  const subs = useQuery({ queryKey: ["notification-subscriptions"], queryFn: workflowApi.subscriptions, retry: false });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const save = useMutation({
    mutationFn: workflowApi.setEmailPreferences,
    onSuccess: (data) => qc.setQueryData(["email-preferences"], data),
    onError: (e) => setMessage({ ok: false, text: problemText(e) }),
  });
  const test = useMutation({
    mutationFn: workflowApi.testEmail,
    onSuccess: (r) => setMessage({ ok: true, text: `Test message sent to ${r.sent_to}.` }),
    onError: (e) => setMessage({ ok: false, text: problemText(e) }),
  });
  const subscribe = useMutation({
    mutationFn: workflowApi.subscribe,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notification-subscriptions"] }),
    onError: (e) => setMessage({ ok: false, text: problemText(e) }),
  });

  const p = prefs.data;
  if (!p) return null;
  const toggleMuted = (key: string, on: boolean) =>
    save.mutate({ email: p.email, muted: on ? p.muted.filter((m) => m !== key) : [...p.muted, key] });
  const flip = (s: WorkspaceSubscription, field: "tickets" | "documents" | "assets") =>
    subscribe.mutate({ ...s, [field]: !s[field] });

  return (
    <section id="notifications" className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-slate-900">Notifications</h2>
        <p className="mt-1 text-sm text-slate-500">
          Everything you are told about is under the bell and on the phone. Choose what also reaches you by e-mail
          {p.address ? <> at <b>{p.address}</b></> : null}.
        </p>
      </div>

      {!p.email_configured && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          This installation does not send e-mail yet: your choices apply once an administrator sets up the mail
          server.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-medium text-slate-800">By e-mail</h3>
          <div className="mt-2 space-y-1 text-sm">
            {MODES.map(([mode, label]) => (
              <label key={mode} className="flex items-center gap-2">
                <input type="radio" name="email-mode" checked={p.email === mode} disabled={save.isPending}
                       onChange={() => save.mutate({ email: mode, muted: p.muted })} />
                {label}
                {mode === "digest" && <span className="text-xs text-slate-400">at {p.digest_hour}:00</span>}
              </label>
            ))}
          </div>
          {p.email_configured && p.email !== "off" && (
            <button onClick={() => test.mutate()} disabled={test.isPending}
                    className="mt-3 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50">
              {test.isPending ? "Sending…" : "Send me a test message"}
            </button>
          )}
        </div>
        <div className="rounded border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-medium text-slate-800">What to e-mail</h3>
          <div className="mt-2 space-y-1 text-sm">
            {p.categories.map((c) => (
              <label key={c.key} className={`flex items-start gap-2 ${p.email === "off" ? "text-slate-400" : ""}`}>
                <input type="checkbox" className="mt-0.5" checked={!p.muted.includes(c.key)}
                       disabled={save.isPending || p.email === "off"}
                       onChange={(e) => toggleMuted(c.key, e.target.checked)} />
                {c.label}
              </label>
            ))}
          </div>
        </div>
      </div>

      {message && <p className={`text-sm ${message.ok ? "text-emerald-700" : "text-rose-700"}`}>{message.text}</p>}

      {subs.data && subs.data.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-800">Everything new in a workspace</h3>
          <p className="mt-1 text-xs text-slate-500">
            Besides the tickets you watch and the equipment and documents you follow (their <i>Follow</i> button):
            every new ticket, every new or newly published document, every new piece of equipment.
          </p>
          <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-3 py-2">Workspace</th><th className="px-3 py-2">New tickets</th>
                  <th className="px-3 py-2">New documents</th><th className="px-3 py-2">New equipment</th></tr>
              </thead>
              <tbody>
                {subs.data.map((s) => (
                  <tr key={s.workspace_id} className="border-t border-slate-100">
                    <td className="px-3 py-2">{s.workspace_name}</td>
                    {(["tickets", "documents", "assets"] as const).map((f) => (
                      <td key={f} className="px-3 py-2">
                        <input type="checkbox" checked={s[f]} disabled={subscribe.isPending}
                               aria-label={`${f} in ${s.workspace_name}`} onChange={() => flip(s, f)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
