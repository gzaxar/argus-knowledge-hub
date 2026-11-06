"""A new release of a beamline's configuration: what changes, and only that.

A key is what people read, so it does not look like a PV name. A record's uid does not depend on
how its key is written, so nothing that links to it breaks. A re-read writes only what differs. And
what a file no longer declares goes only when asked, and comes back when the file states it again.
"""
import secrets

import pytest
import yaml

from app.db import Base, SessionLocal, engine
from app.models.asset import Asset
from app.models.import_job import ImportJob
from app.models.workspace import Workspace
from app.services.element_inference import infer_ioc
from app.services.epik8s_import import _file_of, _Importer, _uid, public_key
from tests.test_epik8s_inference import db, split  # noqa: F401

CONFIG = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    - name: libera-a
      iocprefix: ACC:DIA:LIB02
      devices:
        - {name: BPSA31, address: 192.168.0.28, port: 502}
        - {name: BPSA32, address: 192.168.0.28, port: 503}
    - name: gone-next-release
      iocprefix: ACC:OLD
      devices:
        - {name: OLD01}
"""


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def tag():
    return f"T{secrets.token_hex(3).upper()}"


@pytest.fixture()
def ws():
    workspace = f"chg-{secrets.token_hex(4)}"
    db = SessionLocal()
    db.add(Workspace(id=workspace, name="Changes"))
    db.commit()
    db.close()
    return workspace


def values(tag, edit=None):
    loaded = yaml.safe_load(CONFIG.replace("BEAMLINE", tag))
    if edit:
        edit(loaded["epicsConfiguration"]["iocs"])
    return loaded


def run(ws, tag, revision="r1", edit=None, clear=False, path="deploy/values.yaml"):
    db = SessionLocal()
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, f"git@host:group/repo.git@{revision}:{path}")
    importer.ensure_types()
    importer.run(values(tag, edit), True)
    if clear:
        importer.clear_previous()
    db.commit()
    return db, importer


def record(db, ws, tag, *parts):
    return db.get(Asset, _uid(ws, ":".join([tag, *parts])))


def drop_ioc(iocs):
    iocs[:] = [i for i in iocs if i["name"] != "gone-next-release"]


def test_a_key_reads_with_hyphens_and_no_key_looks_like_a_pv(ws, tag):
    db, importer = run(ws, tag)
    device = record(db, ws, tag, "DEV", "libera-a", "BPSA31")
    assert device.key == f"{tag}-DEV-libera-a-BPSA31"
    assert record(db, ws, tag, "IOC", "libera-a").key == f"{tag}-IOC-libera-a"
    assert not [a.key for a in importer.assets.values() if ":" in a.key]
    db.close()


def test_a_record_made_under_the_old_key_keeps_its_uid_and_what_a_person_wrote(ws, tag):
    db, _ = run(ws, tag)
    device = record(db, ws, tag, "DEV", "libera-a", "BPSA31")
    uid = device.uid
    # As the previous version left it.
    device.key = f"{tag}:DEV:libera-a:BPSA31"
    device.attributes = {**device.attributes, "serial": "written by a person"}
    db.commit()
    db.close()

    db, importer = run(ws, tag, "r2")
    device = db.get(Asset, uid)
    assert device.key == f"{tag}-DEV-libera-a-BPSA31"
    assert device.attributes["serial"] == "written by a person"
    assert importer.counts["records_updated"] == 1
    db.close()


def test_a_new_revision_changes_only_what_it_changed(ws, tag):
    db, first = run(ws, tag, "r1")
    made = first.counts["records_created"]
    db.close()

    def move(iocs):
        iocs[0]["devices"][0]["port"] = 999

    db, second = run(ws, tag, "r2", edit=move)
    changed = record(db, ws, tag, "DEV", "libera-a", "BPSA31")
    untouched = record(db, ws, tag, "DEV", "libera-a", "BPSA32")
    assert str(changed.attributes["port"]) == "999"
    assert "@r2:" in changed.attributes["argus_source_ref"]
    # Still names the revision that last changed it.
    assert "@r1:" in untouched.attributes["argus_source_ref"]
    assert second.counts.get("records_created", 0) == 0
    assert second.counts["records_updated"] >= 1 and second.counts["records_unchanged"] >= made - 3
    db.close()


def test_running_the_same_revision_again_writes_nothing(ws, tag):
    run(ws, tag, "r1")[0].close()
    db, again = run(ws, tag, "r1")
    assert again.counts.get("records_updated", 0) == 0 and again.counts.get("records_created", 0) == 0
    db.close()


def test_what_a_file_stops_declaring_stays_unless_clearing_was_asked_for(ws, tag):
    run(ws, tag, "r1")[0].close()
    db, _ = run(ws, tag, "r2", edit=drop_ioc)
    assert record(db, ws, tag, "DEV", "gone-next-release", "OLD01").deleted_at is None
    db.close()

    db, importer = run(ws, tag, "r3", edit=drop_ioc, clear=True)
    assert record(db, ws, tag, "DEV", "gone-next-release", "OLD01").deleted_at is not None
    assert record(db, ws, tag, "IOC", "gone-next-release").deleted_at is not None
    assert record(db, ws, tag, "DEV", "libera-a", "BPSA31").deleted_at is None
    assert importer.counts["records_retired"] == 2
    assert any("gone-next-release" in w for w in importer.job.warnings)
    db.close()


ADDRESSED = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    - name: libera-a
      host: 192.168.0.28
      devices:
        - {name: BPSA31}
"""


