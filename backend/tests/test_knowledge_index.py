"""The written knowledge Ask ARGUS searches (RAG): indexed incrementally, found by meaning and by words, and
shown only to whoever may read it — the rules the rest of the hub applies, applied when searching.

The embedding model is a fake (words hashed into a small vector), so what is tested is the indexing, the
ranking and the access rules, not a model.
"""
import hashlib
import math
import os
import re
import secrets
import tempfile

import pytest
from sqlalchemy import text

from app.db import SessionLocal
from app.models.asset import Asset
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.issue import Issue, IssueComment
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.services import knowledge_index as ki
from app.services.llm import Endpoint

SYNONYMS = {"pompa": "pump", "ionica": "ion", "sostituire": "replace"}


def fake_embed(endpoint, texts):
    out = []
    for t in texts:
        t = t.split("Query: ", 1)[-1]
        v = [0.0] * 64
        for w in re.findall(r"[a-zà-ù0-9]+", t.lower()):
            w = SYNONYMS.get(w, w)
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        out.append([x / n for x in v])
    return out


@pytest.fixture()
def world(monkeypatch):
    db = SessionLocal()
    if not ki.pgvector_available(db):
        db.close()
        pytest.skip("this Postgres has no pgvector")
    ki.ensure_store(db)
    monkeypatch.setattr(ki, "embed", fake_embed)
    t = secrets.token_hex(4)
    ws, other = f"kn-{t}", f"kn-other-{t}"
    db.add_all([Workspace(id=ws, name="Beamline"), Workspace(id=other, name="Other")])
    db.flush()
    db.add(Schema(uid=f"{ws}:pump", workspace_id=ws, name="Ion Pump", applies_to="objects"))
    db.flush()
    db.add(Asset(uid=f"{ws}-p1", workspace_id=ws, schema_uid=f"{ws}:pump", key=f"{ws.upper()}:SIP01",
                 name="GUNSIP01", type="Ion Pump"))

    def document(owner, code, title, body, shared=False, confidentiality="interno"):
        uid = f"{owner}-{code}"
        d = Document(uid=uid, workspace_id=owner, code=f"{code}-{t}", title=title, is_global=shared,
                     confidentiality=confidentiality)
        db.add(d)
        db.flush()
        r = DocumentRevision(uid=f"{uid}-r1", document_uid=uid, revision_number=1, state="published", body_markdown=body)
        db.add(r)
        db.flush()
        d.current_revision_uid = r.uid
        return uid

    document(ws, "PROC-1", "Ion pump replacement",
             "# Isolate\nClose the gate valves.\n\n# Replace\nReplace the ion pump and bake the sector.")
    document(other, "PROC-2", "Shared vacuum rules", "Never vent an ion pump while it is on.", shared=True)
    document(other, "PROC-3", "Private camera notes", "Camera ion pump calibration secrets.")
    document(ws, "PROC-4", "Confidential incident", "The ion pump exploded because of operator error.",
             confidentiality="riservato")
    db.add(Issue(uid=f"{ws}-t1", workspace_id=ws, title="GUNSIP01 trips", description="The ion pump trips on start.",
                 attributes={"argus_root_cause": "A failed HV cable."}))
    db.add(Issue(uid=f"{ws}-t2", workspace_id=ws, title="Restricted fault", description="Ion pump sabotage.",
                 attributes={"classification": "restricted:security"}))
    db.flush()
    db.add(IssueComment(uid=f"{ws}-c1", issue_uid=f"{ws}-t1", author="ann", body="Replaced the HV cable, fixed."))
    path = os.path.join(tempfile.mkdtemp(), "manual.txt")
    with open(path, "w") as f:
        f.write("TPG 366 manual. The interlock relay opens above the set point.")
    db.add(Attachment(uid=f"{ws}-a1", asset_uid=f"{ws}-p1", workspace_id=ws, filename="manual.txt",
                      mime_type="text/plain", storage_path=path, sha256="x1"))
    db.commit()
    db.close()
    yield {"ws": ws, "other": other, "ep": Endpoint("https://x/v1", "m", embedding_model="fake-64")}
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    for w in (ws, other):
        allow_purge(db)
        db.delete(db.get(Workspace, w))
        db.commit()
    db.close()


def run(w, ws=None):
    db = SessionLocal()
    try:
        return ki.index_workspace(db, ws or w["ws"], w["ep"])
    finally:
        db.close()


def find(w, query, **kw):
    db = SessionLocal()
    try:
        return ki.search(db, w["ws"], w["ep"], query, **kw)
    finally:
        db.close()


def test_everything_written_is_indexed_and_a_second_run_embeds_nothing(world):
    first = run(world)
    assert first["indexed"] == 6 and first["unchanged"] == 0
    # 2 documents, 2 tickets, 1 comment, 1 file: the restricted ticket and the confidential document are indexed
    # too; whether anybody sees them is decided when searching.
    db = SessionLocal()
    kinds = dict(db.execute(text("SELECT source_kind, count(DISTINCT source_uid) FROM knowledge_chunks "
                                 "WHERE workspace_id = :w GROUP BY 1"), {"w": world["ws"]}).all())
    db.close()
    assert kinds == {"document": 2, "ticket": 2, "ticket_comment": 1, "attachment": 1}
    again = run(world)
    assert again["indexed"] == 0 and again["unchanged"] == 6


def test_a_question_in_other_words_finds_the_passage(world):
    run(world)
    run(world, world["other"])
    found = find(world, "come sostituire la pompa ionica")              # Italian, none of the English words
    top = found["results"][0]
    assert top["kind"] == "document" and top["title"].endswith("Ion pump replacement") and top["where"] == "Replace"
    manual = find(world, "TPG 366 interlock relay")["results"][0]
    assert manual["kind"] == "attachment" and manual["record"]["key"] == f"{world['ws'].upper()}:SIP01"


