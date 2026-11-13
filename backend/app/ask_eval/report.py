"""The report of a run: a reproducibility manifest, the per-model table, every case's results with their reasons.

``build`` makes the full report (for administrators: questions, answers, evidence, grades). ``public`` keeps what
may be published with a GitHub release: the fixtures are synthetic, but a case marked ``publish: false`` (asked as
a person with restricted classes) keeps only its scores. ``seal`` gives a report its SHA-256 over the canonical
JSON; a sealed report is never changed — a re-run is a new report.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from app.ask_eval import DATASET_VERSION
from app.ask_eval.dataset import Dataset
from app.ask_eval.runner import percentile, spread

SCHEMA = "argus-ask-eval-report/1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def argus_identity() -> dict:
    """The version and commit this ARGUS is (the image's build arguments; git in a working tree)."""
    commit = os.environ.get("ARGUS_COMMIT")
    if not commit:
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
                                    cwd=os.path.dirname(__file__)).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            commit = None
    return {"version": os.environ.get("ARGUS_VERSION") or "dev", "commit": commit}


def prompt_identity() -> dict:
    """Hashes of what Ask sends a model besides the question: the system prompt (with and without the proposal
    instructions) and the tools' names, descriptions and parameters."""
    from app.services import ask, ask_actions
    tools = json.dumps(ask._tool_specs(), sort_keys=True)
    proposal_tools = json.dumps(ask_actions.tool_specs(), sort_keys=True)
    return {"system_prompt_sha256": _sha(ask.SYSTEM), "proposal_prompt_sha256": _sha(ask_actions.SYSTEM),
            "tools_sha256": _sha(tools), "proposal_tools_sha256": _sha(proposal_tools),
            "max_rounds": ask.MAX_ROUNDS, "max_tool_chars": ask.MAX_TOOL_CHARS}


