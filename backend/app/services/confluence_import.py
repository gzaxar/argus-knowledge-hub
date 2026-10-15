"""Import Confluence pages as documents.

Confluence is a source, like Jira: a page maps onto a Document with a
Revision holding its body, and what Confluence called things is kept as
provenance.

Two details shape the whole importer. Confluence stores pages as its own
XHTML-ish "storage format", not Markdown, so the body has to be converted
or it arrives as a wall of tags nobody can read or retrieve against. And
a page's *version* is the thing that changes: re-importing a page whose
version hasn't moved must not manufacture a new revision, or a document's
history fills with identical entries.
"""
import base64
import binascii
import os
import re
import uuid
from datetime import datetime, timezone
from html import unescape
from typing import Optional
from urllib.parse import parse_qs, unquote_plus, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRelation, DocumentRevision
from app.models.import_job import ImportJob
from app.services.document_types import ensure_document_kinds, type_uid
from app.services.import_merge import effective_strategy
from app.services.jira_import import (
    _TimeoutSession,
    _describe_error,
    _parse_jira_dt,
    _record_diagnostic,
    _set_progress,
)

PAGE_SIZE = 50

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")

# A Confluence label, or a page title prefix, mapped onto one of our
# document types. Checked against labels first, then the title, and
# anything unrecognised becomes a Note rather than being forced into a
# category it doesn't belong to.
LABEL_TO_TYPE = {
    "procedure": "Procedure", "procedura": "Procedure", "sop": "Procedure",
    "work-instruction": "Work Instruction", "istruzione": "Work Instruction",
    "safety": "Safety Document", "sicurezza": "Safety Document",
    "radiation": "Safety Document", "interlock": "Safety Document",
    "specification": "Specification", "specifica": "Specification",
    "requirements": "Specification",
    "design": "Design Report", "design-report": "Design Report",
    "drawing": "Drawing", "disegno": "Drawing",
    "manual": "Manual", "manuale": "Manual",
    "commissioning": "Commissioning Record",
    "test-report": "Test Report", "test": "Test Report", "collaudo": "Test Report",
    "maintenance": "Maintenance Report", "manutenzione": "Maintenance Report",
    "logbook": "Logbook Entry", "elog": "Logbook Entry", "shift": "Logbook Entry",
    "runbook": "Runbook", "troubleshooting": "Runbook",
    "minutes": "Meeting Minutes", "verbale": "Meeting Minutes", "meeting": "Meeting Minutes",
}

TITLE_PREFIX_TO_TYPE = {
    "procedure": "Procedure", "procedura": "Procedure",
    "runbook": "Runbook",
    "minutes": "Meeting Minutes", "verbale": "Meeting Minutes",
    "test report": "Test Report",
    "manual": "Manual", "manuale": "Manual",
}

DEFAULT_TYPE = "Note"

# Confluence stores pages in its own XHTML dialect with <ac:…> and <ri:…>
# macro elements. Those carry the parts a person most needs — code blocks,
# warning panels, links to other pages and to attachments — and an HTML
# converter alone either drops them or renders their raw markup. So the
# macros are turned into ordinary HTML first, and markdownify does the rest
# properly: tables, nested lists and inline formatting are its job, not
# something to re-implement with regexes.

_PANEL_MACROS = {"info": "ℹ️", "note": "📝", "warning": "⚠️", "tip": "💡", "caution": "⚠️"}


def _macro_param(block: str, name: str) -> Optional[str]:
    match = re.search(
        rf'<ac:parameter[^>]*ac:name="{name}"[^>]*>(.*?)</ac:parameter>', block, re.S
    )
    return match.group(1).strip() if match else None


def _macro_body(block: str) -> str:
    match = re.search(
        r"<ac:(?:plain-text-body|rich-text-body)[^>]*>(.*?)</ac:(?:plain-text-body|rich-text-body)>",
        block, re.S,
    )
    if not match:
        return ""
    body = match.group(1)
    return re.sub(r"^<!\[CDATA\[|\]\]>$", "", body.strip())


