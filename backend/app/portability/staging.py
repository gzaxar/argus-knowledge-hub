"""The isolation boundary of an import: a staging database per import (docs/export-import-design.md §10.1).

An import is loaded, rebuilt and reconciled in a database of its own, never in the active one:

* `create` makes `argus_stage_<import>` on the active server (or the server of
  `ARGUS_PORTABILITY_STAGING_URL`) and migrates it to the current head.
* `seed` copies into it what the import must be reconciled against: the active workspaces the archive
  touches (an increment's earlier state, all of it), the portability row map and chain of the same
  origin, and every row those or the archive's rows refer to (types, owner workspaces, people,
  records in other workspaces), recursively.
* The load (`importer.execute`) runs there with durable, per-chunk checkpoints: an interrupted import
  resumes there, and nothing about it is visible to the active instance — not to its APIs, search,
  graph, AI retrieval, projectors, notifications or exports, which only ever read the active database.
* Finalization (`importer.promote`) loads the same verified archive into the active database in ONE
  transaction, rebuilds and reconciles there, and commits only when that result equals the staged
  one. Readers see all of it or none of it. Exports take their watermark lock before reading, so
  they wait for the promotion to commit or roll back.
* `drop` removes the staging database. A discard or failure never touches the active database.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.db import Base

BACKEND = Path(__file__).resolve().parents[2]
_TABLES = {t.name: t for t in Base.metadata.sorted_tables}


class StagingError(RuntimeError):
    pass


def database_name(import_id: str) -> str:
    return "argus_stage_" + re.sub(r"[^a-z0-9]", "_", import_id.lower())[:40]


def _server_url(active_url) -> object:
    explicit = os.environ.get("ARGUS_PORTABILITY_STAGING_URL")
    return make_url(explicit) if explicit else make_url(active_url)


def url_for(active_url, name: str) -> str:
    return _server_url(active_url).set(database=name).render_as_string(hide_password=False)


def create(active_url, import_id: str) -> str:
    """Create (if absent) and migrate the staging database; returns its name."""
    name = database_name(import_id)
    admin = create_engine(_server_url(active_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}):
                c.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, capture_output=True,
                       env={**os.environ, "DATABASE_URL": url_for(active_url, name)}, timeout=600)
    if r.returncode != 0:
        raise StagingError(f"could not migrate the staging database: {r.stderr.decode()[-400:]}")
    return name


def drop(active_url, name: Optional[str]) -> None:
    if not name or not name.startswith("argus_stage_"):
        return
    admin = create_engine(_server_url(active_url).set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def engine_for(active_url, name: str) -> Engine:
    return create_engine(url_for(active_url, name), pool_pre_ping=True)


# --------------------------------------------------------------------------- seeding

class _Copier:
    """Copies active rows into staging as they are (every column, local ids included), following
    foreign keys so that every copied row's references exist there too."""

    def __init__(self, active: Session, stage: Session):
        self.active, self.stage = active, stage
        self.seen: set = set()
        self.copied = 0

    def _pk(self, table) -> list:
        return list(table.primary_key.columns)

    def row(self, table_name: str, pk_values: tuple) -> None:
        key = (table_name, pk_values)
        if key in self.seen:
            return
        self.seen.add(key)
        table = _TABLES[table_name]
        pk = self._pk(table)
        cond = [c == v for c, v in zip(pk, pk_values)]
        found = self.active.execute(select(table).where(*cond)).mappings().first()
        if found is None:
            return
        if self.stage.execute(select(*pk).where(*cond)).first() is not None:
            return
        values = dict(found)
        deferred = {}
        for col in table.columns:
            v = values.get(col.name)
            if v is None or not col.foreign_keys:
                continue
            fk = next(iter(col.foreign_keys))
            if len(self._pk(fk.column.table)) != 1:
                continue
            if col.nullable:
                deferred[col.name] = (fk.column.table.name, v)   # set once the row exists: breaks cycles
                values[col.name] = None
            else:
                self.row(fk.column.table.name, (v,))
        self.stage.execute(insert(table).values(**values))
        self.copied += 1
        if deferred:
            for target, v in deferred.values():
                self.row(target, (v,))
            keep = {c.name: found[c.name] for c in table.columns if c.onupdate is not None}   # no automatic bump
            self.stage.execute(table.update().where(*cond).values(**{c: v for c, (_, v) in deferred.items()}, **keep))

    def query(self, table_name: str, where) -> None:
        table = _TABLES[table_name]
        pk = self._pk(table)
        for r in self.active.execute(select(*pk).where(where)):
            self.row(table_name, tuple(r))


def seed(active: Session, stage: Session, plan, archive_refs: dict) -> dict:
    """Copy into staging the active state an import is reconciled against. `archive_refs` maps a
    table to the primary keys the archive's rows refer to (from `importer.references`)."""
    from app.models.portability import PortabilityChainLink, PortabilityImport, PortabilityRowMap, PortabilityTagSeen
    from app.portability.families import FAMILIES, Scope
    c = _Copier(active, stage)
    present = [w for w in plan.workspaces if active.execute(
        text("SELECT 1 FROM workspaces WHERE id = :w"), {"w": w}).first()]
    # Not scoped to a workspace at all (no workspace_id column: see families.py), so whether any of
    # the archive's workspaces exist here yet has nothing to do with whether it's worth seeding — a
    # local row here can diverge from the archive's regardless. Without this, staging's reconciliation
    # of a merge into a brand-new workspace never sees a pre-existing local row here at all (it was
    # never copied in), so it reconciles as a fresh create — disagreeing with promotion's reconcile
    # against the real, unscoped table, which does see it.
    # The governance policies and installation-wide rulesets belong here for the same reason: which
    # sources are in effect decides what rebuild projects, so staging must see the policy promotion will.
    UNSCOPED = ("equipment_classes", "equipment_class_reviews", "policies", "rulesets")
    sc = Scope(workspaces=present, watermark={t: 2 ** 62 for t in _sequenced()})
    for fam in FAMILIES:
        if not present and fam.name not in UNSCOPED:
            continue
        pk = c._pk(fam.model.__table__)
        for obj in active.scalars(fam.select(active, sc)):
            c.row(fam.table, tuple(getattr(obj, col.key) for col in pk))
    for table_name, keys in archive_refs.items():
        for k in keys:
            c.row(table_name, (k,))
    for model in (PortabilityRowMap, PortabilityChainLink, PortabilityTagSeen):
        col = model.origin if hasattr(model, "origin") else None
        if col is not None:
            c.query(model.__tablename__, col == plan.origin)
    # The earlier imports those row maps name: when each was made tells a row nobody changed since from local work.
    c.query(PortabilityImport.__tablename__, PortabilityImport.id.in_(
        select(PortabilityRowMap.import_id).where(PortabilityRowMap.origin == plan.origin,
                                                  PortabilityRowMap.import_id != plan.import_id).distinct()))
    stage.flush()
    _sync_sequences(stage)
    return {"rows_copied": c.copied, "workspaces": present}


def _sequenced():
    from app.portability.families import SEQUENCED_TABLES
    return SEQUENCED_TABLES


def _sync_sequences(stage: Session) -> None:
    """Rows copied with their ids: move each serial sequence past them."""
    for t in Base.metadata.sorted_tables:
        for col in t.primary_key.columns:
            if col.autoincrement is True or (col.autoincrement == "auto" and col.type.python_type is int):
                seq = stage.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": t.name, "c": col.name}).scalar()
                if seq:
                    stage.execute(text(f"SELECT setval('{seq}', GREATEST((SELECT coalesce(max({col.name}), 0) "
                                       f"FROM {t.name}), 1))"))
