import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRights } from "../lib/permissions";
import { renderWith } from "../test/render";

function Rights() {
  const r = useRights();
  return <p>{r.can_create_tickets ? "create" : "no-create"} {r.can_delete_tickets ? "delete" : "no-delete"}</p>;
}

function signedIn() {
  localStorage.setItem("assetmanagement.profiles", JSON.stringify([
    { id: "p", name: "Me", baseUrl: "http://x", authType: "oidc", activeWorkspaceId: "ws" }]));
  localStorage.setItem("assetmanagement.activeProfileId", "p");
}

describe("actions follow the person's rights", () => {
  it("a member without the right to delete tickets is not offered it", () => {
    signedIn();
    renderWith(<Rights />, { cache: {
      '["me"]': { is_admin: false, workspace_id: null },
      '["my-workspaces"]': [{ id: "ws", can_create_tickets: true, can_delete_tickets: false }],
    } });
    expect(screen.getByText("create no-delete")).toBeInTheDocument();
  });

  it("an administrator is offered everything (the server still checks)", () => {
    signedIn();
    renderWith(<Rights />, { cache: {
      '["me"]': { is_admin: true, workspace_id: null },
      '["my-workspaces"]': [{ id: "ws", can_create_tickets: false, can_delete_tickets: false }],
    } });
    expect(screen.getByText("create delete")).toBeInTheDocument();
  });
});
