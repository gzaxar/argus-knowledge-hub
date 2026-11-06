"""One supply, several magnets: `magnets:` on a channel, and the magnet of its own name when there is no list.

The beam model's elements are the magnets: linked to, never made a second time. What the file names and the
workspace does not hold is reported, not invented.
"""
import secrets
import uuid

import pytest
import yaml

from app.models.asset import Asset, Relation
from app.models.import_job import ImportJob
from app.services.asset_types import resolve_type_uids
from app.services.epik8s_import import _Importer, _uid
from tests.test_epik8s_inference import db, split  # noqa: F401

CONFIG = """
beamline: {tag}
epicsConfiguration:
  iocs:
    - name: danfysik
      iocprefix: ACC:MAG:DANFYSIK
      devgroup: mag
      devtype: sys80it
      devices:
        - {{name: QUAA-001, ps: {{current: {{max: 315}}}}, magnets: [QUAA101, QUAA201]}}
        - {{name: CHHA1002}}
        - {{name: NOMAGNET}}
"""


@pytest.fixture()
def tag():
    return f"T{secrets.token_hex(3).upper()}"


def element(db, ws, name, type_name="Quadrupole", attributes=None):
    asset = Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=resolve_type_uids(db, ws)[type_name],
                  key=f"{ws}:model/{name}", name=name, type=type_name, attributes=attributes or {})
    db.add(asset)
    db.commit()
    return asset


def run(db, ws, tag, infer=False, edit=None, clear=False, text=CONFIG):
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    it = _Importer(db, job, ws, "git@host:group/repo.git@r1:deploy/values.yaml", infer_elements=infer)
    it.ensure_types()
    values = yaml.safe_load(text.format(tag=tag))
    if edit:
        edit(values["epicsConfiguration"]["iocs"][0]["devices"])
    it.run(values, True)
    if clear:
        it.clear_previous()
    db.commit()
    return it, job


def powered_by(db, supply):
    return {name for (name,) in db.query(Asset.name).join(Relation, Relation.to_asset_uid == Asset.uid).filter(
        Relation.from_asset_uid == supply.uid, Relation.relation_type == "powers")}


def relates(db, source, target, kind):
    return db.query(Relation).filter_by(from_asset_uid=source.uid, to_asset_uid=target.uid,
                                        relation_type=kind).count() == 1


def test_a_channel_powers_every_magnet_it_lists_with_or_without_inference(db, split, tag):
    _, ws = split
    for name in ("QUAA101", "QUAA201"):
        element(db, ws, name)
    run(db, ws, tag)
    control = db.get(Asset, _uid(ws, f"{tag}:DEV:danfysik:QUAA-001"))
    supply = db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA-001"))
    assert supply.type == "Power Supply" and supply.name == "QUAA-001 Power Supply"
    assert supply.attributes.get("current_max") == 315, "ratings come from the channel"
    assert powered_by(db, supply) == {"QUAA101", "QUAA201"}
    assert relates(db, control, supply, "acts on")

    run(db, ws, tag, infer=True)
    assert powered_by(db, supply) == {"QUAA101", "QUAA201"}, "the same supply, the same links"
    assert db.get(Asset, _uid(ws, f"{tag}:ELM:QUAA-001")) is None, "the channel's name is not a magnet"


def test_with_no_list_a_channel_powers_the_magnet_of_its_own_name(db, split, tag):
    _, ws = split
    element(db, ws, "CHHA1002", "Corrector")
    it, _job = run(db, ws, tag)
    supply = db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:CHHA1002"))
    assert powered_by(db, supply) == {"CHHA1002"}
    assert db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:NOMAGNET")) is None, "no such magnet, no supply: as before"
    assert it.counts["magnets_linked"] == 1


def test_a_name_that_matches_nothing_is_reported_and_no_magnet_is_invented(db, split, tag):
    _, ws = split
    element(db, ws, "QUAA101")
    it, job = run(db, ws, tag, infer=True)
    db.refresh(job)
    assert it.counts["magnets_unresolved"] == 1
    assert any("QUAA201" in str(m) and "not linked" in str(m) for m in job.warnings or [job.message])
    assert db.query(Asset).filter(Asset.workspace_id == ws, Asset.name == "QUAA201").count() == 0
    assert powered_by(db, db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA-001"))) == {"QUAA101"}


def test_taking_a_magnet_off_the_list_removes_its_link_and_keeps_the_magnet(db, split, tag):
    _, ws = split
    gone = element(db, ws, "QUAA201")
    element(db, ws, "QUAA101")
    run(db, ws, tag)
    run(db, ws, tag, edit=lambda devices: devices[0].update(magnets=["QUAA101"]))
    assert powered_by(db, db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA-001"))) == {"QUAA101"}
    db.refresh(gone)
    assert gone.deleted_at is None


def test_a_retired_element_is_no_magnet_and_a_supply_a_person_recorded_is_reused(db, split, tag):
    _, ws = split
    element(db, ws, "QUAA101")
    old = element(db, ws, "QUAA201")
    old.record_status = "Retired"
    held = element(db, ws, "QUAA-001", "Power Supply")
    db.commit()
    run(db, ws, tag)
    assert db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA-001")) is None, "no twin of the supply"
    assert powered_by(db, held) == {"QUAA101"}
    assert relates(db, db.get(Asset, _uid(ws, f"{tag}:DEV:danfysik:QUAA-001")), held, "acts on")


def test_inference_links_to_the_beam_models_element_instead_of_a_twin(db, split, tag):
    """Seen in production: 12 BPMs and 12 magnets recorded twice, once by the beam model, once inferred."""
    _, ws = split
    magnet = element(db, ws, "QUAA301")
    text = CONFIG.replace("- {{name: NOMAGNET}}", "- {{name: QUAA301}}")
    run(db, ws, tag, infer=True, text=text)
    assert db.get(Asset, _uid(ws, f"{tag}:ELM:QUAA301")) is None
    assert powered_by(db, db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA301"))) == {"QUAA301"}
    db.refresh(magnet)
    assert magnet.attributes.get("argus_source") is None, "the import leaves the model's record as it is"


BPMS = """
beamline: {tag}
epicsConfiguration:
  iocs:
    - name: libera12
      template: libera-bplus
      devtype: bpm
      devgroup: diag
      iocprefix: ACC:DIA:LIB12
      devices: [{{name: BPSA11, channel: 3}}]
"""


def test_a_bpm_channel_reuses_the_beam_models_monitor(db, split, tag):
    _, ws = split
    monitor = element(db, ws, "BPSA11", "Beam Position Monitor")
    run(db, ws, tag, infer=True, text=BPMS)
    assert db.get(Asset, _uid(ws, f"{tag}:ELM:BPSA11")) is None
    assert relates(db, db.get(Asset, _uid(ws, f"{tag}:DEV:libera12:BPSA11")), monitor, "acts on")


def test_an_inferred_twin_goes_when_the_file_is_read_again_with_clear(db, split, tag):
    _, ws = split
    text = CONFIG.replace("- {{name: NOMAGNET}}", "- {{name: QUAA301}}")
    run(db, ws, tag, infer=True, text=text)
    twin = db.get(Asset, _uid(ws, f"{tag}:ELM:QUAA301"))
    assert twin is not None and twin.deleted_at is None
    model = element(db, ws, "QUAA301")
    run(db, ws, tag, infer=True, text=text, clear=True)
    db.refresh(twin)
    assert twin.deleted_at is not None
    assert "QUAA301" in powered_by(db, db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA301")))
    assert relates(db, db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA301")), model, "powers")
