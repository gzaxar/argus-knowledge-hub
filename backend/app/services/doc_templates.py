"""Editorial templates for documents reworked from raw text: read, checked and rendered.

A template is Markdown with a YAML front matter. The front matter declares a stable id, a version, the document
type it is for, the fields and sections the reworked document has, and instructions for the assistant. The body
is the document to produce, with placeholders for what was declared, in a small, explicit syntax — nothing in a
template is ever executed:

    {{field:key}}     a declared field's value          {{#field:key}} … {{/field:key}}      only if it has one
    {{section:key}}   a declared section's content      {{#section:key}} … {{/section:key}}  only if it has some
    {{meta:name}}     title, document_date, source_date, event_date, template_id, template_version,
                      reference_notice

Anything else between double braces is an error. Blocks do not nest the same key and must be closed.

ARGUS ships one official template per predefined document type (app/document_templates/*.md); workspaces and
people make variants of them (models/document_template.py). The rules every template is applied under are in
app/document_templates/_common.yaml and are not part of any template: a template cannot change them.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field as dc_field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

DIR = Path(__file__).resolve().parent.parent / "document_templates"
MAX_SOURCE = 64 * 1024
MAX_FRONT = 16 * 1024
MAX_INSTRUCTIONS = 4000
MAX_ITEMS = 40                 # fields + sections
KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TEMPLATE_ID = re.compile(r"^[a-z][a-z0-9-]{1,59}$")
FIELD_TYPES = ("text", "date", "datetime", "person", "people", "number", "enum", "list", "reference")
SECTION_KINDS = ("text", "list", "steps", "table")
META = ("title", "document_date", "source_date", "event_date", "template_id", "template_version",
        "reference_notice")
FRONT_KEYS = {"id", "version", "document_type", "title", "language", "fields", "sections", "instructions",
              "missing_marker", "inferred_marker", "description"}
DEFAULT_MISSING = "[da confermare]"
DEFAULT_INFERRED = "[da verificare]"
TOKEN = re.compile(r"\{\{(.*?)\}\}", re.S)
TOKEN_GRAMMAR = re.compile(r"^(?P<open>[#/])?(?P<kind>field|section|meta):(?P<key>[a-z][a-z0-9_]*)$")


@dataclass
class Field:
    key: str
    label: str
    type: str = "text"
    required: bool = False
    description: str = ""
    options: list = dc_field(default_factory=list)


@dataclass
class Section:
    key: str
    title: str
    kind: str = "text"
    required: bool = False
    description: str = ""
    columns: list = dc_field(default_factory=list)


@dataclass
class Template:
    id: str
    version: int
    document_type: str
    title: str
    language: str
    fields: list[Field]
    sections: list[Section]
    instructions: str
    body: str
    source: str
    missing_marker: str = DEFAULT_MISSING
    inferred_marker: str = DEFAULT_INFERRED
    description: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.source.encode()).hexdigest()

    def field(self, key: str) -> Optional[Field]:
        return next((f for f in self.fields if f.key == key), None)

    def section(self, key: str) -> Optional[Section]:
        return next((s for s in self.sections if s.key == key), None)

    def describe(self) -> dict:
        return {"id": self.id, "version": self.version, "document_type": self.document_type, "title": self.title,
                "language": self.language, "description": self.description,
                "fields": [vars(f) for f in self.fields], "sections": [vars(s) for s in self.sections],
                "instructions": self.instructions, "missing_marker": self.missing_marker,
                "inferred_marker": self.inferred_marker}


@dataclass
class Problem:
    message: str
    line: Optional[int] = None
    severity: str = "error"          # error | warning

    def view(self) -> dict:
        return {"message": self.message, "line": self.line, "severity": self.severity}


class TemplateError(ValueError):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("; ".join(p.message + (f" (line {p.line})" if p.line else "") for p in problems))


# --------------------------------------------------------------------------- reading and checking

def _split(source: str) -> tuple[str, str, int]:
    """(front matter, body, line the body starts on)."""
    if not source.startswith("---"):
        raise TemplateError([Problem("a template starts with a front matter between two lines of ---", 1)])
    lines = source.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), i + 2
    raise TemplateError([Problem("the front matter is not closed by a line of ---", 1)])


def _items(raw, what: str, problems: list[Problem]) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
        problems.append(Problem(f"{what} must be a list of entries like {{key: …, …}}"))
        return []
    return raw


def parse(source: str, *, official_types: Optional[set] = None) -> tuple[Optional[Template], list[Problem]]:
    """The template and what is wrong with it (errors) or worth a look (warnings). None when it has errors."""
    problems: list[Problem] = []
    if len(source.encode()) > MAX_SOURCE:
        return None, [Problem(f"the template is larger than {MAX_SOURCE // 1024} KB")]
    try:
        front, body, body_line = _split(source)
    except TemplateError as e:
        return None, e.problems
    if len(front.encode()) > MAX_FRONT:
        return None, [Problem(f"the front matter is larger than {MAX_FRONT // 1024} KB", 2)]
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        return None, [Problem(f"the front matter is not valid YAML: {getattr(e, 'problem', None) or e}",
                              (mark.line + 2) if mark else None)]
    if not isinstance(meta, dict):
        return None, [Problem("the front matter must be a set of key: value lines", 2)]
    for k in sorted(set(meta) - FRONT_KEYS):
        problems.append(Problem(f"unknown front-matter key {k!r} (allowed: {', '.join(sorted(FRONT_KEYS))})"))

    tid = str(meta.get("id") or "")
    if not TEMPLATE_ID.match(tid):
        problems.append(Problem("id must be lower-case letters, digits and dashes, starting with a letter"))
    version = meta.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append(Problem("version must be a whole number from 1"))
        version = 0
    doc_type = str(meta.get("document_type") or "").strip()
    if not doc_type:
        problems.append(Problem("document_type is required (one of the workspace's document types)"))
    elif official_types is not None and doc_type not in official_types:
        problems.append(Problem(f"document_type {doc_type!r} is not one of {', '.join(sorted(official_types))}"))
    instructions = str(meta.get("instructions") or "").strip()
    if len(instructions) > MAX_INSTRUCTIONS:
        problems.append(Problem(f"instructions are longer than {MAX_INSTRUCTIONS} characters"))

    fields, sections, seen = [], [], set()
    for raw in _items(meta.get("fields"), "fields", problems):
        key = str(raw.get("key") or "")
        if not KEY.match(key):
            problems.append(Problem(f"field key {key!r}: lower-case letters, digits and _, starting with a letter"))
            continue
        if key in seen:
            problems.append(Problem(f"{key!r} is declared twice"))
            continue
        seen.add(key)
        ftype = str(raw.get("type") or "text")
        if ftype not in FIELD_TYPES:
            problems.append(Problem(f"field {key!r}: type {ftype!r} is not one of {', '.join(FIELD_TYPES)}"))
        options = raw.get("options") or []
        if ftype == "enum" and (not isinstance(options, list) or not options):
            problems.append(Problem(f"field {key!r}: an enum needs its options: [a, b, …]"))
        unknown = set(raw) - {"key", "label", "type", "required", "description", "options"}
        if unknown:
            problems.append(Problem(f"field {key!r}: unknown {', '.join(sorted(unknown))}"))
        fields.append(Field(key=key, label=str(raw.get("label") or key), type=ftype, required=bool(raw.get("required")),
                            description=str(raw.get("description") or ""),
                            options=[str(o) for o in options] if isinstance(options, list) else []))
    for raw in _items(meta.get("sections"), "sections", problems):
        key = str(raw.get("key") or "")
        if not KEY.match(key):
            problems.append(Problem(f"section key {key!r}: lower-case letters, digits and _, starting with a letter"))
            continue
        if key in seen:
            problems.append(Problem(f"{key!r} is declared twice"))
            continue
        seen.add(key)
        kind = str(raw.get("kind") or "text")
        if kind not in SECTION_KINDS:
            problems.append(Problem(f"section {key!r}: kind {kind!r} is not one of {', '.join(SECTION_KINDS)}"))
        columns = raw.get("columns") or []
        if kind == "table" and (not isinstance(columns, list) or not 1 <= len(columns) <= 8):
            problems.append(Problem(f"section {key!r}: a table needs columns: [a, b, …] (1 to 8)"))
        unknown = set(raw) - {"key", "title", "kind", "required", "description", "columns"}
        if unknown:
            problems.append(Problem(f"section {key!r}: unknown {', '.join(sorted(unknown))}"))
        sections.append(Section(key=key, title=str(raw.get("title") or key), kind=kind,
                                required=bool(raw.get("required")), description=str(raw.get("description") or ""),
                                columns=[str(c) for c in columns] if isinstance(columns, list) else []))
    if len(fields) + len(sections) > MAX_ITEMS:
        problems.append(Problem(f"at most {MAX_ITEMS} fields and sections together"))
    if not sections:
        problems.append(Problem("a template declares at least one section"))

    fkeys, skeys = {f.key for f in fields}, {s.key for s in sections}
    used: set[tuple[str, str]] = set()
    open_blocks: list[tuple[str, str, int]] = []
    for m in TOKEN.finditer(body):
        line = body_line + body.count("\n", 0, m.start())
        inner = m.group(1).strip()
        g = TOKEN_GRAMMAR.match(inner)
        if not g:
            problems.append(Problem(f"{{{{{inner[:40]}}}}} is not a placeholder: use field:key, section:key or "
                                    "meta:name, or #…/… around a block", line))
            continue
        kind, key, opener = g.group("kind"), g.group("key"), g.group("open")
        if kind == "meta":
            if opener or key not in META:
                problems.append(Problem(f"meta:{key} is not one of {', '.join(META)}" if not opener
                                        else "meta values cannot open a block", line))
            continue
        if key not in (fkeys if kind == "field" else skeys):
            problems.append(Problem(f"{kind}:{key} is not declared in the front matter", line))
            continue
        if opener == "#":
            if any(o[:2] == (kind, key) for o in open_blocks):
                problems.append(Problem(f"block {kind}:{key} is opened inside itself", line))
            open_blocks.append((kind, key, line))
        elif opener == "/":
            if not open_blocks or open_blocks[-1][:2] != (kind, key):
                problems.append(Problem(f"{{{{/{kind}:{key}}}}} closes a block that is not the last one opened",
                                        line))
            else:
                open_blocks.pop()
        else:
            used.add((kind, key))
    for kind, key, line in open_blocks:
        problems.append(Problem(f"block {kind}:{key} is never closed", line))
    for s in sections:
        if ("section", s.key) not in used:
            problems.append(Problem(f"section {s.key!r} is declared but never placed in the body", None,
                                    "error" if s.required else "warning"))
    for f in fields:
        if ("field", f.key) not in used:
            problems.append(Problem(f"field {f.key!r} is declared but never placed in the body", None, "warning"))

    if any(p.severity == "error" for p in problems):
        return None, problems
    return Template(id=tid, version=int(version), document_type=doc_type, title=str(meta.get("title") or tid),
                    language=str(meta.get("language") or "en"), fields=fields, sections=sections,
                    instructions=instructions, body=body, source=source,
                    missing_marker=str(meta.get("missing_marker") or DEFAULT_MISSING)[:40],
                    inferred_marker=str(meta.get("inferred_marker") or DEFAULT_INFERRED)[:40],
                    description=str(meta.get("description") or "")), problems


def load(source: str, **kw) -> Template:
    t, problems = parse(source, **kw)
    if t is None:
        raise TemplateError([p for p in problems if p.severity == "error"])
    return t


# --------------------------------------------------------------------------- the shipped catalogue

@lru_cache(maxsize=1)
def common() -> dict:
    return yaml.safe_load((DIR / "_common.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def official_templates() -> dict[str, Template]:
    """The templates shipped with ARGUS, by document type."""
    from app.services.document_types import DEFAULT_DOCUMENT_TYPES
    types = {name for name, _ in DEFAULT_DOCUMENT_TYPES}
    out = {}
    for path in sorted(DIR.glob("*.md")):
        t = load(path.read_text(encoding="utf-8"), official_types=types)
        out[t.document_type] = t
    return out


def official_by_id(template_id: str) -> Optional[Template]:
    return next((t for t in official_templates().values() if t.id == template_id), None)


# --------------------------------------------------------------------------- rendering

def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def neutralise(text: str) -> str:
    """Text from the source or the model, made inert: braces cannot form a placeholder, and nothing can open
    an HTML comment or a raw block in the rendered document."""
    return (text or "").replace("{{", "{\u200b{").replace("}}", "}\u200b}").replace("<!--", "&lt;!--")


def _mark(item: dict, t: Template) -> str:
    text = neutralise(str(item.get("text") if "text" in item else item.get("value") or "")).strip()
    if item.get("status") == "inferred" and text:
        text += f" {t.inferred_marker}"
    return text


def render_field(t: Template, f: Field, value: Optional[dict]) -> str:
    if not value or value.get("status") == "absent" or value.get("value") in (None, "", []):
        return t.missing_marker if f.required else ""
    v = value.get("value")
    text = ", ".join(neutralise(str(x)) for x in v) if isinstance(v, list) else neutralise(str(v))
    if value.get("status") == "inferred":
        text += f" {t.inferred_marker}"
    return _cell(text)


def render_section(t: Template, s: Section, content: Optional[dict]) -> str:
    items = [i for i in (content or {}).get("items") or [] if i.get("status") != "absent"]
    if not items:
        return t.missing_marker if s.required else ""
    if s.kind == "text":
        return "\n\n".join(_mark(i, t) for i in items)
    if s.kind == "list":
        return "\n".join(f"- {_mark(i, t)}" for i in items)
    if s.kind == "steps":
        return "\n".join(f"{n}. {_mark(i, t)}" for n, i in enumerate(items, 1))
    head = "| " + " | ".join(c.capitalize() for c in s.columns) + " |"
    rule = "|" + "---|" * len(s.columns)
    rows = []
    for i in items:
        cells = i.get("cells") or {}
        row = [_cell(neutralise(str(cells.get(c) or ""))) for c in s.columns]
        if i.get("status") == "inferred":
            row[-1] = (row[-1] + f" {t.inferred_marker}").strip()
        rows.append("| " + " | ".join(row) + " |")
    return "\n".join([head, rule, *rows])


def render(t: Template, extraction: dict, meta: dict) -> str:
    """The template's body with the extraction's values: one pass, so nothing a value contains is read as a
    placeholder. Optional blocks with nothing in them are left out; a required value that is missing is the
    template's missing marker."""
    fields = {f.key: render_field(t, f, (extraction.get("fields") or {}).get(f.key)) for f in t.fields}
    sections = {s.key: render_section(t, s, (extraction.get("sections") or {}).get(s.key)) for s in t.sections}
    metas = {k: neutralise(str(meta.get(k) or "")) for k in META}
    metas["title"] = metas["title"] or t.title
    metas["document_date"] = metas["document_date"] or t.missing_marker
    values = {"field": fields, "section": sections, "meta": metas}

    def filled(kind: str, key: str) -> bool:
        v = values[kind].get(key, "")
        return bool(v) and v != t.missing_marker

    out, skip_until = [], None
    pos = 0
    for m in TOKEN.finditer(t.body):
        g = TOKEN_GRAMMAR.match(m.group(1).strip())
        if g is None:
            continue
        kind, key, opener = g.group("kind"), g.group("key"), g.group("open")
        if skip_until is None:
            out.append(t.body[pos:m.start()])
        pos = m.end()
        if skip_until is not None:
            if opener == "/" and (kind, key) == skip_until:
                skip_until = None
                # The newline after a closing tag belongs to the block.
                if t.body[pos:pos + 1] == "\n":
                    pos += 1
            continue
        if opener == "#":
            if not filled(kind, key):
                skip_until = (kind, key)
            elif t.body[pos:pos + 1] == "\n" and kind == "section":
                pos += 1
            continue
        if opener == "/":
            if t.body[pos:pos + 1] == "\n" and kind == "section":
                pos += 1
            continue
        out.append(values[kind].get(key, ""))
    if skip_until is None:
        out.append(t.body[pos:])
    text = "".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    return text


def lock_lines() -> str:
    """The lines of _lock.yaml for the shipped templates as they are now."""
    return "".join(f"{t.id}: {{version: {t.version}, sha256: {t.sha256}}}\n"
                   for t in sorted(official_templates().values(), key=lambda t: t.id))


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["lock"]:
        head = (DIR / "_lock.yaml").read_text(encoding="utf-8").split("\n# ---\n")[0]
        (DIR / "_lock.yaml").write_text(head.rstrip("\n") + "\n# ---\n" + lock_lines(), encoding="utf-8")
        print(lock_lines(), end="")
