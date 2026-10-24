import "leaflet/dist/leaflet.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import { Link } from "react-router-dom";
import {
  ApiError, MAP_TILES, indoorApi, placesApi, type ControlPoint, type FloorPlanView, type IndoorView, type PlaceLevel,
} from "../api/client";
import type { Asset } from "../api/types";
import { AffineImage } from "../lib/affineOverlay";
import { FitTo, pointsOf, type LatLng } from "../lib/geo";
import { PlanView, usePlanImage } from "./PlanView";

function problem(e: unknown): string {
  if (e instanceof ApiError) {
    const d = (e.body as { detail?: unknown })?.detail;
    if (d && typeof d === "object" && "error" in d) return String((d as { error: string }).error);
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : "It could not be saved.";
}

const levelName = (l: PlaceLevel | null | undefined) => (l ? l.name : "");

/** Indoors, on a record's page: where it is inside — its place (a room, a hall), its floor, its point on a plan —
 *  and the places that place is in; for a place, its floors, its floor plans (placed on the map by control
 *  points) and what is placed in it. */
export function IndoorCard({ uid, editable }: { uid: string; editable: boolean }) {
  const queryClient = useQueryClient();
  const loc = useQuery({ queryKey: ["asset-location", uid], queryFn: () => placesApi.location(uid), retry: false });
  const view = useQuery({ queryKey: ["asset-indoors", uid], queryFn: () => indoorApi.indoors(uid), retry: false });
  const floors = useQuery({ queryKey: ["asset-levels", uid], queryFn: () => indoorApi.levels(uid), retry: false });
  const [editing, setEditing] = useState(false);
  const refresh = () => {
    for (const k of ["asset-indoors", "asset-levels", "asset-location", "asset-location-context", "asset-history"]) {
      queryClient.invalidateQueries({ queryKey: [k] });
    }
  };
  const remove = useMutation({ mutationFn: () => indoorApi.removeIndoors(uid), onSuccess: refresh });
  if (!view.data || loc.data?.hidden) return null;
  const v = view.data;
  const p = v.placement;
  const isPlace = loc.data?.map_layer === "places" || (floors.data?.levels.length ?? 0) > 0 ||
    (floors.data?.plans.length ?? 0) > 0 || v.contents.length > 0;

  return (
    <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-900">Indoors</h2>
        {p ? (
          <div className="mt-1 text-sm">
            <p>
              {p.place ? <>In <Link to={`/assets/${p.place.uid}`} className="text-indigo-700 hover:underline">{p.place.name}</Link></> : "Placed"}
              {p.level && <>, {p.level.name}</>}
              {p.plan && <> — on the plan <span className="font-medium">{p.plan.name}</span>{p.x != null && ` at ${Math.round(p.x)}, ${Math.round(p.y ?? 0)}`}</>}
            </p>
            {v.in.length > 1 && (
              <p className="text-xs text-slate-500">
                which is in {v.in.slice(1).map((c, i) => (
                  <span key={c.uid}>{i > 0 && " → "}<Link to={`/assets/${c.uid}`} className="hover:underline">{c.name}</Link></span>
                ))}
              </p>
            )}
            {p.plan && p.x != null && p.y != null && (
              <div className="mt-2 max-w-xl">
                <PlanView planUid={p.plan.uid} width={p.plan.width_px} height={p.plan.height_px} className="h-56"
                          pins={[{ id: uid, x: p.x, y: p.y, label: "here", colour: "#dc2626" }]} />
              </div>
            )}
          </div>
        ) : <p className="mt-1 text-sm text-slate-500">Not placed in a room or on a plan.</p>}
        {editable && !editing && (
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => setEditing(true)} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
              {p ? "Move it" : "Place it inside"}
            </button>
            {p && <button type="button" onClick={() => confirm("Take it out of its place?") && remove.mutate()}
                          className="text-xs text-red-600 underline">remove</button>}
          </div>
        )}
        {editing && <PlacementEditor uid={uid} current={v} onDone={() => { setEditing(false); refresh(); }} onCancel={() => setEditing(false)} />}
      </div>

      {isPlace && floors.data && (
        <FloorsAndPlans placeUid={uid} levels={floors.data.levels} plans={floors.data.plans} contents={v.contents}
                        editable={editable} onChanged={refresh} />
      )}
    </section>
  );
}

