"""Prometheus metrics, for the operators deciding when to scale (docs/k8sda.md, "Metrics").

Requests by route template (never the raw path: a scanner's random URLs fall under "(no route)"), method and
status; their duration; those in flight; and the database connection pool. Served on a port of its own
(ARGUS_METRICS_PORT), never through the ingress: the public reaches port 8080 only, and the chart's network
policy lets only the cluster's Prometheus in. Unset, nothing listens; the counters still count, at the cost of a
dictionary lookup per request.

Each API process serves its own numbers; Prometheus adds the replicas up.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Iterator

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

log = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

REQUESTS = Counter("argus_http_requests", "API requests, by route template, method and status.",
                   ["method", "route", "status"], registry=REGISTRY)
DURATION = Histogram("argus_http_request_duration_seconds",
                     "Time until the API's response starts, by route template and method.",
                     ["method", "route"], registry=REGISTRY,
                     buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60))
IN_FLIGHT = Gauge("argus_http_requests_in_flight", "API requests being handled now.", registry=REGISTRY)
# The hourly storage measurement (services/storage.py): local-path volumes report nothing to the kubelet, so
# this is where a dashboard sees them fill.
STORAGE = {key: Gauge(f"argus_storage_{key}", doc, ["area"], registry=REGISTRY) for key, doc in (
    ("used_bytes", "Bytes used by an area (attachments, portability, database)."),
    ("planned_bytes", "Room planned for an area (the chart's volume size)."),
    ("available_bytes", "What an area can still take: planned room left or disk free, whichever is less."),
    ("disk_free_bytes", "Free space on the disk under an area's directory."),
)}


class _PoolCollector(Collector):
    """The SQLAlchemy pool, read when Prometheus asks: how many connections are busy, and how many it may open."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from app.db import engine
        pool = engine.pool
        for name, doc, read in (
            ("argus_db_pool_size", "Connections the pool keeps open.", pool.size),
            ("argus_db_pool_checked_out", "Connections in use by a request or a background job.", pool.checkedout),
            ("argus_db_pool_overflow", "Connections opened beyond the pool size (negative: not all opened yet).",
             pool.overflow),
            ("argus_db_pool_max_overflow", "Connections the pool may open beyond its size.",
             lambda: getattr(pool, "_max_overflow", 0)),
        ):
            try:
                yield GaugeMetricFamily(name, doc, value=float(read()))
            except Exception:  # noqa: BLE001 — a pool without the method (tests' NullPool) has no number
                continue


REGISTRY.register(_PoolCollector())

# What ARGUS holds and how it is used (services/app_metrics.py), read from the database at most once a minute.
if os.environ.get("ARGUS_APP_METRICS", "on").lower() not in ("off", "0", "false"):
    from app.services.app_metrics import AppCollector
    REGISTRY.register(AppCollector())

_started = False
_lock = threading.Lock()


def observe(method: str, route: str, status: int, seconds: float) -> None:
    REQUESTS.labels(method, route, str(status)).inc()
    DURATION.labels(method, route).observe(seconds)


def record_storage(areas: list[dict]) -> None:
    for a in areas:
        for key, gauge in STORAGE.items():
            value = a.get(key)
            if value is not None:
                gauge.labels(a["area"]).set(value)


QUOTA = Gauge("argus_quota_ratio", "What a workspace uses of a quota (1 is the limit; absent: unlimited).",
              ["workspace", "quota"], registry=REGISTRY)


def record_quota(workspace: str, ratios: dict) -> None:
    for key, ratio in ratios.items():
        if ratio is None:
            try:
                QUOTA.remove(workspace, key)
            except KeyError:
                pass
        else:
            QUOTA.labels(workspace, key).set(ratio)


def start() -> None:
    """Listen on ARGUS_METRICS_PORT, once per process; no port, no listener."""
    global _started
    port = os.environ.get("ARGUS_METRICS_PORT", "").strip()
    if not port:
        return
    with _lock:
        if _started:
            return
        try:
            start_http_server(int(port), registry=REGISTRY)
            _started = True
            log.info("metrics on port %s", port)
        except (OSError, ValueError):
            log.warning("metrics port %s could not be opened; metrics are off", port, exc_info=True)
