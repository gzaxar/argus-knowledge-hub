import { afterEach, describe, expect, it, vi } from "vitest";
import { assetsApi } from "../api/client";
import { addProfile, clearSession } from "../api/session";

afterEach(() => vi.restoreAllMocks());

describe("editing a shared record", () => {
  it("is sent to the record's own workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ uid: "m1" }), {
      status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    addProfile("test", { baseUrl: "http://api.test", token: "t" });
    await assetsApi.update("m1", { name: "HiScroll 6" }, "accelerator-infn");
    const headers = new Headers(fetchMock.mock.calls[0][1].headers);
    expect(headers.get("X-Workspace-Id")).toBe("accelerator-infn");
    vi.unstubAllGlobals();
    clearSession();
  });
});
