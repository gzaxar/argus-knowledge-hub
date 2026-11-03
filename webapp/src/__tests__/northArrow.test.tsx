import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NorthArrow } from "../components/PlanView";
import { renderWith } from "../test/render";

describe("true north on a floor plan", () => {
  it("turns the arrow as the drawing has north, and says so", () => {
    renderWith(<NorthArrow deg={270} />);
    const arrow = screen.getByRole("img", { name: "North: 270° clockwise from the plan's top" });
    expect(arrow.querySelector("svg")!.style.transform).toBe("rotate(270deg)");
  });
});
