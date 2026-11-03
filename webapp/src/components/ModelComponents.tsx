const KINDS: Record<string, string> = {
  interfaces: "Interfaces", console_ports: "Console ports", console_server_ports: "Serial ports",
  power_ports: "Power inputs", power_outlets: "Power outlets", front_ports: "Front ports", rear_ports: "Rear ports",
  port_mappings: "Front-to-rear mappings", module_bays: "Module bays", device_bays: "Device bays",
  inventory_items: "Parts",
};

/** A model's components, as its source lists them: one table per kind, a column per property. */
export function ModelComponents({ value }: { value: unknown }) {
  let c: Record<string, Record<string, unknown>[]>;
  try {
    c = typeof value === "string" ? JSON.parse(value) : (value as typeof c);
  } catch {
    return <span className="text-slate-400">—</span>;
  }
  if (!c || typeof c !== "object" || !Object.keys(c).length) return <span className="text-slate-400">—</span>;
  return (
    <div className="space-y-2">
      {Object.entries(c).map(([kind, items]) => {
        const cols = [...new Set(items.flatMap((i) => Object.keys(i)))];
        return (
          <details key={kind} className="rounded border border-slate-100">
            <summary className="cursor-pointer px-2 py-1 text-xs font-medium text-slate-600">
              {KINDS[kind] ?? kind} <span className="font-normal text-slate-400">{items.length}</span>
            </summary>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500">
                  <tr>{cols.map((k) => <th key={k} className="px-2 py-1 font-medium">{k.replace(/_/g, " ")}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {items.map((i, n) => (
                    <tr key={n}>{cols.map((k) => <td key={k} className="px-2 py-0.5">{i[k] === true ? "yes" : String(i[k] ?? "")}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        );
      })}
    </div>
  );
}
