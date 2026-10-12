"""Markdown uploaded as documentation.

The thing that makes this worth having over copy-paste is that the images
come too. A document whose figures are broken links is not the document
somebody wrote.
"""
import io
import secrets
import zipfile

import pytest

from app.packages.install import install
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_token
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models.api_token import ApiToken
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.workspace import Workspace
from app.services.markdown_import import resolve_links, split_front_matter

client = TestClient(app)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _attachments_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(
        "app.services.markdown_import.ATTACHMENTS_DIR",
        str(tmp_path_factory.mktemp("md-attachments")),
    )


@pytest.fixture()
def token():
    db = SessionLocal()
    workspace_id = f"md-{secrets.token_hex(4)}"
    db.add(Workspace(id=workspace_id, name="Test"))
    db.flush()
    install(db, workspace_id, ["core-facility"])  # as the web makes one
    db.flush()
    raw = secrets.token_urlsafe(16)
    db.add(ApiToken(workspace_id=workspace_id, token_hash=hash_token(raw)))
    db.commit()
    db.close()
    return workspace_id, raw


def auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def upload(raw: str, files: list[tuple[str, bytes]], **data):
    return client.post(
        "/v1/documents/import",
        files=[("files", (name, content)) for name, content in files],
        data=data,
        headers=auth(raw),
    )


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def test_front_matter_is_read_and_removed():
    meta, body = split_front_matter(
        "---\ntitle: Vacuum recovery\ntype: Procedure\nkeywords: [vacuum, btf]\n---\n# Heading\n"
    )
    assert meta["title"] == "Vacuum recovery"
    assert meta["keywords"] == ["vacuum", "btf"]
    assert body.startswith("# Heading")


def test_broken_front_matter_stays_in_the_body():
    """Losing the document because its header is malformed is worse than
    showing the header to whoever can fix it."""
    text = "---\ntitle: [unclosed\n---\n# Heading\n"
    meta, body = split_front_matter(text)
    assert meta == {}
    assert body == text


def test_relative_links_are_rewritten_absolute_ones_are_not():
    body = (
        "![layout](images/layout.png)\n"
        "[manual](https://example.invalid/m.pdf)\n"
        "[anchor](#section)\n"
    )
    rewritten, used = resolve_links(
        body, "docs", {"docs/images/layout.png": "/v1/attachments/abc"}
    )
    assert "![layout](/v1/attachments/abc)" in rewritten
    assert "https://example.invalid/m.pdf" in rewritten
    assert "(#section)" in rewritten
    assert used == {"docs/images/layout.png"}


def test_a_stripped_directory_still_finds_the_image():
    """A browser's multi-file input sends `layout.png`, not
    `images/layout.png` — which is how a folder of Markdown arrives when
    nobody thought to zip it first."""
    rewritten, used = resolve_links(
        "![layout](images/layout.png)", "", {"layout.png": "/v1/attachments/abc"}
    )
    assert "![layout](/v1/attachments/abc)" in rewritten
    assert used == {"layout.png"}


def test_an_ambiguous_filename_is_not_guessed():
    """Two files with the same name in different folders: picking one would
    put the wrong figure in the document, which is worse than none."""
    rewritten, used = resolve_links(
        "![plan](a/plan.png)",
        "",
        {"x/plan.png": "/v1/attachments/one", "y/plan.png": "/v1/attachments/two"},
    )
    assert rewritten == "![plan](a/plan.png)"
    assert used == set()


def test_the_full_path_wins_over_the_filename():
    rewritten, _used = resolve_links(
        "![plan](docs/images/plan.png)",
        "",
        {"docs/images/plan.png": "/v1/attachments/right", "plan.png": "/v1/attachments/wrong"},
    )
    assert "/v1/attachments/right" in rewritten


def test_a_link_to_something_not_uploaded_is_left_alone():
    """Inventing a URL for a file nobody sent is worse than an honest
    broken link — it points at something that will never exist."""
    rewritten, used = resolve_links("![x](images/missing.png)", "", {})
    assert rewritten == "![x](images/missing.png)"
    assert used == set()


def test_a_markdown_file_becomes_a_published_document(token):
    workspace_id, raw = token
    resp = upload(raw, [("vacuum-recovery.md", b"# Vacuum recovery\n\nClose the valve.\n")])
    assert resp.status_code == 200, resp.text
    assert resp.json()["documents"] == 1

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    assert document.title == "Vacuum recovery", "the first heading names it"
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert revision.state == "published"
    assert "Close the valve." in revision.body_markdown
    db.close()


