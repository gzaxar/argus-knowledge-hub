"""The catalogue's pinned sources (app/catalogue/sources.py): an Argus-native repository and a NetBox Device
Type Library fork, read at their pinned commits (local repositories here, no network), the NetBox device
types turned into entries with ARGUS's classification, and the rules that keep one shared catalogue: a model
defined once across both sources, a classification only for a model NetBox defines, a vendor that exists,
and a release tag that has not moved."""
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from app.catalogue.loader import load_tree
from app.catalogue.sources import SourceProblem, materialize
from app.catalogue.validate import tree_problems

NPORT = {"manufacturer": "Moxa", "model": "NPort 5450", "slug": "moxa-nport-5450", "u_height": 0,
         "is_full_depth": False, "interfaces": [{"name": "eth0", "type": "100base-tx"}],
         "console-server-ports": [{"name": f"P{i}", "type": "db-9"} for i in range(1, 5)],
         "power-ports": [{"name": "DC", "type": "dc-terminal"}]}
SWITCH = {"manufacturer": "Cisco", "model": "C9200-24T", "slug": "cisco-c9200-24t", "part_number": "C9200-24T",
          "u_height": 1, "is_full_depth": False, "airflow": "front-to-rear", "weight": 3.9, "weight_unit": "kg",
          "interfaces": [{"name": f"Gi1/0/{i}", "type": "1000base-t"} for i in range(1, 25)]
          + [{"name": "Vlan1", "type": "virtual"}]}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(repo), "PATH": "/usr/bin:/bin"}).stdout.strip()


def repo_with(path: Path, files: dict[str, object]) -> str:
    """A repository with these files committed; returns the commit."""
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        git(path, "init", "-q", "-b", "main")
    for rel, content in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content if isinstance(content, str) else yaml.safe_dump(content, sort_keys=False))
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "c")
    return git(path, "rev-parse", "HEAD")


def argus_files(classifications=None, models=None, vendors=None) -> dict:
    vendors = vendors if vendors is not None else [{"id": "moxa", "name": "Moxa", "aliases": ["MOXA Technologies"]},
                                                   {"id": "cisco", "name": "Cisco", "aliases": ["Cisco Systems"]}]
    files = {
        "README.md": "test",
        "collections/vendors/collection.yaml": {"id": "vendors", "version": "0.2.0", "name": "V", "domain": "catalogue",
                                                "owner": "o", "license": "CC0-1.0", "contents": ["vendors.yaml"],
                                                "requires": {"packages": {"core-objects": ">=2.1,<3"}}},
        "collections/vendors/vendors.yaml": {"vendors": vendors},
        "collections/it-classification/collection.yaml": {
            "id": "it-classification", "version": "0.1.0", "name": "C", "domain": "catalogue", "owner": "o",
            "license": "CC0-1.0", "contents": ["c.yaml"],
            "requires": {"packages": {"core-objects": ">=2.1,<3", "it": ">=1.1,<2"},
                         "collections": {"vendors": ">=0.2,<1"}}},
        "collections/it-classification/c.yaml": {"classifications": classifications if classifications is not None else [
            {"id": "moxa/nport-5450", "device_class": "converter", "instance_type": "Serial Converter"},
            {"id": "cisco/c9200-24t", "device_class": "network switch"}]},
    }
    if models is not None:
        files["collections/vacuum/collection.yaml"] = {
            "id": "vacuum", "version": "0.1.0", "name": "Vac", "domain": "catalogue", "owner": "o",
            "license": "CC0-1.0", "contents": ["models.yaml"],
            "requires": {"packages": {"core-objects": ">=2.1,<3"}, "collections": {"vendors": ">=0.2,<1"}}}
        files["collections/vacuum/models.yaml"] = {"models": models}
    return files


def lock(tmp: Path, argus_commit: str, netbox_commit: str, select=("Moxa/*", "Cisco/*"), ref="main") -> Path:
    d = tmp / "lock"
    d.mkdir(exist_ok=True)
    (d / "sources.lock.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": "argus", "kind": "argus-collections", "repo": str(tmp / "argus"), "ref": ref, "commit": argus_commit},
        {"id": "netbox", "kind": "netbox-devicetype-library", "repo": str(tmp / "netbox"), "ref": "infn",
         "commit": netbox_commit, "select": list(select),
         "collection": {"id": "it-devices", "version": "0.1.0", "name": "IT devices",
                        "requires": {"packages": {"core-objects": ">=2.1,<3", "it": ">=1.1,<2"},
                                     "collections": {"vendors": ">=0.2,<1"}}}}]}))
    return d / "sources.lock.yaml"


