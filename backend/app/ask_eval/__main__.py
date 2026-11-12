"""python -m app.ask_eval — the evaluation from a shell, a CI job or a cluster job (docs/ask-eval.md).

  validate                      check the dataset and print its hashes
  run --kind KIND [...]         run it; writes report.json (sealed), report.public.json, report.md, report.html
  not-run --release vX --out D  the "not run" record for a release without a live benchmark
  feedback-drafts [--since D]   answers rated down, as draft cases (YAML) to review
  upload FILE                   send a report to an ARGUS (ARGUS_URL, ARGUS_REPORT_TOKEN: an administrator's
                                personal token)

KIND: release (the production candidate, ASK_EVAL_RELEASE_MODEL or the first of ASK_EVAL_MODELS), benchmark (every
model of ASK_EVAL_MODELS), configurations (ASK_EVAL_CONFIGURATIONS: a JSON list of {"name", "model",
"embedding_model", "rerank_model"}, each with its own index), simulated (the deterministic stand-ins: no server).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _write(out: Path, report: dict) -> dict:
    from app.ask_eval import report as rpt
    out.mkdir(parents=True, exist_ok=True)
    full, sha = rpt.seal(report)
    pub = rpt.public(report)
    pub_text, pub_sha = rpt.seal(pub)
    (out / "report.json").write_text(full)
    (out / "report.public.json").write_text(pub_text)
    (out / "report.md").write_text(rpt.markdown(report))
    (out / "report.public.md").write_text(rpt.markdown(pub))
    (out / "report.html").write_text(rpt.html_page(report))
    (out / "report.public.html").write_text(rpt.html_page(pub))
    (out / "SHA256SUMS").write_text(f"{sha}  report.json\n{pub_sha}  report.public.json\n")
    return {"sha256": sha, "public_sha256": pub_sha}


def cmd_validate(_args) -> int:
    from app.ask_eval import dataset
    ds = dataset.load()
    print(json.dumps({"version": ds.version, "sha256": ds.sha256, "cases": len(ds.cases),
                      "fixtures": ds.fixture_sha256, "labels": len(ds.human_labels)}, indent=2))
    return 0


def cmd_run(args) -> int:
    from app.ask_eval import dataset, judge as judge_mod, report as rpt, runner, standins
    from app.db import SessionLocal
    if args.migrate:
        import subprocess
        subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=str(Path(__file__).resolve().parents[2]))
    ds = dataset.load()
    config = runner.EvalConfig.from_env()
    if args.repeats:
        config.repeats = args.repeats
    if args.models:
        config.models = [m.strip() for m in args.models.split(",") if m.strip()]
    cases = [c.strip() for c in args.cases.split(",")] if args.cases else None
    progress_file = Path(args.progress_file) if args.progress_file else None

    def progress(event: dict) -> None:
        line = json.dumps({k: v for k, v in event.items() if k != "models"}, default=str)
        print(line, flush=True)
        if progress_file:
            with progress_file.open("a") as f:
                f.write(line + "\n")

    db = SessionLocal()
    try:
        if args.kind == "simulated":
            config.models = ["standin:reference", "standin:careless"]
            with standins.installed(ds):
                raw = runner.run(db, ds, config, kind="simulated", case_ids=cases,
                                 endpoint_factory=standins.factory(ds), progress=progress, run_id=args.run_id,
                                 allow_shared_database=args.allow_shared_database)
        elif args.kind == "configurations":
            raw = _configurations(db, ds, config, cases, progress, args)
        else:
            if not config.configured:
                print("ASK_EVAL_API_BASE_URL and ASK_EVAL_MODELS are needed for a live run", file=sys.stderr)
                return 2
            if args.kind == "release":
                config.models = [os.environ.get("ASK_EVAL_RELEASE_MODEL") or config.models[0]]
            raw = runner.run(db, ds, config, kind=args.kind, case_ids=cases, progress=progress, run_id=args.run_id,
                             allow_shared_database=args.allow_shared_database)
        judged = None
        if config.judge_model and args.kind != "simulated":
            from app.services.llm import Endpoint
            jep = Endpoint(base_url=config.judge_base_url or config.base_url, model=config.judge_model,
                           api_key=config.judge_api_key or config.api_key)
            host = (__import__("urllib.parse").parse.urlparse(jep.base_url).hostname or "").lower()
            j = judge_mod.Judge(jep, approved_for_restricted=host in {h.lower() for h in config.approved_hosts})
            judged = judge_mod.run(j, ds, raw, lambda c: runner.restricted(ds, c))
        report = rpt.build(ds, raw, release=args.release, judge=judged)
    except runner.EvalError as e:
        print(f"ask-eval: {config.scrub(str(e))}", file=sys.stderr)
        return 2
    finally:
        db.close()
    sums = _write(Path(args.out), report)
    print(rpt.markdown(report).split("## Cases")[0])
    print(json.dumps(sums))
    return 0 if report["manifest"]["complete"] else 3


def _configurations(db, ds, config, cases, progress, args):
    """Whole configurations compared: each one (chat model, embedding model, re-ranker) with its own index."""
    from app.ask_eval import runner
    configs = json.loads(os.environ.get("ASK_EVAL_CONFIGURATIONS") or "[]")
    if len(configs) < 2:
        raise runner.EvalError("ASK_EVAL_CONFIGURATIONS needs two configurations at least")
    merged = None
    for c in configs:
        name = c["name"]
        sub = runner.EvalConfig(**{**config.__dict__, "models": [c["model"]],
                                   "embedding_model": c.get("embedding_model"), "rerank_model": c.get("rerank_model")})
        raw = runner.run(db, ds, sub, kind="configurations", case_ids=cases, progress=progress,
                         run_id=f"{args.run_id or 'cfg'}-{name}"[:40], allow_shared_database=args.allow_shared_database)
        raw["results"] = {name: raw["results"].get(c["model"], [])}
        raw["preflight"] = {name: {**raw["preflight"].get(c["model"], {}), "model": c["model"],
                                   "index": raw["index"]}}
        if merged is None:
            merged = {**raw, "run_id": args.run_id or raw["run_id"], "index": {"per_configuration": {}}}
        else:
            merged["results"].update(raw["results"])
            merged["preflight"].update(raw["preflight"])
            merged["complete"] = merged["complete"] and raw["complete"]
            merged["finished_at"] = raw["finished_at"]
        merged["index"]["per_configuration"][name] = raw["index"]
    merged["index"]["id"] = "per configuration"
    return merged


def cmd_not_run(args) -> int:
    from app.ask_eval import report as rpt
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    record = rpt.not_run(args.release)
    (out / "not-run.json").write_text(json.dumps(record, indent=2))
    (out / "not-run.md").write_text(f"Ask ARGUS benchmark for {args.release}: **not run**.\n\n{record['note']}\n")
    print(json.dumps(record))
    return 0


def cmd_feedback_drafts(args) -> int:
    from datetime import datetime
    from app.ask_eval import feedback_drafts as fd
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        text, count = fd.export(db, since=datetime.fromisoformat(args.since) if args.since else None,
                                workspace=args.workspace)
    finally:
        db.close()
    Path(args.out).write_text(text)
    print(f"{count} draft(s) written to {args.out}")
    return 0


def cmd_upload(args) -> int:
    import requests
    url, token = os.environ.get("ARGUS_URL"), os.environ.get("ARGUS_REPORT_TOKEN")
    if not (url and token):
        print("ARGUS_URL and ARGUS_REPORT_TOKEN are needed", file=sys.stderr)
        return 2
    report = json.loads(Path(args.file).read_text())
    resp = requests.post(f"{url.rstrip('/')}/v1/admin/ask-eval/runs/upload", json=report,
                         headers={"Authorization": f"Bearer {token}"}, timeout=120)
    print(resp.status_code, resp.text[:500].replace(token, "[token]"))
    return 0 if resp.status_code < 300 else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.ask_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    r = sub.add_parser("run")
    r.add_argument("--kind", choices=["release", "benchmark", "configurations", "simulated"], required=True)
    r.add_argument("--models")
    r.add_argument("--repeats", type=int)
    r.add_argument("--cases")
    r.add_argument("--release")
    r.add_argument("--run-id")
    r.add_argument("--out", default="ask-eval-report")
    r.add_argument("--progress-file")
    r.add_argument("--allow-shared-database", action="store_true")
    r.add_argument("--migrate", action="store_true", help="bring the evaluation database to the current schema")
    n = sub.add_parser("not-run")
    n.add_argument("--release", required=True)
    n.add_argument("--out", default="ask-eval-report")
    f = sub.add_parser("feedback-drafts", help="answers rated down, as draft cases to review")
    f.add_argument("--since")
    f.add_argument("--workspace")
    f.add_argument("--out", default="ask-feedback-drafts.yaml")
    u = sub.add_parser("upload")
    u.add_argument("file")
    args = p.parse_args(argv)
    return {"validate": cmd_validate, "run": cmd_run, "not-run": cmd_not_run, "upload": cmd_upload,
            "feedback-drafts": cmd_feedback_drafts}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
