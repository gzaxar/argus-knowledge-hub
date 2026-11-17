"""A running log's pictures, through "Rework from raw text": read out of the PDF where they are, kept for the
workspace, each put under the entry it belongs to with what the vision model reads in it (once), and saved with
the draft as files of its revision. The models are scripted."""
import ctypes
import io

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.intake import files
from app.intake import markdown as md
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.intake import IntakeRun
from app.models.llm_config import LLMConfig
from app.routers import document_templates as dt_router
from app.services import reshape
from tests.test_document_templates import as_, client, world  # noqa: F401  (world is a fixture)


def make_pdf(pages: list[list[tuple]]) -> bytes:
    """A PDF of A4 pages, each a list of ("text", y, words) and ("image", y, colour), y from the top."""
    pdf = pdfium.PdfDocument.new()
    for items in pages:
        page = pdf.new_page(595, 842)
        for kind, y, what in items:
            if kind == "text":
                obj = pdfium_raw.FPDFPageObj_NewTextObj(pdf.raw, b"Helvetica", ctypes.c_float(12))
                wide = (what + "\x00").encode("utf-16-le")
                pdfium_raw.FPDFText_SetText(obj, ctypes.cast(ctypes.c_char_p(wide),
                                                             ctypes.POINTER(pdfium_raw.FPDF_WCHAR)))
                pdfium_raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 72, 842 - y)
                pdfium_raw.FPDFPage_InsertObject(page.raw, obj)
            else:
                picture = pdfium.PdfImage.new(pdf)
                picture.set_bitmap(pdfium.PdfBitmap.from_pil(Image.new("RGB", (200, 120), what)))
                picture.set_matrix(pdfium.PdfMatrix().scale(200, 120).translate(72, 842 - y - 120))
                page.insert_obj(picture)
        page.gen_content()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


LOG = make_pdf([
    [("text", 72, "16.10.2026"), ("text", 100, "Le misure sono quelle dopo le 17.30"),
     ("text", 116, "10h35: misura emittanza driver AC1"), ("text", 132, "SPEGNI PLASMA"),
     ("image", 150, "red"), ("text", 300, "10h28: misura emittanza witness AC1"), ("image", 320, "blue")],
    [("image", 72, "green"), ("text", 220, "9.35: laser banda C riacceso"), ("image", 240, "red")],
])


def test_a_pdfs_pictures_are_read_where_they_are():
    figures: list = []
    text = files.extract_document(LOG, "log.pdf", "application/pdf", figures=figures)["text"]
    assert [f["page"] for f in figures] == [1, 1, 2, 2]
    order = [line for line in text.split("\n") if line.strip()]
    tokens = [i for i, line in enumerate(order) if files.FIGURE_LINE.match(line)]
    assert len(tokens) == 4
    assert "SPEGNI PLASMA" in order[tokens[0] - 1]
    assert order[tokens[1] - 1].startswith("10h28")
    assert tokens[2] == tokens[1] + 1                   # the second page opens with a picture: it follows on
    assert order[tokens[3] - 1].startswith("9.35")
    # A log's timed line is an entry of its own, never the end of the line above.
    assert "10h35: misura emittanza driver AC1" in [x.strip() for x in order]
    assert md.text_to_markdown("dopo le 17.30\n10h35: misura emittanza", wrapped=True).endswith(
        "\n10h35: misura emittanza")


