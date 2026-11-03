import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelSetting } from "../api/types";
import { DEFAULT_SETTING, ModelSettingsEditor } from "../components/ModelSettings";
import { renderWith } from "../test/render";

describe("per-model settings", () => {
  it("adds a configured model, edits it, and tests it as it is", async () => {
    const changes: Record<string, ModelSetting>[] = [];
    const test = vi.fn().mockResolvedValue({ ok: true, model: "auto", answered_by: "minimax-m27", seconds: 15.2,
                                             valid_json: true, error: null });
    const { rerender } = renderWith(
      <ModelSettingsEditor rows={{}} onChange={(r) => changes.push(r)} suggestions={["auto", ""]} test={test} />);
    fireEvent.click(screen.getByRole("button", { name: "add auto" }));
    expect(changes[changes.length - 1]).toEqual({ auto: DEFAULT_SETTING });

    const rows = { auto: { ...DEFAULT_SETTING } };
    rerender(<ModelSettingsEditor rows={rows} onChange={(r) => changes.push(r)} suggestions={["auto"]} test={test} />);
    fireEvent.change(screen.getByLabelText("Temperature of auto"), { target: { value: "0.6" } });
    expect(changes[changes.length - 1]!.auto.temperature).toBe(0.6);
    fireEvent.click(screen.getByLabelText("Tell it not to think"));
    expect(changes[changes.length - 1]!.auto.no_thinking).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(test).toHaveBeenCalledWith("auto", rows.auto);
    expect(await screen.findByRole("status")).toHaveTextContent("Answered with the JSON in 15.2 s, by minimax-m27");
  });

  it("says what went wrong in a failed test", async () => {
    const test = vi.fn().mockResolvedValue({ ok: false, model: "minimax-m27", answered_by: "minimax-m27", seconds: 280,
      valid_json: false, error: "minimax-m27 was still reasoning after 280 s" });
    renderWith(<ModelSettingsEditor rows={{ "minimax-m27": DEFAULT_SETTING }} onChange={() => {}} suggestions={[]} test={test} />);
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByRole("status")).toHaveTextContent("still reasoning after 280 s (280 s, minimax-m27)");
  });
});
