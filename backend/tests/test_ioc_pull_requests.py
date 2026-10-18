"""The IOC engineer's pull requests: proposed in Ask ARGUS, checked as they are proposed, opened only when the
person confirms, and never by an API token.

The point of the checks is that a pull request ARGUS opens is one the IOC pod could run: a fixture that would
not start is refused when proposed, with the reason the model needs to fix it, and a new driver's entity models
(one repository) count as known to the template that uses them (another).
"""
import json

import pytest

from app.ioc_engineer import pull_requests as prs
from app.services import ask_actions
from tests.test_ask_actions import answer, call, client, events, scripted, world  # noqa: F401 — fixtures
from tests.test_ioc_engineer import checkout  # noqa: F401 — fixture

GOOD_FIXTURE = ("iocname: vgauge-test\ntemplate: gauge\ndevtype: tpg\niocprefix: TEST:VAC\nserver: 10.0.0.1\n"
                "devices:\n  - name: G1\n")


@pytest.fixture()
def github(monkeypatch):
    """GitHub, as far as opening a pull request needs it; every request is kept."""
    import requests
    calls = []

    class Response:
        def __init__(self, data, status=200):
            self.status_code, self._data = status, data
            self.content = json.dumps(data).encode()

        def json(self):
            return self._data

    def fake(method, url, timeout=None, headers=None, json=None):  # noqa: A002
        path = url.split("api.github.com", 1)[1]
        calls.append({"method": method, "path": path, "json": json, "auth": (headers or {}).get("Authorization")})
        if method == "GET" and path.endswith("/infn-epics/ibek-templates"):
            return Response({"default_branch": "main"})
        if "/git/ref/heads/" in path:
            return Response({"object": {"sha": "base-sha"}})
        if "/git/commits/" in path and method == "GET":
            return Response({"tree": {"sha": "base-tree"}})
        if path.endswith("/git/trees"):
            return Response({"sha": "new-tree"}, 201)
        if path.endswith("/git/commits"):
            return Response({"sha": "new-commit"}, 201)
        if path.endswith("/git/refs"):
            return Response({"ref": json["ref"]}, 201)
        if path.endswith("/pulls"):
            return Response({"number": 42, "html_url": "https://github.com/infn-epics/ibek-templates/pull/42"}, 201)
        return Response({"message": "Not Found"}, 404)

    monkeypatch.setattr(requests, "request", fake)
    monkeypatch.setenv("ARGUS_GITHUB_TOKEN", "test-token")
    monkeypatch.delenv("ARGUS_IOC_PR_REPOS", raising=False)
    return calls


# --- the checks --------------------------------------------------------------------------------------------------

def test_only_allowed_repositories_and_paths_inside_them(checkout, github):
    ok = [{"path": "tests/vac-gauge2-test.yaml", "content": GOOD_FIXTURE}]
    with pytest.raises(prs.Refused, match="only on"):
        prs.check("someone/else", ok)
    for path in ("../escape.yaml", "/abs.yaml", ".github/workflows/ci.yml", "a//b.yaml"):
        with pytest.raises(prs.Refused):
            prs.check("infn-epics/ibek-templates", [{"path": path, "content": "x: 1\n"}])
    with pytest.raises(prs.Refused, match="not valid YAML"):
        prs.check("infn-epics/ibek-templates", [{"path": "tests/x.yaml", "content": "a: [1,\n"}])
    with pytest.raises(prs.Refused, match="module and its entity_models"):
        prs.check("infn-epics/ibek-support-infn", [{"path": "x/x.ibek.support.yaml", "content": "module: x\n"}])


def test_no_credential_and_no_odd_branch_ever_goes_out(checkout, github):
    leaked = GOOD_FIXTURE + "password_hint: ghp_" + "A" * 36 + "\n"
    with pytest.raises(prs.Refused, match="credential.*GitHub token"):
        prs.check("infn-epics/ibek-templates", [{"path": "tests/vac-gauge2-test.yaml", "content": leaked}])
    with pytest.raises(prs.Refused):
        prs.check("infn-epics/ibek-templates", [{"path": "./tests/x.yaml", "content": "a: 1\n"}])
    assert prs.safe_branch(" release/v26.10 ") == "release/v26.10" and prs.safe_branch("") is None
    for bad in ("main/../../user", "-x", "a b", "x/", "refs?x"):
        with pytest.raises(prs.Refused):
            prs.safe_branch(bad)


def test_a_fixture_that_would_not_start_is_refused_with_the_reason(checkout, github):
    bad = GOOD_FIXTURE.replace("devtype: tpg", "devtype: legacy")
    with pytest.raises(prs.Refused, match="would not start: .*legacy.device is not compiled"):
        prs.check("infn-epics/ibek-templates", [{"path": "tests/vac-gauge2-test.yaml", "content": bad}])
    checked = prs.check("infn-epics/ibek-templates", [{"path": "tests/vac-gauge2-test.yaml", "content": GOOD_FIXTURE}])
    assert checked["checks"] == ["tests/vac-gauge2-test.yaml: renders and passes the ibek check (template gauge)"]


