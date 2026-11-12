"""The synthetic workspaces a run asks its questions in: built for the run, dropped after it.

A fixture is one or more workspaces: a demo bundle applied (demo_workspaces/), records added from the fixture's
YAML, or both. Applying a bundle into a database that already uses its identifiers renames them (app/bundle/core),
and added records may collide too, so a fixture keeps an alias table: the identifier the dataset names
(NF-SC-DH1, nf-t-022, VL-PS-Q1) → the record it became here. Expected sources, facts and must-not-reveal lists are
resolved through it, so the same dataset scores the same way on an empty CI database and on a scratch database
that already holds a copy.
"""
from __future__ import annotations

import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ask_eval import WORKSPACE_PREFIX
from app.ask_eval.dataset import Fixture, FixtureWorkspace

DEMOS = Path(__file__).resolve().parents[2] / "demo_workspaces"


class FixtureError(Exception):
    pass


@dataclass
class Record:
    """A record of the fixture as it is in this run."""
    kind: str                     # asset | ticket | document
    uid: str
    ref: str                      # what an answer cites it by: key, ticket key or document code
    name: str
    workspace_id: str


@dataclass
class Built:
    fixture_id: str
    workspaces: list[str]
    alias: dict[str, str] = field(default_factory=dict)       # dataset identifier → identifier here
    _records: dict[str, Record] = field(default_factory=dict)

    @property
    def workspace_id(self) -> str:
        return self.workspaces[0]

    def resolve(self, db: Session, ident: str) -> Optional[Record]:
        """The record a dataset identifier names, as it is in this run (None: not in the fixture)."""
        if ident in self._records:
            return self._records[ident]
        from app.models.asset import Asset
        from app.models.document import Document
        from app.models.issue import Issue
        here = self.alias.get(ident, ident)
        found: Optional[Record] = None
        a = db.scalar(select(Asset).where(Asset.workspace_id.in_(self.workspaces),
                                          (Asset.uid == here) | (Asset.key == here)))
        if a is not None:
            found = Record("asset", a.uid, a.key or a.uid, a.name, a.workspace_id)
        if found is None:
            d = db.scalar(select(Document).where(Document.workspace_id.in_(self.workspaces),
                                                 (Document.uid == here) | (Document.code == here)))
            if d is not None:
                found = Record("document", d.uid, d.code, d.title, d.workspace_id)
        if found is None:
            i = db.scalar(select(Issue).where(Issue.workspace_id.in_(self.workspaces),
                                              (Issue.uid == here) | (Issue.key == here)))
            if i is not None:
                found = Record("ticket", i.uid, i.key or i.uid, i.title, i.workspace_id)
        if found is not None:
            self._records[ident] = found
        return found

    def render(self, db: Session, pattern: str) -> str:
        """A fact's pattern with each {ref:X} replaced by X's citation here (its key or code), escaped."""
        def sub(m):
            rec = self.resolve(db, m.group(1))
            return re.escape(rec.ref if rec else m.group(1))
        return re.sub(r"\{ref:([^}]+)\}", sub, pattern)


def workspace_id(run_id: str, fixture_id: str, suffix: str) -> str:
    return f"{WORKSPACE_PREFIX}{run_id}-{fixture_id}-{suffix}"[:120]


def _apply_bundle(db: Session, w: FixtureWorkspace, ws: str, files_root: Path, alias: dict) -> None:
    from app.bundle import core
    path = DEMOS / (w.bundle or "")
    if not (path / "manifest.json").exists():
        raise FixtureError(f"no demo bundle {w.bundle!r}")
    rep = core.apply(db, core.read(path), workspace_id=ws, name=w.name, actor="ask-eval", dry_run=False,
                     files_root=files_root)
    view = rep.view()
    if not view["ok"]:
        db.rollback()
        raise FixtureError(f"bundle {w.bundle} could not be applied: {view.get('blockers')}")
    db.commit()
    for r in rep.renamed:
        if r.get("to") and r["to"] != "the next key here":
            alias[r["from"]] = r["to"]