def test_reading_a_pdf_keeps_its_pictures_for_the_workspace_only(world):
    w = world
    as_(w["writer"])
    r = client.post("/v1/intake/extract", headers=w["h"], files={"file": ("log.pdf", LOG, "application/pdf")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["figures"] == 4
    found = reshape.figures_in(out["text"])
    assert [f["page"] for f in found] == [1, 1, 2, 2]
    assert [f["caption"] for f in found] == ["10h35: misura emittanza driver AC1",
                                              "10h28: misura emittanza witness AC1",
                                              "10h28: misura emittanza witness AC1", "9.35: laser banda C riacceso"]
    picture = client.get(f"/v1/intake/source-images/{found[0]['id']}", headers=w["h"])
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
    as_(w["outsider"])
    assert client.get(f"/v1/intake/source-images/{found[0]['id']}",
                      headers={"X-Workspace-Id": w["other"]}).status_code == 404
    as_(w["reader"])                                    # reading is not reworking
    assert client.get(f"/v1/intake/source-images/{found[0]['id']}", headers=w["h"]).status_code == 403


LOG_EXTRACTION = {
    "title": {"value": "Logbook 16.10.2026", "status": "inferred"},
    "fields": {"shift": {"value": "16.10.2026", "status": "present", "evidence": "L1", "quote": "16.10.2026"}},
    "sections": {"timeline": {"items": [{"cells": {"time": "10h35", "event": "misura emittanza driver AC1"},
                                         "status": "present", "evidence": "L5"}]},
                 "handover": {"items": [{"text": "Spegnere il plasma", "status": "inferred"}]}},
    "dates": {}, "missing": [], "ambiguities": [],
}


def test_the_draft_shows_each_picture_under_its_entry_read_once_and_saved_with_the_revision(world, monkeypatch):
    w = world
    as_(w["writer"])
    db = SessionLocal()
    db.query(LLMConfig).filter(LLMConfig.workspace_id == w["ws"]).update({"vision_model": "eyes"})
    db.commit()
    db.close()
    text = client.post("/v1/intake/extract", headers=w["h"],
                       files={"file": ("log.pdf", LOG, "application/pdf")}).json()["text"]
    seen = {"model": None, "looks": []}

    def model(endpoint, system, user):
        seen["model"] = user
        import json
        return json.dumps(LOG_EXTRACTION)

    def look(endpoint, image, mime, system, user):
        seen["looks"].append(user)
        return "Emittance scan, AC101_EMIT\nX fit εn = 1.7 µm"
    monkeypatch.setattr(reshape, "complete_structured", model)
    monkeypatch.setattr("app.services.llm.look", look)
    body = {"source": {"text": text, "kind": "import", "filename": "log.pdf"},
            "document_type_uid": w["types"]["Logbook Entry"]}
    r = client.post("/v1/ai/reshape", headers=w["h"], json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert "source-images" not in seen["model"] and "[figure 1]" in seen["model"]   # the model gets no links
    assert len(seen["looks"]) == 3                      # four pictures, two the same: read once each
    # Read four at a time: in any order.
    assert any("The entry it belongs to: 10h35: misura emittanza driver AC1" in x for x in seen["looks"])
    draft = out["markdown"]
    assert "## Figures" in draft and "**Figure 1 — 10h35: misura emittanza driver AC1** (page 1)" in draft
    assert "> X fit εn = 1.7 µm" in draft and "to check" in draft
    assert [f["reading"] is not None for f in out["figures"]] == [True] * 4
    again = client.post("/v1/ai/reshape", headers=w["h"], json=body)
    assert again.status_code == 200 and len(seen["looks"]) == 3              # kept: not read again
    db = SessionLocal()
    try:
        runs = db.scalars(select(IntakeRun).where(IntakeRun.workspace_id == w["ws"],
                                                  IntakeRun.operation == "document.figure")).all()
        assert len(runs) == 3 and all("eyes" == r.model for r in runs)
    finally:
        db.close()

    saved = client.post("/v1/documents/reshape", headers=w["h"], json={
        **body, "template": out["template"]["ref"], "title": out["title"], "markdown": draft,
        "dates": out["dates"], "confirm_document_date": True})
    assert saved.status_code == 201, saved.text
    db = SessionLocal()
    try:
        doc = db.get(Document, saved.json()["document_uid"])
        files_ = {a.uid: a for a in db.scalars(select(Attachment).where(
            Attachment.document_revision_uid == saved.json()["revision_uid"]))}
        body_md = db.get(DocumentRevision, saved.json()["revision_uid"]).body_markdown
        assert doc is not None and "source-images" not in body_md
        pictures = [a for a in files_.values() if a.mime_type == "image/png"]
        assert len(pictures) == 3 and all(f"/v1/attachments/{a.uid}" in body_md for a in pictures)
        assert sorted(a.filename for a in pictures) == ["figure-1.png", "figure-2.png", "figure-3.png"]
        source = next(a for a in files_.values() if a.filename == "log.txt")
        assert "source-images" not in open(source.storage_path, encoding="utf-8").read()
    finally:
        db.close()


def test_without_a_vision_model_the_pictures_are_kept_and_the_draft_says_so(world, monkeypatch):
    w = world
    as_(w["writer"])
    text = client.post("/v1/intake/extract", headers=w["h"],
                       files={"file": ("log.pdf", LOG, "application/pdf")}).json()["text"]
    monkeypatch.setattr(reshape, "complete_structured", lambda e, s, u: __import__("json").dumps(LOG_EXTRACTION))
    out = client.post("/v1/ai/reshape", headers=w["h"], json={
        "source": {"text": text, "kind": "import"}, "document_type_uid": w["types"]["Logbook Entry"]}).json()
    assert out["markdown"].count("](/v1/intake/source-images/") == 4 and "to check" not in out["markdown"]
    assert any(i["kind"] == "figures_not_read" and "no vision model" in i["message"] for i in out["issues"])
    assert dt_router.MAX_FIGURE_READINGS >= 10


def test_a_picture_is_captioned_by_its_timed_entry_and_the_line_that_names_it():
    pic = "![Figure {n}, page 7](/v1/intake/source-images/" + "a" * 31 + "{n})"
    text = "\n".join(["15.10.2026", "20.52: durata da rianalizzare", "calibrazione", pic.format(n=1),
                      "spot a deflettore spento", pic.format(n=2), "## SPEGNI PLASMA", pic.format(n=3),
                      "16.10.2026", "una nota senza orario", pic.format(n=4)])
    assert [f["caption"] for f in reshape.figures_in(text)] == [
        "20.52: durata da rianalizzare — calibrazione", "20.52: durata da rianalizzare — spot a deflettore spento",
        "20.52: durata da rianalizzare", "una nota senza orario"]
    assert reshape.for_model(text).split("\n")[3] == "[figure 1]"
