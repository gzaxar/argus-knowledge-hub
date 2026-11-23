import "leaflet/dist/leaflet.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { geoJSON, type LatLngBounds, type Map as LeafletMap } from "leaflet";
import { useEffect, useMemo, useState } from "react";
import { Circle, CircleMarker, MapContainer, Popup, TileLayer, useMapEvents } from "react-leaflet";
import { GeoShape } from "../../lib/geo";
import { AffineImage } from "../../lib/affineOverlay";
import { usePlanImage } from "../../components/PlanView";
import { indoorApi, type FloorPlanView } from "../../api/client";
import { Link, useSearchParams } from "react-router-dom";
import { ViewSwitch } from "../../components/browse/Browse";
import { MAP_TILES, placesApi, schemasApi, workspacesApi, type LocationImport, type MapFeature, type MapFilters } from "../../api/client";
import { useShowKeys } from "../../api/displayPrefs";
import { openInWorkspace } from "../../api/session";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

const LAYER_COLOURS: Record<string, string> = { equipment: "#2563eb", places: "#059669" };
const STATUSES = ["Active", "Provisional", "Retired"];
const ORDER = { outline: 0, route: 1, position: 2 } as const;
const HIDDEN_LAYERS = "argus.map-hidden-layers";

/** The site a workspace belongs to: itself when it is a site, its site when it is a facility at one. */
export const siteOf = (w?: { id: string; role?: string | null; site_id?: string | null } | null) =>
  !w ? null : w.role === "site" ? w.id : w.site_id ?? null;

