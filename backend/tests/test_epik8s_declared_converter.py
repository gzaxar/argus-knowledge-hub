"""A converter the configuration declares, a supply's polarity, and which commits changed the file.

A Moxa the file lists as an IOC of its own (`devtype: moxaNport`, `nports: 8`) is stated, so it is made. The
Access Point stays the endpoint (asset-model-revision §9.2) and is `implemented by` it, and every serial port is
made. The serial port a line uses is read from its TCP port by Moxa's default, and only as advice: no port is
attached on a number (§9.3, I-PORT-4).
"""
import secrets

import yaml

from app.models.asset import Asset, Relation
from app.models.import_job import ImportJob
from app.services import epik8s_import
from app.services.epik8s_import import _Importer, _uid
from app.services.epik8s_import import _file_history as real_file_history
from tests.test_epik8s_it import db, edges, objects, tag, world  # noqa: F401

DECLARED = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    nport803: {name: nport803, template: moxaNport, iocprefix: "BTF:MOXA:N32", server: 192.168.192.32,
               devgroup: net, devtype: moxaNport, nports: 8}
    danfysik:
      iocprefix: ACC:MAG:DANFYSIK
      template: danfysik
      devgroup: mag
      devtype: sys80it
      server: 192.168.192.32
      port: 4001
      devices:
        - {name: QUAA-001, id: 2, ps: {current: {max: 315}, polarity: {mode: unipolar, sign: positive}}}
        - {name: QUAA-002, id: 3, magnets: [QUAA102], ps: {current: {max: 315}, polarity: {mode: unipolar, sign: negative}}}
    beyond:
      iocprefix: ACC:MAG:X
      devgroup: mag
      server: 192.168.192.32
      port: 4009
      devices: [{name: XTRA-001, id: 1}]
"""

OTHER_FILE = """
beamline: BEAMLINE
epicsConfiguration:
  iocs:
    dante:
      iocprefix: TL:MAG:DANTE
      devgroup: mag
      server: 192.168.192.32
      port: 4004
      devices: [{name: DHPTT001, id: 1}]