def _convert_macro(match: re.Match) -> str:
    block = match.group(0)
    name = (match.group(1) or "").lower()
    body = _macro_body(block)

    if name in ("code", "noformat"):
        language = _macro_param(block, "language") or ""
        css = f' class="language-{language}"' if language else ""
        return f"<pre><code{css}>{body}</code></pre>"
    if name in _PANEL_MACROS:
        return f"<blockquote><p>{_PANEL_MACROS[name]} <strong>{name.title()}</strong></p>{body}</blockquote>"
    if name in ("toc", "children", "pagetree", "excerpt-include"):
        # Navigation furniture that means nothing outside Confluence.
        return ""
    if body:
        return body
    # A macro whose content lives only in Confluence — say so rather than
    # leaving a silent hole in the document.
    return f"<p><em>[{name} — see the original page]</em></p>"


# A macro that contains no other macro — so the substitution can work
# innermost-first. A panel wrapping a code block is ordinary in a runbook,
# and matching the outer macro up to the *inner* macro's closing tag threw
# away the code it was wrapping.
_INNERMOST_MACRO = re.compile(
    r'<ac:structured-macro[^>]*ac:name="([^"]+)"'
    r'(?:(?!<ac:structured-macro).)*?</ac:structured-macro>',
    re.S,
)


def _confluence_macros_to_html(storage: str, files: Optional[dict] = None) -> str:
    html = storage
    for _ in range(10):  # nesting this deep is already pathological
        converted = _INNERMOST_MACRO.sub(_convert_macro, html)
        if converted == html:
            break
        html = converted
    html = re.sub(
        r'<ac:structured-macro[^>]*ac:name="([^"]+)"[^>]*/>',
        lambda m: "", html,
    )

    # A link to another page keeps its title; the URL is resolved by
    # whoever reads it, since page ids aren't portable.
    # `.*?` reaches across tags, so a page link would swallow everything
    # from an earlier attachment link up to itself — losing the attachment
    # and merging the two paragraphs. Each span must stop at its own
    # closing tag.
    inside_link = r"(?:(?!</ac:link>).)*?"
    html = re.sub(
        rf'<ac:link[^>]*>{inside_link}<ri:page[^>]*ri:content-title="([^"]+)"[^>]*/>'
        rf'{inside_link}</ac:link>',
        r"<a>\1</a>", html, flags=re.S,
    )
    # Attachments and images. `files` maps a Confluence filename to the URL
    # the file now lives at here; without it the names are kept as text,
    # which is all the converter can honestly do on its own.
    def _attachment_link(match: re.Match) -> str:
        filename = unescape(match.group(1))
        url = (files or {}).get(filename)
        return f'<a href="{url}">{filename}</a>' if url else f"<em>attachment: {filename}</em>"

    def _attachment_image(match: re.Match) -> str:
        filename = unescape(match.group(1))
        url = (files or {}).get(filename)
        if not url:
            return f"<p><em>image: {filename}</em></p>"
        return f'<p><img src="{url}" alt="{filename}" /></p>'

    inside_image = r"(?:(?!</ac:image>).)*?"
    html = re.sub(
        rf'<ac:link[^>]*>{inside_link}<ri:attachment[^>]*ri:filename="([^"]+)"[^>]*/>'
        rf'{inside_link}</ac:link>',
        _attachment_link, html, flags=re.S,
    )
    html = re.sub(
        rf'<ac:image[^>]*>{inside_image}<ri:attachment[^>]*ri:filename="([^"]+)"[^>]*/?>'
        rf'{inside_image}</ac:image>',
        _attachment_image, html, flags=re.S,
    )
    # An image hosted elsewhere keeps its own URL.
    html = re.sub(
        rf'<ac:image[^>]*>{inside_image}<ri:url[^>]*ri:value="([^"]+)"[^>]*/?>'
        rf'{inside_image}</ac:image>',
        lambda m: f'<p><img src="{unescape(m.group(1))}" alt="" /></p>', html, flags=re.S,
    )
    html = re.sub(r"<ac:image[^>]*>.*?</ac:image>", "<p><em>image</em></p>", html, flags=re.S)
    # Whatever ac:/ri: markup is left would otherwise reach the reader raw.
    html = re.sub(r"</?(?:ac|ri):[^>]*>", "", html)
    return html


def _code_language(pre_element) -> str:
    code = pre_element.find("code") if hasattr(pre_element, "find") else None
    classes = (code.get("class") if code is not None else None) or []
    for name in classes:
        if name.startswith("language-"):
            return name.replace("language-", "")
    return ""


