"""Admin script: read an EPIK8s control configuration into a workspace.

Reads a beamline's deploy/values.yaml from disk and writes what it describes as
objects of the catalogue's types, each linked to what the file says it is tied to:

  Facility                the beamline
  Control Configuration   this file at this revision; everything below is declared in it
  IOC Template            the recipe an IOC is deployed from
  IOC                     the deployable unit, on its networks, from its template
  Control Device          the channel, axis or gauge that actually fails
  Access Point            the terminal server or address a device is reached through
  Control Network         a network an IOC is attached to
  Control Service         archiver, gateways, alarm server, logbook
  Storage Mount           an NFS mount or backup target
  Serial Line             one serial port of a converter, with the devices on it

Access Points are found in the inventory by address before any is made, so a Moxa
that is already an object is linked, not duplicated; --no-create-missing reports
the addresses nothing carries instead of making an object for each.

--infer-elements also makes what the channels are for, which the file never lists: the
ion pump behind GUNSIP01, the quadrupole and its power supply behind QUATB002, the
camera, a BPM's electronics, an LLRF chassis, a modulator. They are read from the
device metadata (devgroup, devfunc, devtype, template) and, for magnets, from the LNF
name code; a channel neither says anything about is counted and reported, not guessed
at. Each is marked `inferred` and says why, keeps anything a person adds to it, and
needs the catalogue's types (the accelerator package, installed first).

Each Access Point says what kind of endpoint it is (a serial converter, a host, an
instrument, a camera), read from the class prefix of INFN's DNS naming convention and, for
a bare IP, from a port in Moxa's 4001-4999 range, with the evidence beside it. Each device
on a port of a converter is `on line` a Serial Line that is `port of` the converter's
Access Point.

--it-workspace <workspace> also makes the IT equipment the hostnames name, in that
site-wide workspace: the converter behind a `sc…` host, a server behind `pl…`, a console
behind `pw…co…`, flagged global and keyed by the fully qualified name, so two beamlines
that reach one host share one object. Each Access Point is `implemented by` it.

With --infer-elements, --infer-controllers also makes the controller box each IOC talks to
(an IPCMini, a TPG 366, a Pollux chain), powering what its channels drive; and
--link-inventory links a channel to the unit the inventory already holds (by tag or
address) instead of inferring a twin, as a proposal to confirm under Channels ↔ hardware.
Asking the AI about unrecognised channels is in the web import only.

The workspace must have the accelerator catalogue first (the workspace's Packages page, or
scripts/seed_asset_types.py): an import does not install it, and stops saying so. Run it again after the file changes: it updates what the file says and
leaves what has been added since.

Usage (from anywhere, with the backend's virtualenv and DATABASE_URL set):
  python backend/scripts/import_epik8s.py <workspace_id> <values.yaml>
      [--catalogue <catalogue_workspace>] [--no-create-missing] [--infer-elements [--infer-controllers] [--link-inventory]] [--it-workspace <workspace>] [--dry-run]
"""
import os
import sys

# Runs from any directory: the app package is next to scripts/, not next to
# wherever the shell happens to be.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse(argv: list) -> tuple:
    """(workspace, path, catalogue, create_missing, dry_run, infer, it_workspace), or None."""
    def option(name):
        return argv[argv.index(name) + 1] if name in argv[:-1] else None

    catalogue, it_workspace = option("--catalogue"), option("--it-workspace")
    for name, value in (("--catalogue", catalogue), ("--it-workspace", it_workspace)):
        if name in argv and value is None:
            return None
    rest = [a for i, a in enumerate(argv)
            if not a.startswith("--") and not (i and argv[i - 1] in ("--catalogue", "--it-workspace"))]
    if len(rest) != 2:
        return None
    return (rest[0], rest[1], catalogue, "--no-create-missing" not in argv, "--dry-run" in argv,
            "--infer-elements" in argv, it_workspace)


