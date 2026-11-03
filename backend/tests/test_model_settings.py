"""The AI settings name a model for structured work and say how each model is called (2026-11-03: the INFN
gateway's "auto" chose minimax, a reasoning model that cannot be told not to think, and at temperature 0 it
reasoned past the gateway's 300 s). Saved, applied to the calls, and tried with the Test button."""
import secrets
import uuid

from fastapi.testclient import TestClient

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.llm_config import LLMConfig
from app.models.user import User
from app.models.workspace import Workspace
from app.services import llm
from tests.test_intake import _Reply, _Stream

client = TestClient(app)


def _answer(content='{"date": "2026-10-16", "events": []}', model="minimax-m27"):
    return _Stream([{"choices": [{"delta": {"reasoning_content": "thinking…"}}]},
                    {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}], model=model)


def test_the_settings_are_saved_kept_and_checked():
    ws = f"ms-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    admin = User(id=str(uuid.uuid4()), email=f"admin-{ws}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    h = {"X-Workspace-Id": ws}
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
        body = {"base_url": "https://gateway.example/v1", "model": "auto", "enabled": True,
                "structured_model": " qwen-fast ",
                "model_settings": {"auto": {"temperature": 0.6, "no_thinking": False, "time_limit_s": 200},
                                   "qwen-fast": {"json_mode": False}}}
        out = client.put("/v1/ai/config", headers=h, json=body).json()
        assert out["structured_model"] == "qwen-fast"
        assert out["model_settings"]["auto"] == {"temperature": 0.6, "no_thinking": False, "json_mode": True,
                                                 "time_limit_s": 200}
        # Left out on an update: kept. Out of range: refused.
        again = client.put("/v1/ai/config", headers=h, json={**body, "model_settings": None}).json()
        assert again["model_settings"]["qwen-fast"]["json_mode"] is False
        bad = client.put("/v1/ai/config", headers=h,
                         json={**body, "model_settings": {"auto": {"temperature": 5}}})
        assert bad.status_code == 422
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db.query(LLMConfig).filter(LLMConfig.workspace_id == ws).delete()
        db.delete(db.get(Workspace, ws))
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()


def test_a_structured_answer_comes_from_the_structured_model_called_as_its_settings_say(monkeypatch):
    sent = []

    def gateway(url, headers=None, json=None, timeout=None, **kw):
        sent.append(json)
        return _answer()
    monkeypatch.setattr(llm.requests, "post", gateway)
    ep = llm.Endpoint(base_url="https://gateway.example/v1", model="auto", structured_model="minimax-m27",
                      model_settings={"minimax-m27": {"temperature": 1.0, "no_thinking": False, "json_mode": False}})
    assert llm.complete_structured(ep, "s", "u").model == "minimax-m27"
    assert sent[0]["model"] == "minimax-m27" and sent[0]["temperature"] == 1.0
    assert "chat_template_kwargs" not in sent[0] and "response_format" not in sent[0]

    # No settings: the model's own temperature, JSON mode, told not to think; the chat model if none is named.
    sent.clear()
    plain = llm.Endpoint(base_url="https://gateway.example/v1", model="auto")
    llm.complete_structured(plain, "s", "u")
    assert sent[0]["model"] == "auto" and "temperature" not in sent[0]
    assert sent[0]["response_format"] == {"type": "json_object"} and sent[0]["chat_template_kwargs"]

    # Chat and classification keep 0 unless the chat model's settings say otherwise.
    assert plain.temperature("auto", 0) == {"temperature": 0}
    assert ep.temperature("minimax-m27", 0) == {"temperature": 1.0}

    # Its own time limit.
    monkeypatch.setattr(llm.time, "monotonic", iter([0.0] + [1000.0] * 50).__next__)
    limited = llm.Endpoint(base_url="https://gateway.example/v1", model="auto",
                           model_settings={"auto": {"time_limit_s": 60}})
    try:
        llm.complete_structured(limited, "s", "u")
        raise AssertionError("past its limit")
    except llm.LLMOvertime as e:
        assert e.limit_s == 60


def test_an_intake_profiles_model_still_answers_its_intake():
    from app.intake import profiles
    from app.models.intake import IntakeProfile
    ep = llm.Endpoint(base_url="https://gateway.example/v1", model="auto", structured_model="qwen-fast")
    chosen = profiles.endpoint_for(ep, IntakeProfile(model="evaluated-model", vision_model=None))
    assert chosen.model == chosen.structured_model == "evaluated-model"


def test_the_test_button_says_how_long_which_model_and_whether_the_json_came(monkeypatch):
    ws = f"mt-{secrets.token_hex(3)}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.add(LLMConfig(workspace_id=ws, base_url="https://gateway.example/v1", model="auto", enabled=True))
    admin = User(id=str(uuid.uuid4()), email=f"admin-{ws}@argus.test", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    sent = []
    answers = [_answer(), _answer("Sure, here are the events of the day: …", model="chatty")]

    def gateway(url, headers=None, json=None, timeout=None, **kw):
        sent.append(json)
        return answers.pop(0)
    monkeypatch.setattr(llm.requests, "post", gateway)
    try:
        app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
        h = {"X-Workspace-Id": ws}
        r = client.post("/v1/ai/config/test-model", headers=h,
                        json={"model": "auto", "settings": {"temperature": 0.7, "no_thinking": False}}).json()
        assert r["ok"] and r["valid_json"] and r["answered_by"] == "minimax-m27" and r["model"] == "auto"
        assert sent[0]["temperature"] == 0.7 and "chat_template_kwargs" not in sent[0]    # the form's settings
        r = client.post("/v1/ai/config/test-model", headers=h, json={"model": "chatty"}).json()
        assert not r["ok"] and "not the JSON object" in r["error"]
        db.expire_all()
        assert not db.get(LLMConfig, ws).model_settings                                   # a test saves nothing
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db.query(LLMConfig).filter(LLMConfig.workspace_id == ws).delete()
        db.delete(db.get(Workspace, ws))
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()
