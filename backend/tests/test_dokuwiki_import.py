"""DokuWiki as an import source: a page by its link, or with the pages under it; only from the wikis allowed, over
https, redirects included. Each page one published document, found again on the next run: unchanged pages are
skipped, a changed one gets a new revision; links between imported pages lead to their documents, a page under
another is its child, its pictures are attached and shown in place, its wiki link kept."""
import secrets
import uuid

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.membership import Membership
from app.models.user import User
from app.models.workspace import Workspace
from app.models.document import DocumentRelation
from app.models.import_job import ImportJob
from app.services import wiki_import as wk
from app.packages.install import install
from app.services.dokuwiki_import import run_dokuwiki_import

client = TestClient(app)
ORIGIN = "https://wiki.infn.it"
NS = "strutture:lnf:da:btf:dispositivi:rivelatori:calorimeter"
PAGE = (b'<html><head><meta name="generator" content="DokuWiki"/><script>var DOKU_BASE=\'/\';'
        b'var JSINFO = {"id":"' + NS.encode() + b'","namespace":"strutture:lnf"};</script></head><body>x</body></html>')
INDEX = f"""<ul class="idx">
<li><a href="/doku.php?id=x&amp;idx=strutture:lnf" class="idx_dir"><strong>lnf</strong></a></li>
<li><a href="{ORIGIN}/strutture/lnf/da/home" class="wikilink1" data-wiki-id="strutture:lnf:da:home">Home</a></li>
<li><a href="{ORIGIN}/x" class="wikilink1" data-wiki-id="{NS}">Calorimeter in BTF</a></li>
<li><a href="{ORIGIN}/x/bgo" class="wikilink1" data-wiki-id="{NS}:bgo">BGO</a></li>
<li><a href="/doku.php?id=x&amp;idx={NS}:old" class="idx_dir"><strong>old</strong></a></li>
</ul>"""
INDEX_OLD = f'<a href="{ORIGIN}/x/old/v1" class="wikilink1" data-wiki-id="{NS}:old:v1">Version 1</a>'
BODIES = {
    NS: f'<h3>Calorimeter in BTF</h3><p>CALOBTF1 - Cherenkov<br/>CAL1 - <a href="{ORIGIN}/x/bgo" class="wikilink1" '
        f'data-wiki-id="{NS}:bgo">BGO</a><br/>CAL3 - <a href="{ORIGIN}/x/nope" class="wikilink2" '
        f'data-wiki-id="{NS}:nope">missing</a></p>',
    f"{NS}:bgo": f'<h1>BGO</h1><p><a href="{ORIGIN}/_detail/x/bgo.jpg?id=a" class="media"><img '
                 f'src="{ORIGIN}/_media/strutture/lnf/bgo.jpg?w=400&amp;tok=1" alt="The BGO"/></a></p>'
                 f'<p>See the <a href="https://www.caen.it/v965" class="urlextern">V965</a>.</p>',
    f"{NS}:old:v1": "<h1>Version 1</h1><p>Old.</p>",
}
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 50


class Fake:
    def __init__(self, status=200, content=b"", url="", location=None):
        self.status_code, self._content, self.url = status, content, url
        self.headers = {"location": location} if location else {}

    def iter_content(self, n):
        yield self._content

    def close(self):
        pass

    @property
    def text(self):
        return self._content.decode()

    @property
    def content(self):
        return self._content


@pytest.fixture()
def wiki(monkeypatch):
    asked = []

    def fake_get(url, **kw):
        asked.append(url)
        if "do=export_xhtmlbody" in url:
            pid = url.split("id=", 1)[1].split("&", 1)[0]
            return Fake(200, BODIES[pid].encode(), url)
        if "do=index" in url:
            return Fake(200, (INDEX_OLD if f"idx={NS}:old" in url else INDEX).encode(), url)
        if "/_media/" in url:
            assert "w=400" not in url                          # the picture at its full size
            return Fake(200, JPEG, url)
        if url.startswith(f"{ORIGIN}/redirect"):
            return Fake(302, b"", url, location="http://keycloak:8080/admin")
        return Fake(200, PAGE, url)
    monkeypatch.setattr(requests, "get", fake_get)
    return asked


def test_only_allowed_wikis_over_https_and_never_a_redirect_elsewhere(wiki, monkeypatch):
    for url in ("http://wiki.infn.it/x", "https://evil.example/x", "https://169.254.169.254/latest"):
        with pytest.raises(wk.WikiError):
            wk.open_wiki(url)
    with pytest.raises(wk.WikiError, match="https|not a wiki ARGUS may import from"):
        wk.open_wiki(f"{ORIGIN}/redirect")
    assert not any("keycloak" in u for u in wiki)
    monkeypatch.setenv("ARGUS_WIKI_HOSTS", "wiki.example.org")
    with pytest.raises(wk.WikiError):
        wk.open_wiki(f"{ORIGIN}/x")


def test_a_namespace_lists_its_pages_and_those_below_its_own_page_first(wiki):
    w = wk.open_wiki(f"{ORIGIN}/strutture/lnf/da/btf/dispositivi/rivelatori/calorimeter")
    assert (w.page_id, w.base) == (NS, "/")
    pages, truncated = wk.namespace_pages(w, NS)
    assert [p for p, _ in pages] == [NS, f"{NS}:bgo", f"{NS}:old:v1"] and not truncated
    assert "strutture:lnf:da:home" not in dict(pages)            # the index's other branches are not its pages


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    ws = f"wiki-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name="BTF"))
    db.flush()
    install(db, ws, ["core-facility"])                  # as the web makes one
    writer = User(id=str(uuid.uuid4()), email=f"writer-{t}@argus.test", name="writer", is_admin=False)
    db.add(writer)
    db.flush()
    db.add(Membership(workspace_id=ws, user_id=writer.id, can_read=True, can_create=True, can_modify=True,
                      can_read_documents=True, can_create_documents=True, can_modify_documents=True))
    db.commit()
    db.refresh(writer)
    db.expunge(writer)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=writer)
    yield {"ws": ws, "h": {"X-Workspace-Id": ws}, "writer": writer}
    app.dependency_overrides.pop(get_identity, None)
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.delete(db.get(User, writer.id))
    db.commit()
    db.close()


