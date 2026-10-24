import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BulkActionsBar } from "../components/BulkActionsBar";
import { renderWith } from "../test/render";

const base = { kind: "issue_uids" as const, label: "tickets", onStarted: vi.fn(), onClear: vi.fn() };
const cache = { '["me"]': { workspace_id: "ws" }, '["my-workspaces"]': [] };

describe("the bulk toolbar", () => {
  it("is not there while nothing is selected", () => {
    renderWith(<BulkActionsBar {...base} selected={new Set()} bulkDelete={vi.fn()} />, { cache });
    expect(screen.queryByRole("region", { name: /selected tickets/ })).toBeNull();
    expect(screen.queryByText(/Select tickets to/)).toBeNull();
  });

  it("appears with the selection and every action it allows", () => {
    renderWith(<BulkActionsBar {...base} selected={new Set(["a", "b"])} bulkDelete={vi.fn()} />, { cache });
    const bar = screen.getByRole("region", { name: "Actions on the selected tickets" });
    expect(bar).toHaveTextContent("2 selected");
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.getByLabelText("Copy or move")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
  });

  it("offers only what the person may do", () => {
    renderWith(<BulkActionsBar {...base} selected={new Set(["a"])} canTransfer={false} />, { cache });
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByLabelText("Copy or move")).toBeNull();
    expect(screen.getByRole("button", { name: "Clear selection" })).toBeInTheDocument();
  });

  it("asks before deleting", async () => {
    const del = vi.fn().mockResolvedValue({ deleted: 1, not_found: [] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWith(<BulkActionsBar {...base} selected={new Set(["a"])} bulkDelete={del} />, { cache });
    screen.getByRole("button", { name: "Delete" }).click();
    expect(confirm).toHaveBeenCalledWith("Delete 1 tickets? This cannot be undone.");
    expect(del).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});
