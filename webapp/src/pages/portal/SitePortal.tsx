import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { portalApi, portalError } from "../../api/client";
import type { PortalCatalogue, PortalRequestTypeCard, PortalService } from "../../api/portalTypes";
import { PortalFrame, PortalMessage } from "./PortalFrame";

/** /support: the sites whose portal this person may use. One site: straight to it. */
export function PortalHome() {
  const sites = useQuery({ queryKey: ["portal", "sites"], queryFn: portalApi.sites });
  if (sites.isLoading) return <PortalFrame><p className="text-sm text-slate-500">Loading…</p></PortalFrame>;
  if (sites.error) return <PortalFrame><PortalMessage tone="error">{portalError(sites.error)}</PortalMessage></PortalFrame>;
  const list = sites.data ?? [];
  if (list.length === 1) return <Navigate to={`/support/${list[0].id}`} replace />;
  return (
    <PortalFrame>
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-semibold text-slate-900">Services &amp; Support</h1>
      <p className="mt-1 text-sm text-slate-500">Choose the laboratory you need help from.</p>
      {list.length === 0 && (
        <div className="mt-6"><PortalMessage>No site's help centre is open to you yet. Here people ask a site's
          services for help — the network, the workshop, the vacuum group — and follow their requests. It opens once
          a site's administrators publish its services (Administration → Site → Help centre); until then requests are
          made as tickets in the workspace. <Link to="/" className="font-medium underline">Back to the Knowledge Hub</Link>
        </PortalMessage></div>
      )}
      <ul className="mt-6 grid gap-3 sm:grid-cols-2">
        {list.map((s) => (
          <li key={s.id}>
            <Link to={`/support/${s.id}`}
                  className="block rounded-lg border border-slate-200 bg-white p-4 hover:border-indigo-300 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
              <p className="font-medium text-slate-900">{s.name}</p>
              <p className="mt-1 text-xs text-slate-500">From {s.origins.map((o) => o.name).join(", ")}</p>
              {!s.open && <p className="mt-2 text-xs font-medium text-amber-700">Not open yet — you manage this site.</p>}
            </Link>
          </li>
        ))}
      </ul>
    </div>
    </PortalFrame>
  );
}

const STOP = new Set(["the", "and", "for", "with", "not", "has", "have", "does", "doesn", "from", "this", "that", "into",
  "there", "when", "what", "can", "cannot", "any", "our", "your", "since", "della", "delle", "non", "che", "per", "con"]);

/** How well a search matches: the number of its words (3 letters or more, common words left out) found in the
 *  texts. A sentence such as "no network in lab 214" finds the network request types. */
function score(q: string, ...texts: (string | null | undefined)[]) {
  const words = q.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter((w) => w.length >= 3 && !STOP.has(w));
  const hay = texts.filter(Boolean).join(" ").toLowerCase();
  return words.filter((w) => hay.includes(w)).length;
}

