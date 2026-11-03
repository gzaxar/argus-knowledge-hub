import { describe, expect, it } from "vitest";
import { linkSpeed, portKind, portsFromModel } from "../lib/modelPorts";

describe("a model's ports, offered to a new unit", () => {
  it("reads NetBox types as kinds and speeds", () => {
    expect([portKind("1000base-t"), portKind("10gbase-x-sfpp"), portKind("25gbase-x-sfp28"), portKind("usb-mini-b", true),
            portKind("rj-45", true), portKind("de-9", true), portKind("cisco-stackwise")])
      .toEqual(["RJ45", "SFP", "SFP", "USB", "RS-232", "RS-232", "Other"]);
    expect([linkSpeed("1000base-t"), linkSpeed("100base-tx"), linkSpeed("10gbase-x-sfpp"), linkSpeed("2.5gbase-t"),
            linkSpeed("cisco-stackwise")]).toEqual(["1 Gb/s", "100 Mb/s", "10 Gb/s", "2.5 Gb/s", undefined]);
  });

  it("lists the physical interfaces, the management one and the consoles, ticked", () => {
    const components = JSON.stringify({
      interfaces: [{ name: "Gi1/0/1", type: "1000base-t", poe_mode: "pse", poe_type: "type2-ieee802.3at" },
                   { name: "Vlan1", type: "virtual" }, { name: "Gi0/0", type: "1000base-t", mgmt_only: true }],
      console_ports: [{ name: "Console", type: "rj-45" }],
      console_server_ports: [{ name: "P1", label: "Port 1", type: "de-9", description: "RS-232/422/485" }],
      power_ports: [{ name: "PS-A", type: "iec-60320-c14" }],
    });
    expect(portsFromModel(components)).toEqual([
      { port_label: "Gi1/0/1", port_kind: "RJ45", link_speed: "1 Gb/s", port_settings: "1000base-t · PoE PSE type2-ieee802.3at", on: true },
      { port_label: "Gi0/0", port_kind: "RJ45", link_speed: "1 Gb/s", port_role: "management", port_settings: "1000base-t", on: true },
      { port_label: "Console", port_kind: "RS-232", port_role: "console", port_settings: "rj-45", on: true },
      { port_label: "Port 1", port_kind: "RS-232", port_settings: "de-9 · RS-232/422/485", on: true },
    ]);
    expect(portsFromModel(undefined)).toEqual([]);
    expect(portsFromModel("not json")).toEqual([]);
  });
});
