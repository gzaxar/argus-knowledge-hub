// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MarkdownView } from "../components/MarkdownView";

afterEach(cleanup);
const identifier = "synthetic_identifier_" + "A".repeat(600);
const view = (markdown: string) => render(<MemoryRouter><MarkdownView markdown={markdown} /></MemoryRouter>);

test("long prose, list items, links and inline code retain exact content with emergency wrapping", () => {
  const url = "https://example.invalid/" + "x".repeat(500);
  const { container } = view(`${identifier}\n\n- ${identifier}\n\n[${url}](${url})\n\n\`${identifier}\``);
  const root = container.querySelector<HTMLElement>(".markdown-body")!;
  expect(root.style.overflowWrap).toBe("anywhere");
  expect(root.style.wordBreak).toBe("normal");
  expect(root.style.minWidth).toMatch(/^0(?:px)?$/);
  expect(root.querySelector("p")?.textContent).toBe(identifier);
  expect(root.querySelector("li")?.textContent).toBe(identifier);
  expect(root.querySelector("a")?.getAttribute("href")).toBe(url);
  expect(root.querySelector("code")?.textContent).toBe(identifier);
});

test("fenced code with or without a language preserves text and scrolls instead of wrapping", () => {
  for (const language of ["", "text"]) {
    const { container, unmount } = view(`\`\`\`${language}\n${identifier}\n\`\`\``);
    const pre = container.querySelector("pre")!;
    expect(pre.style.overflowWrap).toBe("normal");
    expect(pre.style.whiteSpace).toBe("pre");
    expect(pre.classList.contains("overflow-x-auto")).toBe(true);
    expect(pre.textContent?.trimEnd()).toBe(identifier);
    unmount();
  }
});

test("rich nested tables keep whole words, colours and their own scroll container", () => {
  const node = "argus-confluence-rich-node";
  const table = `${node} argus-confluence-rich-table`;
  const source = `<table class="${table}"><tbody><tr><td class="${node}"><table class="${table} argus-confluence-nested-table"><tbody><tr><td class="${node} argus-rich-bg-4bce97" colspan="4">Available 4 ports</td></tr></tbody></table></td></tr></tbody></table>`;
  const { container } = view(source);
  const tables = container.querySelectorAll("table");
  expect(tables).toHaveLength(2);
  const cell = container.querySelector<HTMLTableCellElement>('td[colspan="4"]')!;
  expect(cell.textContent).toBe("Available 4 ports");
  expect(cell.style.overflowWrap).toBe("normal");
  expect(cell.style.wordBreak).toBe("normal");
  expect(cell.style.backgroundColor).toBe("rgb(75, 206, 151)");
  expect(tables[1].style.tableLayout).toBe("auto");
  expect(tables[0].parentElement?.classList.contains("overflow-x-auto")).toBe(true);
});
