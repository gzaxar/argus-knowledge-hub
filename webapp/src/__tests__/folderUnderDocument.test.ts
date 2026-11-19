import { test } from "vitest";
import assert from "node:assert/strict";
import type { DocumentNavigationNode } from "../api/types";
import { ancestorPath, branchCounts, descendants, treeRows } from "../lib/documentNavigation";

const nodes: DocumentNavigationNode[] = [
  { id: "d:wp", uid: "wp", kind: "document", title: "WP04 - Controls", parent_id: null },
  { id: "f:epik8s", uid: "epik8s", kind: "folder", title: "EPIK8s", parent_id: "d:wp" },
  { id: "d:manual", uid: "manual", kind: "document", title: "User Manual", parent_id: "f:epik8s" },
  { id: "f:examples", uid: "examples", kind: "folder", title: "Examples", parent_id: "d:manual" },
  { id: "d:example", uid: "example", kind: "document", title: "IOC example", parent_id: "f:examples" },
  { id: "f:empty", uid: "empty", kind: "folder", title: "Empty folder", parent_id: "d:wp" },
];

test("branch counters include documents below alternating document/folder parents", () => {
  const counts = branchCounts(nodes);
  assert.equal(counts.get("d:wp"), 2);
  assert.equal(counts.get("f:epik8s"), 2);
  assert.equal(counts.get("d:manual"), 1);
  assert.equal(counts.get("f:examples"), 1);
  assert.equal(counts.get("d:example"), 0);
  assert.equal(counts.get("f:empty"), 0);
});

test("breadcrumbs retain both folder and document ancestors", () => {
  assert.deepEqual(ancestorPath(nodes, "d:example").map((node) => node.id),
    ["d:wp", "f:epik8s", "d:manual", "f:examples", "d:example"]);
});

test("search expands every ancestor of a document inside nested folders", () => {
  const rows = treeRows(nodes, new Set(), "IOC example");
  assert.deepEqual(rows.map((row) => row.node.id),
    ["d:wp", "f:epik8s", "d:manual", "f:examples", "d:example"]);
  assert.deepEqual(rows.map((row) => row.depth), [0, 1, 2, 3, 4]);
});

test("a folder's descendants exclude document and folder cycle destinations", () => {
  const prohibited = descendants(nodes, "f:epik8s");
  assert.deepEqual([...prohibited].sort(), ["d:example", "d:manual", "f:epik8s", "f:examples"].sort());
  assert.equal(prohibited.has("d:wp"), false);
  assert.equal(prohibited.has("f:empty"), false);
});

test("moving a folder updates its branch and breadcrumbs without duplicating content", () => {
  const moved = nodes.map((node) => node.id === "f:epik8s" ? { ...node, parent_id: null } : node);
  assert.equal(branchCounts(moved).get("d:wp"), 0);
  assert.equal(branchCounts(moved).get("f:epik8s"), 2);
  assert.deepEqual(ancestorPath(moved, "d:manual").map((node) => node.id), ["f:epik8s", "d:manual"]);
  assert.equal(treeRows(moved, new Set(moved.map((node) => node.id)), "").length, nodes.length);
});