/** /support/:siteId — "How can we help?": the site's services by category, each with its request types. */
export function SitePortal() {
  const { siteId = "" } = useParams();
  const cat = useQuery({ queryKey: ["portal", "catalogue", siteId], queryFn: () => portalApi.catalogue(siteId) });
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const data = cat.data;

  const hits = useMemo(() => {
    if (!data || !q.trim()) return [];
    const out: { svc: PortalService; rt: PortalRequestTypeCard; n: number }[] = [];
    for (const c of data.categories) for (const svc of c.services) for (const rt of svc.request_types) {
      // The request type's own words count double: "network not working" before "VPN" for "no network".
      const n = 2 * score(q, rt.name, rt.description) + score(q, svc.name, svc.description, c.name);
      if (n > 0) out.push({ svc, rt, n });
    }
    // Only the close matches: a word shared by chance ("lab") does not bring in every service.
    const best = Math.max(0, ...out.map((h) => h.n));
    return out.filter((h) => 2 * h.n >= best).sort((a, b) => b.n - a.n).slice(0, 6);
  }, [data, q]);

  if (cat.isLoading) return <PortalFrame siteId={siteId}><p className="text-sm text-slate-500">Loading…</p></PortalFrame>;
  if (cat.error || !data) {
    return <PortalFrame siteId={siteId}><PortalMessage tone="error">{portalError(cat.error) ?? "This help centre is not available."}</PortalMessage></PortalFrame>;
  }
  const shown = data.categories.filter((c) => !category || c.name === category);

  return (
    <PortalFrame siteId={siteId} siteName={data.site.name} emergency={data.emergency} hero={
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{data.headline}</h1>
        {data.welcome && <p className="mx-auto mt-2 max-w-2xl text-sm text-slate-200">{data.welcome}</p>}
        <label htmlFor="portal-search" className="sr-only">Search for help</label>
        <input id="portal-search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="What do you need help with?"
               className="mx-auto mt-5 block w-full max-w-2xl rounded-lg border-0 px-4 py-3 text-base text-slate-900 shadow-lg placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-400" />
      </div>
    }>
      {!data.open && <div className="mb-4"><PortalMessage>This help centre is not open to requesters yet: you see it
        because you manage the site.</PortalMessage></div>}

      {data.open_requests > 0 && (
        <Link to={`/support/${siteId}/requests`}
              className="mb-6 flex items-center justify-between rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900 hover:bg-indigo-100">
          <span>You have <b>{data.open_requests}</b> open request{data.open_requests === 1 ? "" : "s"}.</span>
          <span aria-hidden>→</span>
        </Link>
      )}

      {q.trim() ? (
        <section aria-label="Search results">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">{hits.length} matching request type{hits.length === 1 ? "" : "s"}</h2>
          <ul className="space-y-2">
            {hits.map(({ svc, rt }) => (
              <li key={rt.uid}><RequestTypeLink siteId={siteId} rt={rt} service={svc.name} /></li>
            ))}
          </ul>
          {data.assistance && <AssistHint siteId={siteId} data={data} text={q} />}
        </section>
      ) : (
        <>
          {data.categories.length > 1 && (
            <div role="tablist" aria-label="Categories" className="mb-5 flex flex-wrap gap-2">
              {[null, ...data.categories.map((c) => c.name)].map((name) => (
                <button key={name ?? "all"} role="tab" aria-selected={category === name} onClick={() => setCategory(name)}
                        className={`rounded-full px-3 py-1 text-sm ${category === name
                          ? "bg-slate-900 text-white" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-100"}`}>
                  {name ?? "All"}
                </button>
              ))}
            </div>
          )}
          {shown.map((c) => (
            <section key={c.name} className="mb-8" aria-labelledby={`cat-${c.name}`}>
              <h2 id={`cat-${c.name}`} className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">{c.name}</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {c.services.map((svc) => <ServiceCard key={svc.uid} siteId={siteId} svc={svc} />)}
              </div>
            </section>
          ))}
          {data.categories.length === 0 && <PortalMessage>No service is published here yet.</PortalMessage>}
        </>
      )}

      {data.helpdesk && (
        <div className="mt-8 flex flex-col items-start gap-3 rounded-lg border border-slate-200 bg-white p-5 sm:flex-row sm:items-center">
          <div className="flex-1">
            <p className="font-medium text-slate-900">Not sure who to ask?</p>
            <p className="text-sm text-slate-500">Describe it to the service desk: they will find the right team.</p>
          </div>
          <Link to={`/support/${siteId}/new/helpdesk`}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
            I'm not sure — ask the service desk
          </Link>
        </div>
      )}
    </PortalFrame>
  );
}

