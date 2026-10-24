import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { CircleMarker, ImageOverlay, MapContainer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { indoorApi } from "../api/client";

/** The plan's picture, fetched signed in; the URL is let go when the plan is no longer shown. */
export function usePlanImage(uid: string | null | undefined) {
  const q = useQuery({ queryKey: ["plan-image", uid], queryFn: () => indoorApi.planImageUrl(uid!), enabled: !!uid,
                       staleTime: 60 * 60 * 1000, gcTime: 5 * 60 * 1000 });
  return q;
}

export interface PlanPin { id: string; x: number; y: number; label: string; colour?: string; to?: string }

/** Plan pixels (x right, y down) to Leaflet's flat coordinates (y up) and back. */
const toLL = (h: number, x: number, y: number): [number, number] => [h - y, x];

function Clicks({ height, onPick }: { height: number; onPick: (x: number, y: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lng, height - e.latlng.lat) });
  return null;
}

function Fit({ width, height }: { width: number; height: number }) {
  const map = useMap();
  useEffect(() => { map.fitBounds([[0, 0], [height, width]]); }, [width, height]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** A floor plan in its own pixels: zoom and pan it, its pins (the records placed on it, the control points), and
 *  — with `onPick` — a click gives the pixel clicked. */
export function PlanView({ planUid, width, height, pins = [], pick, onPick, className = "h-80" }: {
  planUid: string; width: number; height: number; pins?: PlanPin[];
  pick?: { x: number; y: number } | null; onPick?: (x: number, y: number) => void; className?: string;
}) {
  const image = usePlanImage(planUid);
  const bounds: [[number, number], [number, number]] = [[0, 0], [height, width]];
  return (
    <div className={`${className} overflow-hidden rounded border border-slate-200 bg-slate-50`}>
      {image.isError ? <p className="p-3 text-xs text-red-600">The plan could not be loaded.</p> : (
        <MapContainer crs={L.CRS.Simple} bounds={bounds} minZoom={-6} maxZoom={4} zoomSnap={0.25} className="h-full w-full"
                      attributionControl={false}>
          <Fit width={width} height={height} />
          {image.data && <ImageOverlay url={image.data} bounds={bounds} />}
          {pins.map((p) => (
            <CircleMarker key={p.id} center={toLL(height, p.x, p.y)} radius={6}
                          pathOptions={{ color: "#fff", weight: 2, fillColor: p.colour ?? "#2563eb", fillOpacity: 0.95 }}>
              <Tooltip>{p.label}</Tooltip>
            </CircleMarker>
          ))}
          {pick && <CircleMarker center={toLL(height, pick.x, pick.y)} radius={8} pathOptions={{ color: "#16a34a", fillOpacity: 0.5 }} />}
          {onPick && <Clicks height={height} onPick={(x, y) => {
            if (x >= 0 && y >= 0 && x <= width && y <= height) onPick(Math.round(x * 10) / 10, Math.round(y * 10) / 10);
          }} />}
        </MapContainer>
      )}
    </div>
  );
}
