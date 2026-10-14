"""Operator commands for portable exports and imports (docs/operations.md, "Portable exports").

    python -m app.portability export   --mode workspace --workspace W [--workspace …] --by ACTOR
                                       [--repository NAME] [--store NAME] [--decide DEP=OUTCOME …]
    python -m app.portability approve  EXPORT_ID --by APPROVER
    python -m app.portability generate EXPORT_ID --by ACTOR
    python -m app.portability publish  EXPORT_ID --by ACTOR
    python -m app.portability import   --mode clone --repository NAME --ref TAG --by ACTOR
    python -m app.portability step     IMPORT_ID fetch|verify|dry-run|approve|execute|finalize|discard --by ACTOR
    python -m app.portability drill    --repository NAME [--prefix export/full/] [--by ADMIN]
    python -m app.portability drill-signoff DRILL_ID --by ADMIN [--note TEXT]
    python -m app.portability cycle    --repository NAME --store NAME --by ADMIN
    python -m app.portability cleanup  [--dry-run]
    python -m app.portability legal-hold (export|import) ID --by ADMIN (--reason TEXT | --release)
    python -m app.portability policy
    python -m app.portability schemas  --out DIR

The same lifecycles and audit as the API; the actor is recorded as given (an operator's name,
`--by` on the command line), and separation of duties applies as there.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.portability import PortabilityExport, PortabilityImport
from app.portability import exporter, gitrepo, service
from app.portability import policy as policy_mod

BACKEND = Path(__file__).resolve().parents[2]


def _print(obj) -> None:
    print(json.dumps(obj, indent=1, default=str))


def latest_tag(cfg: service.Config, repository: str, prefix: str = "export/full/") -> str:
    """The newest signed export tag of a repository, by its ledger watermark."""
    url = cfg.repositories[repository]
    out = subprocess.run(["git", "ls-remote", "--tags", "--refs", url, f"refs/tags/{prefix}*"], capture_output=True,
                         text=True, env=gitrepo._env(cfg.git_env(repository)), timeout=120, check=True).stdout
    tags = [line.split("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
    if not tags:
        raise SystemExit(f"no {prefix}* tag in {repository}")
    return max(tags, key=_checkpoint_of)


def _checkpoint_of(tag: str) -> int:
    """The checkpoint number a tag names (`…@cp<n>-<vector hash>`); never repeats or goes back."""
    m = re.search(r"@cp(\d+)-[0-9a-f]+$", tag)
    return int(m.group(1)) if m else -1


def restore_drill(cfg: service.Config, repository: str, database_url: str, prefix: str = "export/full/",
                  keep: bool = False) -> dict:
    """Fetch the latest signed checkpoint, import it into a scratch database at the current schema
    head, reconcile, and drop the database. The report is the drill's evidence."""
    tag = latest_tag(cfg, repository, prefix)
    name = f"argus_drill_{secrets.token_hex(4)}"
    # The scratch database is created by the importer role when one is configured, not the app's.
    base = (os.environ.get("ARGUS_PORTABILITY_STAGING_URL") or database_url).rsplit("/", 1)[0]
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    report: dict = {"repository": repository, "tag": tag, "database": name}
    scratch = create_engine(f"{base}/{name}")
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True,
                       env={**os.environ, "DATABASE_URL": f"{base}/{name}"}, stdout=subprocess.DEVNULL)
        drill_cfg = service.Config(**{**cfg.__dict__, "root": cfg.root / "drills" / name,
                                      "attachments_dir": cfg.root / "drills" / name / "attachments"})
        with Session(scratch) as db:
            imp = service.create_import(db, "restore-drill", mode="clone",
                                        source={"repository": repository, "ref": tag}, decisions={}, cfg=drill_cfg)
            db.commit()
            service.fetch_git(db, imp, "restore-drill", drill_cfg)
            service.verify_import(db, imp, "restore-drill", drill_cfg)
            service.dry_run(db, imp, "restore-drill", drill_cfg)
            db.commit()
            if imp.state != "awaiting_approval":
                report.update({"passed": False, "stage": "dry_run", "dry_run": imp.dry_run})
                return report
            service.approve_import(db, imp, "restore-drill", acknowledge_uninspected=True,   # a clone into a
                                   cfg=drill_cfg)                                  # scratch database
            db.commit()
            service.execute(db, imp, "restore-drill", drill_cfg)
            if imp.state == "ready_to_finalize":
                t0 = time.monotonic()
                service.finalize(db, imp, "restore-drill", drill_cfg)     # promotion into the scratch database
                report["metrics"] = {"promotion_seconds": round(time.monotonic() - t0, 2),
                                     "peak_memory_mb": service._peak_memory_mb()}
            report.update({"passed": imp.state == "finalized" and bool((imp.reconciliation or {}).get("passed")),
                           "commit": imp.commit, "export_id": imp.manifest["export_id"],
                           "checkpoint": imp.manifest["watermark"]["checkpoint_sequence"],
                           "vector_sha256": imp.manifest["watermark"]["vector_sha256"],
                           "reconciliation_sha256": imp.reconciliation_sha256,
                           "families": {k: v["ok"] for k, v in imp.reconciliation["families"].items()},
                           "projections": {k: v["ok"] for k, v in imp.reconciliation["projections"].items()}})
            return report
    finally:
        scratch.dispose()
        if not keep:
            with admin.connect() as c:
                c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def dev_setup() -> dict:
    """For a development instance only: create what the configuration names, where it is missing — a
    throwaway Ed25519 key and its allowed-signers file, the registered repositories as local bare
    repositories, and the artifact stores. Never overwrites a key. Production keys come from the
    institution's secret store (docs/operations.md, "Key management")."""
    from app.portability import signing
    done = {}
    key = os.environ.get("ARGUS_PORTABILITY_SIGNING_KEY")
    if key and not Path(key).exists():
        Path(key).parent.mkdir(parents=True, exist_ok=True)
        signer = signing.new_key(Path(key))
        done["signing_key"] = signer.key_id
        trusted = os.environ.get("ARGUS_PORTABILITY_TRUSTED_KEYS")
        if trusted:
            Path(trusted).write_text(signing.allowed_signers_line(signer))
            done["trusted_keys"] = trusted
    cfg = service.config()
    for name, url in cfg.repositories.items():
        if url.startswith("/") and not Path(url).exists():
            gitrepo.init_bare(Path(url))
            done[f"repository {name}"] = url
    for name, store in cfg.stores.items():
        store.root.mkdir(parents=True, exist_ok=True)
        done[f"store {name}"] = str(store.root)
    return done or {"note": "everything was already in place"}


