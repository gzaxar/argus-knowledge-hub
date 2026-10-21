"""A document, an asset and a ticket exported as Markdown (Export ▸ Markdown, and
the text the web's print view and PDF are made from).

The case is a quadrupole power supply: a procedure about it with a body, steps
and a file, a ticket raised on it with a comment, and a restricted cost field
that must not leave the system in an export any more than on screen.
"""
import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.issue import Issue, IssueComment
from app.models.schema import Schema
from app.models.workspace import Workspace

client = TestClient(app)
NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def world():
    ws = f"mdx-{secrets.token_hex(4)}"
    t = secrets.token_hex(3)
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Export"))
    db.flush()
    db.add(Schema(uid=f"{ws}:ps", workspace_id=ws, name="Power Supply", applies_to="objects", attributes=[
        {"key": "serial", "name": "Serial number", "type": "text"},
        {"key": "mode", "name": "Mode", "type": "enumeration",
         "options": [{"id": "cc", "value": "Constant current"}]},
        {"key": "rack", "name": "Rack", "type": "reference"},
        {"key": "price", "name": "Price", "type": "float", "restricted": "costs"},
    ]))
    db.add(Schema(uid=f"{ws}:proc", workspace_id=ws, name="Procedure", applies_to="documents"))
    db.flush()
    db.add(Asset(uid=f"{ws}-rack", workspace_id=ws, schema_uid=f"{ws}:ps", key=f"RK{t}-1",
                 name="Rack A12", type="Power Supply", attributes={}))
    db.add(Asset(uid=f"{ws}-ps", workspace_id=ws, schema_uid=f"{ws}:ps", key=f"PS{t}-1",
                 name="QUAA001", type="Power Supply",
                 attributes={"serial": "SN-77", "mode": "cc", "rack": f"{ws}-rack", "price": 12000}))
    db.flush()
    db.add(Relation(workspace_id=ws, from_asset_uid=f"{ws}-ps", to_asset_uid=f"{ws}-rack",
                    relation_type="mounted in"))
    db.add(Issue(uid=f"{ws}-t1", workspace_id=ws, title="QUAA001 does not take setpoints below 5 A",
                 description="Writes are ignored | readback stays at 0.", state="new",
                 asset_uid=f"{ws}-ps", labels=["magnets"]))
    db.flush()
    db.add(IssueComment(uid=f"{ws}-c1", issue_uid=f"{ws}-t1", author="operator",
                        body="Same on QUAA002."))
    db.add(Document(uid=f"{ws}-doc", workspace_id=ws, code=f"PRC-{t}-1", title="Cycling the quadrupoles",
                    document_type_uid=f"{ws}:proc"))
    db.flush()
    for n, state in ((1, "published"), (2, "draft")):
        db.add(DocumentRevision(uid=f"{ws}-doc-r{n}", document_uid=f"{ws}-doc", revision_number=n, state=state,
                                body_markdown=f"Body of revision {n}.\n\n![plot](/v1/attachments/{ws}-plot)",
                                steps=[{"ordine": 2, "testo": "Ramp down"},
                                       {"ordine": 1, "testo": "Switch to remote", "voce_critica": True}]))
    db.flush()
    db.get(Document, f"{ws}-doc").current_revision_uid = f"{ws}-doc-r1"
    db.add(DocumentRelation(workspace_id=ws, from_document_uid=f"{ws}-doc", to_type="asset",
                            to_uid=f"{ws}-ps", relation_type="describes"))
    db.add(Attachment(uid=f"{ws}-plot", workspace_id=ws, document_revision_uid=f"{ws}-doc-r1", filename="plot.png",
                      file_size=2048, storage_path="/dev/null"))
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=ws, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    return {"ws": ws, "t": t, "headers": {"Authorization": f"Bearer {raw}"}}


