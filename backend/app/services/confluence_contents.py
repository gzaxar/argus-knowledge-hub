"""Render Confluence TOC macros as local Markdown links; no network or database access."""
import re
import unicodedata
import uuid
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote


class _Headings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.level = None
        self.parts = []
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in {"pre", "script", "style"}:
            self.blocked.append(tag)
        if not self.blocked and re.fullmatch(r"h[1-6]", tag):
            self.level, self.parts = int(tag[1]), []

    def handle_endtag(self, tag):
        if self.level and tag == f"h{self.level}":
            self.headings.append((self.level, "".join(self.parts)))
            self.level, self.parts = None, []
        if self.blocked and self.blocked[-1] == tag:
            self.blocked.pop()

    def handle_data(self, data):
        if self.level and not self.blocked:
            self.parts.append(data)


def collect_headings(html: str) -> list[tuple[int, str]]:
    parser = _Headings()
    parser.feed(html)
    parser.close()
    return parser.headings


def heading_slug(text: str) -> str:
    """Match markdownHeadingAnchors.ts: letters/numbers, whitespace, '_' and '-'."""
    text = text.lower().strip()
    text = "".join(c for c in text if unicodedata.category(c)[0] in {"L", "N"}
                   or c.isspace() or c in "_-")
    return re.sub(r"\s", "-", text) or "section"


def toc_placeholder(block: str, slots: dict) -> str:
    options = {}
    for name in ("minLevel", "maxLevel"):
        match = re.search(r'<ac:parameter\b[^>]*ac:name=["\']' + name
                          + r'["\'][^>]*>(.*?)</ac:parameter>', block, re.S | re.I)
        if match:
            raw = unescape(re.sub(r"<[^>]*>", "", match.group(1))).strip()
            if raw.isdigit() and 1 <= int(raw) <= 6:
                options[name] = int(raw)
    marker = "ARGUSCONTENTSMARKER" + uuid.uuid4().hex + "END"
    slots[marker] = options
    return f"<p>{marker}</p>"


def _title_is_already_first(title: str, markdown: str) -> bool:
    line = markdown.lstrip("\r\n").split("\n", 1)[0].rstrip("\r")
    match = re.fullmatch(r" {0,3}#\s+(.+?)(?:\s+#+)?\s*", line)
    return bool(match and re.sub(r"\\([\\`*_{}\[\]<>!|#])", r"\1", unescape(match.group(1))) == title)


def _label(text: str) -> str:
    # One list item per heading; retain its visible wording while escaping Markdown.
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("&", "&amp;")
    return re.sub(r"([\\`*_{}\[\]<>!|])", r"\\\1", text)


def render_contents(markdown: str, slots: dict, headings: list[tuple[int, str]],
                    title: str | None = None) -> str:
    if not slots:
        return markdown
    counts = {}
    if title and not _title_is_already_first(title, markdown):
        # prepare_presentation adds this H1 after conversion. It can have the same
        # slug as a source heading, so reserve its duplicate-heading counter now.
        counts[heading_slug(title)] = 1
    targets = []
    for level, text in headings:
        slug = heading_slug(text)
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchor = "argus-heading-" + slug + (f"-{count}" if count else "")
        targets.append((level, text, anchor))
    for marker, options in slots.items():
        minimum, maximum = options.get("minLevel", 1), options.get("maxLevel", 6)
        eligible = [item for item in targets if minimum <= item[0] <= maximum]
        levels = []
        lines = []
        for level, text, anchor in eligible:
            while levels and levels[-1] >= level:
                levels.pop()
            lines.append("  " * len(levels) + f"- [{_label(text)}](#{quote(anchor, safe='-_')})")
            levels.append(level)
        # Preserve a surrounding quote (e.g. a TOC inside an Info panel).
        pattern = re.compile(r"(?m)^([ \t]*(?:>[ \t]*)*)" + re.escape(marker) + r"[ \t]*$")
        markdown, count = pattern.subn(lambda m: "\n".join(m.group(1) + line for line in lines), markdown)
        if not count:
            markdown = markdown.replace(marker, "\n".join(lines))
    return markdown
