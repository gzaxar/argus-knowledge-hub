import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TypeExplorer, typeFamily } from "../components/browse/TypeExplorer";
import { renderWith } from "../test/render";

const s = (uid: string, name: string, parent: string | null = null, ws = "ws") =>
  ({ uid, name, parent_schema_uid: parent, applies_to: "tickets", workspace_id: ws, icon_uid: null });
const SCHEMAS = [s("t", "Ticket"), s("inc", "Incident", "t"), s("chg", "Change", "t"), s("std", "Standard change", "chg"),
                 s("other", "Their type", null, "elsewhere")];
const cache = { '["schemas"]': SCHEMAS, '["me"]': { workspace_id: "ws", is_admin: false }, '["my-workspaces"]': [] };
const counts = new Map([["inc", 4], ["std", 2]]);

function setup(selected: string | null = null) {
  const onSelect = vi.fn();
  renderWith(<TypeExplorer appliesTo="tickets" counts={counts} total={9} selected={selected} onSelect={onSelect} />, { cache });
  return onSelect;
}

describe("the type explorer", () => {
  it("is a tree with counts that include the types below", () => {
    setup();
    const tree = screen.getByRole("tree", { name: "Ticket types" });
    const ticket = within(tree).getByRole("treeitem", { name: /Ticket/ });
    expect(ticket).toHaveAttribute("aria-expanded", "true");
    expect(within(ticket).getByLabelText("6 records")).toBeInTheDocument();
    // Lazy: a closed branch's children are not rendered.
    expect(within(tree).queryByRole("treeitem", { name: /Standard change/ })).toBeNull();
  });

  it("selects with a click and clears", async () => {
    const onSelect = setup("inc");
    await userEvent.click(screen.getByRole("treeitem", { name: /Change/ }));
    expect(onSelect).toHaveBeenLastCalledWith("chg");
    await userEvent.click(screen.getByRole("button", { name: /Clear the type filter/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("is operated with the keyboard", () => {
    const onSelect = setup();
    const ticket = screen.getByRole("treeitem", { name: /Ticket/ });
    ticket.focus();
    fireEvent.keyDown(ticket, { key: "ArrowDown" });
    const change = screen.getByRole("treeitem", { name: /^Change/ });
    expect(change).toHaveFocus();
    fireEvent.keyDown(change, { key: "ArrowRight" });
    expect(screen.getByRole("treeitem", { name: /Standard change/ })).toBeInTheDocument();
    fireEvent.keyDown(change, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("chg");
    fireEvent.keyDown(change, { key: "ArrowLeft" });
    expect(screen.queryByRole("treeitem", { name: /Standard change/ })).toBeNull();
  });

  it("searches, opening the branches that match", async () => {
    setup();
    await userEvent.type(screen.getByLabelText("Filter types"), "standard");
    expect(screen.getByRole("treeitem", { name: /Standard change/ })).toBeInTheDocument();
    expect(screen.queryByRole("treeitem", { name: /Incident/ })).toBeNull();
  });

  it("shows every type in one tree, marking a type made in another workspace", () => {
    setup();
    expect(screen.queryByRole("button", { name: /Shared by other workspaces/ })).toBeNull();
    const theirs = screen.getByRole("treeitem", { name: /Their type/ });
    expect(theirs).toHaveTextContent("shared");
    expect(theirs).toHaveAttribute("title", "Their type · made in elsewhere, shared");
  });

  it("is one type when the catalogue and the workspace both hold a package's type, with its version", () => {
    const pkg = { kind: "package", package: "core-objects", version: "2.1.0", package_name: "Core objects" };
    const schemas = [
      { ...s("own-pump", "Vacuum Pump", null), applies_to: "objects", origin: { ...pkg, version: "2.0.0" } },
      { ...s("cat-pump", "Vacuum Pump", null, "catalogue"), applies_to: "objects", origin: pkg },
      { ...s("cat-turbo", "Turbo Pump", "cat-pump", "catalogue"), applies_to: "objects", origin: pkg },
      { ...s("jira", "Motors", null), applies_to: "objects", origin: { kind: "import", source: "jira" } },
    ];
    const onSelect = vi.fn();
    renderWith(<TypeExplorer appliesTo="objects" counts={new Map([["own-pump", 1], ["cat-pump", 2], ["cat-turbo", 4]])}
                             total={7} selected={null} onSelect={onSelect} />,
               { cache: { ...cache, '["schemas"]': schemas } });
    const pumps = screen.getAllByRole("treeitem", { name: /Vacuum Pump/ });
    expect(pumps).toHaveLength(1);                                           // one node, the workspace's own
    expect(pumps[0]).toHaveAttribute("title", "Vacuum Pump · Core objects 2.0.0 (package core-objects)");
    expect(within(pumps[0]).getByLabelText("7 records")).toBeInTheDocument();   // its own, the catalogue's, below
    expect(screen.getByRole("treeitem", { name: /Turbo Pump/ })).toHaveAttribute("aria-level", "2");
    expect(screen.getByRole("treeitem", { name: /Motors/ })).toHaveTextContent("Jira");
    expect([...typeFamily(schemas as never, "own-pump")!].sort()).toEqual(["cat-pump", "cat-turbo", "own-pump"]);
  });

  it("filters by a type and every type below it", () => {
    expect([...typeFamily(SCHEMAS as never, "chg")!].sort()).toEqual(["chg", "std"]);
    expect(typeFamily(SCHEMAS as never, null)).toBeNull();
  });
});