def record_drill(report: dict, actor: str) -> str:
    """The drill's evidence, in this instance's append-only audit (sealed in the daily digest)."""
    from app.db import SessionLocal
    from app.models.portability import PortabilityEvent
    drill_id = f"drill-{report.get('tag', 'none').replace('/', '_')}-{secrets.token_hex(3)}"
    with SessionLocal() as db:
        db.add(PortabilityEvent(subject_kind="drill", subject_id=drill_id, kind="restore_drill",
                                to_state="passed" if report.get("passed") else "failed", actor=actor,
                                detail={k: v for k, v in report.items() if k != "drill_id"}))
        db.commit()
    return drill_id


def signoff_drill(drill_id: str, actor: str, note: str) -> dict:
    """An administrator signs off a drill's evidence (decision: one administrator, every six months)."""
    from sqlalchemy import select as _select

    from app.db import SessionLocal
    from app.models.portability import PortabilityEvent
    with SessionLocal() as db:
        drill = db.scalar(_select(PortabilityEvent).where(PortabilityEvent.subject_id == drill_id,
                                                          PortabilityEvent.kind == "restore_drill"))
        if drill is None:
            raise SystemExit(f"no drill {drill_id}")
        db.add(PortabilityEvent(subject_kind="drill", subject_id=drill_id, kind="drill_signed_off", actor=actor,
                                detail={"note": note or None, "drill_seq": drill.seq, "passed": drill.to_state}))
        db.commit()
    return {"drill_id": drill_id, "signed_off_by": actor, "passed": drill.to_state == "passed"}


