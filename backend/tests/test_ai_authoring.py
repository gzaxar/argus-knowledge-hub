"""Drafting and reviewing documents, and filling in a ticket.

The link-finding tests carry the weight. Asking a model which equipment a
document refers to gets a confident answer about a magnet that does not
exist, and a wrong edge in the graph is worse than a missing one, so the
matching is done against the inventory rather than by the model.
"""
import secrets

import pytest

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services.ai_authoring import draft_ticket_fields, review_document
from app.services.llm import Endpoint
from app.services.text_links import objects_mentioned


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def workspace():
    """A workspace with one camera, whose key and name are both distinctive."""
    workspace_id = f"auth-{secrets.token_hex(4)}"
    key = f"LNFT2-{secrets.randbelow(900000) + 100000}"
    db = SessionLocal()
    db.add(Workspace(id=workspace_id, name="Test"))
    db.flush()
    db.add(Schema(uid=f"{workspace_id}:cam", workspace_id=workspace_id, name="Cameras",
                  applies_to="objects"))
    db.flush()
    db.add(Asset(uid=f"a-{workspace_id}", workspace_id=workspace_id,
                 schema_uid=f"{workspace_id}:cam", key=key,
                 name="Quadrupole QUAD-BTF-03", type="Cameras"))
    db.commit()
    db.close()
    return workspace_id, key


# --- which objects a text mentions --------------------------------------

def test_an_object_key_in_the_text_is_found(workspace):
    workspace_id, key = workspace
    db = SessionLocal()
    found = objects_mentioned(db, workspace_id, f"Close the valve, then check {key}.")
    assert [f["matched_on"] for f in found] == ["key"]
    assert found[0]["key"] == key
    db.close()


def test_an_object_name_in_the_prose_is_found(workspace):
    workspace_id, _key = workspace
    db = SessionLocal()
    found = objects_mentioned(db, workspace_id, "Realign Quadrupole QUAD-BTF-03 afterwards.")
    assert [f["matched_on"] for f in found] == ["name"]
    db.close()


def test_a_key_that_belongs_to_nothing_is_not_returned(workspace):
    """The guard that makes this worth trusting: a plausible code that is
    not in the inventory produces no link at all."""
    workspace_id, _key = workspace
    db = SessionLocal()
    assert objects_mentioned(db, workspace_id, "See LNFM-999999 for details.") == []
    db.close()


def test_another_workspaces_object_is_not_matched(workspace):
    workspace_id, key = workspace
    other = f"other-{secrets.token_hex(4)}"
    db = SessionLocal()
    db.add(Workspace(id=other, name="Other"))
    db.commit()
    assert objects_mentioned(db, other, f"Mentions {key}") == []
    db.close()


def test_empty_text_finds_nothing(workspace):
    workspace_id, _key = workspace
    db = SessionLocal()
    assert objects_mentioned(db, workspace_id, "", None) == []
    db.close()


def test_keys_are_listed_before_names(workspace):
    """A key is something somebody wrote down; a name could be a
    coincidence of words, so the stronger evidence comes first."""
    workspace_id, key = workspace
    db = SessionLocal()
    found = objects_mentioned(
        db, workspace_id, f"{key} — see also Quadrupole QUAD-BTF-03"
    )
    assert found[0]["matched_on"] == "key"
    db.close()


# --- reviewing ----------------------------------------------------------

def test_a_review_is_remarks_and_nothing_else(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_authoring.complete",
        lambda *a, **k: '[{"severity": "high", "message": "No interlock check before the valve opens."},'
                        ' {"severity": "low", "message": "Pressure has no unit."}]',
    )
    db = SessionLocal()
    findings = review_document(db, Endpoint("https://x/v1", "m"), "T", None, "# Body")
    assert [f["severity"] for f in findings] == ["high", "low"], "most serious first"
    db.close()


def test_a_review_that_returns_rubbish_yields_no_findings(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_authoring.complete", lambda *a, **k: "It looks fine to me!"
    )
    db = SessionLocal()
    assert review_document(db, Endpoint("https://x/v1", "m"), "T", None, "# Body") == []
    db.close()


def test_an_invented_severity_is_not_trusted(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_authoring.complete",
        lambda *a, **k: '[{"severity": "catastrophic", "message": "Something"}]',
    )
    db = SessionLocal()
    findings = review_document(db, Endpoint("https://x/v1", "m"), "T", None, "# Body")
    assert findings[0]["severity"] == "low"
    db.close()


# --- ticket fields ------------------------------------------------------

def test_ticket_fields_are_read_from_the_report(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_authoring.complete",
        lambda *a, **k: '{"category": "fault", "impact": "service_down", '
                        '"detected_by": "alarm", "system": "Vacuum", '
                        '"root_cause": "A failed gauge.", "corrective_action": null}',
    )
    fields = draft_ticket_fields(Endpoint("https://x/v1", "m"), "Beam lost", "The alarm fired.")
    assert fields["category"] == "fault"
    assert fields["impact"] == "service_down"
    assert fields["root_cause"] == "A failed gauge."
    assert fields["corrective_action"] is None


def test_a_value_outside_the_vocabulary_is_dropped(monkeypatch):
    """The enumerations are what the hub reasons over; a model inventing
    "catastrophic" must not put it there."""
    monkeypatch.setattr(
        "app.services.ai_authoring.complete",
        lambda *a, **k: '{"category": "disaster", "impact": "service_down"}',
    )
    fields = draft_ticket_fields(Endpoint("https://x/v1", "m"), "T", "D")
    assert fields["category"] is None
    assert fields["impact"] == "service_down"


def test_the_workspaces_own_vocabulary_is_the_one_offered(monkeypatch):
    """The core's impact is neutral; an accelerator workspace's base type has the beam options its package
    extends it with, and those are what the model is offered and what is kept."""
    seen = {}

    def answer(_endpoint, _system, user, **_):
        seen["user"] = user
        return '{"impact": "beam_down"}'
    monkeypatch.setattr("app.services.ai_authoring.complete", answer)
    beam = [{"id": "beam_down", "value": "Beam down"}, {"id": "service_down", "value": "Service down"}]
    fields = draft_ticket_fields(Endpoint("https://x/v1", "m"), "T", "D", {"impact": beam})
    assert fields["impact"] == "beam_down" and "beam_down" in seen["user"]
    assert draft_ticket_fields(Endpoint("https://x/v1", "m"), "T", "D")["impact"] is None


def test_an_unreadable_reply_yields_empty_fields_not_an_error(monkeypatch):
    monkeypatch.setattr("app.services.ai_authoring.complete", lambda *a, **k: "hmm")
    fields = draft_ticket_fields(Endpoint("https://x/v1", "m"), "T", "D")
    assert set(fields.values()) == {None}
