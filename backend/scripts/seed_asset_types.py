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

Safe to run again: an existing type keeps every attribute it has and gains any it
lacks, a type the EPIK8s importers made is adopted rather than duplicated, and a
type seeded under a former name (Equipment Item, Place) is renamed in place. Run
it before or after an import; the result is the same.

Nothing here runs when a workspace is created: a workspace that only holds
tickets has no use for object types in its tree.

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
    from app.services.asset_types import ensure_asset_types

    db = SessionLocal()
    try:
        for name in (workspace, catalogue):
            if name and db.get(Workspace, name) is None:
                print(f"No workspace {name!r}.")
                sys.exit(1)
        try:
            result = ensure_asset_types(db, workspace, scope=mode, catalogue_workspace_id=catalogue)
            from app.packages.install import note_seeded
            note_seeded(db, workspace, "accelerator", how="seeded", actor="seed_asset_types.py",
                        options={"scope": mode, **({"catalogue_workspace_id": catalogue} if catalogue else {})})
        except ValueError as e:                    # includes CatalogueMissing
            print(e)
            db.rollback()
            sys.exit(1)
        where = f"in {workspace!r}" + (f", hanging from {catalogue!r}" if catalogue else "")
        print(f"{mode}: created {len(result.created)}, adopted {len(result.adopted)}, "
              f"renamed {len(result.renamed)}, extended {len(result.extended)} {where}")
        if result.iconed:
            print(f"  default icons given to {len(result.iconed)} types that had none")
        if result.renamed:
            print("  renamed in place: " + ", ".join(result.renamed))
        if result.reused:
            print(f"  used from the catalogue, which shares them ({len(result.reused)}): "
                  + ", ".join(result.reused))
        if result.adopted:
            print("  adopted (made by an importer, now under the catalogue): "
                  + ", ".join(result.adopted))
        if result.duplicates:
            print("  already had a type of the same name that is not the catalogue's — "
                  "left alone, and now there are two: " + ", ".join(result.duplicates))
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