def netbox(tmp: Path, **extra) -> str:
    return repo_with(tmp / "netbox", {"device-types/Moxa/NPort-5450.yaml": NPORT,
                                      "device-types/Cisco/C9200-24T.yaml": SWITCH,
                                      "device-types/Other/Thing.yaml": {"manufacturer": "Other", "model": "T",
                                                                        "slug": "other-t", "u_height": 1,
                                                                        "is_full_depth": False},
                                      **extra})


def problems(root: Path) -> list[str]:
    return [str(p) for ps in tree_problems(load_tree(root)).values() for p in ps]


def test_both_sources_make_one_catalogue(tmp_path):
    a, n = repo_with(tmp_path / "argus", argus_files()), netbox(tmp_path)
    root = materialize(lock(tmp_path, a, n), cache=tmp_path / "cache")
    tree = load_tree(root)
    assert set(tree) == {"vendors", "it-classification", "it-devices"}
    assert tree["it-devices"].origin == "netbox"
    models = {m.id: m.data for m in tree["it-devices"].models}
    assert set(models) == {"moxa/nport-5450", "cisco/c9200-24t"}                 # only what is selected
    nport, switch = models["moxa/nport-5450"], models["cisco/c9200-24t"]
    assert nport["vendor"] == "moxa" and nport["model_code"] == "NPort 5450" and nport["name"] == "Moxa NPort 5450"
    assert nport["device_class"] == "converter" and nport["instance_type"] == "Serial Converter"   # ARGUS's side
    assert nport["specifications"] == {"network_ports": 1, "interface_types": ["100base-tx"], "serial_ports": 4,
                                       "power_inputs": 1}
    assert switch["specifications"]["network_ports"] == 24                      # the virtual one is not a port
    assert switch["specifications"]["weight"] == {"value": 3.9, "unit": "kg"} and switch["part_number"] == "C9200-24T"
    assert nport["sources"] == [{"kind": "netbox-devicetype-library", "ref": "device-types/Moxa/NPort-5450.yaml",
                                 "revision": n[:12]}]
    assert problems(root) == []
    # Read once per lock: the same folder again, without fetching.
    assert materialize(lock(tmp_path, a, n), cache=tmp_path / "cache") == root


def test_the_pinned_commit_is_what_is_read(tmp_path):
    a, n = repo_with(tmp_path / "argus", argus_files()), netbox(tmp_path)
    later = repo_with(tmp_path / "netbox", {"device-types/Moxa/NPort-5450.yaml": {**NPORT, "model": "NPort 5450 v2"}})
    root = materialize(lock(tmp_path, a, n), cache=tmp_path / "cache")
    nport = next(m for m in load_tree(root)["it-devices"].models if m.id == "moxa/nport-5450")
    assert nport.data["model_code"] == "NPort 5450"                             # not the branch head
    root2 = materialize(lock(tmp_path, a, later), cache=tmp_path / "cache")
    assert root2 != root


def test_a_model_is_defined_once_across_both_sources(tmp_path):
    same = {"id": "moxa/nport-5450", "vendor": "moxa", "model_code": "NPort 5450", "name": "NPort 5450",
            "device_class": "converter"}
    a = repo_with(tmp_path / "argus", argus_files(models=[same]))
    root = materialize(lock(tmp_path, a, netbox(tmp_path)), cache=tmp_path / "cache")
    found = "\n".join(problems(root))
    assert "'moxa/nport-5450' is already used" in found
    assert "classifications › moxa/nport-5450: vacuum defines this model itself" in found


def test_a_netbox_model_may_be_unclassified_and_a_classification_needs_its_model(tmp_path):
    a = repo_with(tmp_path / "argus", argus_files(classifications=[
        {"id": "moxa/nport-5450", "device_class": "converter"},
        {"id": "moxa/nport-9999", "device_class": "converter"}]))
    root = materialize(lock(tmp_path, a, netbox(tmp_path)), cache=tmp_path / "cache")
    found = "\n".join(problems(root))
    assert "cisco/c9200-24t" not in found                                       # selected, not classified: fine
    assert "classifications › moxa/nport-9999: no model with this id in any source" in found
    switch = next(m for m in load_tree(root)["it-devices"].models if m.id == "cisco/c9200-24t")
    assert "device_class" not in switch.data


