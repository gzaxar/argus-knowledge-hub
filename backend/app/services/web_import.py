"""A web page saved as a folder — an HTML file and its pictures, as a LabVIEW or Doxygen export or a browser's
"save page" makes it — as documents: one per HTML page.

Each page's HTML becomes Markdown (headings, paragraphs, lists, tables, bold and italics, code, links); the
pictures it shows are attached to the document's first revision and shown where they were; the page's own HTML is
attached as its original, and the folder's files no page uses are attached to the first page's document, so
nothing that was given is lost. A link from one page to another of the folder points to that page's document.

A folder is untrusted: scripts, styles and forms are dropped, nothing is fetched from the internet, and only files
inside the folder are read — a path that leaves it ("../") is ignored. The folder comes as files with their paths
in it (the browser's folder picker) or as one .zip.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import unquote, urlsplit

MAX_FILES = 300
MAX_BYTES = 50 * 1024 * 1024
PAGE_EXTENSIONS = (".html", ".htm", ".xhtml")
PICTURES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
            ".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml"}
SKIPPED_TAGS = {"script", "style", "noscript", "template", "iframe", "object", "embed", "head", "select", "button",
                "svg", "canvas", "form"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
             "wbr"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "figure", "figcaption",
              "center", "body", "html", "dl", "dd", "dt", "address", "fieldset", "caption"}


class WebImportError(ValueError):
    pass


# --------------------------------------------------------------------------- the folder

def clean_path(name: str) -> Optional[str]:
    """A file's path inside the folder, or None for one that would leave it."""
    p = (name or "").replace("\\", "/").lstrip("/")
    if not p or any(part in ("..", "") for part in p.split("/")[:-1]) or p.endswith("/"):
        return None
    norm = posixpath.normpath(p)
    return None if norm.startswith("../") or norm == ".." else norm


