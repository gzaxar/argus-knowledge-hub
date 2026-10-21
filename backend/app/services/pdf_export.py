"""One document, asset or ticket as a PDF, made on the server.

The PDF is the Markdown export (services/markdown_export) laid out on A4, so the
file, the PDF and the printout say the same thing. It is made here rather than
by the browser's print dialog so that one tap gives a file — on a tablet or the
phone there is no "Save as PDF" to find.

Pictures in the text are the record's own attachments, read from disk; nothing
is fetched from the network (a link in imported text is not a reason for the
server to call out). Fonts are DejaVu, already in the image for the drawing
renderer, so any language prints.
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Iterable

import markdown as md
from fastapi import Response
from fpdf import FPDF, FontFace

from app.models.attachment import Attachment

FONT_DIR = os.environ.get("PDF_FONT_DIR", "/usr/share/fonts/truetype/dejavu")
IMAGE = re.compile(r"!\[([^\]]*)\]\(/v1/attachments/([A-Za-z0-9-]+)\)")
ANY_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
ATTACHMENT_LINK = re.compile(r"\[([^\]]*)\]\(/v1/attachments/[A-Za-z0-9-]+\)")

Run = tuple  # (text, bold, italic, mono)


class _Blocks(HTMLParser):
    """Python-Markdown's HTML as blocks to lay out: headings, paragraphs, list items, tables, code,
    quotes, rules and pictures, each paragraph a list of styled runs. Tags it does not know (imported
    Confluence markup) are unwrapped to their text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self.runs: list = []
        self.bold = self.italic = self.mono = 0
        self.lists: list[dict] = []          # {"ordered": bool, "n": int}
        self.quote = 0
        self.pre = False
        self.table = None                    # {"rows": [...], "head": n}
        self.cell = None                     # list of text pieces
        self.cell_bold = False
        self.in_head = False

    # --- paragraphs
    def _flush(self, kind="p", **extra):
        text = "".join(r[0] for r in self.runs)
        if text.strip():
            runs = list(self.runs)
            runs[0] = (runs[0][0].lstrip(),) + tuple(runs[0][1:])
            runs[-1] = (runs[-1][0].rstrip(),) + tuple(runs[-1][1:])
            self.blocks.append({"kind": kind, "runs": runs, "quote": self.quote, **extra})
        self.runs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.table is not None and tag in ("tr", "td", "th", "thead", "tbody"):
            if tag == "thead":
                self.in_head = True
            elif tag == "tbody":
                self.in_head = False
            elif tag == "tr":
                self.table["rows"].append([])
                if self.in_head:
                    self.table["head"] = len(self.table["rows"])
            else:
                self.cell, self.cell_bold = [], False
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self._flush()
        elif tag in ("ul", "ol"):
            self._flush("li", depth=len(self.lists), mark=self._mark()) if self.lists else self._flush()
            self.lists.append({"ordered": tag == "ol", "n": 0})
        elif tag == "li":
            if self.runs and self.lists:
                self._flush("li", depth=len(self.lists) - 1, mark=self._mark())
            if self.lists:
                self.lists[-1]["n"] += 1
        elif tag == "blockquote":
            self._flush()
            self.quote += 1
        elif tag == "pre":
            self._flush()
            self.pre = True
        elif tag == "table":
            self._flush()
            self.table = {"rows": [], "head": 0}
        elif tag == "hr":
            self._flush()
            self.blocks.append({"kind": "hr"})
        elif tag == "br":
            self.runs.append(("\n", self.bold > 0, self.italic > 0, self.mono > 0))
        elif tag == "img":
            self._flush()
            if a.get("src"):
                self.blocks.append({"kind": "img", "src": a["src"]})
        elif tag in ("b", "strong"):
            self.bold += 1
        elif tag in ("i", "em"):
            self.italic += 1
        elif tag == "code":
            self.mono += 1

    def _mark(self) -> str:
        top = self.lists[-1]
        return f"{top['n']}." if top["ordered"] else "•"

    def handle_endtag(self, tag):
        if self.table is not None and tag in ("td", "th"):
            if self.table["rows"] and self.cell is not None:
                self.table["rows"][-1].append((" ".join("".join(self.cell).split()), self.cell_bold))
            self.cell = None
            return
        if tag == "table" and self.table is not None:
            if self.table["rows"]:
                self.blocks.append({"kind": "table", **self.table})
            self.table = None
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush(tag)
        elif tag == "p":
            if self.lists:
                return                        # a loose list item's paragraph: the item ends it
            self._flush()
        elif tag == "li":
            if self.lists:
                self._flush("li", depth=len(self.lists) - 1, mark=self._mark())
        elif tag in ("ul", "ol"):
            if self.lists:
                self._flush("li", depth=len(self.lists) - 1, mark=self._mark())
                self.lists.pop()
        elif tag == "blockquote":
            self._flush()
            self.quote = max(0, self.quote - 1)
        elif tag == "pre":
            text = "".join(r[0] for r in self.runs).strip("\n")
            if text:
                self.blocks.append({"kind": "pre", "text": text})
            self.runs = []
            self.pre = False
        elif tag in ("b", "strong"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("i", "em"):
            self.italic = max(0, self.italic - 1)
        elif tag == "code":
            self.mono = max(0, self.mono - 1)

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
            if self.bold and data.strip():
                self.cell_bold = True
            return
        if not self.pre:
            data = re.sub(r"\s+", " ", data)
            if not self.runs and not data.strip():
                return
        self.runs.append((data, self.bold > 0, self.italic > 0, self.mono > 0 and not self.pre))

    def close(self):
        super().close()
        self._flush()


HEADINGS = {"h1": 17, "h2": 14, "h3": 12, "h4": 11, "h5": 10.5, "h6": 10}
BODY = 10
LINE = 5.2


class _Pdf(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.doc_title = title
        self.add_font("DejaVu", "", os.path.join(FONT_DIR, "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"))
        # No italic face in fonts-dejavu-core: italics print upright rather than not at all.
        self.add_font("DejaVu", "I", os.path.join(FONT_DIR, "DejaVuSans.ttf"))
        self.add_font("DejaVu", "BI", os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"))
        self.add_font("DejaVuMono", "", os.path.join(FONT_DIR, "DejaVuSansMono.ttf"))
        self.add_font("DejaVuMono", "B", os.path.join(FONT_DIR, "DejaVuSansMono-Bold.ttf"))
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, margin=18)
        self.set_title(title)
        self.set_creator("ARGUS Knowledge Hub")

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 7.5)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, f"{self.doc_title[:90]}  ·  {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)

    # --- blocks
    def runs(self, runs, size=BODY, line=LINE, bold=False):
        for text, b, i, mono in runs:
            if mono:
                self.set_font("DejaVuMono", "B" if (b or bold) else "", size * 0.92)
            else:
                self.set_font("DejaVu", ("B" if (b or bold) else "") + ("I" if i else ""), size)
            self.write(line, text)
        self.ln(line)

    def block(self, b: dict):
        kind = b["kind"]
        if getattr(self, "previous", None) == "li" and kind != "li":
            self.ln(1.6)                      # the end of a list
        self.previous = kind
        left = self.l_margin
        if b.get("quote"):
            self.set_left_margin(left + 6 * b["quote"])
            self.set_x(self.l_margin)
            top = self.get_y()
            self.set_text_color(70, 70, 70)
        if kind in HEADINGS:
            size = HEADINGS[kind]
            self.ln(3 if kind != "h1" else 1)
            self.set_text_color(15, 23, 42)
            self.runs(b["runs"], size=size, line=size * 0.5, bold=True)
            if kind in ("h1", "h2"):
                y = self.get_y() + 0.5
                self.set_draw_color(203, 213, 225)
                self.line(self.l_margin, y, self.w - self.r_margin, y)
                self.ln(2)
            self.set_text_color(0, 0, 0)
        elif kind == "p":
            self.runs(b["runs"])
            self.ln(1.6)
        elif kind == "li":
            indent = 5 + 6 * b["depth"]
            self.set_font("DejaVu", "", BODY)
            self.set_x(left + indent)
            self.cell(6, LINE, b["mark"])
            self.set_left_margin(left + indent + 6)
            self.runs(b["runs"])
            self.set_left_margin(left)
            self.set_x(left)
            self.ln(0.6)
        elif kind == "pre":
            self.set_font("DejaVuMono", "", 8.5)
            self.set_fill_color(241, 245, 249)
            self.multi_cell(0, 4.3, b["text"], fill=True, padding=2, new_x="LMARGIN", new_y="NEXT")
            self.ln(2)
        elif kind == "hr":
            self.ln(2)
            self.set_draw_color(203, 213, 225)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(3)
        elif kind == "img":
            try:
                # At most the text's width and 170 mm high (two-thirds of a page), keeping its proportions.
                from PIL import Image
                with Image.open(b["src"]) as im:
                    ratio = im.height / im.width if im.width else 1
                w = min(self.epw, 160)
                if w * ratio > 170:
                    w = 170 / ratio
                self.ln(1)
                self.image(b["src"], w=w, h=w * ratio)
                self.ln(2)
            except Exception:
                self.runs([("[picture could not be read]", False, True, False)])
        elif kind == "table":
            self.table_block(b)
        if b.get("quote"):
            self.set_draw_color(251, 191, 36)
            self.set_line_width(0.8)
            self.line(self.l_margin - 3, top, self.l_margin - 3, self.get_y() - 1)
            self.set_line_width(0.2)
            self.set_text_color(0, 0, 0)
            self.set_left_margin(left)
            self.set_x(left)

    def table_block(self, b: dict):
        rows = [r for r in b["rows"] if r]
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [("", False)] * (width - len(r)) for r in rows]
        head = b.get("head", 0)
        self.set_font("DejaVu", "", 8.5)
        self.set_draw_color(203, 213, 225)
        # A heading row that is empty (a key/value table) is left out rather than printed as a blank band.
        if head and not any(c.strip() for c, _bold in rows[0]):
            rows, head = rows[1:], 0
        with self.table(
            first_row_as_headings=bool(head),
            headings_style=FontFace(emphasis="BOLD", fill_color=(241, 245, 249)),
            line_height=4.4,
            padding=1.2,
            text_align="LEFT",
            borders_layout="HORIZONTAL_LINES",
        ) as table:
            for r in rows:
                row = table.row()
                for c, bold in r:
                    row.cell(c, style=FontFace(emphasis="BOLD") if bold else None)
        self.ln(3)


