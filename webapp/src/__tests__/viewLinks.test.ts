import { describe, expect, it } from "vitest";
import { DOCUMENT_TREE_PARAMS, viewHref } from "../lib/viewLinks";

describe("view destinations", () => {
  it("removes Tree-only state when opening Documents List", () => {
    expect(viewHref("/documents", "?node=d%3Ax&nav=types&panel=page&type_group=t1&rev=r2", DOCUMENT_TREE_PARAMS))
      .toBe("/documents");
  });
  it("keeps shared filters while clearing selection and pagination", () => {
    expect(viewHref("/documents", "?q=bpm&type=t1&status=draft&node=d%3Ax&page=3", DOCUMENT_TREE_PARAMS))
      .toBe("/documents?q=bpm&type=t1&status=draft");
  });
  it("also clears hierarchy selection when opening Board", () => {
    expect(viewHref("/documents/board", "?panel=list&node=f%3Ax&rev=r1&retired=1", DOCUMENT_TREE_PARAMS))
      .toBe("/documents/board?retired=1");
  });
  it("preserves selected-node and revision links when staying in Tree", () => {
    expect(viewHref("/documents/tree", "?node=d%3Ax&panel=page&rev=r2"))
      .toBe("/documents/tree?node=d%3Ax&panel=page&rev=r2");
  });
  it("keeps existing Tickets and Map parameter behaviour", () => {
    expect(viewHref("/tickets/board", "?q=pump&type=inc&page=3")).toBe("/tickets/board?q=pump&type=inc");
    expect(viewHref("/map?types=srv", "?q=rack&page=2")).toBe("/map?q=rack&types=srv");
  });
});
