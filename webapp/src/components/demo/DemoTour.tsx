import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { bundlesApi } from "../../api/client";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

const HIDE = "argus.demo-tour.hidden.";

function useTour() {
  const ws = useCurrentWorkspaceId();
  const q = useQuery({ queryKey: ["workspace-tour", ws], queryFn: () => bundlesApi.tour(ws!), enabled: !!ws,
                       staleTime: 10 * 60_000, retry: false });
  return { ws, tour: q.data?.tour ?? null };
}

/** On every page of a demo workspace: a thin strip saying its content is synthetic. */
export function DemoStrip() {
  const { tour } = useTour();
  if (!tour) return null;
  return (
    <div role="note" className="border-b border-amber-200 bg-amber-50 px-6 py-1 text-xs text-amber-900">
      <b>Synthetic demo</b> — {tour.notice ?? "everything in this workspace is fictional."}
    </div>
  );
}

/** On the cockpit of a demo workspace: what it is and the steps to start exploring. */
export function DemoTour() {
  const { ws, tour } = useTour();
  const [hidden, setHidden] = useState(() => {
    try { return !!ws && localStorage.getItem(HIDE + ws) === "1"; } catch { return false; }
  });
  if (!tour || !ws) return null;
  const toggle = (v: boolean) => {
    setHidden(v);
    try { if (v) localStorage.setItem(HIDE + ws, "1"); else localStorage.removeItem(HIDE + ws); } catch { /* not kept */ }
  };
  if (hidden) {
    return (
      <button type="button" onClick={() => toggle(false)}
              className="rounded border border-sky-200 bg-sky-50 px-3 py-1.5 text-sm font-medium text-sky-800 hover:bg-sky-100">
        Start exploring {tour.title}
      </button>
    );
  }
  return (
    <section aria-label="Start exploring" className="rounded-lg border border-sky-200 bg-sky-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Start exploring: {tour.title}
            <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 align-middle text-[11px] font-medium text-amber-900">synthetic</span>
          </h2>
          {tour.description && <p className="mt-1 max-w-4xl text-sm text-slate-600">{tour.description}</p>}
        </div>
        <button type="button" onClick={() => toggle(true)} className="text-xs text-slate-500 hover:text-slate-800">Hide</button>
      </div>
      <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {tour.steps.map((s, i) => (
          <li key={i} className="rounded border border-sky-100 bg-white p-3">
            <div className="text-xs font-medium text-sky-700">Step {i + 1}</div>
            {s.link ? <Link to={s.link} className="font-medium text-slate-900 hover:underline">{s.title}</Link>
              : <span className="font-medium text-slate-900">{s.title}</span>}
            <p className="mt-1 text-xs text-slate-600">{s.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