def storage_to_markdown(storage: str, files: Optional[dict] = None) -> str:
    """A Confluence page as Markdown.

    Macros become ordinary HTML first (above), then markdownify does the
    conversion — tables, nested lists and inline formatting are exactly the
    parts that are tedious and easy to get subtly wrong by hand.

    `files` maps each attached filename to the URL it now has here, so
    images and file links point at something real instead of naming a file
    the reader has no way to open.
    """
    if not storage:
        return ""
    from markdownify import markdownify

    html = _confluence_macros_to_html(storage, files)
    text = markdownify(
        html,
        heading_style="ATX",       # "## Heading", matching everything else here
        bullets="-",
        # markdownify hands this the <pre>; the language is on the <code>
        # inside it, which is where the macro conversion put it.
        code_language_callback=_code_language,
        # Equipment names are full of * and _; escaping them makes the text
        # harder to read without making it any safer.
        escape_asterisks=False,
        escape_underscores=False,
    )
    text = unescape(text)
    # markdownify is generous with blank lines around block elements.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def choose_document_type(labels: list[str], title: str) -> str:
    for label in labels:
        mapped = LABEL_TO_TYPE.get(label.strip().lower())
        if mapped:
            return mapped
    lowered = (title or "").strip().lower()
    for prefix, mapped in TITLE_PREFIX_TO_TYPE.items():
        if lowered.startswith(prefix):
            return mapped
    return DEFAULT_TYPE


def _person(value) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    return value.get("displayName") or value.get("publicName") or value.get("username")


# Confluence keeps shift reports and news as blogposts, not pages. A wiki
# import that only asks for "page" silently leaves out an entire category
# of operational record.
CONTENT_TYPES = ("page", "blogpost")


def _fetch_pages(session, base_url: str, space_key: Optional[str], cql: Optional[str],
                 start: int, content_type: str = "page") -> dict:
    params = {
        "limit": PAGE_SIZE,
        "start": start,
        # body.storage is the page itself; the rest is what makes it
        # placeable and attributable.
        "expand": "body.storage,version,space,metadata.labels,history,ancestors",
    }
    if cql:
        params["cql"] = cql
        url = f"{base_url}/rest/api/content/search"
    else:
        params["type"] = content_type
        if space_key:
            params["spaceKey"] = space_key
        url = f"{base_url}/rest/api/content"
    resp = session.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def _has_more(payload: dict, received: int) -> bool:
    """Whether another page of results exists.

    `size` on /rest/api/content is the number of results *in this response*,
    not the total — only the CQL search endpoint returns `totalSize`. Reading
    `size` as a total makes the first response look like the whole library,
    which is why an import used to stop dead at the first 50 pages. The
    authority is the `next` link, and the result count as a fallback.
    """
    if (payload.get("_links") or {}).get("next"):
        return True
    total = payload.get("totalSize")
    if isinstance(total, int):
        return received < total
    return len(payload.get("results") or []) == PAGE_SIZE


def _fetch_attachments(session, base_url: str, page_id: str) -> tuple[list[dict], Optional[str]]:
    """Every file attached to a page, and the host the download links hang
    off. Paginated like everything else — a page with more than fifty images
    is unusual but not impossible."""
    out: list[dict] = []
    link_base: Optional[str] = None
    start = 0
    while True:
        resp = session.get(
            f"{base_url}/rest/api/content/{page_id}/child/attachment",
            params={"limit": PAGE_SIZE, "start": start, "expand": "version"},
        )
        if resp.status_code == 404:
            return out, link_base
        resp.raise_for_status()
        payload = resp.json()
        link_base = link_base or (payload.get("_links") or {}).get("base")
        results = payload.get("results") or []
        out.extend(results)
        start += len(results)
        if not results or not _has_more(payload, start):
            return out, link_base


# Files this large are almost always a video or a disk image someone parked
# on a wiki page; copying them into the hub costs more than it returns.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _note(job, seen: Optional[set], category: str, detail: str) -> None:
    """Record a warning against the run, and never let recording one become
    the failure. A file that can't be fetched is a note on an otherwise
    good import; raising here threw away the whole run over one attachment.
    """
    if job is None:
        return
    try:
        _record_diagnostic(job, seen if seen is not None else set(), category, detail)
    except Exception:
        pass


