"""The documents board (docs/documents.md): the list says where each document stands in its review — its newest
revision's state, beside the published one."""
import uuid

from tests.test_document_control import client, published, ws  # noqa: F401  (ws is a fixture)


def listed(headers, uid):
    return next(d for d in client.get("/v1/documents", headers=headers).json() if d["uid"] == uid)


def test_the_list_gives_each_document_its_newest_revision(ws):
    _ws, headers = ws
    draft = client.post("/v1/documents", headers=headers, json={"uid": str(uuid.uuid4()), "title": "Draft"}).json()
    row = listed(headers, draft["uid"])
    assert row["latest_revision"]["state"] == "draft" and row["latest_revision"]["revision_number"] == 1
    assert row["current_revision_uid"] is None

    rev = row["latest_revision"]["uid"]
    assert client.post(f"/v1/documents/{draft['uid']}/revisions/{rev}/submit", headers=headers).status_code == 200
    assert listed(headers, draft["uid"])["latest_revision"]["state"] == "in_review"

    # Published, then a second revision started: the board shows the new draft; the published one stays current.
    uid = published(headers)
    first = listed(headers, uid)
    assert first["latest_revision"]["state"] == "published" and first["latest_revision"]["published_at"]
    second = client.post(f"/v1/documents/{uid}/revisions", headers=headers, json={"body_markdown": "v2"})
    assert second.status_code == 201, second.text
    row = listed(headers, uid)
    assert row["latest_revision"]["state"] == "draft" and row["latest_revision"]["revision_number"] == 2
    assert row["current_revision_uid"] == first["current_revision_uid"]
    # The single document is unchanged: the list alone fills it.
    assert client.get(f"/v1/documents/{uid}", headers=headers).json()["latest_revision"] is None