def test_an_address_found_again_on_a_re_read_is_still_declared(ws, tag):
    """The second run finds the Access Point it made through the network index, without writing it."""
    def importer(revision):
        db = SessionLocal()
        job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
        db.add(job)
        db.commit()
        it = _Importer(db, job, ws, f"git@host:group/repo.git@{revision}:deploy/values.yaml")
        it.ensure_types()
        it.run(yaml.safe_load(ADDRESSED.replace("BEAMLINE", tag)), True)
        return db, it

    db, first = importer("r1")
    db.commit()
    made = [a for a in first.assets.values() if a.type == "Access Point"]
    assert made, "the configuration should make an Access Point, or this test proves nothing"
    uid = made[0].uid
    db.close()

    db, second = importer("r2")
    assert uid not in {a.uid for a in second.assets.values()}, "reached without an upsert: the case under test"
    second.clear_previous()
    db.commit()
    assert db.get(Asset, uid).deleted_at is None
    assert second.counts["records_retired"] == 0
    db.close()


LIBERA = """
beamline: BEAMLINE
iocDefaults:
  libera-sppp: {devgroup: bpm, devtype: libera-spp}
epicsConfiguration:
  iocs:
    - name: libera10
      template: libera-sppp
      iocprefix: ACC:DIA:LIB10:BPSA32
      host: libera10.lnf.infn.it
"""


def test_a_host_a_re_read_cannot_resolve_keeps_its_access_point_and_the_bpm_is_one(db, split, tag):
    """The IOC itself carries the address after the first run, so a second finds it ambiguous and
    reaches no Access Point at all. The file still uses that address, so the record is not stale."""
    _, ws = split

    def importer(revision, text=LIBERA):
        job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
        db.add(job)
        db.commit()
        it = _Importer(db, job, ws, f"git@host:group/repo.git@{revision}:deploy/values.yaml", infer_elements=True)
        it.ensure_types()
        it.run(yaml.safe_load(text.replace("BEAMLINE", tag)), True)
        return it

    importer("r1")
    importer("r2").clear_previous()
    db.commit()
    live = db.query(Asset).filter(Asset.workspace_id == ws, Asset.deleted_at.is_(None))
    assert live.filter(Asset.key.like("%-LIBERA10"), Asset.type == "Access Point").count() == 1
    assert [a.key for a in live.filter(Asset.type == "Beam Position Monitor")] == [f"{tag}-ELM-BPSA32"]

    # And the host goes when the file stops using it.
    other = LIBERA.replace("libera10.lnf.infn.it", "libera11.lnf.infn.it")
    importer("r3", other).clear_previous()
    db.commit()
    assert live.filter(Asset.key.like("%-LIBERA10"), Asset.type == "Access Point").count() == 0


def test_a_cleared_record_comes_back_with_its_uid_when_the_file_states_it_again(ws, tag):
    db, _ = run(ws, tag, "r1")
    uid = record(db, ws, tag, "DEV", "gone-next-release", "OLD01").uid
    db.close()
    run(ws, tag, "r2", edit=drop_ioc, clear=True)[0].close()
    db, importer = run(ws, tag, "r3")
    assert db.get(Asset, uid).deleted_at is None
    assert importer.counts["records_restored"] >= 2
    db.close()


