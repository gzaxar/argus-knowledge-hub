import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { portalError, serviceDeskApi } from "../../api/client";
import type { AdminRequestType, AdminService, RequestTypeInput, ServiceDeskOptions, ServiceInput } from "../../api/portalTypes";

const INPUT = "mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-sm";
const BUTTON = "rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50";
const SECONDARY = "rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50";

function Problems({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-2 list-disc space-y-0.5 rounded bg-amber-50 py-2 pl-6 pr-3 text-xs text-amber-900">
      {items.map((p) => <li key={p}>{p}</li>)}
    </ul>
  );
}

/** /sites/:siteId/service-desk — the site's help centre: whether it is open, its services, their request types and
 *  requester fields, and where each sends its tickets. Publishing needs the destination workspace's authorisation. */
export function ServiceDeskPage() {
  const { siteId = "" } = useParams();
  const qc = useQueryClient();
  const desk = useQuery({ queryKey: ["service-desk", siteId], queryFn: () => serviceDeskApi.get(siteId) });
  const options = useQuery({ queryKey: ["service-desk-options", siteId], queryFn: () => serviceDeskApi.options(siteId) });
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["service-desk", siteId] }); setError(null); setProblems([]); };
  const fail = (e: unknown) => {
    setError(portalError(e));
    const body = (e as { body?: { detail?: { problems?: string[] } } }).body;
    setProblems(body?.detail?.problems ?? []);
  };
  const act = useMutation({ mutationFn: (f: () => Promise<unknown>) => f(), onSuccess: refresh, onError: fail });

  const s = desk.data?.settings;
  const [settings, setSettings] = useState({ enabled: false, headline: "", welcome: "", emergency: "",
    helpdesk_request_type_uid: "", assistance: false });
  useEffect(() => {
    if (s) setSettings({ enabled: s.enabled, headline: s.headline ?? "", welcome: s.welcome ?? "",
      emergency: s.emergency ?? "", helpdesk_request_type_uid: s.helpdesk_request_type_uid ?? "", assistance: s.assistance });
  }, [s]);

  if (desk.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (desk.error || !desk.data) return <p className="text-sm text-red-700">{portalError(desk.error)}</p>;
  const allTypes = desk.data.services.flatMap((svc) => svc.request_types.map((rt) => ({ svc, rt })));

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Help centre <span className="text-base font-normal text-slate-500">· site {s?.site_name}</span></h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          The services people at this site and its facilities can ask for help. Each request becomes one ticket in
          the service's workspace, in its team's queue, with that workspace's workflow and notifications. Requesters
          follow only their own requests; they get no right on the workspace.
        </p>
        <Link to={`/support/${siteId}`} className="mt-2 inline-block text-sm text-indigo-700 hover:underline">
          Open the help centre as requesters see it →
        </Link>
      </div>
      {error && <div role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
        {error}<Problems items={problems} /></div>}

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold text-slate-900">Portal</h2>
        <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault();
          act.mutate(() => serviceDeskApi.saveSettings(siteId, { ...settings,
            helpdesk_request_type_uid: settings.helpdesk_request_type_uid || null }));
        }}>
          <label className="text-sm">Headline<input className={INPUT} placeholder="How can we help?" value={settings.headline}
                 onChange={(e) => setSettings({ ...settings, headline: e.target.value })} /></label>
          <label className="text-sm">"I'm not sure" goes to
            <select className={INPUT} value={settings.helpdesk_request_type_uid}
                    onChange={(e) => setSettings({ ...settings, helpdesk_request_type_uid: e.target.value })}>
              <option value="">— choose the helpdesk request type —</option>
              {allTypes.map(({ svc, rt }) => <option key={rt.uid} value={rt.uid}>{svc.name}: {rt.name}</option>)}
            </select></label>
          <label className="text-sm sm:col-span-2">Welcome text<textarea rows={2} className={INPUT} value={settings.welcome}
                 onChange={(e) => setSettings({ ...settings, welcome: e.target.value })} /></label>
          <label className="text-sm sm:col-span-2">Emergency instructions (shown on every portal page)
            <input className={INPUT} placeholder="Fire, injury, gas: call 112 and the control room on 1234" value={settings.emergency}
                   onChange={(e) => setSettings({ ...settings, emergency: e.target.value })} /></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.assistance}
                 onChange={(e) => setSettings({ ...settings, assistance: e.target.checked })} />
            Offer help while choosing (articles the requester may read, here and in the services' workspaces; AI first help only where their workspace's AI is on)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.enabled}
                 onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })} />
            Open the help centre to requesters</label>
          <div className="sm:col-span-2"><button className={BUTTON} disabled={act.isPending}>Save</button></div>
        </form>
      </section>

      <section>
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-slate-900">Services</h2>
          <button className={SECONDARY} onClick={() => setEditing("new")}>+ New service</button>
        </div>
        {editing === "new" && options.data && (
          <ServiceEditor options={options.data} onCancel={() => setEditing(null)}
                         onSave={(input) => act.mutate(async () => { await serviceDeskApi.createService(siteId, input); setEditing(null); })} />
        )}
        <ul className="mt-3 space-y-3">
          {desk.data.services.map((svc) => (
            <li key={svc.uid} className="rounded-lg border border-slate-200 bg-white p-4">
              {editing === svc.uid && options.data ? (
                <ServiceEditor options={options.data} initial={svc} onCancel={() => setEditing(null)}
                               onSave={(input) => act.mutate(async () => { await serviceDeskApi.updateService(siteId, svc.uid, input); setEditing(null); })} />
              ) : (
                <ServiceRow svc={svc} siteId={siteId} options={options.data} act={act.mutate} busy={act.isPending}
                            onEdit={() => setEditing(svc.uid)} />
              )}
            </li>
          ))}
          {desk.data.services.length === 0 && <li className="text-sm text-slate-500">No service yet. Start with a
            service desk that takes "I'm not sure", then add the site's services.</li>}
        </ul>
      </section>
    </div>
  );
}

