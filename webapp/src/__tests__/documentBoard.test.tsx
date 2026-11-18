import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { documentsApi, membersApi, schemasApi, tokensApi, workspacesApi } from "../api/client";
import type { AppDocument, DocumentLatestRevision } from "../api/types";
import { DocumentViewSwitch } from "../components/DocumentViews";
import { boardColumn, boardMove, publishedRecently } from "../lib/documentBoard";
import { DocumentBoard } from "../pages/documents/Board";
import { DocumentList } from "../pages/documents/List";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const NOW = new Date().toISOString();
const doc = (title: string, rev: Partial<DocumentLatestRevision> | null, extra: Partial<AppDocument> = {}) => ({
  uid: title, workspace_id: "w", code: `DOC-${title}`, title, document_type_uid: null, owner_user_id: null,
  responsible_service_asset_uid: null, authority_level: "informativo", confidentiality: "interno", source: "manual",
  is_global: false, current_revision_uid: null, created_at: NOW, updated_at: NOW,
  latest_revision: rev && { uid: `${title}-r`, revision_number: 1, state: "draft", authored_by: "ann", published_at: null,
                            updated_at: NOW, ...rev },
  ...extra,
}) as AppDocument;

const ctx = { canModify: true, canApprove: true, me: "bob", author: "ann", hasRevision: true };

describe("the documents board's rules", () => {
  it("places a document by its newest revision", () => {
    expect(boardColumn(doc("a", { state: "in_review" }))).toBe("in_review");
    expect(boardColumn(doc("b", { state: "draft", revision_number: 2 }, { current_revision_uid: "old" }))).toBe("draft");
    expect(boardColumn(doc("c", null, { current_revision_uid: "x" }))).toBe("published");
    expect(boardColumn(doc("d", { state: "published" }, { retired_at: NOW }))).toBe("retired");
  });

  it("allows only the review's own steps, as the server does", () => {
    expect(boardMove("draft", "in_review", ctx)).toEqual({ move: "submit" });
    expect(boardMove("in_review", "approved", ctx)).toEqual({ move: "approve" });
    expect(boardMove("approved", "published", ctx)).toEqual({ move: "publish" });
    expect(boardMove("in_review", "draft", ctx)).toEqual({ move: "reject" });
    expect(boardMove("in_review", "draft", { ...ctx, me: "ann" })).toEqual({ move: "withdraw" });
    expect(boardMove("in_review", "approved", { ...ctx, me: "ann" })).toHaveProperty("refused");   // separation of duties
    expect(boardMove("in_review", "approved", { ...ctx, canApprove: false })).toHaveProperty("refused");
    expect(boardMove("draft", "published", ctx)).toHaveProperty("refused");
    expect(boardMove("published", "draft", ctx)).toHaveProperty("refused");
    expect(boardMove("draft", "draft", ctx)).toBeNull();
  });

  it("keeps old publications off the board unless asked", () => {
    const old = new Date(Date.now() - 90 * 86_400_000).toISOString();
    expect(publishedRecently(doc("a", { state: "published", published_at: NOW }), 30)).toBe(true);
    expect(publishedRecently(doc("b", { state: "published", published_at: old }), 30)).toBe(false);
  });
});

describe("the documents views", () => {
  it("are List, Tree and Board, carrying the filters", () => {
    renderWith(<DocumentViewSwitch current="list" />, { path: "/documents?q=bpm&type=t1" });
    expect(screen.getByRole("link", { name: "List" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Tree" })).toHaveAttribute("href", "/documents/tree?q=bpm&type=t1");
    expect(screen.getByRole("link", { name: "Board" })).toHaveAttribute("href", "/documents/board?q=bpm&type=t1");
  });

  it("an address of the former browser opens the Tree", () => {
    vi.spyOn(documentsApi, "list").mockResolvedValue([]);
    const { location } = renderWith(<DocumentList />, { path: "/documents?node=d%3Ax&panel=page" });
    expect(location()).toBe("/documents/tree?node=d%3Ax&panel=page");
  });

  it("the board moves a document one review step from its card", async () => {
    const old = new Date(Date.now() - 90 * 86_400_000).toISOString();
    const rows = [
      doc("Bake-out", { state: "draft" }), doc("Interlock", { state: "in_review" }),
      doc("Mine", { state: "in_review", authored_by: "bob" }), doc("Old log", { state: "published", published_at: old }),
    ];
    vi.spyOn(documentsApi, "list").mockImplementation(async () => rows.map((r) => ({ ...r })));
    vi.spyOn(schemasApi, "list").mockResolvedValue([]);
    vi.spyOn(membersApi, "directory").mockResolvedValue([{ user_id: "ann", email: "ann@x", name: "Ann" }]);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    vi.spyOn(tokensApi, "profile").mockResolvedValue({ auth_type: "oidc", user: { id: "bob" } } as never);
    const submit = vi.spyOn(documentsApi, "submitRevision").mockImplementation(async () => {
      rows[0] = { ...rows[0], latest_revision: { ...rows[0].latest_revision!, state: "in_review" } };
      return {} as never;
    });
    renderWith(<DocumentBoard />, { path: "/documents/board" });

    const draft = await screen.findByRole("region", { name: "Draft" });
    expect(within(draft).getByText("Bake-out")).toBeInTheDocument();
    const review = screen.getByRole("region", { name: "In review" });
    // Another's revision: approve or reject; one's own: withdraw, never approve.
    const theirs = within(review).getByText("Interlock").closest("article")!;
    expect(within(theirs as HTMLElement).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    const mine = within(review).getByText("Mine").closest("article")!;
    expect(within(mine as HTMLElement).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(within(mine as HTMLElement).getByRole("button", { name: "Withdraw from review" })).toBeInTheDocument();
    // Published long ago: hidden, and said so.
    expect(screen.queryByText("Old log")).not.toBeInTheDocument();
    expect(screen.getByText(/1 published earlier is hidden/)).toBeInTheDocument();

    fireEvent.click(within(draft).getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith("Bake-out", "Bake-out-r"));
    expect(await within(screen.getByRole("region", { name: "In review" })).findByText("Bake-out")).toBeInTheDocument();
  });
});
