import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export interface SortState {
  key: string;
  dir: SortDir;
}

type Value = string | number | boolean | Date | null | undefined;

/** Ordering a list by any of its columns: a click on a header sorts by it, a second click reverses it.
 *
 * Empty values go last whichever the direction, so "newest first" never opens on a page of blanks. Text is
 * compared as people read it: "OLOG-BTF-9" comes before "OLOG-BTF-80", accents and case do not matter.
 * The choice is remembered per list (`storageKey`) in this browser. */
export function useSort<T>(
  rows: T[] | undefined,
  columns: Record<string, (row: T) => Value>,
  initial: SortState,
  storageKey?: string,
) {
  const [sort, setSortState] = useState<SortState>(() => {
    if (!storageKey) return initial;
    try {
      const saved = JSON.parse(localStorage.getItem(`argus.sort.${storageKey}`) ?? "null");
      if (saved && typeof saved.key === "string" && saved.key in columns && (saved.dir === "asc" || saved.dir === "desc"))
        return saved as SortState;
    } catch {
      /* unreadable or blocked storage: start from the default */
    }
    return initial;
  });

  const setSort = (next: SortState) => {
    setSortState(next);
    if (storageKey) {
      try {
        localStorage.setItem(`argus.sort.${storageKey}`, JSON.stringify(next));
      } catch {
        /* private window: remembered for this page only */
      }
    }
  };

  // A first click on a time column shows the newest first; on anything else, A to Z.
  const toggle = (key: string, firstDir: SortDir = "asc") =>
    setSort(sort.key === key ? { key, dir: sort.dir === "asc" ? "desc" : "asc" } : { key, dir: firstDir });

  const sorted = useMemo(() => {
    const get = columns[sort.key];
    if (!rows || !get) return rows ?? [];
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      const xEmpty = x === null || x === undefined || x === "";
      const yEmpty = y === null || y === undefined || y === "";
      if (xEmpty || yEmpty) return xEmpty === yEmpty ? 0 : xEmpty ? 1 : -1;
      return sign * compare(x, y);
    });
    // columns is a fresh object each render; what it reads is in rows and sort.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort.key, sort.dir]);

  return { sorted, sort, toggle };
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function compare(x: Exclude<Value, null | undefined>, y: Exclude<Value, null | undefined>): number {
  if (x instanceof Date && y instanceof Date) return x.getTime() - y.getTime();
  if (typeof x === "number" && typeof y === "number") return x - y;
  if (typeof x === "boolean" && typeof y === "boolean") return Number(x) - Number(y);
  return collator.compare(String(x), String(y));
}

/** A column header that sorts the list. Time columns start with the newest first (`time`). */
export function SortHeader({
  label,
  column,
  sort,
  onSort,
  time = false,
  className = "px-4 py-2",
  rowSpan,
}: {
  label: string;
  column: string;
  sort: SortState;
  onSort: (key: string, firstDir?: SortDir) => void;
  time?: boolean;
  className?: string;
  /** For a header of more than one row. */
  rowSpan?: number;
}) {
  const active = sort.key === column;
  const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "↕";
  return (
    <th className={className} rowSpan={rowSpan} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={() => onSort(column, time ? "desc" : "asc")}
        className={`inline-flex items-center gap-1 uppercase hover:text-slate-800 ${active ? "text-slate-800" : ""}`}
        title={`Sort by ${label.toLowerCase()}`}
      >
        {label}
        <span className={`text-[10px] ${active ? "" : "text-slate-300"}`}>{arrow}</span>
      </button>
    </th>
  );
}

/** A date for a list cell: the day, with the time in the tooltip. */
export function ListDate({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-300">—</span>;
  const d = new Date(value);
  return <span title={d.toLocaleString()}>{d.toLocaleDateString()}</span>;
}

const PRIORITY_RANK = ["blocker", "critical", "highest", "urgent", "high", "major", "medium", "normal", "minor", "low",
  "lowest", "trivial"];

/** A ticket priority as a rank, so "Critical" sorts before "Low" rather than after it. Unknown ones go after. */
export function priorityRank(priority: string | null | undefined): number | null {
  if (!priority) return null;
  const i = PRIORITY_RANK.indexOf(priority.trim().toLowerCase());
  return i === -1 ? PRIORITY_RANK.length : i;
}
