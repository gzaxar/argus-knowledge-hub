import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { confirmHeader } from "../api/client";
import { DialogHost, askTyped } from "../lib/dialogs";

const NAME = "Hall B — ground floor";

function start() {
  render(<DialogHost />);
  let result: boolean | undefined;
  const done = askTyped(`Delete workspace "${NAME}"?`, NAME).then((v) => { result = v; });
  return { done, result: () => result };
}

describe("a dangerous action is confirmed twice", () => {
  it("asks the question, then wants the workspace's name typed exactly", async () => {
    const run = start();
    fireEvent.click(await screen.findByRole("button", { name: "Yes, go ahead" }));     // once
    const field = await screen.findByLabelText("The workspace's name");
    const go = screen.getByRole("button", { name: "I understand, do it" });
    expect(go).toBeDisabled();
    fireEvent.change(field, { target: { value: "Hall B" } });
    expect(go).toBeDisabled();
    fireEvent.keyDown(field, { key: "Enter" });                                          // Enter does not get round it
    expect(screen.getByLabelText("The workspace's name")).toBeInTheDocument();
    fireEvent.change(field, { target: { value: ` ${NAME} ` } });
    expect(go).toBeEnabled();
    fireEvent.click(go);                                                                 // twice
    await run.done;
    expect(run.result()).toBe(true);
  });

  it("is not done when the question is cancelled", async () => {
    const run = start();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await run.done;
    expect(run.result()).toBe(false);
    expect(screen.queryByLabelText("The workspace's name")).toBeNull();
  });

  it("is not done when the name is not given", async () => {
    const run = start();
    fireEvent.click(await screen.findByRole("button", { name: "Yes, go ahead" }));
    await screen.findByLabelText("The workspace's name");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await run.done;
    expect(run.result()).toBe(false);
  });

  it("sends the name typed, percent-encoded, for the server to check again", () => {
    expect(confirmHeader(` ${NAME} `)).toEqual({ "X-Confirm-Workspace": encodeURIComponent(NAME) });
  });
});
