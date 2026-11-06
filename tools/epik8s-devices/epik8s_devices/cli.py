"""epik8s-devices — turn a beamline's control configuration into an inventory.

Three steps, kept separate on purpose. `scan` reads the configuration and
writes a file you can open and correct. `match` proposes which physical
asset each device already is. `push` writes the result into a hub.

Nothing is written anywhere until you run `push`, and `push` names the
workspace it is about to write into before it does.
"""
import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict
from typing import Optional

import yaml

from .catalogue import load_templates
from .hub import Hub, HubError
from .match import Inventory
from .scan import Device, scan_file

DEFAULT_TEMPLATES = "../infn-epics-ioc/ibek-templates"


def _write(rows: list[dict], path: Optional[str], fmt: str) -> None:
    if fmt == "csv":
        columns = ["key", "beamline", "ioc", "name", "pv", "device_class", "vendor",
                   "model", "element", "system", "physical_asset", "needs"]
        handle = open(path, "w", newline="") if path else sys.stdout
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "needs": "; ".join(row.get("needs") or [])})
        if path:
            handle.close()
        return

    text = (json.dumps(rows, indent=2, default=str) if fmt == "json"
            else yaml.safe_dump(rows, sort_keys=False, allow_unicode=True))
    if path:
        with open(path, "w") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)


