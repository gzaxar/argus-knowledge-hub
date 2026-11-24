import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { documentsApi, schemasApi } from "../../api/client";
import { importPaths } from "./paths";
import { WorkspaceScopeBanner } from "../../components/WorkspaceScopeBanner";

/** Upload Markdown as documentation.
 *
 * The unit people have is a folder — a few `.md` files and an `images/`
 * beside them — so the whole thing is accepted at once and the bodies are
 * rewritten to point at the images once they are stored here. Sending only
 * the text would produce documents whose every figure is a broken link.
 */
export function MarkdownImport() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const [files, setFiles] = useState<File[]>([]);
  const [documentTypeUid, setDocumentTypeUid] = useState("");
  const [publish, setPublish] = useState(true);

  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const documentSchemas = (schemas.data ?? []).filter((s) => s.applies_to === "documents");

  const importMutation = useMutation({
    mutationFn: () => documentsApi.importMarkdown(files, documentTypeUid || null, publish),
  });

  const markdownCount = files.filter((f) => /\.(md|markdown|mdown|zip)$/i.test(f.name)).length;
  const result = importMutation.data;

  return (
    <div className="max-w-2xl">
      <Link
        to={importPaths.list(workspaceId!)}
        className="text-sm text-slate-500 hover:underline"
      >
        &larr; Imports
      </Link>

      <h1 className="mt-3 text-2xl font-semibold text-slate-900">Import Markdown</h1>
      <p className="mt-1 text-sm text-slate-500">
        Pick the <code className="rounded bg-slate-100 px-1">.md</code> files and the images
        they use — or one zip of the whole folder. Each file becomes a document; relative
        links to images and attachments are rewritten to the copies stored here, and links
        between the uploaded files become relations.
      </p>
      <WorkspaceScopeBanner action="These documents are created in" />

      <div className="mt-6 space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700">Files</label>
          <input
            type="file"
            multiple
            accept=".md,.markdown,.mdown,.zip,image/*,.pdf,.csv,.txt,.svg,.dxf,.dwg"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <p className="mt-2 text-xs text-slate-500">
            …or pick the whole folder, which keeps the paths intact:
          </p>
          <input
            type="file"
            // Not in the React types, but supported by every browser this
            // app runs in; picking a folder preserves each file's path
            // inside it, so links like images/layout.png match exactly.
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="mt-1 w-full rounded border border-dashed border-slate-300 px-3 py-2 text-sm"
          />
          {files.length > 0 && (
            <p className="mt-1 text-xs text-slate-500">
              {files.length} file{files.length === 1 ? "" : "s"} selected,{" "}
              {markdownCount === 0
                ? "none of them Markdown or a zip — nothing would be imported"
                : `${markdownCount} of them Markdown or a zip`}
              .
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">Type</label>
          <select
            value={documentTypeUid}
            onChange={(e) => setDocumentTypeUid(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Decide per file (front matter, then the title)</option>
            {documentSchemas.map((s) => (
              <option key={s.uid} value={s.uid}>
                {s.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            A file's own <code className="rounded bg-slate-100 px-1">type:</code> in its front
            matter is used when there is one; pick a type here to put everything in the same
            place instead.
          </p>
        </div>

        <PublishChoice publish={publish} onChange={setPublish} />

        <button
          onClick={() => importMutation.mutate()}
          disabled={markdownCount === 0 || importMutation.isPending}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {importMutation.isPending ? "Importing…" : "Import"}
        </button>

        {importMutation.isError && (
          <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {(importMutation.error as Error).message || "The import failed."}
          </p>
        )}

        {result && (
          <div className="rounded border border-slate-200 bg-white p-4 text-sm">
            <p className="font-medium text-slate-900">
              {result.documents} document{result.documents === 1 ? "" : "s"} imported
            </p>
            <p className="mt-1 text-slate-600">
              {result.attachments} file{result.attachments === 1 ? "" : "s"} attached ·{" "}
              {result.relations} link{result.relations === 1 ? "" : "s"} between them
            </p>
            {result.skipped.length > 0 && (
              <ul className="mt-2 space-y-0.5 border-t border-slate-100 pt-2 text-xs text-amber-700">
                {result.skipped.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
            <Link
              to="/documents"
              className="mt-3 inline-block rounded bg-slate-900 px-3 py-1.5 text-xs text-white"
            >
              See the documents
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

/** Published as they are at the source, or drafts that go through review — for procedures, say, that become
 *  controlled documents here. Shared by the Markdown upload and the Confluence and DokuWiki imports. */
export function PublishChoice({ publish, onChange }: { publish: boolean; onChange: (v: boolean) => void }) {
  return (
    <fieldset className="space-y-1 text-sm">
      <legend className="font-medium text-slate-700">The documents arrive</legend>
      <label className="flex items-start gap-2">
        <input type="radio" name="publish" checked={publish} onChange={() => onChange(true)} className="mt-1" />
        <span>Published, as they are at the source
          <span className="block text-xs text-slate-500">For pages already in use: readable at once, as informative
            documents.</span></span>
      </label>
      <label className="flex items-start gap-2">
        <input type="radio" name="publish" checked={!publish} onChange={() => onChange(false)} className="mt-1" />
        <span>As drafts to review
          <span className="block text-xs text-slate-500">Each one is reviewed, approved and published like a document
            written here — for procedures that must be validated first.</span></span>
      </label>
    </fieldset>
  );
}
