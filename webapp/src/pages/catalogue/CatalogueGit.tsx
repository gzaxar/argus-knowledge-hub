import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  catalogueCollectionsApi, type CatalogueProposalDraft, type CatalogueProposalIn, type CatalogueSourcePin,
} from "../../api/client";
import { problem } from "./catalogueText";

const input = "w-full rounded border border-slate-300 px-2 py-1 text-sm";
const button = "rounded border border-slate-300 px-2 py-1 text-xs font-medium hover:bg-slate-50 disabled:opacity-50";
const primary = "rounded bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-50";

const STATE: Record<string, string> = {
  open: "pull request open", merged: "merged: waiting for a release", closed: "closed without merging",
  installed: "installed: linked to its entry",
};

/** A source pinned to a release: the newer releases of its repository, pinned from here after the server checks
 *  them; and back to the lock's. Pinning installs nothing: the collections then show their upgrades. */
export function SourceReleases({ source }: { source: CatalogueSourcePin }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const releases = useQuery({ queryKey: ["catalogue-releases", source.id], enabled: open,
                              queryFn: () => catalogueCollectionsApi.releases(source.id) });
  const done = () => {
    for (const k of ["catalogue-collections", "catalogue-releases", "catalogue-newer", "catalogue-models"]) {
      queryClient.invalidateQueries({ queryKey: [k] });
    }
  };
  const pin = useMutation({ mutationFn: (ref: string) => catalogueCollectionsApi.pin(source.id, ref), onSuccess: done });
  const unpin = useMutation({ mutationFn: () => catalogueCollectionsApi.unpin(source.id), onSuccess: done });
  if (!source.releasable) return null;
  const moved = source.pinned_in === "administration";
  const newer = (releases.data?.releases ?? []).filter((r) => r.newer);
  return (
    <div className="ml-4 mt-1 text-xs text-slate-600">
      {moved && (
        <p>
          Pinned here to <span className="font-mono">{source.ref}</span>
          {source.pinned_by && <> by {source.pinned_by}</>}
          {source.pinned_at && <> on {new Date(source.pinned_at).toLocaleDateString()}</>}; ARGUS ships{" "}
          <span className="font-mono">{source.shipped_ref}</span>.{" "}
          <button type="button" className="text-sky-800 underline disabled:opacity-50" disabled={unpin.isPending}
                  onClick={() => unpin.mutate()}>Back to {source.shipped_ref}</button>
        </p>
      )}
      {!open ? (
        <button type="button" className="text-sky-800 underline" onClick={() => setOpen(true)}>Check for newer releases</button>
      ) : releases.isLoading ? <span>Asking the repository…</span>
        : releases.isError ? <span className="text-red-700">{problem(releases.error)}</span>
        : newer.length === 0 ? <span>No newer release.</span> : (
        <ul className="mt-1 space-y-1">
          {newer.map((r) => (
            <li key={r.tag} className="flex items-center gap-2">
              <span className="font-mono">{r.tag}</span>
              <span className="font-mono text-slate-400">{r.commit.slice(0, 12)}</span>
              <button type="button" className={button} disabled={pin.isPending} onClick={() => pin.mutate(r.tag)}>
                {pin.isPending && pin.variables === r.tag ? "Checking…" : `Check and pin ${r.tag}`}
              </button>
            </li>
          ))}
        </ul>
      )}
      {pin.isSuccess && (
        <p role="status" className="mt-1 text-emerald-800">
          {pin.data.ref} is pinned. Choose the collections with an upgrade below, preview, and install.
        </p>
      )}
      {(pin.isError || unpin.isError) && (
        <p className="mt-1 whitespace-pre-line text-red-700">{problem(pin.error ?? unpin.error)}</p>
      )}
    </div>
  );
}

