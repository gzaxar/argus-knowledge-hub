import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Node 25+ has a `localStorage` global of its own, which hides jsdom's: use the page's storage, as a browser does.
const dom = (globalThis as unknown as { jsdom?: { window: Window } }).jsdom?.window;
if (dom) {
  for (const name of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(globalThis, name, { value: dom[name], configurable: true, writable: true });
  }
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