def test_images_are_attached_and_the_body_points_at_them(token):
    workspace_id, raw = token
    # The browser sends the basename only, exactly as a real upload does.
    resp = upload(raw, [
        ("procedure.md", b"# Recovery\n\n![layout](images/layout.png)\n"),
        ("layout.png", PNG),
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["documents"] == 1
    assert body["attachments"] == 1

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    revision = db.get(DocumentRevision, document.current_revision_uid)
    attachment = db.scalar(
        select(Attachment).where(Attachment.document_revision_uid == revision.uid)
    )
    assert attachment.filename == "layout.png"
    assert open(attachment.storage_path, "rb").read() == PNG
    assert f"![layout](/v1/attachments/{attachment.uid})" in revision.body_markdown
    db.close()


def test_a_zip_of_a_folder_is_unpacked(token):
    """A folder reaches a browser as a zip; storing it as one opaque file
    would import nothing."""
    workspace_id, raw = token
    archive = _zip({
        "manual/intro.md": b"---\ntitle: Introduction\n---\nSee the [layout](assets/plan.png).\n",
        "manual/assets/plan.png": PNG,
        "manual/__MACOSX/junk": b"x",
    })
    resp = upload(raw, [("manual.zip", archive)])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"documents": 1, "attachments": 1, "relations": 0, "skipped": []}

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    assert document.title == "Introduction"
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert "/v1/attachments/" in revision.body_markdown
    db.close()


def test_front_matter_chooses_the_type_and_keywords(token):
    workspace_id, raw = token
    resp = upload(raw, [(
        "doc.md",
        b"---\ntitle: Vacuum recovery\ntype: Procedure\nkeywords: [vacuum, BTF]\n"
        b"facility: LNF\n---\nBody.\n",
    )])
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    assert document.document_type_uid.endswith(":procedure")
    revision = db.get(DocumentRevision, document.current_revision_uid)
    assert revision.attributes["argus_keywords"] == ["vacuum", "BTF"]
    assert revision.attributes["argus_facility"] == "LNF"
    db.close()


def test_the_type_falls_back_to_the_title_when_the_header_says_nothing(token):
    workspace_id, raw = token
    upload(raw, [("runbook.md", b"# Runbook: camera offline\n\nFirst actions.\n")])

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    assert document.document_type_uid.endswith(":runbook")
    db.close()


def test_links_between_uploaded_files_become_relations(token):
    """A set of pages should arrive as the set it was, not as unconnected
    documents that happen to have been uploaded together."""
    workspace_id, raw = token
    resp = upload(raw, [
        ("index.md", b"# Index\n\nStart with [recovery](recovery.md).\n"),
        ("recovery.md", b"# Recovery\n\nSteps.\n"),
    ])
    assert resp.status_code == 200, resp.text
    assert resp.json()["relations"] == 1

    db = SessionLocal()
    index = db.scalar(
        select(Document).where(Document.workspace_id == workspace_id, Document.title == "Index")
    )
    relation = db.scalar(
        select(DocumentRelation).where(DocumentRelation.from_document_uid == index.uid)
    )
    assert relation.relation_type == "references"
    db.close()


def test_two_files_with_the_same_name_do_not_collide(token):
    """Document codes are unique across the installation, so a second
    README must not silently replace the first — or be dropped."""
    _workspace_id, raw = token
    archive = _zip({
        "a/README.md": b"# Alpha\n",
        "b/README.md": b"# Beta\n",
    })
    resp = upload(raw, [("docs.zip", archive)])
    assert resp.status_code == 200, resp.text
    assert resp.json()["documents"] == 2


def test_an_upload_with_no_markdown_says_so(token):
    _workspace_id, raw = token
    resp = upload(raw, [("layout.png", PNG)])
    assert resp.status_code == 422
    assert "Markdown" in resp.json()["detail"]


def test_a_dwg_gets_viewable_sheets_beside_it(token, monkeypatch):
    """Nothing renders DWG in a browser, so the upload produces the sheets a
    reader can see. The original stays exactly as uploaded."""
    workspace_id, raw = token
    monkeypatch.setattr(
        "app.services.markdown_import.dwg_to_dxf",
        lambda content: (b"<dxf>", None),
    )
    monkeypatch.setattr(
        "app.services.markdown_import.render_sheets",
        lambda dxf: ([("a_1", b"<svg/>"), ("a_2", b"<svg/>")], None),
    )
    resp = upload(raw, [
        ("drawing-doc.md", b"# Chamber\n\n[plan](chamber.dwg)\n"),
        ("chamber.dwg", b"AC1015 fake dwg bytes"),
    ])
    assert resp.status_code == 200, resp.text
    assert resp.json()["attachments"] == 3, "the original and its two sheets"

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    revision = db.get(DocumentRevision, document.current_revision_uid)
    files = db.scalars(
        select(Attachment).where(Attachment.document_revision_uid == revision.uid)
    ).all()
    by_name = {a.filename: a for a in files}
    assert set(by_name) == {"chamber.dwg", "chamber (a_1).svg", "chamber (a_2).svg"}
    assert open(by_name["chamber.dwg"].storage_path, "rb").read() == b"AC1015 fake dwg bytes"
    for sheet in ("chamber (a_1).svg", "chamber (a_2).svg"):
        assert by_name[sheet].backend_id == f"sheet-of:{by_name['chamber.dwg'].uid}"
        assert by_name[sheet].mime_type == "image/svg+xml"
    # The body still links the original, which is what someone downloads.
    assert f"/v1/attachments/{by_name['chamber.dwg'].uid}" in revision.body_markdown
    db.close()


def test_a_drawing_that_cannot_be_converted_still_arrives(token, monkeypatch):
    """A failed conversion must not take the file with it."""
    workspace_id, raw = token
    monkeypatch.setattr(
        "app.services.markdown_import.dwg_to_dxf",
        lambda content: (None, "unsupported version"),
    )
    resp = upload(raw, [
        ("doc.md", b"# Chamber\n\n[plan](chamber.dwg)\n"),
        ("chamber.dwg", b"whatever"),
    ])
    assert resp.status_code == 200, resp.text
    assert resp.json()["attachments"] == 1

    db = SessionLocal()
    document = db.scalar(select(Document).where(Document.workspace_id == workspace_id))
    revision = db.get(DocumentRevision, document.current_revision_uid)
    attachment = db.scalar(
        select(Attachment).where(Attachment.document_revision_uid == revision.uid)
    )
    assert attachment.filename == "chamber.dwg"
    db.close()
