"""The application's own numbers for Prometheus and Grafana: who uses ARGUS, what it holds, what waits in the
ticket and service-portal queues, and what the AI costs (docs/k8sda.md, "Metrics").

Read from the database when Prometheus scrapes, at most once a minute per process (ARGUS_APP_METRICS_SECONDS), in
one short read-only session. They are aggregates only: labels name workspaces, sites, services, kinds, models and
clients, never a person or any text.

Every API replica reports the same values: a dashboard takes `max` of them, not `sum`.

Windows (`window` label) are 1d, 7d and 30d back from now. The per-day usage tables (LLM) count the calendar days
(UTC) that window reaches into.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

log = logging.getLogger(__name__)

WINDOWS = {"1d": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def _ttl() -> float:
    try:
        return float(os.environ.get("ARGUS_APP_METRICS_SECONDS", "60"))
    except ValueError:
        return 60.0


def gather(db) -> list[tuple[str, str, list[str], list[tuple[tuple, float]]]]:
    """Each metric as (name, help, label names, [(label values, value)])."""
    from sqlalchemy import func, select

    from app.models.ask_conversation import AskConversation, AskMessage
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    from app.models.service_portal import SupportRequest
    from app.models.usage import AskFeedback, UsageLLM, UsagePresence

    now = datetime.now(timezone.utc)
    out = []

    rows = []
    for window, span in WINDOWS.items():
        for client, n in db.execute(select(UsagePresence.client, func.count(func.distinct(UsagePresence.person)))
                                    .where(UsagePresence.bucket >= now - span).group_by(UsagePresence.client)):
            rows.append(((window, client or "unknown"), n))
        total = db.scalar(select(func.count(func.distinct(UsagePresence.person))).where(UsagePresence.bucket >= now - span))
        rows.append(((window, "all"), total or 0))
    out.append(("argus_active_people", "People who used ARGUS in the window, by client (web, app, api; all: anyone).",
                ["window", "client"], rows))

    kinds = (("objects", Asset, Asset.deleted_at.is_(None)), ("tickets", Issue, Issue.deleted_at.is_(None)),
             ("documents", Document, Document.retired_at.is_(None)))
    held, created, changed = [], [], []
    for kind, model, live in kinds:
        for ws, n in db.execute(select(model.workspace_id, func.count()).where(live).group_by(model.workspace_id)):
            held.append(((ws, kind), n))
        for window, span in WINDOWS.items():
            for ws, n in db.execute(select(model.workspace_id, func.count()).where(model.created_at >= now - span)
                                    .group_by(model.workspace_id)):
                created.append(((ws, kind, window), n))
            for ws, n in db.execute(select(model.workspace_id, func.count()).where(
                    model.updated_at >= now - span, model.created_at < now - span).group_by(model.workspace_id)):
                changed.append(((ws, kind, window), n))
    out.append(("argus_records", "Records held, by workspace and kind (objects, tickets, documents).",
                ["workspace", "kind"], held))
    out.append(("argus_records_created", "Records created in the window.", ["workspace", "kind", "window"], created))
    out.append(("argus_records_changed", "Records made before the window and changed in it.",
                ["workspace", "kind", "window"], changed))

    out.append(("argus_tickets_open", "Open tickets, by workspace and state.", ["workspace", "state"],
                [((ws, state), n) for ws, state, n in db.execute(
                    select(Issue.workspace_id, Issue.state, func.count()).where(
                        Issue.deleted_at.is_(None), Issue.closed_at.is_(None)).group_by(Issue.workspace_id, Issue.state))]))

    open_requests, oldest = [], []
    for site, service, n, first in db.execute(
            select(SupportRequest.site_id, SupportRequest.service_name, func.count(), func.min(SupportRequest.created_at))
            .join(Issue, Issue.uid == SupportRequest.issue_uid)
            .where(Issue.deleted_at.is_(None), Issue.closed_at.is_(None))
            .group_by(SupportRequest.site_id, SupportRequest.service_name)):
        open_requests.append(((site, service), n))
        if first is not None:
            oldest.append(((site, service), (now - first).total_seconds()))
    out.append(("argus_service_requests_open", "Open service-portal requests, by site and service.",
                ["site", "service"], open_requests))
    out.append(("argus_service_request_oldest_open_seconds", "Age of the oldest open request, by site and service.",
                ["site", "service"], oldest))
    out.append(("argus_service_requests_created", "Service-portal requests sent in the window, by site.",
                ["site", "window"], [((site, window), n) for window, span in WINDOWS.items()
                                      for site, n in db.execute(select(SupportRequest.site_id, func.count()).where(
                                          SupportRequest.created_at >= now - span).group_by(SupportRequest.site_id))]))

    calls, failures, tokens = [], [], []
    for window, span in WINDOWS.items():
        since = (now - span).date()
        for ws, model, c, f, p, o in db.execute(
                select(UsageLLM.workspace_id, UsageLLM.model, func.sum(UsageLLM.calls), func.sum(UsageLLM.failures),
                       func.sum(UsageLLM.prompt_tokens), func.sum(UsageLLM.completion_tokens))
                .where(UsageLLM.day >= since).group_by(UsageLLM.workspace_id, UsageLLM.model)):
            labels = (ws or "(none)", model or "?", window)
            calls.append((labels, c or 0))
            failures.append((labels, f or 0))
            tokens.append(((*labels, "prompt"), p or 0))
            tokens.append(((*labels, "completion"), o or 0))
    out.append(("argus_llm_calls", "Language-model calls in the window.", ["workspace", "model", "window"], calls))
    out.append(("argus_llm_failures", "Language-model calls that failed in the window.",
                ["workspace", "model", "window"], failures))
    out.append(("argus_llm_tokens", "Language-model tokens in the window, prompt or completion.",
                ["workspace", "model", "window", "direction"], tokens))

    questions, answers, feedback = [], [], []
    for window, span in WINDOWS.items():
        for ws, n in db.execute(select(AskConversation.workspace_id, func.count())
                                .join(AskMessage, AskMessage.conversation_id == AskConversation.id)
                                .where(AskMessage.role == "user", AskMessage.created_at >= now - span)
                                .group_by(AskConversation.workspace_id)):
            questions.append(((ws, window), n))
        for stopped, n in db.execute(select(AskMessage.stopped, func.count()).where(
                AskMessage.role == "assistant", AskMessage.created_at >= now - span).group_by(AskMessage.stopped)):
            answers.append(((stopped or "answered", window), n))
        for rating, n in db.execute(select(AskFeedback.rating, func.count()).where(
                AskFeedback.created_at >= now - span).group_by(AskFeedback.rating)):
            feedback.append(((rating, window), n))
    out.append(("argus_ask_questions", "Questions asked to Ask ARGUS in the window, by workspace.",
                ["workspace", "window"], questions))
    out.append(("argus_ask_answers", "Ask ARGUS answers in the window, by how they ended.", ["outcome", "window"],
                answers))
    out.append(("argus_ask_feedback", "Ask ARGUS feedback in the window, up or down.", ["rating", "window"], feedback))
    return out


class AppCollector(Collector):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._at = 0.0
        self._cached: list = []

    def _read(self) -> list:
        from sqlalchemy import text

        from app.db import SessionLocal
        db = SessionLocal()
        try:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
                db.execute(text("SET LOCAL statement_timeout = '10s'"))
            return gather(db)
        finally:
            db.rollback()
            db.close()

    def collect(self) -> Iterator[GaugeMetricFamily]:
        with self._lock:
            if time.monotonic() - self._at >= _ttl():
                try:
                    self._cached = self._read()
                    ok = 1.0
                except Exception:  # noqa: BLE001 — a scrape must not fail: the last numbers stay, and this says so
                    log.warning("application metrics could not be read", exc_info=True)
                    ok = 0.0
                self._at = time.monotonic()
                self._ok = ok
            cached, ok = self._cached, getattr(self, "_ok", 0.0)
        yield GaugeMetricFamily("argus_app_metrics_up", "1 when the application metrics were last read fine.", value=ok)
        for name, doc, labels, rows in cached:
            family = GaugeMetricFamily(name, doc, labels=labels)
            for values, value in rows:
                family.add_metric([str(v) for v in values], float(value or 0))
            yield family