def test_only_what_the_asker_may_read_is_returned(world):
    run(world)
    run(world, world["other"])
    titles = {r["title"] for r in find(world, "ion pump", limit=20)["results"]}
    assert any(t.endswith("Shared vacuum rules") for t in titles)           # another workspace's, shared
    assert not any(t.endswith("Private camera notes") for t in titles)      # another workspace's, not shared
    assert not any("Restricted fault" in t for t in titles)                 # a restricted class without the grant
    assert not any(t.endswith("Confidential incident") for t in titles)     # riservato, and not allowed here
    allowed = {r["title"] for r in find(world, "ion pump", limit=20, confidential_ok=True)["results"]}
    assert any(t.endswith("Confidential incident") for t in allowed)


def test_a_changed_source_is_reindexed_and_a_removed_one_dropped(world):
    run(world)
    db = SessionLocal()
    issue = db.get(Issue, f"{world['ws']}-t1")
    issue.description = "The ion pump trips when the bakeout heaters are on."
    db.delete(db.get(IssueComment, f"{world['ws']}-c1"))
    db.commit()
    db.close()
    result = run(world)
    assert result["indexed"] == 1 and result["removed"] == 1
    assert "bakeout" in find(world, "bakeout heaters")["results"][0]["excerpt"]



def test_a_reranker_orders_the_passages_found(world, monkeypatch):
    """With a re-ranker, a wider pool is gathered and the re-ranker's order decides; if it fails, the search's own
    order stands."""
    run(world)
    calls = []

    def fake_rerank(endpoint, query, documents):
        calls.append(len(documents))
        # Prefer whatever mentions the HV cable.
        return sorted([(i, 1.0 if "HV cable" in d else 0.1) for i, d in enumerate(documents)], key=lambda x: -x[1])
    monkeypatch.setattr(ki, "rerank", fake_rerank)
    ep = Endpoint("https://x/v1", "m", embedding_model="fake-64", rerank_model="bge-reranker")
    db = SessionLocal()
    try:
        found = ki.search(db, world["ws"], ep, "ion pump", limit=2)
    finally:
        db.close()
    assert found["reranked"] and calls and calls[0] > 2                  # a wider pool than the 2 asked for
    assert "HV cable" in found["results"][0]["excerpt"] and "rerank_score" in found["results"][0]
    assert len(found["results"]) == 2

    def broken(endpoint, query, documents):
        raise ki.LLMError("down")
    monkeypatch.setattr(ki, "rerank", broken)
    db = SessionLocal()
    try:
        plain = ki.search(db, world["ws"], ep, "ion pump", limit=2)
    finally:
        db.close()
    assert not plain["reranked"] and len(plain["results"]) == 2


def test_the_semantic_graph_links_what_is_about_the_same_thing_and_only_what_may_be_read(world):
    run(world)
    db = SessionLocal()
    try:
        ws = world["ws"]
        found = ki.related(db, ws, "document", f"{ws}-PROC-1", min_score=0.2)  # the fake model scores low
        got = {(r["kind"], r["uid"]): r for r in found["related"]}
        assert ("ticket", f"{ws}-t1") in got, "the ion pump that trips is about an ion pump replacement"
        assert ("ticket", f"{ws}-t2") not in got, "a restricted ticket is not shown"
        assert ("document", f"{world['other']}-PROC-3") not in got, "nor another workspace's private document"
        assert ("document", f"{ws}-PROC-4") not in got, "nor a confidential one"
        assert ("document", f"{ws}-PROC-1") not in got, "nor the record itself"
        first = found["related"][0]
        assert 0 < first["score"] <= 1 and first["excerpt"] and first["matched"]
        assert [r["score"] for r in found["related"]] == sorted((r["score"] for r in found["related"]), reverse=True)
    finally:
        db.close()


def test_the_semantic_graph_through_the_api(world):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_ledger_transition import token
    run(world)
    db = SessionLocal()
    headers = token(db, world["ws"])
    db.commit()
    db.close()
    client = TestClient(app)
    r = client.get("/v1/graph/semantic", headers=headers, params={"kind": "ticket", "uid": f"{world['ws']}-t1",
                                                                  "min_score": 0.2})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["nodes"][0]["uid"] == f"{world['ws']}-t1" and g["nodes"][0]["depth"] == 0
    assert g["edges"] and all(e["relation"] == "similar" and e["from_uid"] == f"{world['ws']}-t1" for e in g["edges"])
    assert client.get("/v1/graph/semantic", headers=headers, params={"kind": "ticket", "uid": "nope"}).status_code == 404


def test_a_documents_summary_is_indexed_before_its_body():
    """The summary kept apart from the body (attributes.argus_summary) is found by search, as its own passage."""
    db = SessionLocal()
    ws = f"kn-sum-{secrets.token_hex(4)}"
    db.add(Workspace(id=ws, name="Summary"))
    db.flush()
    d = Document(uid=f"{ws}-d", workspace_id=ws, code=f"NOTE-{ws}", title="Baggage report")
    db.add(d)
    db.flush()
    r = DocumentRevision(uid=f"{ws}-d-r1", document_uid=d.uid, revision_number=1, state="published",
                         body_markdown="# Report\nThe bag arrived damaged.",
                         attributes={"argus_summary": "A damaged bag reported at arrival."})
    db.add(r)
    db.flush()
    d.current_revision_uid = r.uid
    db.flush()
    try:
        [source] = [s for s in ki.sources(db, ws) if s.kind == "document"]
        assert source.parts[0] == ("Summary", "A damaged bag reported at arrival.")
        assert any("arrived damaged" in text for _, text in source.parts[1:])
    finally:
        db.rollback()
        db.close()
