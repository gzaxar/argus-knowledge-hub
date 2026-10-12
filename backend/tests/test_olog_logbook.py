"""A facility's Olog entries reach ARGUS as Logbook Entry documents (tools/olog-to-argus)."""
import importlib.util
import json
import pathlib
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.packages.install import install
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.asset import Asset
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services.olog_logbook import entry_uid

client = TestClient(app)
TOOL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "olog-to-argus" / "olog_to_argus.py"
if not TOOL.exists():                                   # the repository layout, outside the container
    TOOL = pathlib.Path(__file__).resolve().parents[2] / "tools" / "olog-to-argus" / "olog_to_argus.py"


def _tool():
    spec = importlib.util.spec_from_file_location("olog_to_argus", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


def ms(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def entry(i, title, text, created, modified=None, attachments=()):
    return {"id": i, "owner": "operator", "title": title, "source": text, "description": text, "level": "Info",
            "createdDate": ms(created), "modifyDate": ms(modified or created),
            "logbooks": [{"name": "Operations"}], "tags": [{"name": "RF"}],
            "properties": [{"name": "Shift", "attributes": [{"name": "Crew", "value": "A"}]}],
            "attachments": [{"id": f"att-{i}-{n}", "filename": n, "fileMetadataDescription": "text/plain"}
                            for n in attachments]}


@pytest.fixture()
def facility():
    """A workspace with a magnet, and its logbook robot token."""
    t = secrets.token_hex(4)
    ws = f"olog-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="BTF"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.flush()
    db.add(Schema(uid=f"{ws}:magnet", workspace_id=ws, name="Magnet", applies_to="objects"))
    db.flush()
    db.add(Asset(uid=f"{ws}-q1", workspace_id=ws, schema_uid=f"{ws}:magnet", key=f"BTF{t[:3].upper()}-17",
                 name=f"QUATB{t}01", type="Magnet"))
    raw = f"argus_bot_{secrets.token_urlsafe(16)}"
    db.add(ApiToken(kind="robot", workspace_id=ws, token_hash=hash_token(raw), label="Olog BTF",
                    scopes=["read", "create", "modify"], resources=["documents"]))
    db.commit()
    db.close()
    return {"ws": ws, "token": raw, "magnet": f"QUATB{t}01", "magnet_uid": f"{ws}-q1"}


class FakeOlog(BaseHTTPRequestHandler):
    entries: list = []
    files: dict = {}
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        FakeOlog.seen.append(self.path)
        if url.path == "/Olog/logs/search":
            q = parse_qs(url.query)
            start, size = int(q["from"][0]), int(q["size"][0])
            page = FakeOlog.entries[start:start + size]
            body = json.dumps({"logs": page, "hitCount": len(FakeOlog.entries)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif url.path.startswith("/Olog/logs/attachments/"):
            name = url.path.rsplit("/", 1)[-1]
            if name not in FakeOlog.files:
                self.send_response(404)
                self.end_headers()
                return
            body = FakeOlog.files[name]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def olog():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOlog)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeOlog.entries, FakeOlog.files, FakeOlog.seen = [], {}, []
    yield f"http://127.0.0.1:{server.server_address[1]}/Olog"
    server.shutdown()


class ArgusThroughTestClient:
    """The tool's ARGUS side, sending through the application in-process."""

    def __init__(self, tool, token):
        self.real = tool.Argus("http://argus", token)
        self.token = token

    def send(self, facility, entries, entry_url):
        r = client.post("/v1/logbook/olog/entries", headers={"Authorization": f"Bearer {self.token}"},
                        json={"facility": facility, "entry_url": entry_url, "entries": entries})
        assert r.status_code == 200, r.text
        return r.json()

    def attach(self, facility, entry_id, attachment_id, filename, content, content_type, source_url):
        r = client.post(f"/v1/logbook/olog/entries/{facility}/{entry_id}/attachments",
                        headers={"Authorization": f"Bearer {self.token}"},
                        data={"attachment_id": attachment_id, "source_url": source_url},
                        files={"file": (filename, content, content_type)})
        assert r.status_code == 201, r.text


def test_a_days_entries_arrive_with_their_files_and_the_equipment_they_name(facility, olog):
    tool = _tool()
    FakeOlog.entries = [entry(i, f"Shift note {i}", f"Routine {i}.", "2026-10-04T08:00:00") for i in range(1, 251)]
    FakeOlog.entries.append(entry(900, "RF trip", f"The klystron tripped; {facility['magnet']} cycled.",
                                  "2026-10-04T09:40:00", attachments=["scope.txt"]))
    FakeOlog.files = {"scope.txt": b"trace"}
    argus = ArgusThroughTestClient(tool, facility["token"])
    totals = tool.run(tool.Olog(olog), argus, "btf", "2 days", "https://btf-webolog.example/logs/{id}",
                      batch_size=100)
    assert totals == {"created": 251, "updated": 0, "unchanged": 0, "rejected": 0, "files": 1, "failures": 0}
    # Paged through Olog, from the start of the window.
    searches = [s for s in FakeOlog.seen if s.startswith("/Olog/logs/search")]
    assert len(searches) == 2 and "start=2+days" in searches[0]

    db = SessionLocal()
    doc = db.get(Document, entry_uid(facility["ws"], "btf", 900))
    rev = db.get(DocumentRevision, doc.current_revision_uid)
    assert doc.code.startswith("OLOG-BTF-900")       # suffixed when another workspace already has the code
    assert doc.title == "RF trip" and doc.source == "olog" and rev.state == "published"
    assert doc.document_type_uid.endswith("logbook-entry")
    assert "**Logbooks:** Operations" in rev.body_markdown and "[Open in Olog](https://btf-webolog.example/logs/900)" in rev.body_markdown
    assert rev.attributes["olog_tags"] == ["RF"] and rev.attributes["olog_properties"] == {"Shift": {"Crew": "A"}}
    assert db.scalar(select(Attachment.filename).where(Attachment.document_revision_uid == rev.uid)) == "scope.txt"
    assert db.scalar(select(DocumentRelation.to_uid).where(DocumentRelation.from_document_uid == doc.uid)) == \
        facility["magnet_uid"]
    db.close()


def test_running_again_changes_nothing_and_an_edited_entry_becomes_a_revision(facility, olog):
    tool = _tool()
    FakeOlog.entries = [entry(1, "Beam on", "Beam on at 08:12.", "2026-10-04T08:12:00", attachments=["log.txt"]),
                        entry(2, "Vacuum", "Sector 3 at 1e-8.", "2026-10-04T10:00:00")]
    FakeOlog.files = {"log.txt": b"08:12 beam on"}
    argus = ArgusThroughTestClient(tool, facility["token"])
    tool.run(tool.Olog(olog), argus, "btf", "2 days")
    again = tool.run(tool.Olog(olog), argus, "btf", "2 days")
    assert again["unchanged"] == 2 and again["created"] == again["files"] == 0

    FakeOlog.entries[0] = entry(1, "Beam on", "Beam on at 08:15 (corrected).", "2026-10-04T08:12:00",
                                modified="2026-10-05T07:00:00", attachments=["log.txt"])
    edited = tool.run(tool.Olog(olog), argus, "btf", "2 days")
    assert edited["updated"] == 1 and edited["unchanged"] == 1 and edited["files"] == 0
    db = SessionLocal()
    doc = db.get(Document, entry_uid(facility["ws"], "btf", 1))
    revs = db.scalars(select(DocumentRevision).where(DocumentRevision.document_uid == doc.uid)
                      .order_by(DocumentRevision.revision_number)).all()
    assert [r.state for r in revs] == ["superseded", "published"] and "corrected" in revs[1].body_markdown
    # The file follows the entry to its new revision, not copied twice.
    assert db.scalar(select(Attachment.filename).where(Attachment.document_revision_uid == revs[1].uid)) == "log.txt"
    db.close()


def test_a_token_without_the_logbook_scopes_is_refused(facility):
    db = SessionLocal()
    raw = f"argus_bot_{secrets.token_urlsafe(16)}"
    db.add(ApiToken(kind="robot", workspace_id=facility["ws"], token_hash=hash_token(raw), label="reader",
                    scopes=["read"]))
    db.commit()
    db.close()
    r = client.post("/v1/logbook/olog/entries", headers={"Authorization": f"Bearer {raw}"},
                    json={"facility": "btf", "entries": [entry(5, "x", "y", "2026-10-04T08:00:00")]})
    assert r.status_code == 403


def test_a_file_before_its_entry_is_refused(facility):
    r = client.post("/v1/logbook/olog/entries/btf/77/attachments",
                    headers={"Authorization": f"Bearer {facility['token']}"},
                    data={"attachment_id": "a"}, files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 404


def test_the_tool_says_what_is_missing_and_fails_when_argus_refuses(facility, olog, capsys):
    tool = _tool()
    with pytest.raises(SystemExit):
        tool.main(["--olog-url", olog])
    FakeOlog.entries = [entry(1, "x", "y", "2026-10-04T08:00:00")]
    status = tool.main(["--olog-url", olog, "--argus-url", "http://127.0.0.1:9", "--argus-token", "t",
                        "--facility", "btf"])
    assert status == 1 and "error:" in capsys.readouterr().err



def test_the_images_in_an_entry_show_where_the_author_put_them(facility, olog):
    """Olog writes ![](attachment/<file id>){width=…}: once the file is here, the text points at the copy."""
    tool = _tool()
    text = "Scope trace:\n\n![](attachment/att-7-trace.png){width=842 height=1052}\n\nand a missing one ![](attachment/gone)"
    FakeOlog.entries = [entry(7, "Trace", text, "2026-10-04T11:00:00", attachments=["trace.png"])]
    FakeOlog.files = {"trace.png": b"\x89PNG fake"}
    tool.run(tool.Olog(olog), ArgusThroughTestClient(tool, facility["token"]), "btf", "2 days")
    db = SessionLocal()
    doc = db.get(Document, entry_uid(facility["ws"], "btf", 7))
    body = db.get(DocumentRevision, doc.current_revision_uid).body_markdown
    att = db.scalar(select(Attachment.uid).where(Attachment.document_revision_uid == doc.current_revision_uid))
    assert f"![](/v1/attachments/{att})" in body and "{width=" not in body.split("missing")[0]
    assert "](attachment/gone)" in body                      # a file never received stays as Olog wrote it
    db.close()
    # Edited in Olog: the new revision points at the same copy.
    FakeOlog.entries = [entry(7, "Trace", text + " (seen again)", "2026-10-04T11:00:00",
                              modified="2026-10-05T08:00:00", attachments=["trace.png"])]
    tool.run(tool.Olog(olog), ArgusThroughTestClient(tool, facility["token"]), "btf", "2 days")
    db = SessionLocal()
    doc = db.get(Document, entry_uid(facility["ws"], "btf", 7))
    assert f"](/v1/attachments/{att})" in db.get(DocumentRevision, doc.current_revision_uid).body_markdown
    db.close()


def test_entries_imported_before_get_their_image_links_on_upgrade(facility, monkeypatch):
    """The migration points the old references (the first import, before links were rewritten) at the files."""
    import importlib.util as iu
    path = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "f1a3c5e7b9d2_olog_image_links.py"
    spec = iu.spec_from_file_location("olog_image_links", path)
    migration = iu.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db = SessionLocal()
    uid = f"olog-old-{secrets.token_hex(3)}"
    db.add(Document(uid=uid, workspace_id=facility["ws"], code=uid.upper(), title="Old", source="olog"))
    db.flush()
    db.add(DocumentRevision(uid=f"{uid}-r1", document_uid=uid, revision_number=1, state="published",
                            body_markdown="Before ![](attachment/abc-1){width=10 height=20} after",
                            attributes={"argus_source": "olog"}))
    db.flush()
    db.add(Attachment(uid=f"{uid}-a", workspace_id=facility["ws"], document_revision_uid=f"{uid}-r1",
                      filename="abc-1.png", storage_path="/dev/null", backend_id="olog:btf:5:abc-1"))
    db.commit()
    with engine.begin() as conn:
        monkeypatch.setattr(migration.op, "get_bind", lambda: conn, raising=False)
        migration.upgrade()
    db.expire_all()
    assert db.get(DocumentRevision, f"{uid}-r1").body_markdown == f"Before ![](/v1/attachments/{uid}-a) after"
    db.close()