def cycle(cfg: service.Config, repository: str, store: str, actor: str) -> dict:
    """The production-size validation: one full export (full identity), published, then restored into a
    scratch database — with duration, peak memory and promotion-transaction time recorded."""
    import time as _time

    from app.db import SessionLocal, engine
    started = _time.monotonic()
    with SessionLocal() as db:
        exp = service.create_export(db, actor, mode="full", workspaces=[], classifications=[],
                                    destination={"repository": repository, "artifact_store": store},
                                    purpose="backup", cfg=cfg)
        service.analyse_export(db, exp, actor, cfg)
        db.commit()
        if not exp.analysis["ready"]:
            return {"passed": False, "stage": "analysis", "analysis": exp.analysis.get("warnings")}
        service.approve_export(db, exp, actor, admin=True, fresh_auth=True, cfg=cfg, step_up_how="operator CLI")
        db.commit()
        service.generate_export(engine, db, exp, actor, cfg, fresh_auth=True)
        service.publish_export(db, exp, actor, cfg)
        db.commit()
        export_metrics = (exp.analysis or {}).get("metrics", {})
        export_id = exp.id
    drill = restore_drill(cfg, repository, os.environ["DATABASE_URL"])
    report = {"passed": bool(drill.get("passed")), "export_id": export_id, "export": export_metrics,
              "restore": {k: drill.get(k) for k in ("passed", "metrics", "checkpoint", "tag")},
              "total_seconds": round(_time.monotonic() - started, 1)}
    report["drill_id"] = record_drill({**drill, "cycle": report}, actor)
    return report


