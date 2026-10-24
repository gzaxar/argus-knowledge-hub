import type { PathOptions } from "leaflet";
import { useEffect } from "react";
import { CircleMarker, Polygon, Polyline, useMap } from "react-leaflet";
import type { GeoGeometry } from "../api/client";

export type LatLng = [number, number];

/** GeoJSON positions are [longitude, latitude]; Leaflet's are [latitude, longitude]. */
const ll = (p: [number, number]): LatLng => [p[1], p[0]];

/** Every position of a geometry, as Leaflet points (to fit a map to it). */
export function pointsOf(g: GeoGeometry): LatLng[] {
  switch (g.type) {
    case "Point": return [ll(g.coordinates)];
    case "LineString": return g.coordinates.map(ll);
    case "MultiLineString": return g.coordinates.flat().map(ll);
    case "Polygon": return g.coordinates.flat().map(ll);
    case "MultiPolygon": return g.coordinates.flat(2).map(ll);
  }
}

/** A geometry on a react-leaflet map: a point as a dot, a route as a line, an outline as an area. */
export function GeoShape({ geometry, style, children }: {
  geometry: GeoGeometry; style: PathOptions; children?: React.ReactNode;
}) {
  switch (geometry.type) {
    case "Point":
      return <CircleMarker center={ll(geometry.coordinates)} radius={7} pathOptions={style}>{children}</CircleMarker>;
    case "LineString":
      return <Polyline positions={geometry.coordinates.map(ll)} pathOptions={{ weight: 4, ...style }}>{children}</Polyline>;
    case "MultiLineString":
      return <Polyline positions={geometry.coordinates.map((part) => part.map(ll))} pathOptions={{ weight: 4, ...style }}>{children}</Polyline>;
    case "Polygon":
      return <Polygon positions={geometry.coordinates.map((ring) => ring.map(ll))} pathOptions={{ fillOpacity: 0.15, ...style }}>{children}</Polygon>;
    case "MultiPolygon":
      return <Polygon positions={geometry.coordinates.map((poly) => poly.map((ring) => ring.map(ll)))}
                      pathOptions={{ fillOpacity: 0.15, ...style }}>{children}</Polygon>;
  }
}

/** Fit the map to these points once they are known (and again when they change). */
export function FitTo({ points, maxZoom = 19 }: { points: LatLng[]; maxZoom?: number }) {
  const map = useMap();
  const key = points.map((p) => p.join(",")).join(";");
  useEffect(() => {
    if (points.length === 1) map.setView(points[0], Math.min(maxZoom, 18));
    else if (points.length > 1) map.fitBounds(points, { padding: [24, 24], maxZoom });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Drawn points as a GeoJSON route or outline (an outline's ring closed). */
export function drawnGeometry(role: "route" | "outline", points: LatLng[]): GeoGeometry {
  const coords = points.map(([lat, lon]) => [Number(lon.toFixed(8)), Number(lat.toFixed(8))] as [number, number]);
  if (role === "route") return { type: "LineString", coordinates: coords };
  return { type: "Polygon", coordinates: [[...coords, coords[0]]] };
}

/** A pasted GeoJSON geometry, Feature or one-feature FeatureCollection — its geometry, or a reason it is not. */
export function parseGeometry(text: string): GeoGeometry | string {
  try {
    let v = JSON.parse(text);
    if (v?.type === "FeatureCollection") v = v.features?.[0];
    if (v?.type === "Feature") v = v.geometry;
    if (v && typeof v.type === "string" && Array.isArray(v.coordinates)) return v as GeoGeometry;
    return "That is not a GeoJSON geometry.";
  } catch {
    return "That is not JSON.";
  }
}

export const fmtLength = (m?: number) => m == null ? "" : m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(1)} m`;
export const fmtArea = (m2?: number) => m2 == null ? "" : m2 >= 10000 ? `${(m2 / 10000).toFixed(2)} ha` : `${Math.round(m2)} m²`;
