"""Admin script: seed the object type catalogue.

The catalogue has two sets, seeded separately.

  global    the shared types (assets, products, vendors and locations: 59 of
            them), created once in a catalogue workspace and
            flagged global, so every workspace can use them and inherit from
            them. The objects of a global type are visible in every workspace,
            and editable only in the workspace that made them.

  beamline  one machine's own types (its structure, its control and what it
            costs: 44 of them), created in that beamline's workspace, hanging from the global ones.
            Its objects stay in that workspace.

  all       everything in one workspace, for a hub that has only one.

It installs the accelerator package (backend/packages/accelerator) through the package
installer, so the workspace's record says which version it has; core-facility comes with
it when missing. Safe to run again: the version a workspace has already changes nothing;
a newer one adds what the workspace lacks (an existing type keeps every attribute it has),
a type the EPIK8s importers made is adopted rather than duplicated, and a type seeded under
a former name (Equipment Item, Place) is renamed in place. Imports no longer install it:
a workspace needs it before an EPIK8s or PBS import.

The same is on the workspace's Packages page in the web app.

Usage (from anywhere, with the backend's virtualenv and DATABASE_URL set):
  python backend/scripts/seed_asset_types.py global   <catalogue_workspace> [--dry-run]
  python backend/scripts/seed_asset_types.py beamline <workspace> --catalogue <catalogue_workspace> [--dry-run]
  python backend/scripts/seed_asset_types.py all      <workspace> [--dry-run]
  python backend/scripts/seed_asset_types.py <workspace> [--dry-run]       (same as: all)
"""
import os
import sys

# Runs from any directory: the app package is next to scripts/, not next to
# wherever the shell happens to be.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODES = ("global", "beamline", "all")


def parse(argv: list) -> tuple:
    """(mode, workspace, catalogue, dry_run), or None when the arguments do not fit."""
    dry_run = "--dry-run" in argv
    catalogue = None
    rest = []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
        elif arg == "--catalogue":
            if i + 1 >= len(argv):
                return None
            catalogue, skip = argv[i + 1], True
        elif not arg.startswith("--"):
            rest.append(arg)
    if len(rest) == 1:
        mode, workspace = "all", rest[0]            # the invocation that predates the split
    elif len(rest) == 2 and rest[0] in MODES:
        mode, workspace = rest
    else:
        return None
    if mode == "beamline" and not catalogue:
        return None
    if mode != "beamline" and catalogue:
        return None
    return mode, workspace, catalogue, dry_run


def main() -> None:
    parsed = parse(sys.argv[1:])
    if parsed is None:
        print(__doc__)
        sys.exit(1)
    mode, workspace, catalogue, dry_run = parsed
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is not set, e.g. "
              "postgresql://postgres:postgres@localhost:5432/app")
        sys.exit(1)

    from app.db import SessionLocal
    from app.models.workspace import Workspace
    from app.packages import install as installer

    db = SessionLocal()
    try:
        for name in (workspace, catalogue):
            if name and db.get(Workspace, name) is None:
                print(f"No workspace {name!r}.")
                sys.exit(1)
        run = installer.plan if dry_run else installer.install
        kwargs = {} if dry_run else {"actor": "seed_asset_types.py"}
        try:
            plan = run(db, workspace, ["accelerator"], catalogue_workspace_id=catalogue,
                       scope="global" if mode == "global" else None, **kwargs)
        except installer.PackageProblem as e:
            print(e)
            db.rollback()
            sys.exit(1)
        where = f"in {workspace!r}" + (f", hanging from {catalogue!r}" if catalogue else "")
        for step in plan.steps:
            r = step.result or {}
            if step.action == "unchanged":
                print(f"{step.package_id} {step.version}: already installed {where}, nothing to do")
                continue
            print(f"{step.package_id} {step.version}: {step.action}"
                  + (f" from {step.from_version}" if step.from_version else "")
                  + f", created {len(r.get('created') or [])}, extended {len(r.get('extended') or [])} {where}")
            for label, key in (("renamed in place", "renamed"), ("adopted (made by an importer, now under the "
                               "catalogue)", "adopted"), ("used from the catalogue, which shares them", "reused"),
                               ("already had a type of the same name that is not the catalogue's — left alone",
                                "duplicates")):
                if r.get(key):
                    print(f"  {label}: " + ", ".join(r[key]))
        if mode == "global":
            print("  Shared: its types, and so every object made from them. Documents here "
                  "are shared only once the workspace is flagged global (Administration).")
        if dry_run:
            db.rollback()
            print("dry run: nothing written.")
        else:
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
