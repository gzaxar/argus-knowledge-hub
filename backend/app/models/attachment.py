import hashlib
import os
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import TimestampMixin, WorkspaceScopedMixin


class Attachment(Base, WorkspaceScopedMixin, TimestampMixin):
    __tablename__ = "attachments"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    asset_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("assets.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    document_revision_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("document_revisions.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    # A ticket's own files — a screenshot of the fault, a log — which belong
    # to the ticket rather than to whatever object it happens to mention.
    issue_uid: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("issues.uid", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String)
    mime_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # SHA-256 of the stored bytes: what a cutover reconciliation compares (§17.6).
    sha256: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    storage_path: Mapped[str] = mapped_column(String)
    backend_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    backend_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # A ticket file's audience, as a comment's: "internal" unless chosen, "requester" for what its requester sees.
    audience: Mapped[str] = mapped_column(String, default="internal", server_default="internal")


def file_sha256(path: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@event.listens_for(Attachment, "before_insert")
def _checksum(_mapper, _connection, target: Attachment) -> None:
    # Every upload path writes the file before the row, so one hook covers
    # them all, imports included.
    if target.sha256 is None:
        target.sha256 = file_sha256(target.storage_path)
