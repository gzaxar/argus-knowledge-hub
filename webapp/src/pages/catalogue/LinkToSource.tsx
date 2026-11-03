import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { catalogueCollectionsApi } from "../../api/client";
import { problem } from "./catalogueText";

/** A model made by hand, found in the catalogue's sources (the NetBox library among them) and linked to it: its
 *  empty fields — part number, height, weight, ports, every component — filled from the source, the values it
 *  has kept. The catalogue's maintainers. */
export function LinkToSource({ uid, initial }: { uid: string; initial: string }) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState(initial);
  const found = useQuery({
    queryKey: ["catalogue-sources-search", q],
    queryFn: () => catalogueCollectionsApi.searchSources(q),
    enabled: q.trim().length >= 2,
  });
  const link = useMutation({
    mutationFn: (catalogueId: string) => catalogueCollectionsApi.link(catalogueId, uid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["catalogue-record", uid] });
      queryClient.invalidateQueries({ queryKey: ["asset", uid] });
    },
  });
  const hits = found.data?.library ?? [];
  return (
    <section className="rounded border border-slate-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-900">Find it in the catalogue's sources</h2>
      <p className="mt-1 text-xs text-slate-500">
        Linked to the same model in a source (a NetBox device type), its empty fields are filled — part number,
        height, weight, ports, every component — and kept up to date with the source; the values it has stay.
      </p>
      <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the sources"
             className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm" placeholder="Model code or name" />
      {found.isError && <p className="mt-2 text-xs text-red-600">{problem(found.error)}</p>}
      {q.trim().length >= 2 && found.isSuccess && hits.length === 0 && (
        <p className="mt-2 text-xs text-slate-500">No model of the sources matches.</p>
      )}
      <ul className="mt-2 divide-y divide-slate-100 text-sm">
        {hits.map((h) => (
          <li key={h.catalogue_id} className="flex items-center justify-between gap-3 py-1.5">
            <span>
              {h.name}
              <span className="ml-2 text-xs text-slate-500">
                {h.part_number && <>{h.part_number} · </>}{h.source === "netbox" ? "NetBox" : h.collection}
              </span>
            </span>
            <button type="button" disabled={link.isPending} onClick={() => link.mutate(h.catalogue_id)}
                    className="rounded border border-sky-700 px-2 py-0.5 text-xs text-sky-800 hover:bg-sky-50 disabled:opacity-50">
              Link to this one
            </button>
          </li>
        ))}
      </ul>
      {link.isError && <p role="alert" className="mt-2 text-xs text-red-600">{problem(link.error)}</p>}
      {link.isSuccess && (
        <p role="status" className="mt-2 text-xs text-emerald-800">
          Linked{link.data.filled.length ? `: filled ${link.data.filled.join(", ")}` : ""}.
        </p>
      )}
    </section>
  );
}
