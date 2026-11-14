import { useState } from "react";
import { Link } from "react-router-dom";

export interface Listed { uid: string; name: string; type: string; note?: string }

/** Records grouped by type, the most numerous first, when there are many: one line per type with its count, opened
 *  to list its records. A few are listed as they are. */
export function groupByType<T extends Listed>(items: T[]): [string, T[]][] {
  const by = new Map<string, T[]>();
  for (const i of items) by.set(i.type, [...(by.get(i.type) ?? []), i]);
  return [...by.entries()]
    .map(([t, xs]) => [t, [...xs].sort((a, b) => a.name.localeCompare(b.name))] as [string, T[]])
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
}

export function GroupedRecords({ items, flat = 12 }: { items: Listed[]; flat?: number }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const row = (i: Listed, withType: boolean) => (
    <li key={`${i.uid}:${i.note ?? ""}`}>
      <Link to={`/assets/${i.uid}`} className="text-indigo-700 hover:underline">{i.name}</Link>
      <span className="text-slate-500">{withType ? ` · ${i.type}` : ""}{i.note ? ` · ${i.note}` : ""}</span>
    </li>
  );
  if (items.length <= flat) return <ul className="mt-1 space-y-0.5 text-xs">{items.map((i) => row(i, true))}</ul>;
  return (
    <ul className="mt-1 max-h-80 space-y-0.5 overflow-auto text-xs">
      {groupByType(items).map(([type, xs]) => {
        const shown = open.has(type);
        return (
          <li key={type}>
            <button type="button" aria-expanded={shown} className="text-left text-slate-700 hover:text-slate-900"
                    onClick={() => setOpen((s) => { const n = new Set(s); if (n.has(type)) n.delete(type); else n.add(type); return n; })}>
              <span aria-hidden="true" className="inline-block w-3 text-slate-400">{shown ? "▾" : "▸"}</span>
              {type} <span className="text-slate-400">({xs.length})</span>
            </button>
            {shown && <ul className="ml-4 mt-0.5 space-y-0.5">{xs.map((i) => row(i, false))}</ul>}
          </li>
        );
      })}
    </ul>
  );
}