/** Located records whose name, key or type has every word typed, the best first: a name that starts with them. */
export function findOnMap(features: MapFeature[], text: string, limit = 30): MapFeature[] {
  const words = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const seen = new Set<string>();
  const hits = features.filter((f) => {
    if (seen.has(f.properties.uid)) return false;
    const t = `${f.properties.name} ${f.properties.key} ${f.properties.type}`.toLowerCase();
    if (!words.every((w) => t.includes(w))) return false;
    seen.add(f.properties.uid);
    return true;
  });
  const starts = (f: MapFeature) => (f.properties.name.toLowerCase().startsWith(words[0]) ? 0 : 1);
  return hits.sort((a, b) => starts(a) - starts(b) || a.properties.name.localeCompare(b.properties.name)).slice(0, limit);
}
const RADII = [50, 200, 1000, 5000];
// LNF, Frascati: where the map opens when the workspace has nothing located yet.
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
  // Opened from the Assets list (`?types=`): the same type filter, so List and Map show the same records.
  const [params] = useSearchParams();
  const [filters, setFilters] = useState<MapFilters>(() => {
    const t = params.get("types");
    return t ? { types: t.split(",").filter(Boolean) } : {};
  });
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
  // Open on where the shown workspaces' records are: this workspace's at first, and again whenever the workspaces
  // shown change (ticking another one goes to it); otherwise the view is the person's.
  const shownWorkspaces = filters.workspaces ?? (here ? [here] : []);
  const extentKey = shownWorkspaces.join(",");
  const extent = useQuery({ queryKey: ["map-extent", extentKey],
                            queryFn: () => placesApi.extent(filters.workspaces) });
  const [framed, setFramed] = useState<string | null>(null);
  useEffect(() => {
    const box = extent.data?.bbox;
    if (!map || framed === extentKey || !extent.isFetched || extent.isFetching) return;
    setFramed(extentKey);
    if (box) map.fitBounds([[box[1], box[0]], [box[3], box[2]]], { padding: [24, 24], maxZoom: 18 });
  }, [map, framed, extentKey, extent.isFetched, extent.isFetching, extent.data]);
  // Indoors: the plans placed on the map in view, by floor (every building's floor of the same order together).
  const plans = useQuery({ queryKey: ["map-plans", bbox], queryFn: () => indoorApi.mapPlans(bbox!), enabled: bbox !== null,
                           placeholderData: (prev) => prev });
  const [floor, setFloor] = useState<string>("");
  const floorOf = (p: FloorPlanView) => (p.level ? String(p.level.ordinal) : "whole");
  const floors = useMemo(() => {
    const seen = new Map<string, Set<string>>();
    for (const p of plans.data ?? []) {
      const k = floorOf(p);
      if (!seen.has(k)) seen.set(k, new Set());
      seen.get(k)!.add(p.level?.name ?? "plans of whole places");
    }
    return [...seen.entries()].sort(([a], [b]) => (a === "whole" ? 1e9 : Number(a)) - (b === "whole" ? 1e9 : Number(b)));
  }, [plans.data]);
  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) => placesApi.decide(id, accept),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["location-reviews"] });
      queryClient.invalidateQueries({ queryKey: ["map-features"] });
    },
  });

  // The workspaces whose records may be shown with these: those of the same site (the site and its facilities).
  const current = (workspaces.data ?? []).find((w) => w.id === here);
  const site = siteOf(current);
  const siteWorkspaces = (workspaces.data ?? []).filter((w) => w.id === here || (site != null && siteOf(w) === site));
  // Layers turned off on this map (remembered here).
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(HIDDEN_LAYERS) ?? "[]") as string[]); } catch { return new Set(); }
  });
  const toggleLayer = (id: string) => setHidden((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    try { localStorage.setItem(HIDDEN_LAYERS, JSON.stringify([...next])); } catch { /* not remembered */ }
    return next;
  });
  // Everything located in the workspaces shown (their whole extent), to find a record and go to it.
  const everything = useQuery({
    queryKey: ["map-everything", extentKey, filters.types, filters.status],
    queryFn: () => placesApi.features(extent.data!.bbox!, filters),
    enabled: !!extent.data?.bbox,
  });
  const [find, setFind] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  const focusOn = (f: MapFeature) => {
    if (!map) return;
    const box = geoJSON(f.geometry as never).getBounds();
    if (f.geometry.type === "Point") map.setView(box.getCenter(), Math.max(map.getZoom(), 19));
    else map.fitBounds(box, { padding: [40, 40], maxZoom: 19 });
    setFocus(f.properties.uid);
  };
  // `?focus=<uid>` (a record's "On the site map"): go to it once it is found.
  const wanted = params.get("focus");
  const [wentTo, setWentTo] = useState<string | null>(null);
  useEffect(() => {
    if (!wanted || wentTo === wanted || !map || !everything.data) return;
    const hit = everything.data.features.filter((f) => f.properties.uid === wanted)
      .sort((a, b) => ORDER[b.properties.role] - ORDER[a.properties.role])[0];
    if (hit) { setWentTo(wanted); setFramed(extentKey); focusOn(hit); }
  }, [wanted, wentTo, map, everything.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const found = useMemo(() => findOnMap(everything.data?.features ?? [], find), [everything.data, find]);
  // A layer this workspace has nothing on is not offered, unless another workspace shown has something on it here.
  const inView = useMemo(() => new Set((features.data?.features ?? []).map((f) => f.properties.map_layer ?? "")),
                         [features.data]);
  // The building (or hall, or room) gone to: its floor plans, to open or lay on the map.
  const focusedInside = useMemo(() => (plans.data ?? []).filter((p) => p.place.uid === focus)
    .sort((a, b) => (a.level?.ordinal ?? 0) - (b.level?.ordinal ?? 0)), [plans.data, focus]);
  const focusedName = everything.data?.features.find((f) => f.properties.uid === focus)?.properties.name ?? "";

  const objectTypes = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "objects")
    .sort((a, b) => a.name.localeCompare(b.name)), [schemas.data]);
  // Two types of the same name (this workspace's and a shared one) are told apart by where they come from.
  const typeLabel = useMemo(() => {
    const count = new Map<string, number>();
    for (const s of objectTypes) count.set(s.name, (count.get(s.name) ?? 0) + 1);
    return (s: (typeof objectTypes)[number]) =>
      (count.get(s.name) ?? 0) > 1 ? `${s.name} (${s.workspace_id === here ? "this workspace" : s.workspace_id ?? "shared"})` : s.name;
  }, [objectTypes, here]);
  const label = (f: MapFeature) => f.properties.name + (showKeys ? ` · ${f.properties.key}` : "");
  const open = (f: MapFeature, e?: React.MouseEvent) => {
    if (openInWorkspace(f.properties.workspace_id, `/assets/${f.properties.uid}`, here)) e?.preventDefault();
  };
  const toggle = (key: keyof MapFilters, value: string) => setFilters((cur) => {
    // The workspaces start from the current one, shown by default: ticking another adds it, it does not replace it.
    const list = cur[key] ?? (key === "workspaces" && here ? [here] : []);
    const next = list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
    return { ...cur, [key]: next.length ? next : undefined };
  });

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] min-h-0">
      <aside className="w-80 shrink-0 space-y-4 overflow-y-auto border-r border-slate-200 bg-white p-4 text-sm">
        <div>
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-xl font-semibold text-slate-900">Map</h1>
            <ViewSwitch views={[
              { label: "List", to: `/assets/search${filters.types?.length === 1 ? `?type=${encodeURIComponent(filters.types[0])}` : ""}`, current: false },
              { label: "Map", to: "/map", current: true },
            ]} />
          </div>
          <p className="text-xs text-slate-500">
            Records with an approved location — points, routes and outlines. {features.data && `${features.data.features.length} in view`}
            {features.data?.truncated && " (only the first 2000: zoom in)"}
          </p>
        </div>
        <div className="space-y-1">
          <p className="text-xs font-semibold uppercase text-slate-500">Layers</p>
          {(layers.data ?? []).filter((l) => l.count !== 0 || inView.has(l.id)).map((l) => (
            <button key={l.id} type="button" aria-pressed={!hidden.has(l.id)} onClick={() => toggleLayer(l.id)}
                    title={hidden.has(l.id) ? "Show this layer" : "Hide this layer"}
                    className={`flex w-full items-center gap-2 rounded px-1 text-left hover:bg-slate-50 ${hidden.has(l.id) ? "text-slate-400 line-through" : ""}`}>
              <span className="inline-block h-3 w-3 rounded-full" style={{ background: hidden.has(l.id) ? "#cbd5e1" : LAYER_COLOURS[l.id] ?? "#64748b" }} />
              {l.name}
            </button>
          ))}
          {(layers.data?.length ?? 0) > 0 && <p className="text-[11px] text-slate-400">Click a layer to hide or show it.</p>}
          {layers.data?.length === 0 && <p className="text-xs text-slate-500">This workspace's packages define none.</p>}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Find on the map</p>
          <input type="search" value={find} onChange={(e) => setFind(e.target.value)} aria-label="Find on the map"
                 placeholder="A building, a room, a rack, a key…" className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs" />
          {find.trim() && (
            <ul className="mt-1 max-h-56 space-y-0.5 overflow-y-auto">
              {found.length === 0 && <li className="text-xs text-slate-500">{everything.isLoading ? "Looking…" : "Nothing located matches."}</li>}
              {found.map((f) => (
                <li key={f.properties.uid}>
                  <button type="button" onClick={() => focusOn(f)}
                          className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-slate-100">
                    <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ background: LAYER_COLOURS[f.properties.map_layer ?? ""] ?? "#64748b" }} />
                    <span className="truncate">{label(f)}</span>
                    <span className="ml-auto shrink-0 text-slate-400">{f.properties.type}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {focusedInside.length > 0 && (
          <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-xs" aria-label="Inside">
            <p className="font-semibold text-emerald-900">Inside {focusedName}</p>
            <ul className="mt-1 space-y-0.5">
              {focusedInside.map((p) => (
                <li key={p.uid} className="flex items-center gap-2">
                  <Link to={`/plans/${p.uid}`} className="text-indigo-700 hover:underline">{p.level?.name ?? p.name}</Link>
                  {p.corners && <button type="button" onClick={() => setFloor(floorOf(p))}
                                        className="text-slate-600 underline">on the map</button>}
                </li>
              ))}
            </ul>
          </div>
        )}
        <details>
          <summary className="cursor-pointer text-xs font-semibold uppercase text-slate-500">Filter by type
            {filters.types?.length ? ` (${filters.types.length})` : ""}</summary>
          <select multiple aria-label="Types to show" value={filters.types ?? []} size={5}
                  onChange={(e) => setFilters({ ...filters, types: Array.from(e.target.selectedOptions).map((o) => o.value) })}
                  className="mt-1 w-full rounded border border-slate-300 text-xs">
            {objectTypes.map((s) => <option key={s.uid} value={s.uid}>{typeLabel(s)}</option>)}
          </select>
          <p className="text-[11px] text-slate-400">A type includes the types under it. None selected: all.</p>
        </details>
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Workspaces</p>
          <p className="text-[11px] text-slate-400">
            {site ? "This workspace is shown; tick the others of its site to show theirs too (the map moves to take them in)."
                  : "This workspace belongs to no site: only its own records are shown."}</p>
          {siteWorkspaces.map((w) => (
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
        <div className="space-y-1 border-t border-slate-100 pt-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Indoors</p>
          {floors.length === 0 ? (
            <p className="text-[11px] text-slate-400">No floor plan placed on the map here.</p>
          ) : (
            <select value={floor} onChange={(e) => setFloor(e.target.value)} aria-label="Floor"
                    className="w-full rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="">Outdoors: no plan</option>
              {floors.map(([k, names]) => (
                <option key={k} value={k}>{k === "whole" ? "" : `Floor ${k}: `}{[...names].join(", ")}</option>
              ))}
            </select>
          )}
        </div>
        <div className="space-y-2 border-t border-slate-100 pt-3">
          <p className="text-xs font-semibold uppercase text-slate-500">Near a point</p>
          <div className="flex items-center gap-2">
            <select aria-label="Distance" value={radius} onChange={(e) => setRadius(Number(e.target.value))}
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
          {floor && (plans.data ?? []).filter((p) => floorOf(p) === floor && p.corners).map((p) => <PlanOverlay key={p.uid} plan={p} />)}
          {/* Areas under lines under points, so every point stays clickable. */}
          {[...(features.data?.features ?? [])].filter((f) => !hidden.has(f.properties.map_layer ?? ""))
            .sort((a, b) => ORDER[a.properties.role] - ORDER[b.properties.role]).map((f) => {
            const colour = LAYER_COLOURS[f.properties.map_layer ?? ""] ?? "#64748b";
            const lit = focus === f.properties.uid;
            const style = f.properties.role === "position"
              ? { color: lit ? "#f59e0b" : "#fff", weight: lit ? 4 : 2, fillOpacity: 0.9, fillColor: colour }
              : { color: lit ? "#f59e0b" : colour, weight: lit ? 4 : 3 };
            // A building or a room with floor plans: what is inside, plan by plan.
            const inside = (plans.data ?? []).filter((p) => p.place.uid === f.properties.uid);
            return (
              <GeoShape key={f.id} geometry={f.geometry} style={style}>
                <Popup>
                  <p className="font-medium">{label(f)}</p>
                  <p className="text-xs text-slate-500">{f.properties.type} · {f.properties.status}
                    {f.properties.role !== "position" && ` · its ${f.properties.role}`}
                    {f.properties.base_m != null && f.properties.top_m != null && ` · ${f.properties.base_m}–${f.properties.top_m} m`}
                    {f.properties.accuracy_m != null && ` · ±${Math.round(f.properties.accuracy_m)} m`}</p>
                  <Link to={`/assets/${f.properties.uid}`} onClick={(e) => open(f, e)}>Open</Link>
                  {inside.length > 0 && (
                    <div className="mt-2 border-t border-slate-200 pt-1 text-xs" data-inside="">
                      <p className="font-medium text-slate-700">Inside: {inside.length === 1 ? "a floor plan" : `${inside.length} floor plans`}</p>
                      <ul>
                        {[...inside].sort((a, b) => (a.level?.ordinal ?? 0) - (b.level?.ordinal ?? 0)).map((p) => (
                          <li key={p.uid}>
                            <Link to={`/plans/${p.uid}`}>{p.level?.name ?? p.name}</Link>
                            {p.corners && <button type="button" className="ml-2 text-slate-500 underline"
                                                  onClick={() => setFloor(floorOf(p))}>on the map</button>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
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


/** A floor plan laid on the map where its control points place it. */
function PlanOverlay({ plan }: { plan: FloorPlanView }) {
  const image = usePlanImage(plan.uid);
  if (!image.data || !plan.corners) return null;
  return <AffineImage url={image.data} width={plan.width_px} height={plan.height_px} corners={plan.corners} />;
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
      <input type="file" aria-label="Import points (CSV or GeoJSON)" accept=".csv,.json,.geojson" className="text-xs"
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
