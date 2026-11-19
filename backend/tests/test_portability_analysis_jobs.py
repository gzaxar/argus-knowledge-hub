"""Analysis dispatch: keep the synchronous API and commit requests before workers read them."""
from types import SimpleNamespace
from unittest.mock import Mock

from app.routers import portability as api


def _context(monkeypatch):
    db = Mock()
    identity = object()
    person = SimpleNamespace(user=SimpleNamespace(is_admin=False))
    exp = SimpleNamespace(id="exp-test")
    cfg = SimpleNamespace(policy=SimpleNamespace(export_permission="read"))
    monkeypatch.setattr(api, "_person", lambda _: person)
    monkeypatch.setattr(api, "actor_of", lambda _: "alice")
    monkeypatch.setattr(api, "resolve_permission", lambda *args: True)
    monkeypatch.setattr(api, "_export", lambda *args: exp)
    monkeypatch.setattr(api.service, "config", lambda: cfg)
    monkeypatch.setattr(api.service, "create_export", Mock(return_value=exp))
    monkeypatch.setattr(api.service, "analyse_export", Mock(return_value=exp))
    monkeypatch.setattr(api.service, "set_export_decisions", Mock(return_value=exp))
    monkeypatch.setattr(api.service, "export_view", lambda e: {"id": e.id})
    return db, identity, exp, cfg


def _body():
    return SimpleNamespace(mode="workspace", workspaces=["ws-test"], classifications=[],
                           repository=None, artifact_store=None, recipients=[], decisions={},
                           base_export_id=None, identity_profile=None, purpose=None)


def test_create_commits_before_starting_analysis_in_another_session(monkeypatch):
    db, identity, exp, cfg = _context(monkeypatch)
    worker = Mock()
    worker.get.return_value = exp

    def queue(kind, subject, action, actor, run):
        db.commit.assert_called_once()
        assert (kind, subject, action, actor) == ("export", exp.id, "analyse", "alice")
        api.service.analyse_export.assert_not_called()
        run(worker)
        return {"job": "queued"}
    monkeypatch.setattr(api, "_background", queue)
    assert api.create_export(_body(), background=True, identity=identity, db=db) == {"job": "queued"}
    api.service.analyse_export.assert_called_once_with(worker, exp, "alice", cfg)


def test_create_without_background_preserves_the_existing_response(monkeypatch):
    db, identity, exp, cfg = _context(monkeypatch)
    background = Mock()
    monkeypatch.setattr(api, "_background", background)
    assert api.create_export(_body(), identity=identity, db=db) == {"id": exp.id}
    api.service.analyse_export.assert_called_once_with(db, exp, "alice", cfg)
    db.commit.assert_called_once()
    background.assert_not_called()


def test_decisions_are_applied_in_the_worker_session(monkeypatch):
    db, identity, exp, cfg = _context(monkeypatch)
    worker = Mock()
    worker.get.return_value = exp
    body = SimpleNamespace(decisions={"opaque_blobs": "approve_opaque"})
    queued = []
    monkeypatch.setattr(api, "_background", lambda *args: queued.append(args) or {"job": "queued"})
    assert api.decide_export(exp.id, body, background=True, identity=identity, db=db) == {"job": "queued"}
    api.service.set_export_decisions.assert_not_called()
    queued[0][-1](worker)
    api.service.set_export_decisions.assert_called_once_with(worker, exp, body.decisions, "alice", cfg)


def test_analysis_can_be_retried_as_a_job(monkeypatch):
    db, identity, exp, cfg = _context(monkeypatch)
    worker = Mock()
    worker.get.return_value = exp
    queued = []
    monkeypatch.setattr(api, "_background", lambda *args: queued.append(args) or {"job": "queued"})
    assert api.analyse_export(exp.id, background=True, identity=identity, db=db) == {"job": "queued"}
    api.service.analyse_export.assert_not_called()
    queued[0][-1](worker)
    api.service.analyse_export.assert_called_once_with(worker, exp, "alice", cfg)
