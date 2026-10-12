"""Markdown files, and the images they refer to, as documents.

The unit people actually have is a folder: a handful of `.md` files and an
`images/` beside them. Uploading only the text gives a document whose
figures are all broken links, so the resources come too and the body is
rewritten to point at where they now live — the same rule the Confluence
import follows, for the same reason.

A `.md` file can carry YAML front matter, which is the convention
everywhere else Markdown is kept, so a repository's own metadata (title,
type, keywords) is honoured rather than guessed at.
"""
import io
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.services.confluence_import import choose_document_type
from app.services.document_types import ensure_document_kinds, type_uid
from app.services.drawings import (
    dwg_to_dxf,
    needs_conversion,
    render_sheets,
    sheet_filename,
    sheet_marker,
)

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")

MARKDOWN_SUFFIXES = (".md", ".markdown", ".mdown")

# Anything bigger is not a figure in a procedure.
MAX_RESOURCE_BYTES = 25 * 1024 * 1024

MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".bmp": "image/bmp", ".pdf": "application/pdf", ".csv": "text/csv",
    ".txt": "text/plain", ".json": "application/json",
    ".dwg": "image/vnd.dwg", ".dxf": "image/vnd.dxf",
}

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)

# ![alt](path "title") and [text](path) — the two ways a Markdown body can
# name a file that came with it.
LINK = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)>\s]+)>?(\s+\"[^\"]*\")?\s*\)")


def split_front_matter(text: str) -> tuple[dict, str]:
    """The YAML header of a Markdown file, and the body without it."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        # A malformed header is not a reason to lose the document; it stays
        # part of the body, where a person can see what's wrong with it.
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[match.end():]


def _normalise(path: str) -> str:
    """A path as it would be keyed in the upload, with . and .. resolved."""
    return os.path.normpath(path).replace(os.sep, "/").lstrip("./")


def _is_local(target: str) -> bool:
    """Whether a link points at a file that came with the upload, rather
    than at a URL or an anchor."""
    if not target or target.startswith(("#", "/")):
        return False
    return "://" not in target and not target.startswith("mailto:")


def _by_basename(resources: dict[str, str]) -> dict[str, str]:
    """Resources keyed by filename alone, but only where that filename is
    unambiguous. A browser's multi-file input strips the directory — the
    body still says `images/layout.png` while the upload only knows
    `layout.png` — so matching on the name is what saves those figures.
    Two files with the same name in different folders stay unmatched
    rather than silently picking one.
    """
    seen: dict[str, list[str]] = {}
    for path in resources:
        seen.setdefault(os.path.basename(path).lower(), []).append(path)
    return {name: paths[0] for name, paths in seen.items() if len(paths) == 1}


def resolve_links(body: str, base_dir: str, resources: dict[str, str]) -> tuple[str, set[str]]:
    """Rewrite relative links to the files they now point at here.

    `resources` maps a normalised upload path to its new URL. Returns the
    rewritten body and which resources it used — a link to something that
    wasn't uploaded is left exactly as written, because inventing a URL
    for it would be worse than an honest broken link.
    """
    used: set[str] = set()
    fallback = _by_basename(resources)

    def replace(match: re.Match) -> str:
        bang, text, target, title = match.groups()
        if not _is_local(target):
            return match.group(0)
        from urllib.parse import unquote

        clean = unquote(target.split("#")[0].split("?")[0])
        candidates = [
            _normalise(os.path.join(base_dir, clean)) if base_dir else _normalise(clean),
            _normalise(clean),
        ]
        key = next((c for c in candidates if c in resources), None)
        if key is None:
            key = fallback.get(os.path.basename(clean).lower())
        if key is None:
            return match.group(0)
        used.add(key)
        return f"{bang}[{text}]({resources[key]}{title or ''})"

    return LINK.sub(replace, body), used


def _title_from(body: str, filename: str) -> str:
    """The first heading, or the filename — in that order, because a file
    called `index.md` says nothing and its `# Vacuum recovery` says
    everything."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
        if line.strip():
            break
    stem = os.path.splitext(os.path.basename(filename))[0]
    return stem.replace("-", " ").replace("_", " ").strip() or filename


def _store_resource(db: Session, workspace_id: str, revision_uid: str,
                    filename: str, content: bytes) -> Attachment:
    attachment_uid = str(uuid.uuid4())
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    storage_path = os.path.join(ATTACHMENTS_DIR, attachment_uid)
    with open(storage_path, "wb") as f:
        f.write(content)
    suffix = os.path.splitext(filename)[1].lower()
    attachment = Attachment(
        uid=attachment_uid,
        workspace_id=workspace_id,
        document_revision_uid=revision_uid,
        filename=os.path.basename(filename),
        mime_type=MIME_BY_SUFFIX.get(suffix, "application/octet-stream"),
        file_size=len(content),
        storage_path=storage_path,
    )
    db.add(attachment)
    return attachment


def expand_uploads(files: list[tuple[str, bytes]]) -> dict[str, bytes]:
    """Flatten what was uploaded into path -> bytes.

    A zip is the normal way a folder of Markdown reaches a browser, so it
    is unpacked rather than stored as one opaque file.
    """
    out: dict[str, bytes] = {}
    for name, content in files:
        if name.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(io.BytesIO(content))
            except zipfile.BadZipFile:
                continue
            for member in archive.infolist():
                if member.is_dir():
                    continue
                path = _normalise(member.filename)
                # Never let an archive write outside its own tree.
                if path.startswith("..") or os.path.isabs(member.filename):
                    continue
                if "__MACOSX/" in member.filename or os.path.basename(path).startswith("."):
                    continue
                out[path] = archive.read(member)
        else:
            out[_normalise(name)] = content
    return out


