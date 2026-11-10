"""One-document repair: preview by default; apply creates or repairs a draft.

Run inside the local ARGUS backend environment, never against a production DB
merely to test this update. No token or full document body is printed.
"""
import argparse
from copy import deepcopy
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.import_config import ImportConfig
from app.services.crypto import decrypt_secret
from app.services.confluence_import import (
    _INNERMOST_MACRO, _TimeoutSession, configure_confluence_session, confluence_json,
    parse_page_link, resolve_api_base, storage_to_markdown,
)
from app.services.confluence_presentation import prepare_presentation
from app.services.confluence_file_macros import (
    FILE_VIEWER_MACROS, render_file_macro, replace_file_viewer_placeholders,
)


def repair(workspace: str, page_id: str, config_name: str | None = None, apply: bool = False,
           use_existing_draft: bool = False, presentation_only: bool = False) -> None:
    if not page_id.isdigit():
        raise ValueError("The source page ID must contain digits only.")
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Document, DocumentRevision)
            .join(DocumentRevision, Document.current_revision_uid == DocumentRevision.uid)
            .where(Document.workspace_id == workspace, Document.source == "confluence",
                   DocumentRevision.attributes["argus_source_id"].as_string() == page_id)
        ).all()
        if len(rows) != 1:
            raise ValueError("Expected exactly one published Confluence document with that source page ID in this workspace.")
        document, current = rows[0]
        if current.state != "published":
            raise ValueError("This command repairs a published imported revision by creating a new draft.")
        doc_uid, current_uid = document.uid, current.uid
        published_body = current.body_markdown or ""
        opened = db.scalars(select(DocumentRevision).where(
            DocumentRevision.document_uid == doc_uid,
            DocumentRevision.state.in_(("draft", "in_review", "approved")),
        )).all()
        if len(opened) > 1:
            raise ValueError("Multiple open revisions found. Review this document manually.")
        existing = opened[0] if opened else None
        if existing is not None:
            print(f"Existing open revision: {existing.uid}, state={existing.state}")
            if existing.state != "draft":
                raise ValueError("The open revision is in review or approved. Use ARGUS's normal workflow to return it to Draft before repairing.")
            if not use_existing_draft:
                raise ValueError("An editable draft already exists. Repeat with --use-existing-draft to repair only its file links.")
        elif use_existing_draft:
            raise ValueError("No editable draft exists. Repeat without --use-existing-draft to create one.")
        target_uid = existing.uid if existing is not None else None
        old_body = (existing.body_markdown or "") if existing is not None else published_body
        # Source identity comes from the published import. Any source-version
        # metadata explicitly present on a local draft must agree with it.
        if existing is not None:
            for key in ("argus_source_id", "argus_source_version"):
                value = (existing.attributes or {}).get(key)
                original = (current.attributes or {}).get(key)
                if value is not None and str(value) != str(original):
                    raise ValueError("The draft's source metadata differs from the published import. Review it manually.")
        source_version = (current.attributes or {}).get("argus_source_version")
        source_url = (current.attributes or {}).get("argus_source_url") or ""
        source_base = parse_page_link(source_url)["base_url"]
        host = urlparse(source_base).hostname

        configs = db.scalars(select(ImportConfig).where(
            ImportConfig.workspace_id == workspace, ImportConfig.source == "confluence"
        )).all()
        matching = []
        for config in configs:
            params = config.params or {}
            address = params.get("base_url") or params.get("page_url") or ""
            if urlparse(address).hostname == host and (not config_name or config.name == config_name):
                matching.append(config)
        if len(matching) != 1:
            raise ValueError("Expected one saved Confluence configuration for this site. Specify --config-name with its exact name.")
        config = matching[0]
        params = config.params or {}
        token = decrypt_secret(config.encrypted_secret) if config.encrypted_secret else ""
        files = {}
        if not presentation_only:
            attachments = db.scalars(
                select(Attachment).join(DocumentRevision, Attachment.document_revision_uid == DocumentRevision.uid)
                .where(DocumentRevision.document_uid == doc_uid, Attachment.workspace_id == workspace)
                .order_by(DocumentRevision.revision_number.desc(), Attachment.created_at.desc())
            ).all()
            for attachment in attachments:
                files.setdefault(attachment.filename, f"/v1/attachments/{attachment.uid}")
            if not files:
                raise ValueError("This document has no stored attachments to link.")

        session = _TimeoutSession()
        try:
            base = configure_confluence_session(session, params.get("base_url") or source_base,
                                                token, params.get("auth_mode", "pat"), params.get("email", ""))
            base = resolve_api_base(session, base)
            response = session.get(f"{base}/rest/api/content/{page_id}", params={"expand": "body.storage,version"})
            page = confluence_json(response)
        finally:
            session.close()
        if str(page.get("id")) != page_id or str((page.get("version") or {}).get("number")) != str(source_version):
            raise ValueError("The source page/version differs from the imported revision. Review the source update separately.")
        storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
        if presentation_only:
            source_title = page.get("title")
            target_attrs = (existing.attributes if existing is not None else current.attributes) or {}
            new_body, planned_attrs = prepare_presentation(source_title, old_body, target_attrs, storage)
            if new_body == old_body and planned_attrs == target_attrs:
                print("The source title and summary are already present, or no suitable summary prose exists. No data changed.")
                return
        else:
            replacements = []
            for match in _INNERMOST_MACRO.finditer(storage):
                name = match.group(1).lower()
                if name not in FILE_VIEWER_MACROS:
                    continue
                html = render_file_macro(match.group(0), name, files)
                if '<a href="/v1/attachments/' not in html or "Attachment not imported:" in html or "Attachment on another" in html:
                    raise ValueError("A file viewer cannot be matched to this document's stored files. Review its source attachment.")
                replacements.append((name, storage_to_markdown(match.group(0), files).strip()))
            if not replacements:
                raise ValueError("No supported file-viewer macros found in the source page.")
            if all(markdown in old_body for _, markdown in replacements) and not any(
                f"{name} — see the original page" in old_body or f"{name} - see the original page" in old_body
                for name, _ in replacements
            ):
                print("The file-viewer links are already present. No data changed.")
                return
            new_body = replace_file_viewer_placeholders(old_body, replacements)
            if new_body == old_body:
                print("No body change is needed.")
                return
        print(f"Document: {document.code} — {document.title}")
        if presentation_only:
            print(f"Source title: {source_title}")
            print("Summary: " + str(planned_attrs.get("argus_summary") or "No suitable introductory prose found; left empty."))
            print("The published revision will remain unchanged.")
        else:
            print(f"Matched {len(replacements)} file-viewer macro(s); the published revision will remain unchanged.")
        # End the read transaction before taking a fresh lock for the write.
        db.rollback()
        document = db.scalar(select(Document).where(Document.uid == doc_uid, Document.workspace_id == workspace)
                             .with_for_update().execution_options(populate_existing=True))
        current = db.get(DocumentRevision, current_uid)
        if document is None or current is None or document.current_revision_uid != current_uid or current.state != "published" or (current.body_markdown or "") != published_body:
            raise ValueError("The document changed during preview. Run the repair again.")
        opened = db.scalars(select(DocumentRevision).where(
            DocumentRevision.document_uid == doc_uid,
            DocumentRevision.state.in_(("draft", "in_review", "approved")),
        ).with_for_update().execution_options(populate_existing=True)).all()
        if target_uid is not None:
            if len(opened) != 1 or opened[0].uid != target_uid or opened[0].state != "draft" or (opened[0].body_markdown or "") != old_body:
                raise ValueError("The draft changed during preview. Save your editor changes and run the repair again.")
            target = opened[0]
            for key in ("argus_source_id", "argus_source_version"):
                value = (target.attributes or {}).get(key)
                if value is not None and str(value) != str((current.attributes or {}).get(key)):
                    raise ValueError("The draft's source metadata changed during preview. Review it manually.")
        elif opened:
            raise ValueError("A revision was opened during preview. Run the repair again.")
        if not apply:
            action = "update the existing draft" if target_uid is not None else "create a draft"
            print(f"Preview only: no data changed. Repeat with --apply to {action}.")
            return
        if target_uid is not None:
            if presentation_only:
                target.body_markdown, target.attributes = prepare_presentation(
                    source_title, target.body_markdown or "", target.attributes or {}, storage,
                )
            else:
                target.body_markdown = new_body
            db.commit()
            label = "title/summary" if presentation_only else "file links"
            print(f"Updated {label} in existing draft: {target.uid}")
            print(f"Open /documents/{doc_uid} and select that draft to review the result.")
            return
        number = (db.scalar(select(func.max(DocumentRevision.revision_number)).where(
            DocumentRevision.document_uid == doc_uid)) or 0) + 1
        draft_attrs = deepcopy(current.attributes or {})
        if presentation_only:
            new_body, draft_attrs = prepare_presentation(source_title, new_body, draft_attrs, storage)
        draft = DocumentRevision(
            uid=str(uuid.uuid4()), document_uid=doc_uid, revision_number=number, state="draft",
            body_markdown=new_body, steps=deepcopy(current.steps or []),
            attributes=draft_attrs, valid_from=current.valid_from,
            valid_until=current.valid_until, next_review_due=current.next_review_due,
        )
        db.add(draft)
        db.commit()
        print(f"Created draft revision {number}: {draft.uid}")
        print(f"Open /documents/{doc_uid} and select the new draft to review its links.")
        print("Existing attachment links are preserved; no files were downloaded or duplicated.")
    finally:
        db.rollback()
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--config-name")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--use-existing-draft", action="store_true",
                        help="Repair only file-viewer placeholders in an already-open editable draft.")
    parser.add_argument("--presentation-only", action="store_true",
                        help="Add the exact source title and fill a missing summary, preserving existing file links.")
    args = parser.parse_args()
    try:
        repair(args.workspace, args.page_id, args.config_name, args.apply, args.use_existing_draft, args.presentation_only)
    except Exception as exc:
        parser.exit(1, f"Repair stopped: {exc}\n")


if __name__ == "__main__":
    main()
