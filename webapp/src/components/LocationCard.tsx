import "leaflet/dist/leaflet.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from "react-leaflet";
import { ApiError, MAP_TILES, placesApi } from "../api/client";

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

/** Where a piece of equipment is: its approved location on a small map, setting it (typed, or by clicking
 *  the map), its history, and the field observations — one that disagrees waits here to be accepted or
 *  rejected. Shown only for types their package places on the map. */
export function LocationCard({ uid, editable }: { uid: string; editable: boolean }) {
  const queryClient = useQueryClient();
  const loc = useQuery({ queryKey: ["asset-location", uid], queryFn: () => placesApi.location(uid), retry: false });
  const [draft, setDraft] = useState<{ lat: string; lon: string; acc: string } | null>(null);
  const done = () => {
    setDraft(null);
    queryClient.invalidateQueries({ queryKey: ["asset-location", uid] });
    queryClient.invalidateQueries({ queryKey: ["asset-history", uid] });
  };
  const save = useMutation({
    mutationFn: () => placesApi.setLocation(uid, { latitude: Number(draft!.lat), longitude: Number(draft!.lon),
                                                  ...(draft!.acc ? { accuracy_m: Number(draft!.acc) } : {}) }),
    onSuccess: done,
  });
  const decide = useMutation({ mutationFn: ({ id, accept }: { id: number; accept: boolean }) => placesApi.decide(id, accept),
                               onSuccess: done });
  const l = loc.data;
  if (!l || !l.locatable) return null;
  const here = l.location;
  const pending = l.observations.filter((o) => o.status === "pending");

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
          <div className="h-56 overflow-hidden rounded border border-slate-200">
            <MapContainer center={here ? [here.latitude, here.longitude] : [41.8217, 12.6726]} zoom={here ? 18 : 15}
                          className="h-full w-full">
              <TileLayer url={MAP_TILES.url} attribution={MAP_TILES.attribution} maxZoom={20} />
              {here && <CircleMarker center={[here.latitude, here.longitude]} radius={8}
                                     pathOptions={{ color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 0.9 }} />}
              {pending.map((o) => (
                <CircleMarker key={o.id} center={[o.latitude, o.longitude]} radius={6}
                              pathOptions={{ color: "#f59e0b", dashArray: "3", fillOpacity: 0.2 }} />
              ))}
              {draft && draft.lat && draft.lon && !Number.isNaN(Number(draft.lat)) && (
                <CircleMarker center={[Number(draft.lat), Number(draft.lon)]} radius={8}
                              pathOptions={{ color: "#16a34a", fillOpacity: 0.5 }} />
              )}
              {editable && draft && (
                <Picker onPick={(lat, lon) => setDraft({ ...draft, lat: lat.toFixed(7), lon: lon.toFixed(7) })} />
              )}
            </MapContainer>
          </div>
          <div className="space-y-2 text-sm">
            {here ? (
              <p>
                <span className="font-mono">{here.latitude.toFixed(6)}, {here.longitude.toFixed(6)}</span>
                {here.accuracy_m != null && <span className="text-slate-500"> ±{Math.round(here.accuracy_m)} m</span>}
                <span className="block text-xs text-slate-500">
                  {here.source === "field" ? "from the field" : here.source === "import" ? "imported" : "set by hand"}
                  {here.confirmed_by && ` by ${here.confirmed_by}`}{here.reviewer && `, accepted by ${here.reviewer}`}
                  {here.confirmed_at && ` · ${new Date(here.confirmed_at).toLocaleDateString()}`}
                </span>
              </p>
            ) : <p className="text-slate-500">No location yet.</p>}
            {editable && !draft && (
              <button type="button" onClick={() => setDraft({ lat: here ? String(here.latitude) : "", lon: here ? String(here.longitude) : "", acc: "" })}
                      className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
                {here ? "Move it" : "Set its location"}
              </button>
            )}
            {draft && (
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
                {save.isError && <p className="text-xs text-red-600">{problem(save.error)}</p>}
              </form>
            )}
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
            {l.history.length > 1 && (
              <details className="text-xs text-slate-500">
                <summary>Earlier locations ({l.history.length - 1})</summary>
                <ul className="mt-1 space-y-0.5">
                  {l.history.filter((h) => h.state !== "confirmed").map((h) => (
                    <li key={h.uid}>
                      <span className="font-mono">{h.latitude.toFixed(6)}, {h.longitude.toFixed(6)}</span> · {h.source}
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
    </section>
  );
}
