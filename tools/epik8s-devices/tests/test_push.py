"""Writing a reviewed device list into a hub.

`push` writes the object catalogue's own types under the keys the hub's
configuration import uses, so the two tools add to one set of objects. What is
worth testing is what would quietly go wrong: a per-class type made beside the
catalogue, an import's attributes overwritten by an empty cell, an IOC row
written as a device, and a link made twice.
"""
import os
import sys
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epik8s_devices import cli  # noqa: E402
from epik8s_devices.hub import HubError  # noqa: E402

# Pinned, and the same literal is asserted in the backend's tests
# (test_epik8s_import.py): if either tool changes how it derives a uid, one of the
# two fails, instead of the tools quietly writing two objects for one thing.
UID_OF_A_KNOWN_DEVICE = "epik8s-fe97cc093dbeb345ecb787f0"


class FakeHub:
    def __init__(self, workspace="ws1", schemas=None, assets=None, relations=None):
        self.workspace = workspace
        self._schemas = schemas if schemas is not None else [
            {"uid": "s-device", "name": "Control Device", "workspace_id": workspace},
            {"uid": "s-ioc", "name": "IOC", "workspace_id": workspace},
        ]
        self.assets = dict(assets or {})
        self._relations = list(relations or [])
        self.created, self.updated, self.linked = [], [], []

    def whoami(self):
        return {"auth_type": "pat", "workspace_id": self.workspace}

    def schemas(self):
        return self._schemas

    def get_asset(self, uid):
        return self.assets.get(uid)

    def create_asset(self, payload):
        self.assets[payload["uid"]] = payload
        self.created.append(payload)
        return payload

    def update_asset(self, uid, patch):
        self.assets[uid] = {**self.assets[uid], **patch}
        self.updated.append((uid, patch))

    def relations(self):
        return self._relations

    def create_relation(self, from_uid, to_uid, relation_type):
        row = {"from_asset_uid": from_uid, "to_asset_uid": to_uid, "relation_type": relation_type}
        self._relations.append(row)
        self.linked.append(row)


DEVICE_ROW = {
    "beamline": "SPARC", "ioc": "histar", "name": "GUNQUA01", "key": "SPARC:histar:GUNQUA01",
    "pv": "SPARC:MAG:HISTAR:GUNQUA01", "device_class": "Power Supply", "vendor": "CAEN ELS",
    "model": "Hi-Star", "element": "Quadrupole", "system": "Magnets", "function": None,
    "zones": ["LINAC"], "connection": {"host": "192.168.0.28", "via": "ip", "port": "502"},
    "model_spec": {"current_max": 30}, "settings": {"geo": 5},
    "physical_asset": None, "needs": ["link to the physical asset"], "source": "values.yaml",
}


def push(tmp_path, monkeypatch, rows, hub, dry_run=False):
    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(rows))
    monkeypatch.setattr(cli, "Hub", lambda *_a, **_k: hub)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("asked to confirm a dry run"))
    args = SimpleNamespace(devices=str(path), hub="http://hub", token="t", dry_run=dry_run, yes=True)
    return cli.cmd_push(args)


# What the hub's catalogue declares for a Control Device that `push` writes. The same
# list is asserted in the backend's tests (test_asset_types.py) against the catalogue.
CLI_PUSHES = {
    "beamline", "pv", "pv_prefix", "ioc", "system", "function", "zones", "address", "port", "channel",
    "axis", "settings", "argus_facility", "argus_source", "argus_source_ref", "device_class",
    "element", "vendor", "model_code", "argus_keywords",
}


def test_every_key_it_writes_is_one_the_catalogue_declares():
    row = {**DEVICE_ROW, "connection": {"host": "h", "port": "1", "channel": 2, "axis": 3},
           "function": "ion"}
    assert set(cli.new_device_attributes(row)) <= CLI_PUSHES
    assert set(cli.review_attributes(row)) <= CLI_PUSHES


def test_the_uid_is_the_one_the_hubs_own_import_derives():
    assert cli.object_uid("ws1", "SPARC:DEV:histar:GUNQUA01") == UID_OF_A_KNOWN_DEVICE


def test_a_row_is_a_control_device_under_the_key_the_import_gives_it(tmp_path, monkeypatch):
    hub = FakeHub()
    assert push(tmp_path, monkeypatch, [DEVICE_ROW], hub) == 0
    (made,) = hub.created
    assert made["key"] == "SPARC-DEV-histar-GUNQUA01" and made["uid"] == UID_OF_A_KNOWN_DEVICE
    assert made["type"] == "Control Device" and made["schema_uid"] == "s-device"
    attrs = made["attributes"]
    assert attrs["device_class"] == "Power Supply" and attrs["element"] == "Quadrupole"
    assert attrs["address"] == "192.168.0.28" and attrs["port"] == "502"
    assert attrs["pv"] == "SPARC:MAG:HISTAR:GUNQUA01" and attrs["zones"] == ["LINAC"]
    assert attrs["argus_source"] == "epik8s-devices" and attrs["argus_facility"] == "SPARC"
    assert attrs["argus_keywords"] == ["link to the physical asset"]


def test_it_makes_no_type_of_its_own(tmp_path, monkeypatch):
    """The old push made one type per device class beside the catalogue."""
    classes = ("Vacuum", "Cooling", "I/O", "Power Supply", "")
    rows = [{**DEVICE_ROW, "name": f"DEV{i}", "key": f"SPARC:histar:DEV{i}", "device_class": c}
            for i, c in enumerate(classes)]
    hub = FakeHub()
    before = list(hub.schemas())
    push(tmp_path, monkeypatch, rows, hub)
    assert hub.schemas() == before and not hasattr(hub, "create_schema")
    assert len(hub.created) == len(classes)
    assert {a["type"] for a in hub.created} == {"Control Device"}      # every class, one type
    stored = {a["attributes"].get("device_class") for a in hub.created}
    assert stored - {None} == set(classes) - {""}                     # the class is a value...
    assert None in stored                                             # ...and an empty one is not stored


