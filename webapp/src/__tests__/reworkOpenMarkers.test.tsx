import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { reshapeApi } from "../api/client";
import { MadeFromRawText } from "../pages/documents/Detail";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const generation = {
  revision_uid: "r1", source: { kind: "paste" }, template: { id: "procedure", version: 1, scope: "official", version_uid: "v" },
  model: "m", created_at: "2026-11-22T10:00:00Z", dates: {},
};

describe("a reworked revision", () => {
  it("says how many places the rework left to settle, until it is published", async () => {
    vi.spyOn(reshapeApi, "generations").mockResolvedValue([generation] as never);
    const body = "Date [da confermare]\n\nPurpose [da confermare]\n\nStep 3 [da verificare]";
    const { unmount } = renderWith(<MadeFromRawText documentUid="d" revisionUid="r1" state="in_review" body={body} />);
    expect(await screen.findByTestId("open-markers")).toHaveTextContent("3 places still say");
    unmount();
    renderWith(<MadeFromRawText documentUid="d" revisionUid="r1" state="published" body={body} />);
    await screen.findByText(/Reworked from raw text/);
    expect(screen.queryByTestId("open-markers")).not.toBeInTheDocument();
  });
});