URL = f"{ORIGIN}/strutture/lnf/da/btf/dispositivi/rivelatori/calorimeter"


def run(world, **kw):
    uid = str(uuid.uuid4())
    db = SessionLocal()
    db.add(ImportJob(uid=uid, workspace_id=world["ws"], source="dokuwiki"))
    db.commit()
    db.close()
    run_dokuwiki_import(uid, world["ws"], URL, **kw)
    db = SessionLocal()
    job = db.get(ImportJob, uid)
    db.expunge(job)
    db.close()
    return job


def docs(world):
    db = SessionLocal()
    try:
        out = {}
        for d in db.scalars(select(Document).where(Document.workspace_id == world["ws"])):
            rev = db.get(DocumentRevision, d.current_revision_uid)
            out[rev.attributes["argus_source_id"]] = (d, rev)
            db.expunge(d)
            db.expunge(rev)
        return out
    finally:
        db.close()


def test_a_wiki_folder_becomes_published_documents_linked_together_and_a_rerun_changes_only_what_changed(wiki, world):
    job = run(world)
    assert job.status == "succeeded", job.error
    assert job.counts["documents"] == 3 and job.counts["page_tree_links"] == 2
    made = docs(world)
    assert set(made) == {NS, f"{NS}:bgo", f"{NS}:old:v1"}
    main, main_rev = made[NS]
    bgo, bgo_rev = made[f"{NS}:bgo"]
    assert main.source == "dokuwiki" and main.code.startswith("WIKI-CALORIMETER-") and main_rev.state == "published"
    assert main.title == "Calorimeter in BTF" and bgo.title == "BGO"
    assert "CALOBTF1 - Cherenkov  \nCAL1 - " in main_rev.body_markdown
    assert f"[BGO](/documents/{bgo.uid})" in main_rev.body_markdown and "nope" not in main_rev.body_markdown
    assert main_rev.attributes["argus_source_url"] == f"{ORIGIN}/doku.php?id={NS}"
    db = SessionLocal()
    try:
        [pic] = [a for a in db.scalars(select(Attachment).where(Attachment.document_revision_uid == bgo_rev.uid))
                 if a.mime_type == "image/jpeg"]
        assert f"![The BGO](/v1/attachments/{pic.uid})" in bgo_rev.body_markdown
        assert "[V965](https://www.caen.it/v965)" in bgo_rev.body_markdown and "_detail" not in bgo_rev.body_markdown
        parents = {r.from_document_uid: r.to_uid for r in db.scalars(select(DocumentRelation).where(
            DocumentRelation.relation_type == "child_of", DocumentRelation.workspace_id == world["ws"]))}
        assert parents[bgo.uid] == main.uid and parents[made[f"{NS}:old:v1"][0].uid] == main.uid
    finally:
        db.close()

    again = run(world)                                   # nothing changed on the wiki: nothing new here
    assert (again.counts["documents"], again.counts["documents_updated"], again.counts["documents_unchanged"]) == (0, 0, 3)
    assert docs(world)[NS][1].uid == main_rev.uid

    BODIES[f"{NS}:bgo"] = BODIES[f"{NS}:bgo"].replace("See the", "Read the")
    try:
        third = run(world)
    finally:
        BODIES[f"{NS}:bgo"] = BODIES[f"{NS}:bgo"].replace("Read the", "See the")
    assert (third.counts["documents"], third.counts["documents_updated"]) == (0, 1)
    new_bgo, new_rev = docs(world)[f"{NS}:bgo"]
    assert new_bgo.uid == bgo.uid and new_rev.revision_number == 2 and "Read the" in new_rev.body_markdown
    db = SessionLocal()
    assert db.get(DocumentRevision, bgo_rev.uid).state == "superseded"
    db.close()


def test_one_page_alone_and_a_wiki_not_allowed_fails_the_job_with_its_reason(wiki, world):
    job = run(world, include_children=False)
    assert job.status == "succeeded" and set(docs(world)) == {NS}
    bad = str(uuid.uuid4())
    db = SessionLocal()
    db.add(ImportJob(uid=bad, workspace_id=world["ws"], source="dokuwiki"))
    db.commit()
    db.close()
    run_dokuwiki_import(bad, world["ws"], "https://evil.example/x")
    db = SessionLocal()
    failed = db.get(ImportJob, bad)
    assert failed.status == "failed" and "not a wiki ARGUS may import from" in failed.error
    db.close()


def test_a_saved_dokuwiki_import_needs_no_credential_and_runs(wiki, world):
    r = client.post("/v1/import-configs", headers=world["h"], json={
        "name": "BTF calorimeters", "config": {"source": "dokuwiki", "page_url": URL, "include_children": True}})
    assert r.status_code == 201, r.text
    ran = client.post(f"/v1/import-configs/{r.json()['uid']}/run", headers=world["h"])
    assert ran.status_code == 202, ran.text
    job = client.get(f"/v1/imports/{ran.json()['last_import_job_uid']}", headers=world["h"]).json()
    assert job["source"] == "dokuwiki" and job["status"] == "succeeded", job
