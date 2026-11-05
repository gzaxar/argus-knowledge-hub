import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { catalogueCollectionsApi, workspacesApi, type CatalogueFieldDecision, type CatalogueRecordField } from "../../api/client";
import { ProposeModel } from "./CatalogueGit";
import { LinkToSource } from "./LinkToSource";
import { problem, shown, SourceBadge } from "./catalogueText";

/** What a person may say about one field of a catalogue entry, given where its value comes from now. */
function choices(f: CatalogueRecordField): { decision: CatalogueFieldDecision; label: string }[] {
  if (f.source === "record") return [];
  const back = { decision: "managed" as const, label: f.conflict ? "Take the release's value" : "Use the collection's value" };
  const local = { decision: "local" as const, label: "Keep as a local override" };
  const propose = { decision: "propose" as const, label: "Propose this value to Git" };
  switch (f.source) {
    case "edited": return [local, propose, back];
    case "local": return f.conflict ? [back, local] : [{ decision: "managed", label: "Let the collection manage it" }, propose];
    case "correction": return [{ decision: "managed", label: "Withdraw: use the collection's value" }];
    default: return [];
  }
}

/** A catalogue record: each value with where it comes from, the decisions on it, and what uses it. */
export function CatalogueModelPage() {
  const { uid = "" } = useParams();
  const queryClient = useQueryClient();
  const page = useQuery({ queryKey: ["catalogue-record", uid], queryFn: () => catalogueCollectionsApi.record(uid) });
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const decide = useMutation({
    mutationFn: (v: { field: string; decision: CatalogueFieldDecision }) =>
      catalogueCollectionsApi.decideField(page.data!.entry!.catalogue_id, v.field, v.decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["catalogue-record", uid] });
      queryClient.invalidateQueries({ queryKey: ["catalogue-review"] });
    },
  });

  if (page.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (page.isError || !page.data) return <p className="text-sm text-red-600">{problem(page.error)}</p>;
  const r = page.data;
  const entry = r.entry;

  return (
    <div className="max-w-4xl space-y-5">
      <div>
        <Link to="/catalogue/models" className="text-xs text-sky-800 hover:underline">← Product catalogue</Link>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">{r.name}</h1>
        <p className="mt-1 text-sm text-slate-500">
          <span className="font-mono">{r.key}</span> · {r.type} ·{" "}
          <Link to={`/assets/${r.uid}`} className="text-sky-800 hover:underline">Open the record</Link>
        </p>
        {entry ? (
          <p className="mt-2 text-sm text-slate-700">
            Catalogue id <span className="font-mono">{entry.catalogue_id}</span>, from the collection{" "}
            <b>{entry.collection_id}</b> {entry.collection_version}
            {entry.shipped_version && <span className="text-amber-700"> ({entry.shipped_version} is available)</span>}
            {entry.adopted_at && <> · adopted {new Date(entry.adopted_at).toLocaleDateString()}</>}
            {entry.status === "transferring" && <> · moving to another collection</>}
          </p>
        ) : (
          <p className="mt-2 text-sm text-slate-700">
            A local record: no collection states it. It can be proposed for one through a Git review.
          </p>
        )}
        {!entry && r.kind === "model" && (me.data?.is_admin || me.data?.catalogue_maintainer) && (
          <div className="mt-3 space-y-2">
            <LinkToSource uid={r.uid} initial={String(r.fields.find((f) => f.field === "model_code")?.value ?? r.name)} />
            <p className="text-xs text-slate-500">Not in the sources? Propose it, with the document its values were checked against.</p>
            <ProposeModel uid={r.uid} />
          </div>
        )}
        {r.retired && (
          <p role="status" className="mt-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-900">
            Retired since {r.retired.since}: {r.retired.reason}
            {r.retired.replaced_by && <> — replaced by <span className="font-mono">{r.retired.replaced_by}</span></>}.
            It stays in the catalogue while units are of it.
          </p>
        )}
      </div>

      <table className="w-full rounded border border-slate-200 bg-white text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2">Field</th><th className="px-3 py-2">Value</th><th className="px-3 py-2">Source</th>
            <th className="px-3 py-2"></th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {r.fields.map((f) => (
            <tr key={f.field} className="align-top">
              <td className="px-3 py-2 text-slate-500">{f.label}</td>
              <td className="px-3 py-2 break-all">
                {shown(f.value)}
                {(f.source === "edited" || f.source === "local" || f.source === "correction") && f.collection_value !== undefined
                  && f.field !== "vendor" && (
                  <span className="block text-xs text-slate-500">The collection says: {shown(f.collection_value)}</span>
                )}
                {f.conflict && (
                  <span className="block text-xs text-amber-800">
                    Release {f.conflict.version} says {shown(f.conflict.release)}; this record kept its value.
                  </span>
                )}
              </td>
              <td className="px-3 py-2"><SourceBadge source={f.source} /></td>
              <td className="px-3 py-2">
                <div className="flex flex-wrap gap-1">
                  {entry && choices(f).map((c) => (
                    <button key={c.decision} type="button" disabled={decide.isPending}
                            onClick={() => decide.mutate({ field: f.field, decision: c.decision })}
                            className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50">
                      {c.label}
                    </button>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {decide.isError && <p className="whitespace-pre-line text-sm text-red-600">{problem(decide.error)}</p>}

      {Object.keys(r.stated_only).length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Also in the collection</h2>
          <p className="text-xs text-slate-500">Kept in the collection until the Product Model type has fields for them.</p>
          <dl className="mt-1 grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 text-sm">
            {Object.entries(r.stated_only).map(([k, v]) => (
              k === "specifications" && v && typeof v === "object"
                ? Object.entries(v as Record<string, unknown>).map(([sk, sv]) => (
                    <div key={sk} className="contents"><dt className="text-slate-500">{sk.replace(/_/g, " ")}</dt>
                      <dd>{shown(sv)}</dd></div>))
                : <div key={k} className="contents"><dt className="text-slate-500">{k.replace(/_/g, " ")}</dt><dd>{shown(v)}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {r.relations.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Related models</h2>
          <ul className="mt-1 text-sm">
            {r.relations.map((x) => <li key={`${x.verb}:${x.model}`}>{x.verb.replace(/-/g, " ")} <span className="font-mono">{x.model}</span></li>)}
          </ul>
        </section>
      )}

      {r.kind === "model" && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Units of this model</h2>
          {r.units.length === 0 ? <p className="text-sm text-slate-500">None.</p> : (
            <ul className="mt-1 text-sm">
              {r.units.map((u) => <li key={u.workspace_id ?? "hidden"}>{u.name}: {u.count}</li>)}
            </ul>
          )}
        </section>
      )}

      {r.sources.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Sources</h2>
          <ul className="mt-1 text-sm text-slate-700">
            {r.sources.map((s, i) => (
              <li key={i}>{s.kind}{s.ref && <>: <span className="break-all">{s.ref}</span></>}
                {s.revision && <span className="font-mono text-xs"> @{s.revision}</span>}
                {s.checked && <span className="text-xs text-slate-500"> (checked {s.checked})</span>}</li>
            ))}
          </ul>
        </section>
      )}

      {r.releases.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-900">Releases of {entry?.collection_id}</h2>
          <ul className="mt-1 text-sm text-slate-600">
            {r.releases.map((h, i) => (
              <li key={i}>{h.from_version ? `${h.from_version} → ` : ""}<span className="font-mono">{h.version}</span>
                {h.installed_at && <> · {new Date(h.installed_at).toLocaleString()}</>}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
