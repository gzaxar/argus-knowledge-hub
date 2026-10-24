"""Indoors: the floors of a place, its floor plans, and where records are inside (services/indoor.py).

GPS is weak indoors and most of a laboratory's equipment is indoors, so a record is placed inside by what people
know there: **in a room** (or a hall), and — when there is a plan — **at a point on the plan**.

- A **level** is a floor of a place (a building or a hall): its name, its order (0 the ground floor, -1 below),
  and, if known, its elevation and height in metres.
- A **floor plan** is a picture of a level or of a place (from an image, an SVG, a PDF's first page or a DXF
  drawing), in its own pixels. Placed on the map by control points (a pixel and the longitude and latitude it
  is at), it has an affine transform from its pixels to WGS 84 and the residual of the fit in metres.
- An **indoor placement** says a record is in a place (a room, a hall), on a level, and optionally at a point
  of a plan. One approved placement per record; a newer one supersedes it, which stays (the history).
"""
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.mixins import utcnow


class PlaceLevel(Base):
    __tablename__ = "place_levels"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    place_uid: Mapped[str] = mapped_column(String, index=True)               # the building or hall (an asset)
    name: Mapped[str] = mapped_column(String)                                # "Ground floor", "-1", "Mezzanine"
    ordinal: Mapped[int] = mapped_column(Integer, default=0)                 # 0 ground, 1 first, -1 basement
    elevation_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)


class FloorPlan(Base):
    __tablename__ = "floor_plans"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    place_uid: Mapped[str] = mapped_column(String, index=True)
    level_uid: Mapped[Optional[str]] = mapped_column(String, ForeignKey("place_levels.uid", ondelete="SET NULL"),
                                                     nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)                        # the picture shown (PNG, JPEG or SVG)
    mime_type: Mapped[str] = mapped_column(String)
    width_px: Mapped[float] = mapped_column(Float)
    height_px: Mapped[float] = mapped_column(Float)
    source_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_kind: Mapped[str] = mapped_column(String)                         # image | svg | pdf | dxf
    source_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # the file given, when converted
    # Placed on the map: [{x, y, longitude, latitude}], the transform x,y → longitude, latitude
    # ({a, b, c, d, e, f}: lon = a·x + b·y + c, lat = d·x + e·y + f) and how well the points fit it.
    control_points: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    transform: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    residual_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class IndoorPlacement(Base):
    __tablename__ = "indoor_placements"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    asset_uid: Mapped[str] = mapped_column(String, index=True)
    place_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)   # the room or hall it is in
    level_uid: Mapped[Optional[str]] = mapped_column(String, ForeignKey("place_levels.uid", ondelete="SET NULL"),
                                                     nullable=True)
    plan_uid: Mapped[Optional[str]] = mapped_column(String, ForeignKey("floor_plans.uid", ondelete="SET NULL"),
                                                    nullable=True, index=True)
    plan_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    plan_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")            # manual | field | import
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="confirmed")          # confirmed | superseded | removed
    valid_from = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=utcnow)
