"""Workspace bundles from the command line (docs/workspace-bundle.md):

    python -m app.bundle export <workspace> <directory> [--demo demo.json]
    python -m app.bundle zip <directory> <file.zip>
    python -m app.bundle preview <directory|file.zip> --workspace <new id> --name <name> [--people]
    python -m app.bundle import <directory|file.zip> --workspace <new id> --name <name> [--people] [--actor e-mail]

A preview runs the import and rolls it back. Exit status 0 when it is (or would be) imported, 1 when not.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from app.bundle import core


def _open(path: str) -> tuple[core.Bundle, object]:
    p = Path(path)
    if p.is_file() and p.suffix == ".zip":
        tmp = tempfile.TemporaryDirectory()
        core.unpack(p, Path(tmp.name))
        return core.read(Path(tmp.name)), tmp
    return core.read(p), None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.bundle")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("workspace")
    e.add_argument("directory")
    e.add_argument("--demo", help="a JSON file: the demo's title, description and tour")
    e.add_argument("--actor", default="command line")
    z = sub.add_parser("zip")
    z.add_argument("directory")
    z.add_argument("file")
    for name in ("preview", "import"):
        i = sub.add_parser(name)
        i.add_argument("bundle")
        i.add_argument("--workspace", required=True)
        i.add_argument("--name", required=True)
        i.add_argument("--people", action="store_true", help="apply memberships, role bindings and subscriptions")
        i.add_argument("--actor", default=None)
    a = ap.parse_args(argv)
    from app.db import SessionLocal
    if a.cmd == "zip":
        print(core.zip_dir(Path(a.directory), Path(a.file)))
        return 0
    db = SessionLocal()
    try:
        if a.cmd == "export":
            demo = json.loads(Path(a.demo).read_text()) if a.demo else None
            m = core.export(db, a.workspace, Path(a.directory), actor=a.actor, demo=demo)
            print(json.dumps({k: m[k] for k in ("workspace", "packages", "not_reproduced", "missing_files")}, indent=1))
            return 0
        b, _tmp = _open(a.bundle)
        rep = core.apply(db, b, workspace_id=a.workspace, name=a.name, actor=a.actor, people_access=a.people,
                         dry_run=a.cmd == "preview")
        view = rep.view()
        if a.cmd == "import" and view["ok"]:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(view, indent=1, default=str))
        return 0 if view["ok"] else 1
    except core.BundleError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
