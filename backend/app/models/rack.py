"""What is mounted in a rack, and where (docs/rack-elevation.md).

A mounting says: this unit sits in this rack from unit `start_u`, `height_u` units high, on the front, the rear or
through both. A shelf and a reserved space are mountings too, without a unit; a 0U device (a vertical PDU, a cable
manager on the post) is in the rack and takes no unit. Nothing is overwritten: a move closes the old row
(`superseded`, `valid_until`) and opens a new one, so the rack's past can be read.
"""
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow

KINDS = ("device", "shelf", "reserved", "zero_u")
FACES = ("front", "rear", "both")


class RackMounting(Base):
    __tablename__ = "rack_mountings"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    rack_uid: Mapped[str] = mapped_column(String, index=True)
    asset_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)   # none: a reserved space
    kind: Mapped[str] = mapped_column(String, default="device")                 # device | shelf | reserved | zero_u
    start_u: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)      # lowest unit taken; none for 0U
    height_u: Mapped[int] = mapped_column(Integer, default=1)                   # 0 for 0U
    face: Mapped[str] = mapped_column(String, default="front")                  # front | rear | both
    shelf_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)     # the shelf mounting it stands on
    label: Mapped[Optional[str]] = mapped_column(String, nullable=True)         # what a reserved space is kept for
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")               # manual | field | import
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)      # photo, what was read, confidence
    state: Mapped[str] = mapped_column(String, default="confirmed")             # confirmed | superseded | removed
    valid_from = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
