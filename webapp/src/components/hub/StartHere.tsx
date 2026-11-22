import { useState } from "react";
import { Link } from "react-router-dom";
import type { HubStartStep } from "../../api/hubTypes";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

type Action = { label: string; to: string };
type Copy = { title: string; why: string; actions: (s: HubStartStep, ws: string) => Action[] };

/** The recommended order to fill a new workspace: where things are, what is there, who works on it, then what is
 *  written about it and what happens to it — so that each new record has something to link to. */
const COPY: Record<HubStartStep["key"], Copy> = {
  places: {
    title: "Add the places",
    why: "Buildings, halls, rooms and racks first: equipment is then placed in them, and shows on the map.",
    actions: (s) => [{ label: "Add a building", to: s.type_uid ? `/assets/new?schema_uid=${encodeURIComponent(s.type_uid)}` : "/assets/new" }],
  },
  equipment: {
    title: "Add your equipment",
    why: "One unit by hand — describe it in your own words, or from a nameplate photo or a datasheet — or a whole inventory from a spreadsheet.",
    actions: () => [{ label: "Add equipment", to: "/assets/new" }, { label: "Import a spreadsheet", to: "/assets/import" }],
  },
  records: {
    title: "Add a first record",
    why: "One by hand, or a whole list from a spreadsheet.",
    actions: () => [{ label: "Add a record", to: "/assets/new" }, { label: "Import a spreadsheet", to: "/assets/import" }],
  },
  people: {
    title: "Invite your colleagues",
    why: "By e-mail, each with a role: who only reads, who works on tickets, who approves documents.",
    actions: (_s, ws) => [{ label: "Invite people", to: `/workspaces/${encodeURIComponent(ws)}/access` }],
  },
  document: {
    title: "Write a first document",
    why: "A procedure or a note: paste your own text or a file, and ARGUS shapes it with a template and links it to the equipment it names.",
    actions: () => [{ label: "New document", to: "/documents/new" }],
  },
  ticket: {
    title: "Open a first ticket",
    why: "An incident, a request or a maintenance task, linked to the equipment it is about.",
    actions: () => [{ label: "New ticket", to: "/tickets/new" }],
  },
};

const hiddenKey = (ws: string) => `argus.start-here.hidden.${ws}`;

function isHidden(ws: string | null): boolean {
  if (!ws) return false;
  try { return localStorage.getItem(hiddenKey(ws)) === "1"; } catch { return false; }
}

/** *Start here* on the cockpit of a workspace still being set up: each step with why it comes in this order, ticked
 *  once done. It goes away when every step is done, or when hidden (remembered in this browser). */
export function StartHere({ steps }: { steps: HubStartStep[] }) {
  const ws = useCurrentWorkspaceId();
  const [hidden, setHidden] = useState(() => isHidden(ws));
  if (!ws || hidden || steps.every((s) => s.done)) return null;
  const done = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done)?.key;
  const hide = () => {
    try { localStorage.setItem(hiddenKey(ws), "1"); } catch { /* only this browser forgets it */ }
    setHidden(true);
  };
  return (
    <section aria-labelledby="start-here" className="rounded-lg border border-indigo-200 bg-indigo-50/60 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="start-here" className="text-base font-semibold text-slate-900">Start here</h2>
          <p className="mt-0.5 text-sm text-slate-600">
            A new workspace fills best in this order: each step gives the next something to link to.{" "}
            <Link to="/help/getting-started" className="text-indigo-700 hover:underline">Read the guide</Link>
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-slate-600">{done} of {steps.length} done</span>
          <button onClick={hide} className="text-slate-500 hover:text-slate-800 hover:underline">Hide</button>
        </div>
      </div>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {steps.map((s, i) => {
          const c = COPY[s.key];
          return (
            <li key={s.key} className={`rounded-md border bg-white p-3 ${s.key === next ? "border-indigo-300 shadow-sm" : "border-slate-200"}`}>
              <div className="flex items-center gap-2">
                <span aria-hidden className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  s.done ? "bg-emerald-600 text-white" : s.key === next ? "bg-indigo-600 text-white" : "bg-slate-200 text-slate-600"}`}>
                  {s.done ? "✓" : i + 1}
                </span>
                <h3 className={`text-sm font-medium ${s.done ? "text-slate-500" : "text-slate-900"}`}>
                  {c.title}{s.done && <span className="sr-only"> (done)</span>}
                </h3>
              </div>
              <p className="mt-1.5 text-xs text-slate-600">{c.why}</p>
              {s.done ? (
                <p className="mt-2 text-xs font-medium text-emerald-700">Done{s.count > 1 ? ` — ${s.count}` : ""}</p>
              ) : (
                <div className="mt-2 flex flex-wrap gap-2">
                  {c.actions(s, ws).map((a, j) => (
                    <Link key={a.to} to={a.to}
                          className={j === 0
                            ? "rounded-md bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700"
                            : "rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"}>
                      {a.label}
                    </Link>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
