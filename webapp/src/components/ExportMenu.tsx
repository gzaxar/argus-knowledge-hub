import { useEffect, useRef, useState } from "react";
import { exportApi, type ExportKind } from "../api/client";

/** Export ▾ — the record as a Markdown file, as a PDF, or on paper.
 *
 * All three come from the same Markdown the server writes, so the file, the
 * PDF and the printout say the same thing. PDF and Print open the print view
 * in a new tab; the PDF is the browser's own "Save as PDF", which keeps the
 * text selectable and the tables intact.
 */
export function ExportMenu({
  kind,
  uid,
  revisionUid,
  className = "rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50",
}: {
  kind: ExportKind;
  uid: string;
  /** For a document: the revision on screen, rather than the current one. */
  revisionUid?: string | null;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const printView = (pdf: boolean) => {
    const params = new URLSearchParams();
    if (revisionUid) params.set("revision", revisionUid);
    if (pdf) params.set("pdf", "1");
    const query = params.toString();
    window.open(`/print/${kind}/${encodeURIComponent(uid)}${query ? `?${query}` : ""}`, "_blank");
    setOpen(false);
  };

  const markdown = () => {
    setError(null);
    setOpen(false);
    exportApi.downloadMarkdown(kind, uid, revisionUid).catch(() => setError("Could not export."));
  };

  const item = "block w-full px-3 py-1.5 text-left text-sm hover:bg-slate-50";
  return (
    <div ref={box} className="relative inline-block">
      <button type="button" onClick={() => setOpen((v) => !v)} className={className} aria-haspopup="menu">
        Export ▾
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-1 w-44 rounded border border-slate-200 bg-white py-1 shadow-lg">
          <button type="button" role="menuitem" onClick={markdown} className={item}>
            Markdown (.md)
          </button>
          <button type="button" role="menuitem" onClick={() => printView(true)} className={item}>
            PDF
          </button>
          <button type="button" role="menuitem" onClick={() => printView(false)} className={item}>
            Print
          </button>
        </div>
      )}
      {error && <p className="absolute right-0 mt-1 whitespace-nowrap text-xs text-red-600">{error}</p>}
    </div>
  );
}