def test_a_new_driver_is_known_to_the_template_proposed_after_it(checkout, github):
    support = ("module: newg\nentity_models:\n  - name: device\n    description: d\n    parameters:\n"
               "      NAME: {type: id, description: port}\n      IP: {type: str, description: ip}\n")
    driver = prs.check("infn-epics/ibek-support-infn", [{"path": "newg/newg.ibek.support.yaml", "content": support}])
    assert driver["models"] == ["newg.device"]
    template = ("ioc_name: {{ iocname }}\nentities:\n{%- for d in devices %}\n- type: newg.device\n"
                "  NAME: \"{{ d.name }}\"\n  IP: \"{{ server }}\"\n{%- endfor %}\n")
    fixture = "iocname: t\ntemplate: newg\niocprefix: T\nserver: h\ndevices: [{name: A}]\n"
    files = [{"path": "templates/io/newg/newg.yaml.j2", "content": template},
             {"path": "tests/io-newg-test.yaml", "content": fixture}]
    with pytest.raises(prs.Refused, match="unknown entity type newg.device"):
        prs.check("infn-epics/ibek-templates", files)                 # on its own, the type is unknown
    checked = prs.check("infn-epics/ibek-templates", files, prs._models_in(driver["files"]))
    assert checked["checks"][0].startswith("tests/io-newg-test.yaml: renders")


# --- through Ask ARGUS -------------------------------------------------------------------------------------------

def test_a_pull_request_waits_for_the_person_and_then_opens_as_a_draft(world, checkout, github, monkeypatch):
    w = world
    sent = scripted(monkeypatch, [
        call("propose_ioc_pull_request", {
            "repository": "infn-epics/ibek-templates", "title": "Gauge fixture for VGAUGE",
            "description": "A fixture for the new gauge IOC.", "reason": "asked for a PR",
            "files": [{"path": "tests/vac-gauge2-test.yaml", "content": GOOD_FIXTURE}]}),
        answer("Proposed a pull request; apply it to open it."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "Open a PR with that fixture"}))
    assert "propose_ioc_pull_request" in sent[0]["tools"]
    proposal = next(e["action"] for e in evs if e["type"] == "proposal")
    assert proposal["kind"] == "pull_request" and proposal["status"] == "proposed"
    assert "ibek-templates" in proposal["summary"] and "1 file" in proposal["summary"]
    assert github == []                                                  # nothing has left ARGUS yet

    cid = evs[0]["id"]
    applied = client.post(f"/v1/ai/conversations/{cid}/actions/apply", headers=w["h"],
                          json={"ids": [proposal["id"]]}).json()
    assert applied[0]["status"] == "applied", applied
    result = applied[0]["result"]
    assert result["url"].endswith("/pull/42") and result["key"] == "infn-epics/ibek-templates#42"
    assert result["branch"].startswith("argus/gauge-fixture-for-vgauge-")

    by = {(c["method"], c["path"].split("/")[-1]): c for c in github}
    tree = by[("POST", "trees")]["json"]
    assert tree["base_tree"] == "base-tree" and tree["tree"][0]["path"] == "tests/vac-gauge2-test.yaml"
    assert tree["tree"][0]["content"] == GOOD_FIXTURE
    assert by[("POST", "refs")]["json"] == {"ref": f"refs/heads/{result['branch']}", "sha": "new-commit"}
    pr = by[("POST", "pulls")]["json"]
    assert pr["draft"] is True and pr["base"] == "main" and pr["head"] == result["branch"]
    assert "@argus.test" in pr["body"] and "ARGUS does not merge" in pr["body"]
    assert "renders and passes the ibek check" in pr["body"]
    assert all(c["auth"] == "Bearer test-token" for c in github)
    assert not any(c["method"] in ("PUT", "PATCH", "DELETE") or "merge" in c["path"] for c in github)


def test_a_failing_change_is_refused_when_proposed_not_when_applied(world, checkout, github, monkeypatch):
    w = world
    bad = GOOD_FIXTURE.replace("devtype: tpg", "devtype: legacy")
    scripted(monkeypatch, [
        call("propose_ioc_pull_request", {"repository": "infn-epics/ibek-templates", "title": "Broken",
                                          "files": [{"path": "tests/vac-bad-test.yaml", "content": bad}]}),
        answer("It would not start; fixing."),
    ])
    evs = events(client.post("/v1/ai/chat", headers=w["h"], json={"question": "PR this"}))
    assert not [e for e in evs if e["type"] == "proposal"]
    refused = next(e for e in evs if e["type"] == "step" and e["error"])
    assert "would not start" in refused["error"] and github == []


def test_not_offered_without_a_credential(world, checkout, monkeypatch):
    monkeypatch.delenv("ARGUS_GITHUB_TOKEN", raising=False)
    sent = scripted(monkeypatch, [answer("No.")])
    client.post("/v1/ai/chat", headers=world["h"], json={"question": "Open a PR"})
    assert "propose_ioc_pull_request" not in sent[0]["tools"]


def test_only_a_person_opens_one():
    token = object()                       # an API token's identity: not an OidcIdentity
    assert ask_actions._permitted(None, token, "ws", "create") is True
    assert ask_actions._permitted(None, token, "ws", "pull_request") is False
