import { useCallback, useEffect, useRef, useState } from "react";
import { AuthenticatedImage, useAttachmentUrl } from "./AuthenticatedImage";

const MIN = 0.05, MAX = 16, STEP = 1.25;

/** One image over the page, at its original resolution (the file as uploaded, never a reduced copy), to inspect:
 *  fitted to the window at first, then zoomed (the buttons, the wheel at the pointer, + and −) and panned by
 *  dragging; 100% shows it pixel for pixel, and the original opens in a tab of its own (issue #17). Closed by
 *  Esc or the button. */
export function ImageLightbox({ uid, alt, onClose }: { uid: string; alt: string; onClose: () => void }) {
  const { src, failed } = useAttachmentUrl(uid);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const viewport = () => {
    const r = box.current?.getBoundingClientRect();
    return { w: r?.width || window.innerWidth, h: r?.height || window.innerHeight };
  };
  const fitScale = useCallback(() => {
    if (!size) return 1;
    const v = viewport();
    return Math.min(v.w / size.w, v.h / size.h, 1) || 1;
  }, [size]);
  const centred = useCallback((scale: number) => {
    const v = viewport();
    return { scale, x: (v.w - (size?.w ?? 0) * scale) / 2, y: (v.h - (size?.h ?? 0) * scale) / 2 };
  }, [size]);
  const fit = useCallback(() => setView(centred(fitScale())), [centred, fitScale]);
  /** Zoom by `factor`, keeping the point (cx, cy) of the viewport where it is (its centre by default). */
  const zoom = useCallback((factor: number, cx?: number, cy?: number) => {
    const v = viewport();
    const px = cx ?? v.w / 2, py = cy ?? v.h / 2;
    setView((cur) => {
      const scale = Math.min(MAX, Math.max(MIN, cur.scale * factor));
      const k = scale / cur.scale;
      return { scale, x: px - (px - cur.x) * k, y: py - (py - cur.y) * k };
    });
  }, []);
  const actual = useCallback(() => {
    setView((cur) => {
      const v = viewport();
      const k = 1 / cur.scale;
      return { scale: 1, x: v.w / 2 - (v.w / 2 - cur.x) * k, y: v.h / 2 - (v.h / 2 - cur.y) * k };
    });
  }, []);

  useEffect(() => { if (size) fit(); }, [size]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "+" || e.key === "=") zoom(STEP);
      else if (e.key === "-") zoom(1 / STEP);
      else if (e.key === "0") fit();
      else if (e.key === "1") actual();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose, zoom, fit, actual]);

  // The wheel zooms at the pointer (a listener that may prevent the page from scrolling).
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoom(e.deltaY < 0 ? STEP : 1 / STEP, e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [zoom]);

  const button = "rounded bg-white/90 px-2.5 py-1 text-sm text-slate-800 hover:bg-white disabled:opacity-40";
  return (
    <div role="dialog" aria-label={alt || "Image"} className="fixed inset-0 z-50 flex flex-col bg-slate-900/90">
      <div className="flex flex-wrap items-center gap-1.5 p-2">
        <span className="mr-auto truncate px-1 text-sm text-white">{alt}</span>
        <button type="button" className={button} onClick={() => zoom(1 / STEP)} disabled={!size} aria-label="Zoom out">−</button>
        <span className="w-14 text-center text-sm tabular-nums text-white" aria-label="Zoom">{Math.round(view.scale * 100)}%</span>
        <button type="button" className={button} onClick={() => zoom(STEP)} disabled={!size} aria-label="Zoom in">+</button>
        <button type="button" className={button} onClick={fit} disabled={!size}>Fit to window</button>
        <button type="button" className={button} onClick={actual} disabled={!size}>100%</button>
        <button type="button" className={button} disabled={!src} onClick={() => src && window.open(src, "_blank", "noopener")}>
          Open original
        </button>
        <button type="button" className={button} onClick={onClose}>Close</button>
      </div>
      <div
        ref={box}
        className={`relative min-h-0 flex-1 overflow-hidden ${drag.current ? "cursor-grabbing" : "cursor-grab"}`}
        onPointerDown={(e) => {
          drag.current = { x: e.clientX, y: e.clientY, ox: view.x, oy: view.y };
          (e.target as Element).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (d) setView((cur) => ({ ...cur, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y }));
        }}
        onPointerUp={() => { drag.current = null; }}
        onDoubleClick={(e) => {
          const r = box.current!.getBoundingClientRect();
          zoom(2, e.clientX - r.left, e.clientY - r.top);
        }}
      >
        {failed && <p className="p-4 text-sm text-red-200">The image could not be loaded.</p>}
        {!src && !failed && <p className="p-4 text-sm text-slate-300">Loading…</p>}
        {src && (
          <img
            src={src}
            alt={alt}
            draggable={false}
            onLoad={(e) => setSize({ w: e.currentTarget.naturalWidth || 1, h: e.currentTarget.naturalHeight || 1 })}
            className="absolute left-0 top-0 max-w-none select-none bg-white"
            style={{ width: size?.w, height: size?.h, transformOrigin: "0 0",
                     transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
                     visibility: size ? "visible" : "hidden", imageRendering: view.scale > 2 ? "pixelated" : "auto" }}
          />
        )}
      </div>
      {size && (
        <p className="px-3 pb-2 text-xs text-slate-300">
          {size.w} × {size.h} px, the original · drag to move · wheel or + − to zoom · 0 fits, 1 is 100%
        </p>
      )}
    </div>
  );
}

/** A grid of small images; each opens full size. */
export function ImageGallery({ images }: { images: { uid: string; filename: string }[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {images.map((img) => (
        <GalleryItem key={img.uid} uid={img.uid} filename={img.filename} />
      ))}
    </div>
  );
}


function GalleryItem({ uid, filename }: { uid: string; filename: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={filename}
        className="group overflow-hidden rounded border border-slate-200 bg-slate-50 hover:border-indigo-300"
      >
        <AuthenticatedImage uid={uid} alt={filename} className="h-28 w-full object-cover transition group-hover:opacity-90" />
        <span className="block truncate px-1 py-0.5 text-left text-[11px] text-slate-500">{filename}</span>
      </button>
      {open && <ImageLightbox uid={uid} alt={filename} onClose={() => setOpen(false)} />}
    </>
  );
}
