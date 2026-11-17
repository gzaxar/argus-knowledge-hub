"""The pictures of a file being reworked into documents (a running log's plots and photographs), kept between
reading the file and saving its drafts.

Reading a PDF for rework (routers/intake.py, `/extract`) takes its pictures out (intake/files.py, pdf_figures)
and keeps each here, under the workspace, named by its content's hash; the text gets a Markdown image in its
place, linking `/v1/intake/source-images/<id>`. The preview (routers/document_templates.py) puts them in the
draft's Figures section, each under the entry it follows, with what the vision model reads in it (cached here
beside the picture, so a day previewed again is not read again). Saving a draft copies the pictures it shows
into attachments of the revision and links those instead: the draft never depends on this area.

What is here is a working copy: older than a week, it is removed when the workspace next keeps a picture.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional

WEEK = 7 * 86400
LINK = re.compile(r"/v1/intake/source-images/([0-9a-f]{32})\b")
FIGURE = re.compile(r"^!\[([^\]]*)\]\(/v1/intake/source-images/([0-9a-f]{32})\)\s*$", re.M)


def _dir(workspace_id: str) -> Path:
    root = Path(os.environ.get("ATTACHMENTS_DIR", "/data/attachments")) / "source-images"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", workspace_id)
    return root / safe


def keep(workspace_id: str, png: bytes) -> str:
    """Keep a picture for this workspace; its id."""
    d = _dir(workspace_id)
    d.mkdir(parents=True, exist_ok=True)
    _prune(d)
    pid = hashlib.sha256(png).hexdigest()[:32]
    path = d / f"{pid}.png"
    if not path.exists():
        tmp = d / f".{pid}.tmp"
        tmp.write_bytes(png)
        tmp.replace(path)
    else:
        os.utime(path)
    return pid


def path_of(workspace_id: str, pid: str) -> Optional[Path]:
    if not re.fullmatch(r"[0-9a-f]{32}", pid or ""):
        return None
    path = _dir(workspace_id) / f"{pid}.png"
    return path if path.is_file() else None


def reading(workspace_id: str, pid: str) -> Optional[str]:
    """What the vision model read in it before, if it did."""
    path = _dir(workspace_id) / f"{pid}.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def remember_reading(workspace_id: str, pid: str, text: str) -> None:
    if path_of(workspace_id, pid) is not None:
        (_dir(workspace_id) / f"{pid}.txt").write_text(text, encoding="utf-8")


def _prune(d: Path) -> None:
    now = time.time()
    for p in d.iterdir():
        try:
            if now - p.stat().st_mtime > WEEK:
                p.unlink()
        except OSError:
            pass
