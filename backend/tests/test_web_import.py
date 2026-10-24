"""A web page saved as a folder (an HTML file and its pictures) imported as documents, one per page: the page as
Markdown, its pictures attached and shown in place, its HTML kept as the original, links between pages pointing
at their documents, and nothing outside the folder ever read."""
import io
import json
import secrets
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.membership import Membership
from app.models.user import User
from app.models.workspace import Workspace
from app.services import web_import as wi
from app.services.document_types import ensure_document_types

client = TestClient(app)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40

INDEX = b"""<HTML><HEAD><TITLE>PPT.vi</TITLE><script>alert('x')</script><style>p{}</style></HEAD>
<BODY><H2>PPT.vi</H2>
<P><IMG SRC="PPTc.png" ALT="connector"></P>
<Table><TR valign=TOP><TD><P><IMG SRC="cbool.png" ALT="cbool"></P></TD><TD><B>stop</B> </TD></TR></Table>
<UL><Table><TR><TD><IMG SRC="cbool.png" ALT="cbool"></TD><TD><B>ON</B></TD></TR></Table></UL>
<table><tr><th>Signal</th><th>Unit</th></tr><tr><td>HV</td><td>kV</td></tr></table>
<p>See <a href="sub/details.html">the details</a>, <a href="https://example.org/x">the site</a>,
<a href="manual.pdf">the manual</a> and <a href="../outside.html">nothing</a>.</p>
<img src="../secret.png" alt="outside"><img src="http://tracker.example/p.png" alt="remote">
<ol><li>First<ul><li>inner</li></ul></li><li>Second</li></ol>
<pre>line 1
  line 2</pre>
<form><input name=pw></form>
</BODY></HTML>"""
DETAILS = b"<html><head><title>Details</title></head><body><h1>Details</h1><p>Back to <a href='../PPT.html'>main</a>." \
          b"<img src='../PPTp.png' alt='panel'></p></body></html>"


def folder_uploads():
    return [("PPTDOC/PPT.html", INDEX), ("PPTDOC/sub/details.html", DETAILS), ("PPTDOC/PPTc.png", PNG),
            ("PPTDOC/PPTp.png", PNG), ("PPTDOC/cbool.png", PNG), ("PPTDOC/manual.pdf", b"%PDF-1.4"),
            ("PPTDOC/notes.txt", b"unused"), ("PPTDOC/.DS_Store", b"x"), ("../evil.html", b"<p>evil</p>")]


def test_a_page_becomes_markdown_with_its_pictures_and_nothing_from_outside_the_folder():
    files = wi.folder_from(folder_uploads())
    assert set(files) == {"PPT.html", "sub/details.html", "PPTc.png", "PPTp.png", "cbool.png", "manual.pdf",
                          "notes.txt"}                       # the folder's name dropped; ../ and .DS_Store left out
    main, details = wi.pages_of(files)
    assert (main.path, main.title, details.title) == ("PPT.html", "PPT.vi", "Details")
    md = main.markdown
    assert md.startswith("## PPT.vi")
    assert "![connector](file:PPTc.png)" in md and "![cbool](file:cbool.png) **stop**" in md
    assert main.pictures == ["PPTc.png", "cbool.png"]       # each picture once, however often shown
    assert "| Signal | Unit |\n|---|---|\n| HV | kV |" in md
    assert "[the details](page:sub/details.html)" in md and "[the site](https://example.org/x)" in md
    assert "the manual" in md and main.files_linked == ["manual.pdf"]
    assert "alert" not in md and "p{}" not in md and "secret" not in md and "tracker" not in md
    assert "1. First\n  - inner\n2. Second" in md
    assert "```\nline 1\n  line 2\n```" in md
    assert details.pictures == ["PPTp.png"] and details.pages_linked == ["PPT.html"]
    assert wi.unused_files(files, [main, details]) == ["manual.pdf", "notes.txt"]


