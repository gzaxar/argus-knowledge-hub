import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { documentsApi, membersApi, schemasApi, tokensApi } from "../../api/client";
import type { AppDocument } from "../../api/types";
import { BrowsePage, SearchBox, ToolbarSelect, useBrowseParams } from "../../components/browse/Browse";
import { countBy, TypeExplorer, typeFamily } from "../../components/browse/TypeExplorer";
import { DocumentTools, DocumentViewSwitch } from "../../components/DocumentViews";
import { DocumentTypeIcon } from "../../components/DocumentTypeIcon";
import {
  BOARD_LABELS, BOARD_STATES, BoardColumn, BoardMove, boardColumn, boardMove, publishedRecently,
} from "../../lib/documentBoard";
import { askText, notify } from "../../lib/dialogs";
import { useRights } from "../../lib/permissions";

const ACCENT: Record<string, string> = {
  draft: "border-t-slate-400", in_review: "border-t-amber-500", approved: "border-t-sky-500",
  published: "border-t-green-500", retired: "border-t-slate-300",
};
const MOVE_WORDS: Record<BoardMove, string> = {
  submit: "Submit for review", withdraw: "Withdraw from review", reject: "Reject (back to draft)",
  approve: "Approve", publish: "Publish",
};
const MOVE_TO: Record<BoardMove, BoardColumn> = {
  submit: "in_review", withdraw: "draft", reject: "draft", approve: "approved", publish: "published",
};
const RECENT_DAYS = 30;

type GroupBy = "state" | "type" | "owner";

/** Documents as a board of their review: Draft → In review → Approved → Published. Dropping a card is the same
 * submit, withdraw, reject, approve or publish as on the document, with the same rules. */
