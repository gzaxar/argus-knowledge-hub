import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

/* The parts every browse page (Assets, Tickets, Documents) is made of, so the three read alike: a header with
   the title and the primary action, a contextual panel (the type explorer), a toolbar (search, filters, view,
   columns) and the results, with a pager. */

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}

function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* storage blocked: kept for this page only */
  }
}

// --------------------------------------------------------------------------- state in the address

/** A browse page's filters live in the address (`?q=…&type=…`): a reload keeps them, a link shares them, and
 * switching between list, board and map carries them across. */
export function useBrowseParams() {
  const [params, setParams] = useSearchParams();
  const get = useCallback((key: string, fallback = "") => params.get(key) ?? fallback, [params]);
  const set = useCallback(
    (changes: Record<string, string | null | undefined>) =>
      setParams((current) => {
        const next = new URLSearchParams(current);
        for (const [k, v] of Object.entries(changes)) {
          if (v === null || v === undefined || v === "") next.delete(k);
          else next.set(k, v);
        }
        if (!("page" in changes)) next.delete("page");      // a new filter starts on the first page
        return next;
      }, { replace: true }),
    [setParams],
  );
  return { params, get, set };
}

// --------------------------------------------------------------------------- layout

export function BrowsePage({ title, count, primary, actions, explorer, explorerLabel, explorerSummary, storageKey, toolbar,
  children }: {
  title: string;
  count?: React.ReactNode;
  /** The page's main action (New …). */
  primary?: React.ReactNode;
  /** Its other actions (Templates, Rework, Tools…). */
  actions?: React.ReactNode;
  explorer?: React.ReactNode;
  explorerLabel?: string;
  /** What the panel filters by now, shown on the narrow-screen button. */
  explorerSummary?: string;
  storageKey: string;
  toolbar?: React.ReactNode;
  children: React.ReactNode;
}) {
  const panelId = useId();
  const [wideOpen, setWideOpen] = useState(() => readFlag(`argus.browse.${storageKey}.panel`, true));
  const [narrowOpen, setNarrowOpen] = useState(false);
  const toggleWide = () => setWideOpen((v) => { writeFlag(`argus.browse.${storageKey}.panel`, !v); return !v; });
  return (
    <div className="mx-auto max-w-[1600px] space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <h1 className="truncate text-xl font-semibold text-slate-900 sm:text-2xl">{title}</h1>
          {count !== undefined && <span className="shrink-0 text-sm tabular-nums text-slate-500">{count}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {primary}
        </div>
      </header>
      <div className={`grid gap-4 ${explorer && wideOpen ? "lg:grid-cols-[13rem_minmax(0,1fr)] xl:grid-cols-[15rem_minmax(0,1fr)]" : "grid-cols-1"}`}>
        {explorer && (
          <>
            {/* Narrow screens: the panel opens above the results. */}
            <div className="lg:hidden">
              <button type="button" aria-expanded={narrowOpen} aria-controls={panelId}
                      onClick={() => setNarrowOpen((v) => !v)}
                      className="flex w-full items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
                <span className="min-w-0 truncate">{explorerLabel ?? "Types"}: <b>{explorerSummary ?? "all"}</b></span>
                <span aria-hidden className="text-slate-400">{narrowOpen ? "▴" : "▾"}</span>
              </button>
            </div>
            <aside id={panelId}
                   className={`${narrowOpen ? "block" : "hidden"} ${wideOpen ? "lg:flex" : "lg:hidden"} max-h-[70vh] flex-col rounded-lg border border-slate-200 bg-white p-3 lg:sticky lg:top-0 lg:max-h-[calc(100vh-8rem)]`}>
              {explorer}
            </aside>
          </>
        )}
        <div className="min-w-0 space-y-3">
          {(toolbar || explorer) && (
            <div className="flex flex-wrap items-center gap-2">
              {explorer && (
                <button type="button" onClick={toggleWide} aria-expanded={wideOpen} aria-controls={panelId}
                        className="hidden shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 lg:inline-flex"
                        title={wideOpen ? "Hide the type panel" : "Show the type panel"}>
                  {wideOpen ? "⟨ Types" : "Types ⟩"}
                </button>
              )}
              {toolbar}
            </div>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}

/** The search box of a browse page. */
export function SearchBox({ value, onChange, placeholder, label }: {
  value: string; onChange: (v: string) => void; placeholder: string; label: string;
}) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  // The address is written once typing pauses, not on every key.
  useEffect(() => {
    if (draft === value) return;
    const t = setTimeout(() => onChange(draft), 200);
    return () => clearTimeout(t);
  }, [draft, value, onChange]);
  return (
    <div className="min-w-[12rem] flex-1">
      <label htmlFor={id} className="sr-only">{label}</label>
      <input id={id} type="search" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={placeholder}
             className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500" />
    </div>
  );
}

/** A small labelled select for the toolbar. */
export function ToolbarSelect({ label, value, onChange, children }: {
  label: string; value: string; onChange: (v: string) => void; children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-1 text-xs text-slate-500">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}
              className="max-w-[13rem] rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
        {children}
      </select>
    </label>
  );
}

// --------------------------------------------------------------------------- views

/** List, board, map: the same records seen differently. Each link keeps the filters in the address. */
export function ViewSwitch({ views }: { views: { label: string; to: string; current: boolean }[] }) {
  const { search } = useLocation();
  return (
    <nav aria-label="View" className="inline-flex shrink-0 overflow-hidden rounded-md border border-slate-300 bg-white text-sm">
      {views.map((v) => {
        const [path, own] = v.to.split("?");
        const merged = new URLSearchParams(search);
        merged.delete("page");
        new URLSearchParams(own ?? "").forEach((val, k) => merged.set(k, val));
        const qs = merged.toString();
        return (
          <Link key={v.label} to={`${path}${qs ? `?${qs}` : ""}`} aria-current={v.current ? "page" : undefined}
                className={`px-3 py-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500 ${
                  v.current ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`}>
            {v.label}
          </Link>
        );
      })}
    </nav>
  );
}

// --------------------------------------------------------------------------- menus

/** A disclosure menu of links and actions (Tools…), closed by Escape or a click outside. */
export function MenuButton({ label, items, align = "right" }: {
  label: React.ReactNode;
  items: ({ to: string; label: string; hint?: string } | { onClick: () => void; label: string; hint?: string })[];
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  if (items.length === 0) return null;
  return (
    <div className="relative" ref={ref}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
        {label} <span aria-hidden className="text-slate-400">▾</span>
      </button>
      {open && (
        <ul id={id} className={`absolute z-30 mt-1 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg ${
          align === "right" ? "right-0" : "left-0"}`}>
          {items.map((i) => (
            <li key={i.label}>
              {"to" in i ? (
                <Link to={i.to} onClick={() => setOpen(false)}
                      className="block px-3 py-1.5 hover:bg-slate-50 focus-visible:bg-slate-100 focus-visible:outline-none">
                  <span className="block text-sm text-slate-800">{i.label}</span>
                  {i.hint && <span className="block text-xs text-slate-500">{i.hint}</span>}
                </Link>
              ) : (
                <button type="button" onClick={() => { setOpen(false); i.onClick(); }}
                        className="block w-full px-3 py-1.5 text-left hover:bg-slate-50 focus-visible:bg-slate-100 focus-visible:outline-none">
                  <span className="block text-sm text-slate-800">{i.label}</span>
                  {i.hint && <span className="block text-xs text-slate-500">{i.hint}</span>}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- columns

export interface ColumnDef {
  id: string;
  label: string;
  /** Always shown (the column that identifies the row). */
  required?: boolean;
  /** Shown until the person chooses otherwise. */
  initial?: boolean;
}

/** Which columns a list shows: the few needed to scan it by default, the rest a choice remembered in this browser. */
export function useColumns(listKey: string, defs: ColumnDef[]) {
  const storage = `argus.columns.${listKey}`;
  const [chosen, setChosen] = useState<string[] | null>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(storage) ?? "null");
      return Array.isArray(v) ? v : null;
    } catch {
      return null;
    }
  });
  const visible = useMemo(() => {
    const set = new Set(chosen ?? defs.filter((d) => d.initial || d.required).map((d) => d.id));
    defs.filter((d) => d.required).forEach((d) => set.add(d.id));
    return set;
  }, [chosen, defs]);
  const toggle = (id: string) => {
    const next = new Set(visible);
    if (next.has(id)) next.delete(id); else next.add(id);
    const list = defs.map((d) => d.id).filter((x) => next.has(x));
    setChosen(list);
    try { localStorage.setItem(storage, JSON.stringify(list)); } catch { /* this page only */ }
  };
  const reset = () => {
    setChosen(null);
    try { localStorage.removeItem(storage); } catch { /* ignore */ }
  };
  return { show: (id: string) => visible.has(id), visible, toggle, reset, defs, count: visible.size };
}

export function ColumnSettings({ columns }: { columns: ReturnType<typeof useColumns> }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="relative" ref={ref}>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500">
        Columns <span aria-hidden className="text-slate-400">▾</span>
      </button>
      {open && (
        <fieldset id={id} className="absolute right-0 z-30 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
          <legend className="sr-only">Columns to show</legend>
          {columns.defs.map((d) => (
            <label key={d.id} className={`flex items-center gap-2 rounded px-2 py-1 text-sm ${d.required ? "text-slate-400" : "text-slate-700 hover:bg-slate-50"}`}>
              <input type="checkbox" checked={columns.show(d.id)} disabled={d.required} onChange={() => columns.toggle(d.id)} />
              {d.label}
            </label>
          ))}
          <button type="button" onClick={columns.reset} className="mt-1 w-full rounded px-2 py-1 text-left text-xs text-slate-500 hover:bg-slate-50">
            Back to the default columns
          </button>
        </fieldset>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- paging

export const PAGE_SIZE = 50;

/** One page of the rows: a long list renders 50 rows at a time, never the whole of it. The page is in the
 * address with the filters, and a new filter starts again on the first. */
export function usePage<T>(rows: T[], size = PAGE_SIZE) {
  const { get, set } = useBrowseParams();
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const page = Math.min(Math.max(1, Number(get("page", "1")) || 1), pages);
  const slice = useMemo(() => rows.slice((page - 1) * size, page * size), [rows, page, size]);
  return { rows: slice, page, pages, total: rows.length, size, go: (p: number) => set({ page: p > 1 ? String(p) : null }) };
}

export function Pager({ paging, noun }: { paging: ReturnType<typeof usePage<unknown>>; noun: string }) {
  const { page, pages, total, size, go } = paging;
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  return (
    <nav aria-label={`Pages of ${noun}`} className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
      <span aria-live="polite">{total === 0 ? `No ${noun}` : `${from}–${to} of ${total} ${noun}`}</span>
      {pages > 1 && (
        <span className="flex items-center gap-1">
          <button type="button" onClick={() => go(page - 1)} disabled={page <= 1} aria-label="Previous page"
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-700 hover:bg-slate-50 disabled:opacity-40">‹ Previous</button>
          <span className="px-1 tabular-nums">Page {page} of {pages}</span>
          <button type="button" onClick={() => go(page + 1)} disabled={page >= pages} aria-label="Next page"
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-slate-700 hover:bg-slate-50 disabled:opacity-40">Next ›</button>
        </span>
      )}
    </nav>
  );
}

// --------------------------------------------------------------------------- cells

/** Text cut to its cell, whole in the tooltip and to a screen reader. */
export function Clip({ children, title, className = "" }: { children: React.ReactNode; title?: string; className?: string }) {
  const text = title ?? (typeof children === "string" ? children : undefined);
  return <span className={`block truncate ${className}`} title={text}>{children}</span>;
}

const STATE: Record<string, { icon: string; cls: string }> = {
  new: { icon: "○", cls: "bg-slate-100 text-slate-700" },
  in_progress: { icon: "◐", cls: "bg-blue-100 text-blue-800" },
  pending: { icon: "⏸", cls: "bg-amber-100 text-amber-900" },
  resolved: { icon: "✓", cls: "bg-green-100 text-green-800" },
  closed: { icon: "●", cls: "bg-slate-200 text-slate-600" },
};

/** A ticket state: a shape and the word, not only a colour. */
export function StateBadge({ state, label }: { state: string; label?: string }) {
  const s = STATE[state] ?? { icon: "•", cls: "bg-slate-100 text-slate-700" };
  const text = label ?? state.replace(/_/g, " ");
  return (
    <span className={`inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-xs ${s.cls}`}>
      <span aria-hidden>{s.icon}</span>
      <span className="truncate capitalize">{text}</span>
    </span>
  );
}

const PRIORITY: Record<string, { icon: string; cls: string }> = {
  blocker: { icon: "⛔", cls: "text-red-700" },
  critical: { icon: "‼", cls: "text-red-700" },
  highest: { icon: "⇈", cls: "text-red-700" },
  urgent: { icon: "‼", cls: "text-red-700" },
  high: { icon: "↑", cls: "text-orange-700" },
  major: { icon: "↑", cls: "text-orange-700" },
  medium: { icon: "→", cls: "text-slate-700" },
  normal: { icon: "→", cls: "text-slate-700" },
  low: { icon: "↓", cls: "text-slate-500" },
  minor: { icon: "↓", cls: "text-slate-500" },
  lowest: { icon: "⇊", cls: "text-slate-500" },
  trivial: { icon: "⇊", cls: "text-slate-500" },
};

/** A priority: an arrow and the word, not only a colour. */
export function PriorityBadge({ priority, label }: { priority: string | null | undefined; label?: string }) {
  if (!priority) return <span className="text-slate-300">—</span>;
  const p = PRIORITY[priority.toLowerCase()] ?? { icon: "•", cls: "text-slate-700" };
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-xs ${p.cls}`}>
      <span aria-hidden className="w-3 text-center">{p.icon}</span>
      <span className="capitalize">{label ?? priority}</span>
    </span>
  );
}

// --------------------------------------------------------------------------- selection

/** The rows ticked on a list, kept for the browser tab so a trip to the board or the map and back keeps them. */
export function useSelection(listKey: string) {
  const storage = `argus.selection.${listKey}`;
  const [selected, setSelectedState] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(sessionStorage.getItem(storage) ?? "[]"));
    } catch {
      return new Set();
    }
  });
  const setSelected = useCallback((next: Set<string>) => {
    setSelectedState(next);
    try { sessionStorage.setItem(storage, JSON.stringify([...next])); } catch { /* this page only */ }
  }, [storage]);
  const toggle = (uid: string) => {
    const next = new Set(selected);
    if (next.has(uid)) next.delete(uid); else next.add(uid);
    setSelected(next);
  };
  return { selected, setSelected, toggle, clear: () => setSelected(new Set()) };
}

/** The header checkbox: all the rows on this page, indeterminate when some are. */
export function SelectAll({ rows, selection, noun }: {
  rows: string[]; selection: ReturnType<typeof useSelection>; noun: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const on = rows.filter((r) => selection.selected.has(r)).length;
  useEffect(() => { if (ref.current) ref.current.indeterminate = on > 0 && on < rows.length; }, [on, rows.length]);
  return (
    <input ref={ref} type="checkbox" checked={rows.length > 0 && on === rows.length} aria-label={`Select all ${noun} on this page`}
           onChange={() => {
             const next = new Set(selection.selected);
             if (on === rows.length) rows.forEach((r) => next.delete(r)); else rows.forEach((r) => next.add(r));
             selection.setSelected(next);
           }} />
  );
}