def test_a_zip_is_the_same_folder_and_a_folder_without_a_page_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in folder_uploads()[:5]:
            z.writestr(name, content)
        z.writestr("__MACOSX/PPTDOC/._PPT.html", b"x")
    files = wi.folder_from([("PPTDOC.zip", buf.getvalue())])
    assert set(files) == {"PPT.html", "sub/details.html", "PPTc.png", "PPTp.png", "cbool.png"}
    with pytest.raises(wi.WebImportError, match="no web page"):
        wi.folder_from([("x/a.png", PNG)])


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    ws = f"web-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="Linac"))
    db.flush()
    types = ensure_document_types(db, ws)
    writer = User(id=str(uuid.uuid4()), email=f"writer-{t}@argus.test", name="writer", is_admin=False)
    reader = User(id=str(uuid.uuid4()), email=f"reader-{t}@argus.test", name="reader", is_admin=False)
    db.add_all([writer, reader])
    db.flush()
    db.add(Membership(workspace_id=ws, user_id=writer.id, can_read=True, can_read_documents=True,
                      can_create_documents=True, can_modify_documents=True))
    db.add(Membership(workspace_id=ws, user_id=reader.id, can_read=True, can_read_documents=True))
    db.commit()
    for u in (writer, reader):
        db.refresh(u)
        db.expunge(u)
    db.close()
    yield {"ws": ws, "types": types, "writer": writer, "reader": reader, "h": {"X-Workspace-Id": ws}}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    for u in (writer, reader):
        db.delete(db.get(User, u.id))
    db.commit()
    db.close()


def as_(person):
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=person)


def _files():
    return [("files", (name, content, "application/octet-stream")) for name, content in folder_uploads()]


def test_the_preview_lists_the_pages_and_keeps_nothing(world):
    as_(world["writer"])
    r = client.post("/v1/documents/import-web/preview", headers=world["h"], files=_files())
    assert r.status_code == 200, r.text
    out = r.json()
    assert [p["title"] for p in out["pages"]] == ["PPT.vi", "Details"]
    assert out["pages"][0]["pictures"] == 2 and out["unused"] == ["manual.pdf", "notes.txt"]
    db = SessionLocal()
    assert db.scalar(select(Document).where(Document.workspace_id == world["ws"])) is None
    db.close()


def test_each_page_is_a_document_with_its_pictures_its_original_and_links_between_them(world):
    as_(world["writer"])
    r = client.post("/v1/documents/import-web", headers=world["h"], files=_files(),
                    data={"document_type_uid": world["types"]["Manual"], "confidentiality": "interno"})
    assert r.status_code == 201, r.text
    made = {d["path"]: d for d in r.json()["documents"]}
    assert set(made) == {"PPT.html", "sub/details.html"}
    main_uid, details_uid = made["PPT.html"]["uid"], made["sub/details.html"]["uid"]
    db = SessionLocal()
    try:
        main = db.get(Document, main_uid)
        assert (main.title, main.document_type_uid) == ("PPT.vi", world["types"]["Manual"])
        rev = db.get(DocumentRevision, f"{main_uid}-r1")
        files = {a.filename: a for a in db.scalars(select(Attachment).where(Attachment.document_revision_uid == rev.uid))}
        # Its pictures, its own HTML, the PDF it links to, and what no page used: nothing given is lost.
        assert set(files) == {"PPTc.png", "cbool.png", "PPT.html", "manual.pdf", "notes.txt"}
        assert files["PPTc.png"].mime_type == "image/png"
        assert f"![connector](/v1/attachments/{files['PPTc.png'].uid})" in rev.body_markdown
        assert f"[the details](/documents/{details_uid})" in rev.body_markdown
        assert "file:" not in rev.body_markdown and "page:" not in rev.body_markdown
        drev = db.get(DocumentRevision, f"{details_uid}-r1")
        dfiles = {a.filename for a in db.scalars(select(Attachment).where(Attachment.document_revision_uid == drev.uid))}
        assert dfiles == {"PPTp.png", "sub/details.html"}
        assert f"[main](/documents/{main_uid})" in drev.body_markdown
        assert rev.state == "draft"
    finally:
        db.close()


def test_only_the_pages_chosen_are_imported_and_a_reader_may_not_import(world):
    as_(world["writer"])
    r = client.post("/v1/documents/import-web", headers=world["h"], files=_files(),
                    data={"pages": json.dumps(["sub/details.html"])})
    assert r.status_code == 201, r.text
    [only] = r.json()["documents"]
    db = SessionLocal()
    try:
        rev = db.get(DocumentRevision, f"{only['uid']}-r1")
        names = {a.filename for a in db.scalars(select(Attachment).where(Attachment.document_revision_uid == rev.uid))}
        assert "PPT.html" in names                      # the page not imported is kept with the one that was
        assert "[main](" not in rev.body_markdown and "main" in rev.body_markdown
        assert db.scalar(select(DocumentRelation).where(DocumentRelation.from_document_uid == only["uid"])) is None
    finally:
        db.close()
    as_(world["reader"])
    assert client.post("/v1/documents/import-web", headers=world["h"], files=_files()).status_code == 403