def _mean(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarize(dataset: Dataset, results: list[dict]) -> dict:
    """One model's row of the release table, from its case results (every repeat counted)."""
    ran = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    scored = [r["scores"] for r in ran]
    with_facts = [s for s in scored if s["facts"]["score"] is not None]
    abstain = [s for s in scored if s["abstention"]["expected"]]
    cited = [s for s in scored if s["citations"]["cited"]]
    support = [s for s in scored if s["citations"]["supports_expected"] is not None]
    seconds = [r["seconds"] for r in ran if r.get("seconds") is not None]
    tokens = [r["tokens"]["prompt"] + r["tokens"]["completion"] for r in ran]
    by_case: dict[str, list[bool]] = {}
    for r in ran:
        by_case.setdefault(r["case"], []).append(bool(r["scores"]["passed"]))
    rates = [sum(v) / len(v) for v in by_case.values()]
    flaky = sorted(c for c, v in by_case.items() if 0 < sum(v) < len(v))
    return {
        "runs": len(ran),
        "skipped": len(skipped),
        "passed": sum(1 for s in scored if s["passed"]),
        "pass_rate": _mean([1.0 if s["passed"] else 0.0 for s in scored]),
        "factual_pass_rate": _mean([1.0 if s["facts"]["score"] == 1 else 0.0 for s in with_facts]),
        "evidence_retrieval": _mean([s["evidence"]["score"] for s in scored]),
        "citation_validity": _mean([s["citations"]["valid"] / len(s["citations"]["cited"]) for s in cited]),
        "citation_support": _mean([1.0 if s["citations"]["supports_expected"] else 0.0 for s in support]),
        "correct_abstention": _mean([1.0 if s["abstention"]["admitted"] else 0.0 for s in abstain]),
        "unsupported_claims": sum(len(s["unsupported"]["forbidden"]) + len(s["unsupported"]["invalid_citations"])
                                  for s in scored),
        "critical_failures": sum(1 for s in scored if s["critical"]),
        "completion_failures": sum(1 for s in scored if not s["completed"]),
        "timeouts": sum(1 for r in ran if r.get("stopped") == "timeout"),
        "latency_p50_s": percentile(seconds, 0.5),
        "latency_p95_s": percentile(seconds, 0.95),
        "tokens_mean": round(sum(tokens) / len(tokens)) if tokens else None,
        "tokens_estimated": any(r["tokens"]["estimated"] for r in ran),
        "case_pass_rate_spread": spread(rates),
        "flaky_cases": flaky,
        "served_models": sorted({m for r in ran for m in r.get("served_models") or []}),
    }


def build(dataset: Dataset, raw: dict, *, release: Optional[str] = None, judge: Optional[dict] = None,
          requested_by: Optional[str] = None) -> dict:
    """The full report of a run."""
    ident = argus_identity()
    manifest = {
        "schema": SCHEMA,
        "run_id": raw["run_id"],
        "kind": raw["kind"],
        "release": release or ident["version"],
        "argus": ident,
        "dataset": {"version": dataset.version, "sha256": dataset.sha256, "cases": len(raw["cases"]),
                    "labels": {"reviewed": sum(1 for lb in dataset.human_labels if lb.get("status") == "reviewed"),
                               "draft": sum(1 for lb in dataset.human_labels if lb.get("status") != "reviewed")}},
        "fixtures": {k: v for k, v in dataset.fixture_sha256.items()
                     if any(dataset.case(c).fixture == k for c in raw["cases"])},
        "ask": prompt_identity(),
        "index": raw["index"],
        "configuration": raw["config"],
        "models": {m: {**p, "served_models": None} for m, p in raw["preflight"].items()},
        "judge": (judge or {}).get("identity") or {"model": None, "note": "no judge configured: rules only"},
        "isolation": raw["isolation"],
        "started_at": raw["started_at"],
        "finished_at": raw["finished_at"],
        "complete": raw["complete"],
        "requested_by": requested_by,
    }
    table = []
    for model, results in raw["results"].items():
        row = {"model": model, **summarize(dataset, results)}
        manifest["models"][model]["served_models"] = row["served_models"]
        table.append(row)
    for model, p in raw["preflight"].items():
        if p.get("status") != "ok":
            table.append({"model": model, "status": p["status"], "reason": p.get("reason")})
    cases = []
    for cid in raw["cases"]:
        c = dataset.case(cid)
        cases.append({"id": c.id, "language": c.language, "domain": c.domain, "severity": c.severity,
                      "tags": c.tags, "role": c.role, "fixture": c.fixture, "question": c.question,
                      "history": [m.model_dump() for m in c.history],
                      "attachment": c.attachment.model_dump() if c.attachment else None,
                      "expect_insufficient": c.expect_insufficient, "publish": c.publish,
                      "results": {m: [r for r in rs if r["case"] == cid] for m, rs in raw["results"].items()}})
    report = {"manifest": manifest, "table": table, "cases": cases, "judge": judge}
    return report


def public(report: dict) -> dict:
    """What may be attached to a public release: everything synthetic, without the text of unpublished cases."""
    out = json.loads(json.dumps(report))
    out["manifest"]["visibility"] = "public"
    for c in out["cases"]:
        if c.get("publish"):
            continue
        c["question"] = "[not published: asked as a person with restricted classes]"
        c["history"], c["attachment"] = [], None
        for rs in c["results"].values():
            for r in rs:
                r["answer"] = "[not published]"
                r["steps"] = [{"tool": s.get("tool"), "result": "[not published]"} for s in r.get("steps") or []]
                if r.get("scores"):
                    r["scores"]["facts"]["items"] = [{**f, "matched": None} for f in r["scores"]["facts"]["items"]]
    if out.get("judge"):
        for f in out["judge"].get("findings", []):
            if not next((c for c in out["cases"] if c["id"] == f.get("case")), {}).get("publish", True):
                f["evidence"] = "[not published]"
    return out


def canonical(report: dict) -> str:
    return json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def seal(report: dict) -> tuple[str, str]:
    """The report's canonical JSON and its SHA-256: what is stored and attached, never changed afterwards."""
    text = canonical(report)
    return text, _sha(text)


# --------------------------------------------------------------------------- readable reports

COLUMNS = [("pass_rate", "Pass", "%"), ("factual_pass_rate", "Facts", "%"), ("evidence_retrieval", "Evidence", "%"),
           ("citation_support", "Citation support", "%"), ("correct_abstention", "Abstention", "%"),
           ("critical_failures", "Critical", "n"), ("completion_failures", "Incomplete", "n"),
           ("latency_p50_s", "p50 s", "s"), ("latency_p95_s", "p95 s", "s"), ("tokens_mean", "Tokens/case", "n")]


def _fmt(v, unit: str) -> str:
    if v is None:
        return "—"
    if unit == "%":
        return f"{v * 100:.0f}%"
    if unit == "s":
        return f"{v:.1f}"
    return str(v)


def markdown(report: dict) -> str:
    m = report["manifest"]
    lines = [f"# Ask ARGUS {m['kind']} — ARGUS {m['release']}", "",
             f"Run `{m['run_id']}`, {m['started_at'][:16].replace('T', ' ')} UTC"
             f"{'' if m['complete'] else ' — **incomplete run**'}. Dataset {m['dataset']['version']} "
             f"(`{m['dataset']['sha256'][:12]}`), {m['dataset']['cases']} cases. Commit `{(m['argus']['commit'] or '?')[:12]}`.",
             f"Index: {m['index'].get('id')} (embedding {m['index'].get('embedding_model') or 'none'}, re-ranker "
             f"{m['index'].get('rerank_model') or 'none'}). Judge: {m['judge'].get('model') or 'none (rules only)'}. "
             f"Isolation: {m['isolation']}.", ""]
    if m["dataset"]["labels"]["reviewed"] == 0:
        lines += ["> Calibration labels are drafts, not yet reviewed by domain experts.", ""]
    lines += ["| Model | Runs | " + " | ".join(c[1] for c in COLUMNS) + " |",
              "|---|---:|" + "---:|" * len(COLUMNS)]
    for row in report["table"]:
        if row.get("status"):
            lines.append(f"| {row['model']} | — | **{row['status']}**: {row.get('reason') or ''} |"
                         + " |" * (len(COLUMNS) - 1))
            continue
        skipped = f" (+{row['skipped']} skipped)" if row["skipped"] else ""
        lines.append(f"| {row['model']} | {row['runs']}{skipped} | "
                     + " | ".join(_fmt(row.get(k), u) for k, _, u in COLUMNS) + " |")
    lines += ["", "Pass: every required fact, no forbidden claim or invented citation, the right abstention and "
              "proposal behaviour, no critical failure. Critical failures (a restricted record reaching the answer "
              "or the model, a claimed change) fail a case whatever else is right.", ""]
    for row in report["table"]:
        if row.get("flaky_cases"):
            lines.append(f"- {row['model']}: answers vary between repeats on {', '.join(row['flaky_cases'])}.")
    lines += ["", "## Cases", ""]
    for c in report["cases"]:
        lines.append(f"### {c['id']} ({c['language']}, {c['domain']}, {c['severity']}, as {c['role']})")
        lines += ["", f"> {c['question'].strip()}", ""]
        for model, rs in c["results"].items():
            for r in rs:
                if r.get("skipped"):
                    lines.append(f"- **{model}** #{r['attempt'] + 1}: skipped — {r['skipped']}")
                    continue
                s = r["scores"]
                verdict = "PASS" if s["passed"] else ("CRITICAL" if s["critical"] else "fail")
                lookups = ", ".join(st.get("tool", "") for st in r["steps"]) or "none"
                lines.append(f"- **{model}** #{r['attempt'] + 1}: **{verdict}** — {r['seconds']} s, lookups: {lookups}")
                for why in s["reasons"]:
                    lines.append(f"  - {why}")
                answer = (r["answer"] or "").strip().replace("\n", " ")
                lines.append(f"  - answer: {answer[:600]}{'…' if len(answer) > 600 else ''}")
        lines.append("")
    if report.get("judge"):
        j = report["judge"]
        lines += ["## Judge", "", f"Model {j['identity'].get('model')}; agreement with reviewed labels: "
                  f"{j.get('calibration', {}).get('agreement', '—')}.", ""]
    return "\n".join(lines) + "\n"


def html_page(report: dict) -> str:
    """The same report as one HTML page: no scripts, no external resources."""
    e = html.escape
    m = report["manifest"]
    head = "".join(f"<th>{e(label)}</th>" for _, label, _ in COLUMNS)
    rows = []
    for row in report["table"]:
        if row.get("status"):
            rows.append(f"<tr><td>{e(row['model'])}</td><td colspan='{len(COLUMNS) + 1}'><b>{e(row['status'])}</b>: "
                        f"{e(row.get('reason') or '')}</td></tr>")
        else:
            rows.append(f"<tr><td>{e(row['model'])}</td><td>{row['runs']}</td>"
                        + "".join(f"<td>{e(_fmt(row.get(k), u))}</td>" for k, _, u in COLUMNS) + "</tr>")
    cases = []
    for c in report["cases"]:
        items = []
        for model, rs in c["results"].items():
            for r in rs:
                if r.get("skipped"):
                    items.append(f"<li><b>{e(model)}</b>: skipped — {e(r['skipped'])}</li>")
                    continue
                s = r["scores"]
                verdict = "PASS" if s["passed"] else ("CRITICAL" if s["critical"] else "fail")
                reasons = "".join(f"<li>{e(w)}</li>" for w in s["reasons"])
                steps = "".join(f"<li><code>{e(st.get('tool') or '')}</code> {e(json.dumps(st.get('arguments') or {}))}"
                                "</li>" for st in r["steps"])
                items.append(f"<li><b>{e(model)}</b> #{r['attempt'] + 1}: <b class='{verdict.lower()}'>{verdict}</b>, "
                             f"{r['seconds']} s<ul>{reasons}</ul><details><summary>Answer and lookups</summary>"
                             f"<pre>{e(r['answer'] or '')}</pre><ol>{steps}</ol></details></li>")
        cases.append(f"<section><h3>{e(c['id'])} <small>{e(c['language'])} · {e(c['domain'])} · {e(c['severity'])} · "
                     f"as {e(c['role'])}</small></h3><blockquote>{e(c['question'])}</blockquote><ul>{''.join(items)}"
                     "</ul></section>")
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><title>Ask ARGUS evaluation</title><style>"
            "body{font:14px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#111}"
            "table{border-collapse:collapse;width:100%;overflow-x:auto;display:block}"
            "th,td{border-bottom:1px solid #ddd;padding:4px 8px;text-align:right}th:first-child,td:first-child"
            "{text-align:left}.pass{color:#166534}.fail{color:#92400e}.critical{color:#b91c1c}pre{white-space:"
            "pre-wrap;background:#f6f6f6;padding:8px}</style></head><body>"
            f"<h1>Ask ARGUS {e(m['kind'])} — ARGUS {e(m['release'])}</h1>"
            f"<p>Run <code>{e(m['run_id'])}</code>, {e(m['started_at'][:16])} UTC{'' if m['complete'] else ' — <b>incomplete</b>'}"
            f"; dataset {e(m['dataset']['version'])} <code>{e(m['dataset']['sha256'][:12])}</code>; commit "
            f"<code>{e((m['argus']['commit'] or '?')[:12])}</code>; index {e(str(m['index'].get('id')))}; judge "
            f"{e(m['judge'].get('model') or 'none')}; isolation: {e(m['isolation'])}.</p>"
            f"<table><tr><th>Model</th><th>Runs</th>{head}</tr>{''.join(rows)}</table>"
            f"<h2>Cases</h2>{''.join(cases)}</body></html>")


def not_run(release: str) -> dict:
    """What a release without a live benchmark says: not run — never an older run standing in for it."""
    return {"release": release, "status": "not run",
            "note": "No live Ask ARGUS benchmark was run for this release; earlier releases' results do not apply.",
            "generated_at": datetime.now(timezone.utc).isoformat(), "dataset_version": DATASET_VERSION}