def _existing_attachments(db: Session, document_uid: str) -> dict[str, Attachment]:
    """Files already copied for this document, by their source identity.

    A new revision of a page must not re-download every image on it — the
    files are unchanged, and only the ones Confluence says have a new
    version need fetching again.
    """
    rows = db.scalars(
        select(Attachment)
        .join(DocumentRevision, DocumentRevision.uid == Attachment.document_revision_uid)
        .where(DocumentRevision.document_uid == document_uid,
               Attachment.backend_id.is_not(None))
    ).all()
    return {row.backend_id: row for row in rows}


def _import_attachments(db: Session, session, base_url: str, workspace_id: str,
                        document_uid: str, revision_uid: str, page_id: str,
                        job=None, seen: Optional[set] = None) -> tuple[dict[str, str], int]:
    """Copy a page's files in, and say where each one now lives.

    Returns filename -> URL, which is what turns `<ac:image>` into an image
    the reader can actually see rather than the name of a file they cannot
    open.
    """
    try:
        results, link_base = _fetch_attachments(session, base_url, page_id)
    except Exception as e:
        _note(job, seen, "attachment_list", f"page {page_id}: {_describe_error(e, None)}")
        return {}, 0

    already = _existing_attachments(db, document_uid)
    files: dict[str, str] = {}
    copied = 0

    for item in results:
        filename = item.get("title") or item.get("id")
        source_id = str(item.get("id") or "")
        version = ((item.get("version") or {}).get("number")) or 1
        if not filename or not source_id:
            continue
        identity = f"confluence:{source_id}:v{version}"

        existing = already.get(identity)
        if existing is not None:
            files[filename] = f"/v1/attachments/{existing.uid}"
            continue

        download = ((item.get("_links") or {}).get("download")) or ""
        if not download:
            continue
        url = download if download.startswith("http") else f"{link_base or base_url}{download}"
        try:
            resp = session.get(url)
            resp.raise_for_status()
            content = resp.content
        except Exception as e:
            _note(job, seen, "attachment_download",
                  f"{filename} on page {page_id}: {_describe_error(e, None)}")
            continue

        if len(content) > MAX_ATTACHMENT_BYTES:
            _note(job, seen, "attachment_too_large",
                  f"{filename} is {len(content) // (1024 * 1024)} MB, over the "
                  f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit; it stays on Confluence.")
            continue

        attachment_uid = str(uuid.uuid4())
        os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
        storage_path = os.path.join(ATTACHMENTS_DIR, attachment_uid)
        with open(storage_path, "wb") as f:
            f.write(content)

        db.add(Attachment(
            uid=attachment_uid,
            workspace_id=workspace_id,
            document_revision_uid=revision_uid,
            filename=filename,
            mime_type=((item.get("metadata") or {}).get("mediaType"))
            or resp.headers.get("Content-Type"),
            file_size=len(content),
            author=_person(((item.get("version") or {}).get("by"))),
            storage_path=storage_path,
            backend_id=identity,
            backend_url=url,
        ))
        files[filename] = f"/v1/attachments/{attachment_uid}"
        copied += 1

    return files, copied


# Where a page link's path starts after the server's own context path.
_LINK_MARKERS = ("/x/", "/pages/", "/display/", "/spaces/")


class PageLinkError(ValueError):
    pass


def tiny_link_page_id(code: str) -> str:
    """The page id in a short link (/x/YwX6AQ): Confluence writes the id's bytes,
    least significant first, in base64 with - for / and _ for +, without the
    trailing zero bytes."""
    text = code.replace("-", "/").replace("_", "+")
    text += "A" * (-len(text) % 4)
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        raise PageLinkError(f"“{code}” is not a Confluence short link.")
    page_id = int.from_bytes(raw, "little")
    if page_id <= 0:
        raise PageLinkError(f"“{code}” is not a Confluence short link.")
    return str(page_id)


def parse_page_link(link: str) -> dict:
    """A link to one Confluence page, as the browser or the Share button gives it:
    the short link (…/x/YwX6AQ), …/pages/viewpage.action?pageId=…,
    …/spaces/KEY/pages/123/Title, or …/display/KEY/Title. Says the server (with
    its context path) and the page: its id, or its space and title."""
    parsed = urlparse((link or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PageLinkError("A page link starts with https:// and names the Confluence server.")
    path = parsed.path
    cut = min((i for i in (path.find(m) for m in _LINK_MARKERS) if i >= 0), default=-1)
    if cut < 0:
        raise PageLinkError("This is not a link to a Confluence page: copy it from the page, "
                            "or from its Share button.")
    base = f"{parsed.scheme}://{parsed.netloc}{path[:cut]}"
    rest = [p for p in path[cut:].split("/") if p]
    query = parse_qs(parsed.query)
    if rest[0] == "x" and len(rest) > 1:
        return {"base_url": base, "page_id": tiny_link_page_id(rest[1]), "short": rest[1]}
    if rest[0] == "pages" and query.get("pageId"):
        page_id = query["pageId"][0]
    elif rest[0] == "pages" and query.get("spaceKey") and query.get("title"):
        return {"base_url": base, "space": query["spaceKey"][0], "title": query["title"][0]}
    elif rest[0] == "spaces" and len(rest) > 3 and rest[2] == "pages":
        page_id = rest[3]
    elif rest[0] == "display" and len(rest) > 2:
        return {"base_url": base, "space": rest[1], "title": unquote_plus(rest[2])}
    else:
        raise PageLinkError("This link does not name a page: copy it from the page, or from its "
                            "Share button.")
    if not page_id.isdigit():
        raise PageLinkError(f"“{page_id}” is not a Confluence page id.")
    return {"base_url": base, "page_id": page_id}


def resolve_page(session, base_url: str, link: dict) -> tuple[str, str]:
    """The id and title of the page a parsed link names, read from the server so a
    link the account cannot open says so before anything is imported."""
    def refused(resp) -> RuntimeError:
        if resp.status_code in (401, 403):
            return RuntimeError("Confluence refused the token for this page: check the personal access "
                                "token, and that its account can open the page.")
        return RuntimeError(f"The linked page was not found ({_describe_error(None, resp)}).")

    if "page_id" in link:
        resp = session.get(f"{base_url}/rest/api/content/{link['page_id']}")
        if resp.status_code == 200:
            page = resp.json()
            return str(page["id"]), page.get("title") or ""
        if "short" not in link or resp.status_code in (401, 403):
            raise refused(resp)
        # A short link the decoding got wrong: the server knows where it leads.
        hop = session.get(f"{base_url}/x/{link['short']}", allow_redirects=True)
        try:
            target = parse_page_link(hop.url)
        except PageLinkError:
            raise refused(resp)
        if target.get("short") or target == link:
            raise refused(resp)
        return resolve_page(session, base_url, target)
    resp = session.get(f"{base_url}/rest/api/content",
                       params={"spaceKey": link["space"], "title": link["title"], "type": "page"})
    if resp.status_code != 200:
        raise refused(resp)
    results = resp.json().get("results") or []
    if not results:
        raise RuntimeError(f"No page “{link['title']}” in the space {link['space']}, or the token's "
                           "account cannot see it.")
    return str(results[0]["id"]), results[0].get("title") or link["title"]


def resolve_api_base(session, base_url: str) -> str:
    """Confluence Server is often published under /confluence or /wiki, and
    the site root answers with a normal page either way — so a wrong base
    shows up as a 404 from the API and nothing more helpful."""
    tried = []
    for suffix in ("", "/confluence", "/wiki"):
        candidate = f"{base_url}{suffix}"
        url = f"{candidate}/rest/api/space"
        tried.append(url)
        try:
            resp = session.get(url, params={"limit": 1})
        except Exception:
            continue
        if resp.status_code == 404:
            continue
        if resp.status_code < 500:
            return candidate
    raise RuntimeError(
        "No Confluence REST API found. Tried: " + ", ".join(tried) +
        ". Check the server URL — Confluence is often published under a "
        "context path such as /confluence or /wiki rather than the site root."
    )


def _find_or_create_document(db: Session, workspace_id: str, space: Optional[str],
                            page_id: str, title: str) -> tuple[Document, str]:
    """The document this page maps to, creating it if new.

    Document codes are unique across the whole installation, not per
    workspace, so the readable "CONF-LNF-101" can only belong to one
    workspace. Two workspaces importing the same space is a legitimate
    thing to do — the second gets a qualified code rather than silently
    skipping the page, which is what happened before.
    """
    preferred = f"CONF-{space or 'X'}-{page_id}"
    existing = db.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.code.in_([preferred, f"{preferred}-{workspace_id}"]),
        )
    )
    if existing is not None:
        return existing, existing.code

    taken = db.scalar(select(Document).where(Document.code == preferred))
    code = preferred if taken is None else f"{preferred}-{workspace_id}"

    document = Document(
        uid=str(uuid.uuid4()),
        workspace_id=workspace_id,
        code=code,
        title=title,
        source="confluence",
    )
    db.add(document)
    db.flush()
    return document, code


def run_confluence_import(
    job_uid: str,
    workspace_id: str,
    base_url: str,
    pat: str,
    space_key: Optional[str] = None,
    cql: Optional[str] = None,
    merge_strategy: str = "override",
    link_assets: bool = True,
    page_url: Optional[str] = None,
    include_children: bool = True,
) -> None:
    """`page_url` imports one page (and, with `include_children`, every page under
    it) instead of a space or a CQL query; the server comes from the link when
    `base_url` is empty."""
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    seen: set = set()

    try:
        link = parse_page_link(page_url) if page_url else None
        base_url = (base_url or (link or {}).get("base_url") or "").rstrip("/")
        session = _TimeoutSession()
        session.headers.update({"Authorization": f"Bearer {pat}", "Accept": "application/json"})

        resolved = resolve_api_base(session, base_url)
        if resolved != base_url:
            _set_progress(db, job, f"Confluence API found at {resolved}")
        base_url = resolved

        if link is not None:
            root_id, root_title = resolve_page(session, base_url, link)
            space_key = None
            cql = f"id = {root_id} or ancestor = {root_id}" if include_children else f"id = {root_id}"
            _set_progress(db, job, f"The page “{root_title}” ({root_id})"
                                   + (" and the pages under it" if include_children else ""))

        type_uids = ensure_document_kinds(db, workspace_id)
        db.commit()

        # Asset keys mentioned in a page body become links, the same way
        # they do for tickets — a procedure that names a magnet should be
        # findable from that magnet.
        from app.models.asset import Asset

        key_to_asset = dict(
            db.execute(
                select(Asset.key, Asset.uid).where(Asset.workspace_id == workspace_id)
            ).all()
        ) if link_assets else {}
        key_pattern = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")

        merge_strategy, retired = effective_strategy(merge_strategy)
        if retired:
            _set_progress(db, job, retired)

        imported = updated = skipped = links = 0
        attachments_copied = 0
        # Page ids seen this run, so the wiki's own tree can be rebuilt at
        # the end: a child page is imported before or after its parent
        # depending only on result order, so the links can't be made inline.
        document_by_page: dict[str, str] = {}
        parent_of_page: dict[str, str] = {}

        # With CQL the query itself decides what is returned; otherwise both
        # kinds of content are fetched, since a wiki keeps shift reports and
        # announcements as blogposts rather than pages.
        passes = ("page",) if cql else CONTENT_TYPES

        for content_type in passes:
            start = 0
            announced = False

            while True:
                try:
                    payload = _fetch_pages(session, base_url, space_key, cql, start, content_type)
                except Exception as e:
                    raise RuntimeError(
                        f"Confluence search failed: {_describe_error(e, None)}"
                    ) from e

                results = payload.get("results") or []
                if not announced:
                    announced = True
                    reported = payload.get("totalSize")
                    label = "result" if cql else content_type
                    _set_progress(
                        db, job,
                        f"{reported} {label}(s) to import" if isinstance(reported, int)
                        else f"Importing {label}s",
                    )
                if not results:
                    break

                for page in results:
                    page_id = str(page.get("id") or "")
                    title = page.get("title") or f"Untitled {page_id}"
                    if not page_id:
                        continue

                    version = ((page.get("version") or {}).get("number")) or 1
                    labels = [
                        label.get("name")
                        for label in (((page.get("metadata") or {}).get("labels") or {}).get("results") or [])
                        if label.get("name")
                    ]
                    space = ((page.get("space") or {}).get("key"))
                    body = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
                    web_url = f"{base_url}/pages/viewpage.action?pageId={page_id}"
                    ancestors = page.get("ancestors") or []
                    parent_id = str(ancestors[-1].get("id")) if ancestors else None

                    document, code = _find_or_create_document(
                        db, workspace_id, space, page_id, title
                    )
                    is_new = document.current_revision_uid is None
                    document_by_page[page_id] = document.uid
                    if parent_id:
                        parent_of_page[page_id] = parent_id

                    document.title = title
                    kind = choose_document_type(labels, title)
                    document.document_type_uid = type_uids.get(kind) or type_uid(workspace_id, kind)

                    attributes = {
                        "argus_source": "confluence",
                        "argus_source_id": page_id,
                        "argus_source_url": web_url,
                        "argus_source_space": space,
                        "argus_source_version": version,
                        "argus_source_updated": ((page.get("version") or {}).get("when")),
                        "argus_source_author": _person((page.get("version") or {}).get("by")),
                        "argus_keywords": labels,
                    }

                    current = (
                        db.get(DocumentRevision, document.current_revision_uid)
                        if document.current_revision_uid else None
                    )
                    # The page's version is what says whether anything changed.
                    # Without this check every re-import would add a revision
                    # identical to the last one.
                    if current is not None and (current.attributes or {}).get(
                        "argus_source_version"
                    ) == version:
                        skipped += 1
                        continue

                    revision = DocumentRevision(
                        uid=str(uuid.uuid4()),
                        document_uid=document.uid,
                        revision_number=(current.revision_number + 1) if current else 1,
                        # Imported pages arrive published: they are already in
                        # use at the source, and parking them in "draft" would
                        # hide the entire library behind a review that nobody
                        # asked for.
                        state="published",
                        body_markdown="",
                        attributes=attributes,
                        published_at=_parse_jira_dt((page.get("version") or {}).get("when")),
                    )
                    db.add(revision)
                    db.flush()

                    # The files have to exist before the body is converted:
                    # an image is only worth importing if the text can point
                    # at the copy that now lives here.
                    files, copied = _import_attachments(
                        db, session, base_url, workspace_id,
                        document.uid, revision.uid, page_id, job, seen,
                    )
                    attachments_copied += copied
                    markdown = storage_to_markdown(body, files)
                    revision.body_markdown = markdown

                    if current is not None:
                        current.state = "superseded"
                        current.superseded_by_uid = revision.uid
                    document.current_revision_uid = revision.uid

                    if is_new:
                        imported += 1
                    else:
                        updated += 1

                    if link_assets and markdown:
                        for candidate in set(key_pattern.findall(f"{title}\n{markdown}")):
                            asset_uid = key_to_asset.get(candidate)
                            if not asset_uid:
                                continue
                            exists = db.scalar(
                                select(DocumentRelation).where(
                                    DocumentRelation.from_document_uid == document.uid,
                                    DocumentRelation.to_type == "asset",
                                    DocumentRelation.to_uid == asset_uid,
                                )
                            )
                            if exists is None:
                                db.add(DocumentRelation(
                                    workspace_id=workspace_id,
                                    from_document_uid=document.uid,
                                    to_type="asset",
                                    to_uid=asset_uid,
                                    relation_type="describes",
                                ))
                                links += 1

                    if (imported + updated) % 25 == 0:
                        db.commit()
                        _set_progress(db, job, f"{imported + updated} document(s) so far")

                db.commit()
                start += len(results)
                if not _has_more(payload, start):
                    break

        # The wiki's own hierarchy, rebuilt once every page has a document.
        tree_links = 0
        for page_id, parent_id in parent_of_page.items():
            child_uid = document_by_page.get(page_id)
            parent_uid = document_by_page.get(parent_id)
            if not child_uid or not parent_uid or child_uid == parent_uid:
                continue
            exists = db.scalar(
                select(DocumentRelation).where(
                    DocumentRelation.from_document_uid == child_uid,
                    DocumentRelation.to_type == "document",
                    DocumentRelation.to_uid == parent_uid,
                    DocumentRelation.relation_type == "child_of",
                )
            )
            if exists is None:
                db.add(DocumentRelation(
                    workspace_id=workspace_id,
                    from_document_uid=child_uid,
                    to_type="document",
                    to_uid=parent_uid,
                    relation_type="child_of",
                ))
                tree_links += 1
        db.commit()

        _set_progress(
            db, job,
            f"Imported {imported} new and updated {updated} document(s)",
            documents=imported, documents_updated=updated,
            documents_unchanged=skipped, asset_links=links,
            attachments=attachments_copied, page_tree_links=tree_links,
        )

        job.status = "succeeded"
        job.progress = "Import complete"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.get(ImportJob, job_uid)
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
