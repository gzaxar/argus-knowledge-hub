// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MarkdownView } from "../components/MarkdownView";
afterEach(cleanup);
const rich = "argus-confluence-rich-node";
const classes = `${rich} argus-confluence-rich-table`;

test("opt-in tables are centred by their own wrapper, auto-sized and retain header colours", () => {
  const source = `<table class="${classes} argus-confluence-natural-table argus-rich-w-760px"><tbody><tr><th class="${rich} argus-rich-bg-f0f0f0">Parameter</th><th class="${rich} argus-rich-bg-f0f0f0">Value</th></tr><tr><td class="${rich}">Ingress class</td><td class="${rich}">haproxy</td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  const table = container.querySelector("table")!;
  expect(table.style.width).toBe("auto");
  expect(table.style.tableLayout).toBe("auto");
  expect(table.parentElement?.classList.contains("mx-auto")).toBe(true);
  expect(table.parentElement?.classList.contains("w-fit")).toBe(true);
  expect(table.parentElement?.classList.contains("overflow-x-auto")).toBe(true);
  expect(container.querySelector("th")?.style.backgroundColor).toBe("rgb(240, 240, 240)");
  expect(container.textContent).toContain("haproxy");
});

test("existing unmarked rich tables retain full width", () => {
  const { container } = render(<MemoryRouter><MarkdownView markdown={`<table class="${classes}"><tbody><tr><td class="${rich}">Available 4 ports</td></tr></tbody></table>`} /></MemoryRouter>);
  const table = container.querySelector("table")!;
  expect(table.style.width).toBe("100%");
  expect(table.parentElement?.classList.contains("w-fit")).toBe(false);
  expect(container.querySelector("td")?.style.overflowWrap).toBe("normal");
});