def test_a_document_exports_its_current_revision(world):
    ws, t = world["ws"], world["t"]
    resp = client.get(f"/v1/documents/{ws}-doc/markdown", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    assert f'filename="PRC-{t}-1.md"' in resp.headers["content-disposition"]
    md = resp.text
    assert md.startswith(f"# PRC-{t}-1 — Cycling the quadrupoles\n")
    assert "| **Type** | Procedure |" in md
    assert "| **Revision** | 1 · published · current |" in md
    assert "Body of revision 1." in md and "revision 2" not in md
    # Steps in their order; the critical one stands out.
    assert "1. **Switch to remote**\n2. Ramp down" in md
    assert f"- PS{t}-1 — QUAA001 (describes)" in md
    # Links to files stay API paths, for the print view to fetch with the reader's token.
    assert f"- [plot.png](/v1/attachments/{ws}-plot) (2.0 KB)" in md


def test_a_document_exports_the_revision_asked_for(world):
    ws = world["ws"]
    resp = client.get(f"/v1/documents/{ws}-doc/markdown", params={"revision_uid": f"{ws}-doc-r2"},
                      headers=world["headers"])
    assert resp.status_code == 200, resp.text
    assert "| **Revision** | 2 · draft |" in resp.text and "Body of revision 2." in resp.text
    other = client.get(f"/v1/documents/{ws}-doc/markdown", params={"revision_uid": "nope"},
                       headers=world["headers"])
    assert other.status_code == 404


def test_an_asset_exports_its_fields_relations_tickets_and_documents(world):
    ws, t = world["ws"], world["t"]
    resp = client.get(f"/v1/assets/{ws}-ps/markdown", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    md = resp.text
    assert md.startswith(f"# PS{t}-1 — QUAA001\n")
    # Labels and values a reader knows, not keys, option ids and uids.
    assert "| **Serial number** | SN-77 |" in md
    assert "| **Mode** | Constant current |" in md
    assert f"| **Rack** | RK{t}-1 — Rack A12 |" in md
    assert f"- mounted in → RK{t}-1 — Rack A12" in md
    assert "QUAA001 does not take setpoints below 5 A" in md
    assert f"- PRC-{t}-1 — Cycling the quadrupoles (published)" in md
    # A restricted field is not exported to someone without the grant (I-ACL-1).
    assert "Price" not in md and "12000" not in md


def test_a_ticket_exports_its_description_equipment_and_comments(world):
    ws, t = world["ws"], world["t"]
    resp = client.get(f"/v1/issues/{ws}-t1/markdown", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    md = resp.text
    assert md.startswith("# QUAA001 does not take setpoints below 5 A\n")
    assert "| **Labels** | magnets |" in md
    assert "## Description\n\nWrites are ignored | readback stays at 0." in md
    assert f"## Equipment\n\n- PS{t}-1 — QUAA001" in md
    assert "**operator** · " in md and "Same on QUAA002." in md
    assert not md.rstrip().endswith("---")


def test_another_workspace_cannot_export(world):
    ws = world["ws"]
    db = SessionLocal()
    other = f"mdx-{secrets.token_hex(4)}"
    db.add(Workspace(id=other, name="Other"))
    raw = secrets.token_urlsafe(16)
    db.flush()
    db.add(ApiToken(workspace_id=other, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    headers = {"Authorization": f"Bearer {raw}"}
    for path in (f"/v1/documents/{ws}-doc/markdown", f"/v1/assets/{ws}-ps/markdown",
                 f"/v1/issues/{ws}-t1/markdown"):
        assert client.get(path, headers=headers).status_code == 404, path


# --- the same, as a PDF --------------------------------------------------

def _pdf_text(data: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_each_record_comes_as_a_pdf_with_its_text(world, tmp_path):
    ws, t = world["ws"], world["t"]
    # The document's picture is a real file, laid out in the PDF.
    from PIL import Image
    picture = tmp_path / "plot.png"
    Image.new("RGB", (300, 150), (200, 220, 255)).save(picture)
    db = SessionLocal()
    plot = db.get(Attachment, f"{ws}-plot")
    plot.storage_path, plot.mime_type = str(picture), "image/png"
    db.commit()
    db.close()

    resp = client.get(f"/v1/documents/{ws}-doc/pdf", headers=world["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert f'filename="PRC-{t}-1.pdf"' in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    text = _pdf_text(resp.content)
    assert "Cycling the quadrupoles" in text and "Body of revision 1." in text
    assert "/v1/attachments" not in text
    from io import BytesIO

    from pypdf import PdfReader
    assert any(page.images for page in PdfReader(BytesIO(resp.content)).pages), "the picture is in it"

    asset = client.get(f"/v1/assets/{ws}-ps/pdf", headers=world["headers"])
    assert asset.status_code == 200 and "QUAA001" in _pdf_text(asset.content)
    assert "12000" not in _pdf_text(asset.content), "a restricted field stays out of the PDF too"
    ticket = client.get(f"/v1/issues/{ws}-t1/pdf", headers=world["headers"])
    assert ticket.status_code == 200 and "Same on QUAA002." in _pdf_text(ticket.content)


def test_a_picture_from_elsewhere_is_not_fetched():
    """Imported text can point anywhere; the server does not call out to draw it."""
    from app.services import pdf_export
    data = pdf_export.render("Text\n\n![diagram](http://169.254.169.254/latest/x.png)\n", "T", [])
    assert "[picture: diagram]" in _pdf_text(data)


def test_another_workspace_cannot_get_the_pdf(world):
    db = SessionLocal()
    other = f"mdx-{secrets.token_hex(4)}"
    db.add(Workspace(id=other, name="Other"))
    raw = secrets.token_urlsafe(16)
    db.flush()
    db.add(ApiToken(workspace_id=other, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    ws = world["ws"]
    for path in (f"/v1/documents/{ws}-doc/pdf", f"/v1/assets/{ws}-ps/pdf", f"/v1/issues/{ws}-t1/pdf"):
        assert client.get(path, headers={"Authorization": f"Bearer {raw}"}).status_code == 404, path
