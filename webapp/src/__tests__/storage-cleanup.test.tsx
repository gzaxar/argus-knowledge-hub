import { describe, expect, it } from "vitest";
import { growth } from "../pages/admin/Statistics";

describe("storage growth in words", () => {
  it("says shrinking rather than a negative number of bytes", () => {
    expect(growth(-12257128)).toBe("shrinking, 11.7 MB/day");
    expect(growth(5 * 1024 * 1024)).toBe("5.0 MB/day");
    expect(growth(200)).toBe("steady");
    expect(growth(null)).toBe("—");
  });
});
