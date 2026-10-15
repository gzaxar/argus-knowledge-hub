"""Confluence pages as documents.

The conversion is the part worth testing hard: Confluence stores pages in
its own XHTML dialect, and anything the converter drops silently is
content nobody will notice is missing until they need it.
"""
import json
import re
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from app.packages.install import install
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.import_job import ImportJob
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services.confluence_import import (
    PageLinkError,
    choose_document_type,
    parse_page_link,
    run_confluence_import,
    storage_to_markdown,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _attachments_dir(tmp_path_factory, monkeypatch):
    """Imported files land on disk; keep them out of the real volume."""
    directory = tmp_path_factory.mktemp("conf-attachments")
    monkeypatch.setattr(
        "app.services.confluence_import.ATTACHMENTS_DIR", str(directory)
    )


def test_headings_lists_and_links_become_markdown():
    markdown = storage_to_markdown(
        "<h1>Vacuum recovery</h1>"
        "<p>Follow <strong>exactly</strong>.</p>"
        "<ol><li>Close the gate valve</li><li>Start the pump</li></ol>"
        '<p>See <a href="https://wiki.invalid/x">the manual</a>.</p>'
    )
    assert "# Vacuum recovery" in markdown
    assert "**exactly**" in markdown
    assert "1. Close the gate valve" in markdown
    assert "[the manual](https://wiki.invalid/x)" in markdown


def test_tables_survive():
    """A procedure's parameters are usually a table; losing it loses the
    part people actually came for."""
    markdown = storage_to_markdown(
        "<table><tbody>"
        "<tr><th>Parameter</th><th>Value</th></tr>"
        "<tr><td>Pressure</td><td>1e-9 mbar</td></tr>"
        "</tbody></table>"
    )
    assert "Parameter" in markdown and "1e-9 mbar" in markdown
    assert "|" in markdown, "should be a markdown table, not flattened prose"


def test_code_macro_keeps_its_content_and_language():
    markdown = storage_to_markdown(
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[caget BTF:PRESSURE]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert "caget BTF:PRESSURE" in markdown
    # The language belongs on the fence — it is what makes the block
    # readable and highlightable downstream.
    assert "```python" in markdown


def test_warning_panel_is_not_silently_dropped():
    """A safety warning that vanishes in conversion is the worst possible
    thing for this converter to do."""
    markdown = storage_to_markdown(
        '<ac:structured-macro ac:name="warning">'
        "<ac:rich-text-body><p>Interlock must be armed.</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    assert "Interlock must be armed." in markdown
    assert ">" in markdown, "a panel should read as a blockquote"


def test_unconvertible_macro_says_so_rather_than_leaving_a_hole():
    markdown = storage_to_markdown(
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">LNF-1</ac:parameter>'
        "</ac:structured-macro>"
    )
    assert "jira" in markdown.lower()
    assert "original" in markdown.lower()


def test_images_point_at_the_copied_file():
    """An image the reader cannot open is not an imported image. Once the
    file has been copied in, the body has to point at that copy."""
    markdown = storage_to_markdown(
        '<ac:image><ri:attachment ri:filename="layout.png" /></ac:image>',
        {"layout.png": "/v1/attachments/abc-123"},
    )
    assert "![layout.png](/v1/attachments/abc-123)" in markdown


def test_attachment_link_points_at_the_copied_file():
    markdown = storage_to_markdown(
        '<ac:link><ri:attachment ri:filename="wiring.pdf" /></ac:link>',
        {"wiring.pdf": "/v1/attachments/def-456"},
    )
    assert "[wiring.pdf](/v1/attachments/def-456)" in markdown


def test_page_and_attachment_links_keep_their_names():
    markdown = storage_to_markdown(
        '<ac:link><ri:page ri:content-title="Beam interlock" /></ac:link>'
        '<ac:link><ri:attachment ri:filename="layout.pdf" /></ac:link>'
    )
    assert "Beam interlock" in markdown
    assert "layout.pdf" in markdown


def test_two_links_in_a_row_both_survive():
    """A converter whose match reaches across tags eats everything between
    the first link and the second — the first link vanishes and the two
    paragraphs merge into one sentence that was never written."""
    markdown = storage_to_markdown(
        '<p>The drawing is attached: '
        '<ac:link><ri:attachment ri:filename="chamber.pdf" /></ac:link></p>'
        '<p>See also <ac:link><ri:page ri:content-title="Beam interlock" /></ac:link>.</p>',
        {"chamber.pdf": "/v1/attachments/xyz"},
    )
    assert "[chamber.pdf](/v1/attachments/xyz)" in markdown
    assert "Beam interlock" in markdown
    # Two paragraphs, still two.
    assert "attached:" in markdown and "See also" in markdown
    assert "\n\n" in markdown


def test_a_panel_wrapping_a_code_block_keeps_the_code():
    """Runbooks routinely put the command to run inside a warning panel.
    Matching the outer macro up to the inner macro's closing tag threw the
    command away and left the panel empty."""
    markdown = storage_to_markdown(
        '<ac:structured-macro ac:name="warning"><ac:rich-text-body>'
        "<p>Only with the interlock armed:</p>"
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">bash</ac:parameter>'
        "<ac:plain-text-body><![CDATA[caput BTF:VAC:VALVE:CMD 0]]></ac:plain-text-body>"
        "</ac:structured-macro>"
        "</ac:rich-text-body></ac:structured-macro>"
    )
    assert "caput BTF:VAC:VALVE:CMD 0" in markdown
    assert "Only with the interlock armed:" in markdown


def test_no_raw_confluence_markup_survives():
    """Whatever isn't understood must not reach the reader as tags."""
    markdown = storage_to_markdown(
        '<p>Before</p><ac:structured-macro ac:name="toc" /><ri:user ri:userkey="abc" />'
        "<p>After</p>"
    )
    assert "ac:" not in markdown and "ri:" not in markdown
    assert "Before" in markdown and "After" in markdown


def test_document_type_comes_from_labels_then_title():
    assert choose_document_type(["procedure"], "Anything") == "Procedure"
    assert choose_document_type(["sicurezza"], "Anything") == "Safety Document"
    assert choose_document_type([], "Runbook: vacuum loss") == "Runbook"
    assert choose_document_type([], "Verbale riunione") == "Meeting Minutes"
    # Unrecognised becomes a Note rather than being forced somewhere wrong.
    assert choose_document_type(["random"], "Something else") == "Note"


PAGES = [
    {
        "id": "101",
        "title": "Vacuum recovery procedure",
        "space": {"key": "LNF"},
        "version": {"number": 3, "when": "2026-09-01T10:00:00.000Z",
                    "by": {"displayName": "Marco Rossi"}},
        "metadata": {"labels": {"results": [{"name": "procedure"}]}},
        "body": {"storage": {"value": "<h1>Recovery</h1><p>Camera LNFT2-145356 first.</p>"}},
    },
    {
        "id": "102",
        "title": "Shift report 2026-09-02",
        "space": {"key": "LNF"},
        "version": {"number": 1, "when": "2026-09-02T18:00:00.000Z",
                    "by": {"displayName": "Giulia Bianchi"}},
        "metadata": {"labels": {"results": [{"name": "logbook"}]}},
        "body": {"storage": {"value": "<p>Quiet shift.</p>"}},
    },
]


ATTACHMENTS: dict[str, list] = {}
FILES: dict[str, bytes] = {}
# Page ids whose attachment listing should fail, so the unhappy path gets
# exercised — a wiki will always have a file the importer cannot fetch.
BROKEN_LISTINGS: set = set()
# Short links the stub's /x/ answers with a redirect, as Confluence does.
SHORT_LINKS: dict[str, str] = {}

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _ConfluenceStub(BaseHTTPRequestHandler):
    pages = PAGES
    blogposts: list = []

    def log_message(self, *a):
        pass

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _binary(self, payload: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        start = int(query.get("start", ["0"])[0])

        if parsed.path == "/rest/api/space":
            self._json({"results": [{"key": "LNF"}]})
        elif parsed.path == "/rest/api/content":
            # Confluence Server's own shape: `size` counts the results in
            # THIS response — there is no total here — and another page is
            # advertised by a `next` link. A stub that invents a `totalSize`
            # hides the pagination bug this endpoint is prone to.
            rows = self.blogposts if query.get("type") == ["blogpost"] else self.pages
            if query.get("title"):
                rows = [p for p in rows if p["title"] == query["title"][0]]
            window = rows[start:start + 50]
            body = {"results": window, "size": len(window), "start": start, "limit": 50,
                    "_links": {"base": f"http://127.0.0.1:{self.server.server_port}"}}
            if start + len(window) < len(rows):
                body["_links"]["next"] = f"/rest/api/content?start={start + len(window)}"
            self._json(body)
        elif parsed.path == "/rest/api/content/search":
            rows = self.pages
            one = re.fullmatch(r"id = (\d+)( or ancestor = \1)?", query.get("cql", [""])[0])
            if one:
                root, under = one.group(1), bool(one.group(2))
                rows = [p for p in rows if p["id"] == root or (
                    under and root in [a["id"] for a in p.get("ancestors") or []])]
            window = rows[start:start + 50]
            self._json({"results": window, "size": len(window),
                        "totalSize": len(rows)})
        elif re.fullmatch(r"/rest/api/content/\d+", parsed.path):
            found = [p for p in self.pages if p["id"] == parsed.path.rsplit("/", 1)[1]]
            if not found:
                self.send_response(404)
                self.end_headers()
                return
            self._json(found[0])
        elif parsed.path.startswith("/x/") and parsed.path[3:] in SHORT_LINKS:
            self.send_response(302)
            self.send_header("Location", f"/pages/viewpage.action?pageId={SHORT_LINKS[parsed.path[3:]]}")
            self.end_headers()
        elif parsed.path.endswith("/child/attachment"):
            page_id = parsed.path.split("/")[-3]
            if page_id in BROKEN_LISTINGS:
                self.send_response(500)
                self.end_headers()
                return
            results = ATTACHMENTS.get(page_id, [])
            self._json({"results": results, "size": len(results),
                        "_links": {"base": f"http://127.0.0.1:{self.server.server_port}"}})
        elif parsed.path.startswith("/download/"):
            payload = FILES.get(parsed.path)
            if payload is None:
                self.send_response(404)
                self.end_headers()
                return
            self._binary(payload)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def confluence_stub():
    server = HTTPServer(("127.0.0.1", 0), _ConfluenceStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    _ConfluenceStub.pages = PAGES
    _ConfluenceStub.blogposts = []
    ATTACHMENTS.clear()
    FILES.clear()
    BROKEN_LISTINGS.clear()
    SHORT_LINKS.clear()


def _document(db, workspace_id: str, page_id: str) -> Document:
    """Codes are unique across the installation, so a second workspace
    importing the same page gets a qualified one — look the document up by
    workspace rather than assuming the readable code."""
    return db.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.code.like(f"CONF-LNF-{page_id}%"),
        )
    )


def _run(workspace_id, base_url, **kwargs):
    db = SessionLocal()
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=workspace_id, source="confluence")
    db.add(job)
    db.commit()
    job_uid = job.uid
    db.close()
    run_confluence_import(job_uid, workspace_id, base_url, "pat", "LNF", None, **kwargs)
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    result = (job.status, job.error, dict(job.counts or {}))
    db.close()
    return result


def test_pages_become_typed_documents_with_a_published_revision(confluence_stub):
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    # Asset keys are unique across the installation, so the page has to name
    # the one this test creates.
    asset_key = f"LNFT2-{secrets.randbelow(900000) + 100000}"
    pages = json.loads(json.dumps(PAGES))
    pages[0]["body"]["storage"]["value"] = (
        f"<h1>Recovery</h1><p>Camera {asset_key} first.</p>"
    )
    _ConfluenceStub.pages = pages

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.flush()
    db.add(Schema(uid=f"sc-{suffix}", workspace_id=ws, name="Cameras"))
    db.flush()
    db.add(Asset(uid=f"as-{suffix}", workspace_id=ws, schema_uid=f"sc-{suffix}",
                 key=asset_key, name="FI4-B-CAM-VIS-001", type="Cameras"))
    db.commit()
    db.close()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents"] == 2

    db = SessionLocal()
    procedure = _document(db, ws, "101")
    assert procedure.title == "Vacuum recovery procedure"
    assert procedure.source == "confluence"
    assert procedure.document_type_uid.endswith(":procedure")

    revision = db.get(DocumentRevision, procedure.current_revision_uid)
    # An imported page is already in use at the source; parking it in draft
    # would hide the whole library behind a review nobody asked for.
    assert revision.state == "published"
    assert "# Recovery" in revision.body_markdown
    assert revision.attributes["argus_source_version"] == 3
    assert revision.attributes["argus_source_author"] == "Marco Rossi"
    assert revision.attributes["argus_source_url"].endswith("pageId=101")

    logbook = _document(db, ws, "102")
    assert logbook.document_type_uid.endswith(":logbook-entry")

    # A page naming an object key is linked to that object.
    links = db.scalars(
        select(DocumentRelation).where(DocumentRelation.from_document_uid == procedure.uid)
    ).all()
    assert [(r.to_type, r.to_uid) for r in links] == [("asset", f"as-{suffix}")]
    db.close()


def test_reimporting_an_unchanged_page_adds_no_revision(confluence_stub):
    """The page version is what says whether anything changed; without that
    check a document's history fills with identical revisions."""
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    _ConfluenceStub.pages = PAGES

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    _run(ws, confluence_stub)
    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents_unchanged"] == 2
    assert counts.get("documents", 0) == 0

    db = SessionLocal()
    document = _document(db, ws, "101")
    revisions = db.scalars(
        select(DocumentRevision).where(DocumentRevision.document_uid == document.uid)
    ).all()
    assert len(revisions) == 1
    db.close()


def test_an_edited_page_supersedes_the_previous_revision(confluence_stub):
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    _ConfluenceStub.pages = PAGES

    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()
    _run(ws, confluence_stub)

    edited = json.loads(json.dumps(PAGES))
    edited[0]["version"]["number"] = 4
    edited[0]["body"]["storage"]["value"] = "<h1>Recovery</h1><p>Revised.</p>"
    _ConfluenceStub.pages = edited
    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents_updated"] == 1

    db = SessionLocal()
    document = _document(db, ws, "101")
    revisions = sorted(
        db.scalars(
            select(DocumentRevision).where(DocumentRevision.document_uid == document.uid)
        ).all(),
        key=lambda r: r.revision_number,
    )
    assert [r.revision_number for r in revisions] == [1, 2]
    assert revisions[0].state == "superseded"
    assert revisions[0].superseded_by_uid == revisions[1].uid
    assert revisions[1].state == "published"
    assert "Revised." in revisions[1].body_markdown
    assert document.current_revision_uid == revisions[1].uid
    db.close()
    _ConfluenceStub.pages = PAGES


def test_a_wrong_base_url_names_the_context_path(confluence_stub):
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()

    status, error, _counts = _run(ws, confluence_stub + "/nope")
    assert status == "failed"
    assert "context path" in (error or "")


def _page(page_id: str, title: str, *, label: str = "procedure", body: str = "<p>x</p>",
          parent: str | None = None, version: int = 1) -> dict:
    page = {
        "id": page_id,
        "title": title,
        "space": {"key": "LNF"},
        "version": {"number": version, "when": "2026-09-01T10:00:00.000Z",
                    "by": {"displayName": "Marco Rossi"}},
        "metadata": {"labels": {"results": [{"name": label}]}},
        "body": {"storage": {"value": body}},
    }
    if parent:
        page["ancestors"] = [{"id": parent}]
    return page


def _workspace() -> str:
    suffix = secrets.token_hex(4)
    ws = f"ws-{suffix}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="WS"))
    db.flush()
    install(db, ws, ["core-facility"])  # as the web makes one
    db.commit()
    db.close()
    return ws


def test_every_page_is_imported_not_just_the_first_batch(confluence_stub):
    """The first response is one batch, not the library. Reading its `size`
    as a total stopped every import dead at fifty pages — which looks like
    a successful import of a wiki that is mostly missing."""
    _ConfluenceStub.pages = [_page(str(1000 + i), f"Page {i}") for i in range(127)]
    ws = _workspace()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents"] == 127


def test_blogposts_are_imported_too(confluence_stub):
    """A wiki keeps shift reports and announcements as blogposts; asking
    only for pages leaves out an entire category of operational record."""
    _ConfluenceStub.pages = [_page("2001", "A page")]
    _ConfluenceStub.blogposts = [_page("3001", "Shift report 2026-09-10", label="logbook")]
    ws = _workspace()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents"] == 2

    db = SessionLocal()
    blog = _document(db, ws, "3001")
    assert blog is not None, "the blogpost should have become a document"
    assert blog.document_type_uid.endswith(":logbook-entry")
    db.close()


def test_attachments_are_copied_and_the_body_points_at_them(confluence_stub):
    _ConfluenceStub.pages = [
        _page("4001", "Vacuum layout",
              body='<p>See below.</p><ac:image><ri:attachment ri:filename="layout.png" /></ac:image>')
    ]
    ATTACHMENTS["4001"] = [{
        "id": "att-1",
        "title": "layout.png",
        "version": {"number": 1, "by": {"displayName": "Marco Rossi"}},
        "metadata": {"mediaType": "image/png"},
        "_links": {"download": "/download/attachments/4001/layout.png"},
    }]
    FILES["/download/attachments/4001/layout.png"] = PNG
    ws = _workspace()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["attachments"] == 1

    db = SessionLocal()
    document = _document(db, ws, "4001")
    revision = db.get(DocumentRevision, document.current_revision_uid)
    attachment = db.scalar(
        select(Attachment).where(Attachment.document_revision_uid == revision.uid)
    )
    assert attachment.filename == "layout.png"
    assert attachment.file_size == len(PNG)
    assert open(attachment.storage_path, "rb").read() == PNG
    # The body must point at the copy, not name a file on another server.
    assert f"![layout.png](/v1/attachments/{attachment.uid})" in revision.body_markdown
    db.close()


def test_an_unchanged_file_is_not_downloaded_again(confluence_stub):
    """A new revision of a page doesn't mean new images; re-fetching every
    file on every edit is bytes nobody needs to move twice."""
    _ConfluenceStub.pages = [
        _page("5001", "Layout",
              body='<ac:image><ri:attachment ri:filename="layout.png" /></ac:image>')
    ]
    ATTACHMENTS["5001"] = [{
        "id": "att-9", "title": "layout.png",
        "version": {"number": 1},
        "_links": {"download": "/download/attachments/5001/layout.png"},
    }]
    FILES["/download/attachments/5001/layout.png"] = PNG
    ws = _workspace()
    _run(ws, confluence_stub)

    # The page is edited; the image is not.
    _ConfluenceStub.pages = [
        _page("5001", "Layout", version=2,
              body='<p>Revised.</p><ac:image><ri:attachment ri:filename="layout.png" /></ac:image>')
    ]
    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents_updated"] == 1
    assert counts.get("attachments", 0) == 0, "the file was already here"

    db = SessionLocal()
    document = _document(db, ws, "5001")
    attachments = db.scalars(
        select(Attachment)
        .join(DocumentRevision, DocumentRevision.uid == Attachment.document_revision_uid)
        .where(DocumentRevision.document_uid == document.uid)
    ).all()
    assert len(attachments) == 1
    # The new revision still shows the image, pointing at the same copy.
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert f"/v1/attachments/{attachments[0].uid}" in revision.body_markdown
    db.close()


def test_the_page_tree_becomes_document_relations(confluence_stub):
    """A wiki's shape carries meaning — a page under "Vacuum system" is
    about the vacuum system — and it is the cheapest structure the graph
    can get from an import."""
    _ConfluenceStub.pages = [
        _page("6001", "Vacuum system"),
        _page("6002", "Vacuum recovery", parent="6001"),
    ]
    ws = _workspace()
    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["page_tree_links"] == 1

    db = SessionLocal()
    parent = _document(db, ws, "6001")
    child = _document(db, ws, "6002")
    relation = db.scalar(
        select(DocumentRelation).where(
            DocumentRelation.from_document_uid == child.uid,
            DocumentRelation.relation_type == "child_of",
        )
    )
    assert relation.to_uid == parent.uid
    assert relation.to_type == "document"
    db.close()


def test_an_unreachable_attachment_does_not_lose_the_import(confluence_stub):
    """One file the server won't hand over is a note on an otherwise good
    import — not a reason to throw away every page that came with it."""
    _ConfluenceStub.pages = [
        _page("7001", "Layout", body="<p>Body text.</p>"),
        _page("7002", "Another page", body="<p>Also fine.</p>"),
    ]
    BROKEN_LISTINGS.add("7001")
    ws = _workspace()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["documents"] == 2, "both pages still arrive"

    db = SessionLocal()
    document = _document(db, ws, "7001")
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert "Body text." in revision.body_markdown
    db.close()


def test_a_failed_file_is_reported_as_a_warning(confluence_stub):
    """Silently dropping it would leave a body referring to an image that
    was never copied, with nothing anywhere saying so."""
    _ConfluenceStub.pages = [_page("7101", "Layout", body="<p>x</p>")]
    BROKEN_LISTINGS.add("7101")
    ws = _workspace()

    db = SessionLocal()
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=ws, source="confluence")
    db.add(job)
    db.commit()
    job_uid = job.uid
    db.close()

    run_confluence_import(job_uid, ws, confluence_stub, "pat", "LNF", None)

    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    assert job.status == "succeeded"
    assert any("attachment_list" in w for w in (job.warnings or [])), job.warnings
    db.close()


def test_a_file_that_will_not_download_leaves_the_rest_of_the_page(confluence_stub):
    _ConfluenceStub.pages = [
        _page("7201", "Layout",
              body='<p>Text stays.</p>'
                   '<ac:image><ri:attachment ri:filename="gone.png" /></ac:image>'
                   '<ac:image><ri:attachment ri:filename="here.png" /></ac:image>')
    ]
    ATTACHMENTS["7201"] = [
        {"id": "a-gone", "title": "gone.png", "version": {"number": 1},
         "_links": {"download": "/download/attachments/7201/gone.png"}},
        {"id": "a-here", "title": "here.png", "version": {"number": 1},
         "_links": {"download": "/download/attachments/7201/here.png"}},
    ]
    # Only the second file is actually served.
    FILES["/download/attachments/7201/here.png"] = PNG
    ws = _workspace()

    status, error, counts = _run(ws, confluence_stub)
    assert status == "succeeded", error
    assert counts["attachments"] == 1

    db = SessionLocal()
    document = _document(db, ws, "7201")
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert "Text stays." in revision.body_markdown
    # The one that arrived is an image; the one that didn't is named in the
    # text rather than linked to a file that was never copied.
    assert "![here.png](/v1/attachments/" in revision.body_markdown
    assert "image: gone.png" in revision.body_markdown
    assert "![gone.png]" not in revision.body_markdown
    db.close()


def test_a_page_link_names_the_server_and_the_page():
    """What the Share button gives, and the addresses a browser shows."""
    assert parse_page_link("https://confluence.infn.it/x/YwX6AQ") == {
        "base_url": "https://confluence.infn.it", "page_id": "33162595", "short": "YwX6AQ"}
    assert parse_page_link("https://wiki.example.org/confluence/pages/viewpage.action?pageId=4242") == {
        "base_url": "https://wiki.example.org/confluence", "page_id": "4242"}
    assert parse_page_link("https://site.atlassian.net/wiki/spaces/LNF/pages/98765/Vacuum+system")["page_id"] == "98765"
    assert parse_page_link("https://wiki.example.org/display/LNF/Vacuum+recovery") == {
        "base_url": "https://wiki.example.org", "space": "LNF", "title": "Vacuum recovery"}
    for wrong in ("confluence.infn.it/x/YwX6AQ", "https://confluence.infn.it/", "https://wiki.example.org/x/!!"):
        with pytest.raises(PageLinkError):
            parse_page_link(wrong)


def _tree():
    _ConfluenceStub.pages = [
        _page("33162595", "Vacuum system"),
        _page("33162596", "Vacuum recovery", parent="33162595"),
        {**_page("33162597", "Gauge calibration"), "ancestors": [{"id": "33162595"}, {"id": "33162596"}]},
        _page("777", "Elsewhere"),
    ]


def _run_link(ws, link, **kwargs):
    db = SessionLocal()
    job = ImportJob(uid=str(uuid.uuid4()), workspace_id=ws, source="confluence")
    db.add(job)
    db.commit()
    uid = job.uid
    db.close()
    run_confluence_import(uid, ws, "", "pat", page_url=link, **kwargs)
    db = SessionLocal()
    job = db.get(ImportJob, uid)
    result = (job.status, job.error, dict(job.counts or {}))
    db.close()
    return result


def test_a_short_link_imports_its_page_and_the_pages_under_it(confluence_stub):
    _tree()
    ws = _workspace()
    status, error, counts = _run_link(ws, f"{confluence_stub}/x/YwX6AQ")
    assert status == "succeeded", error
    db = SessionLocal()
    assert all(_document(db, ws, i) is not None for i in ("33162595", "33162596", "33162597"))
    assert _document(db, ws, "777") is None                       # not under the page
    db.close()


def test_a_page_link_without_the_pages_under_it(confluence_stub):
    _tree()
    ws = _workspace()
    status, error, _ = _run_link(ws, f"{confluence_stub}/display/LNF/Vacuum+recovery", include_children=False)
    assert status == "succeeded", error
    db = SessionLocal()
    assert _document(db, ws, "33162596") is not None
    assert _document(db, ws, "33162597") is None and _document(db, ws, "33162595") is None
    db.close()


def test_a_short_link_the_server_redirects_is_followed(confluence_stub):
    """Should the id written in a short link ever not be the page's, the server's
    own redirect says which page it is."""
    _tree()
    SHORT_LINKS["AQ"] = "777"                                     # "AQ" decodes to page 1
    ws = _workspace()
    status, error, _ = _run_link(ws, f"{confluence_stub}/x/AQ", include_children=False)
    assert status == "succeeded", error
    db = SessionLocal()
    assert _document(db, ws, "777") is not None
    db.close()


def test_a_link_to_a_page_that_is_not_there_says_so(confluence_stub):
    _tree()
    status, error, _ = _run_link(_workspace(), f"{confluence_stub}/pages/viewpage.action?pageId=5")
    assert status == "failed" and "not found" in error


def test_a_request_needs_a_server_or_a_page_link():
    from pydantic import ValidationError

    from app.schemas.import_config import ConfluenceImportConfigParams
    assert ConfluenceImportConfigParams(source="confluence", page_url="https://confluence.infn.it/x/YwX6AQ")
    with pytest.raises(ValidationError, match="server URL, or a link"):
        ConfluenceImportConfigParams(source="confluence", space_key="LNF")
    with pytest.raises(ValidationError, match="not a link to a Confluence page"):
        ConfluenceImportConfigParams(source="confluence", page_url="https://confluence.infn.it/")
