import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

const Full = createContext(false);

/** True inside a full-page window: a map or a plan there fills the height it is given. */
export function useFullPage(): boolean {
  return useContext(Full);
}

/** A map operation in a window of its own, over the whole page (issue #13): the map or the plan as large as the
 *  screen, the controls beside it. Escape or Close leaves it, as its own Cancel would. Inline when not `open`. */
export function FullPage({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: ReactNode;
}) {
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
        <button type="button" onClick={onClose} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
          Close <span className="text-slate-400">Esc</span>
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <Full.Provider value={true}>{children}</Full.Provider>
      </div>
    </div>,
    document.body,
  );
}
