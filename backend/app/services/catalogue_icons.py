"""Default icons for the catalogue's types.

Every type gets a picture: its own where the map below names one, else its
nearest ancestor's (an Ion Pump shows the pump of Vacuum Pump). Most are Tabler
Icons (MIT, `app/catalogue_icons/tabler/`); four that Tabler has no fitting
symbol for are drawn for ARGUS in the same style (`app/catalogue_icons/argus/`):
a dipole magnet, a quadrupole, a vacuum cross and a valve.

Seeding installs them in the seeded workspace's icon library, shared like the
types, and sets a type's icon only where it has none: a picture somebody chose,
or one an import brought, stays. Seeding again fills gaps and nothing else.
"""
from __future__ import annotations

import os
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.icon import Icon
from app.models.schema import Schema

ICON_DIR = Path(__file__).resolve().parents[1] / "catalogue_icons"

# A package preview runs seeding and rolls it back: it must not leave icon files behind (packages/install).
PREVIEW: ContextVar[bool] = ContextVar("catalogue_icons_preview", default=False)
PREFIX = "argus-"

def _icons() -> tuple[dict, dict, dict]:
    """The default icons, as the packages give them: each object, ticket and document type its own."""
    from app.packages import defaults
    objects = {t.name: t.icon for t in defaults.object_types() if t.icon}
    out = []
    for kinds in (defaults.ticket_types(), defaults.document_types()):
        icons = {kinds.base_name: kinds.base_icon} if kinds.base_icon else {}
        icons.update({name: icon for name, _, icon in kinds.kinds if icon})
        out.append(icons)
    return objects, out[0], out[1]


# A type an import adds (a Jira "Incident") takes its base type's icon.
ICONS, TICKET_ICONS, DOCUMENT_ICONS = _icons()


def ticket_icon(name: str) -> Optional[str]:
    return TICKET_ICONS.get(name, TICKET_ICONS["Ticket"])


def document_icon(name: str) -> Optional[str]:
    return DOCUMENT_ICONS.get(name, DOCUMENT_ICONS["Document"])


def icon_for(name: str) -> Optional[str]:
    """The type's icon, or its nearest ancestor's."""
    from app.services.asset_types import BY_NAME
    cur: Optional[str] = name
    while cur is not None:
        if cur in ICONS:
            return ICONS[cur]
        cur = BY_NAME[cur].parent if cur in BY_NAME else None
    return None


def _attachments_dir() -> str:
    return os.environ.get("ATTACHMENTS_DIR", "/data/attachments")


def _library_icon(db: Session, workspace_id: str, icon: str, share: bool) -> Icon:
    """The catalogue icon in this workspace's library, installed on first use. Its file is a copy in the
    attachment store, as an uploaded icon's is (deleting an icon deletes its file)."""
    source = ICON_DIR / f"{icon}.svg"
    filename = f"{PREFIX}{icon.split('/')[-1]}.svg"
    row = db.scalar(select(Icon).where(Icon.workspace_id == workspace_id, Icon.filename == filename).limit(1))
    content = source.read_bytes()
    if row is None:
        uid = str(uuid.uuid4())
        row = Icon(uid=uid, workspace_id=workspace_id, filename=filename, mime_type="image/svg+xml",
                   name=icon.split("/")[-1].replace("-", " ").capitalize(), file_size=len(content),
                   storage_path=os.path.join(_attachments_dir(), uid), is_global=share)
        db.add(row)
    elif share and not row.is_global:
        row.is_global = True
    # A fresh install, a wiped store, or a release that redrew the icon: the catalogue's own files follow it.
    current = open(row.storage_path, "rb").read() if os.path.exists(row.storage_path) else None
    if current != content and not PREVIEW.get():
        os.makedirs(os.path.dirname(row.storage_path), exist_ok=True)
        with open(row.storage_path, "wb") as f:
            f.write(content)
        row.file_size = len(content)
    return row


def apply(db: Session, workspace_id: str, uids: dict[str, str], share: bool, icon_of=None) -> list[str]:
    """Give each of the workspace's own types its default icon where it has none (`icon_of`: the object
    catalogue's by default, or ticket_icon / document_icon). Returns the names of the types that got one."""
    icon_for_type = icon_of or icon_for
    given = []
    cache: dict[str, Icon] = {}
    for name, uid in uids.items():
        schema = db.get(Schema, uid)
        if schema is None or schema.workspace_id != workspace_id:
            continue
        if schema.icon_uid:
            # Not this type's to fill; but if it shows one of the catalogue's own icons, keep that file current.
            icon_row = db.get(Icon, schema.icon_uid)
            default = icon_for_type(name)
            if icon_row is not None and default and icon_row.filename == f"{PREFIX}{default.split('/')[-1]}.svg" \
                    and icon_row.workspace_id == workspace_id and default not in cache:
                cache[default] = _library_icon(db, workspace_id, default, bool(icon_row.is_global))
            continue
        icon = icon_for_type(name)
        if icon is None or not (ICON_DIR / f"{icon}.svg").exists():
            continue
        if icon not in cache:
            cache[icon] = _library_icon(db, workspace_id, icon, share or bool(schema.is_global))
            db.flush()
        if (share or schema.is_global) and not cache[icon].is_global:
            cache[icon].is_global = True                         # a shared type's icon is seen wherever the type is
        schema.icon_uid = cache[icon].uid
        given.append(name)
    db.flush()
    return given
