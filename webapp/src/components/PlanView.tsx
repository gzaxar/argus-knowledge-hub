import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { CircleMarker, ImageOverlay, MapContainer, Polyline, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { indoorApi } from "../api/client";

/** The plan's picture, fetched signed in; the URL is let go when the plan is no longer shown. */
export function usePlanImage(uid: string | null | undefined) {
  const q = useQuery({ queryKey: ["plan-image", uid], queryFn: () => indoorApi.planImageUrl(uid!), enabled: !!uid,
                       staleTime: 60 * 60 * 1000, gcTime: 5 * 60 * 1000 });
  return q;
}

export interface PlanPin { id: string; x: number; y: number; label: string; colour?: string; to?: string;
  /** The record being looked for: a ring around it and its label always shown. */
  highlight?: boolean }

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
/** True north on a plan placed on the map: an arrow turned as the drawing has north. */
export function NorthArrow({ deg, className = "" }: { deg: number; className?: string }) {
  return (
    <div role="img" aria-label={`North: ${Math.round(deg)}° clockwise from the plan's top`} title="True north"
         className={`pointer-events-none flex h-10 w-10 items-center justify-center rounded-full border border-slate-300 bg-white/90 shadow-sm ${className}`}>
      <svg viewBox="-12 -12 24 24" width="30" height="30" style={{ transform: `rotate(${deg}deg)` }} aria-hidden="true">
        <polygon points="0,-10 5,4 0,1 -5,4" fill="#dc2626" />
        <polygon points="0,10 5,4 0,1 -5,4" fill="#94a3b8" />
        <text x="0" y="-3.5" textAnchor="middle" fontSize="6" fontWeight="700" fill="#fff">N</text>
      </svg>
    </div>
  );
}

export interface PlanLine { id: string; from: { x: number; y: number }; to: { x: number; y: number }; label?: string }

export function PlanView({ planUid, width, height, pins = [], lines = [], pick, onPick, className = "h-80", northDeg }: {
  planUid: string; width: number; height: number; pins?: PlanPin[];
  /** Dashed lines between points, with a label (a distance). */
  lines?: PlanLine[];
  pick?: { x: number; y: number } | null; onPick?: (x: number, y: number) => void; className?: string;
  /** Where true north points on the picture (a plan placed on the map); shown as an arrow. */
  northDeg?: number | null;
}) {
  const image = usePlanImage(planUid);
  const bounds: [[number, number], [number, number]] = [[0, 0], [height, width]];
  return (
    <div className={`${className} relative isolate overflow-hidden rounded border border-slate-200 bg-slate-50`}>
      {northDeg != null && <NorthArrow deg={northDeg} className="absolute right-2 top-2 z-10" />}
      {image.isError ? <p className="p-3 text-xs text-red-600">The plan could not be loaded.</p> : (
        <MapContainer crs={L.CRS.Simple} bounds={bounds} minZoom={-6} maxZoom={4} zoomSnap={0.25} className="h-full w-full"
                      attributionControl={false}>
          <Fit width={width} height={height} />
          {image.data && <ImageOverlay url={image.data} bounds={bounds} />}
          {lines.map((l) => (
            <Polyline key={l.id} positions={[toLL(height, l.from.x, l.from.y), toLL(height, l.to.x, l.to.y)]}
                      pathOptions={{ color: "#475569", weight: 2, dashArray: "6 6" }}>
              {l.label && <Tooltip permanent direction="center" className="!text-[11px]">{l.label}</Tooltip>}
            </Polyline>
          ))}
          {pins.filter((p) => p.highlight).map((p) => (
            <CircleMarker key={`${p.id}-ring`} center={toLL(height, p.x, p.y)} radius={16} interactive={false}
                          pathOptions={{ color: p.colour ?? "#2563eb", weight: 3, fillOpacity: 0.12, className: "animate-pulse" }} />
          ))}
          {pins.map((p) => (
            <CircleMarker key={p.id} center={toLL(height, p.x, p.y)} radius={p.highlight ? 8 : 6}
                          pathOptions={{ color: "#fff", weight: 2, fillColor: p.colour ?? "#2563eb", fillOpacity: 0.95 }}>
              <Tooltip permanent={!!p.highlight} direction="top" offset={[0, -10]}>{p.label}</Tooltip>
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
