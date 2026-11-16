import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const Full = createContext<{ slot: HTMLElement | null } | null>(null);

/** True inside a full-page window: a map or a plan there fills the height it is given. */
export function useFullPage(): boolean {
  return useContext(Full) !== null;
}

/** An editor's own Save and Cancel: in a full-page window they go to its top bar, beside Close, where they are seen
 *  however tall the map or the plan below is; anywhere else they stay where they are written. */
export function FullPageActions({ children, className = "flex gap-2" }: { children: ReactNode; className?: string }) {
  const full = useContext(Full);
  if (full === null) return <div className={className}>{children}</div>;
  if (!full.slot) return null;
  return createPortal(<div className="flex items-center gap-2">{children}</div>, full.slot);
}

/** A map operation in a window of its own, over the whole page (issue #13): the map or the plan as large as the
 *  screen, the controls beside it. Escape or Close leaves it, as its own Cancel would. Inline when not `open`. */
export function FullPage({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode;
}) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); document.body.style.overflow = overflow; };
  }, [open, onClose]);
  if (!open) return <>{children}</>;
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={title} className="fixed inset-0 z-[2000] flex flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <div className="flex items-center gap-3">
          <div ref={setSlot} data-full-page-actions="" className="flex items-center gap-2 text-xs" />
          <button type="button" onClick={onClose} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
            Close <span className="text-slate-400">Esc</span>
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <Full.Provider value={{ slot }}>{children}</Full.Provider>
      </div>
    </div>,
    document.body,
  );
}
