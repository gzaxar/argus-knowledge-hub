import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The web image's nginx: an application route that is also a folder of the build (/assets) must reach the app.
const conf = readFileSync(resolve(__dirname, "../../nginx.conf"), "utf8");

describe("the web server", () => {
  it("never answers a route with a folder: /assets is the Assets list", () => {
    const fallback = conf.match(/location \/ \{[^}]*try_files ([^;]+);/);
    expect(fallback?.[1].trim()).toBe("$uri /index.html");
  });

  it("makes no redirect that names its own port", () => {
    expect(conf).toMatch(/absolute_redirect off;/);
  });
});
