import type { PortAttributes } from "../api/client";

export type PortChoice = PortAttributes & { on: boolean };

/** A serial port's settings in one line, as a converter's page writes them: 9600 · 8N1 · RTS/CTS. */
export function portSettings(p: PortAttributes): string {
  return [p.baud ? `${p.baud}` : null, p.framing, p.flow_control && p.flow_control !== "None" ? p.flow_control : null,
          p.link_speed, p.port_settings].filter(Boolean).join(" · ");
}

/** The unit's ports a file or a description lists, one row each, ticked to be made as Equipment Ports
 *  (“port of” the unit) with their settings. */
export function ProposedPorts({ ports, onToggle, title = "Its ports",
  note = "Read from the file: each ticked port becomes an Equipment Port record, “port of” this one, with its settings." }: {
  ports: PortChoice[]; onToggle: (index: number, on: boolean) => void; title?: string; note?: string;
}) {
  if (!ports.length) return null;
  const all = ports.every((p) => p.on);
  return (
    <fieldset className="rounded-md border border-slate-200 bg-white p-3">
      <legend className="px-1 text-sm font-medium text-slate-800">{title}</legend>
      <p className="text-xs text-slate-500">{note}</p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="w-6 py-1">
                <input type="checkbox" aria-label="All ports" checked={all}
                       onChange={(e) => ports.forEach((_, i) => onToggle(i, e.target.checked))} />
              </th>
              <th className="py-1 pr-2">Port</th>
              <th className="py-1 pr-2">Kind</th>
              <th className="py-1 pr-2">Alias</th>
              <th className="py-1 pr-2">Settings</th>
              <th className="py-1">TCP port</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700">
            {ports.map((p, i) => (
              <tr key={`${p.port_label}-${i}`}>
                <td className="py-1">
                  <input type="checkbox" aria-label={`Add ${p.port_label}`} checked={p.on}
                         onChange={(e) => onToggle(i, e.target.checked)} />
                </td>
                <td className="py-1 pr-2 font-medium">{p.port_label}</td>
                <td className="py-1 pr-2">{p.port_kind}</td>
                <td className="py-1 pr-2">{p.port_role ?? ""}</td>
                <td className="py-1 pr-2">{portSettings(p)}</td>
                <td className="py-1 font-mono">{p.tcp_port ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </fieldset>
  );
}

/** What a port choice sends: its fields, without the tick. */
export function portBody({ on: _on, ...p }: PortChoice): PortAttributes {
  return p;
}
