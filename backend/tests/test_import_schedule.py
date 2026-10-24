"""Saved imports that run by themselves: when (every few hours, daily or weekly at a local time that stays put
across daylight saving), as whom (the person who set the schedule, with their permissions at the time), never two
runs of one import at once, and failures told to that person — three in a row switch the schedule off."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models.import_config import ImportConfig
from app.models.import_job import ImportJob
from app.models.membership import Membership
from app.models.workflow import Notification
from app.schemas.import_config import ScheduleIn
from app.services import import_schedule as sch
from tests.test_dokuwiki_import import URL, wiki, world  # noqa: F401 — fixtures shared with the source's tests

client = TestClient(app)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def cfg(**kw):
    return ImportConfig(uid="x", workspace_id="w", name="n", source="dokuwiki", params={}, **kw)


def test_when_the_next_run_is():
    every6 = cfg(schedule_kind="hours", schedule_every_hours=6)
    assert sch.next_run(every6, utc(2026, 10, 24, 10)) == utc(2026, 10, 24, 16)
    nightly = cfg(schedule_kind="daily", schedule_time="02:00", schedule_timezone="Europe/Rome")
    assert sch.next_run(nightly, utc(2026, 10, 23, 12)) == utc(2026, 10, 24, 0)      # 02:00 summer time
    assert sch.next_run(nightly, utc(2026, 10, 25, 12)) == utc(2026, 10, 26, 1)      # 02:00 winter time
    mondays = cfg(schedule_kind="weekly", schedule_weekday=0, schedule_time="07:30", schedule_timezone="UTC")
    assert sch.next_run(mondays, utc(2026, 10, 21, 9)) == utc(2026, 10, 26, 7, 30)   # from a Wednesday
    assert sch.next_run(mondays, utc(2026, 10, 26, 7, 30)) == utc(2026, 11, 2, 7, 30)
    assert sch.next_run(cfg(schedule_kind="off"), utc(2026, 1, 1)) is None


def test_a_schedule_says_all_it_needs_and_belongs_to_a_person():
    c = cfg()
    for bad in (ScheduleIn(kind="hours"), ScheduleIn(kind="daily"), ScheduleIn(kind="weekly", time="02:00"),
                ScheduleIn(kind="daily", time="02:00", timezone="Mars/Olympus")):
        with pytest.raises(sch.ScheduleError):
            sch.apply(c, bad, "someone")
    with pytest.raises(sch.ScheduleError, match="runs as a person"):
        sch.apply(c, ScheduleIn(kind="hours", every_hours=6), None)
    sch.apply(c, ScheduleIn(kind="daily", time="03:15", timezone="Europe/Rome"), "u1", utc(2026, 10, 24, 12))
    assert (c.scheduled_by, c.next_run_at) == ("u1", utc(2026, 10, 25, 2, 15))       # 03:15 winter time


def _saved(world, **schedule):
    r = client.post("/v1/import-configs", headers=world["h"], json={
        "name": "BTF calorimeters", "config": {"source": "dokuwiki", "page_url": URL},
        **({"schedule": schedule} if schedule else {})})
    assert r.status_code == 201, r.text
    return r.json()


def _due_now(uid):
    db = SessionLocal()
    db.get(ImportConfig, uid).next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    db.close()


def _config(uid):
    db = SessionLocal()
    c = db.get(ImportConfig, uid)
    db.expunge(c)
    db.close()
    return c


def test_a_scheduled_import_runs_by_itself_as_the_person_who_set_it(wiki, world):
    saved = _saved(world, kind="daily", time="02:00", timezone="Europe/Rome")
    assert saved["schedule_kind"] == "daily" and saved["next_run_at"]
    assert _config(saved["uid"]).scheduled_by == world["writer"].id
    assert sch.tick(SessionLocal) == []                     # not due yet
    _due_now(saved["uid"])
    [result] = sch.tick(SessionLocal)
    assert result["outcome"] == "succeeded", result
    c = _config(saved["uid"])
    assert c.last_outcome == "succeeded" and c.running_since is None
    assert c.next_run_at > datetime.now(timezone.utc)
    db = SessionLocal()
    job = db.get(ImportJob, c.last_import_job_uid)
    assert job.status == "succeeded" and job.counts["documents"] == 3
    db.close()
    assert sch.tick(SessionLocal) == []                     # once per time it comes round
    off = client.put(f"/v1/import-configs/{saved['uid']}", headers=world["h"], json={"schedule": {"kind": "off"}})
    assert off.json()["schedule_kind"] == "off" and off.json()["next_run_at"] is None


def test_never_two_runs_of_one_import_at_once(wiki, world):
    saved = _saved(world, kind="hours", every_hours=6)
    db = SessionLocal()
    running = ImportJob(uid=str(uuid.uuid4()), workspace_id=world["ws"], source="dokuwiki", status="running",
                        started_at=datetime.now(timezone.utc))
    db.add(running)
    db.get(ImportConfig, saved["uid"]).last_import_job_uid = running.uid
    db.commit()
    db.close()
    _due_now(saved["uid"])
    [result] = sch.tick(SessionLocal)
    assert result["outcome"] == "skipped"
    c = _config(saved["uid"])
    assert c.last_message == "the previous run was still going" and c.next_run_at > datetime.now(timezone.utc)
    assert client.post(f"/v1/import-configs/{saved['uid']}/run", headers=world["h"]).status_code == 409
    _due_now(saved["uid"])
    db = SessionLocal()
    assert sch.claim(db, saved["uid"]) and not sch.claim(db, saved["uid"])            # one server takes it
    db.close()


def test_failures_are_told_and_three_in_a_row_switch_the_schedule_off(wiki, world):
    saved = _saved(world, kind="hours", every_hours=1)
    db = SessionLocal()
    db.get(ImportConfig, saved["uid"]).params = {"page_url": "https://evil.example/x", "include_children": True}
    db.commit()
    db.close()
    for n in range(1, 4):
        _due_now(saved["uid"])
        [result] = sch.tick(SessionLocal)
        assert result["outcome"] == "failed" and "not a wiki ARGUS may import from" in result["message"]
        assert _config(saved["uid"]).schedule_failures == n
    c = _config(saved["uid"])
    assert c.schedule_kind == "off" and "switched off after 3 failures" in c.last_message
    db = SessionLocal()
    told = list(db.scalars(select(Notification).where(Notification.recipient == world["writer"].id,
                                                      Notification.kind == "import_failed")))
    assert len(told) == 3 and "its schedule is off" in told[-1].title
    assert told[0].detail["path"].endswith(f"/imports/{told[0].detail['path'].rsplit('/', 1)[-1]}")
    db.close()


def test_someone_no_longer_allowed_to_import_does_not_import_by_a_schedule(wiki, world):
    saved = _saved(world, kind="hours", every_hours=6)
    db = SessionLocal()
    for m in db.scalars(select(Membership).where(Membership.workspace_id == world["ws"])):
        db.delete(m)
    db.commit()
    db.close()
    _due_now(saved["uid"])
    [result] = sch.tick(SessionLocal)
    assert result["outcome"] == "failed" and "may no longer import here" in result["message"]
