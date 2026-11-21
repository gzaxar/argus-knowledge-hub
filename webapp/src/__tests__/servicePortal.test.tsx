import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, portalApi } from "../api/client";
import type { MyRequestDetail, PortalCatalogue, PortalForm } from "../api/portalTypes";
import { RequestDetail } from "../pages/portal/MyRequests";
import { RequestForm } from "../pages/portal/RequestForm";
import { SitePortal } from "../pages/portal/SitePortal";
import { renderWith } from "../test/render";

const params = vi.hoisted(() => ({ value: {} as Record<string, string> }));
vi.mock("react-router-dom", async (actual) => ({
  ...(await actual<typeof import("react-router-dom")>()),
  useParams: () => params.value,
}));
afterEach(() => vi.restoreAllMocks());

const catalogue: PortalCatalogue = {
  site: { id: "lnf", name: "LNF" }, open: true, headline: "How can we help?", welcome: null,
  emergency: "Call 112", assistance: false, open_requests: 1,
  helpdesk: { uid: "rt-desk", slug: "desk", name: "Ask the service desk", description: null, allow_attachments: true },
  categories: [{ name: "IT", services: [{ uid: "s-net", slug: "net", name: "Network & connectivity",
    description: "Wi-Fi, VPN", hours: null, contact: null, request_types: [
      { uid: "rt-net", slug: "wifi", name: "Wi-Fi or network problem", description: "No connection", allow_attachments: true }] }] }],
  origins: [{ id: "sparc", name: "SPARC" }],
};
const form: PortalForm = {
  uid: "rt-net", slug: "wifi", name: "Wi-Fi or network problem", description: null, allow_attachments: true,
  guidance: "Check the cable first.",
  fields: [{ key: "building", label: "Building", help: null, required: true, type: "text", options: [] }],
  service: { uid: "s-net", name: "Network & connectivity", description: null, hours: null, contact: null, category: "IT" },
};

describe("the help centre", () => {
  it("shows categories, request types, the helpdesk, the emergency text and the way to my requests", async () => {
    params.value = { siteId: "lnf" };
    vi.spyOn(portalApi, "catalogue").mockResolvedValue(catalogue);
    renderWith(<SitePortal />);
    expect(await screen.findByRole("heading", { name: "How can we help?" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Wi-Fi or network problem/ })).toHaveAttribute("href", "/support/lnf/new/rt-net");
    expect(screen.getByRole("link", { name: /I'm not sure/ })).toHaveAttribute("href", "/support/lnf/new/helpdesk");
    expect(screen.getByText("Call 112")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /My requests|open request/ }).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Search for help"), { target: { value: "vpn" } });
    expect(screen.getByText(/1 matching request type/)).toBeInTheDocument();
  });

  it("reviews the destination before sending, and a retry sends the same submission", async () => {
    params.value = { siteId: "lnf", requestTypeUid: "rt-net" };
    vi.spyOn(portalApi, "catalogue").mockResolvedValue(catalogue);
    vi.spyOn(portalApi, "form").mockResolvedValue(form);
    vi.spyOn(portalApi, "preview").mockResolvedValue({ request_type_uid: "rt-net", request_type_name: "Wi-Fi or network problem",
      service_name: "Network & connectivity", team_name: "Network team", provider_name: "LNF IT", helpdesk: false,
      reason: "You chose Network & connectivity.", version: "v1" });
    const submit = vi.spyOn(portalApi, "submit")
      .mockRejectedValueOnce(new ApiError(503, { detail: "unavailable" }))
      .mockResolvedValueOnce({ uid: "req-1", key: "IT-TCK-1", created: true, site_id: "lnf" });
    renderWith(<RequestForm />);
    expect(await screen.findByText("Check the cable first.")).toBeInTheDocument();
    const review = screen.getByRole("button", { name: "Review" });
    expect(review).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Summary/), { target: { value: "No network in room 12" } });
    fireEvent.change(screen.getByLabelText(/Building/), { target: { value: "B1" } });
    fireEvent.click(review);
    expect(await screen.findByText("Network team")).toBeInTheDocument();
    expect(screen.getByText("No network in room 12")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: "Send request" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    const [first, second] = submit.mock.calls.map((c) => c[1]);
    expect(second.submission_uid).toBe(first.submission_uid);
    expect(first).toMatchObject({ request_type_uid: "rt-net", origin_workspace_id: "sparc", fields: { building: "B1" },
      route_version: "v1" });
  });

  it("shows a request's public conversation and status, and sends a reply", async () => {
    params.value = { siteId: "lnf", uid: "req-1" };
    const detail: MyRequestDetail = {
      uid: "req-1", key: "IT-TCK-1", title: "No network", service_name: "Network & connectivity",
      request_type_name: "Wi-Fi or network problem", status: { category: "active", label: "In progress" },
      created_at: "2026-11-21T10:00:00Z", updated_at: "2026-11-21T11:00:00Z", site_id: "lnf", origin_name: "SPARC",
      unread: false, restricted: false, resolution: null, resolved_at: null, can_reply: true, can_reopen: false,
      description: "Port dark", submitted: [{ key: "building", label: "Building", value: "B1" }],
      conversation: [{ uid: "c1", body: "We are on our way.", created_at: "2026-11-21T11:00:00Z", mine: false, author_name: "Agent" }],
      attachments: [],
    };
    vi.spyOn(portalApi, "catalogue").mockResolvedValue(catalogue);
    vi.spyOn(portalApi, "get").mockResolvedValue(detail);
    const reply = vi.spyOn(portalApi, "reply").mockResolvedValue(detail);
    renderWith(<RequestDetail />);
    expect(await screen.findByText("We are on our way.")).toBeInTheDocument();
    expect(screen.getAllByText("In progress").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Add a reply"), { target: { value: "Thanks" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(reply).toHaveBeenCalledWith("lnf", "req-1", "Thanks"));
  });
});
