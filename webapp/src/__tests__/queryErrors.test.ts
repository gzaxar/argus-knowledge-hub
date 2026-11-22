import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { refusalToTell } from "../lib/queryErrors";

describe("a refusal", () => {
  it("is told, unless the query asked for it on purpose", () => {
    const refused = new ApiError(403, "Forbidden");
    expect(refusalToTell(refused)).toBe(true);
    expect(refusalToTell(refused, { expect403: true })).toBe(false);
    expect(refusalToTell(new ApiError(404, "Not found"))).toBe(false);
  });
});