def test_an_unknown_manufacturer_becomes_a_vendor_of_the_collection(tmp_path):
    a = repo_with(tmp_path / "argus", argus_files(vendors=[{"id": "moxa", "name": "Moxa"}]))
    n = netbox(tmp_path)
    root = materialize(lock(tmp_path, a, n, select=("*",)), cache=tmp_path / "cache")
    tree = load_tree(root)
    made = {v.id: v.data for v in tree["it-devices"].vendors}
    assert set(made) == {"cisco", "other"}                                      # Moxa is ARGUS's already
    assert made["cisco"]["name"] == "Cisco" and made["cisco"]["sources"] == [
        {"kind": "netbox-devicetype-library", "ref": "device-types/Cisco", "revision": n[:12]}]
    models = {m.id: m.data for m in tree["it-devices"].models}
    assert models["cisco/c9200-24t"]["vendor"] == "cisco" and models["moxa/nport-5450"]["vendor"] == "moxa"
    assert set(models) == {"moxa/nport-5450", "cisco/c9200-24t", "other/t"}     # "*": every device type
    assert problems(root) == []


def test_exclude_leaves_out_what_select_takes(tmp_path):
    a, n = repo_with(tmp_path / "argus", argus_files()), netbox(tmp_path)
    lk = lock(tmp_path, a, n, select=("*",))
    data = yaml.safe_load(lk.read_text())
    data["sources"][1]["exclude"] = ["Other/*", "Cisco/C9200-*"]
    lk.write_text(yaml.safe_dump(data))
    models = {m.id for m in load_tree(materialize(lk, cache=tmp_path / "cache"))["it-devices"].models}
    assert models == {"moxa/nport-5450"}
    data["sources"][1]["exclude"] = "Other/*"
    lk.write_text(yaml.safe_dump(data))
    with pytest.raises(SourceProblem, match="`exclude` is a list of patterns"):
        materialize(lk, cache=tmp_path / "cache2")


def test_a_made_vendor_never_takes_an_id_already_used(tmp_path):
    a = repo_with(tmp_path / "argus", argus_files(vendors=[{"id": "other", "name": "Other Industries AG"},
                                                           {"id": "moxa", "name": "Moxa"}, {"id": "cisco", "name": "Cisco"}]))
    root = materialize(lock(tmp_path, a, netbox(tmp_path), select=("*",)), cache=tmp_path / "cache")
    made = {v.id: v.data["name"] for v in load_tree(root)["it-devices"].vendors}
    assert made == {"other-2": "Other"}                                         # "other" is another company's id


def test_a_moved_release_tag_is_refused(tmp_path):
    a = repo_with(tmp_path / "argus", argus_files())
    git(tmp_path / "argus", "tag", "v0.1.0")
    n = netbox(tmp_path)
    assert materialize(lock(tmp_path, a, n, ref="v0.1.0"), cache=tmp_path / "c1")
    b = repo_with(tmp_path / "argus", {"README.md": "changed"})
    git(tmp_path / "argus", "tag", "-f", "v0.1.0", b)                            # someone moves the tag
    with pytest.raises(SourceProblem, match="no longer points at the pinned commit"):
        materialize(lock(tmp_path, a, n, ref="v0.1.0"), cache=tmp_path / "c2")


def test_a_lock_that_names_a_branch_head_is_refused(tmp_path):
    d = tmp_path / "lock"
    d.mkdir()
    (d / "sources.lock.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": "argus", "kind": "argus-collections", "repo": "x", "ref": "main", "commit": "main"}]}))
    with pytest.raises(SourceProblem, match="full 40-character commit"):
        materialize(d / "sources.lock.yaml", cache=tmp_path / "cache")


