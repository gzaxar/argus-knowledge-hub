"""Running the dataset through the real Ask flow, model after model.

Every case is asked through services/ask.ask_events — the system prompt, the tools, the history and attachment
handling, the proposal tools — exactly as the Ask page does, in a fixture workspace built for the run, as a person
with the case's role (its restricted classes, whether Ask may propose changes for them).

For a fair comparison between chat models everything else is held fixed in a run: the fixtures (built once, asked
by every model), the search index (built once, with one embedding model), the re-ranker, the prompt, the tools,
the temperature (Ask's own) and the output budget. Each case is asked `repeats` times, so the report shows how
much a model's answers vary. Comparing whole configurations — another embedding model or re-ranker — is a separate
mode (`configurations`): each configuration rebuilds the index and says which index it used.

The API key is never logged, never written to a report and never put in an error message.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import logging
import os
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.ask_eval import fixtures as fx
from app.ask_eval.dataset import Case, Dataset
from app.ask_eval.scoring import score

log = logging.getLogger(__name__)

DEFAULT_CASE_TIMEOUT = 300

# The case being asked, for the deterministic stand-ins (two cases may ask the same question as different roles).
CURRENT_CASE: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("ask_eval_case", default=None)


class EvalError(Exception):
    pass


@dataclass
class EvalConfig:
    """What a run uses. Read from the environment (ASK_EVAL_*) or from the encrypted settings an administrator
    saved (app/ask_eval/settings.py); the key itself only ever lives in this object, in memory."""
    base_url: str = ""
    api_key: Optional[str] = field(default=None, repr=False)
    models: list[str] = field(default_factory=list)
    embedding_model: Optional[str] = None
    rerank_model: Optional[str] = None
    judge_model: Optional[str] = None
    judge_base_url: Optional[str] = None
    judge_api_key: Optional[str] = field(default=None, repr=False)
    repeats: int = 1
    case_timeout_s: int = DEFAULT_CASE_TIMEOUT
    max_output_tokens: Optional[int] = None
    # Hosts allowed to receive answers built from restricted (synthetic) records: the cases asked as a person
    # with restricted classes run only against these.
    approved_hosts: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, env=os.environ) -> "EvalConfig":
        split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]  # noqa: E731
        return cls(
            base_url=env.get("ASK_EVAL_API_BASE_URL", "").strip(),
            api_key=env.get("ASK_EVAL_API_KEY") or None,
            models=split(env.get("ASK_EVAL_MODELS")),
            embedding_model=env.get("ASK_EVAL_EMBEDDING_MODEL") or None,
            rerank_model=env.get("ASK_EVAL_RERANK_MODEL") or None,
            judge_model=env.get("ASK_EVAL_JUDGE_MODEL") or None,
            judge_base_url=env.get("ASK_EVAL_JUDGE_BASE_URL") or None,
            judge_api_key=env.get("ASK_EVAL_JUDGE_API_KEY") or None,
            repeats=max(1, int(env.get("ASK_EVAL_REPEATS") or 1)),
            case_timeout_s=max(10, int(env.get("ASK_EVAL_CASE_TIMEOUT") or DEFAULT_CASE_TIMEOUT)),
            max_output_tokens=int(env["ASK_EVAL_MAX_OUTPUT_TOKENS"]) if env.get("ASK_EVAL_MAX_OUTPUT_TOKENS") else None,
            approved_hosts=split(env.get("ASK_EVAL_APPROVED_HOSTS")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.models)

    @property
    def host(self) -> str:
        return (urlparse(self.base_url).hostname or "").lower()

    def approved_for_restricted(self) -> bool:
        return self.host in {h.lower() for h in self.approved_hosts}

    def public(self) -> dict:
        """What a report may say about the configuration: never the key, the server only by its host."""
        return {"server_host": self.host or None, "models": list(self.models),
                "embedding_model": self.embedding_model, "rerank_model": self.rerank_model,
                "judge_model": self.judge_model, "repeats": self.repeats, "case_timeout_s": self.case_timeout_s,
                "max_output_tokens": self.max_output_tokens, "temperature": "Ask's default (0)",
                "approved_for_restricted": self.approved_for_restricted(),
                "api_key": "set" if self.api_key else "not set"}

    def scrub(self, text: Optional[str]) -> Optional[str]:
        """An error message with the keys taken out, whatever the server echoed back."""
        if not text:
            return text
        for k in (self.api_key, self.judge_api_key):
            if k:
                text = text.replace(k, "[key]")
        return text


def endpoint(config: EvalConfig, model: str):
    from app.services.llm import Endpoint
    return Endpoint(base_url=config.base_url, model=model, api_key=config.api_key,
                    embedding_model=config.embedding_model, rerank_model=config.rerank_model,
                    max_output_tokens=config.max_output_tokens)


# --------------------------------------------------------------------------- preflight

def preflight(config: EvalConfig, models: list[str]) -> dict[str, dict]:
    """Whether each model can be evaluated: listed by the server, and answering a tool call (Ask needs tools).
    An unavailable or unsupported model is reported as such — never scored as wrong answers."""
    import requests
    from app.services.llm import LLMError, list_models
    out: dict[str, dict] = {}
    try:
        listed = set(list_models(endpoint(config, models[0] if models else "")))
    except LLMError as e:
        return {m: {"status": "unavailable", "reason": config.scrub(str(e))} for m in models}
    for m in models:
        if m not in listed:
            out[m] = {"status": "unavailable", "reason": "the server does not list this model"}
            continue
        ep = endpoint(config, m)
        probe = {"model": m, "max_tokens": 64, "temperature": 0,
                 "messages": [{"role": "user", "content": "Call the ping tool."}],
                 "tools": [{"type": "function", "function": {"name": "ping", "description": "Answer a ping.",
                                                             "parameters": {"type": "object", "properties": {}}}}],
                 "tool_choice": "auto"}
        try:
            resp = requests.post(f"{ep.root}/chat/completions", headers=ep.headers(), json=probe, timeout=60)
        except requests.RequestException as e:
            out[m] = {"status": "unavailable", "reason": config.scrub(f"could not reach the server: {e}")}
            continue
        if resp.status_code in (401, 403):
            out[m] = {"status": "unavailable", "reason": "the server refused the key"}
        elif resp.status_code >= 400:
            detail = config.scrub((resp.text or "")[:200])
            kind = "unsupported" if "tool" in (detail or "").lower() else "unavailable"
            out[m] = {"status": kind, "reason": f"{resp.status_code}: {detail}"}
        else:
            try:
                body = resp.json()
                served = body.get("model")
                calls = body["choices"][0]["message"].get("tool_calls")
            except (ValueError, KeyError, IndexError, TypeError):
                out[m] = {"status": "unsupported", "reason": "the reply was not an OpenAI chat completion"}
                continue
            out[m] = {"status": "ok", "served_model": served,
                      **({} if calls else {"warning": "did not call the tool when asked: Ask may not work well"})}
    return out


# --------------------------------------------------------------------------- one case

def _grants(dataset: Dataset, case: Case):
    from app.services.visibility import Grants
    return Grants(dataset.roles[case.role].grants)


def restricted(dataset: Dataset, case: Case) -> bool:
    """Whether this case's answer is built from records a person without restricted classes may not see."""
    return bool(dataset.roles[case.role].grants) or not case.publish