function ServiceRow({ svc, siteId, options, act, busy, onEdit }: {
  svc: AdminService; siteId: string; options?: ServiceDeskOptions; act: (f: () => Promise<unknown>) => void;
  busy: boolean; onEdit: () => void;
}) {
  const [adding, setAdding] = useState<string | "new" | null>(null);
  const mayAuthorize = options?.workspaces.find((w) => w.id === svc.provider_workspace_id)?.may_authorize;
  const ticketTypes = options?.workspaces.find((w) => w.id === svc.provider_workspace_id)?.ticket_types ?? [];
  return (
    <div>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-slate-900">{svc.name}
            <span className={`ml-2 rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase ${svc.active
              ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>{svc.active ? "Published" : "Draft"}</span>
          </p>
          <p className="text-xs text-slate-500">{svc.category ?? "Services"} · tickets into <b>{svc.provider_name}</b>,
            queue of <b>{svc.team_name}</b>{svc.authorized_by ? ` · authorised by ${svc.authorized_by}` : " · not authorised yet"}</p>
          {svc.description && <p className="mt-1 text-sm text-slate-600">{svc.description}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={SECONDARY} onClick={onEdit}>Edit</button>
          {mayAuthorize && !svc.authorized_by && (
            <button className={SECONDARY} disabled={busy} onClick={() => act(() => serviceDeskApi.authorize(siteId, svc.uid))}>
              Authorise destination</button>)}
          {svc.active ? (
            <button className={SECONDARY} disabled={busy} onClick={() => act(() => serviceDeskApi.unpublish(siteId, svc.uid))}>Unpublish</button>
          ) : (
            <button className={BUTTON} disabled={busy} onClick={() => act(() => serviceDeskApi.publish(siteId, svc.uid))}>Publish</button>
          )}
        </div>
      </div>
      <Problems items={svc.problems} />
      <div className="mt-3 border-t border-slate-100 pt-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Request types</p>
          <button className="text-xs text-indigo-700 hover:underline" onClick={() => setAdding("new")}>+ Add</button>
        </div>
        {adding === "new" && (
          <RequestTypeEditor ticketTypes={ticketTypes} onCancel={() => setAdding(null)}
                             onSave={(input) => { act(() => serviceDeskApi.createRequestType(siteId, svc.uid, input)); setAdding(null); }} />
        )}
        <ul className="mt-2 space-y-2">
          {svc.request_types.map((rt) => (
            <li key={rt.uid} className="rounded border border-slate-100 px-3 py-2 text-sm">
              {adding === rt.uid ? (
                <RequestTypeEditor ticketTypes={ticketTypes} initial={rt} onCancel={() => setAdding(null)}
                                   onSave={(input) => { act(() => serviceDeskApi.updateRequestType(siteId, rt.uid, input)); setAdding(null); }} />
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{rt.name}</span>
                  {!rt.active && <span className="text-xs text-slate-400">(hidden)</span>}
                  <span className="text-xs text-slate-500">
                    {ticketTypes.find((t) => t.uid === rt.schema_uid)?.name ?? (rt.schema_uid ? "ticket type" : "plain ticket")}
                    {rt.fields.length ? ` · asks ${rt.fields.map((f) => f.label || f.key).join(", ")}` : ""}
                  </span>
                  <button className="ml-auto text-xs text-indigo-700 hover:underline" onClick={() => setAdding(rt.uid)}>Edit</button>
                  <Problems items={rt.problems.filter((p) => !svc.problems.includes(p))} />
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ServiceEditor({ options, initial, onSave, onCancel }: {
  options: ServiceDeskOptions; initial?: AdminService; onSave: (i: ServiceInput) => void; onCancel: () => void;
}) {
  const [v, setV] = useState<ServiceInput>({
    name: initial?.name ?? "", category: initial?.category ?? "", description: initial?.description ?? "",
    hours: initial?.hours ?? "", contact: initial?.contact ?? "",
    provider_workspace_id: initial?.provider_workspace_id ?? options.workspaces[0]?.id ?? "",
    team_group_uid: initial?.team_group_uid ?? "", position: initial?.position ?? 0,
  });
  const set = (k: keyof ServiceInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setV({ ...v, [k]: k === "position" ? Number(e.target.value) : e.target.value });
  return (
    <form className="mt-3 grid gap-3 rounded border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); onSave(v); }}>
      <label className="text-sm">Name<input required className={INPUT} value={v.name} onChange={set("name")} /></label>
      <label className="text-sm">Category<input className={INPUT} placeholder="IT, Facilities, Accelerator…" value={v.category ?? ""} onChange={set("category")} /></label>
      <label className="text-sm sm:col-span-2">What it handles<textarea rows={2} className={INPUT} value={v.description ?? ""} onChange={set("description")} /></label>
      <label className="text-sm">Hours<input className={INPUT} value={v.hours ?? ""} onChange={set("hours")} /></label>
      <label className="text-sm">Contact<input className={INPUT} value={v.contact ?? ""} onChange={set("contact")} /></label>
      <label className="text-sm">Tickets go to (workspace)
        <select className={INPUT} value={v.provider_workspace_id} onChange={set("provider_workspace_id")}>
          {options.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select></label>
      <label className="text-sm">Responsible team (group)
        <select required className={INPUT} value={v.team_group_uid} onChange={set("team_group_uid")}>
          <option value="">— choose —</option>
          {options.groups.map((g) => <option key={g.uid} value={g.uid}>{g.name}</option>)}
        </select></label>
      <label className="text-sm">Order<input type="number" className={INPUT} value={v.position ?? 0} onChange={set("position")} /></label>
      <div className="flex items-end gap-2"><button className={BUTTON}>Save</button>
        <button type="button" className={SECONDARY} onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

function RequestTypeEditor({ ticketTypes, initial, onSave, onCancel }: {
  ticketTypes: ServiceDeskOptions["workspaces"][number]["ticket_types"]; initial?: AdminRequestType;
  onSave: (i: RequestTypeInput) => void; onCancel: () => void;
}) {
  const [v, setV] = useState<RequestTypeInput>({
    name: initial?.name ?? "", description: initial?.description ?? "", guidance: initial?.guidance ?? "",
    schema_uid: initial?.schema_uid ?? null, fields: initial?.fields ?? [], allow_attachments: initial?.allow_attachments ?? true,
    active: initial?.active ?? true, position: initial?.position ?? 0,
  });
  const type = ticketTypes.find((t) => t.uid === v.schema_uid);
  const chosen = (key: string) => v.fields.find((f) => f.key === key);
  const toggle = (key: string, label: string) => setV({ ...v, fields: chosen(key)
    ? v.fields.filter((f) => f.key !== key) : [...v.fields, { key, label, required: false }] });
  return (
    <form className="mt-2 grid gap-3 rounded border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2"
          onSubmit={(e) => { e.preventDefault(); onSave(v); }}>
      <label className="text-sm">Name<input required className={INPUT} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></label>
      <label className="text-sm">Ticket type
        <select className={INPUT} value={v.schema_uid ?? ""} onChange={(e) => setV({ ...v, schema_uid: e.target.value || null, fields: [] })}>
          <option value="">Plain ticket</option>
          {ticketTypes.map((t) => <option key={t.uid} value={t.uid}>{t.name}</option>)}
        </select></label>
      <label className="text-sm sm:col-span-2">Short description<input className={INPUT} value={v.description ?? ""}
             onChange={(e) => setV({ ...v, description: e.target.value })} /></label>
      <label className="text-sm sm:col-span-2">Guidance shown above the form<textarea rows={2} className={INPUT} value={v.guidance ?? ""}
             onChange={(e) => setV({ ...v, guidance: e.target.value })} /></label>
      {type && (
        <fieldset className="text-sm sm:col-span-2">
          <legend className="font-medium">Fields the requester fills in</legend>
          <p className="text-xs text-slate-500">Only these are shown and accepted; every other field of the type stays internal.</p>
          <ul className="mt-1 space-y-1">
            {type.fields.map((f) => {
              const c = chosen(f.key);
              return (
                <li key={f.key} className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2"><input type="checkbox" checked={!!c} onChange={() => toggle(f.key, f.label)} />{f.label}</label>
                  {c && <>
                    <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={c.required}
                           onChange={(e) => setV({ ...v, fields: v.fields.map((x) => x.key === f.key ? { ...x, required: e.target.checked } : x) })} />required</label>
                    <input aria-label={`Help for ${f.label}`} placeholder="help text" className="rounded border border-slate-300 px-2 py-0.5 text-xs"
                           value={c.help ?? ""} onChange={(e) => setV({ ...v, fields: v.fields.map((x) => x.key === f.key ? { ...x, help: e.target.value } : x) })} />
                  </>}
                </li>
              );
            })}
          </ul>
        </fieldset>
      )}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.allow_attachments}
             onChange={(e) => setV({ ...v, allow_attachments: e.target.checked })} />Takes attachments</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.active}
             onChange={(e) => setV({ ...v, active: e.target.checked })} />Shown to requesters</label>
      <div className="flex gap-2 sm:col-span-2"><button className={BUTTON}>Save</button>
        <button type="button" className={SECONDARY} onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

/** /admin/service-authorizations — for whoever manages a workspace's access: the site services that send, or ask
 *  to send, tickets into it. Authorising one lets the site publish it; revoking stops it at once. */
export function ServiceAuthorizationsPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["service-authorizations"], queryFn: serviceDeskApi.myAuthorizations });
  const [error, setError] = useState<string | null>(null);
  const act = useMutation({ mutationFn: (f: () => Promise<unknown>) => f(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["service-authorizations"] }); setError(null); },
    onError: (e) => setError(portalError(e)) });
  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Help centre destinations</h1>
        <p className="mt-1 text-sm text-slate-500">Site services that create tickets in a workspace whose access you
          manage. A service can be published only once someone who manages its destination has authorised it.</p>
      </div>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <ul className="space-y-2">
        {(list.data ?? []).map((svc) => (
          <li key={svc.uid} className="flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-white p-3 text-sm">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{svc.name} <span className="text-xs text-slate-500">· site {svc.site_name}</span></p>
              <p className="text-xs text-slate-500">into {svc.provider_name}, queue of {svc.team_name} ·{" "}
                {svc.authorized_by ? `authorised by ${svc.authorized_by}` : "waiting for authorisation"} · {svc.active ? "published" : "draft"}</p>
            </div>
            {svc.authorized_by ? (
              <button className={SECONDARY} onClick={() => act.mutate(() => serviceDeskApi.revoke(svc.site_id!, svc.uid))}>Revoke</button>
            ) : (
              <button className={BUTTON} onClick={() => act.mutate(() => serviceDeskApi.authorize(svc.site_id!, svc.uid))}>Authorise</button>
            )}
          </li>
        ))}
        {list.data?.length === 0 && <li className="text-sm text-slate-500">No site service points at a workspace you manage.</li>}
      </ul>
    </div>
  );
}
