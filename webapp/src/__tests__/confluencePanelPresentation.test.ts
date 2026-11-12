import { test } from "vitest";
import assert from "node:assert/strict";
import { confluencePanelStyle } from "../lib/confluencePanelPresentation";

test("validated source panel colours become React styles", () => assert.deepEqual(confluencePanelStyle("argus-confluence-panel argus-confluence-panel-bg-e6fcff argus-confluence-panel-border-b3d4ff"), {backgroundColor: "#e6fcff", borderColor: "#b3d4ff", borderStyle: "solid", borderWidth: 1}));
test("ordinary HTML classes do not acquire panel styles", () => assert.equal(confluencePanelStyle("something-else argus-confluence-panel-bg-e6fcff"), undefined));
test("CSS expressions cannot become panel colours", () => assert.deepEqual(confluencePanelStyle("argus-confluence-panel argus-confluence-panel-bg-url(javascript:bad)"), {}));