def _schema(db: Session, ws: str, name: str, applies_to: str, cache: dict) -> str:
    from app.models.schema import Schema
    k = (applies_to, name)
    if k in cache:
        return cache[k]
    found = db.scalar(select(Schema.uid).where(Schema.workspace_id == ws, Schema.name == name,
                                               Schema.applies_to == applies_to))
    if found is None:
        found = f"{ws}-{applies_to}-{re.sub(r'[^a-z0-9]+', '-', name.lower())}"
        db.add(Schema(uid=found, workspace_id=ws, name=name, applies_to=applies_to))
        db.flush()
    cache[k] = found
    return found


def _free(db: Session, column, value: str, ws: str) -> str:
    """A unique value as given, or made unique for this workspace when the installation already uses it."""
    taken = db.scalar(select(column).where(column == value).limit(1))
    return value if taken is None else f"{value}-{ws}"


def _add_records(db: Session, ws: str, records: dict, alias: dict, all_ws: dict[str, str]) -> None:
    """Records written in the fixture: types, assets, relations, tickets with comments, documents with their
    revisions and the records they describe. Identifiers get this run's prefix; keys and codes stay as written
    unless already used here."""
    from app.models.asset import Asset, Relation
    from app.models.document import Document, DocumentRelation, DocumentRevision
    from app.models.issue import Issue, IssueComment
    cache: dict = {}
    run_uid = lambda u: alias.setdefault(u, f"{ws}:{u}")  # noqa: E731

    def ref(u: str) -> str:
        if u in alias:
            return alias[u]
        # A record of another workspace of the fixture, written as <suffix>/<uid>.
        if "/" in u:
            suffix, rest = u.split("/", 1)
            if suffix in all_ws:
                return alias.get(rest, f"{all_ws[suffix]}:{rest}")
        return alias.get(u, u)

    for a in records.get("assets", []):
        attrs = dict(a.get("attributes") or {})
        if a.get("classification"):
            attrs["classification"] = f"restricted:{a['classification']}"
        key = _free(db, Asset.key, a["key"], ws) if a.get("key") else None
        uid = run_uid(a["uid"])
        if a.get("key"):
            alias[a["key"]] = key
        db.add(Asset(uid=uid, workspace_id=ws, schema_uid=_schema(db, ws, a["type"], "objects", cache), key=key,
                     name=a["name"], type=a["type"], attributes=attrs, is_global=bool(a.get("global"))))
    db.flush()
    for r in records.get("relations", []):
        db.add(Relation(workspace_id=ws, from_asset_uid=ref(r["from"]), to_asset_uid=ref(r["to"]),
                        relation_type=r["type"]))
    db.flush()
    for t in records.get("tickets", []):
        attrs = dict(t.get("attributes") or {})
        if t.get("classification"):
            attrs["classification"] = f"restricted:{t['classification']}"
        uid = run_uid(t["uid"])
        issue = Issue(uid=uid, workspace_id=ws, title=t["title"], description=t.get("description"),
                      state=t.get("state", "new"), priority=t.get("priority"),
                      asset_uid=ref(t["asset"]) if t.get("asset") else None, attributes=attrs)
        db.add(issue)
        db.flush()
        for i, c in enumerate(t.get("comments", [])):
            db.add(IssueComment(uid=f"{uid}-c{i}", issue_uid=uid, author=c.get("author", "eval"), body=c["body"]))
    db.flush()
    for d in records.get("documents", []):
        uid = run_uid(d["uid"])
        code = _free(db, Document.code, d["code"], ws)
        alias[d["code"]] = code
        doc = Document(uid=uid, workspace_id=ws, code=code, title=d["title"],
                       document_type_uid=_schema(db, ws, d.get("type", "Procedure"), "documents", cache),
                       confidentiality=d.get("confidentiality", "interno"), is_global=bool(d.get("global")))
        db.add(doc)
        db.flush()
        current = None
        for rv in d.get("revisions") or [{"number": 1, "state": "published", "body": d.get("body", "")}]:
            rev = DocumentRevision(uid=f"{uid}-r{rv['number']}", document_uid=uid, revision_number=rv["number"],
                                   state=rv.get("state", "published"), body_markdown=rv["body"])
            db.add(rev)
            db.flush()
            if rv.get("current", rv.get("state", "published") == "published"):
                current = rev.uid
        doc.current_revision_uid = current
        for target in d.get("describes", []):
            db.add(DocumentRelation(workspace_id=ws, from_document_uid=uid, to_type="asset", to_uid=ref(target),
                                    relation_type="describes"))
    db.flush()


