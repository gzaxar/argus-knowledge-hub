import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { aiApi, problemText, webImportApi, type WebFolderImported, type WebFolderPreview } from "../api/client";

const MAX_SUGGESTED = 20;

/** A web page saved as a folder — an HTML file and its pictures, as a LabVIEW or Doxygen export or a browser's
 * "save page" makes it — imported as documents, one per page: each page's pictures are attached and shown in
 * place, its HTML is kept as the original, and the files no page uses go with the first document. The new
 * documents take the type, confidentiality and authority chosen in the form beside. */
export function WebFolderImport({ documentTypeUid, confidentiality, authorityLevel, relateAsset }: {
  documentTypeUid: string;
  confidentiality: string;
  authorityLevel: string;
  relateAsset?: string | null;
}) {
  const navigate = useNavigate();
  const folderInput = useRef<HTMLInputElement>(null);
  const zipInput = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<WebFolderPreview | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [done, setDone] = useState<WebFolderImported | null>(null);
  // The assistant reads each page's text and proposes its type, a summary and keywords.
  const ai = useQuery({ queryKey: ["ai-status"], queryFn: aiApi.status, staleTime: 60_000 });
  const canSuggest = !!ai.data?.validated;
  const [suggest, setSuggest] = useState(true);
  const suggesting = canSuggest && suggest && chosen.size <= MAX_SUGGESTED;

  const look = useMutation({
    mutationFn: (picked: File[]) => webImportApi.preview(picked),
    onSuccess: (p) => { setPreview(p); setChosen(new Set(p.pages.map((x) => x.path))); },
  });
  const run = useMutation({
    mutationFn: () => webImportApi.run(files, {
      pages: preview!.pages.filter((p) => chosen.has(p.path)).map((p) => p.path),
      document_type_uid: documentTypeUid || undefined, confidentiality, authority_level: authorityLevel,
      relate_asset: relateAsset ?? undefined, suggest: suggesting }),
    onSuccess: (r) => {
      if (r.documents.length === 1 && !r.suggestions_failed.length) navigate(`/documents/${r.documents[0].uid}`);
      else setDone(r);
    },
  });

  const pick = (list: FileList | null, label: string) => {
    const picked = Array.from(list ?? []);
    if (!picked.length) return;
    setFiles(picked);
    setName(label);
    setPreview(null);
    setDone(null);
    look.mutate(picked);
  };

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-800">Import a web page folder</h2>
      <p className="mt-1 text-xs text-slate-500">
        An HTML page saved with its pictures (a LabVIEW or Doxygen export, a saved web page): one document per page,
        with its pictures in place and the original files attached.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => folderInput.current?.click()} disabled={look.isPending || run.isPending}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40">
          Choose a folder
        </button>
        <button type="button" onClick={() => zipInput.current?.click()} disabled={look.isPending || run.isPending}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs disabled:opacity-40">
          …or a .zip of it
        </button>
        <input ref={folderInput} type="file" multiple className="hidden" {...{ webkitdirectory: "", directory: "" }}
               onChange={(e) => {
                 const list = e.target.files;
                 pick(list, list?.[0]?.webkitRelativePath.split("/")[0] ?? "folder");
                 e.target.value = "";
               }} />
        <input ref={zipInput} type="file" accept=".zip,application/zip" className="hidden"
               onChange={(e) => { pick(e.target.files, e.target.files?.[0]?.name ?? "zip"); e.target.value = ""; }} />
      </div>
      {look.isPending && <p className="mt-2 text-xs text-slate-500">Reading {name}…</p>}
      {look.isError && <p className="mt-2 text-xs text-rose-700">{problemText(look.error)}</p>}
      {preview && !done && (
        <div className="mt-3 space-y-2 text-xs">
          <p className="text-slate-600">
            <b>{name}</b>: {preview.files} files, {preview.pages.length} page{preview.pages.length === 1 ? "" : "s"}.
            {preview.unused.length > 0 && ` ${preview.unused.length} file(s) no page uses will be attached to the first document.`}
          </p>
          <ul className="max-h-60 space-y-1 overflow-y-auto">
            {preview.pages.map((p) => (
              <li key={p.path}>
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={chosen.has(p.path)} className="mt-0.5"
                         onChange={(e) => setChosen((cur) => {
                           const next = new Set(cur);
                           if (e.target.checked) next.add(p.path); else next.delete(p.path);
                           return next;
                         })} />
                  <span>
                    <span className="font-medium text-slate-800">{p.title}</span>
                    <span className="block text-slate-500">{p.path} · {p.pictures} picture{p.pictures === 1 ? "" : "s"}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <p className="text-slate-500">
            Each becomes a draft document{documentTypeUid ? " of the type chosen in the form" : " without a type (choose one in the form first, or later)"}, {confidentiality}.
          </p>
          {canSuggest && (
            <label className="flex items-start gap-2 text-slate-700">
              <input type="checkbox" checked={suggest} onChange={(e) => setSuggest(e.target.checked)} className="mt-0.5" />
              <span>
                Let the assistant suggest each page&apos;s type{documentTypeUid ? " (the form's is kept)" : ""}, a summary
                and keywords, from its text
                <span className="block text-slate-500">
                  {chosen.size > MAX_SUGGESTED
                    ? `For at most ${MAX_SUGGESTED} pages at a time: these are imported without suggestions.`
                    : "It reads the text, not the pictures; check what it wrote on each document."}
                </span>
              </span>
            </label>
          )}
          <button type="button" onClick={() => run.mutate()} disabled={run.isPending || chosen.size === 0}
                  className="rounded bg-slate-900 px-3 py-1.5 font-medium text-white disabled:opacity-40">
            {run.isPending ? (suggesting ? "Importing, with the assistant…" : "Importing…")
              : `Import ${chosen.size} document${chosen.size === 1 ? "" : "s"}`}
          </button>
          {run.isError && <p className="text-rose-700">{problemText(run.error)}</p>}
        </div>
      )}
      {done && (
        <div className="mt-3 text-xs">
          <p className="text-emerald-800">Imported as {done.documents.length} draft document{done.documents.length === 1 ? "" : "s"}:</p>
          <ul className="mt-1 list-disc pl-4">
            {done.documents.map((d) => (
              <li key={d.uid}>
                <Link to={`/documents/${d.uid}`} className="text-indigo-600 hover:underline">{d.code} {d.title}</Link>
                {d.suggested.length > 0 && <span className="text-slate-500"> · suggested by the assistant: {d.suggested.map(
                  (f) => ({ title: "title", document_type_uid: "type", summary: "summary", "attributes.argus_keywords": "keywords" } as Record<string, string>)[f] ?? f).join(", ")}</span>}
                {done.suggestions_failed.includes(d.path) && <span className="text-amber-800"> · the assistant could not read it</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
