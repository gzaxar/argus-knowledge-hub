import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { portalApi, portalError } from "../../api/client";
import { PortalFrame, PortalMessage, StatusLozenge, when } from "./PortalFrame";

/** /support/:siteId/requests — the person's own requests at this site, newest activity first. */
export function MyRequests() {
  const { siteId = "" } = useParams();
  const cat = useQuery({ queryKey: ["portal", "catalogue", siteId], queryFn: () => portalApi.catalogue(siteId), retry: false });
  const mine = useQuery({ queryKey: ["portal", "mine", siteId], queryFn: () => portalApi.mine(siteId) });
  const [filter, setFilter] = useState<"open" | "done" | "all">("open");
  const [q, setQ] = useState("");
  const rows = (mine.data ?? []).filter((r) =>
    (filter === "all" || (filter === "done" ? r.status.category === "done" : r.status.category !== "done")) &&
    (!q.trim() || `${r.key ?? ""} ${r.title} ${r.service_name}`.toLowerCase().includes(q.trim().toLowerCase())));

  return (
    <PortalFrame siteId={siteId} siteName={cat.data?.site.name} emergency={cat.data?.emergency}
                 crumbs={[{ to: `/support/${siteId}`, label: "Help centre" }, { label: "My requests" }]}>
      <div className="flex flex-wrap items-end gap-3">
        <h1 className="mr-auto text-2xl font-semibold text-slate-900">My requests</h1>
        <label className="text-sm">
          <span className="sr-only">Search my requests</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search"
                 className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
        </label>
        <label className="text-sm">
          <span className="sr-only">Show</span>
          <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
            <option value="open">Open requests</option>
            <option value="done">Resolved</option>
            <option value="all">All</option>
          </select>
        </label>
      </div>
      {mine.error && <div className="mt-4"><PortalMessage tone="error">{portalError(mine.error)}</PortalMessage></div>}
      {mine.isLoading && <p className="mt-4 text-sm text-slate-500">Loading…</p>}
      {mine.data && rows.length === 0 && (
        <div className="mt-4"><PortalMessage>
          {mine.data.length === 0 ? <>You have not sent a request here yet. <Link className="font-medium text-indigo-700 underline"
            to={`/support/${siteId}`}>Find the right service</Link></> : "No request matches."}
        </PortalMessage></div>
      )}
      {rows.length > 0 && (
        <div className="mt-4 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <caption className="sr-only">My requests</caption>
            <thead className="hidden bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 sm:table-header-group">
              <tr><th className="px-4 py-2">Reference</th><th className="px-4 py-2">Summary</th>
                <th className="px-4 py-2">Service</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Updated</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.uid} className="block hover:bg-slate-50 sm:table-row">
                  <td className="block px-4 pt-3 text-xs text-slate-500 sm:table-cell sm:py-3">{r.key}</td>
                  <td className="block px-4 sm:table-cell sm:py-3">
                    <Link to={`/support/${siteId}/requests/${r.uid}`} className="font-medium text-indigo-700 hover:underline">
                      {r.title}
                    </Link>
                    {r.unread && <span className="ml-2 rounded bg-indigo-600 px-1.5 text-[10px] font-semibold uppercase text-white">New reply</span>}
                  </td>
                  <td className="block px-4 text-slate-600 sm:table-cell sm:py-3">{r.service_name}</td>
                  <td className="block px-4 sm:table-cell sm:py-3"><StatusLozenge status={r.status} /></td>
                  <td className="block px-4 pb-3 text-xs text-slate-500 sm:table-cell sm:py-3">{when(r.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PortalFrame>
  );
}

/** /support/:siteId/requests/:uid — what was sent, the public conversation and files, the status and resolution. */
export function RequestDetail() {
  const { siteId = "", uid = "" } = useParams();
  const sent = (useLocation().state as { sent?: boolean } | null)?.sent;
  const qc = useQueryClient();
  const cat = useQuery({ queryKey: ["portal", "catalogue", siteId], queryFn: () => portalApi.catalogue(siteId), retry: false });
  const req = useQuery({ queryKey: ["portal", "request", siteId, uid], queryFn: () => portalApi.get(siteId, uid) });
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const done = (d: unknown) => {
    qc.setQueryData(["portal", "request", siteId, uid], d);
    qc.invalidateQueries({ queryKey: ["portal", "mine", siteId] });
    setBody("");
    setError(null);
  };
  const reply = useMutation({ mutationFn: () => portalApi.reply(siteId, uid, body), onSuccess: done,
    onError: (e) => setError(portalError(e)) });
  const reopen = useMutation({ mutationFn: () => portalApi.reopen(siteId, uid, body), onSuccess: done,
    onError: (e) => setError(portalError(e)) });
  const upload = useMutation({ mutationFn: (f: File) => portalApi.addFile(siteId, uid, f), onSuccess: (d) => {
    qc.setQueryData(["portal", "request", siteId, uid], d); }, onError: (e) => setError(portalError(e)) });

  const r = req.data;
  return (
    <PortalFrame siteId={siteId} siteName={cat.data?.site.name} emergency={cat.data?.emergency}
                 crumbs={[{ to: `/support/${siteId}`, label: "Help centre" },
                   { to: `/support/${siteId}/requests`, label: "My requests" }, { label: r?.key ?? "Request" }]}>
      {req.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {req.error && <PortalMessage tone="error">{portalError(req.error)}</PortalMessage>}
      {r && (
        <>
          {sent && <div className="mb-4"><PortalMessage tone="ok">Your request was sent to {r.service_name}
            {r.key ? <> as <b>{r.key}</b></> : null}. You will be told here, and by e-mail, when the team replies.</PortalMessage></div>}
          <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
            <section className="space-y-4">
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <p className="text-xs text-slate-500">{r.key}</p>
                <h1 className="text-xl font-semibold text-slate-900">{r.title}</h1>
                {r.notice && <div className="mt-3"><PortalMessage>{r.notice}</PortalMessage></div>}
                {r.description && <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{r.description}</p>}
                {r.submitted.length > 0 && (
                  <dl className="mt-4 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[10rem_1fr]">
                    {r.submitted.map((s) => (
                      <div key={s.key} className="contents"><dt className="text-slate-500">{s.label}</dt><dd>{String(s.value)}</dd></div>
                    ))}
                  </dl>
                )}
              </div>
              {r.status.category === "done" && (
                <PortalMessage tone="ok">
                  <b>Resolved{r.resolution ? `: ${r.resolution}` : ""}</b>{r.resolved_at ? ` · ${when(r.resolved_at)}` : ""}.
                  {r.can_reopen ? " Not solved? Reopen it below." : " Not solved? Add a reply and the team will see it."}
                </PortalMessage>
              )}
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <h2 className="text-sm font-semibold text-slate-700">Activity</h2>
                <ol className="mt-3 space-y-4">
                  {r.conversation.map((c) => (
                    <li key={c.uid} className="flex gap-3">
                      <span aria-hidden className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                        c.mine ? "bg-slate-200 text-slate-700" : "bg-indigo-600 text-white"}`}>
                        {c.author_name.slice(0, 1).toUpperCase()}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-xs text-slate-500"><b className="text-slate-700">{c.author_name}</b> · {when(c.created_at)}</p>
                        <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-800">{c.body}</p>
                      </div>
                    </li>
                  ))}
                  {r.conversation.length === 0 && <li className="text-sm text-slate-400">No replies yet.</li>}
                </ol>
                {r.can_reply && (
                  <form className="mt-4 border-t border-slate-100 pt-4" onSubmit={(e) => { e.preventDefault(); if (body.trim()) reply.mutate(); }}>
                    <label htmlFor="reply" className="text-sm font-medium text-slate-700">Add a reply</label>
                    <textarea id="reply" rows={3} value={body} onChange={(e) => setBody(e.target.value)}
                              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
                    {error && <div className="mt-2"><PortalMessage tone="error">{error}</PortalMessage></div>}
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button type="submit" disabled={!body.trim() || reply.isPending}
                              className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                        {reply.isPending ? "Sending…" : "Send reply"}
                      </button>
                      {r.can_reopen && (
                        <button type="button" onClick={() => reopen.mutate()} disabled={reopen.isPending}
                                className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm hover:bg-slate-50">
                          Reopen request
                        </button>
                      )}
                    </div>
                  </form>
                )}
              </div>
            </section>
            <aside className="space-y-3 text-sm">
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <StatusLozenge status={r.status} />
                <dl className="mt-3 space-y-2">
                  <div><dt className="text-xs text-slate-500">Service</dt><dd>{r.service_name}</dd></div>
                  <div><dt className="text-xs text-slate-500">Request type</dt><dd>{r.request_type_name}</dd></div>
                  {r.origin_name && <div><dt className="text-xs text-slate-500">Reported from</dt><dd>{r.origin_name}</dd></div>}
                  <div><dt className="text-xs text-slate-500">Sent</dt><dd>{when(r.created_at)}</dd></div>
                </dl>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Files</p>
                <ul className="mt-2 space-y-1">
                  {r.attachments.map((a) => (
                    <li key={a.uid}>
                      <button className="text-left text-indigo-700 hover:underline"
                              onClick={() => portalApi.downloadFile(siteId, uid, a.uid, a.filename)}>{a.filename}</button>
                      <span className="block text-xs text-slate-400">{a.mine ? "You" : "Support team"} · {when(a.created_at)}</span>
                    </li>
                  ))}
                  {r.attachments.length === 0 && <li className="text-slate-400">None.</li>}
                </ul>
                {r.can_reply && (
                  <label className="mt-3 inline-block cursor-pointer text-xs text-indigo-700 hover:underline">
                    {upload.isPending ? "Uploading…" : "+ Add a file"}
                    <input type="file" className="sr-only"
                           onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
                  </label>
                )}
              </div>
            </aside>
          </div>
        </>
      )}
    </PortalFrame>
  );
}