def main(argv=None) -> int:
    from app.db import SessionLocal, engine
    ap = argparse.ArgumentParser(prog="python -m app.portability")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--mode", default="workspace")
    e.add_argument("--workspace", action="append", default=[])
    e.add_argument("--classification", action="append", default=[])
    e.add_argument("--repository")
    e.add_argument("--store")
    e.add_argument("--base")
    e.add_argument("--decide", action="append", default=[])
    e.add_argument("--identity-profile")
    e.add_argument("--purpose", choices=list(policy_mod.PURPOSES))
    e.add_argument("--recipient", action="append", default=[], help="approved recipient (restricted exports)")
    e.add_argument("--by", required=True)
    for name in ("approve", "generate", "publish"):
        p = sub.add_parser(name)
        p.add_argument("export_id")
        p.add_argument("--by", required=True)
    i = sub.add_parser("import")
    i.add_argument("--mode", default="clone")
    i.add_argument("--repository", required=True)
    i.add_argument("--ref", required=True)
    i.add_argument("--expected-commit")
    i.add_argument("--by", required=True)
    s = sub.add_parser("step")
    s.add_argument("import_id")
    s.add_argument("step", choices=["fetch", "verify", "dry-run", "approve", "execute", "finalize", "discard"])
    s.add_argument("--by", required=True)
    s.add_argument("--reason", default="")
    s.add_argument("--accept-uninspected", action="store_true",
                   help="approve an archive carrying uninspected (opaque or unreadable) files")
    d = sub.add_parser("drill")
    d.add_argument("--repository", required=True)
    d.add_argument("--prefix", default="export/full/")
    d.add_argument("--by", default="restore-drill")
    so = sub.add_parser("drill-signoff")
    so.add_argument("drill_id")
    so.add_argument("--by", required=True)
    so.add_argument("--note", default="")
    cy = sub.add_parser("cycle", help="one full export, publication and restore drill, measured")
    cy.add_argument("--repository", required=True)
    cy.add_argument("--store", required=True)
    cy.add_argument("--by", required=True)
    sub.add_parser("scheduled", help="run the periodic Git exports whose time has come (a CronJob, every 15 min)")
    cl = sub.add_parser("cleanup", help="retention: delete expired archive files unless held")
    cl.add_argument("--dry-run", action="store_true")
    lh = sub.add_parser("legal-hold")
    lh.add_argument("kind", choices=["export", "import"])
    lh.add_argument("subject_id")
    lh.add_argument("--by", required=True)
    lh.add_argument("--reason", default="")
    lh.add_argument("--release", action="store_true")
    sub.add_parser("policy", help="the portability policy in force, and its relaxations")
    sub.add_parser("dev-setup", help="development only: a throwaway key, a local bare repository, an artifact store")
    rk = sub.add_parser("recipient-key", help="an X25519 recipient key pair: private key to a file, public line printed")
    rk.add_argument("--name", required=True)
    rk.add_argument("--out", required=True)
    sc = sub.add_parser("schemas")
    sc.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cfg = service.config()

    if a.cmd == "schemas":
        out = Path(a.out)
        for rel, body in exporter.json_schemas().items():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
        return 0
    if a.cmd == "recipient-key":
        from app.portability import envelope
        print(envelope.new_recipient_key(Path(a.out), a.name), end="")
        return 0
    if a.cmd == "dev-setup":
        _print(dev_setup())
        return 0
    if a.cmd == "policy":
        _print(cfg.policy.describe())
        return 0
    if a.cmd == "drill":
        report = restore_drill(cfg, a.repository, os.environ["DATABASE_URL"], a.prefix)
        report["drill_id"] = record_drill(report, a.by)
        _print(report)
        return 0 if report.get("passed") else 1
    if a.cmd == "drill-signoff":
        _print(signoff_drill(a.drill_id, a.by, a.note))
        return 0
    if a.cmd == "scheduled":
        from app.portability import schedules
        out = schedules.run_due(engine, cfg)
        _print({"runs": out})
        return 1 if any(r["outcome"] == "failed" for r in out) else 0
    if a.cmd == "cycle":
        report = cycle(cfg, a.repository, a.store, a.by)
        _print(report)
        return 0 if report.get("passed") else 1
    db = SessionLocal()
    try:
        if a.cmd == "cleanup":
            if a.dry_run:
                db.begin_nested()
            out = service.cleanup(db, cfg, actor="retention-job")
            if a.dry_run:
                db.rollback()
                out["dry_run"] = True
            else:
                db.commit()
            _print(out)
            return 0
        if a.cmd == "legal-hold":
            model = PortabilityExport if a.kind == "export" else PortabilityImport
            subject = db.get(model, a.subject_id)
            service.set_legal_hold(db, subject, not a.release, a.reason, a.by)
            db.commit()
            _print({"id": subject.id, "legal_hold": subject.legal_hold, "reason": subject.legal_hold_reason})
            return 0
        if a.cmd == "export":
            decisions = dict(x.split("=", 1) for x in a.decide)
            exp = service.create_export(db, a.by, mode=a.mode, workspaces=a.workspace,
                                        classifications=a.classification,
                                        destination={"repository": a.repository, "artifact_store": a.store,
                                                     **({"recipients": a.recipient} if a.recipient else {})},
                                        decisions=decisions, base_export_id=a.base,
                                        identity_profile=a.identity_profile, purpose=a.purpose, cfg=cfg)
            service.analyse_export(db, exp, a.by, cfg)
            db.commit()
            _print(service.export_view(exp))
        elif a.cmd in ("approve", "generate", "publish"):
            exp = db.get(PortabilityExport, a.export_id)
            # The operator CLI runs with host-level access to ARGUS: that is its step-up (audited as such).
            if a.cmd == "approve":
                service.approve_export(db, exp, a.by, admin=True, fresh_auth=True, cfg=cfg, step_up_how="operator CLI")
            elif a.cmd == "generate":
                service.generate_export(engine, db, exp, a.by, cfg, fresh_auth=True)
            else:
                service.publish_export(db, exp, a.by, cfg)
            db.commit()
            _print(service.export_view(db.get(PortabilityExport, a.export_id)))
        elif a.cmd == "import":
            imp = service.create_import(db, a.by, mode=a.mode, source={"repository": a.repository, "ref": a.ref,
                                        **({"expected_commit": a.expected_commit} if a.expected_commit else {})},
                                        decisions={}, cfg=cfg)
            db.commit()
            _print(service.import_view(imp))
        elif a.cmd == "step":
            imp = db.get(PortabilityImport, a.import_id)
            fn = {"fetch": lambda: service.fetch_git(db, imp, a.by, cfg),
                  "verify": lambda: service.verify_import(db, imp, a.by, cfg),
                  "dry-run": lambda: service.dry_run(db, imp, a.by, cfg),
                  "approve": lambda: service.approve_import(db, imp, a.by, acknowledge_uninspected=a.accept_uninspected,
                                                             cfg=cfg),
                  "execute": lambda: service.execute(db, imp, a.by, cfg),
                  "finalize": lambda: service.finalize(db, imp, a.by, cfg),
                  "discard": lambda: service.discard(db, imp, a.by, cfg, a.reason)}[a.step]
            out = fn()
            db.commit()
            _print({**service.import_view(out), "dry_run": out.dry_run})
    except service.ServiceError as err:
        db.rollback()
        _print({"error": str(err), "code": err.code, **err.detail})
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
