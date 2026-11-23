import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { intakeApi, schemasApi } from "../api/client";
import { AssetForm } from "../pages/assets/Form";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());
const me = { auth_type: "oidc", workspace_id: null, user_id: "u", email: "u", name: null, is_admin: true };

describe("a new record's checklist", () => {
  it("shows what is missing as a to-do until something is written, then as what stops the save", async () => {
    vi.spyOn(schemasApi, "list").mockResolvedValue([]);
    vi.spyOn(intakeApi, "guide").mockResolvedValue({ kind: "asset", ready: false, steps: [], next: null,
      checks: [{ id: "name", level: "error", message: "Give it a name." }] } as never);
    renderWith(<Routes><Route path="/assets/new" element={<AssetForm />} /></Routes>,
               { path: "/assets/new", cache: { '["me"]': me } });
    const item = (await screen.findByText("Give it a name.")).closest("li")!;
    expect(item).toHaveAttribute("data-level", "todo");
    expect(item.className).not.toMatch(/red/);
    const name = screen.getByText("Name", { selector: "label" }).parentElement!.querySelector("input")!;
    fireEvent.change(name, { target: { value: "Gun ion pump" } });
    await waitFor(() => expect(screen.getByText("Give it a name.").closest("li")).toHaveAttribute("data-level", "error"));
  });
});
