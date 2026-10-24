import L from "leaflet";
import { useEffect } from "react";
import { useMap } from "react-leaflet";

/** A picture laid on the map by three of its corners (top-left, top-right, bottom-left), so a plan placed by
 *  control points — rotated, scaled, even sheared — sits where its points say. Redrawn after each zoom; hidden
 *  while the map animates one. */
class AffineImageLayer extends L.Layer {
  private img?: HTMLImageElement;

  constructor(private url: string, private width: number, private height: number,
              private corners: [L.LatLngExpression, L.LatLngExpression, L.LatLngExpression], private opacity: number) {
    super();
  }

  onAdd(map: L.Map) {
    const img = L.DomUtil.create("img", "leaflet-image-layer leaflet-zoom-hide") as HTMLImageElement;
    img.src = this.url;
    Object.assign(img.style, { position: "absolute", left: "0", top: "0", width: `${this.width}px`, height: `${this.height}px`,
                               transformOrigin: "0 0", opacity: String(this.opacity), pointerEvents: "none",
                               maxWidth: "none" });
    map.getPanes().overlayPane.appendChild(img);
    this.img = img;
    map.on("zoomend viewreset", this.reset, this);
    this.reset();
    return this;
  }

  onRemove(map: L.Map) {
    map.off("zoomend viewreset", this.reset, this);
    this.img?.remove();
    this.img = undefined;
    return this;
  }

  private reset() {
    const map = this._map;
    if (!map || !this.img) return;
    const [p0, p1, p2] = this.corners.map((c) => map.latLngToLayerPoint(c));
    const a = (p1.x - p0.x) / this.width, b = (p1.y - p0.y) / this.width;
    const c = (p2.x - p0.x) / this.height, d = (p2.y - p0.y) / this.height;
    this.img.style.transform = `matrix(${a}, ${b}, ${c}, ${d}, ${p0.x}, ${p0.y})`;
  }
}

/** A plan's picture on a react-leaflet map, by its corners ([longitude, latitude]: top-left, top-right,
 *  bottom-right, bottom-left, as the server gives them). */
export function AffineImage({ url, width, height, corners, opacity = 0.75 }: {
  url: string; width: number; height: number; corners: [number, number][]; opacity?: number;
}) {
  const map = useMap();
  const key = corners.flat().join(",");
  useEffect(() => {
    const ll = (c: [number, number]): L.LatLngExpression => [c[1], c[0]];
    const layer = new AffineImageLayer(url, width, height, [ll(corners[0]), ll(corners[1]), ll(corners[3])], opacity);
    layer.addTo(map);
    return () => { layer.remove(); };
  }, [map, url, width, height, key, opacity]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
