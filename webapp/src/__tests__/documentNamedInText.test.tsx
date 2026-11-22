import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { documentsApi, hubApi } from "../api/client";
import { DocumentContextPanel } from "../components/hub/ContextPanels";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const pump = { uid: "p1", key: "IP-0003", name: "Pompa ionica sezione 1A", type: "Ion Pump", matched_on: "name" };
const context = (named: unknown[]) => ({
  document: { uid: "d" }, access: { assets: true, tickets: true }, assets: [], instances: [], types: [],
  open_tickets: [], named,
});

describe("a document's Applies to", () => {
  it("offers the equipment its text names, and links one only when asked", async () => {
    vi.spyOn(hubApi, "documentContext").mockResolvedValue(context([pump]) as never);
    const add = vi.spyOn(documentsApi, "addRelation").mockResolvedValue({} as never);
    renderWith(<DocumentContextPanel documentUid="d" canLink />);
    expect(await screen.findByTestId("named-in-text")).toHaveTextContent("Pompa ionica sezione 1A");
    expect(add).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(add).toHaveBeenCalledWith("d", { to_type: "asset", to_uid: "p1", relation_type: "describes" }));
  });

  it("offers nothing to someone who may not change the document", async () => {
    vi.spyOn(hubApi, "documentContext").mockResolvedValue(context([pump]) as never);
    renderWith(<DocumentContextPanel documentUid="d" />);
    await screen.findByText(/Not linked to any asset/);
    expect(screen.queryByTestId("named-in-text")).not.toBeInTheDocument();
  });
});
