import type { AppDocument } from "../api/types";

/** The documents board's columns: the review a revision goes through (SPEC-DOC-0001 §5). */
export const BOARD_STATES = ["draft", "in_review", "approved", "published"] as const;
export type BoardColumn = (typeof BOARD_STATES)[number] | "retired";

export const BOARD_LABELS: Record<BoardColumn, string> = {
  draft: "Draft", in_review: "In review", approved: "Approved", published: "Published", retired: "Retired",
};

/** Where a document stands: its newest revision's state; a retired document is retired, whatever its revisions. */
export function boardColumn(d: AppDocument): BoardColumn {
  if (d.retired_at) return "retired";
  const state = d.latest_revision?.state;
  if (!state) return d.current_revision_uid ? "published" : "draft";
  if (state === "retired") return "retired";
  if (state === "superseded") return "published";
  return state;
}

/** The action a drop from one column to another means: the server's own transitions, nothing else. */
export type BoardMove = "submit" | "withdraw" | "reject" | "approve" | "publish";

export type MoveCheck = { move: BoardMove } | { refused: string };

/** Whether a document may be dropped in a column, and as which action — what the server would allow.
 * me: the signed-in person (null for a token); author: who wrote the revision. */
export function boardMove(from: BoardColumn, to: BoardColumn, ctx: {
  canModify: boolean; canApprove: boolean; me: string | null; author: string | null; hasRevision: boolean;
}): MoveCheck | null {
  if (from === to) return null;
  if (!ctx.hasRevision) return { refused: "This document has no revision yet" };
  if (from === "draft" && to === "in_review") {
    return ctx.canModify ? { move: "submit" } : { refused: "You may not edit documents here" };
  }
  if (from === "in_review" && to === "draft") {
    if (ctx.me && ctx.author === ctx.me) return { move: "withdraw" };
    return ctx.canApprove ? { move: "reject" } : { refused: "Only its author can withdraw it, or an approver reject it" };
  }
  if (from === "in_review" && to === "approved") {
    if (!ctx.canApprove) return { refused: "You may not approve documents here" };
    if (ctx.me && ctx.author === ctx.me) return { refused: "You wrote this revision: another approver must approve it" };
    return { move: "approve" };
  }
  if (from === "approved" && to === "published") {
    return ctx.canApprove ? { move: "publish" } : { refused: "You may not publish documents here" };
  }
  return { refused: `A revision cannot go from ${BOARD_LABELS[from]} to ${BOARD_LABELS[to]}` };
}

/** Published long ago: hidden by default, so years of logbook entries do not bury the work in progress. */
export function publishedRecently(d: AppDocument, days: number, now = Date.now()): boolean {
  const at = d.latest_revision?.published_at ?? d.latest_revision?.updated_at ?? d.updated_at;
  return now - new Date(at).getTime() <= days * 86_400_000;
}
