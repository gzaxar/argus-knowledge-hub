import { test } from "vitest";
import assert from "node:assert/strict";
import { confluenceRichStyle, fitConfluenceRichTables, richCellSpan, richTableClass } from "../lib/confluenceRichTables";

test("formatting requires the trusted rich-node marker", () => {
  assert.equal(confluenceRichStyle("argus-rich-bg-ffffff"), undefined);
  assert.equal(richTableClass("not-argus-confluence-rich-node", "argus-confluence-rich-node"), false);
});
test("source colours and alignment become styles", () => {
  assert.deepEqual(confluenceRichStyle("argus-confluence-rich-node argus-rich-bg-cce0ff argus-rich-fg-172b4d argus-rich-align-center argus-rich-valign-middle"), {backgroundColor:"#cce0ff",color:"#172b4d",textAlign:"center",verticalAlign:"middle"});
});
test("column widths preserve px and percentage units", () => {
  assert.equal(confluenceRichStyle("argus-confluence-rich-node argus-rich-w-42px")?.width, "42px");
  assert.equal(confluenceRichStyle("argus-confluence-rich-node argus-rich-w-4_167pct")?.width, "4.167%");
});
test("invalid widths and CSS payloads are ignored", () => {
  assert.deepEqual(confluenceRichStyle("argus-confluence-rich-node argus-rich-w-999999px argus-rich-bg-url(javascript:bad) argus-rich-w-101pct"), {});
});
test("only complete valid colour tokens are accepted", () => {
  assert.deepEqual(confluenceRichStyle("argus-confluence-rich-node argus-rich-bg-ffffff-extra"), {});
});
test("source emphasis uses fixed CSS values", () => {
  assert.deepEqual(confluenceRichStyle("argus-confluence-rich-node argus-rich-bold argus-rich-italic argus-rich-underline argus-rich-fixed"), {fontWeight:"bold",fontStyle:"italic",textDecoration:"underline",tableLayout:"fixed"});
});
test("merged spans accept bounded positive integers", () => {
  assert.equal(richCellSpan("24"), 24);
  assert.equal(richCellSpan(2), 2);
  assert.equal(richCellSpan(1), 1);
});
test("merged spans reject injection, fractions and excessive values", () => {
  for (const value of [null, undefined, true, "", "24 onclick=bad", -1, 0, 1.5, 1001, NaN, Infinity, {}]) assert.equal(richCellSpan(value), undefined);
});


function richNode(tagName: string, width?: string, children: any[] = [], span?: number): any {
  return { type:"element", tagName, properties:{ className:["argus-confluence-rich-node", ...(tagName === "table" ? ["argus-confluence-rich-table"] : []), ...(width ? [`argus-rich-w-${width}`] : [])], ...(span ? {span} : {}) }, children };
}
const fittedWidth = (node: any) => confluenceRichStyle(node.properties.className.join(" "))?.width;

test("outer and nested widths use independent column totals, including spans", () => {
  const innerCols = [richNode("col", "218px"), ...Array.from({length:23}, () => richNode("col", "53px"))];
  const inner = richNode("table", "1800px", [richNode("colgroup", undefined, innerCols)]);
  const cols = [richNode("col", "200px", [], 2), richNode("col", "400px")];
  const outer = richNode("table", "1342px", [richNode("colgroup", undefined, cols), richNode("tbody", undefined, [inner])]);
  fitConfluenceRichTables()(outer);
  assert.equal(fittedWidth(outer), "100%");
  assert.equal(fittedWidth(inner), "100%");
  assert.equal(fittedWidth(cols[0]), "25%");
  assert.equal(fittedWidth(cols[1]), "50%");
  assert.equal(fittedWidth(innerCols[0]), "15.17%");
  assert.equal(fittedWidth(innerCols[1]), "3.688%");
  assert.equal(confluenceRichStyle(outer.properties.className.join(" "))?.tableLayout, "fixed");
  const before = JSON.stringify(outer);
  fitConfluenceRichTables()(outer);
  assert.equal(JSON.stringify(outer), before);
});

test("ordinary tables and source colour and merge metadata are untouched", () => {
  const plain = {type:"element", tagName:"table", properties:{className:["ordinary"]}, children:[richNode("col", "42px")]};
  const before = JSON.stringify(plain);
  fitConfluenceRichTables()(plain);
  assert.equal(JSON.stringify(plain), before);
  const cell = richNode("td", "250px");
  cell.properties.colSpan = 2;
  cell.properties.className.push("argus-rich-bg-57d9a3");
  const table = richNode("table", "1000px", [cell]);
  fitConfluenceRichTables()(table);
  assert.equal(cell.properties.colSpan, 2);
  assert.equal(fittedWidth(cell), "25%");
  assert.equal(confluenceRichStyle(cell.properties.className.join(" "))?.backgroundColor, "#57d9a3");
});

test("percentage columns stay percentages and missing dimensions do not invent pixel minima", () => {
  const cols = [richNode("col", "40pct"), richNode("col", "60pct")];
  const table = richNode("table", undefined, [richNode("colgroup", undefined, cols)]);
  fitConfluenceRichTables()(table);
  assert.equal(fittedWidth(cols[0]), "40%");
  assert.equal(fittedWidth(cols[1]), "60%");
  const orphan = richNode("col", "42px");
  fitConfluenceRichTables()(richNode("table", undefined, [richNode("colgroup", undefined, [orphan])]));
  assert.equal(fittedWidth(orphan), "100%");
});
