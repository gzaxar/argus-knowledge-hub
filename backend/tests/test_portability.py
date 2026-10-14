"""Portable archives and the Git portability project (docs/export-import-design.md §16).

Each test builds a source instance and a target instance as two fresh databases at the migration
head, so a checkpoint is proved to rebuild ARGUS somewhere it has never been. Test names carry the
acceptance-test numbers of the design (A1–A30).
"""
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.db import DATABASE_URL
from app.ledger import engine as ledger, service as ledger_service
from app.models.asset import Asset, Relation
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.issue import Issue, IssueComment, IssueHistory
from app.models.ledger import Claim, ClaimEvent, Decision
from app.models.portability import PortabilityEvent, PortabilityExport, PortabilityImport, PortabilityRowMap
from app.models.user import User
from app.models.workspace import Workspace
from app.portability import chunks, envelope, exporter, gitrepo, importer, service, signing, staging
from app.portability.artifacts import DirectoryStore
from app.portability.policy import Policy
from tests.test_ledger_slice import T0, insight_json, values_yaml

pytestmark = pytest.mark.skipif(not DATABASE_URL.startswith("postgresql"), reason="needs Postgres")
BACKEND = Path(__file__).resolve().parents[1]


def _url(name: str) -> str:
    return DATABASE_URL.rsplit("/", 1)[0] + f"/{name}"


def fresh_db():
    name = f"argus_port_{secrets.token_hex(4)}"
    admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                   env={**os.environ, "DATABASE_URL": _url(name)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return name, create_engine(_url(name))


def drop_db(name, eng):
    eng.dispose()
    admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def dbs():
    made = []

    def make():
        name, eng = fresh_db()
        made.append((name, eng))
        return eng
    yield make
    for name, eng in made:
        drop_db(name, eng)


@pytest.fixture()
def env(tmp_path):
    """Keys, an artifact store, a bare portability repository and the service configuration."""
    signer = signing.new_key(tmp_path / "signing_key")
    allowed = tmp_path / "allowed_signers"
    allowed.write_text(signing.allowed_signers_line(signer))
    repo = gitrepo.init_bare(tmp_path / "escrow.git")
    restricted_repo = gitrepo.init_bare(tmp_path / "escrow-restricted.git")
    store = DirectoryStore("vault", tmp_path / "vault")
    keys = tmp_path / "decryption-keys"           # what an import session would have mounted
    keys.mkdir()
    recipients = tmp_path / "recipients"
    recipients.write_text(envelope.new_recipient_key(keys / "escrow-officer", "escrow-officer"))

    def cfg(name: str, decrypt: bool = True) -> service.Config:
        return service.Config(root=tmp_path / name, attachments_dir=tmp_path / name / "attachments",
                              stores={"vault": store}, signer=signer, trusted=allowed,
                              repositories={"escrow": repo, "escrow-restricted": restricted_repo},
                              restricted_destinations={"escrow-restricted": {"costs", "personnel"}},
                              recipients={"escrow-restricted": recipients},
                              decryption_keys=keys if decrypt else None, evidence_readers={"reader@example.org"},
                              policy=Policy.strict())   # these tests prove the strict rules; see test_portability_policy
    return SimpleNamespace(signer=signer, allowed=allowed, repo=repo, restricted_repo=restricted_repo, store=store,
                           cfg=cfg, tmp=tmp_path, keys=keys)


def populate(eng, tmp: Path) -> SimpleNamespace:
    """A small facility: configuration and inventory streams, a confirmed Installation, a person's
    edit, a Jira-sourced ticket with comments and history, a document with a superseded revision,
    an attachment, an asserted relation, a retired record and a merge tombstone."""
    s = SimpleNamespace(fac=f"P{secrets.token_hex(2).upper()}", ws=f"cfg-{secrets.token_hex(3)}",
                        inv=f"inv-{secrets.token_hex(3)}", oid1=str(secrets.randbelow(10 ** 9)),
                        oid2=str(secrets.randbelow(10 ** 9)))
    s.config = f"epik8s:{s.fac}#values.yaml@main"
    s.insight = f"insight:{s.fac}:schema=44"
    with Session(eng) as db:
        db.add_all([Workspace(id=s.ws, name="Configuration"), Workspace(id=s.inv, name="Inventory")])
        db.add(User(id="u-rossi", email="rossi@example.org", name="M. Rossi", oidc_sub="sub-rossi"))
        db.flush()
        ledger.register_stream(db, s.config, s.ws, "epik8s", facility=s.fac,
                               may_create=["IOC", "Control Device", "Equipment Position"])
        ledger.register_stream(db, s.insight, s.inv, "insight", may_create=["Ion Pump"])
        ledger.activate_policy(db)
        ledger.ingest(db, s.config, revision="r1", content=values_yaml(s.fac, s.oid1), observed_at=T0,
                      parser="epik8s-slice")
        ledger.ingest(db, s.insight, revision="i1", content=insight_json(s.fac, s.oid1, s.oid2), observed_at=T0,
                      parser="insight-fixture")
        pos = db.scalar(select(Asset).where(Asset.key == f"{s.fac}:POS:GUNSIP01"))
        [prop] = [v for v in ledger.installations(db, position_uid=pos.uid) if v["status"] == "Proposed"]
        ledger_service.confirm_installation(db, s.ws, "operator@example.org", prop["uid"])
        s.installation = prop["uid"]
        s.unit = db.scalar(select(Asset).where(Asset.key == f"{s.fac}INV-84321")).uid
        s.spare = db.scalar(select(Asset).where(Asset.key == f"{s.fac}INV-90001")).uid
        ledger_service.edit_value(db, s.inv, "rossi@example.org", s.unit, "attr:argus_location", "Rack B13")
        pump = ledger.ensure_type(db, s.inv, "Ion Pump")
        s.retired = str(uuid.uuid4())
        s.survivor, s.tomb = str(uuid.uuid4()), str(uuid.uuid4())
        db.add_all([
            Asset(uid=s.retired, workspace_id=s.inv, key=f"{s.fac}-OLD-1", name="Old pump", type="Ion Pump",
                  schema_uid=pump.uid, record_status="Retired", attributes={"argus_source_key": f"{s.fac}OLD-1"}),
            Asset(uid=s.survivor, workspace_id=s.inv, key=f"{s.fac}-SURV", name="Survivor", type="Ion Pump",
                  schema_uid=pump.uid, attributes={}),
        ])
        db.flush()
        db.add(Asset(uid=s.tomb, workspace_id=s.inv, key=f"{s.fac}-TOMB", name="Duplicate", type="Ion Pump",
                     schema_uid=pump.uid, record_status="Merged", merged_into_uid=s.survivor, attributes={}))
        db.add(Relation(workspace_id=s.inv, from_asset_uid=s.spare, to_asset_uid=s.unit, relation_type="spare for"))
        s.issue = str(uuid.uuid4())
        db.add(Issue(uid=s.issue, workspace_id=s.inv, title="Pump noisy", asset_uid=s.unit, state="closed",
                     created_at=T0, closed_at=T0,
                     attributes={"argus_source": "jira", "argus_source_key": f"{s.fac}-9",
                                 "argus_source_url": f"https://jira.example/browse/{s.fac}-9"}))
        db.flush()
        db.add(IssueComment(uid=str(uuid.uuid4()), issue_uid=s.issue, author="rossi", body="replaced the gasket",
                            created_at=T0))
        db.add(IssueHistory(uid=str(uuid.uuid4()), issue_uid=s.issue, type="transition", author="rossi",
                            field="state", from_value="open", to_value="closed", timestamp=T0))
        s.doc = str(uuid.uuid4())
        db.add(Document(uid=s.doc, workspace_id=s.inv, code=f"{s.fac}-PROC-1", title="Pump procedure",
                        owner_user_id="u-rossi"))
        db.flush()
        r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())
        db.add(DocumentRevision(uid=r1, document_uid=s.doc, revision_number=1, state="superseded",
                                body_markdown="v1", approved_by="u-rossi", approved_at=T0))
        db.add(DocumentRevision(uid=r2, document_uid=s.doc, revision_number=2, state="published",
                                body_markdown="v2", approved_by="u-rossi", approved_at=T0))
        db.flush()
        db.get(DocumentRevision, r1).superseded_by_uid = r2
        db.get(Document, s.doc).current_revision_uid = r2
        photo = tmp / "files" / f"{s.fac}.jpg"
        photo.parent.mkdir(exist_ok=True)
        photo.write_bytes(b"a photo of the pump " + s.fac.encode())
        db.add(Attachment(uid=str(uuid.uuid4()), workspace_id=s.inv, issue_uid=s.issue, filename="photo.jpg",
                          mime_type="image/jpeg", file_size=photo.stat().st_size, storage_path=str(photo)))
        db.flush()
        ledger.derive_all(db, [s.ws, s.inv])      # what the write paths do: ticket links, derived edges
        db.commit()
    return s


def run_export(eng, env, s, *, mode="workspace", workspaces=None, decisions=None, base=None,
               requester="alice@example.org", approver="bob@example.org", publish=True, root="src",
               classifications=(), repository="escrow", identity_profile=None):
    cfg = env.cfg(root)
    with Session(eng) as db:
        exp = service.create_export(db, requester, mode=mode, workspaces=workspaces or [s.ws, s.inv],
                                    classifications=list(classifications),
                                    destination={"repository": repository, "artifact_store": "vault",
                                                 **({"recipients": ["escrow-officer"]} if classifications else {})},
                                    decisions={"opaque_blobs": "approve_opaque", **(decisions or {})},
                                    base_export_id=base, cfg=cfg, identity_profile=identity_profile)
        service.analyse_export(db, exp, requester, cfg)
        db.commit()
        assert exp.analysis["ready"], (exp.analysis["closure"], exp.analysis["blobs"])
        service.approve_export(db, exp, approver, admin=True, fresh_auth=True, cfg=cfg)
        db.commit()
        service.generate_export(eng, db, exp, approver, cfg, fresh_auth=True)
        if publish:
            service.publish_export(db, exp, approver, cfg)
        db.commit()
        return service.export_view(db.get(PortabilityExport, exp.id)), db.get(PortabilityExport, exp.id).manifest


def run_import(eng, env, ref, *, mode="clone", decisions=None, root="dst", finalize=True, expect_ready=True,
               stop_after=None, requester="carol@example.org", approver="dave@example.org", repository="escrow"):
    cfg = env.cfg(root)
    with Session(eng) as db:
        imp = service.create_import(db, requester, mode=mode, source={"repository": repository, "ref": ref},
                                    decisions=decisions or {}, cfg=cfg)
        db.commit()
        service.fetch_git(db, imp, requester, cfg)
        service.verify_import(db, imp, requester, cfg)
        service.dry_run(db, imp, requester, cfg)
        db.commit()
        if not expect_ready:
            return imp.id, imp.dry_run
        assert imp.state == "awaiting_approval", imp.dry_run
        service.approve_import(db, imp, approver, acknowledge_uninspected=True, cfg=cfg)
        db.commit()
        if stop_after is not None:
            with pytest.raises(service.ServiceError):
                service.execute(db, imp, approver, cfg, stop_after=stop_after)
            return imp.id, None
        service.execute(db, imp, approver, cfg)
        db.commit()
        assert imp.reconciliation["passed"], json.dumps(_failures(imp.reconciliation), indent=1, default=str)
        if finalize:
            service.finalize(db, imp, approver, cfg)
            db.commit()
        return imp.id, imp.reconciliation


def _failures(rec: dict) -> dict:
    return {"families": {k: v for k, v in rec["families"].items() if not v["ok"]},
            "projections": {k: v for k, v in rec["projections"].items() if not v["ok"]},
            "invariants": rec["invariants"]}


# =========================================================================== the slice

