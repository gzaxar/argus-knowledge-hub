import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { exportApi, type ExportKind } from "../api/client";
import { MarkdownView } from "../components/MarkdownView";

const KINDS: ExportKind[] = ["document", "asset", "ticket"];

/** A document, asset or ticket on a plain page, for paper or for a PDF.
 *
 * Opened in its own tab by Export ▸ PDF / Print: no sidebar, no buttons in
 * the printout, and the print dialog opens by itself once the text and its
 * pictures are in. The tab's title is the file name, which is what the
 * browser offers when saving as PDF.
 */
export function PrintPage() {
  const { kind, uid } = useParams<{ kind: string; uid: string }>();
  const [params] = useSearchParams();
  const revision = params.get("revision");
  const pdf = params.get("pdf") === "1";
  const valid = KINDS.includes(kind as ExportKind) && !!uid;
  const printed = useRef(false);

  const md = useQuery({
    queryKey: ["export-markdown", kind, uid, revision],
    queryFn: () => exportApi.markdown(kind as ExportKind, uid!, revision),
    enabled: valid,
    retry: false,
  });

  useEffect(() => {
    if (!md.data || printed.current) return;
    printed.current = true;
    document.title = md.data.filename.replace(/\.md$/, "");
    // Pictures in the body are fetched with the reader's token after the
    // text renders; wait for them (up to a few seconds) so they are on paper.
    const started = Date.now();
    const timer = window.setInterval(() => {
      const images = Array.from(document.querySelectorAll<HTMLImageElement>(".print-sheet img"));
      const pending = document.querySelectorAll(".print-sheet [data-loading]").length;
      if ((images.every((i) => i.complete) && pending === 0) || Date.now() - started > 5000) {
        window.clearInterval(timer);
        window.print();
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [md.data]);

  if (!valid) return <p className="p-6 text-sm text-red-600">Nothing to print here.</p>;

  return (
    <div className="min-h-screen bg-slate-100 print:bg-white">
      <style>{`
        @page { margin: 16mm 14mm; }
        @media print {
          .print-sheet { box-shadow: none !important; border: 0 !important; padding: 0 !important; max-width: none !important; }
          .print-sheet pre, .print-sheet thead { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          .print-sheet h1, .print-sheet h2, .print-sheet h3 { break-after: avoid; }
          .print-sheet tr, .print-sheet img, .print-sheet pre { break-inside: avoid; }
          .print-sheet .overflow-x-auto { overflow: visible !important; }
        }
      `}</style>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 text-sm print:hidden">
        <span className="text-slate-600">
          {pdf ? (
            <>In the print dialog choose <b>Save as PDF</b> as the destination.</>
          ) : (
            "Printing opens by itself once the page is ready."
          )}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => window.print()}
            disabled={!md.data}
            className="rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-40"
          >
            {pdf ? "Save as PDF…" : "Print…"}
          </button>
          <button type="button" onClick={() => window.close()} className="rounded border border-slate-300 px-3 py-1.5">
            Close
          </button>
        </div>
      </div>
      <div className="print-sheet mx-auto my-6 max-w-4xl rounded border border-slate-200 bg-white p-10 shadow-sm">
        {md.isLoading && <p className="text-sm text-slate-500">Preparing…</p>}
        {md.isError && <p className="text-sm text-red-600">Could not load it: you may not have access, or it no longer exists.</p>}
        {md.data && <MarkdownView markdown={md.data.text} />}
      </div>
    </div>
  );
}
