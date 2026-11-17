// @vitest-environment jsdom
import { afterEach, expect, test } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { MarkdownView } from "../components/MarkdownView";

afterEach(cleanup);
const node = "argus-confluence-rich-node";
const outer = `${node} argus-confluence-rich-table`;
const inner = `${outer} argus-confluence-nested-table`;

test("nested table, merged cell, colours and paragraphs survive the full renderer", () => {
  const source = `<table class="${outer}"><tbody><tr><td class="${node} argus-rich-bg-cce0ff" colspan="2"><p class="${node}">Ports 01 - 24</p><table class="${inner}"><tbody><tr><td class="${node}">01</td><td class="${node}">02</td></tr><tr><td class="${node} argus-rich-bg-4bce97" colspan="2">Available</td></tr></tbody></table></td></tr><tr><td class="${node}"><p class="${node}">RF Driver</p><p class="${node}">Connected to</p><span class="${node} argus-rich-bg-fff0b3">B tag</span></td><td class="${node}" rowspan="2">Other port</td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  const tables = container.querySelectorAll("table");
  expect(tables.length).toBe(2);
  expect(tables[0].querySelector("table")).toBe(tables[1]);
  expect(container.querySelector('td[colspan="2"]')?.getAttribute("colspan")).toBe("2");
  expect(container.querySelector('td[rowspan="2"]')?.getAttribute("rowspan")).toBe("2");
  expect((container.querySelector('td[colspan="2"]') as HTMLElement)?.style.backgroundColor).toBe("rgb(204, 224, 255)");
  expect(container.querySelectorAll("p").length).toBe(3);
  expect((container.querySelector("span") as HTMLElement)?.style.backgroundColor).toBe("rgb(255, 240, 179)");
  expect(tables[1].parentElement?.tagName).toBe("TD");
});

test("column geometry is retained by sanitization and the component layer", () => {
  const source = `<table class="${outer}"><colgroup class="${node}"><col class="${node} argus-rich-w-42px" span="2" /></colgroup><tbody><tr><td>Data</td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  const column = container.querySelector("col");
  expect(column?.getAttribute("span")).toBe("2");
  expect(column?.style.width).toBe("50%");
});

test("source panels inside tables keep their validated background", () => {
  const source = `<table class="${outer}"><tbody><tr><td class="${node}"><div class="argus-confluence-panel argus-confluence-panel-bg-fffae6"><p>⚠️ Important: B tag</p></div></td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  expect((container.querySelector(".argus-confluence-panel") as HTMLElement)?.style.backgroundColor).toBe("rgb(255, 250, 230)");
  expect(container.textContent).toContain("Important: B tag");
});

test("scripts, source style attributes and event handlers stay blocked", () => {
  const source = `<table class="${outer}" style="position:fixed" onclick="bad()"><tbody><tr><td><script>bad()</script><img src="https://example.invalid/a.png" onerror="bad()" /><a href="javascript:bad()">Unsafe</a></td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("[onclick], [onerror]")).toBeNull();
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
  expect(container.querySelector("table")?.style.position).toBe("");
});

test("ordinary Markdown parameter tables keep their existing presentation", () => {
  const { container } = render(<MemoryRouter><MarkdownView markdown={"| Setting | Value |\n| --- | --- |\n| Range | 50 V |"} /></MemoryRouter>);
  expect(container.querySelectorAll("table").length).toBe(1);
  expect(container.querySelector("th")?.className).toContain("uppercase");
  expect(container.textContent).toContain("50 V");
});


test("wide outer and nested source grids fit independently using column proportions", () => {
  const source = `<table class="${outer} argus-rich-w-1342px"><colgroup><col class="${node} argus-rich-w-686px"/><col class="${node} argus-rich-w-656px"/></colgroup><tbody><tr><td class="${node}" colspan="2"><table class="${inner} argus-rich-w-1800px"><colgroup><col class="${node} argus-rich-w-218px"/>${Array.from({length:23}, () => `<col class="${node} argus-rich-w-53px"/>`).join("")}</colgroup><tbody><tr>${Array.from({length:24}, (_, i) => `<td class="${node}">${i+1}</td>`).join("")}</tr><tr><td class="${node}" colspan="24">Port labels</td></tr></tbody></table></td></tr><tr><td class="${node}"><p>RF Driver</p><div class="argus-confluence-panel argus-confluence-panel-bg-fffae6">Important: B tag</div></td><td class="${node}">RF Modulator</td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  const tables = container.querySelectorAll("table");
  for (const table of tables) {
    expect(table.style.width).toBe("100%");
  }
  expect(tables[0].style.tableLayout).toBe("fixed");
  expect(tables[1].style.tableLayout).toBe("auto");
  expect(tables[0].querySelector("col")?.style.width).toBe("51.118%");
  expect(tables[1].querySelector("col")?.style.width).toBe("15.17%");
  expect(tables[1].querySelectorAll("tr")[0].children.length).toBe(24);
  expect(tables[1].parentElement?.tagName).toBe("TD");
  expect(tables[1].querySelector('[colspan="24"]')).not.toBeNull();
  expect(container.textContent).toContain("Important: B tag");
  expect(container.querySelector("td")?.style.overflowWrap).toBe("normal");
  expect(container.querySelectorAll("[style*=px]").length).toBe(0);
});


test("rich cells wrap between whole words without automatic hyphenation", () => {
  const source = `<table class="${outer} argus-rich-w-1800px"><tbody><tr><th class="${node}">Available 4 ports</th></tr><tr><td class="${node}" colspan="4"><strong>Available 4 ports</strong></td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  for (const cell of container.querySelectorAll<HTMLElement>("th,td")) {
    expect(cell.style.overflowWrap).toBe("normal");
    expect(cell.style.wordBreak).toBe("normal");
    expect(cell.style.hyphens).toBe("none");
    expect(cell.className).not.toContain("overflow-wrap:anywhere");
    expect(cell.textContent).toBe("Available 4 ports");
  }
  expect(container.querySelector("table")?.style.width).toBe("100%");
  expect(container.querySelector("table")?.style.tableLayout).toBe("fixed");
  expect(container.querySelector("td")?.colSpan).toBe(4);
});


test("nested port grids use content sizing so later row labels can widen a column", () => {
  const source = `<table class="${outer} argus-rich-w-1342px"><tbody><tr><td class="${node}" colspan="2"><table class="${inner} argus-rich-w-1800px argus-rich-fixed"><colgroup><col class="${node} argus-rich-w-53px"/><col class="${node} argus-rich-w-53px"/></colgroup><tbody><tr><td class="${node}">01</td><td class="${node}">02</td></tr><tr><td class="${node} argus-rich-bg-57d9a3">Available 4 ports</td><td class="${node}">A tag</td></tr></tbody></table></td></tr></tbody></table>`;
  const { container } = render(<MemoryRouter><MarkdownView markdown={source} /></MemoryRouter>);
  const tables = container.querySelectorAll("table");
  expect(tables[0].style.tableLayout).toBe("fixed");
  expect(tables[1].style.tableLayout).toBe("auto");
  expect(tables[1].style.width).toBe("100%");
  expect(tables[1].querySelector("col")?.style.width).toBe("50%");
  const cell = tables[1].querySelectorAll("td")[2];
  expect(cell.textContent).toBe("Available 4 ports");
  expect(cell.style.wordBreak).toBe("normal");
  expect(cell.style.overflowWrap).toBe("normal");
  expect(cell.style.backgroundColor).toBe("rgb(87, 217, 163)");
});
