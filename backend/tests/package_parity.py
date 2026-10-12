"""What seeding writes, recorded so a change in how it is defined (Python, then YAML packages) can be shown to
write exactly the same: every type, enumeration and icon a workspace gets, in each of the ways a workspace is
seeded. Workspace ids are replaced by placeholders, so two runs compare."""
import json
import secrets
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models.global_value import GlobalValue
from app.models.icon import Icon
from app.models.schema import Schema
from app.models.workspace import Workspace

FIXTURES = Path(__file__).parent / "fixtures" / "package_parity"


def _abstract(value, names: dict):
    text = json.dumps(value, sort_keys=True, default=str)
    for real, placeholder in sorted(names.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(real, placeholder)
    return json.loads(text)


def _dump(db, workspaces: dict) -> dict:
    out = {}
    for placeholder, ws in workspaces.items():
        schemas = []
        for s in db.scalars(select(Schema).where(Schema.workspace_id == ws).order_by(Schema.uid)):
            icon = db.get(Icon, s.icon_uid) if s.icon_uid else None
            schemas.append({"uid": s.uid, "name": s.name, "description": s.description, "applies_to": s.applies_to,
                            "is_concrete": s.is_concrete, "is_global": s.is_global,
                            "parent": s.parent_schema_uid, "attributes": s.attributes,
                            "metadata": s.metadata_json, "icon": icon.name if icon else None})
        values = []
        for g in db.scalars(select(GlobalValue).where(GlobalValue.workspace_id == ws)
                            .order_by(GlobalValue.applies_to, GlobalValue.key)):
            values.append({"key": g.key, "name": g.name, "type": g.type, "applies_to": g.applies_to,
                           "options": g.options, "default_value": g.default_value,
                           "is_system_default": g.is_system_default})
        out[placeholder] = {"schemas": schemas, "global_values": values}
    return _abstract(out, {ws: placeholder for placeholder, ws in workspaces.items()})


def seed_every_way(seed) -> dict:
    """`seed` is a callable(db, kind, workspace_id, catalogue_id) doing what each way of seeding does today
    (or, later, by installing packages): kind is core | accelerator | catalogue | beamline."""
    t = secrets.token_hex(3)
    ws = {"{core}": f"parity-core-{t}", "{accelerator}": f"parity-acc-{t}", "{catalogue}": f"parity-cat-{t}",
          "{beamline}": f"parity-bl-{t}"}
    db = SessionLocal()
    try:
        for w in ws.values():
            db.add(Workspace(id=w, name=w))
        db.flush()
        seed(db, "core", ws["{core}"], None)
        seed(db, "accelerator", ws["{accelerator}"], None)
        seed(db, "catalogue", ws["{catalogue}"], None)
        seed(db, "beamline", ws["{beamline}"], ws["{catalogue}"])
        db.flush()
        return _dump(db, ws)
    finally:
        db.rollback()
        db.close()


def todays_seeding(db, kind, workspace_id, catalogue_id):
    """How each kind of workspace is seeded before packages."""
    from app.routers.workspaces import seed_default_global_values, seed_default_ticket_types
    from app.services import asset_types
    from app.services.document_types import ensure_document_types
    seed_default_global_values(db, workspace_id)
    seed_default_ticket_types(db, workspace_id)
    ensure_document_types(db, workspace_id)
    if kind == "accelerator":
        asset_types.ensure_asset_types(db, workspace_id, scope=asset_types.SCOPE_ALL)
    elif kind == "catalogue":
        asset_types.ensure_asset_types(db, workspace_id, scope=asset_types.SCOPE_GLOBAL)
    elif kind == "beamline":
        asset_types.ensure_asset_types(db, workspace_id, scope=asset_types.SCOPE_BEAMLINE,
                                       catalogue_workspace_id=catalogue_id)


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "seeding.json").write_text(json.dumps(seed_every_way(todays_seeding), indent=1, sort_keys=True))
    print("recorded", FIXTURES / "seeding.json")
