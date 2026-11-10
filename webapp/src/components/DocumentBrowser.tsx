import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, documentNavigationApi as nav, schemasApi } from "../api/client";
import type { DocumentNavigationNode } from "../api/types";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import { useWorkspaceNames } from "../api/useWorkspaceNames";
import { useRights } from "../lib/permissions";
import { ancestorPath, branchCounts, descendants, previewBody, treeRows } from "../lib/documentNavigation";
import { MarkdownView } from "./MarkdownView";
import { DocumentTypeIcon } from "./DocumentTypeIcon";

const button = "rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const active = "rounded-md bg-slate-900 px-3 py-1.5 text-sm text-white";
const field = "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm";
// Match the existing TypeExplorer: text-xs navigation, text-sm document rows/body.
const navigationField = "w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-xs";
const navigationTab = "rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50";
const navigationTabActive = "rounded-md bg-slate-900 px-2 py-1 text-xs text-white";
const stateLabels: Record<string, string> = { draft: "Draft", in_review: "In review", approved: "Approved", published: "Published", superseded: "Superseded", retired: "Retired" };
const accessLabels: Record<string, string> = { interno: "Interno", pubblico: "Pubblico", riservato: "Riservato" };

function NodeIcon({ folder }: { folder: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5 shrink-0">
    {folder ? <path d="M3 6h7l2 2h9v11H3z" /> : <><path d="M6 3h9l4 4v14H6zM15 3v5h4" /><path d="M9 12h7M9 16h7" /></>}
  </svg>;
}

type Dialog = { kind: "create" | "folder" | "move"; uid?: string } | null;

export function DocumentBrowser({ onFullTable }: { onFullTable: () => void }) {
  const workspaceId = useCurrentWorkspaceId();
  const workspaceName = useWorkspaceNames();
  const rights = useRights();
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("node") ?? "";
  const tab = params.get("nav") === "types" ? "types" : "hierarchy";
  const panel = params.get("panel") === "list" ? "list" : "page";
  const revisionUid = params.get("rev") || undefined;
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(new Set<string>());
  const [dialog, setDialog] = useState<Dialog>(null);
  const dialogRef = useRef<HTMLFormElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const activeType = params.get("type_group");
  const [name, setName] = useState("");
  const [destination, setDestination] = useState("root");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const snapshot = useQuery({ queryKey: ["document-navigation", workspaceId], queryFn: nav.snapshot, enabled: !!workspaceId });
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });
  const nodes = snapshot.data?.nodes ?? [];
  const documents = snapshot.data?.documents ?? [];
  const totalDocuments = new Set(documents.map((d) => d.uid)).size;
  const selected = nodes.find((n) => n.id === selectedId);
  const selectedDoc = selected?.kind === "document" ? documents.find((d) => d.uid === selected.uid) : undefined;
  const typeNames = new Map((schemas.data ?? []).map((s) => [s.uid, s.name]));
  const typeIcons = new Map((schemas.data ?? []).map((s) => [s.uid, s.icon_uid]));
  const documentById = new Map(documents.map((d) => [d.uid, d]));
  const iconForNode = (node: DocumentNavigationNode) => {
    const uid = node.id.startsWith("type:") ? node.id.slice(5) : documentById.get(node.uid)?.document_type_uid;
    return uid ? typeIcons.get(uid) : undefined;
  };
  const choose = (id: string, replace = false) => {
    const next = new URLSearchParams(params); next.set("node", id); next.delete("rev");
    setParams(next, { replace });
  };
  const option = (key: string, value: string) => {
    const next = new URLSearchParams(params); next.set(key, value); setParams(next);
  };
  useEffect(() => { setExpanded(new Set()); setDialog(null); setQuery(""); }, [workspaceId]);
  useEffect(() => {
    if (!snapshot.data) return;
    if (!selected) {
      const rows = treeRows(snapshot.data.nodes, new Set(snapshot.data.nodes.map((n) => n.id)), "");
      const first = rows.find((r) => r.node.kind === "document")?.node ?? rows[0]?.node;
      if (first) choose(first.id, true);
    } else {
      const path = ancestorPath(snapshot.data.nodes, selected.id);
      setExpanded((prev) => new Set([...prev, ...path.map((n) => n.id), ...(tab === "types" && selectedDoc ? [`type:${selectedDoc.document_type_uid ?? "none"}`] : [])]));
    }
  }, [snapshot.data, selectedId, tab]);
  useEffect(() => {
    if (!dialog) return;
    const previous = returnFocus.current;
    dialogRef.current?.querySelector<HTMLElement>("input,select,button")?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [dialog]);

  const preview = useQuery({
    queryKey: ["document-browser-preview", workspaceId, selectedDoc?.uid, revisionUid],
    queryFn: () => nav.preview(selectedDoc!.uid, revisionUid), enabled: !!selectedDoc, retry: false,
  });
  const typeNodes = useMemo(() => {
    const groups = new Map<string, DocumentNavigationNode>();
    const result: DocumentNavigationNode[] = [];
    for (const doc of documents) {
      const key = `type:${doc.document_type_uid ?? "none"}`;
      if (!groups.has(key)) groups.set(key, { id: key, uid: key, kind: "group", title: doc.document_type_uid ? typeNames.get(doc.document_type_uid) ?? "Unknown type" : "No type", parent_id: null });
      result.push({ id: `d:${doc.uid}`, uid: doc.uid, kind: "document", title: doc.title, parent_id: key });
    }
    return [...groups.values(), ...result];
  }, [snapshot.data, schemas.data]);
  const browsingNodes = tab === "types" ? typeNodes : nodes;
  const counts = useMemo(() => branchCounts(browsingNodes), [browsingNodes]);
  const rows = treeRows(browsingNodes.map((n) => ({ ...n, searchText: `${n.title} ${n.kind === "document" ? documents.find((d) => d.uid === n.uid)?.code ?? "" : ""}` })), expanded, query);
  const crumbs = selected ? ancestorPath(nodes, selected.id) : [];
  const branch = selected ? descendants(nodes, selected.id) : new Set(nodes.map((n) => n.id));
  const listDocs = documents.filter((d) => branch.has(`d:${d.uid}`));
  const visibleListDocs = (activeType ? documents.filter((d) => (d.document_type_uid ?? "none") === activeType) : listDocs)
    .filter((d) => !query.trim() || `${d.title} ${d.code}`.toLowerCase().includes(query.trim().toLowerCase()));
  const ownDoc = selectedDoc?.workspace_id === workspaceId;
  const revision = preview.data?.revision;
  const attrs = revision?.attributes ?? {};
  const summary = typeof attrs.argus_summary === "string" ? attrs.argus_summary : "";
  const isConfluence = selectedDoc?.source === "confluence" || attrs.argus_source === "confluence" || attrs.argus_source === "Confluence" || !!attrs.argus_confluence_import;
  const message = (e: unknown) => e instanceof ApiError ? e.detail ?? "The change could not be saved." : e instanceof Error ? e.message : "The change could not be saved.";
  const openDialog = (kind: "create" | "folder" | "move") => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setError(""); setName(selected?.kind === "folder" && kind === "folder" ? selected.title : "");
    const parent = kind === "create" ? (selected?.kind === "folder" ? selected.id : "root") : selected?.parent_id;
    setDestination(parent?.startsWith("f:") || parent?.startsWith("d:") ? parent : "root");
    setDialog({ kind, uid: selected?.uid });
  };
  const refresh = () => client.invalidateQueries({ queryKey: ["document-navigation", workspaceId] });
  const saveDialog = async () => {
    if (!dialog || busy) return;
    setBusy(true); setError("");
    try {
      let newId: string | undefined;
      if (dialog.kind === "create" || dialog.kind === "folder") {
        const parent = destination.startsWith("f:") ? destination.slice(2) : null;
        const result = dialog.kind === "create" ? await nav.createFolder(name.trim(), parent) : await nav.updateFolder(dialog.uid!, name.trim(), parent);
        if (result) newId = `f:${result.uid}`;
      } else if (destination === "source") await nav.resetLocation(dialog.uid!);
      else await nav.locate(dialog.uid!, destination.startsWith("f:") ? { folder_uid: destination.slice(2) } : destination.startsWith("d:") ? { parent_document_uid: destination.slice(2) } : {});
      await refresh(); setDialog(null); if (newId) choose(newId);
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  };
  const removeFolder = async () => {
    if (!selected || selected.kind !== "folder" || !window.confirm(`Delete the empty folder “${selected.title}”? Documents are not deleted.`)) return;
    setBusy(true); setError("");
    try { await nav.deleteFolder(selected.uid); await refresh(); setDialog(null); }
    catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  };
  const newDocumentUrl = selected?.kind === "folder" ? `/documents/new?folder=${encodeURIComponent(selected.uid)}` : selectedDoc && ownDoc ? `/documents/new?parent_document=${encodeURIComponent(selectedDoc.uid)}` : "/documents/new";
  const prohibited = dialog?.kind === "create" ? new Set<string>() : selected ? descendants(nodes, selected.id) : new Set<string>();

  return <div className="mx-auto max-w-[1600px] space-y-4">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-baseline gap-2"><h1 className="text-xl font-semibold text-slate-900 sm:text-2xl">Documents</h1><span className="text-sm tabular-nums text-slate-500" aria-label="Total documents">({snapshot.data ? totalDocuments : "…"})</span></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={onFullTable}>Full table</button>
        <Link className={button} to="/documents/templates">Templates</Link>
        {rights.can_create_documents && <><button type="button" className={button} onClick={() => openDialog("create")} disabled={!snapshot.data}>+ Folder</button><Link className={active} to="/documents/new">New document</Link></>}
      </div>
    </header>
    {snapshot.isLoading && <p role="status" className="text-sm text-slate-500">Loading documents…</p>}
    {snapshot.isError && <div role="alert" className="rounded border border-rose-200 bg-rose-50 p-4 text-sm">The document browser could not load. <button className="underline" onClick={() => void snapshot.refetch()}>Retry</button> or <button className="underline" onClick={onFullTable}>open the full table</button>.</div>}
    {snapshot.data && <div className="grid items-start gap-4 lg:grid-cols-[19rem_minmax(0,1fr)]">
      <aside aria-label="Document navigation" className="rounded-lg border border-slate-200 bg-white p-3 lg:sticky lg:top-2">
        <div className="mb-3 flex gap-1 rounded-md border border-slate-200 p-1">
          <button type="button" aria-pressed={tab === "hierarchy"} className={`flex-1 ${tab === "hierarchy" ? navigationTabActive : navigationTab}`} onClick={() => { const next = new URLSearchParams(params); next.set("nav", "hierarchy"); next.delete("type_group"); setParams(next); }}>Hierarchy</button>
          <button type="button" aria-pressed={tab === "types"} className={`flex-1 ${tab === "types" ? navigationTabActive : navigationTab}`} onClick={() => { option("nav", "types"); setExpanded((prev) => new Set([...prev, ...typeNodes.filter((n) => n.kind === "group").map((n) => n.id)])); }}>Document types</button>
        </div>
        <p className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-600"><span className="tabular-nums">({totalDocuments})</span><span>Total documents</span></p>
        <input type="search" aria-label="Find a document or folder" placeholder="Find a document or folder…" value={query} onChange={(e) => setQuery(e.target.value)} className={navigationField} />
        <div className="my-3 flex justify-between gap-2 text-xs text-indigo-700">
          <button onClick={() => setExpanded(new Set([...nodes, ...typeNodes].map((n) => n.id)))}>Expand all</button>
          <button onClick={() => setExpanded(new Set())}>Collapse all</button>
        </div>
        <div className="max-h-[60vh] overflow-auto lg:max-h-[calc(100vh-19rem)]">
          {rows.map(({ node, depth, hasChildren, open }) => <div key={node.id} className="flex items-start gap-1 py-0.5" style={{ paddingLeft: Math.min(depth, 10) * 14 }}>
            {hasChildren ? <button type="button" className="mt-1.5 w-4 shrink-0 text-slate-500" aria-label={`${open ? "Collapse" : "Expand"} ${node.title}`} aria-expanded={open} onClick={() => setExpanded((prev) => { const next = new Set(prev); if (next.has(node.id)) next.delete(node.id); else next.add(node.id); return next; })}>{open ? "▾" : "▸"}</button> : <span className="w-4 shrink-0" />}
            <button type="button" aria-current={(activeType ? node.id === `type:${activeType}` : selectedId === node.id) ? "page" : undefined} title={node.title} className={`flex min-w-0 flex-1 items-start gap-2 rounded-md px-2 py-1 text-left text-xs ${(activeType ? node.id === `type:${activeType}` : selectedId === node.id) ? "bg-indigo-50 text-indigo-800 ring-1 ring-indigo-200" : "text-slate-700 hover:bg-slate-50"}`} onClick={() => {
              if (node.id.startsWith("type:")) { const next = new URLSearchParams(params); next.set("type_group", node.id.slice(5)); next.set("panel", "list"); setParams(next); }
              else { const next = new URLSearchParams(params); next.delete("type_group"); next.set("node", node.id); next.delete("rev"); setParams(next); }
            }}>{node.kind === "document" || node.id.startsWith("type:") ? <DocumentTypeIcon iconUid={iconForNode(node)} /> : <NodeIcon folder />}{(node.kind !== "document" || hasChildren) && <span className="shrink-0 tabular-nums text-slate-500" title="Documents below this branch">({counts.get(node.id) ?? 0})</span>}<span className="min-w-0 break-words">{node.title}</span></button>
          </div>)}
          {!rows.length && <p className="p-3 text-sm text-slate-500">{query ? "No matching documents or folders." : "No documents yet. Create a folder or a document to start."}</p>}
        </div>
      </aside>
      <main className="min-w-0 space-y-3">
        <nav aria-label="Document breadcrumbs" className="flex flex-wrap items-center gap-1 text-xs leading-6 text-indigo-700"><span>Documents</span>{activeType ? <span> › Document types › {typeNames.get(activeType) ?? "No type"}</span> : crumbs.map((n) => <span key={n.id} className="flex items-center gap-1"><span aria-hidden="true" className="text-slate-400">›</span><button type="button" className="text-left hover:underline" onClick={() => choose(n.id)}>{n.title}</button></span>)}</nav>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 text-sm text-slate-500">{(activeType || selectedDoc) && <DocumentTypeIcon iconUid={typeIcons.get(activeType ?? selectedDoc?.document_type_uid ?? "")} />}{activeType ? typeNames.get(activeType) ?? "No type" : selectedDoc ? typeNames.get(selectedDoc.document_type_uid ?? "") ?? "No type" : selected?.title ?? "Document browser"}</span>
          <div className="flex gap-1">{selected?.kind === "folder" && rights.can_modify_documents && <button type="button" className={button} onClick={() => openDialog("folder")}>Edit folder</button>}<button aria-pressed={panel === "page"} className={panel === "page" ? active : button} onClick={() => { const next = new URLSearchParams(params); next.delete("type_group"); next.set("panel", "page"); setParams(next); }}>Page</button><button aria-pressed={panel === "list"} className={panel === "list" ? active : button} onClick={() => option("panel", "list")}>List</button></div>
        </div>
        {snapshot.data.warnings.map((w) => <p key={w} role="status" className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{w}</p>)}
        {panel === "list" ? <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm"><caption className="sr-only">Documents in the selected branch or type</caption><thead className="bg-slate-50 text-xs uppercase text-slate-500"><tr><th className="p-3">Title</th><th className="p-3">Type</th><th className="p-3">Publication</th></tr></thead>
            <tbody>{visibleListDocs.map((d) => <tr key={d.uid} className="border-t border-slate-100"><td className="p-3"><button className="text-left font-medium hover:underline" onClick={() => { const next = new URLSearchParams(params); next.set("node", `d:${d.uid}`); next.set("panel", "page"); next.delete("type_group"); next.delete("rev"); setParams(next); }}>{d.title}</button><div className="text-xs text-slate-400">{d.code}</div></td><td className="p-3"><span className="inline-flex items-center gap-1.5"><DocumentTypeIcon iconUid={typeIcons.get(d.document_type_uid ?? "")} />{typeNames.get(d.document_type_uid ?? "") ?? "No type"}</span></td><td className="p-3">{d.current_revision_uid ? "Published revision available" : "Not published"}</td></tr>)}{!visibleListDocs.length && <tr><td colSpan={3} className="p-6 text-center text-slate-500">No documents match this branch and search.</td></tr>}</tbody>
          </table>
        </div> : selectedDoc ? <>
          {preview.isLoading && <p role="status" className="p-4 text-sm text-slate-500">Loading document…</p>}
          {preview.isError && <p role="alert" className="rounded border border-rose-200 p-4 text-sm text-rose-800">The document preview could not be loaded. <button className="underline" onClick={() => void preview.refetch()}>Retry</button>.</p>}
          {preview.data && <article className="space-y-4 rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
            <h2 className="break-words text-2xl font-semibold text-slate-900">{selectedDoc.title}</h2>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1.5 rounded border border-slate-200 px-2 py-1"><DocumentTypeIcon iconUid={typeIcons.get(selectedDoc.document_type_uid ?? "")} />{typeNames.get(selectedDoc.document_type_uid ?? "") ?? "No type"}</span>
              {revision && <span className={`rounded px-2 py-1 ${revision.state === "published" ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-900"}`}>{stateLabels[revision.state] ?? revision.state} · revision {revision.revision_number}</span>}
              {isConfluence && <span className="rounded bg-emerald-50 px-2 py-1 text-emerald-800">From Confluence</span>}
              {!ownDoc && <span className="rounded bg-sky-50 px-2 py-1 text-sky-800">Shared · read only here</span>}
            </div>
            <div className="flex flex-wrap items-center gap-3 border-y border-slate-100 py-3 text-xs text-slate-600">
              <span>Workspace: {workspaceName(selectedDoc.workspace_id)}</span>{typeof attrs.argus_source_space === "string" && <span>Source space: {attrs.argus_source_space}</span>}<span>Access: {accessLabels[selectedDoc.confidentiality] ?? selectedDoc.confidentiality}</span>
              {preview.data.revisions.length > 0 && <label className="ml-auto">Revision <select aria-label="Preview revision" className="ml-1 rounded border border-slate-200 bg-white p-1" value={revision?.uid ?? ""} onChange={(e) => option("rev", e.target.value)}>{preview.data.revisions.map((r) => <option key={r.uid} value={r.uid}>{r.revision_number} · {stateLabels[r.state]}</option>)}</select></label>}
            </div>
            {revision && revision.state !== "published" && selectedDoc.current_revision_uid && <p className="text-xs text-slate-500">You are viewing an unpublished revision. A published revision is also available in the revision selector.</p>}
            {summary && <section className="rounded-md bg-slate-50 p-3"><h3 className="mb-1 text-sm font-semibold">Summary</h3><p className="whitespace-pre-wrap text-sm text-slate-700">{summary}</p></section>}
            {revision ? <MarkdownView markdown={previewBody(revision.body_markdown ?? "", selectedDoc.title)} /> : <p className="text-sm text-slate-500">No readable revision is available.</p>}
            {!!revision?.steps?.length && <section><h3 className="font-semibold">Steps</h3><ol className="ml-5 list-decimal space-y-2 text-sm">{revision.steps.map((s, i) => <li key={i}>{s.testo}</li>)}</ol></section>}
            <footer className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
              {ownDoc && rights.can_create_documents && <Link to={newDocumentUrl} className={button}>+ Add child document</Link>}
              {ownDoc && rights.can_modify_documents && <button type="button" className={button} onClick={() => openDialog("move")}>Move in hierarchy</button>}
              <Link className={`${button} ml-auto`} to={`/documents/${selectedDoc.uid}${revision ? `?revision=${encodeURIComponent(revision.uid)}` : ""}`}>Open full document</Link>
            </footer>
          </article>}
        </> : <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-6"><h2 className="text-xl font-semibold">{selected?.title ?? "Documents"}</h2><p className="text-sm text-slate-500">{listDocs.length} document(s) in this branch. Select a document to read it, or use List to browse its contents.</p><div className="flex flex-wrap gap-2">{rights.can_create_documents && <Link to={newDocumentUrl} className={button}>+ New document here</Link>}{selected?.kind === "folder" && rights.can_modify_documents && <button className={button} onClick={() => openDialog("folder")}>Edit folder</button>}</div></section>}
      </main>
    </div>}
    {dialog && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4" onKeyDown={(e) => { if (e.key === "Escape" && !busy) setDialog(null); }}>
      <form ref={dialogRef} onKeyDown={(e) => {
        if (e.key !== "Tab") return;
        const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>("input:not(:disabled),select:not(:disabled),button:not(:disabled)") ?? []);
        if (!controls.length) { e.preventDefault(); return; }
        const first = controls[0], last = controls[controls.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }} role="dialog" aria-modal="true" aria-labelledby="document-navigation-dialog" className="w-full max-w-lg space-y-4 rounded-lg bg-white p-5 shadow-xl" onSubmit={(e) => { e.preventDefault(); void saveDialog(); }}>
        <h2 id="document-navigation-dialog" className="text-lg font-semibold">{dialog.kind === "create" ? "New folder" : dialog.kind === "folder" ? "Edit folder" : "Move document in hierarchy"}</h2>
        {dialog.kind !== "move" && <label className="block space-y-1 text-sm"><span>Folder name</span><input disabled={busy} autoFocus required maxLength={240} value={name} onChange={(e) => setName(e.target.value)} className={field} /></label>}
        <label className="block space-y-1 text-sm"><span>{dialog.kind === "move" ? "Place under" : "Parent folder"}</span><select disabled={busy} value={destination} onChange={(e) => setDestination(e.target.value)} className={field}>
          <option value="root">{dialog.kind === "move" ? "Unfiled documents" : "Top level"}</option>
          {dialog.kind === "move" && <option value="source">Use relationship / imported parent</option>}
          {nodes.filter((n) => n.kind === "folder" && !prohibited.has(n.id)).map((n) => <option key={n.id} value={n.id}>{ancestorPath(nodes, n.id).map((p) => p.title).join(" / ")}</option>)}
          {dialog.kind === "move" && nodes.filter((n) => n.kind === "document" && !prohibited.has(n.id) && documents.find((d) => d.uid === n.uid)?.workspace_id === workspaceId).map((n) => <option key={n.id} value={n.id}>Document: {n.title}</option>)}
        </select></label>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <div className="flex flex-wrap gap-2"><button type="submit" disabled={busy} className={active}>{busy ? "Saving…" : "Save"}</button><button type="button" disabled={busy} className={button} onClick={() => setDialog(null)}>Cancel</button>{dialog.kind === "folder" && rights.can_delete_documents && <button type="button" disabled={busy} className={`${button} ml-auto text-rose-700`} onClick={() => void removeFolder()}>Delete empty folder</button>}</div>
      </form>
    </div>}
  </div>;
}
