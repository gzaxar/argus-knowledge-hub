"""The user guide: the same Markdown read by the Help pages, Ask ARGUS (search_help, read_help) and MCP
clients. What is tested is that every topic is well formed, that a question finds the section that answers
it, that the API serves it to anyone signed in, and that Ask can call it."""
import json

import pytest
from fastapi.testclient import TestClient

from app import help as guide
from app.main import app
from app.services import mcp_tools

client = TestClient(app)


def test_every_topic_is_well_formed():
    topics = guide.topics()
    assert len(topics) >= 14
    slugs = [t.slug for t in topics]
    assert len(slugs) == len(set(slugs))
    for t in topics:
        assert t.title and t.summary and t.keywords, t.slug
        assert t.sections and all(s.text for s in t.sections), t.slug
        assert "\n## " in "\n" + t.body, f"{t.slug} has no sections"
    assert [t.order for t in topics] == sorted(t.order for t in topics)


@pytest.mark.parametrize("question, topic", [
    ("how do I export my workspaces to a github repository", "export-import"),
    ("move my local argus to production", "export-import"),
    ("artifact store vault-dev is not configured here", "export-import"),
    ("give a role to a group", "workspaces-people-roles"),
    ("import an EPIK8s values.yaml", "imports"),
    ("output-token limit for a reasoning model", "ai-settings"),
    ("report a fault ticket", "service-desk"),
    ("apply the changes the assistant proposed", "ask-argus"),
])
def test_a_question_finds_the_topic_that_answers_it(question, topic):
    hits = guide.search(question)
    assert hits and hits[0]["topic"] == topic, [(h["topic"], h["section"]) for h in hits[:3]]


def test_the_guide_names_only_pages_that_exist():
    """A guide that sends people to a page the app does not have is worse than none: the side bar and
    administration labels it cites must be the app's."""
    body = "\n".join(t.body for t in guide.topics())
    for label in ("Workspace settings", "Columns", "Type catalogue", "Labels & QR codes", "Bulk changes", "Channels ↔ hardware",
                  "Map imported records", "Review queue", "Knowledge graph", "Ask ARGUS", "AI endpoint",
                  "Administration → Portability", "Download checkpoint (.tar)", "Fetch into quarantine",
                  "Output-token limit", "Check endpoint", "Build the index", "Add a repository",
                  "Make a signing key", "Trust it", "Confirm the fingerprints", "Read and write",
                  "In the repository, with the archive", "Change address or provider", "Artifact stores",
                  "Re-ranker model", "Give this workspace settings of its own", "Use the installation's settings instead",
                  "My account", "Robot tokens", "Generate token", "Generate robot token", "Daily logbook upload",
                  "Read and write", "Administration → API tokens"):
        assert label in body, label


def test_the_api_serves_the_guide_to_anyone_signed_in(monkeypatch):
    assert client.get("/v1/help").status_code == 401
    from app.auth import OidcIdentity, get_identity
    from app.models.user import User
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=User(id="u", email="u@x.org"))
    try:
        index = client.get("/v1/help").json()
        assert index[0]["slug"] == "getting-started" and index[0]["sections"]
        found = client.get("/v1/help/search", params={"q": "export to gitlab"}).json()
        assert found[0]["topic"] == "export-import"
        page = client.get("/v1/help/export-import").json()
        assert page["title"].startswith("Export and import") and "## Import, step by step" in page["body"]
        assert client.get("/v1/help/nothing-here").status_code == 404
    finally:
        app.dependency_overrides.pop(get_identity, None)


def test_ask_and_mcp_clients_can_read_it():
    names = {t["name"] for t in mcp_tools.catalogue()}
    assert {"search_help", "read_help"} <= names
    found = json.loads(mcp_tools.call(None, "any", "search_help", {"query": "step by step import from git"}))
    assert found["results"][0]["topic"] == "export-import"
    topic = json.loads(mcp_tools.call(None, "any", "read_help", {"topic": "export-import"}))
    assert topic["found"] and "Verify" in topic["body"]
    missing = json.loads(mcp_tools.call(None, "any", "read_help", {"topic": "nope"}))
    assert not missing["found"] and missing["topics"]



def test_the_guide_answers_how_a_facility_uploads_its_logbook():
    found = guide.search("robot token to upload the daily logbook")
    assert found[0]["topic"] == "account-and-api-tokens"



def test_the_guide_answers_how_to_rebuild_a_lost_installation():
    found = guide.search("rebuild a wiped installation from the git archive")
    assert found[0]["topic"] == "export-import" and "rebuild" in found[0]["section"].lower()