/** The models proposed to Git from here, and how far each got. */
export function CatalogueProposals() {
  const list = useQuery({ queryKey: ["catalogue-proposals"], queryFn: catalogueCollectionsApi.proposals });
  if (list.isError) return <p className="text-sm text-red-600">{problem(list.error)}</p>;
  const rows = list.data?.proposals ?? [];
  return (
    <section aria-label="Proposed to Git">
      <h2 className="mb-1 text-sm font-semibold text-slate-900">Proposed to Git</h2>
      {list.data && !list.data.enabled && (
        <p className="text-xs text-amber-800">
          Proposing needs ARGUS_GITHUB_TOKEN with contents and pull requests on{" "}
          <span className="font-mono">{list.data.repository ?? "the catalogue repository"}</span>.
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">
          None. A model made here is proposed from its page: <i>Propose for the catalogue</i>.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white text-sm">
          {rows.map((p) => (
            <li key={p.id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2">
              <a href={`/catalogue/models/${p.record_uid}`} className="font-medium text-sky-800 hover:underline">
                {p.record_name ?? p.record_uid}
              </a>
              <span className="font-mono text-xs">{p.catalogue_id}</span>
              <span className="text-xs text-slate-500">in {p.collection_id}</span>
              {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="text-xs text-sky-800 underline">
                #{p.number}</a>}
              <span className={`text-xs ${p.state === "closed" ? "text-red-700" : p.state === "installed" ? "text-emerald-800" : "text-slate-600"}`}>
                {STATE[p.state] ?? p.state}
              </span>
              <span className="text-xs text-slate-400">{p.proposed_by}, {new Date(p.proposed_at).toLocaleDateString()}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function initial(d: CatalogueProposalDraft): CatalogueProposalIn {
  return {
    record_uid: d.record_uid,
    entry: { ...d.entry },
    vendor: d.vendor.new ? { id: d.vendor.id, name: d.vendor.name,
                             website: String(d.vendor.entry?.website ?? "") } : {},
    collection: { id: d.collections[0]?.id ?? "" },
    source: { kind: "datasheet", ref: String(d.entry.datasheet_url ?? "") },
  };
}

const FIELDS: { key: string; label: string; hint?: string }[] = [
  { key: "model_code", label: "Model code", hint: "The manufacturer's designation, as on the label" },
  { key: "name", label: "Name" },
  { key: "part_number", label: "Part number" },
  { key: "datasheet_url", label: "Datasheet" },
  { key: "description", label: "Description", hint: "What the product is, in a sentence (no datasheet text)" },
];

/** A model made here, proposed for the Git catalogue: the entry ARGUS reads from it, completed and checked, then
 *  opened as a pull request. When the release carrying it is installed, this record is linked to its entry. */
export function ProposeModel({ uid }: { uid: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CatalogueProposalIn | null>(null);
  const [newCollection, setNewCollection] = useState(false);
  const draft = useQuery({ queryKey: ["catalogue-proposal-draft", uid], enabled: open, retry: false,
                           queryFn: () => catalogueCollectionsApi.proposalDraft(uid) });
  const preview = useMutation({ mutationFn: (b: CatalogueProposalIn) => catalogueCollectionsApi.proposalPreview(b) });
  const propose = useMutation({
    mutationFn: (b: CatalogueProposalIn) => catalogueCollectionsApi.propose(b),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["catalogue-proposals"] });
      queryClient.invalidateQueries({ queryKey: ["catalogue-proposal-draft", uid] });
    },
  });

  if (!open) {
    return <button type="button" className={button} onClick={() => setOpen(true)}>Propose for the catalogue…</button>;
  }
  if (propose.isSuccess) {
    return (
      <p role="status" className="rounded border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-900">
        Proposed as <span className="font-mono">{propose.data.catalogue_id}</span>:{" "}
        {propose.data.url ? <a href={propose.data.url} target="_blank" rel="noreferrer" className="underline">
          pull request #{propose.data.number}</a> : "pull request opened"}. Once it is merged, its release is offered at the top of
        Administration › Catalogue: <i>Review the update</i>, then <i>Install</i>. This record is then linked to its entry.
      </p>
    );
  }
  if (draft.isLoading) return <p className="text-sm text-slate-500">Reading the record…</p>;
  if (draft.isError || !draft.data) {
    return <p className="whitespace-pre-line text-sm text-red-600">{problem(draft.error)}</p>;
  }
  const d = draft.data;
  const f = form ?? initial(d);
  const set = (next: Partial<CatalogueProposalIn>) => { setForm({ ...f, ...next }); preview.reset(); };
  const setEntry = (k: string, v: string) => set({ entry: { ...f.entry, [k]: v } });
  const ready = !!f.collection.id && !!f.source.ref.trim() && !!f.entry.device_class;

  return (
    <form className="space-y-3 rounded border border-slate-200 bg-white p-3 text-sm"
          onSubmit={(e) => { e.preventDefault(); preview.mutate(f); }}>
      <h2 className="font-semibold text-slate-900">Propose for the catalogue</h2>
      <p className="text-xs text-slate-500">
        A pull request on <span className="font-mono">{d.repository ?? "the catalogue repository"}</span>, checked
        by the validator when it is opened and reviewed before it is released. Only what the source confirms goes in; the unit's serial, firmware and addresses stay on
        the unit.
      </p>
      {!d.enabled && (
        <p className="text-xs text-amber-800">ARGUS has no GitHub credential for it yet: the files can be checked, not proposed.</p>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs text-slate-500">Catalogue id</span>
          <input className={`${input} font-mono`} value={f.entry.id ?? ""} onChange={(e) => setEntry("id", e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs text-slate-500">Device class</span>
          <select className={input} value={f.entry.device_class ?? ""} onChange={(e) => setEntry("device_class", e.target.value)}>
            <option value="">—</option>
            {d.device_classes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {d.device_class_written && (
            <span className="text-xs text-amber-800">
              The record says “{d.device_class_written}”{d.entry.device_class
                ? `: read as ${d.entry.device_class}. Change it if that is wrong.`
                : ": choose the catalogue's class for it."}
            </span>
          )}
        </label>
        {FIELDS.map((x) => (
          <label key={x.key} className="block">
            <span className="text-xs text-slate-500">{x.label}</span>
            <input className={input} value={f.entry[x.key] ?? ""} title={x.hint}
                   onChange={(e) => setEntry(x.key, e.target.value)} />
          </label>
        ))}
      </div>

      <fieldset className="space-y-1">
        <legend className="text-xs font-semibold text-slate-700">Vendor</legend>
        {d.vendor.new ? (
          <div className="grid gap-2 sm:grid-cols-3">
            <p className="text-xs text-amber-800 sm:col-span-3">
              The catalogue has no vendor {d.vendor.name}: it is proposed with the model. If it is a company the
              catalogue has under another name, set that name on the record's vendor instead.
              {d.vendor.library_name && <> The NetBox library knows it as {d.vendor.library_name}, under the id{" "}
                <span className="font-mono">{d.vendor.id}</span>: the id stays, and that name is kept as a spelling.</>}
            </p>
            {(["id", "name", "website"] as const).map((k) => (
              <label key={k} className="block">
                <span className="text-xs text-slate-500">{k === "id" ? "Vendor id" : k === "name" ? "Name" : "Website"}</span>
                <input className={input} value={f.vendor[k] ?? ""}
                       readOnly={k === "id" && !!d.vendor.library_name}
                       title={k === "id" && d.vendor.library_name ? "The NetBox library's id for this company: its models are under it" : undefined}
                       onChange={(e) => {
                  const vendor = { ...f.vendor, [k]: e.target.value };
                  // The catalogue id is vendor/model: a new vendor id carries the model's id with it.
                  const was = `${f.vendor.id ?? ""}/`;
                  const id = String(f.entry.id ?? "");
                  set(k === "id" && id.startsWith(was)
                    ? { vendor, entry: { ...f.entry, id: `${e.target.value}/${id.slice(was.length)}` } }
                    : { vendor });
                }} />
              </label>
            ))}
            <label className="block sm:col-span-3">
              <span className="text-xs text-slate-500">Other spellings, comma separated</span>
              <input className={input} value={(f.vendor.aliases ?? []).join(", ")}
                     onChange={(e) => set({ vendor: { ...f.vendor, aliases: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} />
            </label>
          </div>
        ) : (
          <p className="text-xs text-slate-600">
            <span className="font-mono">{d.vendor.id}</span> ({d.vendor.name}), in the catalogue already.
          </p>
        )}
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="text-xs font-semibold text-slate-700">Collection</legend>
        <label className="mr-3 text-xs">
          <input type="radio" checked={!newCollection} onChange={() => { setNewCollection(false); set({ collection: { id: d.collections[0]?.id ?? "" } }); }} />{" "}
          an existing one
        </label>
        <label className="text-xs">
          <input type="radio" checked={newCollection} onChange={() => { setNewCollection(true); set({ collection: { id: "", domain: "catalogue" } }); }} />{" "}
          a new one
        </label>
        {!newCollection ? (
          <select className={input} value={f.collection.id} onChange={(e) => set({ collection: { id: e.target.value } })}>
            {d.collections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.id} {c.version})</option>)}
          </select>
        ) : (
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="block"><span className="text-xs text-slate-500">Id</span>
              <input className={`${input} font-mono`} placeholder="test-measurement" value={f.collection.id}
                     onChange={(e) => set({ collection: { ...f.collection, id: e.target.value } })} /></label>
            <label className="block"><span className="text-xs text-slate-500">Name</span>
              <input className={input} placeholder="Test and measurement" value={f.collection.name ?? ""}
                     onChange={(e) => set({ collection: { ...f.collection, name: e.target.value } })} /></label>
            <label className="block"><span className="text-xs text-slate-500">Offered to</span>
              <input className={`${input} font-mono`} title="A package id, or catalogue for every workspace"
                     value={f.collection.domain ?? ""}
                     onChange={(e) => set({ collection: { ...f.collection, domain: e.target.value } })} /></label>
          </div>
        )}
      </fieldset>

      <fieldset className="space-y-1">
        <legend className="text-xs font-semibold text-slate-700">Checked against</legend>
        <div className="grid gap-2 sm:grid-cols-[10rem_1fr]">
          <select className={input} value={f.source.kind} onChange={(e) => set({ source: { ...f.source, kind: e.target.value } })}>
            {d.source_kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <input className={input} placeholder="The datasheet's link, or the document checked" value={f.source.ref}
                 onChange={(e) => set({ source: { ...f.source, ref: e.target.value } })} />
          <input className={`${input} sm:col-span-2`} placeholder="A note for the reviewer (optional)" value={f.source.note ?? ""}
                 onChange={(e) => set({ source: { ...f.source, note: e.target.value } })} />
        </div>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <button type="button" className={primary} disabled={!ready || !d.enabled || propose.isPending}
                onClick={() => propose.mutate(f)}>
          {propose.isPending ? "Checking and opening…" : "Open the pull request"}
        </button>
        <button type="submit" className={button} disabled={!ready || preview.isPending}>
          {preview.isPending ? "Checking…" : "Show the files"}
        </button>
        <button type="button" className={button} onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {(preview.isError || propose.isError) && (
        <p className="whitespace-pre-line text-sm text-red-600">{problem(preview.error ?? propose.error)}</p>
      )}
      {preview.isSuccess && (
        <div className="space-y-2">
          <p className="text-xs text-emerald-800">
            The validator accepts it. <b>{preview.data.title}</b>, against {preview.data.base}:
          </p>
          {Object.entries(preview.data.files).map(([path, text]) => (
            <details key={path} className="rounded border border-slate-200">
              <summary className="cursor-pointer px-2 py-1 font-mono text-xs">{path}</summary>
              <pre className="max-h-64 overflow-auto bg-slate-50 p-2 text-xs">{text}</pre>
            </details>
          ))}
        </div>
      )}
    </form>
  );
}