Transport = Callable[[str, Case, int], Optional[Callable]]


def run_case(dataset: Dataset, case: Case, built: fx.Built, ep, *, timeout_s: int,
             scrub: Callable[[Optional[str]], Optional[str]] = lambda t: t) -> dict:
    """One question, asked once, through the real Ask flow; what it found, what it answered, and its scores."""
    from app.db import SessionLocal
    from app.models.ask_conversation import AskConversation
    from app.services import ask_actions, usage
    from app.services.ask import ask_events, with_attachments
    from app.services.llm import LLMError
    from app.services.visibility import set_current_grants
    from app.services.who_has_access import set_viewer

    role = dataset.roles[case.role]
    question = with_attachments(case.question, [case.attachment.model_dump()] if case.attachment else None)
    history = [m.model_dump() for m in case.history]
    calls: list = []
    proposals: list = []

    def work() -> dict:
        CURRENT_CASE.set(case.id)
        set_current_grants(_grants(dataset, case))
        set_viewer(None)
        usage.capture(calls)
        db = SessionLocal()
        final: dict = {}
        steps: list = []
        try:
            proposer = None
            if role.can_propose:
                convo = AskConversation(id=str(uuid.uuid4()), workspace_id=built.workspace_id, owner="ask-eval",
                                        title=case.id)
                db.add(convo)
                db.commit()
                proposer = ask_actions.Proposer(db, built.workspace_id, convo.id, len(history))
            for event in ask_events(db, built.workspace_id, ep, question, history=history, stream=False,
                                    proposer=proposer,
                                    context=None):
                if event["type"] == "step":
                    steps.append({k: event[k] for k in ("tool", "arguments", "result", "error", "seconds")})
                elif event["type"] == "proposal":
                    proposals.append(event["action"])
                elif event["type"] == "done":
                    final = event
            return final
        except LLMError as e:
            return {"answer": "", "steps": steps, "stopped": "failed", "error": scrub(str(e))}
        finally:
            db.rollback()
            db.close()

    started = time.monotonic()
    ctx = contextvars.copy_context()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        final = pool.submit(ctx.run, work).result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        final = {"answer": "", "steps": [], "stopped": "timeout",
                 "error": f"no answer within {timeout_s} s"}
    except Exception as e:  # noqa: BLE001 — a crash in one case is reported, and the run goes on
        final = {"answer": "", "steps": [], "stopped": "failed", "error": scrub(f"{type(e).__name__}: {e}")}
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    elapsed = round(time.monotonic() - started, 2)

    answer = final.get("answer") or ""
    steps = final.get("steps") or []
    db = __import__("app.db", fromlist=["SessionLocal"]).SessionLocal()
    try:
        scores = score(case, answer, steps, resolve=lambda i: built.resolve(db, i),
                       render=lambda p: built.render(db, p), stopped=final.get("stopped"),
                       error=final.get("error"), proposals=proposals)
    finally:
        db.close()
    llm_calls = [c for c in calls if "purpose" in c]
    served = sorted({c["served_model"] for c in calls if "served_model" in c})
    return {
        "case": case.id,
        "answer": answer,
        "steps": [{**s, "result": (s.get("result") or "")[:4000]} for s in steps],
        "proposals": [{k: p.get(k) for k in ("number", "kind", "summary", "status")} for p in proposals],
        "stopped": final.get("stopped"),
        "error": scrub(final.get("error")),
        "seconds": elapsed,
        "tokens": {"prompt": sum(int(c.get("prompt_tokens") or 0) for c in llm_calls),
                   "completion": sum(int(c.get("completion_tokens") or 0) for c in llm_calls),
                   "estimated": any(c.get("estimated") for c in llm_calls), "calls": len(llm_calls),
                   "failed_calls": sum(1 for c in llm_calls if c.get("failed"))},
        "served_models": served,
        "scores": scores,
    }


