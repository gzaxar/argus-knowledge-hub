import "leaflet/dist/leaflet.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LatLngBounds, Map as LeafletMap } from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, useMapEvents } from "react-leaflet";
import { GeoShape } from "../../lib/geo";
import { Link } from "react-router-dom";
import { MAP_TILES, placesApi, schemasApi, workspacesApi, type LocationImport, type MapFeature, type MapFilters } from "../../api/client";
import { useShowKeys } from "../../api/displayPrefs";
import { openInWorkspace } from "../../api/session";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

const LAYER_COLOURS: Record<string, string> = { equipment: "#2563eb", places: "#059669" };
const STATUSES = ["Active", "Provisional", "Retired"];
const ORDER = { outline: 0, route: 1, position: 2 } as const;
const RADII = [50, 200, 1000, 5000];
// LNF, Frascati: where the map opens before it knows better.
const START: [number, number] = [41.8217, 12.6726];

function Bounds({ onChange }: { onChange: (b: LatLngBounds, map: LeafletMap) => void }) {
  const map = useMapEvents({ moveend: () => onChange(map.getBounds(), map) });
  useEffect(() => onChange(map.getBounds(), map), []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** The records with a location, on a map: filtered by type, workspace and status, searched near a point,
 *  and the field observations waiting for review. Each marker opens its record. */
export function MapPage() {
  const here = useCurrentWorkspaceId();
  const showKeys = useShowKeys();
  const queryClient = useQueryClient();
  const [bbox, setBbox] = useState<[number, number, number, number] | null>(null);
  const [map, setMap] = useState<LeafletMap | null>(null);
  const [filters, setFilters] = useState<MapFilters>({});
  const [radius, setRadius] = useState(200);
  const [centre, setCentre] = useState<[number, number] | null>(null);

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: () => schemasApi.list() });
  const workspaces = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const layers = useQuery({ queryKey: ["map-layers", here], queryFn: placesApi.layers });
  const features = useQuery({
    queryKey: ["map-features", bbox, filters],
    queryFn: () => placesApi.features(bbox!, filters),
    enabled: bbox !== null,
    placeholderData: (prev) => prev,
  });
  const nearby = useQuery({
    queryKey: ["map-nearby", centre, radius, filters],
    queryFn: () => placesApi.nearby(centre![0], centre![1], radius, filters),
    enabled: centre !== null,
  });
  const reviews = useQuery({ queryKey: ["location-reviews", here], queryFn: () => placesApi.reviews() });
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) => placesApi.decide(id, accept),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["location-reviews"] });
      queryClient.invalidateQueries({ queryKey: ["map-features"] });
    },
  });

  const objectTypes = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "objects")
    .sort((a, b) => a.name.localeCompare(b.name)), [schemas.data]);
  const label = (f: MapFeature) => f.properties.name + (showKeys ? ` · ${f.properties.key}` : "");
  const open = (f: MapFeature, e?: React.MouseEvent) => {
    if (openInWorkspace(f.properties.workspace_id, `/assets/${f.properties.uid}`, here)) e?.preventDefault();
  };
  const toggle = (key: keyof MapFilters, value: string) => setFilters((cur) => {
    const list = cur[key] ?? [];
    const next = list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
    return { ...cur, [key]: next.length ? next : undefined };
  });

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] min-h-0">
      <aside className="w-80 shrink-0 space-y-4 overflow-y-auto border-r border-slate-200 bg-white p-4 text-sm">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Map</h1>
          <p className="text-xs text-slate-500">
            Records with an approved location — points, routes and outlines. {features.data && `${features.data.features.length} in view`}
            {features.data?.truncated && " (only the first 2000: zoom in)"}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500">Layers</p>
          {(layers.data ?? []).map((l) => (
            <p key={l.id} className="flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-full" style={{ background: LAYER_COLOURS[l.id] ?? "#64748b" }} />
              {l.name}
            </p>
          ))}
          {layers.data?.length === 0 && <p className="text-xs text-slate-500">This workspace's packages define none.</p>}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Type</p>
          <select multiple value={filters.types ?? []} size={5}
                  onChange={(e) => setFilters({ ...filters, types: Array.from(e.target.selectedOptions).map((o) => o.value) })}
                  className="mt-1 w-full rounded border border-slate-300 text-xs">
            {objectTypes.map((s) => <option key={s.uid} value={s.uid}>{s.name}</option>)}
          </select>
          <p className="text-[11px] text-slate-400">A type includes the types under it. None selected: all.</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Workspaces</p>
          {(workspaces.data ?? []).map((w) => (
            <label key={w.id} className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={filters.workspaces ? filters.workspaces.includes(w.id) : w.id === here}
                     onChange={() => toggle("workspaces", w.id)} />
              {w.name}
            </label>
          ))}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Status</p>
          {STATUSES.map((s) => (
            <label key={s} className="mr-3 inline-flex items-center gap-1 text-xs">
              <input type="checkbox" checked={!filters.status || filters.status.includes(s)}
                     onChange={() => toggle("status", s)} />
              {s}
            </label>
          ))}
        </div>
        <div className="space-y-2 border-t border-slate-100 pt-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Near a point</p>
          <div className="flex items-center gap-2">
            <select value={radius} onChange={(e) => setRadius(Number(e.target.value))}
                    className="rounded border border-slate-300 px-2 py-1 text-xs">
              {RADII.map((r) => <option key={r} value={r}>within {r < 1000 ? `${r} m` : `${r / 1000} km`}</option>)}
            </select>
            <button type="button" className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
                    onClick={() => map && setCentre([map.getCenter().lat, map.getCenter().lng])}>
              of the map's centre
            </button>
            {centre && <button type="button" className="text-xs text-slate-500 underline" onClick={() => setCentre(null)}>clear</button>}
          </div>
          {nearby.data && (
            <ul className="space-y-1">
              {nearby.data.features.length === 0 && <li className="text-xs text-slate-500">Nothing within that distance.</li>}
              {nearby.data.features.map((f) => (
                <li key={f.id} className="flex justify-between gap-2 text-xs">
                  <Link to={`/assets/${f.properties.uid}`} onClick={(e) => open(f, e)} className="truncate hover:underline">
                    {label(f)}
                  </Link>
                  <span className="shrink-0 text-slate-500">{Math.round(f.properties.distance_m ?? 0)} m</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <LocationImportBox onDone={() => {
          queryClient.invalidateQueries({ queryKey: ["map-features"] });
          queryClient.invalidateQueries({ queryKey: ["location-reviews"] });
        }} />
        <div className="space-y-2 border-t border-slate-100 pt-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Observed elsewhere: to review ({reviews.data?.length ?? 0})</p>
          {(reviews.data ?? []).map((o) => (
            <div key={o.id} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs">
              <Link to={`/assets/${o.subject_uid}`} className="font-medium hover:underline">{o.record?.name}</Link>
              <p className="text-slate-600">
                {o.approved ? `${Math.round(o.distance_m ?? 0)} m from its location` : "no location yet"}
                {o.accuracy_m != null && ` · ±${Math.round(o.accuracy_m)} m`}{o.observed_by && ` · by ${o.observed_by}`}
              </p>
              <div className="mt-1 flex gap-2">
                <button type="button" onClick={() => map?.setView([o.latitude, o.longitude], 18)} className="underline">show</button>
                <button type="button" onClick={() => decide.mutate({ id: o.id, accept: true })} className="text-emerald-700 underline">accept</button>
                <button type="button" onClick={() => decide.mutate({ id: o.id, accept: false })} className="text-red-700 underline">reject</button>
              </div>
            </div>
          ))}
        </div>
      </aside>
      <div className="relative min-w-0 flex-1">
        <MapContainer center={START} zoom={16} className="h-full w-full" ref={setMap}>
          <TileLayer url={MAP_TILES.url} attribution={MAP_TILES.attribution} maxZoom={20} />
          <Bounds onChange={(b) => setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()])} />
          {centre && <Circle center={centre} radius={radius} pathOptions={{ color: "#f59e0b", fillOpacity: 0.05 }} />}
          {/* Areas under lines under points, so every point stays clickable. */}
          {[...(features.data?.features ?? [])].sort((a, b) => ORDER[a.properties.role] - ORDER[b.properties.role]).map((f) => {
            const colour = LAYER_COLOURS[f.properties.map_layer ?? ""] ?? "#64748b";
            const style = f.properties.role === "position"
              ? { color: "#fff", weight: 2, fillOpacity: 0.9, fillColor: colour }
              : { color: colour };
            return (
              <GeoShape key={f.id} geometry={f.geometry} style={style}>
                <Popup>
                  <p className="font-medium">{label(f)}</p>
                  <p className="text-xs text-slate-500">{f.properties.type} · {f.properties.status}
                    {f.properties.role !== "position" && ` · its ${f.properties.role}`}
                    {f.properties.base_m != null && f.properties.top_m != null && ` · ${f.properties.base_m}–${f.properties.top_m} m`}
                    {f.properties.accuracy_m != null && ` · ±${Math.round(f.properties.accuracy_m)} m`}</p>
                  <Link to={`/assets/${f.properties.uid}`} onClick={(e) => open(f, e)}>Open</Link>
                </Popup>
              </GeoShape>
            );
          })}
          {(reviews.data ?? []).map((o) => (
            <CircleMarker key={`o${o.id}`} center={[o.latitude, o.longitude]} radius={6}
                          pathOptions={{ color: "#f59e0b", dashArray: "3", fillOpacity: 0.2 }}>
              <Popup>Observed position of {o.record?.name}, to review</Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </div>
    </div>
  );
}


const OUTCOMES: Record<string, string> = {
  set: "location set", consistent: "agrees with its location", to_review: "differs: to review", rejected: "refused",
};

/** Locations from a survey or another system: previewed row by row, then applied. A record that already has a
 *  location is never moved by a file: a different position waits for review. */
function LocationImportBox({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<LocationImport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => placesApi.importLocations(file!, dryRun),
    onSuccess: (r) => { setPreview(r); setError(null); if (!r.dry_run) onDone(); },
    onError: (e) => setError(String((e as { body?: { detail?: { error?: string } } }).body?.detail?.error ?? e)),
  });
  return (
    <div className="space-y-2 border-t border-slate-100 pt-3">
      <p className="text-xs font-semibold uppercase text-slate-500">Import locations</p>
      <p className="text-[11px] text-slate-400">CSV (key or label, latitude, longitude, accuracy_m) or GeoJSON, in WGS 84: points,
        lines (routes) and polygons (outlines, with base_m and top_m for a volume). A record&apos;s route or outline is
        never replaced by a file.</p>
      <input type="file" accept=".csv,.json,.geojson" className="text-xs"
             onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
      <div className="flex gap-2">
        <button type="button" disabled={!file || run.isPending} onClick={() => run.mutate(true)}
                className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50">Preview</button>
        {preview?.dry_run && (preview.counts.set + preview.counts.to_review + preview.counts.consistent) > 0 && (
          <button type="button" disabled={run.isPending} onClick={() => run.mutate(false)}
                  className="rounded bg-slate-900 px-2 py-1 text-xs text-white">Apply</button>
        )}
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {preview && (
        <div className="text-xs">
          <p className="font-medium">{preview.dry_run ? "Would do" : "Done"}: {preview.counts.set} set ·{" "}
            {preview.counts.consistent} agree · {preview.counts.to_review} to review · {preview.counts.rejected} refused</p>
          <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto">
            {preview.rows.filter((r) => r.outcome !== "set" && r.outcome !== "consistent").map((r) => (
              <li key={r.row} className={r.outcome === "rejected" ? "text-red-700" : "text-amber-700"}>
                row {r.row} ({r.identifier || "—"}): {OUTCOMES[r.outcome]}{r.problem ? ` — ${r.problem}` : ""}
                {r.distance_m != null && ` (${Math.round(r.distance_m)} m away)`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