def main() -> None:
    parsed = parse(sys.argv[1:])
    if parsed is None:
        print(__doc__)
        sys.exit(1)
    workspace_id, path, catalogue, create_missing, dry_run, infer, it_workspace = parsed
    if not os.path.exists(path):
        print(f"No such file: {path}")
        sys.exit(1)
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set, e.g. "
              "postgresql://postgres:postgres@localhost:5432/app")
        sys.exit(1)

    import secrets

    import yaml
    from sqlalchemy.orm import Session

    from app.db import SessionLocal, engine
    from app.models.import_job import ImportJob
    from app.models.workspace import Workspace
    from app.services.epik8s_import import _Importer
    from app.services.relations import rebuild_asset_relations

    values = yaml.safe_load(open(path))
    if not isinstance(values, dict):
        print(f"{path} did not parse as a mapping: is that the right file?")
        sys.exit(1)
    from app.services.epik8s_import import base_values_path, with_base
    base_path = base_values_path(path.replace(os.sep, "/"), values)
    if base_path:
        # An overlay (values-linac.yaml): the beamline and its templates' defaults are in values.yaml beside it.
        base = yaml.safe_load(open(base_path)) if os.path.exists(base_path) else None
        if not isinstance(base, dict) or not str(base.get("beamline") or "").strip():
            print(f"{path} names no beamline, and {base_path} beside it does not either (or is missing).")
            sys.exit(1)
        print(f"{path} names no beamline: using {base_path} for the beamline and its templates' defaults")
        values = with_base(values, base)

    if dry_run:
        # The importer commits as it goes, so a rollback at the end would undo
        # nothing. Run inside an outer transaction whose commits are savepoints,
        # and throw the whole thing away: a real run that leaves no trace.
        connection = engine.connect()
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
    else:
        connection = outer = None
        db = SessionLocal()
    try:
        for name in (workspace_id, catalogue, it_workspace):
            if name and db.get(Workspace, name) is None:
                print(f"No workspace {name!r}.")
                sys.exit(1)
        # The accelerator catalogue first, explicitly: an import does not install it.
        from app.packages.requirements import require
        from app.services.epik8s_import import REQUIRES
        try:
            require(db, workspace_id, *REQUIRES)
        except ValueError as e:
            print(f"{e}\n(or: python backend/scripts/seed_asset_types.py beamline {workspace_id} "
                  f"--catalogue <catalogue>)")
            sys.exit(1)

        job = ImportJob(uid=f"job-{secrets.token_hex(6)}", workspace_id=workspace_id,
                        source="epik8s")
        db.add(job)
        db.commit()
        link = infer and "--link-inventory" in sys.argv
        importer = _Importer(db, job, workspace_id, path, infer_elements=infer, it_workspace=it_workspace,
                             infer_controllers=infer and "--infer-controllers" in sys.argv, link_inventory=link)
        try:
            importer.ensure_types()
            importer.run(values, create_missing)
        except ValueError as e:                 # a key that belongs to another workspace, or no catalogue
            db.rollback()
            print(e)
            sys.exit(1)
        for asset in importer.assets.values():
            rebuild_asset_relations(db, asset.uid)
        db.commit()
        if link and not dry_run:
            from app.ledger import control_binding
            importer.counts["inventory_link_proposals"] = control_binding.propose(db, workspace_id)["proposed"]
            db.commit()

        beamline = str(values.get("beamline") or "").strip() or "unknown"
        print(f"read {path}: beamline {beamline}")
        for name, n in sorted(importer.counts.items()):
            if n:
                print(f"  {name:24s} {n}")
        if infer and importer.not_inferred:
            left = sum(importer.not_inferred.values())
            print(f"  not inferred: {left} channel(s) no rule covers, by group/template:")
            for kind, n in importer.not_inferred.most_common(8):
                print(f"    {n:4d}  {kind}")
        warnings = list(job.warnings or [])
        if warnings:
            print(f"{len(warnings)} warning(s):")
            for w in warnings[:40]:
                print("  - " + w)
            if len(warnings) > 40:
                print(f"  … and {len(warnings) - 40} more")
        if dry_run:
            print("dry run: nothing written.")
    finally:
        db.close()
        if outer is not None:
            outer.rollback()
            connection.close()


if __name__ == "__main__":
    main()
