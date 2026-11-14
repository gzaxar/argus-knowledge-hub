import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { proposalsApi, type AssistantProposal } from "../api/client";
import { AssistantProposals } from "../pages/review/AssistantProposals";
import { renderWith } from "../test/render";

afterEach(() => vi.restoreAllMocks());

const p = (id: string, n: number, kind: AssistantProposal["kind"], summary: string): AssistantProposal => ({
  id, number: n, turn_seq: 0, kind, summary, status: "proposed", result: null, error: null, reason: n === 1 ? "asked for it" : null,
  conversation: { id: "c1", title: "Proposals from token claude-desktop — 2026-11-14", from: "token claude-desktop" },
  created_at: "2026-11-14T10:00:00Z",
});

describe("Review queue › proposed by assistants", () => {
  it("lists a batch, and applies only what the person chose", async () => {
    vi.spyOn(proposalsApi, "list").mockResolvedValue([p("a", 1, "create", "Create Camera “Camera 2”"),
                                                      p("b", 2, "document", "Write a draft document “Replacing a camera”")]);
    const apply = vi.spyOn(proposalsApi, "apply").mockResolvedValue([{ ...p("b", 2, "document", "Write a draft document “Replacing a camera”"),
                                                                       status: "applied", result: { uid: "d1" } }]);
    renderWith(<AssistantProposals />);
    await screen.findByText("Proposals from token claude-desktop — 2026-11-14");
    expect(screen.getByText("Why: asked for it")).toBeInTheDocument();
    expect(screen.getByText("Draft document")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Choose Write a draft document “Replacing a camera”"));
    fireEvent.click(screen.getByRole("button", { name: "Apply 1" }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith(["b"]));
    expect(await screen.findByRole("link", { name: "open" })).toHaveAttribute("href", "/documents/d1");
  });

  it("shows nothing when nothing waits", async () => {
    vi.spyOn(proposalsApi, "list").mockResolvedValue([]);
    const { container } = renderWith(<AssistantProposals />);
    await waitFor(() => expect(proposalsApi.list).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
