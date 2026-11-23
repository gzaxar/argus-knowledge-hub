import { describe, expect, it } from "vitest";
import { authorityLabel, confidentialityLabel } from "../lib/documentLabels";

describe("a document's stored values", () => {
  it("are read as words, and an unknown one as it is", () => {
    expect(authorityLabel("bozza_interna")).toBe("Internal draft");
    expect(confidentialityLabel("riservato")).toBe("Confidential");
    expect(authorityLabel("custom")).toBe("custom");
    expect(confidentialityLabel(null)).toBe("");
  });
});
