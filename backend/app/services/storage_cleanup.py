"""Freeing room in the portability area (ARGUS_PORTABILITY_ROOT): what is there, what may go, and taking it away.

What the area holds and what is kept:

- `work/<repository>`: the local copy of the Git repository the scheduled exports are pushed to (portability
  service). Everything in it is also in that repository once pushed, so it can always be **compacted** (`git gc`:
  the objects each export wrote loose are packed together) and, when it has nothing the remote lacks, **dropped**:
  the next export clones it again.
- `bundles/imports/<id>`: workspace bundles uploaded to be imported. Once the import is done (or given up) the
  upload is not needed; ones older than a week can go.
- `bundles/exports/<id>`: workspace bundles exported to be downloaded; older than a month can go.
- `staging`, `quarantine`, `verify`, `exports`: transient files of exports and imports in progress; what is older
  than a week is left over and can go.
- the files of exports and imports that are **over** (an import finalized, discarded or invalid; an export failed,
  revoked or expired), at any age: what the retention period would delete later, done now, audited the same way
  (portability service.purge_finished); a legal hold keeps them.

Nothing else is touched: the database's own records of exports and imports, the evidence they cite (kept in the
repository) and the attachments are not in this area or are not removed here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from app.services.storage import dir_usage

WEEK = 7 * 86400
MONTH = 30 * 86400
TRANSIENT = ("staging", "quarantine", "verify", "exports")


def root() -> Path:
    return Path(os.environ.get("ARGUS_PORTABILITY_ROOT", "/data/portability"))


def _bundles() -> Path:
    return Path(os.environ.get("ARGUS_BUNDLES_DIR") or root() / "bundles")


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return dir_usage(str(p))[0] if p.is_dir() else 0


def _age(p: Path) -> float:
    try:
        return time.time() - p.stat().st_mtime
    except OSError:
        return 0.0


def _git(args: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def _repository(work: Path) -> dict:
    """A local copy of the export repository: its size, how much is loose, and whether the remote has all of it."""
    out = {"path": str(work.relative_to(root())), "bytes": _size(work), "loose_bytes": 0, "in_sync": False,
           "reason": None}
    r = _git(["count-objects", "-v"], work, timeout=60)
    if r.returncode == 0:
        stats = dict(line.split(": ", 1) for line in r.stdout.splitlines() if ": " in line)
        out["loose_bytes"] = int(stats.get("size", "0")) * 1024
    status = _git(["status", "--porcelain"], work, timeout=60)
    ahead = _git(["rev-list", "--count", "origin/main..HEAD"], work, timeout=60)
    if status.returncode != 0 or ahead.returncode != 0:
        out["reason"] = "not a repository ARGUS can read"
    elif status.stdout.strip():
        out["reason"] = "it has changes not committed"
    elif ahead.stdout.strip() not in ("", "0"):
        out["reason"] = f"{ahead.stdout.strip()} commit(s) not pushed yet"
    else:
        out["in_sync"] = True
    return out


def _old(parent: Path, older_than: float) -> list[Path]:
    return [p for p in sorted(parent.iterdir()) if _age(p) > older_than] if parent.is_dir() else []


def _finished(db):
    from app.portability import service
    cfg = service.config()
    exps, imps = service.finished(db)
    return cfg, exps, imps, service.finished_paths(cfg, exps, imps)


def preview(db=None) -> dict:
    """What the area holds, by part, and what each cleanup would free."""
    base = root()
    parts = []
    work = base / "work"
    for repo in sorted(work.iterdir()) if work.is_dir() else []:
        if (repo / ".git").exists():
            parts.append({"kind": "export_repository", **_repository(repo)})
    imports = _old(_bundles() / "imports", WEEK)
    exports = _old(_bundles() / "exports", MONTH)
    leftovers = [p for d in TRANSIENT for p in _old(base / d, WEEK)]
    actions = []
    for p in parts:
        actions.append({"id": f"compact:{p['path']}", "label": f"Compact the export repository copy ({p['path']})",
                        "frees_up_to": p["loose_bytes"], "available": p["loose_bytes"] > 0,
                        "note": "Packs the objects each export wrote loose; nothing is lost."})
        actions.append({"id": f"drop:{p['path']}", "label": f"Drop the export repository copy ({p['path']})",
                        "frees_up_to": p["bytes"], "available": p["in_sync"],
                        "note": "Everything in it is in the remote repository; the next export clones it again."
                                if p["in_sync"] else f"Kept: {p['reason']}."})
    actions.append({"id": "bundle_imports", "label": "Remove uploaded workspace bundles older than a week",
                    "frees_up_to": sum(_size(p) for p in imports), "available": bool(imports), "count": len(imports),
                    "note": "The upload is not needed once the import is done or given up."})
    actions.append({"id": "bundle_exports", "label": "Remove exported workspace bundles older than a month",
                    "frees_up_to": sum(_size(p) for p in exports), "available": bool(exports), "count": len(exports),
                    "note": "Export the workspace again to download a fresh one."})
    actions.append({"id": "leftovers", "label": "Remove left-over files of exports and imports older than a week",
                    "frees_up_to": sum(_size(p) for p in leftovers), "available": bool(leftovers),
                    "count": len(leftovers), "note": "From staging, quarantine and verification."})
    if db is not None:
        _cfg, exps, imps, paths = _finished(db)
        actions.append({"id": "finished", "label": "Remove the files of exports and imports that are over, at any age",
                        "frees_up_to": sum(_size(p) for p in paths), "available": bool(paths),
                        "count": len(exps) + len(imps),
                        "note": "Imports finalized, discarded or invalid; exports failed, revoked or expired. Their records "
                                "and audit stay; a legal hold keeps them. The retention would delete them later."})
    holds = [{"part": "work", "bytes": _size(work), "what": "local copy of the export Git repository"},
             {"part": "bundles", "bytes": _size(_bundles()), "what": "workspace bundles uploaded or exported"}]
    holds += [{"part": d, "bytes": _size(base / d), "what": "files of exports and imports in progress"}
              for d in TRANSIENT if (base / d).exists()]
    return {"root": str(base), "holds": holds, "repositories": parts, "actions": actions}


def run(action_ids: list[str], db=None, actor: str = "administrator") -> dict:
    """Do the cleanups asked for that are available now; what each freed."""
    base = root()
    current = {a["id"]: a for a in preview(db)["actions"]}
    done = []
    for aid in action_ids:
        a = current.get(aid)
        if a is None or not a["available"]:
            done.append({"id": aid, "done": False, "freed": 0, "reason": "not available now"})
            continue
        kind, _, path = aid.partition(":")
        before = _size(base)
        if kind == "compact":
            r = _git(["gc", "--prune=now", "--quiet"], base / path)
            ok = r.returncode == 0
        elif kind == "drop":
            target = (base / path).resolve()
            ok = target.parent == (base / "work").resolve()
            if ok:
                shutil.rmtree(target)
        elif kind == "bundle_imports":
            for p in _old(_bundles() / "imports", WEEK):
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            ok = True
        elif kind == "bundle_exports":
            for p in _old(_bundles() / "exports", MONTH):
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            ok = True
        elif kind == "leftovers":
            for d in TRANSIENT:
                for p in _old(base / d, WEEK):
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            ok = True
        elif kind == "finished" and db is not None:
            from app.portability import service
            cfg = service.config()
            service.purge_finished(db, cfg, actor)
            db.commit()
            ok = True
        else:
            ok = False
        done.append({"id": aid, "done": ok, "freed": max(0, before - _size(base))})
    return {"actions": done, "freed": sum(d["freed"] for d in done)}


def compact_after_publish(work: Path) -> Optional[str]:
    """Pack what an export just wrote into its repository copy, so it does not pile up loose. Never fails an export."""
    try:
        r = _git(["gc", "--prune=now", "--quiet"], work)
        return None if r.returncode == 0 else r.stderr.strip()[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)[:200]
