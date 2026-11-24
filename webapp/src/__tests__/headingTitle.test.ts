import { describe, expect, it } from "vitest";
import { withTitle } from "../lib/headingTitle";

describe("a reworked draft saved with its title", () => {
  it("opens with that title, once, after the draft notice; nothing else changes", () => {
    const draft = "> ⚠ DRAFT reworked\n\n# Sostituzione pompa IP-01 - appunti di Luca\n\n## Steps\n\n# Not the top";
    expect(withTitle(draft, "Sostituzione della pompa ionica IP-01")).toBe(
      "> ⚠ DRAFT reworked\n\n# Sostituzione della pompa ionica IP-01\n\n## Steps\n\n# Not the top");
    expect(withTitle("No heading here", "T")).toBe("No heading here");
    expect(withTitle("# Kept", "  ")).toBe("# Kept");
  });
});