def import_markdown(
    db: Session,
    workspace_id: str,
    files: list[tuple[str, bytes]],
    document_type_uid: Optional[str] = None,
) -> dict:
    """Create a document per Markdown file, with its resources attached.

    Returns counts, and the titles it could not import, so a partial upload
    says which part was partial.
    """
    contents = expand_uploads(files)
    markdown_paths = [p for p in contents if p.lower().endswith(MARKDOWN_SUFFIXES)]

    type_uids = ensure_document_kinds(db, workspace_id)
    db.flush()

    documents = attachments = 0
    skipped: list[str] = []
    created: dict[str, str] = {}  # upload path -> document uid, for cross-links

    for path in sorted(markdown_paths):
        raw = contents[path]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                skipped.append(f"{path}: not readable as text")
                continue

        meta, body = split_front_matter(text)
        title = str(meta.get("title") or _title_from(body, path))
        base_dir = os.path.dirname(path)

        code = str(meta.get("code") or "").strip()
        if not code:
            # Derived from the path so two files called README.md in
            # different folders don't collide.
            code = "MD-" + re.sub(r"[^A-Za-z0-9]+", "-", os.path.splitext(path)[0]).strip("-").upper()
        if db.scalar(select(Document).where(Document.code == code)):
            code = f"{code}-{uuid.uuid4().hex[:6]}"

        keywords = meta.get("keywords") or meta.get("tags") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        kind = str(meta.get("type") or "").strip()
        chosen_type = (
            document_type_uid
            or (type_uids.get(kind) if kind else None)
            or type_uids.get(choose_document_type([str(k) for k in keywords], title))
            or type_uid(workspace_id, "Note")
        )

        document = Document(
            uid=str(uuid.uuid4()),
            workspace_id=workspace_id,
            code=code,
            title=title,
            document_type_uid=chosen_type,
            source="manual",
        )
        db.add(document)
        db.flush()

        revision = DocumentRevision(
            uid=str(uuid.uuid4()),
            document_uid=document.uid,
            revision_number=1,
            state="published",
            body_markdown="",
            attributes={
                "argus_keywords": [str(k) for k in keywords],
                **({"argus_system": str(meta["system"])} if meta.get("system") else {}),
                **({"argus_facility": str(meta["facility"])} if meta.get("facility") else {}),
                **({"argus_document_number": str(meta["document_number"])}
                   if meta.get("document_number") else {}),
            },
            published_at=datetime.now(timezone.utc),
        )
        db.add(revision)
        db.flush()

        # Resources are stored first: the body can only point at a file
        # once that file exists here.
        resources: dict[str, str] = {}
        for candidate, content in contents.items():
            if candidate.lower().endswith(MARKDOWN_SUFFIXES):
                continue
            if len(content) > MAX_RESOURCE_BYTES:
                continue
            resources[candidate] = candidate  # placeholder, replaced below

        rewritten, used = resolve_links(body, base_dir, resources)
        stored: dict[str, str] = {}
        for candidate in sorted(used):
            attachment = _store_resource(
                db, workspace_id, revision.uid, candidate, contents[candidate]
            )
            db.flush()
            stored[candidate] = f"/v1/attachments/{attachment.uid}"
            attachments += 1

            # A drawing referenced by a document gets its viewable sheets
            # here too, for the same reason it does on upload.
            if needs_conversion(candidate):
                dxf, _error = dwg_to_dxf(contents[candidate])
                sheets, _render_error = render_sheets(dxf) if dxf else ([], None)
                for sheet_name, svg in sheets:
                    sheet = _store_resource(
                        db, workspace_id, revision.uid,
                        sheet_filename(candidate, sheet_name), svg,
                    )
                    sheet.mime_type = "image/svg+xml"
                    sheet.backend_id = sheet_marker(attachment.uid)
                    db.flush()
                    attachments += 1

        revision.body_markdown, _ = resolve_links(body, base_dir, stored)
        document.current_revision_uid = revision.uid
        created[path] = document.uid
        documents += 1

    # A link from one uploaded file to another becomes a relation, so a set
    # of pages arrives as the set it was, not as unconnected documents.
    relations = 0
    for path, document_uid in created.items():
        body = contents[path].decode("utf-8", errors="replace")
        _, links = split_front_matter(body)
        for match in LINK.finditer(links):
            target = match.group(3)
            if not _is_local(target) or not target.lower().endswith(MARKDOWN_SUFFIXES):
                continue
            base_dir = os.path.dirname(path)
            resolved = _normalise(os.path.join(base_dir, target.split("#")[0]))
            other = created.get(resolved)
            if not other or other == document_uid:
                continue
            exists = db.scalar(
                select(DocumentRelation).where(
                    DocumentRelation.from_document_uid == document_uid,
                    DocumentRelation.to_type == "document",
                    DocumentRelation.to_uid == other,
                )
            )
            if exists is None:
                db.add(DocumentRelation(
                    workspace_id=workspace_id,
                    from_document_uid=document_uid,
                    to_type="document",
                    to_uid=other,
                    relation_type="references",
                ))
                relations += 1

    db.commit()
    return {
        "documents": documents,
        "attachments": attachments,
        "relations": relations,
        "skipped": skipped,
    }
