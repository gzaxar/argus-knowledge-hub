"""Prometheus metrics (services/metrics.py): requests counted by route template, the pool read on demand, and no
listener unless a port is given."""
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from app.main import app
from app.services import metrics


def _value(text: str, prefix: str) -> float:
    for line in text.splitlines():
        if line.startswith(prefix):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def test_requests_are_counted_by_route_template_not_raw_path():
    client = TestClient(app)
    before = generate_latest(metrics.REGISTRY).decode()
    ok = 'argus_http_requests_total{method="GET",route="/health",status="200"}'
    lost = 'argus_http_requests_total{method="GET",route="(no route)",status="404"}'
    n_ok, n_lost = _value(before, ok), _value(before, lost)

    assert client.get("/health").status_code == 200
    client.get("/no/such/path/xyz-123")

    after = generate_latest(metrics.REGISTRY).decode()
    assert _value(after, ok) == n_ok + 1
    assert _value(after, lost) == n_lost + 1
    assert "xyz-123" not in after                       # the raw path never becomes a label
    assert 'argus_http_request_duration_seconds_bucket{le="0.01",method="GET",route="/health"}' in after
    assert _value(after, "argus_http_requests_in_flight") == 0


def test_the_database_pool_is_reported():
    text = generate_latest(metrics.REGISTRY).decode()
    for name in ("argus_db_pool_size", "argus_db_pool_checked_out", "argus_db_pool_max_overflow"):
        assert f"\n{name} " in text, name
    assert _value(text, "argus_db_pool_size ") == 20


def test_no_port_no_listener(monkeypatch):
    monkeypatch.delenv("ARGUS_METRICS_PORT", raising=False)
    started = []
    monkeypatch.setattr(metrics, "start_http_server", lambda *a, **k: started.append(a))
    monkeypatch.setattr(metrics, "_started", False)
    metrics.start()
    assert started == []
    monkeypatch.setenv("ARGUS_METRICS_PORT", "9100")
    metrics.start()
    metrics.start()                                     # once per process
    assert len(started) == 1 and started[0][0] == 9100


def test_storage_measurements_are_published():
    metrics.record_storage([{"area": "attachments", "used_bytes": 1234, "planned_bytes": 15 * 2 ** 30,
                             "available_bytes": 99, "disk_free_bytes": None}])
    text = generate_latest(metrics.REGISTRY).decode()
    assert _value(text, 'argus_storage_used_bytes{area="attachments"}') == 1234
    assert _value(text, 'argus_storage_available_bytes{area="attachments"}') == 99
    assert 'argus_storage_disk_free_bytes{area="attachments"}' not in text