def folder_from(uploads: list[tuple[str, bytes]]) -> dict[str, bytes]:
    """{path: content}: the files given with their paths, or what one .zip holds. The folder's own name, common
    to every path, is dropped ("PPTDOC/PPT.html" is "PPT.html")."""
    if len(uploads) == 1 and uploads[0][0].lower().endswith(".zip"):
        try:
            z = zipfile.ZipFile(io.BytesIO(uploads[0][1]))
        except zipfile.BadZipFile:
            raise WebImportError("The .zip could not be opened.")
        infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
        if len(infos) > MAX_FILES:
            raise WebImportError(f"The folder has more than {MAX_FILES} files.")
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise WebImportError(f"The folder is larger than {MAX_BYTES // (1024 * 1024)} MB.")
        uploads = [(i.filename, z.read(i)) for i in infos]
    if len(uploads) > MAX_FILES:
        raise WebImportError(f"The folder has more than {MAX_FILES} files.")
    if sum(len(c) for _, c in uploads) > MAX_BYTES:
        raise WebImportError(f"The folder is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    files: dict[str, bytes] = {}
    for name, content in uploads:
        p = clean_path(name)
        if p is None or posixpath.basename(p).startswith("."):
            continue                                           # outside the folder, or .DS_Store and the like
        files[p] = content
    roots = {p.split("/", 1)[0] for p in files}
    if len(roots) == 1 and all("/" in p for p in files):
        root = roots.pop() + "/"
        files = {p[len(root):]: c for p, c in files.items()}
    if not any(p.lower().endswith(PAGE_EXTENSIONS) for p in files):
        raise WebImportError("There is no web page (.html) in the folder.")
    return files


def _decode(content: bytes) -> str:
    head = content[:2048].decode("ascii", errors="ignore")
    m = re.search(r"charset=[\"']?([A-Za-z0-9_\-]+)", head, re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "windows-1252"]:
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- HTML to Markdown

@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class _Tree(HTMLParser):
    """A forgiving tree: unclosed tags are closed by their parent's end, stray end tags ignored."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        node = _Node(tag, {k.lower(): (v or "") for k, v in attrs})
        if tag in ("p", "li", "tr", "td", "th", "dt", "dd"):          # an open one of the same kind ends here
            closes = {"p": ("p",), "li": ("li", "p"), "tr": ("tr", "td", "th", "p"), "td": ("td", "th", "p"),
                      "th": ("td", "th", "p"), "dt": ("dt", "dd", "p"), "dd": ("dt", "dd", "p")}[tag]
            while self.stack[-1].tag in closes and len(self.stack) > 1:
                self.stack.pop()
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), {k.lower(): (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.stack[-1].children.append(data)


@dataclass
class Page:
    path: str
    title: str
    markdown: str                       # pictures as file:<path>, links to pages as page:<path>
    pictures: list[str]
    pages_linked: list[str]
    files_linked: list[str]


class _Render:
    def __init__(self, page_path: str, files: dict[str, bytes]):
        self.base = posixpath.dirname(page_path)
        self.files = files
        self.pictures: list[str] = []
        self.pages: list[str] = []
        self.linked: list[str] = []
        self.first_heading = ""

    def local(self, ref: str) -> Optional[str]:
        """The folder's file a src or href names, if it is one."""
        if not ref:
            return None
        parts = urlsplit(ref.strip())
        if parts.scheme or parts.netloc or not parts.path:
            return None
        p = posixpath.normpath(posixpath.join(self.base, unquote(parts.path)))
        if p.startswith("../"):
            return None
        if p in self.files:
            return p
        lower = {k.lower(): k for k in self.files}                  # exports from Windows mix the case
        return lower.get(p.lower())

    # -- inline

    def inline(self, nodes, pre: bool = False) -> str:
        out = []
        for n in nodes:
            if isinstance(n, str):
                out.append(n if pre else re.sub(r"\s+", " ", n))
                continue
            t = n.tag
            if t in SKIPPED_TAGS or t == "title":
                continue
            if t == "br":
                out.append(BREAK)
            elif t == "img":
                out.append(self.picture(n))
            elif t in ("b", "strong"):
                inner = self.inline(n.children, pre).strip()
                out.append(f" **{inner}** " if inner else " ")
            elif t in ("i", "em", "cite"):
                inner = self.inline(n.children, pre).strip()
                out.append(f" *{inner}* " if inner else " ")
            elif t in ("code", "tt", "kbd", "samp") and not pre:
                inner = self.inline(n.children, True).strip()
                out.append(f" `{inner}` " if inner else " ")
            elif t == "a":
                out.append(self.link(n, pre))
            elif t in ("ul", "ol", "table", "pre", "blockquote") or t in BLOCK_TAGS or re.fullmatch(r"h[1-6]", t):
                out.append(" " + self.inline(n.children, pre) + " ")
            else:
                out.append(self.inline(n.children, pre))
        return "".join(out)

    def picture(self, n: _Node) -> str:
        alt = (n.attrs.get("alt") or "").replace("]", "").replace("[", "").strip()
        p = self.local(n.attrs.get("src", ""))
        if p and posixpath.splitext(p)[1].lower() in PICTURES:
            if p not in self.pictures:
                self.pictures.append(p)
            return f" ![{alt}](file:{p}) "
        return f" {alt} " if alt else " "

    def link(self, n: _Node, pre: bool) -> str:
        text = self.inline(n.children, pre).strip()
        href = (n.attrs.get("href") or "").strip()
        parts = urlsplit(href)
        if parts.scheme in ("http", "https", "mailto") and text:
            return f" [{text}]({href}) "
        p = self.local(href)
        if p and p.lower().endswith(PAGE_EXTENSIONS) and text:
            if p not in self.pages:
                self.pages.append(p)
            return f" [{text}](page:{p}) "
        if p and text:
            if p not in self.linked:
                self.linked.append(p)
            return f" {text} "
        return f" {text} " if text else " "

    # -- blocks

    def blocks(self, nodes, depth: int = 0) -> list[str]:
        out: list[str] = []
        run: list = []                      # inline content between blocks

        def flush():
            text = _tidy(self.inline(run))
            if text:
                out.append(text)
            run.clear()

        for n in nodes:
            if isinstance(n, str) or n.tag not in BLOCK_TAGS | {"ul", "ol", "table", "pre", "blockquote", "hr"} \
                    and not re.fullmatch(r"h[1-6]", n.tag):
                if not (isinstance(n, _Node) and n.tag in SKIPPED_TAGS):
                    run.append(n)
                continue
            flush()
            t = n.tag
            if re.fullmatch(r"h[1-6]", t):
                text = _tidy(self.inline(n.children)).replace("\n", " ")
                if text:
                    self.first_heading = self.first_heading or re.sub(r"[*`]", "", text)
                    out.append("#" * int(t[1]) + " " + text)
            elif t in ("ul", "ol"):
                out.append(self.list(n, depth))
            elif t == "table":
                table = self.table(n)
                if table:
                    out.append(table)
            elif t == "pre":
                code = self.inline(n.children, pre=True).replace(BREAK, "\n").strip("\n")
                if code.strip():
                    out.append("```\n" + code + "\n```")
            elif t == "blockquote":
                inner = "\n\n".join(self.blocks(n.children, depth))
                if inner:
                    out.append("\n".join("> " + line for line in inner.split("\n")))
            elif t == "hr":
                out.append("---")
            else:
                out.extend(self.blocks(n.children, depth))
        flush()
        return [b for b in out if b.strip()]

    def list(self, n: _Node, depth: int) -> str:
        lines, number = [], 0
        for item in n.children:
            if not isinstance(item, _Node):
                continue
            if item.tag in ("ul", "ol"):                         # a list put straight inside a list
                lines.append(self.list(item, depth + 1))
                continue
            if item.tag == "table":                              # an export that puts tables in a list
                table = self.table(item)
                if table:
                    lines.extend("  " * (depth + 1) + "- " + line for line in table.split("\n"))
                continue
            if item.tag != "li":
                continue
            number += 1
            nested = [c for c in item.children if isinstance(c, _Node) and c.tag in ("ul", "ol")]
            own = [c for c in item.children if not (isinstance(c, _Node) and c.tag in ("ul", "ol"))]
            text = _tidy(self.inline(own)).replace("\n", " ")
            marker = f"{number}." if n.tag == "ol" else "-"
            lines.append("  " * depth + f"{marker} {text}".rstrip())
            for sub in nested:
                lines.append(self.list(sub, depth + 1))
        return "\n".join(line for line in lines if line.strip())

    def table(self, n: _Node) -> str:
        rows = []

        def collect(node):
            for c in node.children:
                if isinstance(c, _Node):
                    if c.tag == "tr":
                        rows.append(c)
                    elif c.tag in ("thead", "tbody", "tfoot"):
                        collect(c)
        collect(n)
        cells = [[(c.tag, _tidy(self.inline(c.children)).replace("\n", " ").replace("|", "\\|"))
                  for c in r.children if isinstance(c, _Node) and c.tag in ("td", "th")] for r in rows]
        cells = [r for r in cells if any(text for _, text in r)]
        if not cells:
            return ""
        width = max(len(r) for r in cells)
        headed = any(tag == "th" for tag, _ in cells[0])
        if headed and len(cells) > 1 and width > 1:
            grid = [[text for _, text in r] + [""] * (width - len(r)) for r in cells]
            head, body = grid[0], grid[1:]
            return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * width,
                              *("| " + " | ".join(r) + " |" for r in body)])
        # A layout table (a picture beside its label, as a LabVIEW export makes): one line per row.
        return "\n".join(" ".join(text for _, text in r if text) for r in cells)