export function DocumentBoard() {
  const queryClient = useQueryClient();
  const rights = useRights();
  const { get, set } = useBrowseParams();
  const q = get("q");
  const typeUid = get("type") || null;
  const groupBy = (get("group") || "state") as GroupBy;
  const allPublished = get("published") === "all";
  const showRetired = get("retired") === "1";
  const [dragging, setDragging] = useState<AppDocument | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const documents = useQuery({ queryKey: ["documents"], queryFn: () => documentsApi.list() });
  const schemas = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list, staleTime: 60_000 });
  const members = useQuery({ queryKey: ["members"], queryFn: membersApi.directory, staleTime: 60_000 });
  const profile = useQuery({ queryKey: ["my-profile"], queryFn: tokensApi.profile, staleTime: 60_000 });
  const me = profile.data?.user?.id ?? null;

  const documentSchemas = useMemo(() => (schemas.data ?? []).filter((s) => s.applies_to === "documents"), [schemas.data]);
  const typeName = useMemo(() => new Map(documentSchemas.map((s) => [s.uid, s.name])), [documentSchemas]);
  const typeIcons = useMemo(() => new Map(documentSchemas.map((s) => [s.uid, s.icon_uid])), [documentSchemas]);
  const family = useMemo(() => typeFamily(documentSchemas, typeUid), [documentSchemas, typeUid]);
  const person = (id: string | null) => (id ? members.data?.find((m) => m.user_id === id)?.name
    || members.data?.find((m) => m.user_id === id)?.email || "Someone" : null);
  const counts = useMemo(() => countBy(documents.data, (d) => d.document_type_uid), [documents.data]);

  const visible = useMemo(() => {
    const n = q.trim().toLowerCase();
    return (documents.data ?? []).filter((d) => {
      if (n && !`${d.title} ${d.code}`.toLowerCase().includes(n)) return false;
      if (family && !(d.document_type_uid && family.has(d.document_type_uid))) return false;
      const column = boardColumn(d);
      if (column === "retired" && !showRetired) return false;
      if (column === "published" && !allPublished && !publishedRecently(d, RECENT_DAYS)) return false;
      return true;
    });
  }, [documents.data, q, family, showRetired, allPublished]);
  const hiddenPublished = useMemo(() => (documents.data ?? []).filter((d) =>
    boardColumn(d) === "published" && !publishedRecently(d, RECENT_DAYS)).length, [documents.data]);

  const { columns, cards } = useMemo(() => {
    const grouped = new Map<string, AppDocument[]>();
    const keyOf = (d: AppDocument) => groupBy === "state" ? boardColumn(d)
      : groupBy === "type" ? d.document_type_uid ?? "__none__" : d.owner_user_id ?? "__none__";
    for (const d of visible) {
      const k = keyOf(d);
      if (!grouped.has(k)) grouped.set(k, []);
      grouped.get(k)!.push(d);
    }
    for (const list of grouped.values()) list.sort((a, b) =>
      (b.latest_revision?.updated_at ?? b.updated_at).localeCompare(a.latest_revision?.updated_at ?? a.updated_at));
    let keys: string[];
    if (groupBy === "state") keys = [...BOARD_STATES, ...(showRetired ? ["retired"] : [])];
    else {
      const name = (k: string) => (groupBy === "type" ? typeName.get(k) : person(k)) ?? k;
      keys = [...grouped.keys()].filter((k) => k !== "__none__").sort((a, b) => name(a).localeCompare(name(b)));
      if (grouped.has("__none__")) keys.push("__none__");
    }
    return { columns: keys, cards: grouped };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, groupBy, showRetired, typeName, members.data]);

  const label = (k: string) => groupBy === "state" ? BOARD_LABELS[k as BoardColumn]
    : k === "__none__" ? (groupBy === "type" ? "No type" : "No owner")
    : groupBy === "type" ? typeName.get(k) ?? "Unknown type" : person(k) ?? "Someone";

  const check = (d: AppDocument, to: BoardColumn) => boardMove(boardColumn(d), to, {
    canModify: rights.can_modify_documents, canApprove: rights.can_approve_documents, me,
    author: d.latest_revision?.authored_by ?? null, hasRevision: !!d.latest_revision,
  });

  const move = useMutation({
    mutationFn: async ({ d, action, comment }: { d: AppDocument; action: BoardMove; comment?: string }) => {
      const rev = d.latest_revision!.uid;
      if (action === "submit") return documentsApi.submitRevision(d.uid, rev);
      if (action === "withdraw") return documentsApi.withdrawRevision(d.uid, rev);
      if (action === "reject") return documentsApi.rejectRevision(d.uid, rev, comment ?? "");
      if (action === "approve") return documentsApi.approveRevision(d.uid, rev);
      return documentsApi.publishRevision(d.uid, rev);
    },
    // The board is the whole page: the card moves at once, then the refetch settles it.
    onMutate: async ({ d, action }) => {
      await queryClient.cancelQueries({ queryKey: ["documents"] });
      const previous = queryClient.getQueryData<AppDocument[]>(["documents"]);
      const state = MOVE_TO[action];
      const now = new Date().toISOString();
      queryClient.setQueryData<AppDocument[]>(["documents"], (old) => (old ?? []).map((x) => x.uid !== d.uid || !x.latest_revision ? x : {
        ...x,
        current_revision_uid: action === "publish" ? x.latest_revision.uid : x.current_revision_uid,
        latest_revision: { ...x.latest_revision, state: state as "draft", updated_at: now,
                           published_at: action === "publish" ? now : x.latest_revision.published_at },
      }));
      return { previous };
    },
    onError: (e, _v, context) => {
      if (context?.previous) queryClient.setQueryData(["documents"], context.previous);
      notify(e instanceof Error ? e.message : "The document could not be moved.", "error");
    },
    onSettled: (_r, _e, { d }) => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.invalidateQueries({ queryKey: ["document-navigation"] });
      queryClient.invalidateQueries({ queryKey: ["document-current", d.uid] });
      queryClient.invalidateQueries({ queryKey: ["document", d.uid] });
    },
  });

  const run = async (d: AppDocument, action: BoardMove) => {
    let comment: string | undefined;
    if (action === "reject") {
      const why = await askText(`Why is “${d.title}” sent back to draft? (required)`);
      if (!why?.trim()) return;
      comment = why.trim();
    }
    move.mutate({ d, action, comment });
  };

  const draggingCheck = (to: string) => (dragging && groupBy === "state" ? check(dragging, to as BoardColumn) : null);

  return (
    <BrowsePage
      title="Documents"
      count={documents.data ? `(${visible.length}${visible.length !== documents.data.length ? ` of ${documents.data.length}` : ""})` : undefined}
      storageKey="documents"
      primary={rights.can_create_documents && (
        <Link to="/documents/new" className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">New document</Link>
      )}
      actions={<DocumentTools rights={rights} />}
      explorerLabel="Type"
      explorerSummary={typeUid ? typeName.get(typeUid) : undefined}
      explorer={<TypeExplorer appliesTo="documents" counts={counts} total={documents.data?.length ?? 0} selected={typeUid}
                              onSelect={(uid) => set({ type: uid })} />}
      toolbar={
        <>
          <SearchBox value={q} onChange={(v) => set({ q: v })} label="Search documents" placeholder="Search by title or code…" />
          <ToolbarSelect label="Group by" value={groupBy} onChange={(v) => set({ group: v === "state" ? null : v })}>
            <option value="state">Review state</option>
            <option value="type">Type</option>
            <option value="owner">Owner</option>
          </ToolbarSelect>
          <ToolbarSelect label="Published" value={allPublished ? "all" : ""} onChange={(v) => set({ published: v || null })}>
            <option value="">Last {RECENT_DAYS} days</option>
            <option value="all">Any time</option>
          </ToolbarSelect>
          <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-slate-600">
            <input type="checkbox" checked={showRetired} onChange={(e) => set({ retired: e.target.checked ? "1" : null })} />
            Show retired
          </label>
          <DocumentViewSwitch current="board" />
        </>
      }
    >
      <p className="text-sm text-slate-500" role="status">
        {dragging && groupBy === "state"
          ? "Drop on a highlighted column: the move is the document's own review step."
          : groupBy === "state"
            ? "Drag a document to the next column — submit, approve, publish — or use its menu."
            : "Grouped for viewing: moves are made when grouped by review state."}
        {groupBy === "state" && !allPublished && hiddenPublished > 0 && (
          <> {hiddenPublished} published earlier {hiddenPublished === 1 ? "is" : "are"} hidden — <button type="button" className="underline" onClick={() => set({ published: "all" })}>show them</button>.</>
        )}
      </p>
      {documents.isLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {documents.isError && <p role="alert" className="text-sm text-rose-700">The documents could not be loaded.</p>}
      {documents.data && (
        <div className="flex min-h-0 gap-3 overflow-x-auto pb-4" aria-label="Documents board">
          {columns.map((key) => {
            const items = cards.get(key) ?? [];
            const verdict = draggingCheck(key);
            const allowed = !!verdict && "move" in verdict;
            return (
              <section key={key} aria-label={label(key)}
                onDragOver={(e) => { if (!allowed) return; e.preventDefault(); setOver(key); }}
                onDragLeave={() => setOver((c) => (c === key ? null : c))}
                onDrop={(e) => {
                  e.preventDefault(); setOver(null);
                  const d = dragging; setDragging(null);
                  if (d && verdict && "move" in verdict) void run(d, verdict.move);
                }}
                title={verdict && "refused" in verdict ? verdict.refused : undefined}
                className={`flex min-w-[14rem] flex-1 basis-0 flex-col rounded-lg border border-t-4 bg-slate-50 transition-opacity ${ACCENT[key] ?? "border-t-slate-300"} ${
                  over === key ? "border-indigo-400 bg-indigo-50" : allowed ? "border-indigo-200" : "border-slate-200"} ${
                  dragging && groupBy === "state" && !allowed && verdict ? "opacity-50" : ""}`}>
                <div className="flex items-center justify-between px-3 py-2">
                  <h2 className="text-sm font-medium text-slate-700">{label(key)}</h2>
                  <span className="rounded bg-white px-1.5 py-0.5 text-xs tabular-nums text-slate-500">{items.length}</span>
                </div>
                <div className="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto px-2 pb-2 lg:max-h-[calc(100vh-16rem)]">
                  {items.map((d) => {
                    const r = d.latest_revision;
                    const column = boardColumn(d);
                    const moves = groupBy === "state" && column !== "retired"
                      ? BOARD_STATES.map((to) => check(d, to)).filter((c): c is { move: BoardMove } => !!c && "move" in c)
                      : [];
                    return (
                      <article key={d.uid} draggable={groupBy === "state" && moves.length > 0}
                        onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; setDragging(d); }}
                        onDragEnd={() => { setDragging(null); setOver(null); }}
                        className={`rounded border border-slate-200 bg-white p-2.5 text-sm shadow-sm hover:border-slate-300 ${dragging?.uid === d.uid ? "opacity-50" : ""} ${moves.length ? "cursor-grab" : ""}`}>
                        <Link to={`/documents/${d.uid}`} className="line-clamp-3 font-medium text-slate-900 hover:underline">{d.title}</Link>
                        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                          <span className="inline-flex min-w-0 items-center gap-1"><DocumentTypeIcon iconUid={typeIcons.get(d.document_type_uid ?? "")} /><span className="truncate">{typeName.get(d.document_type_uid ?? "") ?? "No type"}</span></span>
                          <span className="font-mono">{d.code}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                          {r ? <span>v{r.revision_number}{groupBy !== "state" ? ` · ${BOARD_LABELS[column]}` : ""}</span> : <span>no revision</span>}
                          {r && d.current_revision_uid && d.current_revision_uid !== r.uid && (
                            <span className="rounded bg-green-50 px-1 text-green-800" title="Readers still see the published revision">earlier one published</span>
                          )}
                          {r?.authored_by && <span className="truncate">by {r.authored_by === me ? "you" : person(r.authored_by)}</span>}
                        </div>
                        {moves.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {moves.map(({ move: m }) => (
                              <button key={m} type="button" disabled={move.isPending} onClick={() => void run(d, m)}
                                      className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                                {MOVE_WORDS[m]}
                              </button>
                            ))}
                          </div>
                        )}
                      </article>
                    );
                  })}
                  {items.length === 0 && <p className="px-1 py-4 text-center text-xs text-slate-400">Nothing here</p>}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </BrowsePage>
  );
}
