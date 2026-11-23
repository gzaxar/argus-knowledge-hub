import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { portalApi, workspacesApi } from "../api/client";
import { PortalHome } from "../pages/portal/SitePortal";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

describe("the help centre reached from the Knowledge Hub", () => {
  it("with no site open says what it is for and leads back to the hub", async () => {
    vi.spyOn(portalApi, "sites").mockResolvedValue([]);
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([{ id: "btf", name: "BTF" }] as never);
    renderWith(<PortalHome />);
    expect(await screen.findByText(/Here people ask a site's/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "← Knowledge Hub" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Back to the Knowledge Hub" })).toHaveAttribute("href", "/");
  });

  it("shows no way to the hub to someone who only makes requests", async () => {
    vi.spyOn(workspacesApi, "listMine").mockResolvedValue([]);
    vi.spyOn(portalApi, "sites").mockResolvedValue([{ id: "a", name: "Site Alpha", origins: [], open: true },
                                                    { id: "b", name: "Site Beta", origins: [], open: true }] as never);
    renderWith(<PortalHome />);
    await screen.findByText("Site Alpha");
    expect(screen.queryByRole("link", { name: "← Knowledge Hub" })).not.toBeInTheDocument();
  });
});