/** Choose the place (a room, a hall) by searching, optionally a plan of it (or of a place it is in) and the
 *  point on it. */
function PlacementEditor({ uid, current, onDone, onCancel }: {
  uid: string; current: IndoorView; onDone: () => void; onCancel: () => void;
}) {
  const [q, setQ] = useState("");
  const [place, setPlace] = useState<{ uid: string; name: string } | null>(current.placement?.place ?? null);
  const [planUid, setPlanUid] = useState<string | null>(current.placement?.plan?.uid ?? null);
  const [point, setPoint] = useState<{ x: number; y: number } | null>(
    current.placement?.x != null ? { x: current.placement.x, y: current.placement.y ?? 0 } : null);
  const found = useQuery({ queryKey: ["place-search", q], queryFn: () => indoorApi.searchRecords(q), enabled: q.trim().length >= 2 });
  const placeIndoors = useQuery({ queryKey: ["asset-indoors", place?.uid], queryFn: () => indoorApi.indoors(place!.uid), enabled: !!place });
  // The plans of the place, and of the places it is in (a room's floor plan is usually the building's).
  const owners = place ? [place.uid, ...(placeIndoors.data?.in.map((c) => c.uid) ?? [])] : [];
  const plans = useQuery({
    queryKey: ["plans-of", owners.join(",")],
    queryFn: async () => (await Promise.all(owners.map((o) => indoorApi.levels(o).catch(() => ({ plans: [] as FloorPlanView[] })))))
      .flatMap((r) => r.plans),
    enabled: owners.length > 0,
  });
  const plan = plans.data?.find((x) => x.uid === planUid) ?? null;
  const save = useMutation({
    mutationFn: () => indoorApi.setIndoors(uid, { place_uid: place?.uid ?? null, plan_uid: planUid,
                                                   x: planUid && point ? point.x : null, y: planUid && point ? point.y : null }),
    onSuccess: onDone,
  });
  return (
    <div className="mt-2 space-y-2 rounded border border-slate-200 p-3 text-sm">
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">The place it is in</p>
        {place ? (
          <p>{place.name} <button type="button" onClick={() => { setPlace(null); setPlanUid(null); setPoint(null); }}
                                  className="ml-2 text-xs text-slate-500 underline">change</button></p>
        ) : (
          <>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a room, a hall, a building…"
                   className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm" />
            <ul className="mt-1 max-h-40 overflow-y-auto">
              {(found.data ?? []).filter((a: Asset) => a.uid !== uid).map((a: Asset) => (
                <li key={a.uid}>
                  <button type="button" onClick={() => setPlace({ uid: a.uid, name: a.name })}
                          className="w-full rounded px-2 py-1 text-left text-xs hover:bg-slate-100">
                    {a.name} <span className="text-slate-500">· {a.type} · {a.key}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      {place && (
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">On a plan (optional)</p>
          <select value={planUid ?? ""} onChange={(e) => { setPlanUid(e.target.value || null); setPoint(null); }}
                  className="mt-1 rounded border border-slate-300 px-2 py-1 text-xs">
            <option value="">No plan: just in {place.name}</option>
            {(plans.data ?? []).map((pl) => (
              <option key={pl.uid} value={pl.uid}>{pl.name}{pl.level ? ` (${pl.level.name})` : ""} · {pl.place.name}</option>
            ))}
          </select>
          {plan && (
            <>
              <p className="mt-1 text-xs text-slate-500">Click the plan where it is{plan.corners ? "; the plan is placed on the map, so this gives it its position too" : ""}.</p>
              <PlanView planUid={plan.uid} width={plan.width_px} height={plan.height_px} pick={point}
                        onPick={(x, y) => setPoint({ x, y })} className="mt-1 h-72" />
            </>
          )}
        </div>
      )}
      {save.isError && <p className="text-xs text-red-600">{problem(save.error)}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={!place || save.isPending || (!!planUid && !point)} onClick={() => save.mutate()}
                className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-40">Save</button>
        <button type="button" onClick={onCancel} className="text-xs text-slate-500 underline">cancel</button>
      </div>
    </div>
  );
}

/** A place's floors and plans, and what is placed in it. */
function FloorsAndPlans({ placeUid, levels, plans, contents, editable, onChanged }: {
  placeUid: string; levels: PlaceLevel[]; plans: FloorPlanView[]; contents: IndoorView["contents"]; editable: boolean;
  onChanged: () => void;
}) {
  const [form, setForm] = useState({ name: "", ordinal: "0", elevation: "", height: "" });
  const [upload, setUpload] = useState<{ file: File | null; name: string; level: string }>({ file: null, name: "", level: "" });
  const [open, setOpen] = useState<string | null>(null);
  const [placing, setPlacing] = useState<string | null>(null);
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const addLevel = useMutation({
    mutationFn: () => indoorApi.addLevel(placeUid, { name: form.name, ordinal: Number(form.ordinal) || 0,
                                                     elevation_m: num(form.elevation), height_m: num(form.height) }),
    onSuccess: () => { setForm({ name: "", ordinal: "0", elevation: "", height: "" }); onChanged(); },
  });
  const removeLevel = useMutation({ mutationFn: indoorApi.removeLevel, onSuccess: onChanged });
  const addPlan = useMutation({
    mutationFn: () => indoorApi.addPlan(placeUid, upload.file!, upload.name, upload.level || null),
    onSuccess: () => { setUpload({ file: null, name: "", level: "" }); onChanged(); },
  });
  const removePlan = useMutation({ mutationFn: indoorApi.removePlan, onSuccess: onChanged });
  return (
    <div className="space-y-4 border-t border-slate-100 pt-3 text-sm">
      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Floors</p>
        {levels.length === 0 && <p className="text-xs text-slate-500">None yet.</p>}
        <ul className="mt-1 space-y-0.5">
          {levels.map((l) => (
            <li key={l.uid} className="text-xs">
              <span className="font-medium">{l.name}</span> <span className="text-slate-500">(order {l.ordinal}
              {l.elevation_m != null && `, at ${l.elevation_m} m`}{l.height_m != null && `, ${l.height_m} m high`})</span>
              {editable && <button type="button" onClick={() => confirm(`Remove the floor ${l.name}?`) && removeLevel.mutate(l.uid)}
                                   className="ml-2 text-red-600 underline">remove</button>}
            </li>
          ))}
        </ul>
        {editable && (
          <form className="mt-2 flex flex-wrap items-center gap-1 text-xs" onSubmit={(e) => { e.preventDefault(); addLevel.mutate(); }}>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Ground floor"
                   className="w-32 rounded border border-slate-300 px-2 py-1" />
            <input value={form.ordinal} onChange={(e) => setForm({ ...form, ordinal: e.target.value })} title="0 ground, 1 first, -1 basement"
                   className="w-14 rounded border border-slate-300 px-2 py-1" />
            <input value={form.elevation} onChange={(e) => setForm({ ...form, elevation: e.target.value })} placeholder="at m"
                   className="w-16 rounded border border-slate-300 px-2 py-1" />
            <input value={form.height} onChange={(e) => setForm({ ...form, height: e.target.value })} placeholder="high m"
                   className="w-16 rounded border border-slate-300 px-2 py-1" />
            <button type="submit" disabled={!form.name.trim() || addLevel.isPending} className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">Add a floor</button>
            {addLevel.isError && <span className="text-red-600">{problem(addLevel.error)}</span>}
          </form>
        )}
      </div>

      <div>
        <p className="text-xs font-semibold uppercase text-slate-500">Floor plans</p>
        {plans.length === 0 && <p className="text-xs text-slate-500">None yet.</p>}
        <ul className="mt-1 space-y-1">
          {plans.map((pl) => (
            <li key={pl.uid} className="text-xs">
              <span className="font-medium">{pl.name}</span>
              <span className="text-slate-500"> · {levelName(pl.level) || "the whole place"} · {pl.source_kind}
                {pl.corners ? ` · placed on the map (±${(pl.residual_m ?? 0).toFixed(2)} m)` : " · not on the map"}</span>
              <button type="button" onClick={() => setOpen(open === pl.uid ? null : pl.uid)} className="ml-2 text-indigo-700 underline">
                {open === pl.uid ? "hide" : "show"}</button>
              {editable && <button type="button" onClick={() => setPlacing(placing === pl.uid ? null : pl.uid)} className="ml-2 text-indigo-700 underline">
                {pl.corners ? "re-place on the map" : "place on the map"}</button>}
              {editable && <button type="button" onClick={() => confirm(`Remove the plan ${pl.name}?`) && removePlan.mutate(pl.uid)}
                                   className="ml-2 text-red-600 underline">remove</button>}
              {open === pl.uid && <OpenPlan uid={pl.uid} />}
              {placing === pl.uid && <PlanPlacer plan={pl} onDone={() => { setPlacing(null); onChanged(); }} />}
            </li>
          ))}
        </ul>
        {editable && (
          <form className="mt-2 flex flex-wrap items-center gap-1 text-xs" onSubmit={(e) => { e.preventDefault(); addPlan.mutate(); }}>
            <input type="file" accept=".png,.jpg,.jpeg,.gif,.webp,.bmp,.tif,.tiff,.svg,.pdf,.dxf,.dwg"
                   onChange={(e) => setUpload({ ...upload, file: e.target.files?.[0] ?? null })} />
            <input value={upload.name} onChange={(e) => setUpload({ ...upload, name: e.target.value })} placeholder="name"
                   className="w-32 rounded border border-slate-300 px-2 py-1" />
            <select value={upload.level} onChange={(e) => setUpload({ ...upload, level: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1">
              <option value="">the whole place</option>
              {levels.map((l) => <option key={l.uid} value={l.uid}>{l.name}</option>)}
            </select>
            <button type="submit" disabled={!upload.file || addPlan.isPending} className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40">
              {addPlan.isPending ? "Uploading…" : "Add a plan"}</button>
            <span className="w-full text-slate-500">An image, an SVG, a PDF (its first page) or a DXF/DWG drawing.</span>
            {addPlan.isError && <span className="text-red-600">{problem(addPlan.error)}</span>}
          </form>
        )}
      </div>

      {contents.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Placed here ({contents.length})</p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {contents.slice(0, 100).map((c) => (
              <li key={c.uid}><Link to={`/assets/${c.uid}`} className="text-indigo-700 hover:underline">{c.name}</Link>
                <span className="text-slate-500"> · {c.type}</span></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** A plan with the records placed on it. */
function OpenPlan({ uid }: { uid: string }) {
  const plan = useQuery({ queryKey: ["plan", uid], queryFn: () => indoorApi.plan(uid) });
  if (!plan.data) return null;
  const p = plan.data;
  return (
    <div className="mt-1 max-w-3xl">
      <PlanView planUid={p.uid} width={p.width_px} height={p.height_px} className="h-96"
                pins={(p.placed ?? []).map((r) => ({ id: r.uid, x: r.x, y: r.y, label: r.name }))} />
      <p className="mt-1 text-slate-500">{(p.placed ?? []).length} record(s) placed on it.</p>
    </div>
  );
}

function WorldClicks({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

/** Placing a plan on the map: click a point of the plan, then where it is on the map — two pairs at least,
 *  three or more to see each one's residual (a large one is a point clicked in the wrong place). */
function PlanPlacer({ plan, onDone }: { plan: FloorPlanView; onDone: () => void }) {
  const [points, setPoints] = useState<ControlPoint[]>(plan.control_points ?? []);
  const [pixel, setPixel] = useState<{ x: number; y: number } | null>(null);
  const [result, setResult] = useState<FloorPlanView | null>(null);
  const image = usePlanImage(plan.uid);
  const save = useMutation({ mutationFn: () => indoorApi.placePlan(plan.uid, points), onSuccess: (r) => setResult(r) });
  const unplace = useMutation({ mutationFn: () => indoorApi.unplacePlan(plan.uid), onSuccess: onDone });
  const shown = result ?? plan;
  const fit: LatLng[] = shown.corners ? pointsOf({ type: "Polygon", coordinates: [[...shown.corners, shown.corners[0]]] })
    : points.map((p) => [p.latitude, p.longitude] as LatLng);
  return (
    <div className="mt-2 space-y-2 rounded border border-indigo-100 bg-indigo-50/40 p-2">
      <p className="text-slate-600">
        {pixel ? "Now click the same place on the map." : "Click a point you can recognise on the plan (a corner, a column), then the same place on the map."}
      </p>
      <div className="grid gap-2 lg:grid-cols-2">
        <PlanView planUid={plan.uid} width={plan.width_px} height={plan.height_px} className="h-80" pick={pixel}
                  pins={points.map((p, i) => ({ id: String(i), x: p.x, y: p.y, label: `point ${i + 1}`, colour: "#7c3aed" }))}
                  onPick={(x, y) => setPixel({ x, y })} />
        <div className="h-80 overflow-hidden rounded border border-slate-200">
          <MapContainer center={[41.8217, 12.6726]} zoom={17} className="h-full w-full">
            <TileLayer url={MAP_TILES.url} attribution={MAP_TILES.attribution} maxZoom={21} />
            <FitTo points={fit} maxZoom={20} />
            {image.data && shown.corners && <AffineImage url={image.data} width={plan.width_px} height={plan.height_px} corners={shown.corners} opacity={0.6} />}
            {points.map((p, i) => (
              <CircleMarker key={i} center={[p.latitude, p.longitude]} radius={6} pathOptions={{ color: "#7c3aed", fillOpacity: 0.8 }}>
                <Tooltip>point {i + 1}</Tooltip>
              </CircleMarker>
            ))}
            <WorldClicks onPick={(lat, lon) => {
              if (!pixel) return;
              setPoints([...points, { x: pixel.x, y: pixel.y, longitude: Number(lon.toFixed(8)), latitude: Number(lat.toFixed(8)) }]);
              setPixel(null);
            }} />
          </MapContainer>
        </div>
      </div>
      <ul className="space-y-0.5">
        {points.map((p, i) => (
          <li key={i}>
            point {i + 1}: plan {Math.round(p.x)}, {Math.round(p.y)} → {p.latitude.toFixed(6)}, {p.longitude.toFixed(6)}
            {result?.residuals_m?.[i] != null && (
              <span className={result.residuals_m[i] > 1 ? " font-medium text-red-700" : " text-slate-500"}> · off by {result.residuals_m[i].toFixed(2)} m</span>
            )}
            <button type="button" onClick={() => { setPoints(points.filter((_, j) => j !== i)); setResult(null); }} className="ml-2 text-red-600 underline">remove</button>
          </li>
        ))}
      </ul>
      {result && (
        <p className="text-slate-600">Placed: {result.metres_per_px?.toFixed(4)} m a pixel, turned {result.rotation_deg}°, fit within ±{(result.residual_m ?? 0).toFixed(2)} m.</p>
      )}
      {save.isError && <p className="text-red-600">{problem(save.error)}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={points.length < 2 || save.isPending} onClick={() => save.mutate()}
                className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40">{result ? "Place it again" : "Place it"}</button>
        {result && <button type="button" onClick={onDone} className="rounded border border-slate-300 px-3 py-1">Done</button>}
        {plan.corners && <button type="button" onClick={() => confirm("Take the plan off the map?") && unplace.mutate()} className="text-red-600 underline">take it off the map</button>}
      </div>
    </div>
  );
}
