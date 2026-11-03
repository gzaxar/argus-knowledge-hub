import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, attachmentsApi } from "../../api/client";

const INLINE = /^(image\/|application\/pdf$|text\/plain$)/;

/** Where a link to a file leads (issue #18): the person signed in, the file shown when the browser can show it
 *  (a picture, a PDF), downloaded otherwise — read in its own workspace, whichever one they are working in. */
export function AttachmentPage() {
  const { uid = "" } = useParams();
  const about = useQuery({ queryKey: ["attachment-about", uid], queryFn: () => attachmentsApi.about(uid), retry: false });
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!about.data) return;
    let made: string | null = null;
    let gone = false;
    attachmentsApi.fetchBlobUrl(uid, about.data.workspace_id)
      .then((u) => { if (gone) URL.revokeObjectURL(u); else { made = u; setUrl(u); } })
      .catch(() => setFailed(true));
    return () => { gone = true; if (made) URL.revokeObjectURL(made); };
  }, [about.data, uid]);

  if (about.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (about.isError) {
    const missing = about.error instanceof ApiError && about.error.status === 404;
    return (
      <p role="alert" className="text-sm text-red-700">
        {missing ? "This file does not exist, or you may not read the workspace it belongs to." : "The file could not be opened."}
      </p>
    );
  }
  const a = about.data!;
  const kind = a.mime_type ?? "";
  const inline = INLINE.test(kind);
  const save = () => {
    if (!url) return;
    const link = Object.assign(document.createElement("a"), { href: url, download: a.filename });
    document.body.appendChild(link);
    link.click();
    link.remove();
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{a.filename}</h1>
        <span className="text-sm text-slate-500">
          {kind || "file"}{a.size_bytes != null && ` · ${Math.max(1, Math.round(a.size_bytes / 1024))} KB`} · workspace {a.workspace_id}
        </span>
        {a.asset_uid && <Link to={`/assets/${a.asset_uid}`} className="text-sm text-indigo-700 hover:underline">its record</Link>}
        {a.document_uid && <Link to={`/documents/${a.document_uid}`} className="text-sm text-indigo-700 hover:underline">its document</Link>}
        <button type="button" onClick={save} disabled={!url}
                className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-40">Download</button>
      </div>
      {failed && <p role="alert" className="text-sm text-red-700">The file could not be read.</p>}
      {!url && !failed && <p className="text-sm text-slate-500">Opening the file…</p>}
      {url && kind.startsWith("image/") && (
        <img src={url} alt={a.filename} className="max-h-[80vh] max-w-full rounded border border-slate-200 bg-white" />
      )}
      {url && inline && !kind.startsWith("image/") && (
        <iframe src={url} title={a.filename} className="h-[80vh] w-full rounded border border-slate-200 bg-white" />
      )}
      {url && !inline && <p className="text-sm text-slate-600">This kind of file is not shown here: download it.</p>}
    </div>
  );
}
