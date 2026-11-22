"""What the integrity page calls an orphaned object — and offers to delete all at once."""
import secrets
import uuid

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.document import Document, DocumentRelation
from app.models.indoor import IndoorPlacement
from app.models.issue import Issue
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services.integrity import generate_integrity_report


def test_a_building_with_halls_in_it_or_a_record_with_a_document_or_ticket_is_not_orphaned():
    ws = f"orph-{secrets.token_hex(4)}"
    db = SessionLocal()
    try:
        db.add(Workspace(id=ws, name="Orphans"))
        db.flush()
        db.add(Schema(uid=f"{ws}:t", workspace_id=ws, name="Thing", applies_to="objects"))
        db.flush()
        for k in ("building", "hall", "pump", "gauge", "alone"):
            db.add(Asset(uid=f"{ws}-{k}", workspace_id=ws, schema_uid=f"{ws}:t", key=f"{ws}-{k}", name=k, type="Thing",
                         attributes={}))
        db.add(Document(uid=f"{ws}-doc", workspace_id=ws, code=f"{ws}-D", title="Procedure"))
        db.flush()
        db.add(IndoorPlacement(uid=str(uuid.uuid4()), workspace_id=ws, asset_uid=f"{ws}-hall", place_uid=f"{ws}-building"))
        db.add(DocumentRelation(workspace_id=ws, from_document_uid=f"{ws}-doc", to_type="asset", to_uid=f"{ws}-pump",
                                relation_type="describes"))
        db.add(Issue(uid=f"{ws}-t1", workspace_id=ws, title="Leak", state="new", asset_uid=f"{ws}-gauge"))
        db.commit()
        orphans = [o["name"] for o in generate_integrity_report(db, ws)["orphaned_objects"]]
        assert orphans == ["alone"]
    finally:
        db.close()
