"""Apply a rack layout file to a workspace that already exists (app/services/rack_layout.py).

Run it inside the API container; the demos carry theirs (scripts/demo_rack_layouts/<demo>.json):

    PYTHONPATH=/app python scripts/apply_rack_layout.py <workspace id> <layout.json> [--dry-run]

Only what differs changes; nothing is deleted. With --dry-run nothing is written and the report says what would be.
"""
import json
import sys
from pathlib import Path

from app.db import SessionLocal
from app.services import rack_layout


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    workspace, path = args
    dry = "--dry-run" in argv
    db = SessionLocal()
    try:
        report = rack_layout.apply(db, workspace, json.loads(Path(path).read_text()), actor="rack layout",
                                   dry_run=dry)
        if dry or report["refused"]:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    for line in report["changed"]:
        print(("would change  " if dry else "changed  ") + line)
    print(f"unchanged: {report['unchanged']} · plan points moved into racks: {report['points_moved']}")
    for m in report["missing"]:
        print(f"not found in {workspace}: {m}")
    for r in report["refused"]:
        print(f"refused, rack {r['rack']}: " + "; ".join(p["message"] for p in r["problems"]))
    return 1 if report["refused"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