def render(markdown_text: str, title: str, attachments: Iterable[Attachment]) -> bytes:
    """The Markdown as an A4 PDF. `attachments` are the files the text may show as pictures."""
    pictures = {a.uid: a for a in attachments
                if (a.mime_type or "").startswith("image/") and a.storage_path and os.path.isfile(a.storage_path)}

    def picture(m: re.Match) -> str:
        a = pictures.get(m.group(2))
        if a is None:
            return f"*[picture: {m.group(1) or 'not available'}]*"
        return f'\n\n<img src="{a.storage_path}">\n\n'

    text = IMAGE.sub(picture, markdown_text)
    # Pictures from anywhere else are not fetched; their description stands in for them.
    text = ANY_IMAGE.sub(lambda m: f"*[picture: {m.group(1) or m.group(2)}]*", text)
    # A link to a file only works inside ARGUS: in the PDF it is the file's name.
    text = ATTACHMENT_LINK.sub(lambda m: m.group(1), text)
    parser = _Blocks()
    parser.feed(md.markdown(text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html"))
    parser.close()

    pdf = _Pdf(title)
    pdf.add_page()
    for b in parser.blocks:
        pdf.block(b)
    return bytes(pdf.output())


# What the three /pdf endpoints declare, so the contract says a PDF file, not JSON.
OPENAPI = {"response_class": Response,
           "responses": {200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}}}


def response(data: bytes, stem: str) -> Response:
    """The PDF as a download named after the record."""
    name = (re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "export")[:120] + ".pdf"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