def test_clearing_leaves_other_files_people_and_other_sources_alone(ws, tag):
    db, importer = run(ws, tag, "r1", path="deploy/values-accumulator.yaml")
    schema_uid = next(iter(importer.assets.values())).schema_uid
    db.add(Asset(uid=f"{ws}-hand", workspace_id=ws, schema_uid=schema_uid, key=f"{tag}-HAND", name="by hand",
                 type="IOC", attributes={"argus_source_ref": "git@host:group/repo.git@r0:deploy/values.yaml"}))
    db.add(Asset(uid=f"{ws}-jira", workspace_id=ws, schema_uid=schema_uid, key=f"{tag}-JIRA", name="other source",
                 type="IOC", attributes={"argus_source": "jira",
                                         "argus_source_ref": "git@host:group/repo.git@r0:deploy/values.yaml"}))
    db.commit()
    db.close()

    db, _ = run(ws, tag, "r2", edit=drop_ioc, clear=True, path="deploy/values.yaml")
    assert record(db, ws, tag, "DEV", "gone-next-release", "OLD01").deleted_at is None
    assert db.get(Asset, f"{ws}-hand").deleted_at is None
    assert db.get(Asset, f"{ws}-jira").deleted_at is None
    db.close()


def test_the_old_spelling_of_the_source_counts_as_this_import(ws, tag):
    db, importer = run(ws, tag, "r1")
    device = record(db, ws, tag, "DEV", "gone-next-release", "OLD01")
    device.attributes = {**device.attributes, "argus_source": "EPIK8s"}
    db.commit()
    db.close()
    db, _ = run(ws, tag, "r2", edit=drop_ioc, clear=True)
    assert record(db, ws, tag, "DEV", "gone-next-release", "OLD01").deleted_at is not None
    db.close()


def test_a_file_with_no_ioc_clears_nothing(ws, tag):
    run(ws, tag, "r1")[0].close()

    def empty(iocs):
        iocs.clear()

    db, importer = run(ws, tag, "r2", edit=empty, clear=True)
    assert record(db, ws, tag, "DEV", "libera-a", "BPSA31").deleted_at is None
    assert importer.counts.get("records_retired", 0) == 0
    assert any("declares no IOC" in w for w in importer.job.warnings)
    db.close()


def test_what_this_run_was_not_asked_to_infer_is_not_cleared(ws, tag):
    db, importer = run(ws, tag, "r1")
    schema_uid = next(iter(importer.assets.values())).schema_uid
    db.add(Asset(uid=f"{ws}-inf", workspace_id=ws, schema_uid=schema_uid, key=f"{tag}-ELM-X", name="X", type="IOC",
                 attributes={"argus_source": "epik8s", "argus_keywords": ["inferred"],
                             "argus_source_ref": "git@host:group/repo.git@r1:deploy/values.yaml"}))
    db.commit()
    db.close()
    db, _ = run(ws, tag, "r2", edit=drop_ioc, clear=True)
    assert db.get(Asset, f"{ws}-inf").deleted_at is None
    db.close()


def test_a_ledger_only_workspace_is_told_why_nothing_was_cleared(ws, tag):
    db, _ = run(ws, tag, "r1")
    db.get(Workspace, ws).ledger_only = True
    db.commit()
    db.close()
    db, importer = run(ws, tag, "r2", edit=drop_ioc, clear=True)
    assert importer.counts.get("records_retired", 0) == 0
    assert record(db, ws, tag, "DEV", "gone-next-release", "OLD01").deleted_at is None
    assert any("ledger-only" in w for w in importer.job.warnings)
    db.close()


def test_two_things_that_would_share_a_key_are_refused_by_name(ws, tag):
    def clash(iocs):
        iocs[:] = [{"name": "a-b", "devices": [{"name": "c"}]}, {"name": "a", "devices": [{"name": "b-c"}]}]

    with pytest.raises(ValueError, match=f"{tag}-DEV-a-b-c"):
        run(ws, tag, edit=clash)


@pytest.mark.parametrize("prefix, ioc, element", [
    ("ACC:DIA:LIB02:BPSA31", "libera02", "BPSA31"),
    ("ACC:LIBERA02:BPSA31", "libera02", "BPSA31"),
    ("BPSA31", "libera02", "BPSA31"),
    ("", "libera02", "LIBERA02"),
])
def test_a_bpm_is_named_for_itself_and_not_for_its_pv_prefix(prefix, ioc, element):
    found = infer_ioc({"name": ioc, "template": "libera-sppp", "iocprefix": prefix})
    assert found.element_name == element


@pytest.mark.parametrize("ref, expected", [
    ("https://host/g/repo.git@abc:deploy/values.yaml", ("https://host/g/repo.git", "deploy/values.yaml")),
    ("git@host:g/repo.git@abc:deploy/values.yaml", ("git@host:g/repo.git", "deploy/values.yaml")),
    ("", ("", "")),
])
def test_which_file_a_record_came_from_does_not_depend_on_the_revision(ref, expected):
    assert _file_of(ref) == expected


def test_a_key_is_its_identity_with_hyphens():
    assert public_key("BTF:DEV:libera12:BPSA11") == "BTF-DEV-libera12-BPSA11"