def test_a_netbox_device_type_keeps_every_component_its_notes_and_its_datasheet(tmp_path):
    """Everything a device type says comes in: each component list as NetBox writes it, its notes (and the
    datasheet linked from them), its weight and power draw."""
    from app.catalogue.sources import netbox_entry
    doc = {**SWITCH, "comments": "[Data sheet](https://vendor.example/c9200.pdf).", "description": "A switch",
           "weight": 8.6, "weight_unit": "lb",
           "interfaces": SWITCH["interfaces"] + [{"name": "Gi0/0", "type": "1000base-t", "mgmt_only": True}],
           "console-ports": [{"name": "Console", "type": "rj-45"}],
           "power-ports": [{"name": "PS-A", "type": "iec-60320-c14", "maximum_draw": 125, "allocated_draw": 60},
                           {"name": "PS-B", "type": "iec-60320-c14", "maximum_draw": 125}],
           "module-bays": [{"name": "Network Module", "position": "1"}],
           "inventory-items": [{"name": "Fan", "manufacturer": "Cisco", "part_id": "FAN-T1"}]}
    e, why = netbox_entry(doc, "device-types/Cisco/C9200-24T.yaml", "abcdef1234567890", [{"id": "cisco", "name": "Cisco"}])
    assert why is None
    assert e["datasheet_url"] == "https://vendor.example/c9200.pdf" and e["notes"].startswith("[Data sheet]")
    assert e["description"] == "A switch" and e["specifications"]["maximum_draw_w"] == 125
    assert set(e["components"]) == {"interfaces", "console_ports", "power_ports", "module_bays", "inventory_items"}
    assert e["components"]["power_ports"][0] == {"name": "PS-A", "type": "iec-60320-c14", "maximum_draw": 125,
                                                 "allocated_draw": 60}
    assert {"name": "Gi0/0", "type": "1000base-t", "mgmt_only": True} in e["components"]["interfaces"]

    from app.catalogue.install import _hardware
    h = _hardware(e)
    assert h["weight_kg"] == 3.901 and h["rack_units"] == 1 and h["full_depth"] is False
    assert h["part_number"] == "C9200-24T" and h["maximum_draw_w"] == 125
    assert h["port_summary"] == "24 × 1000base-t, 1 management, 1 console, 2 power, 1 module bay"   # Vlan1: not a socket
    assert json.loads(h["components"]) == e["components"]


def test_a_collection_with_components_is_valid_and_a_malformed_one_is_not(tmp_path):
    good = [{"id": "moxa/nport-5650-8", "vendor": "moxa", "model_code": "NPort 5650-8", "name": "Moxa NPort 5650-8",
             "device_class": "converter", "notes": "8 ports",
             "components": {"console_server_ports": [{"name": "P1", "type": "de-9", "description": "RS-232/422/485"}]}}]
    repo_with(tmp_path / "argus", argus_files(models=good, classifications=[]))
    assert not [p for p in problems_of(tmp_path, "c1") if "vacuum" in p]
    bad = [{**good[0], "components": {"Console Server Ports": [{"name": ["P1"]}]}}]
    repo_with(tmp_path / "argus", argus_files(models=bad, classifications=[]))
    found = [p for p in problems_of(tmp_path, "c2") if "components" in p]
    assert any("lowercase words" in p for p in found) and any("plain values" in p for p in found)


def problems_of(tmp_path: Path, cache: str) -> list[str]:
    a = git(tmp_path / "argus", "rev-parse", "HEAD")
    n = netbox(tmp_path) if not (tmp_path / "netbox").exists() else git(tmp_path / "netbox", "rev-parse", "HEAD")
    return problems(materialize(lock(tmp_path, a, n), cache=tmp_path / cache))


def test_the_netbox_library_is_one_file_per_vendor_and_read_in_part(tmp_path):
    """Every component of 12,760 device types is too much to read on a page view: the library's models are
    written one file per vendor, and the application reads only the vendors of the models it needs — the same
    collection (checksum), with no problem for the models it did not read."""
    a, n = repo_with(tmp_path / "argus", argus_files()), netbox(tmp_path)
    root = materialize(lock(tmp_path, a, n), cache=tmp_path / "cache")
    manifest = yaml.safe_load((root / "it-devices" / "collection.yaml").read_text())
    assert manifest["contents"] == ["models/cisco.yaml", "models/moxa.yaml"]
    part = load_tree(root, netbox_models={"it-devices": {"moxa/nport-5450"}})
    some = part["it-devices"]
    assert [m.id for m in load_tree(root, netbox_models={})["it-devices"].models] == []
    assert [str(p) for ps in tree_problems(part).values() for p in ps] == []      # cisco: classified, not read
    full = load_tree(root)["it-devices"]                  # a small tree is then kept whole
    assert some.partial and not full.partial and some.checksum == full.checksum
    assert [m.id for m in some.models] == ["moxa/nport-5450"]
    assert problems(root) == []
