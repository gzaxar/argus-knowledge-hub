"""A workspace to look at the beam model with (docs/beam-model.md).

Seeds the catalogue's types into the workspace, imports the three canonical fixtures (a DAΦNE-accumulator-like
ring with an extraction line, an electron linac, a laser transport that branches to a camera), and adds
illustrative hardware behind a few positions so the element panel has something to show:

* QUAA101: a magnet installed since 2024, swapped for a spare in March 2026; its power supply, the control
  device acting on the supply, its IOC, and setpoint/readback/status signal identities;
* BPM01: a stripline pickup connected to its electronics, the device and IOC, X and Y signals;
* CAM01: the camera installed at the laser line's diagnostic leg, and its profile signal.

It also imports the argus.beam-model/2 fixtures (a ring with vacuum components, a girder and apertures, a
branched transfer line, an aperture example, a collider interaction region) and adds the ring's mock
physical assets (`ring_assets.json`), so Beam model → *assets* has something to synchronise.

The hardware is made up for the demo (names say so); the fixtures are not any machine's real lattice.

    python backend/scripts/beam_model_demo.py <workspace> [--activate-policy]

A model from a new source waits for governance (`awaiting_policy`); `--activate-policy` activates the
current authority policy so it takes effect — a governance step, meant for a demo or development hub.
"""
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "beam_model"
ACTOR = "beam-model-demo"


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        sys.exit(2)
    ws = argv[0]
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.ledger import engine, service
    from app.models.asset import Asset
    from app.models.schema import Schema
    from app.models.workspace import Workspace
    from app.services import beam_model as bm

    db = SessionLocal()
    if db.get(Workspace, ws) is None:
        print(f"no workspace {ws}: tools/argus-admin workspace create {ws} first")
        sys.exit(1)
    from app.packages.install import install
    plan = install(db, ws, ["accelerator"], actor="beam_model_demo.py")
    db.commit()
    print("packages: " + ", ".join(f"{s.package_id} {s.version} {s.action}" for s in plan.steps))
    awaiting = False
    for name in ("dafne_accumulator.json", "linac.json", "laser_transport.json", "ring.beam.json",
                 "transfer.beam.json", "aperture.beam.json", "collider_ir.beam.json"):
        r = bm.import_canonical(db, ws, json.loads((FIXTURES / name).read_text()), ACTOR)
        db.commit()
        awaiting |= r["awaiting_policy"]
        print(f"{r['model']}: {r['state']}, {r['elements']} elements, {r['values']} values"
              + (" — waiting for the policy to cover this source" if r["awaiting_policy"] else ""))
    if awaiting and "--activate-policy" in argv:
        engine.activate_policy(db, None, ACTOR)
        db.commit()
        print("policy activated: the imported claims take effect")
    elif awaiting:
        print("run again with --activate-policy (or activate it from Ledger → Policy) to accept the imports")
        return

    types = {s.name: s.uid for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}

    def position(model_name: str) -> Asset:
        """A position of the original three models (the v2 ring has names of its own model)."""
        keys = [f"{ws}:{m}/{model_name}" for m in ("dafne-accumulator", "linac-demo", "laser-transport")]
        return db.scalar(select(Asset).where(Asset.key.in_(keys)))

    def record(type_name: str, key: str, name: str, **attrs) -> str:
        existing = db.scalar(select(Asset).where(Asset.key == f"{ws}:demo/{key}"))
        if existing is not None:
            return existing.uid
        uid = str(uuid.uuid4())
        service.create_record(db, ws, ACTOR, uid=uid, schema_uid=types[type_name], key=f"{ws}:demo/{key}", name=name,
                              type_name=type_name, attributes={"description": "Demo hardware for the beam model.",
                                                               **attrs})
        return uid

    def relate(a: str, rel: str, b: str) -> None:
        service.relate(db, ws, ACTOR, a, rel, b)

    def install(pos: Asset, unit: str, since: str) -> None:
        if engine.installations(db, position_uid=pos.uid):
            return
        inst = service.new_installation_claims(db, ws, ACTOR, pos.uid, unit,
                                               {"kind": "date", "nominal": since, "precision": "day"})
        service.confirm_installation(db, ws, ACTOR, inst)

    # QUAA101: magnet, swapped; supply, device, IOC, signals.
    quad = position("QUAA101")
    old = record("Magnet Assembly", "MAG-Q-0001", "QUAA101 magnet (demo)", serial="Q-0001", manufacturer="Danfysik")
    spare = record("Magnet Assembly", "MAG-Q-0007", "Spare quadrupole Q-0007 (demo)", serial="Q-0007",
                   manufacturer="Danfysik")
    ps = record("Power Supply", "PS-QUAA101", "PS-QUAA101 (demo)", serial="PS-3321", manufacturer="OCEM")
    dev = record("Control Device", "DEV-QUAA101", "QUAA101", pv="DAFNE:ACC:QUAA101")
    ioc = record("IOC", "IOC-ACC-MAG", "ioc-acc-magnets (demo)")
    relate(ps, "powers", quad.uid)
    relate(dev, "acts on", ps)
    relate(dev, "provided by", ioc)
    if not engine.installations(db, position_uid=quad.uid):
        install(quad, old, "2024-03-01T00:00:00+00:00")
        service.swap(db, ws, ACTOR, quad.uid, spare, {"kind": "date", "nominal": "2026-03-01T00:00:00+00:00",
                                                      "precision": "day"}, reason="Failure")
    for suffix, role, unit in (("CURRENT:SP", "setpoint", "A"), ("CURRENT:RB", "readback", "A"),
                               ("STATUS", "status", None)):
        bm.ensure_signal(db, ws, ACTOR, name=f"QUAA101 {suffix.lower().replace(':', ' ')}",
                         address=f"DAFNE:ACC:QUAA101:{suffix}", role=role, device_uid=dev, for_uid=quad.uid,
                         quantity="current" if "CURRENT" in suffix else "status", unit=unit)
    db.commit()

    # BPM01 (linac): pickup → electronics, device, IOC, X/Y.
    bpm = position("BPM01")
    pickup = record("Other Equipment", "PICKUP-BPM01", "Stripline pickup SP-7 (demo)", serial="SP-7")
    libera = record("Digitizer", "LIBERA-03", "Libera Single Pass 03 (demo)", serial="LSP-03")
    bdev = record("Control Device", "DEV-BPM01", "BPM01", pv="LINAC:BPM01")
    bioc = record("IOC", "IOC-LINAC-BPM", "ioc-linac-bpm (demo)")
    install(bpm, pickup, "2025-01-15T00:00:00+00:00")
    relate(pickup, "connected to", libera)
    relate(bdev, "acts on", libera)
    relate(bdev, "provided by", bioc)
    for plane in ("x", "y"):
        bm.ensure_signal(db, ws, ACTOR, name=f"BPM01 {plane.upper()}", address=f"LINAC:BPM01:{plane.upper()}",
                         role="measurement", device_uid=bdev, for_uid=bpm.uid, measures=f"beam.position.{plane}",
                         unit="mm")
    db.commit()

    # CAM01 (laser): the camera, and its profile signal.
    cam = position("CAM01")
    camera = record("Camera", "CAM-LASER-01", "Basler acA1300 leak camera (demo)", serial="BAS-2219")
    cdev = record("Control Device", "DEV-CAM01", "CAM01", pv="LASER:CAM01")
    install(cam, camera, "2025-06-01T00:00:00+00:00")
    relate(cdev, "acts on", camera)
    bm.ensure_signal(db, ws, ACTOR, name="CAM01 image", address="LASER:CAM01:image1:ArrayData", role="measurement",
                     device_uid=cdev, for_uid=cam.uid, measures="optical.profile")
    db.commit()
    print("demo hardware: QUAA101 (magnet swapped 2026-03-01), BPM01 (pickup, electronics, X/Y), CAM01 (camera)")

    # The v2 ring's physical assets, as a facility's asset register might name them.
    fx = json.loads((FIXTURES / "ring_assets.json").read_text())
    made = {}
    for a in fx["assets"]:
        attrs = {**a.get("attributes", {}), **({"aliases": a["aliases"]} if a.get("aliases") else {})}
        made[a["id"]] = record(a["type"], f"v2-{a['id']}", f"{a['name']}", **attrs)
    relate(made["a-pu-bpsa101"], "connected to", made["a-el-bpsa101"])
    for comp, asset in (("CHHA101", "a-cor-h-01"), ("KCKA101", "a-kck-old")):
        pos = db.scalar(select(Asset).where(Asset.key == f"{ws}:dafne-accumulator-v2/{comp}"))
        if pos is not None:
            install(pos, made[asset], "2025-01-01T00:00:00+00:00")
    db.commit()
    print(f"v2 ring assets: {len(made)} (open Beam model → dafne-accumulator-v2 → assets)")


if __name__ == "__main__":
    main(sys.argv[1:])
