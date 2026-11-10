"""Source-derived summaries and a literal page-title heading; no AI rewriting."""
import re
from html import unescape
from html.parser import HTMLParser


class _IntroParagraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self.parts = None
        self.blocked = []

    def handle_starttag(self, tag, attrs):
        if tag in {"ac:structured-macro", "ac:adf-extension", "pre", "table", "ul", "ol", "script", "style"}:
            self.blocked.append(tag)
        if tag == "p" and not self.blocked:
            self.parts = []
        elif tag == "br" and self.parts is not None and not self.blocked:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "p" and self.parts is not None and not self.blocked:
            text = re.sub(r"\s+", " ", "".join(self.parts)).strip()
            if text:
                self.paragraphs.append(text)
            self.parts = None
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()

    def handle_data(self, data):
        if self.parts is not None and not self.blocked:
            self.parts.append(data)


def source_summary(storage: str, max_chars: int = 480) -> str:
    """Extract opening prose, excluding macros, tables, lists and instructions.

    No new technical assertions are generated. If no suitable prose exists,
    leave the summary empty rather than inventing one from a page title.
    """
    parser = _IntroParagraphs()
    parser.feed(storage or "")
    parser.close()
    candidates = []
    for text in parser.paragraphs:
        if len(text) < 30:
            continue
        if re.search(r"\b(password|credentials?|token|secret|api[ _-]?key)\b", text, re.I):
            continue
        if re.match(r"^(connect|ensure|press|exit|log[ -]?in|open|enter|type|communicate|make sure|turn on|turn off)\b", text, re.I):
            continue
        candidates.append(text)
    if not candidates:
        return ""
    summary = candidates[0]
    # Very short introductions can use the following descriptive paragraph too.
    if len(summary) < 100 and len(candidates) > 1 and len(summary) + len(candidates[1]) + 1 <= max_chars:
        summary += " " + candidates[1]
    if len(summary) > max_chars:
        summary = summary[:max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return summary


def title_heading(title: str, body: str) -> str:
    """Display the source title literally, without duplicate first headings."""
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise ValueError("A non-empty, single-line Confluence page title is required.")
    body = body or ""
    beginning = body.lstrip("\r\n")
    first_line = beginning.split("\n", 1)[0].rstrip("\r")
    match = re.fullmatch(r" {0,3}#\s+(.+?)(?:\s+#+)?\s*", first_line)
    if match:
        visible = re.sub(r"\\([\\`*_{}\[\]<>!|#])", r"\1", unescape(match.group(1)))
        if visible == title:
            return body
    literal = re.sub(r"([\\`*_{}\[\]<>!|#])", r"\\\1", title)
    return f"# {literal}\n\n{beginning}"


def prepare_presentation(title: str, body: str, attributes: dict, storage: str) -> tuple[str, dict]:
    attrs = dict(attributes or {})
    # A manually written summary takes precedence over automatic extraction.
    if not str(attrs.get("argus_summary") or "").strip():
        summary = source_summary(storage)
        if summary:
            attrs["argus_summary"] = summary
    return title_heading(title, body), attrs
