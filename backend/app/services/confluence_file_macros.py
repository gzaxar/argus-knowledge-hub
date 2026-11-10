"""Convert file-viewer macros to ordinary links to files already imported."""
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote
from collections import Counter
import re


FILE_VIEWER_MACROS = frozenset({"view-file", "viewpdf", "viewdoc", "viewppt", "viewxls"})


class _References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "ri:attachment":
            values = dict(attrs)
            self.current = {"filename": values.get("ri:filename") or "", "external": False}
            self.references.append(self.current)
        elif tag == "ri:page" and self.current is not None:
            self.current["external"] = True

    def handle_endtag(self, tag):
        if tag == "ri:attachment":
            self.current = None


def render_file_macro(block: str, name: str, files: dict | None = None) -> str:
    """Use exact filenames, including entity/URL decoding, without guessing IDs.

    A nested ri:page refers to another page's attachment. The current files map
    has no page provenance, so it must not resolve that reference by basename.
    """
    parser = _References()
    parser.feed(block)
    parser.close()
    if not parser.references:
        return f"<p><em>[{escape(name)} — no attachment reference found; see the original page]</em></p>"
    output = []
    seen = set()
    for ref in parser.references:
        filename = ref["filename"]
        key = (filename, ref["external"])
        if key in seen:
            continue
        seen.add(key)
        if not filename:
            output.append("<p><em>[File viewer — missing filename; see the original page]</em></p>")
            continue
        if ref["external"]:
            output.append(f"<p><em>Attachment on another Confluence page: {escape(filename)} — see the original page</em></p>")
            continue
        resolved = filename
        if resolved not in (files or {}):
            resolved = unquote(filename)
        url = (files or {}).get(resolved)
        if url:
            output.append(f'<p><a href="{escape(str(url), quote=True)}">{escape(resolved)}</a></p>')
        else:
            output.append(f"<p><em>Attachment not imported: {escape(filename)} — see the original page</em></p>")
    return "".join(output)


def replace_file_viewer_placeholders(body: str, replacements: list[tuple[str, str]]) -> str:
    """Replace only old markers, preserving all surrounding ARGUS wording.

    Source order determines which same-kind placeholder belongs to which macro.
    Refuse a count mismatch instead of guessing after local document edits.
    """
    patterns = {}
    for name, count in Counter(name for name, _ in replacements).items():
        pattern = re.compile(
            r"(?P<wrap>\*{1,2}|_{1,2})?\\?\[" + re.escape(name)
            + r"\s+[—-]\s+see the original page\\?\](?(wrap)(?P=wrap))"
        )
        if len(list(pattern.finditer(body))) != count:
            raise ValueError(f"Cannot match {name} placeholders to the source macros. Review this document manually.")
        patterns[name] = pattern
    for name, markdown in replacements:
        body = patterns[name].sub(lambda match: markdown, body, count=1)
    return body