def test_the_assistant_suggests_each_pages_type_summary_and_keywords_from_its_text(world, monkeypatch):
    from app.models.llm_config import LLMConfig
    db = SessionLocal()
    db.add(LLMConfig(workspace_id=world["ws"], base_url="https://gateway.example/v1", model="m-1", enabled=True,
                     last_check_ok=True))
    db.commit()
    db.close()
    seen = []

    def complete(endpoint, system, user, max_tokens=512):
        seen.append(user)
        return json.dumps({"title": "Pulsed power tube control panel", "type": "Manual",
                           "summary": "The control panel of the PPT: heaters, HVPS and interlocks.",
                           "keywords": ["PPT", "HVPS"]})
    monkeypatch.setattr("app.services.llm.complete_structured", complete)
    as_(world["writer"])
    r = client.post("/v1/documents/import-web", headers=world["h"], files=_files(),
                    data={"pages": json.dumps(["PPT.html"]), "suggest": "true"})
    assert r.status_code == 201, r.text
    [doc] = r.json()["documents"]
    assert set(doc["suggested"]) >= {"document_type_uid", "summary", "attributes.argus_keywords"}
    assert "[picture: connector]" in seen[0] and "file:" not in seen[0]   # pictures named to it, not sent
    db = SessionLocal()
    try:
        d = db.get(Document, doc["uid"])
        assert d.title == "PPT.vi"                         # the page's own title is kept
        assert d.document_type_uid == world["types"]["Manual"]
        rev = db.get(DocumentRevision, f"{doc['uid']}-r1")
        assert rev.attributes["argus_summary"].startswith("The control panel")
        assert rev.attributes["argus_keywords"] == ["PPT", "HVPS"]
    finally:
        db.close()
    # Without a working assistant, asking for suggestions says so rather than importing half.
    db = SessionLocal()
    db.get(LLMConfig, world["ws"]).enabled = False
    db.commit()
    db.close()
    r = client.post("/v1/documents/import-web", headers=world["h"], files=_files(), data={"suggest": "true"})
    assert r.status_code == 409


def test_a_file_kept_as_it_is_becomes_markdown_with_its_structure():
    from app.intake import files
    from app.intake import markdown as md
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    xml = (f'<w:document {w}><w:body>'
           '<w:p><w:pPr><w:pStyle w:val="Titolo1"/></w:pPr><w:r><w:t>Procedura</w:t></w:r></w:p>'
           '<w:p><w:r><w:t xml:space="preserve">Chiudere la </w:t></w:r><w:r><w:rPr><w:b/></w:rPr>'
           '<w:t>valvola V1</w:t></w:r></w:p>'
           '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>primo</w:t></w:r></w:p>'
           '<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/></w:numPr></w:pPr><w:r><w:t>dettaglio</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Segnale</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Unità</w:t></w:r>'
           '</w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>HV</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>kV</w:t>'
           '</w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    assert files.extract_document(buf.getvalue(), "p.docx", None)["text"] == (
        "# Procedura\n\nChiudere la **valvola V1**\n\n- primo\n  - dettaglio\n\n| Segnale | Unità |\n|---|---|\n| HV | kV |")
    pdf_text = ("PROPERTY IRREGULARITY REPORT\n\nThe bag was found damaged at the arri-\nval belt and the passenger "
                "was in-\nformed.\n• Handle broken\n• Wheel missing\n\nSigned\nMario Rossi")
    assert md.text_to_markdown(pdf_text, wrapped=True) == (
        "## PROPERTY IRREGULARITY REPORT\n\nThe bag was found damaged at the arrival belt and the passenger was "
        "informed.\n\n- Handle broken\n- Wheel missing\n\nSigned  \nMario Rossi")
    page = files.extract_document(b"<html><body><h1>Note</h1><ul><li>a</li><li>b</li></ul><img src='x.png' alt='plot'>"
                                  b"</body></html>", "note.html", "text/html")
    assert page["format"] == "html" and page["text"] == "# Note\n\n- a\n- b\n\nplot"
    mail = (b"From: someone@example.org\nSubject: Chiller alarm\nDate: Fri, 25 Sep 2026 08:00:00 +0000\n\n"
            b"It rang twice.\n\n- at 08:00\n- at 09:00")
    text = files.extract_document(mail, "a.eml", None)["text"]
    assert text.startswith("**Subject:** Chiller alarm  \n**Date:**") and "- at 08:00\n- at 09:00" in text
    assert "someone@example.org" not in text
    assert md.csv_markdown("a;b\n1;2\n") == "| a | b |\n|---|---|\n| 1 | 2 |"