def test_A1_A2_A3_A28_a_signed_git_checkpoint_rebuilds_the_same_state_in_an_empty_instance(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, manifest = run_export(src, env, s)
    assert view["state"] == "published" and view["labels"]["signed"] and view["labels"]["git_published"]
    tag = view["git"]["tag"]
    wm = manifest["watermark"]
    assert tag.startswith("export/workspace/") and tag.endswith(f"@cp{wm['checkpoint_sequence']}-{wm['vector_sha256'][:12]}")
    assert manifest["families"]["claim_events"]["rows"] > 0
    # The attachment and every source revision's content travel as artifacts, not in Git.
    blobs = [json.loads(x) for x in (Path(view["git"] and env.cfg("src").export_dir(manifest["export_id"]))
                                     / "blobs.manifest.ndjson").read_text().splitlines()]
    assert any(r.startswith("attachments:") for b in blobs for r in b["referenced_by"])
    assert any(r.startswith("source_revisions:") for b in blobs for r in b["referenced_by"])

    # A28: a clone of the repository plus the artifacts is enough to verify, without ARGUS.
    clone = env.tmp / "clone"
    subprocess.run(["git", "clone", "-q", "--branch", tag, env.repo, str(clone)], check=True, capture_output=True)
    cp = clone / gitrepo.CHECKPOINTS / manifest["export_id"]
    out = subprocess.run([sys.executable, str(clone / "tools" / "validate"), str(cp), "--trusted", str(env.allowed),
                          "--artifacts", f"vault={env.store.root}"], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads(out.stdout)["problems"] == []
    for name in ("format/manifest.schema.json", "format/families/claims.schema.json", "catalogue/types.yaml",
                 "governance/authority-policy.yaml", "README.md", "VERSION", ".argus-portability.json"):
        assert (clone / name).exists(), name

    imp_id, rec = run_import(dst, env, tag)
    # A2: what the target rebuilt from the ledger equals the projection the export carried.
    assert all(p["ok"] for p in rec["projections"].values())
    assert rec["families"]["claims"]["sha256"] == manifest["families"]["claims"]["sha256"]
    with Session(dst) as db:
        assert db.get(Workspace, s.inv).import_state is None
        unit = db.get(Asset, s.unit)
        assert unit.attributes["argus_location"] == "Rack B13"
        # A3: the attachment is the same bytes as in the source.
        att = db.scalar(select(Attachment).where(Attachment.issue_uid == s.issue))
        assert Path(att.storage_path).read_bytes().startswith(b"a photo of the pump")
        assert hashlib.sha256(Path(att.storage_path).read_bytes()).hexdigest() == att.sha256
        # A15: retired records, merge tombstones and Installation history survive.
        assert db.get(Asset, s.retired).record_status == "Retired"
        assert db.get(Asset, s.tomb).merged_into_uid == s.survivor
        inst = ledger.installation_view(db, db.get(Asset, s.installation))
        assert inst["status"] == "Confirmed"
        with Session(src) as sdb:
            def events(d, uid):
                from app.models.ledger import StatusEvent
                return sorted((e.predicate, e.to_status) for e in d.scalars(
                    select(StatusEvent).where(StatusEvent.subject_uid == uid)))
            assert events(db, s.installation) == events(sdb, s.installation)
            assert db.scalar(select(func.count()).select_from(Decision)) == \
                sdb.scalar(select(func.count()).select_from(Decision))
        # A16: Jira keys and URLs still resolve.
        issue = db.scalar(select(Issue).where(Issue.attributes["argus_source_key"].astext == f"{s.fac}-9"))
        assert issue.uid == s.issue and issue.attributes["argus_source_url"].endswith(f"{s.fac}-9")
        # A17: tickets, comments, history, documents, revisions and approvals keep their history.
        assert issue.closed_at == T0 and issue.state == "closed"
        assert db.scalar(select(IssueComment.body).where(IssueComment.issue_uid == s.issue)) == "replaced the gasket"
        assert db.scalar(select(IssueHistory.to_value).where(IssueHistory.issue_uid == s.issue)) == "closed"
        doc = db.get(Document, s.doc)
        revs = {r.revision_number: r for r in db.scalars(select(DocumentRevision).where(
            DocumentRevision.document_uid == s.doc))}
        assert doc.current_revision_uid == revs[2].uid and revs[1].superseded_by_uid == revs[2].uid
        assert revs[1].approved_by == "u-rossi" and revs[1].approved_at == T0
        # A26: historical actors without their identity provider: references, not accounts. Under the
        # default (institutional) profile a known person is their user uid, an unknown one a pseudonym.
        actors = set(db.scalars(select(Decision.actor)))
        assert "u-rossi" in actors and not any("@example.org" in a for a in actors)
        assert any(a.startswith("actor-") and a.endswith("@pseudonym.invalid") for a in actors)
        rossi = db.get(User, "u-rossi")
        assert rossi.oidc_sub == "sub-rossi" and rossi.email == "u-rossi@historical.invalid" and rossi.name is None
        imp = db.get(PortabilityImport, imp_id)
        assert imp.state == "finalized" and imp.reconciliation["signature"]["algorithm"] == "ed25519"
        kinds = [e.kind for e in db.scalars(select(PortabilityEvent).where(PortabilityEvent.subject_id == imp_id)
                                            .order_by(PortabilityEvent.seq))]
        assert kinds[:3] == ["request", "fetch", "fetched"] and kinds[-1] == "finalize"


# =========================================================================== helpers for the rest

def counts(eng, models=(Asset, Issue, IssueComment, Relation, Attachment, Claim, ClaimEvent, Decision,
                        Document, DocumentRevision, User, Workspace)) -> dict:
    with Session(eng) as db:
        return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in models}


def all_counts(eng) -> dict:
    """Every table except the portability bookkeeping: what "active state unchanged" compares."""
    with eng.connect() as c:
        tables = [r[0] for r in c.execute(text(
            "select tablename from pg_tables where schemaname = 'public' and tablename not like 'portability_%' "
            "and tablename <> 'alembic_version' and tablename <> 'app_settings'"))]
        return {t: c.execute(text(f'select count(*) from "{t}"')).scalar() for t in sorted(tables)}


def state_digest(eng, workspaces) -> dict:
    """Authoritative content per family, independent of local sequence numbers and ingestion times."""
    from app.portability.exporter import rows_of
    from app.portability.families import FAMILIES, SEQUENCED_TABLES, Scope
    out = {}
    with Session(eng) as db:
        sc = Scope(workspaces=sorted(workspaces), watermark={t: 10 ** 12 for t in SEQUENCED_TABLES})
        for fam in FAMILIES:
            if not fam.authoritative or fam.name in ("identities",):
                continue
            lines = []
            for _, row in rows_of(db, fam, sc, _HashBlobs(), []):
                row = {k: v for k, v in row.items() if k not in ("seq", "updated_at")}
                lines.append(json.dumps(row, sort_keys=True, default=str))
            out[fam.name] = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
    return out


class _HashBlobs:
    """Blobs by their content hash, without inspecting or storing them (for comparing states)."""

    def add(self, obj, fam, col, kind, row):
        v = getattr(obj, col, None)
        if v is None:
            return None
        data = Path(v).read_bytes() if kind == "file" else bytes(v)
        return f"sha256:{hashlib.sha256(data).hexdigest()}"


def table_digests(eng) -> dict:
    """Every table's content, byte for byte (portability bookkeeping and settings aside): what
    "active state unchanged" compares."""
    with eng.connect() as c:
        tables = [r[0] for r in c.execute(text(
            "select tablename from pg_tables where schemaname = 'public' and tablename not like 'portability_%' "
            "and tablename <> 'alembic_version' and tablename <> 'app_settings'"))]
        return {t: c.execute(text(f'select md5(coalesce(string_agg(x::text, \'|\' order by x::text), \'\')) '
                                  f'from "{t}" x')).scalar() for t in sorted(tables)}


def sequence_highs(eng) -> dict:
    from app.portability.families import SEQUENCED_TABLES
    with eng.connect() as c:
        return {t: c.execute(text(f"select coalesce(max(seq),0) from {t}")).scalar() for t in SEQUENCED_TABLES}


def signed_repo(env, name: str, build) -> str:
    """A repository shaped like a portability repository, built by `build(work)` and published with a
    signed commit and a signed export tag — for content an honest exporter would never write."""
    bare = gitrepo.init_bare(env.tmp / f"{name}.git")
    work = env.tmp / f"{name}-work"
    work.mkdir()
    gitrepo.git(["init", "-q", "-b", "main"], cwd=work)
    (work / gitrepo.IDENTITY_FILE).write_text(json.dumps({"repository_id": str(uuid.uuid4())}))
    (work / gitrepo.CHECKPOINTS / "exp-x").mkdir(parents=True)
    (work / gitrepo.CHECKPOINTS / "exp-x" / "manifest.json").write_text("{}")
    build(work)
    gitrepo.git(["add", "-A"], cwd=work)
    gitrepo.git(["commit", "-q", "-S", "-m", "export-id: exp-x\n"], cwd=work, signer=env.signer)
    gitrepo.git(["tag", "-s", "export/full/2026-10-03@ledger-1", "-m", "export-id: exp-x\n"], cwd=work,
                signer=env.signer)
    gitrepo.git(["push", "-q", bare, "main", "--tags"], cwd=work)
    return bare


# =========================================================================== chain and Git rules

def test_A8_A10_A11_increments_in_order_equal_a_full_export_and_out_of_order_is_refused(dbs, env):
    src, chain_target, full_target, lone_target = dbs(), dbs(), dbs(), dbs()
    s = populate(src, env.tmp)
    first, m1 = run_export(src, env, s)
    with Session(src) as db:                                  # later work at the source
        ledger_service.edit_value(db, s.inv, "rossi@example.org", s.unit, "attr:argus_location", "Rack C1")
        ledger.ingest(db, s.insight, revision="i2", content=insight_json(s.fac, s.oid1, s.oid2, location="Hall 2"),
                      observed_at=T0, parser="insight-fixture")
        db.add(IssueComment(uid=str(uuid.uuid4()), issue_uid=s.issue, author="rossi", body="checked again",
                            created_at=T0))
        db.commit()
    inc, m2 = run_export(src, env, s, mode="incremental", base=first["id"])
    full, m3 = run_export(src, env, s)                        # the same watermark, as one checkpoint
    assert m2["watermark"]["vector"] == m3["watermark"]["vector"]
    assert m2["watermark"]["vector_sha256"] == m3["watermark"]["vector_sha256"]
    assert m2["watermark"]["checkpoint_sequence"] != m3["watermark"]["checkpoint_sequence"]
    assert m2["base"]["export_id"] == first["id"] and inc["git"]["previous_tag"] == first["git"]["tag"]
    assert m2["families"]["claim_events"]["rows"] < m3["families"]["claim_events"]["rows"]

    # A11: the increment alone, without its base, is refused.
    _, report = run_import(lone_target, env, inc["git"]["tag"], root="lone", expect_ready=False)
    assert not report["ready"] and report["chain"]["status"] == "out_of_order"

    # A10: base then increment equals the full checkpoint at the same watermark.
    run_import(chain_target, env, first["git"]["tag"], root="chain")
    run_import(chain_target, env, inc["git"]["tag"], root="chain")
    run_import(full_target, env, full["git"]["tag"], root="full")
    assert state_digest(chain_target, [s.ws, s.inv]) == state_digest(full_target, [s.ws, s.inv])
    with Session(chain_target) as db:
        assert db.get(Asset, s.unit).attributes["argus_location"] == "Rack C1"

    # A8: importing the same commit again changes nothing.
    before = counts(chain_target)
    _, rec = run_import(chain_target, env, inc["git"]["tag"], root="again")
    assert rec.get("already_applied") and counts(chain_target) == before


def test_A4_A5_A7_missing_commits_moved_and_unsigned_tags_and_branches_are_refused(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, _ = run_export(src, env, s)
    cfg = env.cfg("dst")
    with Session(dst) as db:
        def attempt(ref, **source):
            imp = service.create_import(db, "carol", mode="clone", source={"repository": "escrow", "ref": ref,
                                                                            **source}, decisions={}, cfg=cfg)
            db.commit()
            with pytest.raises(service.ServiceError) as e:
                service.fetch_git(db, imp, "carol", cfg)
            assert db.get(PortabilityImport, imp.id).state == "invalid"
            return e.value.code
        assert attempt("main") == "not_a_tag"                                      # A7
        assert attempt("refs/heads/main") == "not_a_tag"
        assert attempt("0" * 40) == "missing_commit"                               # A4
        assert attempt(view["git"]["tag"], expected_commit="1" * 40) == "unexpected_commit"
    # A5: a lightweight (unsigned) tag.
    work = env.cfg("src").work("escrow")
    gitrepo.git(["tag", "export/full/2026-10-03@ledger-999", view["git"]["commit"]], cwd=work)
    gitrepo.git(["push", "-q", "origin", "refs/tags/export/full/2026-10-03@ledger-999"], cwd=work)
    with Session(dst) as db:
        assert attempt("export/full/2026-10-03@ledger-999") == "unsigned"
    # A5: a tag signed by an untrusted key.
    rogue = signing.new_key(env.tmp / "rogue")
    gitrepo.git(["tag", "-s", "export/full/2026-10-03@ledger-998", "-m", "export-id: x", view["git"]["commit"]],
                cwd=work, signer=rogue)
    gitrepo.git(["push", "-q", "origin", "refs/tags/export/full/2026-10-03@ledger-998"], cwd=work)
    with Session(dst) as db:
        assert attempt("export/full/2026-10-03@ledger-998") == "bad_signature"
    # A5: a tag that moved after it was imported here.
    run_import(dst, env, view["git"]["tag"])
    gitrepo.git(["commit", "-q", "--allow-empty", "-S", "-m", "something else"], cwd=work, signer=env.signer)
    gitrepo.git(["tag", "-f", "-s", view["git"]["tag"], "-m", f"export-id: {view['id']}"], cwd=work, signer=env.signer)
    gitrepo.git(["push", "-q", "-f", "origin", f"refs/tags/{view['git']['tag']}"], cwd=work)
    with Session(dst) as db:
        assert attempt(view["git"]["tag"]) == "moved_tag"


def test_A6_A29_a_modified_file_or_a_missing_lfs_object_fails_verification(dbs, env):
    from app.portability import verify as verifier
    src = dbs()
    s = populate(src, env.tmp)
    _, manifest = run_export(src, env, s, publish=False)
    cp = env.cfg("src").export_dir(manifest["export_id"])
    assert verifier.verify(cp, trusted=env.allowed)["report"]["signed_by"] == "argus-portability"

    tampered = env.tmp / "tampered"
    shutil.copytree(cp, tampered)
    chunk = next(tampered.glob("records-assets-*.ndjson.zst"))
    chunk.write_bytes(chunk.read_bytes()[:-3] + b"xyz")
    with pytest.raises(verifier.VerificationError) as e:
        verifier.verify(tampered, trusted=env.allowed)
    assert e.value.code == "checksum_mismatch"

    # Re-computed checksums without the key: the signature no longer covers them.
    resummed = env.tmp / "resummed"
    shutil.copytree(tampered, resummed)
    sums = "".join(f"{chunks.sha256_file(resummed / n)}  {n}\n" for n in sorted(
        p.name for p in resummed.iterdir() if p.name not in ("checksums.sha256", "signature.json")))
    (resummed / "checksums.sha256").write_text(sums)
    with pytest.raises(verifier.VerificationError) as e:
        verifier.verify(resummed, trusted=env.allowed)
    assert e.value.code == "bad_signature"

    # A29: a chunk replaced by a Git LFS pointer is recovered only if its object is available.
    lfs = env.tmp / "lfs"
    shutil.copytree(cp, lfs)
    chunk = next(lfs.glob("catalogue-types-*.ndjson.zst"))      # a chunk stored in Git
    real = chunk.read_bytes()
    digest = hashlib.sha256(real).hexdigest()
    chunk.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:" + digest.encode() +
                      f"\nsize {len(real)}\n".encode())
    pointer = [{"file": chunk.name, "sha256": digest, "size": len(real)}]
    with pytest.raises(verifier.VerificationError) as e:
        verifier.verify(lfs, trusted=env.allowed, stores={"vault": env.store}, lfs=pointer)
    assert e.value.code == "missing_lfs_object"
    env.store.put_bytes(real)
    assert verifier.verify(lfs, trusted=env.allowed, stores={"vault": env.store}, lfs=pointer)["report"]["files"] > 0
    # A4: a blob missing from the artifact store.
    gone = next(iter(json.loads(x) for x in (cp / "blobs.manifest.ndjson").read_text().splitlines()))
    path = env.store._path(gone["sha256"])
    os.chmod(path, 0o644)
    path.unlink()
    with pytest.raises(verifier.VerificationError) as e:
        verifier.verify(cp, trusted=env.allowed, stores={"vault": env.store}, blob_dir=env.tmp / "blobs")
    assert e.value.code == "missing_artifact"


@pytest.mark.parametrize("payload, problem", [
    (lambda w: os.symlink("/etc/passwd", w / gitrepo.CHECKPOINTS / "exp-x" / "link"), "symbolic link"),
    (lambda w: (w / ".gitmodules").write_text('[submodule "x"]\n\tpath = x\n\turl = ../x\n'), "submodule"),
    (lambda w: (lambda p: (p.write_text("#!/bin/sh\nrm -rf /\n"), os.chmod(p, 0o755)))(
        w / gitrepo.CHECKPOINTS / "exp-x" / "run.sh"), "executable payload"),
    (lambda w: (w / "hooks").mkdir() or (lambda p: (p.write_text("#!/bin/sh\n"), os.chmod(p, 0o755)))(
        w / "hooks" / "post-checkout"), "executable payload"),
])
def test_A21_malicious_paths_links_submodules_hooks_and_executables_are_refused(env, payload, problem):
    bare = signed_repo(env, f"bad{secrets.token_hex(2)}", payload)
    with pytest.raises(gitrepo.GitError) as e:
        gitrepo.fetch_into_quarantine(bare, "export/full/2026-10-03@ledger-1", env.tmp / "q", env.allowed)
    assert e.value.code == "unsafe_repository"
    assert any(problem in p for p in e.value.detail["problems"])
    assert not (env.tmp / "q" / "checkpoint").exists() or not any((env.tmp / "q" / "checkpoint").iterdir())


def test_A22_decompression_bombs_oversized_and_malformed_lines_are_rejected(tmp_path):
    import zstandard
    small = chunks.Limits(max_chunk_bytes=1 << 20, max_ratio=50, max_line_bytes=1024)
    bomb = tmp_path / "bomb.ndjson.zst"
    bomb.write_bytes(zstandard.ZstdCompressor().compress(b"0" * (64 << 20)))
    with pytest.raises(chunks.ChunkError, match="decompress"):
        list(chunks.read_chunk(bomb, "assets", small))
    long = tmp_path / "long.ndjson.zst"
    long.write_bytes(zstandard.ZstdCompressor().compress(chunks.line("assets", "k", {"x": secrets.token_hex(3000)})))
    with pytest.raises(chunks.ChunkError, match="longer than"):
        list(chunks.read_chunk(long, "assets", small))
    bad = tmp_path / "bad.ndjson.zst"
    bad.write_bytes(zstandard.ZstdCompressor().compress(b'{"f": "assets", "k": "a", "d": [1]}\n'))
    with pytest.raises(chunks.ChunkError, match="envelope"):
        list(chunks.read_chunk(bad, "assets"))
    other = tmp_path / "other.ndjson.zst"
    other.write_bytes(zstandard.ZstdCompressor().compress(chunks.line("claims", "a", {})))
    with pytest.raises(chunks.ChunkError, match="declared"):
        list(chunks.read_chunk(other, "assets"))
    with pytest.raises(chunks.ChunkError, match="zstd"):
        (tmp_path / "junk.ndjson.zst").write_bytes(b"not zstd at all")
        list(chunks.read_chunk(tmp_path / "junk.ndjson.zst", "assets"))


# =========================================================================== import outcomes

def test_A9_A23_R6_R7_R8_R22_an_isolated_import_resumes_and_a_discard_changes_no_active_byte(dbs, env):
    from app.ledger import audit as ledger_audit
    src, dst, ref = dbs(), dbs(), dbs()
    s = populate(src, env.tmp)
    view, _ = run_export(src, env, s)
    run_import(ref, env, view["git"]["tag"], root="ref")              # a clean import, to compare with

    with Session(dst) as db:                                         # the target has work of its own, sealed
        db.add(Workspace(id="local", name="Local work"))
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        from app.models.ledger import RecordEvent
        db.add(RecordEvent(uid="local-rec", kind="status", before="Active", after="Retired", cause="local",
                           at=yesterday))
        db.flush()
        ledger_audit.seal_day(db, yesterday.date())
        db.commit()
    before, highs = table_digests(dst), sequence_highs(dst)

    # R22: interrupted in staging; nothing of it is in the active database.
    imp_id, _ = run_import(dst, env, view["git"]["tag"], stop_after=4)
    with Session(dst) as db:
        imp = db.get(PortabilityImport, imp_id)
        assert imp.state == "importing" and imp.error["code"] == "interrupted"
        assert len([d for d in imp.checkpoints["done"] if d != "seeded"]) == 4
        assert imp.staging["database"].startswith("argus_stage_")
        assert db.get(Workspace, s.inv) is None and db.get(Asset, s.unit) is None
    assert table_digests(dst) == before
    # R6, R7: a discard drops staging, keeps the audit, deletes nothing active.
    with Session(dst) as db:
        imp = db.get(PortabilityImport, imp_id)
        service.discard(db, imp, "dave@example.org", env.cfg("dst"), reason="wrong checkpoint")
        db.commit()
        kinds = [e.kind for e in db.scalars(select(PortabilityEvent).where(PortabilityEvent.subject_id == imp_id)
                                            .order_by(PortabilityEvent.seq))]
        assert kinds[:4] == ["request", "fetch", "fetched", "verify"] and "approve" in kinds
        assert "staging_created" in kinds and "interrupted" in kinds and kinds[-1] == "discard"
        last = db.scalar(select(PortabilityEvent).where(PortabilityEvent.subject_id == imp_id)
                         .order_by(PortabilityEvent.seq.desc()).limit(1))
        assert last.actor == "dave@example.org" and last.detail["reason"] == "wrong checkpoint"
        assert db.get(PortabilityImport, imp_id).manifest["export_id"] == view["id"]       # what was attempted
        # R8: no watermark moved back, no sealed day changed.
        assert ledger_audit.verify(db)["ok"]
    assert table_digests(dst) == before
    assert all(sequence_highs(dst)[t] >= v for t, v in highs.items())
    with create_engine(_url("postgres"), isolation_level="AUTOCOMMIT").connect() as c:
        assert not c.execute(text("select 1 from pg_database where datname = :n"),
                             {"n": staging.database_name(imp_id)}).first()

    # A9: interrupted again, then resumed in staging and promoted: no duplicate anywhere.
    imp_id, _ = run_import(dst, env, view["git"]["tag"], stop_after=6, root="dst2")
    assert table_digests(dst) == before
    with Session(dst) as db:
        imp = db.get(PortabilityImport, imp_id)
        service.execute(db, imp, "dave@example.org", env.cfg("dst2"))           # resume
        db.commit()
        assert imp.reconciliation["passed"] and imp.state == "ready_to_finalize"
        assert db.get(Workspace, s.inv) is None                                   # still not visible
        service.finalize(db, imp, "dave@example.org", env.cfg("dst2"))
        db.commit()
        dupes = db.scalar(select(func.count()).select_from(
            select(PortabilityRowMap.origin, PortabilityRowMap.family, PortabilityRowMap.source_key)
            .group_by(PortabilityRowMap.origin, PortabilityRowMap.family, PortabilityRowMap.source_key)
            .having(func.count() > 1).subquery()))
        assert dupes == 0
        assert ledger_audit.verify(db)["ok"]
    assert state_digest(dst, [s.ws, s.inv]) == state_digest(ref, [s.ws, s.inv])
    assert counts(dst)["ledger_claims"] == counts(ref)["ledger_claims"]


def test_A12_A13_A14_merge_blocks_divergent_uids_proposes_candidates_and_never_overwrites_types(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, _ = run_export(src, env, s)
    from app.models.schema import Schema
    with Session(src) as sdb:
        schema = sdb.get(Schema, sdb.get(Asset, s.unit).schema_uid)
        schema_row = {c.key: getattr(schema, c.key) for c in Schema.__mapper__.column_attrs}
    with Session(dst) as db:
        db.add(Workspace(id=schema_row["workspace_id"], name="theirs"))
        db.add(Workspace(id="local", name="Local"))
        db.flush()
        # A14: a type with the same id and another definition.
        db.add(Schema(**{**schema_row, "attributes": [{"name": "something_else", "type": "text"}]}))
        db.flush()
        # A12: the same uid with other content, made here.
        db.add(Asset(uid=s.spare, workspace_id="local", key="LOCAL-1", name="Not that pump", type="Ion Pump",
                     schema_uid=schema.uid, attributes={}))
        # A13: an immutable external identifier the archive's unit also holds.
        db.add(Asset(uid=str(uuid.uuid4()), workspace_id="local", key="LOCAL-2", name="Pump", type="Ion Pump",
                     schema_uid=schema.uid, attributes={"serial": "84321"}))
        db.commit()
    before = all_counts(dst)
    _, report = run_import(dst, env, view["git"]["tag"], mode="merge", expect_ready=False)
    assert not report["ready"]
    assert any(b["family"] == "assets" and b["key"] == s.spare for b in report["blocking"])
    assert any(c["family"] == "types" and c["key"] == schema.uid for c in report["catalogue_conflicts"])
    assert any(c["identifier"] == "serial" and c["value"] == "84321" for c in report["identity_candidates"])
    assert all_counts(dst) == before                       # a dry run writes nothing
    with Session(dst) as db:
        assert db.get(Schema, schema.uid).attributes == [{"name": "something_else", "type": "text"}]
        assert db.get(Asset, s.spare).name == "Not that pump"
        imp = db.scalar(select(PortabilityImport).order_by(PortabilityImport.created_at.desc()).limit(1))
        from app.portability.lifecycle import TransitionError
        with pytest.raises((service.ServiceError, TransitionError)):
            service.approve_import(db, imp, "dave@example.org", cfg=env.cfg("dst"))        # not ready: nothing to approve


def test_a_divergent_equipment_class_is_resolvable_keep_local_or_use_the_archive(dbs, env):
    """Unlike an asset or a type (A12/A14 above), an equipment class carries no ledger history and no
    access control — so instead of only ever blocking, the dry run offers a per-record choice
    (importer.CATALOGUE_RESOLVABLE), and the import proceeds once every one is made."""
    from app.models.equipment_class import EquipmentClass
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    t = datetime.now(timezone.utc)
    name = f"Crate {s.ws}"
    with Session(src) as db:
        db.add(EquipmentClass(name=name, status="active", added_by="rossi@example.org", added_at=t,
                              note="from the archive"))
        db.commit()
    with Session(dst) as db:
        db.add(Workspace(id="local", name="Local"))
        db.add(EquipmentClass(name=name, status="deprecated", added_by="local-admin@example.org", added_at=t,
                              note="made here, not by that archive"))
        db.commit()
    view, _ = run_export(src, env, s)

    # No decision yet: it blocks, but names what differs and both options — not a dead end.
    _, report = run_import(dst, env, view["git"]["tag"], mode="merge", expect_ready=False)
    item = next(b for b in report["blocking"] if b["family"] == "equipment_classes" and b["key"] == name)
    assert item["resolvable"] is True
    assert set(item["fields"]) >= {"status", "added_by", "note"}
    assert item["local"]["status"] == "deprecated" and item["archive"]["status"] == "active"
    with Session(dst) as db:
        assert db.get(EquipmentClass, name).status == "deprecated"    # a dry run writes nothing

    # "Keep what's here": the import goes on, and the local record is untouched.
    _, rec = run_import(dst, env, view["git"]["tag"], mode="merge",
                        decisions={"catalogue_conflicts": {f"equipment_classes:{name}": "keep_local"}})
    assert rec["passed"], _failures(rec)
    with Session(dst) as db:
        assert db.get(EquipmentClass, name).status == "deprecated"
        assert db.get(EquipmentClass, name).note == "made here, not by that archive"

    # The same conflict, resolved the other way in a fresh destination (re-importing the same export
    # into the same one is correctly a no-op the second time — "already applied" — so this needs its
    # own): "use the archive's version" overwrites it.
    dst2 = dbs()
    with Session(dst2) as db:
        db.add(Workspace(id="local", name="Local"))
        db.add(EquipmentClass(name=name, status="deprecated", added_by="local-admin@example.org", added_at=t,
                              note="made here, not by that archive"))
        db.commit()
    _, rec2 = run_import(dst2, env, view["git"]["tag"], mode="merge",
                         decisions={"catalogue_conflicts": {f"equipment_classes:{name}": "use_archive"}})
    assert rec2["passed"], _failures(rec2)
    with Session(dst2) as db:
        assert db.get(EquipmentClass, name).status == "active"
        assert db.get(EquipmentClass, name).note == "from the archive"


def test_a_beam_model_admitted_at_the_source_stays_in_effect_after_a_clone_into_a_hub_with_its_own_policy(dbs, env):
    """A beam model's records are claims from its own external stream, in effect only once a policy lists the
    stream. The archive carries the source's policy that admitted it, but a hub that activated a policy of its own
    later keeps that one active — so, loaded alone, the model's records would project empty here (and staging,
    never seeing the hub's policy, used to pass where finalization then failed). The import activates the union."""
    import json as _json
    from app.services import beam_model as bm
    from app.services.asset_types import ensure_asset_types
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    linac = _json.loads((Path(__file__).parent / "fixtures" / "beam_model" / "linac.json").read_text())
    with Session(src) as db:
        ensure_asset_types(db, s.ws)
        ledger.activate_policy(db)
        assert bm.import_canonical(db, s.ws, linac, "test")["awaiting_policy"]
        ledger.activate_policy(db)                                   # governance admits the model's stream
        db.commit()
        admitted = set(ledger.active_policy(db)[1].vocabulary["streams"])
        elements = {a.uid: a.attributes for a in db.scalars(select(Asset).where(
            Asset.workspace_id == s.ws, Asset.attributes["model_id"].astext.isnot(None)))}
    assert admitted and elements
    with Session(dst) as db:
        ledger.activate_policy(db)                                   # the hub's own, newer, admitting nothing
        db.commit()
    view, _ = run_export(src, env, s)
    _, rec = run_import(dst, env, view["git"]["tag"], mode="clone")
    assert rec["passed"], _failures(rec)
    with Session(dst) as db:
        policy = ledger.active_policy(db)[1]
        # Here the union is exactly the archive's own latest policy, so that one is activated again (keeping
        # who first activated it); with local sources of its own it would be a new version, by the import.
        assert admitted <= set(policy.vocabulary["streams"])
        for uid, attrs in elements.items():
            assert db.get(Asset, uid).attributes.get("model_id") == attrs["model_id"]


def test_A13_a_candidate_is_opened_never_merged(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, _ = run_export(src, env, s)
    other = str(uuid.uuid4())
    with Session(dst) as db:
        db.add(Workspace(id="local", name="Local"))
        db.flush()
        pump = ledger.ensure_type(db, "local", "Ion Pump")
        db.add(Asset(uid=other, workspace_id="local", key="LOCAL-2", name="Pump", type="Ion Pump",
                     schema_uid=pump.uid, attributes={"serial": "84321"}))
        db.commit()
    _, rec = run_import(dst, env, view["git"]["tag"], mode="clone", decisions={})
    with Session(dst) as db:
        assert db.get(Asset, other).merged_into_uid is None and db.get(Asset, s.unit).merged_into_uid is None
        assert db.get(Asset, other).record_status != "Merged"


# =========================================================================== what never leaves

def test_A18_A19_A20_restricted_records_and_secrets_never_reach_git_or_the_archive(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    secret_uid, secret_name = str(uuid.uuid4()), f"Budget line {secrets.token_hex(4)}"
    raw_token = secrets.token_urlsafe(24)
    with Session(src) as db:
        from app.auth import hash_token
        from app.models.api_token import ApiToken
        pump = ledger.ensure_type(db, s.inv, "Ion Pump")
        db.add(Asset(uid=secret_uid, workspace_id=s.inv, key=f"{s.fac}-COST", name=secret_name, type="Ion Pump",
                     schema_uid=pump.uid, attributes={"classification": "restricted:costs", "cost": 12345}))
        db.add(Relation(workspace_id=s.inv, from_asset_uid=s.unit, to_asset_uid=secret_uid, relation_type="privately sponsored by"))
        db.add(ApiToken(workspace_id=s.inv, token_hash=hash_token(raw_token)))
        db.commit()
    cfg = env.cfg("src")
    with Session(src) as db:
        exp = service.create_export(db, "alice", mode="workspace", workspaces=[s.ws, s.inv], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque"}, cfg=cfg)
        service.analyse_export(db, exp, "alice", cfg)
        db.commit()
        dep = {d["id"]: d for d in exp.analysis["closure"]["dependencies"]}
        store_before = sorted(p.name for p in env.store.root.rglob("*") if p.is_file())
        assert "restricted_reference" in dep and not exp.analysis["ready"]
        assert all(ex["to"] == "(restricted)" for ex in dep["restricted_reference"]["examples"])
        with pytest.raises(service.ServiceError):
            service.approve_export(db, exp, "bob", admin=True, cfg=cfg)          # never chosen silently
        service.set_export_decisions(db, exp, {"restricted_reference": "exclude_referrers"}, "alice", cfg)
        service.approve_export(db, exp, "bob", admin=True, cfg=cfg)
        assert sorted(p.name for p in env.store.root.rglob("*") if p.is_file()) == store_before   # nothing yet
        service.generate_export(src, db, exp, "bob", cfg)
        service.publish_export(db, exp, "bob", cfg)
        db.commit()
        view = service.export_view(exp)
    assert not view["labels"]["complete"] and view["labels"]["selective"]
    clone = env.tmp / "clone18"
    subprocess.run(["git", "clone", "-q", env.repo, str(clone)], check=True, capture_output=True)
    files: dict[str, bytes] = {}
    for p in clone.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            data = p.read_bytes()
            files[str(p.relative_to(clone))] = __import__("zstandard").ZstdDecompressor().decompressobj().decompress(
                data) if p.name.endswith(".zst") else data
    for stored in env.store.root.rglob("*"):
        if stored.is_file():
            data = stored.read_bytes()
            try:
                data = __import__("zstandard").ZstdDecompressor().decompressobj().decompress(data)
            except Exception:  # noqa: BLE001 — a blob, not a chunk
                pass
            files[f"artifact:{stored.name}"] = data

    def leaks(needle: bytes) -> list[str]:
        return [name for name, data in files.items() if needle in data]
    assert leaks(secret_uid.encode()) == [] and leaks(secret_name.encode()) == []           # A18
    assert leaks(b"privately sponsored by") == [] and leaks(b"12345") == []
    assert leaks(raw_token.encode()) == [] and leaks(b"token_hash") == []                    # A19
    assert leaks(b"PRIVATE KEY") == [] and leaks(env.signer.key_path.read_bytes()) == []
    manifest = json.loads((clone / gitrepo.CHECKPOINTS / view["id"] / "manifest.json").read_text())
    assert manifest["classifications"]["excluded_classes"] == ["costs"]
    assert "restricted" not in json.dumps(manifest["families"])

    # A20: a credential in the data stops the export before anything is published.
    with Session(src) as db:
        db.get(Asset, s.spare).attributes = {**db.get(Asset, s.spare).attributes,
                                             "notes": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"}
        db.commit()
        tags_before = gitrepo.git(["tag", "-l"], cwd=Path(env.repo)).stdout
        exp = service.create_export(db, "alice", mode="workspace", workspaces=[s.ws, s.inv], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"restricted_reference": "exclude_referrers",
                                               "opaque_blobs": "approve_opaque"}, cfg=cfg)
        service.analyse_export(db, exp, "alice", cfg)
        service.approve_export(db, exp, "bob", admin=True, cfg=cfg)
        db.commit()
        stored = sorted(p.name for p in env.store.root.rglob("*") if p.is_file())
        with pytest.raises(service.ServiceError) as e:
            service.generate_export(src, db, exp, "bob", cfg)
        assert e.value.code == "secret_found"
        assert sorted(p.name for p in env.store.root.rglob("*") if p.is_file()) == stored   # R4: no artifact
        assert e.value.detail["findings"][0]["where"].startswith("assets[")
        assert "ghp_" not in json.dumps(e.value.detail)
        assert db.get(PortabilityExport, exp.id).state == "failed"
        assert gitrepo.git(["tag", "-l"], cwd=Path(env.repo)).stdout == tags_before
        assert not env.cfg("src").export_dir(exp.id).exists()


# =========================================================================== modes and closure

def test_A24_an_evidence_import_creates_no_active_projection(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, manifest = run_export(src, env, s)
    before = all_counts(dst)
    imp_id, rec = run_import(dst, env, view["git"]["tag"], mode="evidence")
    assert rec["evidence_only"] and all_counts(dst) == before
    with Session(dst) as db:
        imp = db.get(PortabilityImport, imp_id)
        rows = service.evidence_rows(db, imp, env.cfg("dst"), "claims", 0, 5, viewer=None, actor="carol")
        assert rows["total"] == manifest["families"]["claims"]["rows"] and len(rows["rows"]) == 5


def test_A25_a_selective_export_includes_or_explicitly_resolves_every_dependency(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    cfg = env.cfg("src")
    with Session(src) as db:
        exp = service.create_export(db, "alice", mode="workspace", workspaces=[s.ws], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque"}, cfg=cfg)
        service.analyse_export(db, exp, "alice", cfg)
        db.commit()
        deps = {d["id"]: d for d in exp.analysis["closure"]["dependencies"]}
        assert f"derived_endpoint:{s.inv}" in deps or f"claim_subject:{s.inv}" in deps
        assert not exp.analysis["ready"] and set(exp.analysis["closure"]["unresolved"]) == set(deps)
        with pytest.raises(service.ServiceError):
            service.approve_export(db, exp, "bob", admin=True, cfg=cfg)
        # Including the inventory's workspace closes the dependency.
        service.set_export_decisions(db, exp, {d: "include_workspace" for d in deps
                                               if "include_workspace" in deps[d]["options"]}, "alice", cfg)
        assert exp.analysis["ready"] and s.inv in exp.analysis["closure"]["workspaces"]
        # A blocked dependency stops the export.
        service.set_export_decisions(db, exp, {next(iter(deps)): "block"}, "alice", cfg)
        assert not exp.analysis["ready"] and exp.analysis["closure"]["blocked"]


def test_A27_an_export_at_W_excludes_later_transactions(dbs, env):
    from app.portability.exporter import at_watermark
    src = dbs()
    s = populate(src, env.tmp)
    with at_watermark(src) as (db, wm):
        with Session(src) as writer:                            # commits after W
            ledger_service.edit_value(writer, s.inv, "rossi@example.org", s.unit, "attr:argus_location", "Later")
            writer.commit()
            latest = writer.scalar(select(func.max(Decision.seq)))
        assert latest > wm["vector"]["ledger_decisions"]
        assert db.scalar(select(func.max(Decision.seq))) == wm["vector"]["ledger_decisions"]
        assert db.get(Asset, s.unit).attributes["argus_location"] == "Rack B13"   # records at W, too
        for table, high in wm["vector"].items():
            assert db.execute(text(f"select coalesce(max(seq),0) from {table}")).scalar() == high


def test_A30_the_restore_drill_verifies_the_latest_signed_full_checkpoint(dbs, env):
    from app.portability.__main__ import restore_drill
    src = dbs()
    populate(src, env.tmp)
    with Session(src) as db:                                   # a full export of this instance
        exp = service.create_export(db, "alice", mode="full", workspaces=[], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque"}, cfg=env.cfg("src"))
        service.analyse_export(db, exp, "alice", env.cfg("src"))
        service.approve_export(db, exp, "bob", admin=True, fresh_auth=True, cfg=env.cfg("src"))
        db.commit()
        service.generate_export(src, db, exp, "bob", env.cfg("src"))
        service.publish_export(db, exp, "bob", env.cfg("src"))
        db.commit()
        assert exp.git["tag"].startswith("export/full/") and exp.manifest["labels"]["complete"]
    report = restore_drill(env.cfg("drill"), "escrow", str(src.url.render_as_string(hide_password=False)))
    assert report["passed"], report
    assert report["tag"] == exp.git["tag"] and all(report["families"].values())


# =========================================================================== the API

def test_R19_R21_the_api_enforces_people_step_up_separation_destinations_and_single_use_downloads(env, monkeypatch,
                                                                                                  caplog):
    import logging
    import time

    from fastapi.testclient import TestClient

    from app.auth import OidcIdentity, PatIdentity, get_identity
    from app.db import SessionLocal
    from app.log_redaction import RedactTokens
    from app.main import app
    monkeypatch.setenv("ARGUS_PORTABILITY_ROOT", str(env.tmp / "api"))
    monkeypatch.setenv("ARGUS_PORTABILITY_POLICY", "strict")
    monkeypatch.setenv("ARGUS_PORTABILITY_REPOSITORIES", f"escrow={env.repo},escrow-restricted={env.restricted_repo}")
    monkeypatch.setenv("ARGUS_PORTABILITY_ARTIFACT_STORES", f"vault={env.store.root}")
    monkeypatch.setenv("ARGUS_PORTABILITY_SIGNING_KEY", str(env.signer.key_path))
    monkeypatch.setenv("ARGUS_PORTABILITY_TRUSTED_KEYS", str(env.allowed))
    monkeypatch.setenv("ARGUS_PORTABILITY_DECRYPTION_KEYS", str(env.keys))
    monkeypatch.setenv("ARGUS_PORTABILITY_RESTRICTED_DESTINATIONS", "escrow-restricted=costs|personnel")
    monkeypatch.setenv("ARGUS_PORTABILITY_RECIPIENTS", f"escrow-restricted={env.tmp / 'recipients'}")
    ws = f"api-{secrets.token_hex(3)}"
    db = SessionLocal()
    alice = User(id=f"a-{ws}", email=f"alice-{ws}@example.org", is_admin=True)
    bob = User(id=f"b-{ws}", email=f"bob-{ws}@example.org", is_admin=True)
    eve = User(id=f"e-{ws}", email=f"eve-{ws}@example.org", is_admin=False)
    db.add_all([Workspace(id=ws, name="API"), alice, bob, eve])
    db.flush()
    pump = ledger.ensure_type(db, ws, "Ion Pump")
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=ws, key=f"{ws}-1", name="Pump", type="Ion Pump",
                 schema_uid=pump.uid, attributes={}))
    db.add(Asset(uid=str(uuid.uuid4()), workspace_id=ws, key=f"{ws}-2", name="Budget", type="Ion Pump",
                 schema_uid=pump.uid, attributes={"classification": "restricted:costs"}))
    db.commit()
    for u in (alice, bob, eve):
        db.refresh(u)
        db.expunge(u)
    db.close()
    client = TestClient(app)
    now = time.time()
    person = lambda u, fresh=True: (lambda: OidcIdentity(user=u, claims={"auth_time": now if fresh else now - 3600}))  # noqa: E731
    try:
        app.dependency_overrides[get_identity] = lambda: PatIdentity(workspace_id=ws, restricted_grants=())
        assert client.post("/v1/portability/exports", json={"mode": "workspace", "workspaces": [ws]}).status_code == 403
        app.dependency_overrides[get_identity] = person(eve)
        assert client.post("/v1/portability/exports", json={"mode": "full"}).status_code == 403
        assert client.post("/v1/portability/imports", json={"mode": "clone"}).status_code == 403
        app.dependency_overrides[get_identity] = person(alice)
        cfg = client.get("/v1/portability/config").json()
        assert cfg["repositories"] == ["escrow", "escrow-restricted"] and cfg["artifact_stores"] == ["vault"]
        assert cfg["signing"]["configured"] and cfg["trusted_keys"] and "costs" in cfg["restricted_classes"]
        assert cfg["default_identity_profile"] == "institutional_reference"
        assert str(env.repo) not in json.dumps(cfg)                    # names only, never locations
        # R19: restricted classes only to an approved, encrypted destination.
        r = client.post("/v1/portability/exports", json={"mode": "workspace", "workspaces": [ws], "repository": "escrow",
                                                         "artifact_store": "vault", "classifications": ["costs"]})
        assert r.status_code == 422 and r.json()["problem"]["code"] == "restricted_destination_required"
        r = client.post("/v1/portability/exports", json={"mode": "workspace", "workspaces": [ws],
                                                         "repository": "escrow-restricted", "artifact_store": "vault",
                                                         "classifications": ["costs"], "recipients": ["escrow-officer"],
                                                         # icons other tests gave the shared type are opaque images
                                                         "decisions": {"opaque_blobs": "approve_opaque"}})
        assert r.status_code == 201, r.text
        exp = r.json()
        assert exp["state"] == "awaiting_approval" and exp["risk"] == "high" and exp["analysis"]["ready"]
        r = client.post(f"/v1/portability/exports/{exp['id']}/approve")
        assert r.status_code == 403 and r.json()["problem"]["code"] == "separation"
        app.dependency_overrides[get_identity] = person(bob, fresh=False)
        r = client.post(f"/v1/portability/exports/{exp['id']}/approve")
        assert r.status_code == 401 and r.json()["problem"]["code"] == "step_up_required"
        app.dependency_overrides[get_identity] = person(bob)
        assert client.post(f"/v1/portability/exports/{exp['id']}/approve").json()["state"] == "approved"
        assert client.post(f"/v1/portability/exports/{exp['id']}/approve").json()["state"] == "approved"   # idempotent
        r = client.post(f"/v1/portability/exports/{exp['id']}/generate")
        assert r.json()["state"] == "ready_to_publish", r.text
        assert r.json()["labels"]["encrypted"]
        r = client.post(f"/v1/portability/exports/{exp['id']}/publish-git")
        assert r.status_code == 200, r.text
        tag = r.json()["git"]["tag"]
        manifest = client.get(f"/v1/portability/exports/{exp['id']}/manifest").json()["manifest"]
        assert manifest["encryption"]["algorithm"] == "AES-256-GCM"
        assert manifest["encryption"]["recipients"][0]["recipient"] == "escrow-officer"
        # R21: single-use, bound, short-lived tokens; no-store; redacted from logs.
        tok = client.post(f"/v1/portability/exports/{exp['id']}/download-token").json()["token"]
        logger = logging.getLogger("uvicorn.access")
        record = logger.makeRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1", "GET", f"/v1/portability/exports/x/download?token={tok}", "1.1", 200),
                                   None)
        RedactTokens().filter(record)
        assert tok not in record.getMessage() and "[redacted]" in record.getMessage()
        r = client.get(f"/v1/portability/exports/{exp['id']}/download", headers={"X-Download-Token": tok})
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert r.headers["referrer-policy"] == "no-referrer"
        r = client.get(f"/v1/portability/exports/{exp['id']}/download", headers={"X-Download-Token": tok})
        assert r.status_code == 403 and "already used" in r.json()["problem"]["error"]
        r = client.get(f"/v1/portability/exports/{exp['id']}/download", params={"token": "made-up"})
        assert r.status_code == 400 and r.json()["problem"]["code"] == "query_token_disabled"   # header only
        assert client.get(f"/v1/portability/exports/{exp['id']}/download",
                          headers={"X-Download-Token": "made-up"}).status_code == 403
        with SessionLocal() as sdb:
            from app.models.portability import PortabilityDownloadToken
            old = client.post(f"/v1/portability/exports/{exp['id']}/download-token").json()["token"]
            row = sdb.get(PortabilityDownloadToken, hashlib.sha256(old.encode()).hexdigest())
            assert row.actor == f"bob-{ws}@example.org" and row.manifest_sha256 == exp_sha(client, exp["id"])
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            sdb.commit()
            assert sdb.scalar(select(func.count()).select_from(PortabilityDownloadToken).where(
                PortabilityDownloadToken.token_sha256 == old)) == 0            # stored as a hash only
        r = client.get(f"/v1/portability/exports/{exp['id']}/download", headers={"X-Download-Token": old})
        assert r.status_code == 403 and "expired" in r.json()["problem"]["error"]
        assert client.get(f"/v1/portability/exports/{exp['id']}/archive").status_code == 200
        r = client.post(f"/v1/portability/exports/{exp['id']}/revoke", json={"reason": "test"})
        assert r.json()["state"] == "revoked"
        assert client.post(f"/v1/portability/exports/{exp['id']}/generate").status_code == 409             # invalid transition

        # R20: evidence of the encrypted archive (decrypted for this session), browsed by classification.
        imp = client.post("/v1/portability/imports", json={"mode": "evidence", "repository": "escrow-restricted",
                                                           "ref": tag}).json()
        for step, state in (("fetch-git", "quarantined"), ("verify", "dry_run_ready"), ("dry-run", "awaiting_approval"),
                            ("approve", "approved"), ("execute", "ready_to_finalize"), ("finalize", "finalized")):
            if step == "approve":           # restricted classes inside: the requester may not approve
                r = client.post(f"/v1/portability/imports/{imp['id']}/approve", json={"acknowledge_uninspected": True})
                assert r.status_code == 403 and r.json()["problem"]["code"] == "separation"
                app.dependency_overrides[get_identity] = person(alice)
                view = client.get(f"/v1/portability/imports/{imp['id']}").json()
                if view["manifest"]["blobs"]["inspection"].get("uninspected"):     # opaque icons of other tests
                    r = client.post(f"/v1/portability/imports/{imp['id']}/approve")
                    assert r.status_code == 409 and r.json()["problem"]["code"] == "acknowledgement_required"
            r = client.post(f"/v1/portability/imports/{imp['id']}/{step}",
                            json={"acknowledge_uninspected": True} if step == "approve" else None)
            assert r.status_code == 200 and r.json()["state"] == state, (step, r.text)
        prov = client.get(f"/v1/portability/imports/{imp['id']}/provenance").json()
        assert prov["git"]["tag"] == tag and [e["kind"] for e in prov["events"]][-1] == "finalize"
        seen = client.get(f"/v1/portability/imports/{imp['id']}/evidence/assets").json()
        assert seen["total"] == 1 and seen["rows"][0]["row"]["name"] == "Pump"     # the budget is not counted
        families = {f["family"]: f["visible_rows"] for f in
                    client.get(f"/v1/portability/imports/{imp['id']}/evidence").json()}
        assert families["assets"] == 1
        monkeypatch.setenv("ARGUS_PORTABILITY_EVIDENCE_READERS", f"alice-{ws}@example.org")
        assert client.get(f"/v1/portability/imports/{imp['id']}/evidence/assets").json()["total"] == 2
    finally:
        app.dependency_overrides.pop(get_identity, None)
    with SessionLocal() as db:
        kinds = [e.kind for e in db.scalars(select(PortabilityEvent).where(PortabilityEvent.subject_id == exp["id"])
                                            .order_by(PortabilityEvent.seq))]
        assert kinds[:2] == ["request", "analyse"] and "download_token" in kinds and "download" in kinds
        assert "download_refused" in kinds and kinds.count("approve") == 1 and kinds[-1] == "download_tokens_revoked"
        reads = [e for e in db.scalars(select(PortabilityEvent).where(PortabilityEvent.subject_id == imp["id"],
                                                                      PortabilityEvent.kind == "evidence_read"))]
        assert len(reads) == 2 and reads[-1].detail["restricted_reader"]
        with pytest.raises(Exception):                         # the audit is append-only in the database
            db.execute(text("update portability_events set actor = 'x'"))
            db.flush()


def exp_sha(client, export_id):
    return client.get(f"/v1/portability/exports/{export_id}").json()["manifest_sha256"]


# =========================================================================== what is inside blobs (R1–R4)

def _attach(eng, s, name: str, data: bytes, mime: str, tmp: Path) -> str:
    path = tmp / "files" / f"{secrets.token_hex(3)}-{name}"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    with Session(eng) as db:
        a = Attachment(uid=str(uuid.uuid4()), workspace_id=s.inv, issue_uid=s.issue, filename=name, mime_type=mime,
                       file_size=len(data), storage_path=str(path))
        db.add(a)
        db.commit()
        return hashlib.sha256(data).hexdigest()


def _request(eng, env, s, decisions=None, root="src"):
    cfg = env.cfg(root)
    with Session(eng) as db:
        exp = service.create_export(db, "alice", mode="workspace", workspaces=[s.ws, s.inv], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque", **(decisions or {})}, cfg=cfg)
        service.analyse_export(db, exp, "alice", cfg)
        db.commit()
        return exp.id, exp.analysis


def _artifacts(env) -> list[str]:
    return sorted(p.name for p in env.store.root.rglob("*") if p.is_file())


def test_R1_R4_a_secret_only_inside_a_source_revision_blocks_the_export_and_nothing_is_stored(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    with Session(src) as db:                       # the secret is only in the raw source content
        ledger.ingest(db, s.config, revision="r2", observed_at=T0, parser="epik8s-slice",
                      content=values_yaml(s.fac, s.oid1) + b"\n# deploy key ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8\n")
        db.commit()
    store_before, tags_before = _artifacts(env), gitrepo.git(["tag", "-l"], cwd=Path(env.repo)).stdout
    exp_id, analysis = _request(src, env, s)
    assert not analysis["ready"] and analysis["blobs"]["secrets"]
    where = analysis["blobs"]["secrets"][0]["where"]
    assert where.startswith("source_revisions[") and where.endswith(".content")
    assert "ghp_" not in json.dumps(analysis)                   # the kind and place, never the value
    # Even generated directly, past the analysis, it stops before storing anything.
    out = env.tmp / "direct"
    with pytest.raises(exporter.ExportError) as e:
        exporter.generate(src, export_id="exp-direct", mode="workspace", workspaces=[s.ws, s.inv], out_dir=out,
                          store=env.store, signer=env.signer, requested_by="alice",
                          decisions={"opaque_blobs": "approve_opaque"})
    assert e.value.code == "secret_found" and not out.exists()
    assert not (env.tmp / ".direct.staging").exists()
    assert _artifacts(env) == store_before                                   # R4
    assert gitrepo.git(["tag", "-l"], cwd=Path(env.repo)).stdout == tags_before


def test_R2_R3_attachments_are_inspected_classified_or_held_for_a_decision(dbs, env):
    src = dbs()
    s = populate(src, env.tmp)
    secret = _attach(src, s, "settings.yaml", b"service:\n  api_key: Zk3Qw9Lm2Xp7Rt5Vy8Bn4Jh6\n", "text/yaml", env.tmp)
    _, analysis = _request(src, env, s)
    assert any(f["where"].endswith(".storage_path") for f in analysis["blobs"]["secrets"]) and not analysis["ready"]
    with Session(src) as db:                                    # corrected at the source
        db.execute(text("delete from attachments where filename = 'settings.yaml'"))
        db.commit()
    marked = _attach(src, s, "report.txt", b"STRICTLY CONFIDENTIAL - internal review\n", "text/plain", env.tmp)
    png = _attach(src, s, "scan.png", b"\x89PNG\r\n\x1a\n" + os.urandom(64), "image/png", env.tmp)
    photo = hashlib.sha256(b"a photo of the pump " + s.fac.encode()).hexdigest()
    _, analysis = _request(src, env, s, decisions={"opaque_blobs": None})
    need = {b["id"]: b for b in analysis["blobs"]["needs_decision"]}
    assert need[f"blob:{marked}"]["status"] == "finding" and "accept_classified" in need[f"blob:{marked}"]["options"]
    assert need[f"blob:{png}"]["status"] == "opaque" and "approve_opaque" in need[f"blob:{png}"]["options"]
    assert not analysis["ready"] and secret not in json.dumps(analysis)
    # Decided: the marked report excluded, the scan approved as opaque.
    exp_id, analysis = _request(src, env, s, decisions={"opaque_blobs": None, f"blob:{marked}": "exclude",
                                                        f"blob:{png}": "approve_opaque",
                                                        f"blob:{photo}": "approve_opaque"})
    assert analysis["blobs"]["ready"], analysis["blobs"]
    cfg = env.cfg("src")
    with Session(src) as db:
        exp = db.get(PortabilityExport, exp_id)
        assert exp.analysis["ready"], exp.analysis
        service.approve_export(db, exp, "bob", admin=True, cfg=cfg)
        service.generate_export(src, db, exp, "bob", cfg)
        db.commit()
        manifest = exp.manifest
    rows = []
    for c in manifest["families"]["attachments"]["chunks"]:
        rows += [r for _, r in chunks.read_chunk(cfg.export_dir(exp_id) / c["file"], "attachments")]
    by_name = {r["filename"]: r for r in rows}
    assert by_name["report.txt"]["storage_path"] is None                     # excluded: no blob travels
    assert by_name["scan.png"]["storage_path"] == f"sha256:{png}"
    assert env.store.has(png) and not env.store.has(marked)
    assert manifest["blobs"]["excluded"] == 1 and not manifest["labels"]["complete"]


# =========================================================================== isolation and the origin chain

def test_R5_R23_a_staged_import_is_invisible_until_one_atomic_promotion(dbs, env):
    from app.services import mcp_tools
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    view, _ = run_export(src, env, s)
    with Session(dst) as db:
        db.add(Workspace(id="local", name="Local work"))
        db.commit()
    before = table_digests(dst)
    imp_id, _ = run_import(dst, env, view["git"]["tag"], mode="merge", finalize=False)
    # R5: staged and reconciled, yet the active database holds nothing of it: no API, search, graph,
    # AI retrieval, projector or export can see what is not there.
    assert table_digests(dst) == before
    with Session(dst) as db:
        assert db.get(Workspace, s.inv) is None and db.get(Asset, s.unit) is None
        found = mcp_tools.search_objects(db, s.inv, "pump")
        assert found.get("total", 0) == 0
    with exporter.at_watermark(dst) as (rdb, _wm):
        assert rdb.get(Workspace, s.inv) is None
    # R23: during promotion another connection still sees nothing; after commit, everything.
    seen = {}

    def probe():
        with dst.connect() as other:
            seen["workspaces"] = other.execute(text("select count(*) from workspaces where id in (:a, :b)"),
                                               {"a": s.ws, "b": s.inv}).scalar()
            seen["assets"] = other.execute(text("select count(*) from assets where workspace_id = :w"),
                                           {"w": s.inv}).scalar()
    cfg = env.cfg("dst")
    with Session(dst) as db:
        imp = db.get(PortabilityImport, imp_id)
        service.finalize(db, imp, "dave@example.org", cfg, probe=probe)
        db.commit()
    assert seen == {"workspaces": 0, "assets": 0}
    with Session(dst) as db:
        assert db.get(Workspace, s.inv) is not None
        with Session(src) as sdb:
            assert db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == s.inv)) == \
                sdb.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == s.inv))


def test_R9_R10_R11_imports_never_change_sealed_days_and_keep_a_verifiable_origin_chain(dbs, env):
    from app.ledger import audit as ledger_audit
    from app.models.ledger import ClaimEvent as CE
    from app.models.portability import PortabilityOriginRecord
    src, cloned, merged = dbs(), dbs(), dbs()
    s = populate(src, env.tmp)
    view, manifest = run_export(src, env, s)
    for eng, mode in ((cloned, "clone"), (merged, "merge")):
        with Session(eng) as db:                 # a local day, sealed before anything arrives
            db.add(Workspace(id="local", name="Local"))
            day = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)       # the same day the archive's events claim
            from app.models.ledger import RecordEvent
            db.add(RecordEvent(uid="local-rec", kind="status", before="Active", after="Retired", cause="local", at=day))
            db.flush()
            sealed = ledger_audit.seal_day(db, day.date())
            digest = sealed.digest
            db.commit()
        imp_id, rec = run_import(eng, env, view["git"]["tag"], mode=mode, root=f"dst-{mode}")
        with Session(eng) as db:
            # R9: the sealed day is unchanged although imported events carry its date as `at`.
            from app.models.ledger import AuditDigest
            assert db.get(AuditDigest, day.date()).digest == digest and ledger_audit.verify(db)["ok"]
            imported = db.scalars(select(CE)).all()
            assert imported and all(e.at < e.recorded_at for e in imported)
            assert all(e.recorded_at.date() == datetime.now(timezone.utc).date() for e in imported)
            # R10: the origin chain verifies against the rows here.
            check = importer.verify_chain(db, imp_id)
            assert check["ok"], check
            # R11: one ingestion event, naming the checkpoint and the chain; every origin record points at it
            # and carries the hash of its exact archive line.
            ev = db.scalar(select(PortabilityEvent).where(PortabilityEvent.subject_id == imp_id,
                                                          PortabilityEvent.kind == "ingested"))
            assert ev.detail["origin_instance_id"] == manifest["argus"]["instance_id"]
            assert ev.detail["origin_checkpoint_hash"] == view["manifest_sha256"]
            records = db.scalars(select(PortabilityOriginRecord).where(PortabilityOriginRecord.import_id == imp_id)
                                 .order_by(PortabilityOriginRecord.position)).all()
            assert records and {r.local_ingestion_event_id for r in records} == {ev.seq}
            lines = {}
            for name in ("claim_events", "decisions"):
                for c in manifest["families"][name]["chunks"]:
                    for key, row in chunks.read_chunk(env.cfg("src").export_dir(view["id"]) / c["file"], name):
                        lines[(name, key)] = hashlib.sha256(chunks.line(name, key, row)).hexdigest()
            for r in records:
                if (r.origin_family, r.origin_sequence) in lines:
                    assert r.origin_event_hash == lines[(r.origin_family, r.origin_sequence)]
            assert check["origin_chain_sha256"] == ev.detail["origin_chain_sha256"]
            # Tampering with an imported row is found.
            victim = db.scalar(select(CE).limit(1))
            db.execute(text("ALTER TABLE ledger_claim_events DISABLE TRIGGER ledger_claim_events_append_only"))
            db.execute(text("UPDATE ledger_claim_events SET kind = 'tampered' WHERE seq = :s"), {"s": victim.seq})
            db.expire_all()
            assert not importer.verify_chain(db, imp_id)["ok"]
            db.rollback()


# =========================================================================== identity profiles (R12, R13)

def _all_rows(cp: Path, manifest: dict) -> dict:
    out = {}
    for name, fam in manifest["families"].items():
        out[name] = [r for c in fam["chunks"] for _, r in chunks.read_chunk(cp / c["file"], name)]
    return out


def test_R12_R13_identity_profiles_decide_what_travels_about_people(dbs, env, monkeypatch):
    src = dbs()
    s = populate(src, env.tmp)
    with Session(src) as db:
        db.get(User, "u-rossi").dn = "uid=rossi,ou=people,dc=example,dc=org"
        db.commit()
    # R13: the default profile, selective export: no e-mail, no DN, no display name anywhere.
    view, manifest = run_export(src, env, s, publish=False)
    rows = _all_rows(env.cfg("src").export_dir(view["id"]), manifest)
    blob = json.dumps(rows)
    assert manifest["identity"]["profile"] == "institutional_reference" and view["risk"] == "normal"
    assert "@example.org" not in blob and "dc=example" not in blob and "M. Rossi" not in blob
    [rossi] = [r for r in rows["identities"] if r["id"] == "u-rossi"]
    assert set(rossi) == {"id", "oidc_sub", "source", "active", "actor_type"}
    assert {d["actor"] for d in rows["decisions"]} >= {"u-rossi"}
    # R12: full identity — everything about the person, high-risk.
    view, manifest = run_export(src, env, s, publish=False, identity_profile="full_identity", root="src-full")
    rows = _all_rows(env.cfg("src-full").export_dir(view["id"]), manifest)
    [rossi] = [r for r in rows["identities"] if r["id"] == "u-rossi"]
    assert rossi["email"] == "rossi@example.org" and rossi["dn"].startswith("uid=rossi") and rossi["name"] == "M. Rossi"
    assert view["risk"] == "high" and any(d["actor"] == "operator@example.org" for d in rows["decisions"])
    # R12: pseudonymized — a salted institutional pseudonym, the same for every action of a person.
    monkeypatch.setenv("ARGUS_PORTABILITY_PSEUDONYM_SALT", "institutional-secret")
    view, manifest = run_export(src, env, s, publish=False, identity_profile="pseudonymized", root="src-pseudo")
    rows = _all_rows(env.cfg("src-pseudo").export_dir(view["id"]), manifest)
    blob = json.dumps(rows)
    assert "u-rossi" not in blob and "@example.org" not in blob and "sub-rossi" not in blob
    pseudo = [r for r in rows["identities"]]
    assert all(r["id"].startswith("actor-") and "email" not in r for r in pseudo)
    assert any("issuer_hash" in r for r in pseudo)
    rossi_ref = next(r["id"] for r in pseudo if r.get("issuer_hash"))
    assert sum(1 for d in rows["decisions"] if d["actor"] == rossi_ref) >= 1          # actions still grouped
    assert manifest["identity"]["salt_key_id"] and "institutional-secret" not in json.dumps(manifest)


# =========================================================================== chunks outside Git (R14–R16)

def test_R14_R15_R16_bulk_chunks_are_artifacts_fetched_verified_and_never_in_git(dbs, env):
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    first, m1 = run_export(src, env, s)
    with Session(src) as db:
        ledger_service.edit_value(db, s.inv, "rossi@example.org", s.unit, "attr:argus_location", "Rack C2")
        db.commit()
    second, m2 = run_export(src, env, s)
    external = [c for f in m2["families"].values() for c in f["chunks"] if c["storage"] == "artifact"]
    in_git = [c for f in m2["families"].values() for c in f["chunks"] if c["storage"] == "git"]
    assert external and all(f["group"] in ("catalogue", "governance", "access")
                            for f in m2["families"].values() for c in f["chunks"] if c["storage"] == "git")
    # R16: Git holds no ledger, record or projection chunk, in any checkpoint.
    tree = gitrepo.git(["ls-tree", "-r", "--name-only", "main"], cwd=Path(env.repo)).stdout.split()
    assert not [p for p in tree if "/ledger-" in p or "/records-" in p or "/projection-" in p]
    assert len([p for p in tree if p.endswith(".ndjson.zst")]) == len(in_git) + sum(
        1 for f in m1["families"].values() for c in f["chunks"] if c["storage"] == "git")
    bulk = sum(c["bytes"] for c in external)
    assert second["git"]["repository_bytes"] > 0 and bulk > 0
    # R14: an import fetches every external chunk by locator and verifies it.
    imp_id, rec = run_import(dst, env, second["git"]["tag"])
    with Session(dst) as db:
        assert db.get(PortabilityImport, imp_id).verification["checkpoint"]["external_chunks"] == len(external)
    # R15: a modified, then a missing, external chunk blocks the import.
    victim = env.store._path(external[0]["sha256"])
    original = victim.read_bytes()
    os.chmod(victim, 0o644)
    victim.write_bytes(original[:-4] + b"evil")
    other = dbs()
    with Session(other) as db:
        cfg = env.cfg("dst-bad")
        imp = service.create_import(db, "carol", mode="clone", source={"repository": "escrow",
                                                                       "ref": second["git"]["tag"]}, decisions={},
                                    cfg=cfg)
        db.commit()
        service.fetch_git(db, imp, "carol", cfg)
        with pytest.raises(service.ServiceError) as e:
            service.verify_import(db, imp, "carol", cfg)
        assert e.value.code == "missing_chunk"
    victim.unlink()
    with Session(other) as db:
        cfg = env.cfg("dst-missing")
        imp = service.create_import(db, "carol", mode="clone", source={"repository": "escrow",
                                                                       "ref": second["git"]["tag"]}, decisions={},
                                    cfg=cfg)
        db.commit()
        service.fetch_git(db, imp, "carol", cfg)
        with pytest.raises(service.ServiceError) as e:
            service.verify_import(db, imp, "carol", cfg)
        assert e.value.code == "missing_chunk" and "missing" in str(e.value)
    victim.write_bytes(original)


# =========================================================================== the watermark (R17, R18)

def test_R17_watermark_identity_is_the_whole_vector():
    from app.portability.families import SEQUENCED_TABLES
    import random
    seen = {}
    rnd = random.Random(7)
    for _ in range(5000):
        v = {t: rnd.randrange(0, 50) for t in SEQUENCED_TABLES}
        h = exporter.vector_sha256(v)
        key = tuple(sorted(v.items()))
        assert seen.setdefault(h, key) == key                 # different vectors, different hashes
    a = {t: i for i, t in enumerate(SEQUENCED_TABLES)}
    b = dict(reversed(list(a.items())))
    assert exporter.vector_sha256(a) == exporter.vector_sha256(b)     # canonical: order does not matter
    c = dict(a)
    t1, t2 = SEQUENCED_TABLES[0], SEQUENCED_TABLES[1]
    c[t1], c[t2] = a[t1] + 1, a[t2] - 1                       # the same sum, another vector
    assert sum(c.values()) == sum(a.values()) and exporter.vector_sha256(c) != exporter.vector_sha256(a)


def test_R18_an_increment_on_another_base_vector_is_refused(dbs, env):
    from app.models.portability import PortabilityChainLink
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    first, _ = run_export(src, env, s)
    with Session(src) as db:
        ledger_service.edit_value(db, s.inv, "rossi@example.org", s.unit, "attr:argus_location", "Rack C3")
        db.commit()
    inc, _ = run_export(src, env, s, mode="incremental", base=first["id"])
    run_import(dst, env, first["git"]["tag"])
    with Session(dst) as db:                     # what was applied here claims another watermark
        link = db.scalar(select(PortabilityChainLink).where(PortabilityChainLink.export_id == first["id"]))
        link.vector_sha256 = "0" * 64
        db.commit()
    _, report = run_import(dst, env, inc["git"]["tag"], root="inc", expect_ready=False)
    assert not report["ready"] and "vector differs" in report["chain"]["problem"]


# =========================================================================== every mode end to end (R24)

def test_R24_restore_merge_and_selective_run_end_to_end(dbs, env):
    from app.models.app_setting import AppSetting
    src, restored, merged, selected = dbs(), dbs(), dbs(), dbs()
    s = populate(src, env.tmp)
    with Session(src) as db:                      # a full export of the source instance, people included
        exp = service.create_export(db, "alice", mode="full", workspaces=[], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque"}, cfg=env.cfg("src"),
                                    identity_profile="full_identity")
        service.analyse_export(db, exp, "alice", env.cfg("src"))
        service.approve_export(db, exp, "bob", admin=True, fresh_auth=True, cfg=env.cfg("src"))
        db.commit()
        service.generate_export(src, db, exp, "bob", env.cfg("src"))
        service.publish_export(db, exp, "bob", env.cfg("src"))
        db.commit()
        tag, origin = exp.git["tag"], exp.manifest["argus"]["instance_id"]
    # restore: an empty instance becomes the source instance.
    run_import(restored, env, tag, mode="restore", root="restore")
    with Session(restored) as db:
        assert db.get(AppSetting, "portability.instance").value["id"] == origin
        assert db.get(Asset, s.unit).attributes["argus_location"] == "Rack B13"
    assert state_digest(restored, [s.ws, s.inv]) == state_digest(src, [s.ws, s.inv])
    # merge: alongside the target's own workspace, which stays as it was.
    with Session(merged) as db:
        db.add(Workspace(id="theirs", name="Their work"))
        db.commit()
    run_import(merged, env, tag, mode="merge", root="merge")
    with Session(merged) as db:
        assert db.get(Workspace, "theirs") is not None and db.get(Workspace, s.inv) is not None
        assert db.get(AppSetting, "portability.instance") is None or \
            db.get(AppSetting, "portability.instance").value["id"] != origin
    # selective: only the inventory workspace (its records do not depend on the configuration's).
    run_import(selected, env, tag, mode="selective", root="sel", decisions={"select_workspaces": [s.inv],
                                                                            "unresolved_references": "defer"})
    with Session(selected) as db:
        assert db.get(Workspace, s.inv) is not None and db.get(Asset, s.unit) is not None
        # The configuration workspace was not chosen: none of its records or streams came. (Types it owns
        # come with the catalogue, under a stub owner workspace of the same id.)
        assert db.get(Asset, s.installation) is None
        assert db.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == s.ws)) == 0
        from app.models.ledger import LedgerStream
        assert db.scalar(select(func.count()).select_from(LedgerStream).where(LedgerStream.workspace_id == s.ws)) == 0


def test_built_in_roles_made_by_each_installation_never_block_an_import(dbs, env):
    """Both installations make the built-in roles themselves, at different times: the same role is not
    'divergent' because its timestamps differ (the first local-to-production import was blocked by it)."""
    from app.models.role import Role, RoleBinding
    from app.services.roles import ensure_system_roles
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    with Session(src) as db:
        ensure_system_roles(db)
        db.add(RoleBinding(workspace_id=s.ws, subject_type="user", subject_id="u-rossi", role_id="viewer",
                           created_at=datetime.now(timezone.utc)))
        db.commit()
    with Session(dst) as db:
        ensure_system_roles(db)
        db.query(Role).filter(Role.is_system.is_(True)).update(
            {Role.created_at: datetime(2030, 1, 1, tzinfo=timezone.utc), Role.updated_at: datetime(2030, 1, 1, tzinfo=timezone.utc)})
        db.commit()
    # The same relation stored twice by an older import, created microseconds apart (seen in ELI).
    with Session(src) as db:
        a, b = db.scalars(select(Asset.uid).where(Asset.workspace_id == s.ws).limit(2)).all()
        t0 = datetime.now(timezone.utc)
        db.add_all([Relation(workspace_id=s.ws, from_asset_uid=a, to_asset_uid=b, relation_type="enabled by",
                             created_at=t0 + timedelta(microseconds=n)) for n in (1, 2)])
        db.commit()
    view, manifest = run_export(src, env, s)
    assert manifest["families"]["roles"]["rows"] >= 1
    _, report = run_import(dst, env, view["git"]["tag"], expect_ready=False)
    assert report["ready"], report.get("blocking")
    assert report["families"]["roles"].get("identical", 0) >= 1 and not report["families"]["roles"].get("divergent")
    # …and the reconciliation in staging, then the finalization, pass with both (the import that reached
    # reconciling in production failed on exactly these two).
    _, reconciliation = run_import(dst, env, view["git"]["tag"])
    assert reconciliation["passed"], {k: v["mismatches"][:2] for k, v in reconciliation["families"].items() if not v["ok"]}


def test_a_background_step_reports_how_far_it_has_got():
    from app.db import SessionLocal
    from app.portability import jobs

    def step(db):
        for n in (0, 50, 100):
            jobs.report("checking assets", n, 100, force=True)
    job = jobs.start(SessionLocal, "import", f"imp-progress-{uuid.uuid4().hex[:6]}", "dry-run", "tester", step, wait=True)
    assert job["state"] == "completed"
    assert job["metrics"]["progress"] == {**job["metrics"]["progress"], "stage": "checking assets", "done": 100,
                                          "total": 100, "percent": 100.0}
    jobs.report("outside a job", 1, 2)             # a step run synchronously reports nowhere, and does not fail


def test_beam_models_global_values_groups_and_equipment_classes_travel(dbs, env):
    """The first local-to-production import left the beam model's layout and element data, the global values,
    the groups granted roles and the equipment classes behind: the archive did not carry them."""
    from app.models.beam_model import BeamAssetBinding, BeamModelDocument, BeamModelValue
    from app.models.equipment_class import EquipmentClass, EquipmentClassReview
    from app.models.global_value import GlobalValue
    from app.models.group import Group, GroupMember
    from app.models.role import RoleBinding
    from app.services.roles import ensure_system_roles
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    t = datetime.now(timezone.utc)
    with Session(src) as db:
        ensure_system_roles(db)
        a, b, c = db.scalars(select(Asset.uid).where(Asset.workspace_id == s.ws).order_by(Asset.uid).limit(3)).all()
        db.add(BeamModelDocument(workspace_id=s.ws, model_id="ring", revision="r1", current=True,
                                 document={"schema": "argus.beam-model/2", "layout": {"x": [0, 1]}}, report={},
                                 imported_by="rossi@example.org", imported_at=t))
        db.add(BeamModelValue(workspace_id=s.ws, dataset_uid=a, subject_uid=b, path_uid=c, s=1.5, x=0.1,
                              optics={"beta_x": 3.2}))
        db.add(BeamAssetBinding(workspace_id=s.ws, model_id="ring", component_id="QF1", component_uid=b,
                                relation="implemented_by", asset_uid=c, status="confirmed", authority="person",
                                confidence=0.9, evidence=[], method="manual", created_at=t, updated_at=t))
        db.add(GlobalValue(uid=f"gv-{s.ws}", workspace_id=s.ws, name="Status", key="status", type="enumeration",
                           options=[{"id": "ok", "label": "OK"}]))
        db.add(EquipmentClass(name=f"Crate {s.ws}", status="active", added_by="rossi@example.org", added_at=t))
        db.add(EquipmentClassReview(class_name=f"Crate {s.ws}", triggers={"count": 12}, status="open", opened_at=t))
        db.add(Group(uid=f"g-{s.ws}", name="Vacuum team", source="directory"))
        db.flush()
        db.add(GroupMember(group_uid=f"g-{s.ws}", user_id="u-rossi", source="directory", created_at=t))
        db.add(RoleBinding(workspace_id=s.ws, subject_type="group", subject_id=f"g-{s.ws}", role_id="viewer",
                           created_at=t))
        db.commit()
    with Session(dst) as db:
        ensure_system_roles(db)
        db.commit()
    view, manifest = run_export(src, env, s)
    for fam in ("beam_model_documents", "beam_model_values", "beam_asset_bindings", "global_values",
                "equipment_classes", "equipment_class_reviews", "groups", "group_members"):
        assert manifest["families"][fam]["rows"] >= 1, fam
    _, reconciliation = run_import(dst, env, view["git"]["tag"])
    assert reconciliation["passed"], {k: v["mismatches"][:2] for k, v in reconciliation["families"].items() if not v["ok"]}
    with Session(dst) as db:
        doc = db.scalar(select(BeamModelDocument).where(BeamModelDocument.model_id == "ring"))
        assert doc.document["layout"] == {"x": [0, 1]} and doc.current
        assert db.scalar(select(BeamModelValue).where(BeamModelValue.subject_uid == b)).optics == {"beta_x": 3.2}
        assert db.scalar(select(BeamAssetBinding).where(BeamAssetBinding.component_id == "QF1")).status == "confirmed"
        assert db.get(GlobalValue, f"gv-{s.ws}").options[0]["label"] == "OK"
        assert db.get(EquipmentClass, f"Crate {s.ws}") is not None
        assert db.scalar(select(GroupMember).where(GroupMember.group_uid == f"g-{s.ws}")).user_id == "u-rossi"


def test_a_second_full_export_fills_in_what_the_first_import_lacked(dbs, env):
    """Production already holds the first import: a new full export from the same installation imports on top,
    finding everything already there identical and creating only what is new (the beam model)."""
    from app.models.beam_model import BeamModelDocument
    from app.services.roles import ensure_system_roles
    src, dst = dbs(), dbs()
    s = populate(src, env.tmp)
    for eng in (src, dst):
        with Session(eng) as db:
            ensure_system_roles(db)
            db.commit()
    first, _ = run_export(src, env, s)
    run_import(dst, env, first["git"]["tag"])
    with Session(src) as db:
        db.add(BeamModelDocument(workspace_id=s.ws, model_id="linac", revision="r1", current=True,
                                 document={"layout": {}}, report={}, imported_by="rossi@example.org",
                                 imported_at=datetime.now(timezone.utc)))
        db.commit()
    second, _ = run_export(src, env, s)
    _, report = run_import(dst, env, second["git"]["tag"], expect_ready=False)
    assert report["ready"], (report.get("blocking"), report.get("chain"))
    assert report["families"]["beam_model_documents"]["create"] == 1
    assert report["families"]["assets"].get("identical", 0) > 0 and not report["families"]["assets"].get("create")
    _, reconciliation = run_import(dst, env, second["git"]["tag"])
    assert reconciliation["passed"]
    with Session(dst) as db:
        assert db.scalar(select(BeamModelDocument).where(BeamModelDocument.model_id == "linac")) is not None


def test_a_new_installations_empty_default_workspace_does_not_block_a_restore(dbs, env):
    """A new installation makes a default workspace ("main"); restore needs an empty instance, and a workspace
    nobody has put anything in leaves it empty. One holding records still blocks it."""
    src, fresh, used = dbs(), dbs(), dbs()
    s = populate(src, env.tmp)
    with Session(src) as db:
        exp = service.create_export(db, "alice", mode="full", workspaces=[], classifications=[],
                                    destination={"repository": "escrow", "artifact_store": "vault"},
                                    decisions={"opaque_blobs": "approve_opaque"}, cfg=env.cfg("src"),
                                    identity_profile="full_identity")
        service.analyse_export(db, exp, "alice", env.cfg("src"))
        service.approve_export(db, exp, "bob", admin=True, fresh_auth=True, cfg=env.cfg("src"))
        db.commit()
        service.generate_export(src, db, exp, "bob", env.cfg("src"))
        service.publish_export(db, exp, "bob", env.cfg("src"))
        db.commit()
        tag = exp.git["tag"]
    with Session(fresh) as db:
        db.add(Workspace(id="main", name="Main"))
        db.commit()
    run_import(fresh, env, tag, mode="restore", root="restore-fresh")
    with Session(fresh) as db:
        assert db.get(Asset, s.unit) is not None
    with Session(used) as db:
        db.add(Workspace(id="main", name="Main"))
        db.flush()
        from app.models.document import Document
        db.add(Document(uid="mine-1", workspace_id="main", code="MINE-1", title="Mine"))
        db.commit()
    _, report = run_import(used, env, tag, mode="restore", root="restore-used", expect_ready=False)
    assert not report["ready"] and any(b["family"] == "instance" for b in report["blocking"])