def build(db: Session, fixture: Fixture, run_id: str) -> Built:
    """The fixture's workspaces, created and committed; what they were called and renamed to."""
    from app.models.llm_config import LLMConfig
    from app.models.workspace import Workspace
    names = {w.suffix: workspace_id(run_id, fixture.id, w.suffix) for w in fixture.workspaces}
    built = Built(fixture.id, [names[w.suffix] for w in fixture.workspaces])
    files_root = Path(tempfile.mkdtemp(prefix=f"askeval-{run_id}-"))
    try:
        # The others first: the workspace questions are asked in may point at their records (a shared catalogue).
        for w in reversed(fixture.workspaces):
            ws = names[w.suffix]
            if db.get(Workspace, ws) is not None:
                raise FixtureError(f"workspace {ws} exists already: a run id is used once")
            if w.bundle:
                _apply_bundle(db, w, ws, files_root, built.alias)
            else:
                db.add(Workspace(id=ws, name=w.name))
                db.flush()
            workspace = db.get(Workspace, ws)
            workspace.is_global = w.is_global
            # Each workspace's AI setting decides whether confidential text may go to a model (mcp_tools).
            config = db.get(LLMConfig, ws)
            if config is None:
                config = LLMConfig(workspace_id=ws, base_url="http://ask-eval.invalid/v1", model="ask-eval",
                                   enabled=False)
                db.add(config)
            config.allow_confidential = w.allow_confidential
            db.flush()
            _add_records(db, ws, w.records, built.alias, names)
            db.commit()
    except Exception:
        db.rollback()
        drop(db, built.workspaces)
        raise
    return built


def drop(db: Session, workspaces: list[str]) -> None:
    """The run's workspaces, gone with everything in them."""
    from app.ledger.audit import allow_purge
    from app.models.workspace import Workspace
    for ws in workspaces:
        if not ws.startswith(WORKSPACE_PREFIX):
            raise FixtureError(f"refusing to drop {ws}: not an evaluation workspace")
        w = db.get(Workspace, ws)
        if w is not None:
            allow_purge(db)
            db.delete(w)
            db.commit()
        # The search index is kept in its own tables (services/knowledge_index), not tied to the workspace row.
        from sqlalchemy import text
        for table in ("knowledge_chunks", "knowledge_index_runs"):
            try:
                with db.begin_nested():
                    db.execute(text(f"DELETE FROM {table} WHERE workspace_id = :w"), {"w": ws})
                db.commit()
            except Exception:  # noqa: BLE001 — no index store in this database
                db.rollback()


def leftovers(db: Session) -> list[str]:
    from app.models.workspace import Workspace
    return list(db.scalars(select(Workspace.id).where(Workspace.id.like(f"{WORKSPACE_PREFIX}%"))))


def other_workspaces(db: Session) -> list[str]:
    """Workspaces in this database that are not an evaluation's: a run refuses to share a database with them
    unless told to (their global records would be visible to the questions, and the run would write beside
    real data)."""
    from app.models.workspace import Workspace
    return list(db.scalars(select(Workspace.id).where(~Workspace.id.like(f"{WORKSPACE_PREFIX}%"))))


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]