BREAK = "\ue000"                # a <br>, until it is written as Markdown's line break ("  " and a new line)


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    out = "\n".join(lines).strip()
    out = re.sub(r"\*\*\s*\*\*", "", out)
    out = re.sub(rf"^[\s{BREAK}]+|[\s{BREAK}]+$", "", out)
    out = re.sub(rf"[ \t]*{BREAK}[ \t]*", "  \n", out)
    return re.sub(r"\n{3,}", "\n\n", out)


def stem(path: str) -> str:
    return posixpath.splitext(posixpath.basename(path))[0]


def convert(path: str, files: dict[str, bytes]) -> Page:
    tree = _Tree()
    tree.feed(_decode(files[path]))
    tree.close()
    r = _Render(path, files)
    markdown = "\n\n".join(r.blocks(tree.root.children)).strip()
    title = re.sub(r"\s+", " ", tree.title).strip() or r.first_heading or stem(path)
    return Page(path=path, title=title[:300], markdown=markdown, pictures=r.pictures, pages_linked=r.pages,
                files_linked=r.linked)


def pages_of(files: dict[str, bytes]) -> list[Page]:
    """Every page of the folder, the main one first (index.html, else the one most linked from the others, else
    by name)."""
    pages = [convert(p, files) for p in sorted(files) if p.lower().endswith(PAGE_EXTENSIONS)]
    linked = {p: sum(p in other.pages_linked for other in pages) for p in (x.path for x in pages)}

    def rank(page: Page):
        name = posixpath.basename(page.path).lower()
        return (name not in ("index.html", "index.htm"), page.path.count("/"), -linked[page.path], page.path)
    return sorted(pages, key=rank)


def unused_files(files: dict[str, bytes], pages: list[Page]) -> list[str]:
    used = {p.path for p in pages}
    for p in pages:
        used.update(p.pictures)
    return [f for f in sorted(files) if f not in used]


def finish(markdown: str, pictures: dict[str, str], documents: dict[str, str]) -> str:
    """The Markdown with its pictures pointing at their attachments and its links at the documents made."""
    def pic(m):
        uid = pictures.get(m.group(2))
        return f"![{m.group(1)}](/v1/attachments/{uid})" if uid else m.group(1)

    def page(m):
        uid = documents.get(m.group(2))
        return f"[{m.group(1)}](/documents/{uid})" if uid else m.group(1)
    out = re.sub(r"!\[([^\]]*)\]\(file:([^)]+)\)", pic, markdown)
    return re.sub(r"\[([^\]]*)\]\(page:([^)]+)\)", page, out)


def mime_of(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    if ext in PICTURES:
        return PICTURES[ext]
    if ext in PAGE_EXTENSIONS:
        return "text/html"
    return {".pdf": "application/pdf", ".txt": "text/plain", ".css": "text/css", ".js": "text/javascript",
            ".csv": "text/csv"}.get(ext, "application/octet-stream")
