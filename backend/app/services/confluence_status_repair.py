"""Local administration utility: preview/apply status-prompt cleanup to an existing draft only."""
import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models.document import Document, DocumentRevision
from app.services.confluence_page_fields import normalize_document_status


def choose_editable_draft(revisions):
    if len(revisions) != 1:
        raise ValueError("Expected one open draft. Create a draft with ARGUS's New revision action first; do not delete or reimport the document.")
    revision = revisions[0]
    if revision.state != "draft":
        raise ValueError("The open revision is not editable. Return it to Draft through ARGUS's normal review workflow first.")
    return revision


def repair_status(workspace: str, document_uid: str, apply: bool = False) -> None:
    with SessionLocal() as db:
        document = db.scalar(select(Document).where(
            Document.uid == document_uid, Document.workspace_id == workspace,
        ).with_for_update())
        if document is None or document.source != "confluence":
            raise ValueError("Expected a Confluence document in the specified workspace.")
        opened = db.scalars(select(DocumentRevision).where(
            DocumentRevision.document_uid == document.uid,
            DocumentRevision.state.in_(("draft", "in_review", "approved")),
        ).with_for_update()).all()
        draft = choose_editable_draft(opened)
        if draft.uid == document.current_revision_uid:
            raise ValueError("The open draft is unexpectedly marked current. Review this document manually.")
        old_body = draft.body_markdown or ""
        new_body = normalize_document_status(old_body)
        print(f"Document: {document.code} — {document.title}")
        print(f"Draft: {draft.uid}")
        if new_body == old_body:
            print("No status prompt found. No changes made.")
            return
        for before, after in zip(old_body.splitlines(), new_body.splitlines()):
            if before != after:
                print("Before:", before)
                print("After: ", after)
        if not apply:
            print("Preview only. No changes made. Repeat with --apply to update this draft.")
            return
        draft.body_markdown = new_body
        db.commit()
        print("Updated the draft status cell. Published revision, attachments and other fields are unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--document", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        repair_status(args.workspace, args.document, args.apply)
    except ValueError as exc:
        parser.exit(1, f"Repair stopped: {exc}\n")


if __name__ == "__main__":
    main()