def _summary(rows: list[dict]) -> str:
    total = len(rows)
    classified = sum(1 for r in rows if r.get("device_class"))
    elements = sum(1 for r in rows if r.get("element"))
    specs = sum(1 for r in rows if r.get("model_spec"))
    by_class: dict[str, int] = {}
    for row in rows:
        by_class[row.get("device_class") or "(unclassified)"] = \
            by_class.get(row.get("device_class") or "(unclassified)", 0) + 1
    lines = [
        f"{total} devices — {classified} classified from an ibek template, "
        f"{elements} with the element they serve read from the name, "
        f"{specs} carrying a rating (ps:/motor:)",
    ]
    for name, count in sorted(by_class.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {count:5d}  {name}")
    return "\n".join(lines)


def cmd_scan(args) -> int:
    templates = load_templates(args.templates)
    if not templates:
        print(f"! no ibek templates found at {args.templates} — devices will be "
              f"classified only where a built-in fallback covers them",
              file=sys.stderr)
    else:
        print(f"{len(templates)} device templates read from {args.templates}",
              file=sys.stderr)

    devices: list[Device] = []
    for path in args.values:
        found = scan_file(path, templates)
        print(f"{path}: {len(found)} devices", file=sys.stderr)
        devices.extend(found)

    rows = [asdict(d) for d in devices]
    print(_summary(rows), file=sys.stderr)
    _write(rows, args.out, args.format)
    if args.out:
        print(f"\nwritten to {args.out} — open it, correct it, then `match` or `push`",
              file=sys.stderr)
    return 0


def cmd_match(args) -> int:
    rows = yaml.safe_load(open(args.devices)) or []
    hub = Hub(args.hub, args.token)
    me = hub.whoami()
    workspace = me.get("workspace_id") or (me.get("user") or {}).get("email") or "?"
    print(f"matching against {args.hub} as workspace {workspace}", file=sys.stderr)

    inventory = Inventory(hub.assets())
    print(f"{len(inventory.assets)} objects in the inventory", file=sys.stderr)

    matched = ambiguous = 0
    for row in rows:
        proposal = inventory.for_device(row)
        if proposal.get("uid"):
            row["physical_asset"] = proposal["uid"]
            row["physical_asset_evidence"] = {
                k: v for k, v in proposal.items() if k != "uid"
            }
            matched += 1
        elif proposal.get("ambiguous"):
            row["physical_asset_candidates"] = proposal["ambiguous"]
            ambiguous += 1

    print(f"{matched} proposed, {ambiguous} with more than one candidate "
          f"(left for you), {len(rows) - matched - ambiguous} unmatched",
          file=sys.stderr)
    _write(rows, args.out or args.devices, "yaml")
    return 0


# The objects `push` writes are the object catalogue's own types, made by
# backend/scripts/seed_asset_types.py, not types of its own: a row describes a
# control channel, so it is a Control Device, and what class of hardware it drives
# is a value it carries.
CONTROL_DEVICE = "Control Device"
IOC = "IOC"
REVIEW_KEYS = ("device_class", "element", "vendor", "model_code", "argus_keywords")


def object_identity(row: dict) -> str:
    """What the hub's own configuration import derives the uid from, so the two write
    to one object rather than building two trees nobody reconciles."""
    tag, ioc, name = row["beamline"], row["ioc"], row["name"]
    return f"{tag}:IOC:{ioc}" if _is_ioc_row(row) else f"{tag}:DEV:{ioc}:{name}"


def object_key(row: dict) -> str:
    """The key the hub's import shows for the same thing (services/epik8s_import.py, public_key)."""
    return object_identity(row).replace(":", "-")


def object_uid(workspace: str, identity: str) -> str:
    """Deterministic, and the same as the hub's import derives (services/epik8s_import.py)."""
    return "epik8s-" + hashlib.sha1(f"{workspace}:{identity}".encode()).hexdigest()[:24]


def _is_ioc_row(row: dict) -> bool:
    # Rows written before the marker existed: an IOC with no device list is named
    # for the IOC itself.
    return bool(row.get("ioc_only", row.get("name") == row.get("ioc")))


def _present(attributes: dict) -> dict:
    return {k: v for k, v in attributes.items() if v not in (None, "", [], {})}


def review_attributes(row: dict) -> dict:
    """What a person's review adds to an object the hub already has: the class of
    hardware, the element it serves, the vendor and model as found. Only what is
    said: an empty cell never erases a value somebody entered in the hub."""
    return _present({
        "device_class": row.get("device_class"),
        "element": row.get("element"),
        "vendor": row.get("vendor"),
        "model_code": row.get("model"),
        # What is still missing from the row, so "what is incomplete" is one filter.
        "argus_keywords": row.get("needs"),
    })


def new_device_attributes(row: dict) -> dict:
    """A Control Device the hub does not have yet: everything the scan read."""
    conn = row.get("connection") or {}
    settings = {**(row.get("model_spec") or {}), **(row.get("settings") or {})}
    return _present({
        "beamline": row.get("beamline"),
        "pv": row.get("pv"),
        "pv_prefix": row.get("pv"),
        "ioc": row.get("ioc"),
        "system": row.get("system"),
        "function": row.get("function"),
        "zones": row.get("zones"),
        "address": conn.get("host"),
        "port": conn.get("port"),
        "channel": conn.get("channel"),
        "axis": conn.get("axis"),
        "settings": settings,
        "argus_facility": row.get("beamline"),
        "argus_source": "epik8s-devices",
        "argus_source_ref": row.get("source"),
        **review_attributes(row),
    })


def _find_types(hub: Hub, workspace: str) -> dict:
    """The two catalogue types `push` writes, this workspace's own before a shared one."""
    found: dict = {}
    for schema in sorted(hub.schemas(), key=lambda s: s.get("workspace_id") != workspace):
        found.setdefault(schema["name"], schema)
    missing = [n for n in (CONTROL_DEVICE, IOC) if n not in found]
    if missing:
        raise HubError(
            f"This workspace has no {' or '.join(missing)} type. `push` writes the object "
            f"catalogue's types and makes none of its own: seed them first with "
            f"backend/scripts/seed_asset_types.py, then push again.")
    return found


def cmd_push(args) -> int:
    rows = yaml.safe_load(open(args.devices)) or []
    hub = Hub(args.hub, args.token)
    workspace = hub.whoami().get("workspace_id")
    if not workspace:
        raise HubError("The hub did not say which workspace this token is for.")
    types = _find_types(hub, workspace)

    devices = [r for r in rows if not _is_ioc_row(r)]
    ioc_rows = [r for r in rows if _is_ioc_row(r)]
    linked = [r for r in rows if r.get("physical_asset")]
    print(f"About to write into workspace {workspace} at {args.hub}:")
    print(f"  {len(devices)} Control Devices, added to what the hub already has")
    print(f"  {len(ioc_rows)} IOC-only rows, which are IOCs the configuration import made; "
          f"only their physical-asset link is written")
    print(f"  {len(linked)} link(s) to a physical asset")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return 0
    if not args.yes:
        answer = input("Type the workspace id to confirm: ").strip()
        if answer != workspace:
            print("Not confirmed; nothing written.")
            return 1

    known = {(r["from_asset_uid"], r["to_asset_uid"], r["relation_type"]) for r in hub.relations()}
    created = updated = related = skipped = failed = 0
    for row in rows:
        key = object_key(row)
        uid = object_uid(workspace, object_identity(row))
        ioc_row = _is_ioc_row(row)
        try:
            existing = hub.get_asset(uid)
            if ioc_row and existing is None:
                skipped += 1
                print(f"  - {key}: not in the hub. Import the configuration first "
                      f"(scripts/import_epik8s.py), then push.", file=sys.stderr)
                continue
            if existing is None:
                hub.create_asset({
                    "uid": uid, "schema_uid": types[CONTROL_DEVICE]["uid"], "key": key,
                    "name": row["name"], "type": CONTROL_DEVICE,
                    "attributes": new_device_attributes(row),
                })
                created += 1
            elif not ioc_row:
                overlay = review_attributes(row)
                current = existing.get("attributes") or {}
                if any(current.get(k) != v for k, v in overlay.items()):
                    hub.update_asset(uid, {"attributes": {**(existing.get("attributes") or {}),
                                                          **overlay}})
                    updated += 1
            target = row.get("physical_asset")
            if target:
                relation = "drives" if ioc_row else "acts on"
                if (uid, target, relation) not in known:
                    hub.create_relation(uid, target, relation)
                    known.add((uid, target, relation))
                    related += 1
        except HubError as e:
            failed += 1
            print(f"  ! {key}: {e}", file=sys.stderr)
    print(f"{created} created, {updated} updated, {related} linked to a physical asset, "
          f"{skipped} skipped, {failed} failed")
    return 0 if not failed else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="epik8s-devices",
        description="Turn an EPIK8s beamline configuration into a device inventory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="read values.yaml into a device list")
    scan_parser.add_argument("values", nargs="+", help="one or more values.yaml")
    scan_parser.add_argument("--templates", default=DEFAULT_TEMPLATES,
                             help="path to infn-epics-ioc/ibek-templates")
    scan_parser.add_argument("--out", help="write here instead of stdout")
    scan_parser.add_argument("--format", choices=("yaml", "json", "csv"), default="yaml")
    scan_parser.set_defaults(func=cmd_scan)

    match_parser = sub.add_parser("match", help="propose the physical asset each device is")
    match_parser.add_argument("devices", help="the file `scan` wrote")
    match_parser.add_argument("--hub", required=True, help="https://assets-api…")
    match_parser.add_argument("--token", required=True, help="a workspace PAT")
    match_parser.add_argument("--out", help="write here instead of in place")
    match_parser.set_defaults(func=cmd_match)

    push_parser = sub.add_parser("push", help="write the devices into a hub workspace")
    push_parser.add_argument("devices", help="the file `scan`/`match` wrote")
    push_parser.add_argument("--hub", required=True)
    push_parser.add_argument("--token", required=True)
    push_parser.add_argument("--dry-run", action="store_true")
    push_parser.add_argument("--yes", action="store_true",
                             help="skip the workspace confirmation")
    push_parser.set_defaults(func=cmd_push)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except HubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
