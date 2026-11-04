import { useRef, useState } from "react";
import { convertConfluenceMarkdown, type ImportedPage, type ImportOptions } from "../lib/confluenceImport";
import { MarkdownView } from "./MarkdownView";

export type ConfluenceSelection = { page: ImportedPage; original: File; attachments: File[] };
export function ConfluenceImport({ disabled, hasContent, onImport }: {
  disabled: boolean; hasContent: boolean; onImport: (selection: ConfluenceSelection) => void;
}) {
  const sourceInput = useRef<HTMLInputElement>(null);
  const [original, setOriginal] = useState<File | null>(null);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [options, setOptions] = useState<ImportOptions>({ sourceLink: "", sourceSpace: "SSRIPTTDoc", sourceVersion: "", sourceUpdated: "", sourceAuthor: "" });
  const [preview, setPreview] = useState<ImportedPage | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const invalidate = () => { setPreview(null); setError(""); };
  const prepare = async () => {
    if (!original) return;
    setReading(true); setError(""); setPreview(null);
    try {
      if (original.size > 10 * 1024 * 1024) throw new Error("Choose a Markdown export smaller than 10 MiB.");
      if (!/\.(md|markdown)$/i.test(original.name)) throw new Error("Choose a .md or .markdown export. ZIP/HTML imports remain in the existing web-folder importer.");
      const names = attachments.map((f) => f.name);
      if (new Set(names).size !== names.length) throw new Error("Two selected attachments have the same filename. Select unique filenames to avoid linking the wrong file.");
      setPreview(convertConfluenceMarkdown(await original.text(), options));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setReading(false); }
  };
  return (
    <section className="rounded-lg border border-indigo-200 bg-white p-3">
      <h2 className="text-sm font-semibold text-slate-800">Import from Confluence — ELI-NP</h2>
      <p className="mt-1 text-xs text-slate-500">Import one Markdown export with its supporting files. Keeps technical wording and headings; no AI rewriting. Saves into the currently selected workspace.</p>
      <fieldset disabled={disabled || reading} className="mt-3 space-y-3 disabled:opacity-50">
        <label className="flex items-start gap-2 text-xs text-slate-700">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          <span>I have selected the intended ELI-NP workspace. This profile does not switch workspaces.</span>
        </label>
        <button type="button" className="rounded border px-3 py-1.5 text-xs" onClick={() => sourceInput.current?.click()}>Choose Markdown export</button>
        <input ref={sourceInput} type="file" accept=".md,.markdown,text/markdown" className="hidden" onChange={(e) => { setOriginal(e.target.files?.[0] ?? null); invalidate(); e.target.value = ""; }} />
        {original && <p className="break-all text-xs">{original.name}</p>}
        <label className="block text-xs font-medium">Supporting PDFs, images and other resources
          <input type="file" multiple className="mt-1 block w-full text-xs" onChange={(e) => { setAttachments(Array.from(e.target.files ?? [])); invalidate(); }} />
        </label>
        <p className="text-xs text-slate-500">File upload limits are enforced by your existing ARGUS server. Matching filenames replace resource links after upload. Other selected files are attached too.</p>
        {([
          ["sourceLink", "Original Confluence page URL"], ["sourceSpace", "Source space"],
          ["sourceVersion", "Version at source"], ["sourceUpdated", "Updated at source (including timezone)"],
          ["sourceAuthor", "Author at source"],
        ] as const).map(([key, label]) => (
          <label key={key} className="block text-xs font-medium text-slate-700">{label}
            <input type="text" value={options[key]} onChange={(e) => { setOptions((p) => ({ ...p, [key]: e.target.value })); invalidate(); }} className="mt-1 w-full rounded border px-2 py-1.5 text-xs" />
          </label>
        ))}
        <button type="button" disabled={!original || !confirmed} onClick={() => void prepare()} className="rounded bg-indigo-700 px-3 py-1.5 text-xs text-white disabled:opacity-40">{reading ? "Reading…" : "Preview import"}</button>
        {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
        {preview && <div className="space-y-2">
          <p className="text-xs font-medium">{preview.title || "No title found — enter one in the form"}</p>
          <ul className="list-disc pl-4 text-xs text-amber-800">{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          <p className="text-xs text-slate-500">Source metadata is retained with the body and under argus_confluence_import. Confirm the document type, facility and source catalogue attributes in the main form. This version does not check server-side duplicates.</p>
          <details className="text-xs"><summary className="cursor-pointer">Preview converted document</summary><div className="mt-2 max-h-96 overflow-auto border p-2"><MarkdownView markdown={preview.body} /></div></details>
          <button type="button" disabled={!confirmed} className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-40" onClick={() => {
            if (hasContent && !window.confirm("Replace the current title and body with this Confluence export?")) return;
            onImport({ page: preview, original: original!, attachments });
          }}>Use in document form</button>
          <p className="text-xs text-slate-500">Review in the main form, then press Create document. The original export is attached unless you uncheck that option. Confidentiality is preserved; sharing with every workspace is turned off.</p>
        </div>}
      </fieldset>
      {disabled && <p className="mt-2 text-xs text-slate-500">This draft already exists. Start a new document for another import.</p>}
    </section>
  );
}
