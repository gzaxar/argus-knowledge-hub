import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { portalApi, portalError, portalErrorCode } from "../../api/client";
import type { PortalField, PortalForm, RoutePreview } from "../../api/portalTypes";
import { ApiError } from "../../api/client";
import { PortalFrame, PortalMessage } from "./PortalFrame";

const HELPDESK = "helpdesk";

/** /support/:siteId/new/:requestTypeUid ("helpdesk" for "I'm not sure"): the request type's form, then a
 *  review of where it goes and exactly what is sent, then one submission — retried safely with the same id. */
export function RequestForm() {
  const { siteId = "", requestTypeUid = HELPDESK } = useParams();
  const helpdesk = requestTypeUid === HELPDESK;
  const navigate = useNavigate();
  const draft = (useLocation().state as { draft?: { title?: string; description?: string } } | null)?.draft;
  const cat = useQuery({ queryKey: ["portal", "catalogue", siteId], queryFn: () => portalApi.catalogue(siteId) });
  const typeUid = helpdesk ? cat.data?.helpdesk?.uid : requestTypeUid;
  const form = useQuery({
    queryKey: ["portal", "form", siteId, typeUid],
    queryFn: () => portalApi.form(siteId, typeUid!),
    enabled: !!typeUid,
  });

  const [origin, setOrigin] = useState<string>("");
  const [title, setTitle] = useState(draft?.title ?? "");
  const [description, setDescription] = useState(draft?.description ?? "");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [step, setStep] = useState<"form" | "review">("form");
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fallback, setFallback] = useState<RoutePreview | null>(null);
  // One id per request, kept for every retry of it: the server makes one ticket for it, whatever happens.
  const submission = useRef(crypto.randomUUID());
  const fileInput = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!origin && cat.data?.origins.length) setOrigin(cat.data.origins[0].id);
  }, [cat.data, origin]);
  useEffect(() => { heading.current?.focus(); }, [step]);

  const review = useMutation({
    mutationFn: () => portalApi.preview(siteId, helpdesk ? null : requestTypeUid, origin),
    onSuccess: (p) => { setPreview(p); setStep("review"); setError(null); setFallback(null); },
    onError: (e) => {
      setError(portalError(e));
      const fb = (e instanceof ApiError ? (e.body as { detail?: { fallback?: RoutePreview } })?.detail?.fallback : null);
      setFallback(fb ?? null);
    },
  });
  const send = useMutation({
    mutationFn: () => portalApi.submit(siteId, {
      submission_uid: submission.current, request_type_uid: helpdesk ? null : requestTypeUid,
      origin_workspace_id: origin, title, description, fields: typedFields(form.data?.fields ?? [], fields),
      route_version: preview?.version,
    }, files),
    onSuccess: (r) => navigate(`/support/${siteId}/requests/${r.uid}`, { state: { sent: true }, replace: true }),
    onError: (e) => {
      if (portalErrorCode(e) === "route_changed") {
        const p = (e as ApiError).body as { detail?: { preview?: RoutePreview } };
        if (p.detail?.preview) setPreview(p.detail.preview);
      }
      setError(portalError(e));
    },
  });

  if (cat.isLoading || form.isLoading) return <PortalFrame siteId={siteId}><p className="text-sm text-slate-500">Loading…</p></PortalFrame>;
  if (cat.error || !cat.data) return <PortalFrame siteId={siteId}><PortalMessage tone="error">{portalError(cat.error)}</PortalMessage></PortalFrame>;
  if (!typeUid || form.error || !form.data) {
    return (
      <PortalFrame siteId={siteId} siteName={cat.data.site.name} emergency={cat.data.emergency}
                   crumbs={[{ to: `/support/${siteId}`, label: "Help centre" }, { label: "Request" }]}>
        <PortalMessage tone="error">This request type is not available. <Link className="underline"
          to={`/support/${siteId}`}>Back to the services</Link></PortalMessage>
      </PortalFrame>
    );
  }
  const f: PortalForm = form.data;
  const missing = f.fields.filter((x) => x.required && !(fields[x.key] ?? "").trim()).map((x) => x.label);
  const ready = title.trim().length > 0 && !!origin && missing.length === 0;
  const originName = cat.data.origins.find((o) => o.id === origin)?.name ?? origin;

  return (
    <PortalFrame siteId={siteId} siteName={cat.data.site.name} emergency={cat.data.emergency}
                 crumbs={[{ to: `/support/${siteId}`, label: "Help centre" },
                   { label: helpdesk ? "Service desk" : f.service.name }, { label: f.name }]}>
      <div className="grid gap-6 lg:grid-cols-[1fr_16rem]">
        <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
          <ol aria-label="Steps" className="mb-4 flex gap-3 text-xs font-medium">
            <li className={step === "form" ? "text-indigo-700" : "text-slate-400"}>1. Describe</li>
            <li aria-hidden className="text-slate-300">›</li>
            <li className={step === "review" ? "text-indigo-700" : "text-slate-400"}>2. Review and send</li>
          </ol>
          <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold text-slate-900 focus:outline-none">
            {step === "form" ? f.name : "Check your request"}
          </h1>
          {error && <div className="mt-4"><PortalMessage tone="error">{error}
            {fallback && <> <button className="font-medium underline" onClick={() =>
              navigate(`/support/${siteId}/new/${HELPDESK}`, { state: { draft: { title, description } } })}>
              Send it to the service desk instead</button></>}
          </PortalMessage></div>}

          {step === "form" ? (
            <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) review.mutate(); }}>
              {f.description && <p className="text-sm text-slate-600">{f.description}</p>}
              {f.guidance && (
                <div className="whitespace-pre-wrap rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
                  {f.guidance}
                </div>
              )}
              {cat.data.origins.length > 1 && (
                <Field id="origin" label="Reporting from" required>
                  <select id="origin" value={origin} onChange={(e) => setOrigin(e.target.value)} className={INPUT}>
                    {cat.data.origins.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </Field>
              )}
              <Field id="title" label="Summary" required help="One line: what is wrong, or what you need.">
                <input id="title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} className={INPUT} />
              </Field>
              <Field id="description" label="Details" help="What happens, since when, where, and what you have tried.">
                <textarea id="description" rows={6} value={description} onChange={(e) => setDescription(e.target.value)}
                          className={INPUT} />
              </Field>
              {f.fields.map((x) => (
                <RequesterField key={x.key} field={x} value={fields[x.key] ?? ""}
                                onChange={(v) => setFields((all) => ({ ...all, [x.key]: v }))} />
              ))}
              {f.allow_attachments && (
                <div>
                  <p className="text-sm font-medium text-slate-700">Attachments</p>
                  <p className="text-xs text-slate-500">Screenshots, logs, photos — up to 10 files of 25 MB.</p>
                  <input ref={fileInput} type="file" multiple className="sr-only" id="files"
                         onChange={(e) => { setFiles((all) => [...all, ...Array.from(e.target.files ?? [])].slice(0, 10)); e.target.value = ""; }} />
                  <label htmlFor="files" className="mt-2 inline-block cursor-pointer rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
                    Add files
                  </label>
                  <ul className="mt-2 space-y-1 text-sm">
                    {files.map((file, i) => (
                      <li key={i} className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate">{file.name}</span>
                        <span className="text-xs text-slate-400">{Math.ceil(file.size / 1024)} KB</span>
                        <button type="button" className="text-xs text-red-600 hover:underline"
                                aria-label={`Remove ${file.name}`}
                                onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}>Remove</button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
                <button type="submit" disabled={!ready || review.isPending}
                        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                  {review.isPending ? "Checking…" : "Review"}
                </button>
                <Link to={`/support/${siteId}`} className="text-sm text-slate-600 hover:underline">Cancel</Link>
                {!ready && missing.length > 0 && <span className="text-xs text-slate-500">Still needed: {missing.join(", ")}</span>}
              </div>
            </form>
          ) : preview && (
            <div className="mt-4 space-y-4">
              <dl className="grid gap-x-4 gap-y-2 rounded-md bg-slate-50 p-4 text-sm sm:grid-cols-[10rem_1fr]">
                <dt className="text-slate-500">Service</dt><dd className="font-medium">{preview.service_name}: {preview.request_type_name}</dd>
                <dt className="text-slate-500">Responsible team</dt><dd className="font-medium">{preview.team_name}</dd>
                <dt className="text-slate-500">Reporting from</dt><dd>{originName}</dd>
                <dt className="text-slate-500">Why there</dt><dd className="text-slate-600">{preview.reason}</dd>
              </dl>
              <div>
                <h2 className="text-sm font-semibold text-slate-700">What the team will receive</h2>
                <dl className="mt-2 space-y-2 text-sm">
                  <div><dt className="text-xs text-slate-500">Summary</dt><dd>{title}</dd></div>
                  {description.trim() && <div><dt className="text-xs text-slate-500">Details</dt>
                    <dd className="whitespace-pre-wrap">{description}</dd></div>}
                  {f.fields.filter((x) => (fields[x.key] ?? "").trim()).map((x) => (
                    <div key={x.key}><dt className="text-xs text-slate-500">{x.label}</dt>
                      <dd>{x.options.find((o) => String(o.value) === fields[x.key])?.label ?? fields[x.key]}</dd></div>
                  ))}
                  {files.length > 0 && <div><dt className="text-xs text-slate-500">Files</dt>
                    <dd>{files.map((x) => x.name).join(", ")}</dd></div>}
                </dl>
                <p className="mt-3 text-xs text-slate-500">Nothing else is shared: not your other records, not the
                  equipment of your workspace. You follow the request under My requests.</p>
              </div>
              <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-4">
                <button onClick={() => send.mutate()} disabled={send.isPending}
                        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50">
                  {send.isPending ? "Sending…" : "Send request"}
                </button>
                <button onClick={() => {
                  // An edited request is another request: it gets its own id.
                  submission.current = crypto.randomUUID(); setStep("form"); setError(null); }} disabled={send.isPending}
                        className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm hover:bg-slate-50">
                  Back to edit
                </button>
              </div>
            </div>
          )}
        </section>
        <aside className="space-y-3 text-sm">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="font-medium text-slate-900">{helpdesk ? "Service desk" : f.service.name}</p>
            {f.service.description && <p className="mt-1 text-slate-600">{f.service.description}</p>}
            {f.service.hours && <p className="mt-2 text-xs text-slate-500">Hours: {f.service.hours}</p>}
            {f.service.contact && <p className="text-xs text-slate-500">Contact: {f.service.contact}</p>}
          </div>
          {!helpdesk && cat.data.helpdesk && (
            <Link to={`/support/${siteId}/new/${HELPDESK}`} state={{ draft: { title, description } }}
                  className="block rounded-lg border border-dashed border-slate-300 p-4 text-slate-600 hover:bg-white">
              Not the right service? <span className="text-indigo-700">Ask the service desk instead</span>
            </Link>
          )}
        </aside>
      </div>
    </PortalFrame>
  );
}

const INPUT = "mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

function Field({ id, label, required, help, children }: {
  id: string; label: string; required?: boolean; help?: string | null; children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}{required && <span className="text-red-600" aria-hidden> *</span>}
        {required && <span className="sr-only"> (required)</span>}
      </label>
      {help && <p id={`${id}-help`} className="text-xs text-slate-500">{help}</p>}
      {children}
    </div>
  );
}

function RequesterField({ field, value, onChange }: { field: PortalField; value: string; onChange: (v: string) => void }) {
  const id = `f-${field.key}`;
  return (
    <Field id={id} label={field.label} required={field.required} help={field.help}>
      {field.type === "enumeration" && field.options.length > 0 ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} aria-required={field.required}>
          <option value="">Choose…</option>
          {field.options.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
        </select>
      ) : field.type === "textarea" || field.type === "markdown" ? (
        <textarea id={id} rows={3} value={value} onChange={(e) => onChange(e.target.value)} className={INPUT} aria-required={field.required} />
      ) : (
        <input id={id} type={field.type === "date" ? "date" : field.type === "number" ? "number" : "text"} value={value}
               onChange={(e) => onChange(e.target.value)} className={INPUT} aria-required={field.required} />
      )}
    </Field>
  );
}

/** The values as the ticket type stores them: numbers as numbers, the rest as text; empty ones left out. */
function typedFields(defs: PortalField[], values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const d of defs) {
    const v = (values[d.key] ?? "").trim();
    if (!v) continue;
    out[d.key] = d.type === "number" && !Number.isNaN(Number(v)) ? Number(v) : v;
  }
  return out;
}
