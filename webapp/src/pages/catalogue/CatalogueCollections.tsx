import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  catalogueCollectionsApi, type CatalogueDecision, type CatalogueFieldDecision, type CataloguePatches,
  type CatalogueCollection, type CataloguePlan, type CataloguePlanItem,
} from "../../api/client";
import { CatalogueProposals, SourceReleases } from "./CatalogueGit";
import { CATEGORY, problem, shown } from "./catalogueText";

const FIELD_CHOICES: { v: CatalogueFieldDecision; label: string }[] = [
  { v: "managed", label: "the collection's" },
  { v: "local", label: "keep this record's" },
  { v: "propose", label: "keep, and propose to Git" },
];

function readText(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(f);
  });
}

function save(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/x-diff" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** The corrections proposed back to Git, as a patch per source repository to apply on a branch and propose. */
export function CorrectionPatches() {
  const [got, setGot] = useState<CataloguePatches | null>(null);
  const load = useMutation({
    mutationFn: catalogueCollectionsApi.corrections,
    onSuccess: (r) => {
      setGot(r);
      for (const p of r.patches) save(`${p.repo}-corrections.patch`, p.diff);
    },
  });
  const skipped = got?.items.filter((i) => i.status === "skipped") ?? [];
  return (
    <div className="mt-2">
      <button type="button" disabled={load.isPending} onClick={() => load.mutate()}
              className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
        {load.isPending ? "Preparing…" : "Download the corrections as patches"}
      </button>
      {load.isError && <p className="mt-1 whitespace-pre-line text-xs text-red-600">{problem(load.error)}</p>}
      {got && (
        <div className="mt-1 text-xs text-slate-600">
          {got.patches.length === 0 ? <p>No correction is waiting to go back to Git.</p> : (
            <p>
              {got.patches.map((p) => `${p.repo}-corrections.patch`).join(" and ")}: apply on a branch at the pinned
              commit (<span className="font-mono">git apply</span>) and open a pull request.
            </p>
          )}
          {skipped.length > 0 && (
            <ul className="mt-1 text-amber-800">
              {skipped.map((i) => <li key={`${i.catalogue_id}:${i.field}`}>{i.catalogue_id} {i.field}: {i.why}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Whether an item still needs something from the person, given the decisions made so far. */
export function stillOpen(item: CataloguePlanItem, d: CatalogueDecision | undefined): boolean {
  if (item.category !== "link") return false;
  if (!d?.action) return item.needs_decision;              // the server decided it: a record proposed to Git
  if (d.action === "create") return false;
  return item.fields.some((f) => f.action === null && !d.fields?.[f.field]);
}

/** The vendors waiting for a person — an existing record that looks like the collection's — that nobody has
 *  decided yet. With a manifest, only those it left undecided. */
export function openVendorLinks(plan: CataloguePlan, decisions: Record<string, CatalogueDecision>,
                                manifest: boolean): CataloguePlanItem[] {
  const undecided = new Set(plan.undecided);
  return plan.releases.flatMap((r) => r.items).filter((i) =>
    i.kind === "vendor" && i.category === "link" && i.needs_decision && (!manifest || undecided.has(i.catalogue_id)) &&
    !decisions[i.catalogue_id]?.action);
}

/** Link every such vendor, keeping this record's value of each field that differs (its name, usually): nothing
 *  already in ARGUS is overwritten, and each choice can still be changed one by one. */
export function linkAllVendors(items: CataloguePlanItem[]): Record<string, CatalogueDecision> {
  return Object.fromEntries(items.map((i) => [i.catalogue_id, {
    action: "link" as const,
    fields: Object.fromEntries(i.fields.filter((f) => f.action === null).map((f) => [f.field, "local" as const])),
  }]));
}

/** What an update brings: every collection with a newer version, and those a merged proposal is waiting in. */
export function updatesOf(collections: CatalogueCollection[], merged: Set<string>): string[] {
  return collections.filter((c) => c.problems.length === 0 && (c.upgrade_available || (merged.has(c.id) && !c.installed_version)))
    .map((c) => c.id);
}

/** A record that may already be the entry: link it (deciding the fields that differ) or create a separate one. */
function LinkDecision({ item, d, onChange }: {
  item: CataloguePlanItem; d: CatalogueDecision | undefined; onChange: (d: CatalogueDecision) => void;
}) {
  const differing = item.fields.filter((f) => f.action === null || (d?.fields && f.field in d.fields));
  return (
    <div className="mt-1 rounded border border-amber-200 bg-amber-50/50 p-2 text-xs">
      <p>
        <b>{item.record_name}</b> is already here and looks like the same {item.kind}.{" "}
        <label className="ml-1"><input type="radio" name={`a:${item.catalogue_id}`} checked={d?.action === "link"}
               onChange={() => onChange({ ...d, action: "link" })} /> link it (it keeps its id, key and references)</label>
        <label className="ml-2"><input type="radio" name={`a:${item.catalogue_id}`} checked={d?.action === "create"}
               onChange={() => onChange({ ...d, action: "create" })} /> create a separate one</label>
      </p>
      {d?.action === "link" && differing.length > 0 && (
        <table className="mt-1">
          <tbody>
            {differing.map((f) => (
              <tr key={f.field} className="align-top">
                <td className="pr-2 text-slate-500">{f.field}</td>
                <td className="pr-2">here: {shown(f.record)}<br />collection: {shown(f.release)}</td>
                <td>
                  {FIELD_CHOICES.map((c) => (
                    <label key={c.v} className="mr-2 whitespace-nowrap">
                      <input type="radio" name={`f:${item.catalogue_id}:${f.field}`} checked={d.fields?.[f.field] === c.v}
                             onChange={() => onChange({ ...d, fields: { ...d.fields, [f.field]: c.v } })} /> {c.label}
                    </label>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function PlanView({ plan, decisions, setDecision, setMany, manifest }: {
  plan: CataloguePlan; decisions: Record<string, CatalogueDecision>;
  setDecision: (id: string, d: CatalogueDecision) => void;
  setMany: (many: Record<string, CatalogueDecision>) => void; manifest: boolean;
}) {
  const undecided = new Set(plan.undecided);
  const vendors = openVendorLinks(plan, decisions, manifest);
  return (
    <div className="space-y-3">
      {vendors.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-amber-200 bg-amber-50/50 p-2 text-xs">
          <button type="button" onClick={() => setMany(linkAllVendors(vendors))}
                  className="rounded border border-slate-300 bg-white px-3 py-1 font-medium hover:bg-slate-50">
            Link all matching vendors ({vendors.length})
          </button>
          <span className="text-slate-600">
            Links each vendor still waiting to the record that matches it, keeping this record's value of any field
            that differs. Each can still be changed below.
          </span>
        </div>
      )}
      {plan.releases.map((r) => (
        <div key={r.collection} className="rounded border border-slate-200 p-3">
          <h3 className="text-sm font-semibold text-slate-900">
            {r.collection} {r.from_version ? `${r.from_version} → ` : ""}{r.version}
            {r.already_installed && <span className="ml-2 font-normal text-slate-500">already installed — nothing to do</span>}
          </h3>
          {Object.keys(r.not_stored).length > 0 && (
            <p className="text-xs text-slate-500">
              Kept in the collection only, until the Product Model type has the fields:{" "}
              {Object.entries(r.not_stored).map(([k, n]) => `${k} (${n})`).join(", ")}
            </p>
          )}
          <ul className="mt-1 space-y-1 text-sm">
            {r.items.filter((i) => i.category !== "unchanged").map((i) => (
              <li key={i.catalogue_id}>
                <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{CATEGORY[i.category]}</span>
                <span className="font-mono text-xs">{i.catalogue_id}</span>
                {i.record_uid && i.category !== "link" && (
                  <Link to={`/catalogue/models/${i.record_uid}`} className="ml-2 text-xs text-sky-800 hover:underline">{i.record_name}</Link>
                )}
                {i.category !== "link" && i.fields.filter((f) => f.action === "managed" || f.action === "conflict").length > 0 && (
                  <span className="ml-2 text-xs text-slate-500">
                    {i.fields.filter((f) => f.action === "managed" || f.action === "conflict")
                      .map((f) => `${f.field}${f.action === "conflict" ? " (kept)" : ""}`).join(", ")}
                  </span>
                )}
                {i.notes.filter((n) => i.category !== "link" || !n.startsWith("the same product")).map((n) => (
                  <span key={n} className="block text-xs text-slate-500">{n}</span>
                ))}
                {i.category === "link" && manifest && !undecided.has(i.catalogue_id) && (
                  <span className="ml-2 text-xs text-slate-600">
                    {i.record_name}: linked as the migration manifest says
                  </span>
                )}
                {i.category === "link" && !manifest && !i.needs_decision && !decisions[i.catalogue_id] && (
                  <span className="ml-2 text-xs text-emerald-800">
                    {i.record_name}: linked, the same record, with the reviewed values
                  </span>
                )}
                {i.category === "link" && (i.needs_decision || !!decisions[i.catalogue_id]) && (!manifest || undecided.has(i.catalogue_id)) && (
                  <LinkDecision item={i} d={decisions[i.catalogue_id]} onChange={(d) => setDecision(i.catalogue_id, d)} />
                )}
              </li>
            ))}
            {r.items.filter((i) => i.category === "unchanged").length > 0 && (
              <li className="text-xs text-slate-500">{r.items.filter((i) => i.category === "unchanged").length} unchanged</li>
            )}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** The collections this installation ships, what the catalogue has installed, previewing and installing a
 *  release, and the entries waiting for review. */
/** The catalogue's collections: sources, versions, preview and install, review, corrections, history. On its own
 *  page, or `embedded` in Administration › Catalogue. */
export function CatalogueCollectionsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["catalogue-collections"], queryFn: catalogueCollectionsApi.list });
  const review = useQuery({ queryKey: ["catalogue-review"], queryFn: catalogueCollectionsApi.review });
  const [chosen, setChosen] = useState<string[]>([]);
  const [plan, setPlan] = useState<CataloguePlan | null>(null);
  const [decisions, setDecisions] = useState<Record<string, CatalogueDecision>>({});
  const [manifest, setManifest] = useState<{ name: string; text: string } | null>(null);
  const [fromUpdate, setFromUpdate] = useState(false);
  const proposals = useQuery({ queryKey: ["catalogue-proposals"], queryFn: catalogueCollectionsApi.proposals, retry: false });
  const merged = new Set((proposals.data?.proposals ?? []).filter((p) => p.state === "merged").map((p) => p.collection_id));
  // The newest release of each source that moves by release; a repository out of reach only means nothing is offered.
  const releasable = (list.data?.sources ?? []).filter((s) => s.releasable).map((s) => s.id);
  const newer = useQuery({
    queryKey: ["catalogue-newer", releasable], enabled: releasable.length > 0, retry: false,
    queryFn: async () => {
      const found: { source: string; tag: string }[] = [];
      for (const source of releasable) {
        const got = await catalogueCollectionsApi.releases(source).catch(() => null);
        const next = got?.releases.find((r) => r.newer);
        if (next) found.push({ source, tag: next.tag });
      }
      return found;
    },
  });
  const waiting = updatesOf(list.data?.collections ?? [], merged);
  // One step for the whole of an update: the release read (the validator first), its collections chosen, previewed.
  const update = useMutation({
    mutationFn: async () => {
      for (const n of newer.data ?? []) await catalogueCollectionsApi.pin(n.source, n.tag);
      const fresh = await queryClient.fetchQuery({ queryKey: ["catalogue-collections"], queryFn: catalogueCollectionsApi.list, staleTime: 0 });
      const ids = updatesOf(fresh.collections, merged);
      return { ids, plan: ids.length ? await catalogueCollectionsApi.preview(ids, {}, null) : null };
    },
    onSuccess: ({ ids, plan: got }) => {
      install.reset();
      setChosen(ids);
      setPlan(got);
      setDecisions({});
      setManifest(null);
      setFromUpdate(true);
    },
    onSettled: () => {
      for (const k of ["catalogue-collections", "catalogue-newer", "catalogue-releases", "catalogue-models"]) {
        queryClient.invalidateQueries({ queryKey: [k] });
      }
    },
  });
  const preview = useMutation({ mutationFn: () => catalogueCollectionsApi.preview(chosen, decisions, manifest?.text),
                                onSuccess: (got) => setPlan(got) });
  const install = useMutation({
    mutationFn: () => catalogueCollectionsApi.install(chosen, decisions, manifest?.text),
    onSuccess: () => {
      setPlan(null);
      setDecisions({});
      setChosen([]);
      setManifest(null);
      setFromUpdate(false);
      for (const k of ["catalogue-collections", "catalogue-review", "catalogue-models", "catalogue-proposals"]) {
        queryClient.invalidateQueries({ queryKey: [k] });
      }
    },
  });
  const toggle = (id: string) => {
    setChosen(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]);
    setPlan(null);
    setFromUpdate(false);
  };
  const items = plan?.releases.flatMap((r) => r.items) ?? [];
  // The server applied the manifest's decisions to this plan: an item it left undecided is still open.
  const undecided = new Set(plan?.undecided ?? []);
  const open = items.filter((i) => (manifest ? undecided.has(i.catalogue_id) : true) &&
                                   stillOpen(i, decisions[i.catalogue_id]));
  const nothing = plan?.releases.every((r) => r.already_installed || r.items.every((i) => i.category === "unchanged"));
  const planBlock = plan && (
    <div className="mt-3 space-y-3">
      <PlanView plan={plan} decisions={decisions} manifest={!!manifest}
                setDecision={(id, d) => setDecisions({ ...decisions, [id]: d })}
                setMany={(many) => setDecisions({ ...decisions, ...many })} />
      {plan.trial && plan.trial !== "ok" && (
        <p className="text-sm text-red-700">A trial installation failed: {plan.trial.replace(/^failed: /, "")}</p>
      )}
      {open.length > 0 && (
        <p className="text-sm text-amber-800">
          {open.length} entr{open.length === 1 ? "y needs" : "ies need"} a decision before installing.
        </p>
      )}
      <button type="button" disabled={!!nothing || open.length > 0 || install.isPending} onClick={() => install.mutate()}
              className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
        {install.isPending ? "Installing…" : nothing ? "Nothing to install" : "Install"}
      </button>
      {install.isError && <p className="whitespace-pre-line text-sm text-red-600">{problem(install.error)}</p>}
    </div>
  );

  return (
    <div className="max-w-5xl space-y-6">
      {!embedded && <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Catalogue collections</h1>
          <p className="mt-1 text-sm text-slate-500">
            Versioned Vendor and Product Model records, reviewed in Git and shipped with ARGUS. Installing a release
            adds what is new, updates the values the collection manages, and never overwrites a value kept here.
          </p>
        </div>
        <Link to="/catalogue/models" className="text-sm font-medium text-sky-800 underline">Product catalogue</Link>
      </div>}
      {list.isError && <p className="whitespace-pre-line text-sm text-red-600">{problem(list.error)}</p>}

      {list.data && (
        <section aria-label="Update the catalogue" className="rounded border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-800">
              {(newer.data ?? []).length > 0
                ? <>Release <b className="font-mono">{newer.data!.map((n) => n.tag).join(", ")}</b> is out.</>
                : waiting.length > 0
                  ? <>{waiting.length} collection{waiting.length === 1 ? " has" : "s have"} an update to install.</>
                  : merged.size > 0
                    ? "A proposal is merged: its release is offered here once the repository has made it."
                    : "The catalogue is up to date."}
            </p>
            {((newer.data ?? []).length > 0 || waiting.length > 0) && (
              <button type="button" disabled={update.isPending} onClick={() => update.mutate()}
                      className="rounded bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-50">
                {update.isPending ? "Checking the release…" : "Review the update"}
              </button>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Reviewing checks the release and shows what would change. Nothing changes until you install.
          </p>
          {update.isError && <p className="mt-2 whitespace-pre-line text-sm text-red-600">{problem(update.error)}</p>}
          {install.isSuccess && (
            <p role="status" className="mt-2 text-sm text-emerald-800">
              Installed{Object.keys(install.data.counts).length > 0 &&
                `: ${Object.entries(install.data.counts).map(([k, n]) => `${n} ${CATEGORY[k] ?? k}`).join(", ")}`}.
            </p>
          )}
          {fromUpdate && planBlock}
        </section>
      )}

      {(list.data?.sources ?? []).length > 0 && (
        <section aria-label="Sources">
          <h2 className="mb-1 text-sm font-semibold text-slate-900">Sources</h2>
          <ul className="space-y-1 text-sm text-slate-700">
            {list.data!.sources.map((s) => (
              <li key={s.id}>
                <a href={s.repo.replace(/\.git$/, "")} className="font-medium text-sky-800 hover:underline" target="_blank"
                   rel="noreferrer">{s.repo.replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, "")}</a>{" "}
                <span className="font-mono text-xs">{s.ref ?? ""} @ {s.commit.slice(0, 12)}</span>
                <span className="text-xs text-slate-500">
                  {s.kind === "netbox-devicetype-library" ? ` · NetBox device types: ${(s.select ?? []).length} selected` : " · ARGUS collections"}
                </span>
                <SourceReleases source={s} />
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-slate-500">
            Read at exactly these commits. ARGUS ships its pins in <span className="font-mono">backend/catalogue/sources.lock.yaml</span>;
            a newer release of a source can be pinned here once the validator accepts it, and an ARGUS release that
            ships a newer one takes over.
          </p>
        </section>
      )}

      <CatalogueProposals />

      <table className="w-full rounded border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2"></th><th className="px-3 py-2">Collection</th><th className="px-3 py-2">Holds</th>
            <th className="px-3 py-2">Shipped</th><th className="px-3 py-2">Installed</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {(list.data?.collections ?? []).map((c) => (
            <tr key={c.id} className="align-top">
              <td className="px-3 py-2">
                <input type="checkbox" aria-label={`Choose ${c.name}`} checked={chosen.includes(c.id)}
                       disabled={c.problems.length > 0 || (!!c.installed_version && !c.upgrade_available)}
                       onChange={() => toggle(c.id)} />
              </td>
              <td className="px-3 py-2">
                <span className="font-medium text-slate-900">{c.name}</span>
                <span className="block font-mono text-xs text-slate-400">{c.id} · {c.owner} · {c.license}</span>
                {c.problems.length > 0 && (
                  <ul className="mt-1 text-xs text-red-700">{c.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                )}
              </td>
              <td className="px-3 py-2 text-slate-600">{c.summary}</td>
              <td className="px-3 py-2 font-mono">{c.version}</td>
              <td className="px-3 py-2 font-mono">
                {c.installed_version ?? <span className="font-sans text-slate-400">not installed</span>}
                {c.upgrade_available && <span className="block font-sans text-xs text-amber-700">upgrade available</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="rounded border border-slate-200 bg-white p-4">
        <div className="flex items-center gap-2">
          <button type="button" disabled={chosen.length === 0 || preview.isPending} onClick={() => preview.mutate()}
                  className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
            {preview.isPending ? "Working it out…" : plan ? "Preview again" : "Preview"}
          </button>
          <span className="text-xs text-slate-500">
            {chosen.length ? `${chosen.join(", ")} (and the collections they require)` : "Choose the collections to install or upgrade."}
          </span>
        </div>
        <details className="mt-2 text-xs text-slate-600">
          <summary className="cursor-pointer">Migrating existing records with a manifest</summary>
          <label className="mt-1 block">
            Migration manifest (optional):{" "}
            <input type="file" accept=".yaml,.yml" aria-label="Migration manifest"
                   onChange={async (e) => {
                     const f = e.target.files?.[0];
                     setManifest(f ? { name: f.name, text: await readText(f) } : null);
                     setPlan(null);
                   }} />
          </label>
          <span className="block text-slate-500">
            From <span className="font-mono">python -m app.catalogue export</span>: which existing record each
            entry is, the duplicates merged into it, and the references checked after the install.
            {manifest && <> Using <b>{manifest.name}</b>.</>}
          </span>
        </details>
        {preview.isError && <p className="mt-2 whitespace-pre-line text-sm text-red-600">{problem(preview.error)}</p>}
        {!fromUpdate && planBlock}
      </div>

      <section>
        <h2 className="mb-1 text-sm font-semibold text-slate-900">Waiting for review</h2>
        <CorrectionPatches />
        {(review.data ?? []).length === 0 ? <p className="text-sm text-slate-500">Nothing.</p> : (
          <ul className="space-y-1 text-sm">
            {review.data!.map((r) => (
              <li key={r.catalogue_id}>
                <Link to={`/catalogue/models/${r.record_uid}`} className="font-medium text-sky-800 hover:underline">{r.name}</Link>{" "}
                <span className="font-mono text-xs text-slate-500">{r.catalogue_id}</span>
                <span className="text-xs text-slate-600">
                  {Object.keys(r.conflicts).length > 0 && ` · release conflicts: ${Object.keys(r.conflicts).join(", ")}`}
                  {r.edited.length > 0 && ` · edited here: ${r.edited.join(", ")}`}
                  {Object.keys(r.corrections).length > 0 && ` · proposed to Git: ${Object.keys(r.corrections).join(", ")}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold text-slate-900">History</h2>
        <ul className="space-y-1 text-sm text-slate-600">
          {(list.data?.history ?? []).map((h, i) => (
            <li key={i}>
              <span className="text-slate-400">{h.installed_at ? new Date(h.installed_at).toLocaleString() : ""}</span>{" "}
              <span className="font-mono">{h.collection_id}</span> {h.from_version ? `${h.from_version} → ` : ""}
              <span className="font-mono">{h.version}</span>
              {h.result?.counts && Object.keys(h.result.counts).length > 0 &&
                ` — ${Object.entries(h.result.counts).map(([k, n]) => `${n} ${k}`).join(", ")}`}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
