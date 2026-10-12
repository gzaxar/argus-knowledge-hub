"""Where records are, on the earth: approved locations and the field observations proposing them.

A **spatial feature** is a record's approved location: its geometry (a point in this release; lines and
polygons later, in the same column), the coordinate reference it was given in, where it came from, how
accurate it is, when it was observed, the period it is valid for, and who confirmed it. A newer approved
location supersedes the old one, which stays (`valid_until`, `state`): the history is the rows.

A **location observation** is what a phone (or an import) saw — never the record's location by itself. One
that agrees with the approved location is noted as consistent; one that does not goes to review, where a
person accepts it (it becomes the approved location) or rejects it.

Geometries are stored in WGS 84 (EPSG:4326, longitude/latitude); `crs` records what they were given in.
They are separate from the knowledge graph: where a unit physically is, and what it is functionally
connected to, are different facts.
"""
import json
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db import Base
from app.models.mixins import utcnow

SRID = 4326


class Geometry(UserDefinedType):
    """A PostGIS geometry in WGS 84, read and written as GeoJSON (a dict)."""
    cache_ok = True

    def get_col_spec(self, **kw):
        return f"geometry(Geometry, {SRID})"

    def bind_expression(self, bindvalue):
        return func.ST_SetSRID(func.ST_GeomFromGeoJSON(bindvalue), SRID)

    def column_expression(self, col):
        return func.ST_AsGeoJSON(col)

    def bind_processor(self, dialect):
        return lambda value: None if value is None else json.dumps(value)

    def result_processor(self, dialect, coltype):
        return lambda value: None if value is None else json.loads(value)


class SpatialFeature(Base):
    __tablename__ = "spatial_features"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    subject_kind: Mapped[str] = mapped_column(String, default="asset")        # the record it locates
    subject_uid: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="position")            # later: route, footprint, area
    geometry: Mapped[dict] = mapped_column(Geometry)
    geometry_type: Mapped[str] = mapped_column(String)                       # Point (LineString, Polygon later)
    crs: Mapped[str] = mapped_column(String, default="EPSG:4326")
    source: Mapped[str] = mapped_column(String)                              # manual | field | import | survey
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String, default="confirmed")          # confirmed | superseded | removed
    confirmed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confirmed_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # when it came through review
    observation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    provenance: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # an import's source and row
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocationObservation(Base):
    __tablename__ = "location_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    subject_kind: Mapped[str] = mapped_column(String, default="asset")
    subject_uid: Mapped[str] = mapped_column(String, index=True)
    geometry: Mapped[dict] = mapped_column(Geometry)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    observed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="field")             # field | import
    # consistent: agrees with the approved location; pending: waits for review; accepted / rejected
    status: Mapped[str] = mapped_column(String, default="pending")
    distance_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # from the approved location then
    feature_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # the approved location it compared with
    decided_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    decided_at: Mapped[Optional[object]] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
