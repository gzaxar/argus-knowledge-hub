"""The IOC catalogue from the command line.

    python -m app.ioc_engineer build --repo PATH [--sources DIR] [--beamline URL[@REF]|PATH ...] [--out FILE]
        read a checkout of infn-epics-ioc (git submodule update --init first) into the catalogue;
        --sources also clones each INFN driver's repository (organization + module from its
        install.yml) into DIR and indexes its db templates, protocols and README.
        --beamline (repeatable) reads a beamline repository's deploy value files (iocDefaults, IOC entries)
        so its IOCs can be listed, rendered and checked as deployed.
        --out defaults to the bundled snapshot, app/ioc_engineer/data/catalog.json.gz
    python -m app.ioc_engineer summary [--catalog FILE]
        what a catalogue holds, and what it found wrong while reading
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.ioc_engineer import catalog


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ioc_engineer")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repo", required=True, type=Path, help="a checkout of infn-epics-ioc with its submodules")
    b.add_argument("--sources", type=Path, help="clone and index the drivers' own repositories here")
    b.add_argument("--beamline", action="append", default=[],
                   help="a beamline repository (git URL, optionally @ref, or a path); repeatable")
    b.add_argument("--out", type=Path, default=catalog.BUNDLED)
    s = sub.add_parser("summary")
    s.add_argument("--catalog", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        built = catalog.build(args.repo, sources=args.sources, beamlines=tuple(args.beamline))
        catalog.write(built, args.out)
        cat = built
        print(f"wrote {args.out}")
    else:
        if args.catalog:
            os.environ["ARGUS_IOC_CATALOG"] = str(args.catalog)
        cat = catalog.load()
    with_source = [m for m in cat["modules"] if m.get("source")]
    print(json.dumps({
        "repository": cat.get("repository"),
        "modules": len(cat["modules"]),
        "in_image": sum(1 for m in cat["modules"] if m["built"]["in_image"]),
        "entity_models": len(cat["entity_models"]),
        "templates": len(cat["templates"]),
        "examples": len(cat["examples"]),
        "beamlines": {b["name"]: len(b.get("iocs", [])) for b in cat.get("beamlines", [])},
        "sources": {"indexed": sum(1 for m in with_source if not m["source"].get("error")),
                    "failed": {m["folder"]: m["source"]["error"] for m in with_source if m["source"].get("error")}},
        "problems": cat.get("problems", []),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
