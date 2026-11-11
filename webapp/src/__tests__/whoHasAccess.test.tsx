import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { rolesApi } from "../api/client";
import type { WhoHasAccess as Listing } from "../api/types";
import { WhoHasAccess } from "../pages/workspace/WhoHasAccess";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const ALL = { objects: ["read", "create", "modify", "delete"], tickets: ["read", "create", "modify", "delete"],
  documents: ["read", "create", "modify", "delete", "approve"], workspace: ["manage_members"] };
const person = (email: string, over: object) => ({ user_id: email, email, name: null, signed_in: true, active: true,
  installation_administrator: false, rights: ALL, routes: [], ...over });

const satc: Listing = {
  workspace_id: "satc", workspace_name: "SATC", site_id: "lnf",
  people: [
    person("anna@lnf.infn.it", { routes: [{ source: "group", role: "Workspace administrator", group: "IT-LNF", label: "" }] }),
    person("gallo@lnf.infn.it", { rights: { objects: ["read"], tickets: ["read"], documents: ["read"], workspace: ["manage_members"] },
      routes: [{ source: "site_administrator", site: "lnf", label: "" }] }),
    person("me@lnf.infn.it", { installation_administrator: true, routes: [
      { source: "instance_administrator", label: "" }, { source: "legacy", label: "" }] }),
    person("root@gmail.com", { installation_administrator: true, routes: [{ source: "instance_administrator", label: "" }] }),
  ],
  anyone_signed_in: {},
  counts: { people: 4, installation_administrators: 2, manage_access: 4, anyone_signed_in: false },
} as Listing;

describe("who has access", () => {
  it("lists everyone with why, folds the installation's administrators, and says nobody else gets in", async () => {
    vi.spyOn(rolesApi, "whoHasAccess").mockResolvedValue(satc);
    renderWith(<WhoHasAccess workspaceId="satc" />);
    const section = await screen.findByRole("region", { name: "Who has access" });
    expect(within(section).getByText(/4 people can open SATC/)).toBeInTheDocument();
    expect(within(section).getByText("Workspace administrator via IT-LNF")).toBeInTheDocument();
    expect(within(section).getByText("Site administrator of lnf")).toBeInTheDocument();
    expect(within(section).getByText("Objects: read · Tickets: read · Documents: read")).toBeInTheDocument();
    // Administrator with a route of its own here stays listed; one with none is folded away.
    expect(within(section).getByText("Area permissions")).toBeInTheDocument();
    expect(within(section).queryByText("root@gmail.com")).not.toBeInTheDocument();
    fireEvent.click(within(section).getByRole("button", { name: "Show 1 installation administrator" }));
    expect(within(section).getByText("root@gmail.com")).toBeInTheDocument();
    expect(within(section).getByText(/Nobody else/)).toBeInTheDocument();
  });

  it("warns when anyone signed in gets something", async () => {
    vi.spyOn(rolesApi, "whoHasAccess").mockResolvedValue({ ...satc, anyone_signed_in: { objects: ["read"] },
      counts: { ...satc.counts, anyone_signed_in: true } });
    renderWith(<WhoHasAccess workspaceId="satc" />);
    expect(await screen.findByText("Objects: read")).toBeInTheDocument();
    expect(screen.getByText(/Anyone signed in to ARGUS/)).toBeInTheDocument();
  });
});
