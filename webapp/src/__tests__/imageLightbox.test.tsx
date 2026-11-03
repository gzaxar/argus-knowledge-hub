import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { attachmentsApi } from "../api/client";
import { ImageLightbox } from "../components/ImageLightbox";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());
// jsdom has no object URLs: the viewer lets its own go when it closes.
URL.revokeObjectURL = URL.revokeObjectURL ?? (() => undefined);

async function opened() {
  vi.spyOn(attachmentsApi, "fetchBlobUrl").mockResolvedValue("blob:layout");
  renderWith(<ImageLightbox uid="a1" alt="layout_elettroni.png" onClose={() => {}} />);
  const img = await screen.findByAltText("layout_elettroni.png");
  Object.defineProperty(img, "naturalWidth", { value: 4000 });
  Object.defineProperty(img, "naturalHeight", { value: 6000 });
  fireEvent.load(img);
  return img as HTMLImageElement;
}

describe("a diagram, inspected (issue #17)", () => {
  it("shows the original file fitted, then zoomed, at 100%, and fitted again", async () => {
    const img = await opened();
    expect(attachmentsApi.fetchBlobUrl).toHaveBeenCalledWith("a1");              // the file itself
    expect(screen.getByText(/4000 × 6000 px, the original/)).toBeInTheDocument();
    const zoom = screen.getByLabelText("Zoom");
    const fitted = zoom.textContent;
    expect(Number(fitted!.replace("%", ""))).toBeLessThan(100);                 // a big diagram starts fitted
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(zoom.textContent).not.toBe(fitted);
    fireEvent.click(screen.getByRole("button", { name: "100%" }));
    expect(zoom).toHaveTextContent("100%");
    expect(img.style.transform).toContain("scale(1)");
    fireEvent.keyDown(window, { key: "0" });
    await waitFor(() => expect(zoom.textContent).toBe(fitted));
  });

  it("opens the original in a tab of its own", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await opened();
    fireEvent.click(screen.getByRole("button", { name: "Open original" }));
    expect(open).toHaveBeenCalledWith("blob:layout", "_blank", "noopener");
  });
});
