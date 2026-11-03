import type { PortChoice } from "../components/ProposedPorts";

type Component = Record<string, unknown>;

/** A NetBox interface or console type as an Equipment Port kind. */
export function portKind(type: string, serial = false): string {
  const t = type.toLowerCase();
  if (t.startsWith("usb")) return "USB";
  if (/sfp|qsfp|xfp|cfp|gbic|-x-|base-x\b|base-[lsez]r/.test(t)) return "SFP";
  if (serial || t === "de-9" || t === "db-25" || t === "rj-11" || t === "rj-12") {
    return t === "rj-45" || t.startsWith("de-") || t.startsWith("db-") || t.startsWith("rj-1") ? "RS-232" : "Other";
  }
  if (/base-t|base-tx|rj-45|^1000base|^100base|^10gbase-t|^2\.5gbase|^5gbase/.test(t)) return "RJ45";
  return "Other";
}

/** 1000base-t → 1 Gb/s; 100base-tx → 100 Mb/s; 10gbase-x-sfpp → 10 Gb/s. */
export function linkSpeed(type: string): string | undefined {
  const m = /^(\d+(?:\.\d+)?)(g?)base/i.exec(type);
  if (!m) return undefined;
  const mbps = Number(m[1]) * (m[2] ? 1000 : 1);
  return mbps >= 1000 ? `${mbps / 1000} Gb/s` : `${mbps} Mb/s`;
}

const VIRTUAL = new Set(["virtual", "lag", "bridge"]);

/** The sockets a model's components list (its physical interfaces, console and serial ports), as ports a new
 *  unit of it is offered: ticked, each one an Equipment Port “port of” the unit. */
export function portsFromModel(components: unknown): PortChoice[] {
  let c: Record<string, Component[]>;
  try {
    c = typeof components === "string" ? JSON.parse(components) : (components as Record<string, Component[]>);
  } catch {
    return [];
  }
  if (!c || typeof c !== "object") return [];
  const out: PortChoice[] = [];
  const str = (v: unknown) => (v === undefined || v === null ? "" : String(v));
  for (const i of c.interfaces ?? []) {
    const type = str(i.type);
    if (VIRTUAL.has(type)) continue;
    out.push({
      port_label: str(i.label) || str(i.name), port_kind: portKind(type), link_speed: linkSpeed(type),
      port_role: i.mgmt_only ? "management" : undefined,
      port_settings: [type, i.poe_mode ? `PoE ${str(i.poe_mode).toUpperCase()} ${str(i.poe_type)}`.trim() : "",
                      str(i.description)].filter(Boolean).join(" · ") || undefined,
      on: true,
    });
  }
  for (const [key, role] of [["console_ports", "console"], ["console_server_ports", undefined]] as const) {
    for (const p of c[key] ?? []) {
      const type = str(p.type);
      out.push({
        port_label: str(p.label) || str(p.name), port_kind: portKind(type, true), port_role: role,
        port_settings: [type, str(p.description)].filter(Boolean).join(" · ") || undefined, on: true,
      });
    }
  }
  return out.map((p) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined)) as PortChoice);
}