function ServiceCard({ siteId, svc }: { siteId: string; svc: PortalService }) {
  return (
    <article className="flex flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="font-semibold text-slate-900">{svc.name}</h3>
      {svc.description && <p className="mt-1 text-sm text-slate-600">{svc.description}</p>}
      {(svc.hours || svc.contact) && (
        <p className="mt-2 text-xs text-slate-500">{[svc.hours, svc.contact].filter(Boolean).join(" · ")}</p>
      )}
      <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3">
        {svc.request_types.map((rt) => (
          <li key={rt.uid}>
            <Link to={`/support/${siteId}/new/${rt.uid}`}
                  className="group block rounded px-2 py-1.5 -mx-2 hover:bg-indigo-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500">
              <span className="text-sm font-medium text-indigo-700 group-hover:underline">{rt.name}</span>
              {rt.description && <span className="block text-xs text-slate-500">{rt.description}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </article>
  );
}

function RequestTypeLink({ siteId, rt, service }: { siteId: string; rt: PortalRequestTypeCard; service: string }) {
  return (
    <Link to={`/support/${siteId}/new/${rt.uid}`}
          className="block rounded-lg border border-slate-200 bg-white px-4 py-3 hover:border-indigo-300">
      <span className="text-sm font-medium text-indigo-700">{rt.name}</span>
      <span className="ml-2 text-xs text-slate-500">{service}</span>
      {rt.description && <span className="block text-xs text-slate-500">{rt.description}</span>}
    </Link>
  );
}

/** Optional help from the search box: articles the person can read (in their own workspace and the services'
 *  workspaces), and — only when they ask — first steps the assistant draws from those articles, with the service
 *  that fits and a drafted summary if they still need help. */
function AssistHint({ siteId, data, text }: { siteId: string; data: PortalCatalogue; text: string }) {
  const origin = data.origins[0]?.id;
  const [asked, setAsked] = useState(false);
  const [solved, setSolved] = useState(false);
  const articles = useQuery({
    queryKey: ["portal", "assist", siteId, origin, text, asked],
    queryFn: () => portalApi.assist(siteId, text, origin!, asked),
    enabled: !!origin && text.trim().length >= 4,
    staleTime: 60_000,
  });
  const res = articles.data;
  const ai = res?.ai;
  const suggestion = ai?.request_type_uid;
  const suggested = data.categories.flatMap((c) => c.services.flatMap((svc) => svc.request_types))
    .find((rt) => rt.uid === suggestion);
  const steps = ai?.first_help ?? [];
  if (asked && articles.isFetching) {
    return <p className="mt-6 text-sm text-slate-500" role="status">The assistant is looking at the help articles…</p>;
  }
  if (!res) return null;
  const draft = ai && {
    title: ai.title,
    description: [ai.summary, steps.length ? `Already tried (suggested by the help centre):\n${steps.map((s) => `- ${s}`).join("\n")}` : ""]
      .filter(Boolean).join("\n\n"),
  };
  const docLink = (a: { uid: string; workspace_id: string }) => `/documents/${a.uid}?ws=${encodeURIComponent(a.workspace_id)}`;
  return (
    <div className="mt-6 space-y-3">
      {res.ai_available && !asked && (
        <button onClick={() => setAsked(true)} className="text-sm font-medium text-indigo-700 hover:underline">
          Ask the assistant for help →
        </button>
      )}
      {ai?.error && <PortalMessage tone="error">{ai.error}</PortalMessage>}
      {ai && !ai.error && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4" aria-live="polite">
          {steps.length > 0 ? (
            <>
              <h3 className="text-sm font-semibold text-emerald-900">Try this first</h3>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-800">
                {steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
              {!!ai.sources?.length && (
                <p className="mt-2 text-xs text-slate-600">From: {ai.sources.map((a, i) => (
                  <span key={a.uid}>{i > 0 && " · "}<Link to={docLink(a)} className="text-indigo-700 hover:underline">{a.title}</Link></span>
                ))}</p>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-700">The help articles do not cover this: send a request to the team.</p>
          )}
          {ai.why && <p className="mt-2 text-sm text-slate-700">{ai.why}</p>}
          {solved ? (
            <p className="mt-3 text-sm font-medium text-emerald-900" role="status">Glad it is solved — no request was sent.</p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {steps.length > 0 && (
                <button onClick={() => setSolved(true)}
                        className="rounded-md border border-emerald-300 bg-white px-3 py-1.5 text-sm font-medium text-emerald-800 hover:bg-emerald-100">
                  That solved it
                </button>
              )}
              {suggestion && (
                <Link to={`/support/${siteId}/new/${suggestion}`} state={{ draft }}
                      className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
                  {steps.length > 0 ? "Still need help? " : ""}Send “{suggested?.name ?? "the request"}” with the drafted summary →
                </Link>
              )}
            </div>
          )}
          <span className="mt-2 block text-xs text-slate-500">Suggestions from the help articles: you decide, and you review anything before it is sent.</span>
        </div>
      )}
      {res.articles.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-semibold text-slate-700">Articles that may help</h3>
          <ul className="mt-2 space-y-2">
            {res.articles.map((a) => (
              <li key={a.uid} className="text-sm">
                <Link to={docLink(a)} className="font-medium text-indigo-700 hover:underline">{a.title}</Link>
                {a.excerpt && <p className="text-xs text-slate-500">{a.excerpt}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
