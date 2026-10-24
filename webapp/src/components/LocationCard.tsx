import "leaflet/dist/leaflet.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CircleMarker, MapContainer, Polygon, Polyline, TileLayer, useMapEvents } from "react-leaflet";
import { Link } from "react-router-dom";
import { ApiError, MAP_TILES, placesApi, type PlaceNeighbour, type PlacedFeature } from "../api/client";
import { FitTo, GeoShape, drawnGeometry, fmtArea, fmtLength, parseGeometry, pointsOf, type LatLng } from "../lib/geo";

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
  }
  return "It could not be saved.";
}

function Picker({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

type PointDraft = { kind: "position"; lat: string; lon: string; acc: string };
type ShapeDraft = { kind: "route" | "outline"; points: LatLng[]; base: string; top: string; pasted: string };

const STYLE = {
  position: { color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 0.9 },
  route: { color: "#7c3aed" },
  outline: { color: "#059669" },
};
const SOURCE = (f: PlacedFeature) =>
  (f.source === "field" ? "from the field" : f.source === "import" ? "imported" : "set by hand")
  + (f.confirmed_by ? ` by ${f.confirmed_by}` : "") + (f.reviewer ? `, accepted by ${f.reviewer}` : "")
  + (f.confirmed_at ? ` · ${new Date(f.confirmed_at).toLocaleDateString()}` : "");

/** Where a record is: its position (a point), its route (a line: a cable, a pipe) and its outline (an area: a
 *  building, hall, room or zone — with heights, a volume), on a small map; setting them (typed, clicked or drawn
 *  on the map, or pasted as GeoJSON); their history; the field observations waiting for review; and what the
 *  shapes say about the others — what is inside it, what crosses it, what it is in. Shown for types their
 *  package places on the map. */
export function LocationCard({ uid, editable }: { uid: string; editable: boolean }) {
  const queryClient = useQueryClient();
  const loc = useQuery({ queryKey: ["asset-location", uid], queryFn: () => placesApi.location(uid), retry: false });
  const [draft, setDraft] = useState<PointDraft | ShapeDraft | null>(null);
  const l = loc.data;
  const placed = !!(l && (l.location || l.route || l.outline));
  const ctx = useQuery({ queryKey: ["asset-location-context", uid], queryFn: () => placesApi.context(uid),
                         enabled: placed && !l?.hidden, retry: false });
  const done = () => {
    setDraft(null);
    for (const k of ["asset-location", "asset-location-context", "asset-history"]) queryClient.invalidateQueries({ queryKey: [k, uid] });
  };
  const save = useMutation({
    mutationFn: async () => {
      const d = draft!;
      if (d.kind === "position") {
        return placesApi.setLocation(uid, { latitude: Number(d.lat), longitude: Number(d.lon),
                                            ...(d.acc ? { accuracy_m: Number(d.acc) } : {}) });
      }
      const pasted = d.pasted.trim() ? parseGeometry(d.pasted) : null;
      if (typeof pasted === "string") throw new Error(pasted);
      return placesApi.setShape(uid, d.kind, {
        geometry: pasted ?? drawnGeometry(d.kind, d.points),
        ...(d.kind === "outline" ? { base_m: d.base === "" ? null : Number(d.base), top_m: d.top === "" ? null : Number(d.top) } : {}),
      });
    },
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: (role: "route" | "outline") => placesApi.removeShape(uid, role), onSuccess: done });
  const decide = useMutation({ mutationFn: ({ id, accept }: { id: number; accept: boolean }) => placesApi.decide(id, accept),
                               onSuccess: done });
  if (!l || !l.locatable) return null;
  const here = l.location;
  const pending = l.observations.filter((o) => o.status === "pending");
  const shapeDraft = draft && draft.kind !== "position" ? draft : null;
  const fit = [here, l.route, l.outline].flatMap((f) => (f ? pointsOf(f.geometry) : []));
  const minimum = shapeDraft ? (shapeDraft.kind === "route" ? 2 : 3) : 0;
  const startShape = (kind: "route" | "outline") => {
    const f = kind === "outline" ? l.outline : null;
    setDraft({ kind, points: [], base: f?.base_m != null ? String(f.base_m) : "", top: f?.top_m != null ? String(f.top_m) : "", pasted: "" });
  };

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Location</h2>
        {l.map_layer && <span className="text-xs text-slate-500">map layer: {l.map_layer}</span>}
      </div>
      {l.hidden ? (
        <p className="mt-2 text-sm text-slate-500">Its location is restricted.</p>
      ) : (
        <div className="mt-2 grid gap-4 md:grid-cols-2">
          <div className={`${shapeDraft ? "h-80" : "h-56"} overflow-hidden rounded border border-slate-200`}>
            <MapContainer center={[41.8217, 12.6726]} zoom={15} className="h-full w-full">
              <TileLayer url={MAP_TILES.url} attribution={MAP_TILES.attribution} maxZoom={20} />
              <FitTo points={fit} />
              {l.outline && <GeoShape geometry={l.outline.geometry} style={STYLE.outline} />}
              {l.route && <GeoShape geometry={l.route.geometry} style={STYLE.route} />}
              {here && <GeoShape geometry={here.geometry} style={STYLE.position} />}
              {pending.map((o) => (
                <CircleMarker key={o.id} center={[o.latitude, o.longitude]} radius={6}
                              pathOptions={{ color: "#f59e0b", dashArray: "3", fillOpacity: 0.2 }} />
              ))}
              {draft?.kind === "position" && draft.lat && draft.lon && !Number.isNaN(Number(draft.lat)) && (
                <CircleMarker center={[Number(draft.lat), Number(draft.lon)]} radius={8} pathOptions={{ color: "#16a34a", fillOpacity: 0.5 }} />
              )}
              {shapeDraft && shapeDraft.points.length > 0 && (shapeDraft.kind === "outline" && shapeDraft.points.length > 2
                ? <Polygon positions={shapeDraft.points} pathOptions={{ color: "#16a34a", dashArray: "4" }} />
                : <Polyline positions={shapeDraft.points} pathOptions={{ color: "#16a34a", dashArray: "4", weight: 4 }} />)}
              {shapeDraft?.points.map((p, i) => <CircleMarker key={i} center={p} radius={4} pathOptions={{ color: "#16a34a" }} />)}
              {editable && draft?.kind === "position" && (
                <Picker onPick={(lat, lon) => setDraft({ ...draft, lat: lat.toFixed(7), lon: lon.toFixed(7) })} />
              )}
              {editable && shapeDraft && (
                <Picker onPick={(lat, lon) => setDraft({ ...shapeDraft, points: [...shapeDraft.points, [lat, lon]] })} />
              )}
            </MapContainer>
          </div>
          <div className="space-y-3 text-sm">
            <div>
              <p className="text-xs font-semibold uppercase text-slate-500">Position</p>
              {here ? (
                <p>
                  <span className="font-mono">{here.latitude?.toFixed(6)}, {here.longitude?.toFixed(6)}</span>
                  {here.accuracy_m != null && <span className="text-slate-500"> ±{Math.round(here.accuracy_m)} m</span>}
                  <span className="block text-xs text-slate-500">{SOURCE(here)}</span>
                </p>
              ) : <p className="text-slate-500">None yet.</p>}
            </div>
            {l.route && (
              <div>
                <p className="text-xs font-semibold uppercase text-slate-500">Route</p>
                <p>{fmtLength(l.route.length_m)} long <span className="block text-xs text-slate-500">{SOURCE(l.route)}</span></p>
              </div>
            )}
            {l.outline && (
              <div>
                <p className="text-xs font-semibold uppercase text-slate-500">Outline</p>
                <p>
                  {fmtArea(l.outline.area_m2)}
                  {l.outline.base_m != null && l.outline.top_m != null &&
                    ` · from ${l.outline.base_m} m to ${l.outline.top_m} m (${(l.outline.top_m - l.outline.base_m).toFixed(1)} m high)`}
                  <span className="block text-xs text-slate-500">{SOURCE(l.outline)}</span>
                </p>
              </div>
            )}
            {editable && !draft && (
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setDraft({ kind: "position", lat: here?.latitude != null ? String(here.latitude) : "",
                                                                 lon: here?.longitude != null ? String(here.longitude) : "", acc: "" })}
                        className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
                  {here ? "Move it" : "Set its position"}
                </button>
                <button type="button" onClick={() => startShape("route")}
                        className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
                  {l.route ? "Redraw its route" : "Draw its route"}
                </button>
                <button type="button" onClick={() => startShape("outline")}
                        className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
                  {l.outline ? "Redraw its outline" : "Draw its outline"}
                </button>
                {l.route && <button type="button" onClick={() => confirm("Remove its route?") && remove.mutate("route")}
                                    className="text-xs text-red-600 underline">remove route</button>}
                {l.outline && <button type="button" onClick={() => confirm("Remove its outline?") && remove.mutate("outline")}
                                      className="text-xs text-red-600 underline">remove outline</button>}
              </div>
            )}
            {draft?.kind === "position" && (
              <form className="space-y-1" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
                <p className="text-xs text-slate-500">Click the map, or type WGS 84 coordinates.</p>
                <div className="flex gap-1">
                  <input placeholder="latitude" value={draft.lat} onChange={(e) => setDraft({ ...draft, lat: e.target.value })}
                         className="w-28 rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
                  <input placeholder="longitude" value={draft.lon} onChange={(e) => setDraft({ ...draft, lon: e.target.value })}
                         className="w-28 rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
                  <input placeholder="± m" value={draft.acc} onChange={(e) => setDraft({ ...draft, acc: e.target.value })}
                         className="w-16 rounded border border-slate-300 px-2 py-1 text-xs" />
                </div>
                <div className="flex gap-2">
                  <button type="submit" disabled={save.isPending} className="rounded bg-slate-900 px-3 py-1 text-xs text-white">Save</button>
                  <button type="button" onClick={() => setDraft(null)} className="text-xs text-slate-500 underline">cancel</button>
                </div>
              </form>
            )}
            {shapeDraft && (
              <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
                <p className="text-xs text-slate-500">
                  {shapeDraft.kind === "route"
                    ? "Click the map along the route, point by point."
                    : "Click the map at each corner; the outline closes by itself."}{" "}
                  {shapeDraft.points.length} point{shapeDraft.points.length === 1 ? "" : "s"}.
                </p>
                <div className="flex flex-wrap gap-2 text-xs">
                  <button type="button" disabled={!shapeDraft.points.length}
                          onClick={() => setDraft({ ...shapeDraft, points: shapeDraft.points.slice(0, -1) })}
                          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40">undo last point</button>
                  <button type="button" disabled={!shapeDraft.points.length} onClick={() => setDraft({ ...shapeDraft, points: [] })}
                          className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40">start again</button>
                </div>
                {shapeDraft.kind === "outline" && (
                  <div className="flex flex-wrap items-center gap-1 text-xs">
                    <span className="text-slate-600">Heights (optional, a volume):</span>
                    <input placeholder="bottom m" value={shapeDraft.base} onChange={(e) => setDraft({ ...shapeDraft, base: e.target.value })}
                           className="w-20 rounded border border-slate-300 px-2 py-1" />
                    <input placeholder="top m" value={shapeDraft.top} onChange={(e) => setDraft({ ...shapeDraft, top: e.target.value })}
                           className="w-20 rounded border border-slate-300 px-2 py-1" />
                  </div>
                )}
                <details className="text-xs">
                  <summary className="cursor-pointer text-slate-600">…or paste GeoJSON (a survey, a GIS export)</summary>
                  <textarea value={shapeDraft.pasted} onChange={(e) => setDraft({ ...shapeDraft, pasted: e.target.value })} rows={4}
                            placeholder={shapeDraft.kind === "route" ? '{"type": "LineString", "coordinates": [[12.672, 41.821], …]}'
                                                                     : '{"type": "Polygon", "coordinates": [[[12.672, 41.821], …]]}'}
                            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono" />
                  <span className="text-slate-500">WGS 84 longitude, latitude. It is used instead of what is drawn.</span>
                </details>
                <div className="flex gap-2">
                  <button type="submit" disabled={save.isPending || (!shapeDraft.pasted.trim() && shapeDraft.points.length < minimum)}
                          className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-40">Save</button>
                  <button type="button" onClick={() => setDraft(null)} className="text-xs text-slate-500 underline">cancel</button>
                </div>
              </form>
            )}
            {save.isError && <p className="text-xs text-red-600">{save.error instanceof Error && !(save.error instanceof ApiError) ? save.error.message : problem(save.error)}</p>}
            {pending.map((o) => (
              <div key={o.id} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs">
                Seen at <span className="font-mono">{o.latitude.toFixed(6)}, {o.longitude.toFixed(6)}</span>
                {o.accuracy_m != null && ` ±${Math.round(o.accuracy_m)} m`}{o.observed_by && ` by ${o.observed_by}`}
                {o.distance_m != null ? ` — ${Math.round(o.distance_m)} m from its location` : " — it had none"}
                {editable && (
                  <span className="ml-2">
                    <button type="button" onClick={() => decide.mutate({ id: o.id, accept: true })} className="text-emerald-700 underline">accept</button>{" "}
                    <button type="button" onClick={() => decide.mutate({ id: o.id, accept: false })} className="text-red-700 underline">reject</button>
                  </span>
                )}
              </div>
            ))}
            {l.history.some((h) => h.state !== "confirmed") && (
              <details className="text-xs text-slate-500">
                <summary>Earlier ({l.history.filter((h) => h.state !== "confirmed").length})</summary>
                <ul className="mt-1 space-y-0.5">
                  {l.history.filter((h) => h.state !== "confirmed").map((h) => (
                    <li key={h.uid}>
                      {h.role === "position"
                        ? <span className="font-mono">{h.latitude?.toFixed(6)}, {h.longitude?.toFixed(6)}</span>
                        : <span>{h.role}</span>} · {h.state} · {h.source}
                      {h.valid_from && ` · ${new Date(h.valid_from).toLocaleDateString()}`}
                      {h.valid_until && `–${new Date(h.valid_until).toLocaleDateString()}`}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      )}
      {ctx.data && <PlaceRelations ctx={ctx.data} />}
    </section>
  );
}

function Neighbours({ title, items, distance }: { title: string; items: PlaceNeighbour[]; distance?: boolean }) {
  if (!items.length) return null;
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-slate-500">{title} ({items.length})</p>
      <ul className="mt-1 space-y-0.5 text-xs">
        {items.slice(0, 50).map((n) => (
          <li key={`${n.uid}:${n.role}`}>
            <Link to={`/assets/${n.uid}`} className="text-indigo-700 hover:underline">{n.name}</Link>
            <span className="text-slate-500"> · {n.type}{n.role !== "position" ? ` (${n.role})` : ""}
              {distance && n.distance_m != null ? ` · ${n.distance_m.toFixed(1)} m` : ""}
              {n.base_m != null && n.top_m != null ? ` · ${n.base_m}–${n.top_m} m` : ""}</span>
          </li>
        ))}
        {items.length > 50 && <li className="text-slate-500">…and {items.length - 50} more</li>}
      </ul>
    </div>
  );
}

/** What the record's shapes say about the others: inside its outline, crossing it, along its route, and the
 *  outlines (halls, zones) it is in. */
function PlaceRelations({ ctx }: { ctx: { inside: PlaceNeighbour[]; crossing: PlaceNeighbour[]; along: PlaceNeighbour[];
                                          within: PlaceNeighbour[]; along_m: number } }) {
  if (!ctx.inside.length && !ctx.crossing.length && !ctx.along.length && !ctx.within.length) return null;
  return (
    <div className="mt-4 grid gap-3 border-t border-slate-100 pt-3 md:grid-cols-2">
      <Neighbours title="It is in" items={ctx.within} />
      <Neighbours title="Inside it" items={ctx.inside} />
      <Neighbours title="Crossing it" items={ctx.crossing} />
      <Neighbours title={`Along its route (within ${ctx.along_m} m)`} items={ctx.along} distance />
    </div>
  );
}
