import { test } from "vitest";
import assert from "node:assert/strict";
import { confluenceRichStyle, fitConfluenceRichTables } from "../lib/confluenceRichTables";

const node = (tagName: string, classes: string[], children: any[] = []) => ({
  type: "element", tagName, properties: { className: classes }, children,
});
const marker = "argus-confluence-rich-node";
const table = "argus-confluence-rich-table";
const natural = "argus-confluence-natural-table";

test("natural tables use content sizing only with the validated rich marker", () => {
  assert.deepEqual(confluenceRichStyle(natural), undefined);
  assert.deepEqual(confluenceRichStyle(`${marker} ${natural} argus-rich-w-760px argus-rich-fixed`), {
    width: "auto", tableLayout: "auto",
  });
});

test("natural table dimensions are removed while colours, alignment and spans survive", () => {
  const cell = node("th", [marker, "argus-rich-w-220px", "argus-rich-bg-f0f0f0", "argus-rich-align-center"]);
  (cell.properties as any).colSpan = 2;
  const col = node("col", [marker, "argus-rich-w-100px"]);
  const root = node("table", [marker, table, natural, "argus-rich-w-760px", "argus-rich-fixed"], [node("colgroup", [marker], [col]), node("tbody", [marker], [node("tr", [marker], [cell])])]);
  fitConfluenceRichTables()(root);
  assert.equal(confluenceRichStyle(root.properties.className.join(" "))?.width, "auto");
  assert.equal(confluenceRichStyle(col.properties.className.join(" "))?.width, undefined);
  assert.equal(confluenceRichStyle(cell.properties.className.join(" "))?.width, undefined);
  assert.equal(confluenceRichStyle(cell.properties.className.join(" "))?.backgroundColor, "#f0f0f0");
  assert.equal((cell.properties as any).colSpan, 2);
  const before = JSON.stringify(root);
  fitConfluenceRichTables()(root);
  assert.equal(JSON.stringify(root), before);
});

test("natural sizing does not change a sibling grid's responsive width or a nested grid's independent sizing", () => {
  const inner = node("table", [marker, table, "argus-confluence-nested-table", "argus-rich-w-500px"]);
  const naturalTable = node("table", [marker, table, natural], [node("tbody", [], [node("tr", [], [node("td", [marker], [inner])])])]);
  const fixed = node("table", [marker, table, "argus-rich-w-900px"]);
  fitConfluenceRichTables()(node("div", [], [naturalTable, fixed]));
  assert.equal(confluenceRichStyle(naturalTable.properties.className.join(" "))?.width, "auto");
  assert.equal(confluenceRichStyle(fixed.properties.className.join(" "))?.width, "100%");
  assert.equal(confluenceRichStyle(inner.properties.className.join(" "))?.width, "100%");
});
