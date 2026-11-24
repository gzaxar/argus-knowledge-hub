import { describe, expect, it } from "vitest";
import { keyExample } from "../lib/keyExample";

describe("a key pattern's example", () => {
  it("follows the pattern being chosen", () => {
    const d = new Date("2026-11-24T10:00:00Z");
    expect(keyExample("{WS}-{TYPE}-{SEQ:4}", "linac-test-stand", d)).toBe("LINAC-TEST-STAND-IP-0001");
    expect(keyExample("{TYPE}-{YYYY}-{SEQ:4}", "btf", d)).toBe("IP-2026-0001");
    expect(keyExample("{WS}-{SEQ:5}", "btf", d)).toBe("BTF-00001");
  });
});
