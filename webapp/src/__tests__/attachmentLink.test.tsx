import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, attachmentsApi } from "../api/client";
import { ownPage } from "../api/infnAuth";
import { AttachmentPage } from "../pages/attachments/AttachmentPage";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());
URL.revokeObjectURL = URL.revokeObjectURL ?? (() => undefined);

describe("a link to a file someone sent (issue #18)", () => {
  it("shows the file, read in its own workspace", async () => {
    vi.spyOn(attachmentsApi, "about").mockResolvedValue({ uid: "f1", filename: "layout_elettroni.png",
      mime_type: "image/png", size_bytes: 204800, workspace_id: "btf", asset_uid: "a1", document_uid: null });
    const fetch = vi.spyOn(attachmentsApi, "fetchBlobUrl").mockResolvedValue("blob:f1");
    renderWith(<Routes><Route path="/attachments/:uid" element={<AttachmentPage />} /></Routes>, { path: "/attachments/f1" });
    expect(await screen.findByAltText("layout_elettroni.png")).toHaveAttribute("src", "blob:f1");
    expect(fetch).toHaveBeenCalledWith("f1", "btf");
    expect(screen.getByText(/workspace btf/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "its record" })).toHaveAttribute("href", "/assets/a1");
  });

  it("says plainly when it cannot be read", async () => {
    vi.spyOn(attachmentsApi, "about").mockRejectedValue(new ApiError(404, { detail: "Attachment not found" }));
    renderWith(<Routes><Route path="/attachments/:uid" element={<AttachmentPage />} /></Routes>, { path: "/attachments/f2" });
    expect(await screen.findByRole("alert")).toHaveTextContent("may not read the workspace it belongs to");
  });

  it("comes back after sign-in only to a page of the app", () => {
    expect(ownPage("/attachments/f1")).toBe("/attachments/f1");
    expect(ownPage("/assets/a1?tab=files")).toBe("/assets/a1?tab=files");
    for (const away of ["//evil.example/x", "https://evil.example", "/\\evil.example", "/auth/callback", undefined, 7]) {
      expect(ownPage(away)).toBeNull();
    }
  });
});
