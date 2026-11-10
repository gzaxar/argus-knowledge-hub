import test from "node:test";
import assert from "node:assert/strict";
import { ancestorPath, branchCounts, descendants, treeRows, previewBody } from "../src/lib/documentNavigation.ts";

const nodes = [
  { id: "f:sub", kind: "folder", uid: "sub", title: "Subsystems", parent_id: null },
  { id: "d:wp02", kind: "document", uid: "wp02", title: "WP02 RF sources", parent_id: "f:sub" },
  { id: "d:howto", kind: "document", uid: "howto", title: "Connect the modulator", parent_id: "d:wp02", searchText: "Connect the modulator CONF-123" },
];

test("breadcrumbs follow folder and document parents", () => {
  assert.deepEqual(ancestorPath(nodes, "d:howto").map((n) => n.id), ["f:sub", "d:wp02", "d:howto"]);
});
test("descendants include the selected node and each document once", () => {
  assert.deepEqual([...descendants(nodes, "f:sub")].sort(), ["d:howto", "d:wp02", "f:sub"]);
});
test("collapsed branches are hidden", () => {
  assert.deepEqual(treeRows(nodes, new Set(), "").map((r) => r.node.id), ["f:sub"]);
});
test("expand all visits every node", () => {
  assert.equal(treeRows(nodes, new Set(nodes.map((n) => n.id)), "").length, 3);
});
test("search keeps ancestors and opens the matching path", () => {
  assert.deepEqual(treeRows(nodes, new Set(), "modulator").map((r) => r.node.id), ["f:sub", "d:wp02", "d:howto"]);
});
test("codes can be searched without changing visible titles", () => {
  assert.equal(treeRows(nodes, new Set(), "CONF-123")[2].node.title, "Connect the modulator");
});
test("a failed search has no matching rows", () => {
  assert.equal(treeRows(nodes, new Set(), "absent").length, 0);
});
test("missing parents do not hide nodes", () => {
  assert.equal(treeRows([{...nodes[2], parent_id: "missing"}], new Set(), "").length, 1);
});
test("breadcrumbs and descendant traversal terminate on damaged cycles", () => {
  const cycle = [{ ...nodes[1], parent_id: "d:howto" }, nodes[2]];
  assert.equal(ancestorPath(cycle, "d:howto").length, 2);
  assert.equal(descendants(cycle, "d:howto").size, 2);
});
test("numeric WP names sort naturally", () => {
  const values = [10, 2, 1].map((i) => ({ ...nodes[1], id: `d:${i}`, title: `WP${i}`, parent_id: null }));
  assert.deepEqual(treeRows(values, new Set(), "").map((r) => r.node.title), ["WP1", "WP2", "WP10"]);
});
test("only the duplicated source title is omitted from the preview", () => {
  const body = "# Title\n\n[Manual](/v1/attachments/pdf)";
  assert.equal(previewBody(body, "Title"), "[Manual](/v1/attachments/pdf)");
  assert.equal(body, "# Title\n\n[Manual](/v1/attachments/pdf)");
});
test("a different heading remains in the preview", () => {
  assert.equal(previewBody("# Instructions\n\nBody", "Page title"), "# Instructions\n\nBody");
});
test("escaped literal title punctuation is recognised", () => {
  assert.equal(previewBody("# SIGMA\\_PHI \\[setup\\]\n\nBody", "SIGMA_PHI [setup]"), "Body");
});
test("a literal trailing hash in the source title stays literal", () => {
  assert.equal(previewBody("# Title \\#\n\nBody", "Title #"), "Body");
});
test("folder counts include the overview and its child documents", () => {
  assert.equal(branchCounts(nodes).get("f:sub"), 2);
});
test("system-page counts exclude the overview itself", () => {
  const result = branchCounts(nodes);
  assert.equal(result.get("d:wp02"), 1);
  assert.equal(result.get("d:howto"), 0);
});
test("type groups count their assigned document records", () => {
  const typeNodes = [{ id: "type:wi", uid: "type:wi", kind: "group", title: "Work Instruction", parent_id: null },
    { ...nodes[2], parent_id: "type:wi" }];
  assert.equal(branchCounts(typeNodes).get("type:wi"), 1);
});
test("an empty folder has a zero count", () => {
  assert.equal(branchCounts([nodes[0]]).get("f:sub"), 0);
});
test("counts deduplicate repeated document UIDs", () => {
  const repeated = [...nodes, { ...nodes[2], id: "d:alias", parent_id: "d:wp02" }];
  assert.equal(branchCounts(repeated).get("f:sub"), 2);
  assert.equal(branchCounts(repeated).get("d:wp02"), 1);
});
test("counts terminate on a damaged parent cycle", () => {
  const cycle = [{ ...nodes[1], parent_id: "d:howto" }, nodes[2]];
  const result = branchCounts(cycle);
  assert.equal(result.get("d:wp02"), 1);
  assert.equal(result.get("d:howto"), 1);
});
