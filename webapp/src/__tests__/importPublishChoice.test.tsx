import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { documentsApi, schemasApi } from "../api/client";
import { MarkdownImport } from "../pages/imports/Markdown";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

describe("a Markdown import", () => {
  it("publishes as at the source unless asked for drafts to review", async () => {
    vi.spyOn(schemasApi, "list").mockResolvedValue([]);
    const run = vi.spyOn(documentsApi, "importMarkdown").mockResolvedValue(
      { documents: 1, attachments: 0, relations: 0, skipped: [] } as never);
    renderWith(<Routes><Route path="/workspaces/:workspaceId/imports/markdown" element={<MarkdownImport />} /></Routes>,
               { path: "/workspaces/btf/imports/markdown" });
    const file = new File(["# Leak test"], "leak.md", { type: "text/markdown" });
    const input = (await screen.findAllByLabelText(/./, { selector: 'input[type="file"]' }).catch(() => []))[0]
      ?? document.querySelector('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("radio", { name: /As drafts to review/ }));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    await waitFor(() => expect(run).toHaveBeenCalledWith([file], null, false));
  });
});