# --------------------------------------------------------------------------- a whole run

def _isolation(db: Session, allow_shared: bool) -> str:
    """'dedicated' when no other workspace holds records here; refused otherwise unless `allow_shared`."""
    from sqlalchemy import func, select
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    others = fx.other_workspaces(db)
    busy = []
    for ws in others:
        n = sum(db.scalar(select(func.count()).select_from(m).where(m.workspace_id == ws)) or 0
                for m in (Asset, Issue, Document))
        if n:
            busy.append(ws)
    if not busy:
        return "dedicated"
    if not allow_shared:
        raise EvalError(f"this database holds {len(busy)} workspace(s) with records ({', '.join(busy[:5])}…): run "
                        "the evaluation against its own database (ASK_EVAL_DATABASE_URL, docs/ask-eval.md), or "
                        "pass allow_shared_database to accept that their shared records are visible to the questions")
    return f"shared database ({len(busy)} other workspaces with records)"


def _index(db: Session, config: EvalConfig, built: list[fx.Built]) -> dict:
    """The search index the run uses, built once for every model: which embedding model, how many passages."""
    if not config.embedding_model:
        return {"id": "none", "embedding_model": None, "rerank_model": config.rerank_model,
                "note": "no embedding model: search_knowledge answers that the index is not available"}
    from app.services import knowledge_index
    ep = endpoint(config, config.models[0] if config.models else "")
    counts = {}
    for b in built:
        for ws in b.workspaces:
            out = knowledge_index.index_workspace(db, ws, ep)
            counts[ws] = {k: v for k, v in out.items() if isinstance(v, (int, float))}
    ident = hashlib.sha256(json.dumps([config.embedding_model, config.rerank_model, sorted(counts.items())],
                                      default=str).encode()).hexdigest()[:16]
    return {"id": ident, "embedding_model": config.embedding_model, "rerank_model": config.rerank_model,
            "passages": counts}