def test_a_device_the_import_already_made_gains_only_what_the_review_adds(tmp_path, monkeypatch):
    uid = cli.object_uid("ws1", "SPARC:DEV:histar:GUNQUA01")
    already = {"uid": uid, "attributes": {"settings": {"tsh": "3E-7"}, "address": "192.168.0.28",
                                          "argus_source": "epik8s", "element": "kept?"}}
    hub = FakeHub(assets={uid: already})
    push(tmp_path, monkeypatch, [{**DEVICE_ROW, "element": "Quadrupole", "vendor": None}], hub)
    assert not hub.created
    (_, patch), = hub.updated
    merged = patch["attributes"]
    assert merged["settings"] == {"tsh": "3E-7"}           # the import's, not the scan's
    assert merged["argus_source"] == "epik8s"              # it stays the import's object
    assert merged["element"] == "Quadrupole"               # the review's word
    assert merged["device_class"] == "Power Supply"


def test_an_empty_cell_never_erases_what_somebody_entered(tmp_path, monkeypatch):
    uid = cli.object_uid("ws1", "SPARC:DEV:histar:GUNQUA01")
    hub = FakeHub(assets={uid: {"uid": uid, "attributes": {"vendor": "Entered by hand"}}})
    row = {**DEVICE_ROW, "vendor": None, "model": "", "device_class": "", "element": None, "needs": []}
    push(tmp_path, monkeypatch, [row], hub)
    assert not hub.updated and not hub.created            # nothing to add, nothing written


def test_an_ioc_only_row_is_an_ioc_not_a_device_with_the_iocs_name(tmp_path, monkeypatch):
    row = {**DEVICE_ROW, "name": "orbit", "ioc": "orbit", "ioc_only": True,
           "physical_asset": "asset-uid-1"}
    ioc_uid = cli.object_uid("ws1", "SPARC:IOC:orbit")
    hub = FakeHub(assets={ioc_uid: {"uid": ioc_uid, "attributes": {}}})
    push(tmp_path, monkeypatch, [row], hub)
    assert not hub.created and not hub.updated             # the IOC is the import's to describe
    assert hub.linked == [{"from_asset_uid": ioc_uid, "to_asset_uid": "asset-uid-1",
                           "relation_type": "drives"}]


def test_an_ioc_the_import_has_not_made_is_named_not_invented(tmp_path, monkeypatch, capsys):
    row = {**DEVICE_ROW, "name": "orbit", "ioc": "orbit", "ioc_only": True}
    hub = FakeHub()
    push(tmp_path, monkeypatch, [row], hub)
    assert not hub.created
    assert "Import the configuration first" in capsys.readouterr().err


def test_rows_from_before_the_marker_existed_still_read_an_ioc_row_as_one():
    assert cli._is_ioc_row({"name": "orbit", "ioc": "orbit"})
    assert not cli._is_ioc_row({"name": "GUNQUA01", "ioc": "histar"})


def test_a_physical_asset_becomes_an_acts_on_link_made_once(tmp_path, monkeypatch):
    row = {**DEVICE_ROW, "physical_asset": "asset-uid-9"}
    hub = FakeHub()
    push(tmp_path, monkeypatch, [row], hub)
    push(tmp_path, monkeypatch, [row], hub)                # again
    assert [(l["relation_type"], l["to_asset_uid"]) for l in hub.linked] == [("acts on", "asset-uid-9")]


def test_a_workspace_without_the_catalogue_is_told_to_seed_it(tmp_path, monkeypatch):
    hub = FakeHub(schemas=[{"uid": "x", "name": "Power Supply", "workspace_id": "ws1"}])
    with pytest.raises(HubError, match="seed_asset_types"):
        push(tmp_path, monkeypatch, [DEVICE_ROW], hub)
    assert not hub.created


def test_the_workspaces_own_type_is_used_before_a_shared_one(tmp_path, monkeypatch):
    hub = FakeHub(schemas=[
        {"uid": "shared-device", "name": "Control Device", "workspace_id": "catalogue"},
        {"uid": "own-device", "name": "Control Device", "workspace_id": "ws1"},
        {"uid": "own-ioc", "name": "IOC", "workspace_id": "ws1"},
    ])
    push(tmp_path, monkeypatch, [DEVICE_ROW], hub)
    assert hub.created[0]["schema_uid"] == "own-device"


def test_a_dry_run_writes_nothing_and_does_not_ask(tmp_path, monkeypatch):
    hub = FakeHub()
    assert push(tmp_path, monkeypatch, [DEVICE_ROW], hub, dry_run=True) == 0
    assert not hub.created and not hub.updated and not hub.linked


def test_a_second_push_of_the_same_review_writes_nothing(tmp_path, monkeypatch):
    uid = cli.object_uid("ws1", "SPARC:DEV:histar:GUNQUA01")
    hub = FakeHub(assets={uid: {"uid": uid, "attributes": {}}})
    push(tmp_path, monkeypatch, [DEVICE_ROW], hub)
    assert len(hub.updated) == 1
    push(tmp_path, monkeypatch, [DEVICE_ROW], hub)          # the hub now holds what the review says
    assert len(hub.updated) == 1
