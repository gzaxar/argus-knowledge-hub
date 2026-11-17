"""The test files of one CI shard: the suite split in N parts of about the same time, so N runners can run it in
parallel, each with its own database (.github/workflows/tests.yml).

    python tests/shard.py 2 4        # the files of shard 2 of 4, one per line

The time of each file comes from tests/durations.json (seconds, from a full run: `python tests/shard.py --record
junit.xml` writes it from pytest's --junitxml report). A file not in it yet counts as the median file. Files are
given out longest first, each to the shard with the least time so far: the same files always make the same shards.
"""
from __future__ import annotations

import json
import statistics
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
DURATIONS = HERE / "durations.json"


def test_files() -> list[str]:
    return sorted(f"tests/{p.name}" for p in HERE.glob("test_*.py"))


def durations() -> dict[str, float]:
    try:
        return json.loads(DURATIONS.read_text())
    except (OSError, ValueError):
        return {}


def shards(n: int, files: list[str] | None = None, times: dict[str, float] | None = None) -> list[list[str]]:
    files = test_files() if files is None else files
    times = durations() if times is None else times
    known = [times[f] for f in files if f in times]
    default = statistics.median(known) if known else 1.0
    cost = {f: times.get(f, default) for f in files}
    out: list[list[str]] = [[] for _ in range(n)]
    load = [0.0] * n
    for f in sorted(files, key=lambda f: (-cost[f], f)):
        i = min(range(n), key=lambda i: (load[i], i))
        out[i].append(f)
        load[i] += cost[f]
    return [sorted(s) for s in out]


def record(junit: Path) -> dict[str, float]:
    """Seconds per test file, from a --junitxml report."""
    out: dict[str, float] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        module = (case.get("classname") or "").split(".")
        if len(module) >= 2 and module[0] == "tests":
            f = f"tests/{module[1]}.py"
            out[f] = round(out.get(f, 0.0) + float(case.get("time") or 0), 1)
    return dict(sorted(out.items()))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--record"]:
        DURATIONS.write_text(json.dumps(record(Path(sys.argv[2])), indent=1) + "\n")
    else:
        k, n = int(sys.argv[1]), int(sys.argv[2])
        if not 1 <= k <= n:
            sys.exit(f"shard {k} of {n}: k must be 1..n")
        print("\n".join(shards(n)[k - 1]))
