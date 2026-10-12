"""python -m app.packages validate [<package dir> …] | list | show <id>

`validate` with no argument checks every package this installation ships; given directories, it checks
those (a package being written, before it is added) against the shipped ones. It exits non-zero when
anything is wrong, so CI can run it."""
import json
import sys
from pathlib import Path

from app.packages.loader import available, load
from app.packages.validate import validate


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, rest = argv[0], argv[1:]
    shipped = available()
    if command == "list":
        for p in shipped.values():
            deps = ", ".join(f"{k} {v}" for k, v in p.depends.items()) or "—"
            print(f"{p.id} {p.version}  {p.name}  (owner: {p.owner}; depends: {deps})")
        return 0
    if command == "show":
        print(json.dumps(shipped[rest[0]].describe(), indent=2))
        return 0
    if command == "validate":
        packages = [load(Path(d)) for d in rest] if rest else list(shipped.values())
        catalog = {**shipped, **{p.id: p for p in packages}}
        bad = 0
        for p in packages:
            problems = validate(p, catalog)
            if problems:
                bad += 1
                print(f"✗ {p.id} {p.version}: {len(problems)} problem(s)")
                for problem in problems:
                    print(f"    {problem.file}" + (f" › {problem.where}" if problem.where else "") + f": {problem.message}")
            else:
                counts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in p.summary().items() if v)
                print(f"✓ {p.id} {p.version} ({counts}) sha256:{p.checksum[:12]}")
        return 1 if bad else 0
    print(f"unknown command {command!r}\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