"""


def run(db, ws, tag, text=DECLARED, path="deploy/values-accumulator.yaml", history=None, ref="abc1234"):
    job = ImportJob(uid=f"job-{secrets.token_hex(4)}", workspace_id=ws, source="epik8s")
    db.add(job)
    db.commit()
    importer = _Importer(db, job, ws, f"https://git.example/g/r.git@{ref}:{path}")
    if history is not None:
        importer.history = lambda: history
    importer.ensure_types()
    importer.run(yaml.safe_load(text.replace("BEAMLINE", tag)), True)
    db.commit()
    return importer, job


def test_a_declared_moxa_is_made_and_the_access_point_stays_the_endpoint_it_implements(db, world, tag):
    _, _, (ws, _) = world
    importer, _ = run(db, ws, tag)
    found = objects(db, ws)
    converter = found[f"{tag}-SC-192.168.192.32"]
    assert converter.type == "Serial Converter" and converter.name == "nport803"
    assert converter.attributes["manufacturer"] == "Moxa" and converter.attributes["n_serial_ports"] == 8
    assert converter.attributes["tcp_port_base"] == 4001
    assert "ip" not in converter.attributes, "the Access Point answers to the address, not the converter"
    ap = f"NET-{ws}-192.168.192.32"
    assert found[ap].type == "Access Point"
    written = edges(db, ws)
    assert (ap, "implemented by", converter.key) in written
    assert (f"{tag}-IOC-nport803", "acts on", converter.key) in written
    assert (f"{tag}-IOC-nport803", "connects to", ap) in written
    assert importer.counts["converters_declared"] == 1
    assert not importer.not_inferred, "a declared converter is not something no rule recognised"


def test_every_serial_port_of_a_declared_converter_is_made_and_none_is_attached(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    converter = objects(db, ws)[f"{tag}-SC-192.168.192.32"]
    ports = {a.attributes["port_label"]: a for a in db.query(Asset).join(
        Relation, Relation.from_asset_uid == Asset.uid).filter(
        Relation.to_asset_uid == converter.uid, Relation.relation_type == "port of")}
    assert sorted(ports) == [f"P{n}" for n in range(1, 9)]
    assert ports["P5"].attributes["tcp_port"] == 4005 and ports["P5"].attributes["port_role"] == "serial-data#5"
    assert "Nobody has confirmed" in ports["P5"].attributes["description"]
    assert not db.query(Relation).filter(Relation.relation_type == "attached to",
                                         Relation.workspace_id == ws).count()


def test_a_line_is_carried_by_the_converter_and_names_its_probable_serial_port(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    found = objects(db, ws)
    line = found[f"{tag}-LINE-192.168.192.32-4001"]
    assert line.attributes["serial_port"] == "P1"
    assert "Not confirmed" in line.attributes["description"]
    assert (line.key, "carried by", f"{tag}-SC-192.168.192.32") in edges(db, ws)


def test_a_tcp_port_beyond_the_declared_ports_names_no_port_and_says_so(db, world, tag):
    _, _, (ws, _) = world
    _, job = run(db, ws, tag)
    line = objects(db, ws)[f"{tag}-LINE-192.168.192.32-4009"]
    assert "serial_port" not in line.attributes
    assert not [a for a in objects(db, ws).values() if a.name.endswith(" P9")]
    db.refresh(job)
    assert any("P9" in w and "does not have" in w for w in job.warnings or []), job.warnings


def test_another_file_reaching_the_same_address_uses_the_declared_converter(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    run(db, ws, tag, text=OTHER_FILE, path="deploy/values-tl.yaml")
    found = objects(db, ws)
    line = found[f"{tag}-LINE-192.168.192.32-4004"]
    assert line.attributes["serial_port"] == "P4"
    assert (line.key, "carried by", f"{tag}-SC-192.168.192.32") in edges(db, ws)
    assert len([a for a in found.values() if a.type == "Serial Converter"]) == 1
    assert len([a for a in found.values() if a.type == "Access Point"]) == 1


def test_a_re_read_changes_nothing(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag)
    before = {k: dict(a.attributes) for k, a in objects(db, ws).items()}
    second, _ = run(db, ws, tag)
    after = {k: dict(a.attributes) for k, a in objects(db, ws).items()}
    strip = lambda d: {k: {f: v for f, v in a.items() if f != "imported_at"} for k, a in d.items()}  # noqa: E731
    assert strip(before) == strip(after)
    assert second.counts["converters_declared"] == 1


def test_a_unipolar_supply_keeps_its_sign_and_its_maker(db, world, tag):
    _, _, (ws, _) = world
    from tests.test_epik8s_magnets import element
    element(db, ws, "QUAA102")
    run(db, ws, tag)
    supply = db.get(Asset, _uid(ws, f"{tag}:AST:danfysik:QUAA-002"))
    assert supply.attributes["polarity_sign"] == "negative" and supply.attributes["bipolar"] is False
    assert supply.attributes["manufacturer"] == "Danfysik" and supply.attributes["model"] == "System 8000"
    from app.services.element_inference import _ratings
    assert "polarity_sign" not in _ratings({}, {"ps": {"polarity": {"mode": "bipolar", "sign": "positive"}}})


# --- which commits changed the file ----------------------------------------------------------------

def commit(sha, title, date="2026-11-06T09:00:00Z", author="A. Person"):
    return {"sha": sha * 5, "title": title, "author": author, "date": date, "url": f"https://git.example/c/{sha}"}


def test_the_configuration_names_the_commit_read_and_the_last_change_to_the_file(db, world, tag):
    _, _, (ws, _) = world
    run(db, ws, tag, history=[commit("aaaaaaaa", "add magnets lists")], ref="4f71d477")
    cfg = objects(db, ws)[f"{tag}-CFG-values-accumulator"]
    assert cfg.attributes["git_commit"] == "4f71d477"
    assert cfg.attributes["git_last_change"] == "add magnets lists (A. Person)"
    assert cfg.attributes["git_last_change_url"] == "https://git.example/c/aaaaaaaa"
    assert "git_recent_changes" not in cfg.attributes, "a first import has nothing to compare with"


def test_a_re_import_lists_the_commits_that_changed_the_file_since_the_previous_one(db, world, tag):
    _, _, (ws, _) = world
    first = [commit("aaaaaaaa", "add magnets lists")]
    run(db, ws, tag, history=first, ref="4f71d477")
    newer = [commit("cccccccc", "QUAA-002 is negative", "2026-11-09T10:00:00Z"),
             commit("bbbbbbbb", "declare nport803", "2026-11-08T10:00:00Z"), *first]
    _, job = run(db, ws, tag, history=newer, ref="5e00e000")
    cfg = objects(db, ws)[f"{tag}-CFG-values-accumulator"]
    assert cfg.attributes["git_recent_changes"] == [
        "cccccccc 2026-11-09 A. Person: QUAA-002 is negative", "bbbbbbbb 2026-11-08 A. Person: declare nport803"]
    db.refresh(job)
    assert any(w.startswith("2 commits changed this file") for w in job.warnings or []), job.warnings
    # Read again at a commit that did not touch the file: the list stays what it was.
    run(db, ws, tag, history=newer, ref="6f00f000")
    cfg = objects(db, ws)[f"{tag}-CFG-values-accumulator"]
    assert len(cfg.attributes["git_recent_changes"]) == 2


def test_the_file_history_is_read_from_gitlab_and_github(monkeypatch):
    class Reply:
        def __init__(self, body):
            self.ok, self._body = True, body

        def json(self):
            return self._body

    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        if "gitlab" in url:
            return Reply([{"id": "a" * 40, "title": "add magnets", "author_name": "A", "committed_date": "2026-11-06",
                           "web_url": "https://gitlab.example/c"}])
        return Reply([{"sha": "b" * 40, "commit": {"message": "first line\n\nbody", "author": {
            "name": "B", "date": "2026-11-07"}}, "html_url": "https://github.com/c"}])

    monkeypatch.setattr(epik8s_import.requests, "get", get)
    lab = real_file_history("gitlab", "https://gitlab.example/g/r.git", None, "abc", "deploy/values.yaml")
    hub = real_file_history("github", "https://github.com/o/r", None, "abc", "deploy/values.yaml")
    assert lab == [{"sha": "a" * 40, "title": "add magnets", "author": "A", "date": "2026-11-06",
                    "url": "https://gitlab.example/c"}]
    assert hub[0]["title"] == "first line" and hub[0]["author"] == "B"
    assert all(p["path"] == "deploy/values.yaml" for _, p in calls)
