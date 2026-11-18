import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { DocumentBoard } from "../pages/documents/Board";
import { DocumentList, DocumentTree } from "../pages/documents/List";
import { areas, SideNav } from "../layout/AppShell";
import { browseViewKey } from "../lib/browseViews";
import { renderWith } from "../test/render";

const cache = {
  '["me"]': { workspace_id: "w", is_admin: true },
  '["my-workspaces"]': [],
  '["documents"]': [],
  '["schemas"]': [],
  '["members"]': [],
  '["my-profile"]': { auth_type: "oidc", user: { id: "tester" } },
  '["document-navigation","w"]': { nodes: [], documents: [], folders: [], placements: [], warnings: [] },
};
const features = { equipment: true, map: true, beam_model: true } as Parameters<typeof areas>[0];

function documentRoutes(path: string) {
  return renderWith(<>
    <SideNav items={areas(features, 0)} />
    <Routes>
      <Route path="/documents" element={<DocumentList />} />
      <Route path="/documents/tree" element={<DocumentTree />} />
      <Route path="/documents/board" element={<DocumentBoard />} />
    </Routes>
  </>, { path, cache });
}

describe("Documents Tree exits and legacy links", () => {
  it.each([
    "node=d%3Ax&panel=page&rev=r2",
    "node=f%3Ax&nav=hierarchy&panel=list",
    "nav=types&type_group=t1&node=type%3At1",
  ])("opens the real List from Tree with %s", async (selection) => {
    const r = documentRoutes(`/documents/tree?${selection}&q=bpm&type=t1&status=draft&page=3`);
    const views = screen.getByRole("navigation", { name: "View" });
    expect(within(views).getByRole("link", { name: "List" }))
      .toHaveAttribute("href", "/documents?q=bpm&type=t1&status=draft");
    await userEvent.click(within(views).getByRole("link", { name: "List" }));
    expect(r.location()).toBe("/documents?q=bpm&type=t1&status=draft");
    expect(within(screen.getByRole("navigation", { name: "View" })).getByRole("link", { name: "List" }))
      .toHaveAttribute("aria-current", "page");
    expect(localStorage.getItem(browseViewKey("browser", "documents"))).toBe("list");
    expect(screen.queryByRole("complementary", { name: "Document navigation" })).not.toBeInTheDocument();
  });

  it("opens Board without taking Tree's selected node or revision", async () => {
    const r = documentRoutes("/documents/tree?node=d%3Ax&panel=page&rev=r2&q=bpm&type=t1");
    await userEvent.click(within(screen.getByRole("navigation", { name: "View" })).getByRole("link", { name: "Board" }));
    expect(r.location()).toBe("/documents/board?q=bpm&type=t1");
    expect(within(screen.getByRole("navigation", { name: "View" })).getByRole("link", { name: "Board" }))
      .toHaveAttribute("aria-current", "page");
  });

  it("preserves selected-node / revision state on a Tree destination", async () => {
    const r = documentRoutes("/documents/board?node=d%3Ax&panel=page&rev=r2&q=bpm");
    await userEvent.click(within(screen.getByRole("navigation", { name: "View" })).getByRole("link", { name: "Tree" }));
    expect(r.location()).toBe("/documents/tree?node=d%3Ax&panel=page&rev=r2&q=bpm");
  });

  it("still opens Tree from an old bookmarked browser address", () => {
    const r = documentRoutes("/documents?node=d%3Ax&panel=page&rev=r2");
    expect(r.location()).toBe("/documents/tree?node=d%3Ax&panel=page&rev=r2");
    expect(within(screen.getByRole("navigation", { name: "View" })).getByRole("link", { name: "Tree" }))
      .toHaveAttribute("aria-current", "page");
  });
});