def run(db: Session, dataset: Dataset, config: EvalConfig, *, kind: str = "benchmark",
        case_ids: Optional[list[str]] = None, endpoint_factory=None, allow_shared_database: bool = False,
        progress: Optional[Callable[[dict], None]] = None, run_id: Optional[str] = None,
        preflighted: Optional[dict] = None) -> dict:
    """The dataset (or `case_ids` of it), asked of every configured model `repeats` times, in fixtures built once
    for the run and dropped at its end. `endpoint_factory(model)` replaces the HTTP endpoint (the deterministic
    stand-ins, tests). Returns the raw results; app/ask_eval/report.py makes the report."""
    started_at = datetime.now(timezone.utc)
    run_id = run_id or fx.new_run_id()
    isolation = _isolation(db, allow_shared_database)
    cases = [c for c in dataset.cases if not case_ids or c.id in case_ids]
    if case_ids and len(cases) != len(set(case_ids)):
        raise EvalError("unknown case ids: " + ", ".join(sorted(set(case_ids) - {c.id for c in cases})))
    if not config.models:
        raise EvalError("no model to evaluate: set ASK_EVAL_MODELS")
    models = preflighted if preflighted is not None else (
        {m: {"status": "ok"} for m in config.models} if endpoint_factory else preflight(config, config.models))
    runnable = [m for m in config.models if models.get(m, {}).get("status") == "ok"]
    note = progress or (lambda _e: None)
    total = len(runnable) * len(cases) * config.repeats
    note({"type": "start", "run_id": run_id, "total": total, "models": models})

    built: dict[str, fx.Built] = {}
    results: dict[str, list] = {m: [] for m in runnable}
    index = {"id": "not built"}
    done = 0
    try:
        for fixture_id in sorted({c.fixture for c in cases}):
            built[fixture_id] = fx.build(db, dataset.fixtures[fixture_id], run_id)
        index = _index(db, config, list(built.values())) if not endpoint_factory else {
            "id": "none", "embedding_model": None, "rerank_model": None, "note": "deterministic stand-ins"}
        for model in runnable:
            ep = endpoint_factory(model) if endpoint_factory else endpoint(config, model)
            for case in cases:
                for attempt in range(config.repeats):
                    if restricted(dataset, case) and not endpoint_factory and not config.approved_for_restricted():
                        r = {"case": case.id, "skipped": "the server is not approved to receive restricted content "
                                                         "(ASK_EVAL_APPROVED_HOSTS)", "attempt": attempt}
                    else:
                        r = run_case(dataset, case, built[case.fixture], ep, timeout_s=config.case_timeout_s,
                                     scrub=config.scrub)
                        r["attempt"] = attempt
                    results[model].append(r)
                    done += 1
                    note({"type": "case", "model": model, "case": case.id, "attempt": attempt, "done": done,
                          "total": total, "passed": (r.get("scores") or {}).get("passed"),
                          "skipped": bool(r.get("skipped")), "error": r.get("error")})
    finally:
        fx.drop(db, [ws for b in built.values() for ws in b.workspaces])
    finished_at = datetime.now(timezone.utc)
    return {"run_id": run_id, "kind": kind, "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(), "isolation": isolation, "index": index,
            "config": config.public(), "preflight": models, "cases": [c.id for c in cases],
            "results": results, "complete": done == total}


def percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def spread(values: list[float]) -> Optional[float]:
    return round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0 if values else None
