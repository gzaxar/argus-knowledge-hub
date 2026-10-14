"""The seven domain packages on a neutral core: each one's representative queries against its fixtures, the
workspaces they make (only IT, only technology transfer), approval workflows, code validators, typed
relations, role templates and restricted classes, and workspaces made with 1.35.25's packages upgrading
with nothing they had lost."""
import secrets
import shutil
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import OidcIdentity, get_identity
from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.issue import Issue
from app.models.schema import Schema
from app.models.user import User
from app.models.workspace import Workspace
from app.packages import defaults, loader, queries
from app.packages import install as installer
from app.packages.loader import available
from app.services import asset_types

client = TestClient(app)
DOMAINS = ("safety", "vacuum-cryo", "civil-access", "optics-alignment", "environmental", "administration",
           "tech-transfer")
RELEASE_1_35_25 = Path(__file__).parent / "fixtures" / "package_versions" / "release-1.35.25"


@pytest.fixture()
def spaces():
    made: list[str] = []

    def make(packages=(), prefix="dc") -> str:
        w = f"{prefix}-{secrets.token_hex(3)}"
        db = SessionLocal()
        db.add(Workspace(id=w, name=w))
        db.flush()
        if packages:
            installer.install(db, w, list(packages))
        db.commit()
        db.close()
        made.append(w)
        return w
    yield make
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    for w in reversed(made):
        row = db.get(Workspace, w)
        if row is not None:
            db.delete(row)
    db.commit()
    db.close()


def _types(db, ws) -> set[str]:
    return set(db.scalars(select(Schema.name).where(Schema.workspace_id == ws, Schema.applies_to == "objects")))


def _kinds(db, ws, applies) -> set[str]:
    return set(db.scalars(select(Schema.name).where(Schema.workspace_id == ws, Schema.applies_to == applies)))


def _descends(db, ws, name: str, root: str) -> bool:
    s = db.get(Schema, asset_types.type_uid(ws, name))
    while s is not None:
        if s.name == root:
            return True
        s = db.get(Schema, s.parent_schema_uid) if s.parent_schema_uid else None
    return False


# --------------------------------------------------------------------------- the catalogue as a whole

def test_no_two_packages_define_the_same_type_kind_verb_role_or_class():
    shipped = available()
    seen: dict = {}
    for p in shipped.values():
        names = [("type", t["name"]) for t in (p.section("object_types") or {}).get("types") or []]
        names += [("ticket kind", k["name"]) for k in (p.section("ticket_types") or {}).get("kinds") or []]
        names += [("document kind", k["name"]) for k in (p.section("document_types") or {}).get("kinds") or []]
        names += [("verb", r["verb"].lower()) for r in p.section("relation_types") or []]
        names += [("role", r["id"]) for r in p.section("roles") or []]
        names += [("class", c["id"]) for c in p.section("restricted_classes") or []]
        names += [("workflow", w["id"]) for w in p.section("workflows") or []]
        for n in names:
            assert n not in seen, f"{n} is in {seen.get(n)} and {p.id}"
            seen[n] = p.id
    # "Access Point" stays the control endpoint; the physical side of access control has its own names
    assert seen[("type", "Access Point")] == "accelerator"
    assert {seen[("type", n)] for n in ("Door", "Badge Reader", "Access Controller")} == {"civil-access"}


def _redefinitions(types) -> set:
    by_name = {t.name: t for t in types}
    out = set()
    for t in by_name.values():
        cur, inherited = t.parent, set()
        while cur in by_name:
            inherited |= {a["key"] for a in by_name[cur].attributes}
            cur = by_name[cur].parent
        out |= {(t.name, a["key"]) for a in t.attributes if a["key"] in inherited}
    return out


def _release_types():
    from app.packages import compile as c
    from app.packages.loader import load
    pkgs = [load(RELEASE_1_35_25 / pid) for pid in ("core-facility", "core-objects", "it", "accelerator", "electrical",
                                                     "hydraulic", "hvac", "plant")]
    sets = c.option_sets(pkgs)
    return [t for p in pkgs for t in c.object_types(p, sets)]


# Redefinitions that predate 1.35.26 (records hold values under them): allowed, not to be repeated.
KNOWN_REDEFINITIONS = _redefinitions(_release_types())


def test_no_type_redefines_a_field_it_inherits():
    by_name = {t.name: t for t in defaults.object_types()}

    def inherited(name):
        keys, cur = {}, by_name[name].parent
        while cur:
            keys.update({a["key"]: cur for a in by_name[cur].attributes})
            cur = by_name[cur].parent
        return keys
    for t in by_name.values():
        clash = {a["key"]: inherited(t.name)[a["key"]] for a in t.attributes
                 if a["key"] in inherited(t.name) and (t.name, a["key"]) not in KNOWN_REDEFINITIONS}
        assert not clash, f"{t.name} redefines {clash}"


def test_the_core_is_domain_neutral():
    core = available()["core-facility"]
    impact = next(a for a in core.section("ticket_types")["base"]["attributes"] if a["key"] == "argus_impact")
    assert {o["id"] for o in impact["options"]} == {"service_down", "service_degraded", "no_impact", "safety", "unknown"}
    assert not core.section("object_types")
    objects = available()["core-objects"]
    item = next(t for t in objects.section("object_types")["types"] if t["name"] == "Item")
    crit = next(a for a in item["attributes"] if a["key"] == "argus_criticality")
    assert {o["id"] for o in crit["options"]} == {"safety", "mission_critical", "degrades_service", "non_critical"}


@pytest.mark.parametrize("pid", DOMAINS)
def test_each_domain_package_says_who_owns_it_and_that_it_establishes_no_compliance(pid):
    p = available()[pid]
    assert p.owner and "compliance" in p.description and "approv" in p.description
    s = p.summary()
    assert s["queries"] >= 2, "representative queries with fixtures"
    assert s["roles"] >= 1 and (s["workflows"] >= 1 or pid in ("optics-alignment",)) or s["workflows"] >= 1


# --------------------------------------------------------------------------- representative queries

CASES = [(p.id, q["id"]) for p, q in queries.shipped_queries()]


@pytest.mark.parametrize("package_id,query_id", CASES)
def test_each_representative_query_returns_what_its_package_says(package_id, query_id, spaces):
    p = available()[package_id]
    q = next(x for x in p.section("queries") if x["id"] == query_id)
    ws = spaces([package_id])
    db = SessionLocal()
    queries.load(db, ws, p, q["fixture"])
    db.commit()
    assert queries.run(db, ws, q) == q["expect"]
    db.close()


def test_a_restricted_record_is_left_out_of_a_query_for_someone_without_the_class(spaces):
    from app.services.visibility import Grants
    p = available()["tech-transfer"]
    q = next(x for x in p.section("queries") if x["id"] == "patents-of-a-family")
    ws = spaces(["tech-transfer"])
    db = SessionLocal()
    uids = queries.load(db, ws, p, q["fixture"])
    pat = db.get(Asset, uids["PAT-US"])
    pat.attributes = {**pat.attributes, "classification": "restricted:unpublished_invention"}
    db.commit()
    assert queries.run(db, ws, q, Grants()) == ["PAT-EP", "PAT-IT"]
    assert queries.run(db, ws, q, Grants({"unpublished_invention"})) == ["PAT-EP", "PAT-IT", "PAT-US"]
    db.close()


# --------------------------------------------------------------------------- what a workspace gets

def test_a_workspace_with_only_it_gets_no_technology_transfer_nor_beam(spaces):
    ws = spaces(["it"])
    db = SessionLocal()
    assert set(installer.installed(db, ws)) == {"core-facility", "core-objects", "core-records", "it"}
    names = _types(db, ws)
    tt = {t["name"] for t in available()["tech-transfer"].section("object_types")["types"]}
    assert not names & tt and "Beam Element" not in names and "Fire Extinguisher" not in names
    assert {"Computing Node", "Software License", "Contract", "Organization"} <= names
    caps = installer.capabilities(db, ws)["features"]
    assert caps["equipment"] and caps["map"] and not caps["beam_model"]
    assert db.scalar(select(Asset).where(Asset.workspace_id == ws)) is None
    db.close()


def test_a_workspace_with_only_technology_transfer_has_no_equipment_nor_map(spaces):
    ws = spaces(["tech-transfer"])
    db = SessionLocal()
    assert set(installer.installed(db, ws)) == {"core-facility", "core-records", "tech-transfer"}
    names = _types(db, ws)
    assert "Asset" not in names and "Item" not in names and "Location" not in names
    assert all(_descends(db, ws, n, "Record") for n in names)
    caps = installer.capabilities(db, ws)
    assert caps["features"] == {"tickets": True, "documents": True, "equipment": False, "records": True,
                                "map": False, "beam_model": False, "control_system": False, "type_catalogue": True}
    assert caps["map_layers"] == []
    impact = next(a for a in db.get(Schema, f"{ws}:argus-ticket").attributes if a["key"] == "argus_impact")
    assert "beam_down" not in {o["id"] for o in impact["options"]}
    assert {"Disclosure Evaluation", "Annuity Decision"} <= _kinds(db, ws, "tickets")
    db.close()


@pytest.mark.parametrize("domain", DOMAINS)
def test_each_domain_installs_with_just_what_it_stands_on(domain, spaces):
    ws = spaces([domain])
    db = SessionLocal()
    assert set(installer.installed(db, ws)) == set(defaults.closure(domain))
    expected = {t.name for t in defaults.object_types(domain)}
    assert _types(db, ws) == expected
    db.close()


def test_a_new_workspace_is_previewed_made_private_and_recorded_with_versions_and_checksums():
    db = SessionLocal()
    admin = User(id=str(uuid.uuid4()), email=f"dc-{secrets.token_hex(3)}@argus.test", name="admin", is_admin=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.expunge(admin)
    db.close()
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=admin)
    wid = f"dc-api-{secrets.token_hex(3)}"
    try:
        preview = client.post("/v1/packages/preview", json={"packages": ["tech-transfer"]})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert [s["package_id"] for s in body["steps"]] == ["core-facility", "core-records", "tech-transfer"]
        assert all(len(s["checksum"]) == 64 and s["action"] == "install" for s in body["steps"])
        made = next(s for s in body["steps"] if s["package_id"] == "tech-transfer")["result"]["created"]
        assert "Patent" in made
        db = SessionLocal()
        assert db.scalar(select(Workspace).where(Workspace.id.like("preview-%"))) is None, "nothing kept"
        db.close()
        r = client.post("/v1/workspaces", json={"name": "TT office", "id": wid, "packages": ["tech-transfer"]})
        assert r.status_code == 201, r.text
        db = SessionLocal()
        w = db.get(Workspace, wid)
        assert not w.is_global and not w.default_can_read and not w.default_can_read_tickets
        assert db.scalar(select(Asset).where(Asset.workspace_id == wid)) is None
        db.close()
        mine = client.get(f"/v1/workspaces/{wid}/packages").json()
        shipped = available()
        assert {(p["package_id"], p["version"], p["checksum"]) for p in mine["packages"]} == {
            (pid, shipped[pid].version, shipped[pid].checksum) for pid in ("core-facility", "core-records", "tech-transfer")}
        caps = client.get(f"/v1/workspaces/{wid}/capabilities").json()
        assert caps["features"]["map"] is False and caps["features"]["equipment"] is False
        templates = {t["id"]: t for t in client.get("/v1/access-reviews/templates",
                                                     headers={"X-Workspace-Id": wid}).json()}
        assert templates["argus-technology-transfer-officer"]["package"] == "tech-transfer"
        assert "argus-fire-safety-officer" not in templates, "only the roles of the packages it has"
        assert client.post("/v1/packages/preview", json={"packages": ["nowhere"]}).status_code == 422
    finally:
        app.dependency_overrides.pop(get_identity, None)
        db = SessionLocal()
        from app.ledger.audit import allow_purge
        allow_purge(db)
        w = db.get(Workspace, wid)
        if w is not None:
            db.delete(w)
        db.delete(db.get(User, admin.id))
        db.commit()
        db.close()


# --------------------------------------------------------------------------- behaviour packages declare

def test_a_package_workflow_governs_its_kinds_and_an_approval_needs_someone_who_may_approve(spaces):
    from app.services import workflows
    ws = spaces(["safety"])
    db = SessionLocal()
    kind = db.get(Schema, installer.kind_uid(ws, "ticket_types", "Permit to Work"))
    wf = workflows.workflow_for(db, ws, kind.uid)
    assert wf["name"] == "Permit to work" and wf["initial"] == "requested"
    assert workflows.workflow_for(db, ws, installer.kind_uid(ws, "ticket_types", "Radiation Work Permit"))["uid"] == wf["uid"]
    assert {a["key"] for a in kind.attributes} >= {"work_hazards", "valid_from", "valid_until", "precautions"}
    permit = Issue(uid=str(uuid.uuid4()), workspace_id=ws, title="Hot work in hall B", schema_uid=kind.uid,
                   state="requested", attributes={}, labels=[])
    db.add(permit)
    db.flush()
    workflows.transition(db, permit, "under_review", "requester")
    with pytest.raises(workflows.WorkflowError, match="approval"):
        workflows.transition(db, permit, "approved", "requester")
    workflows.transition(db, permit, "approved", "officer", may_approve=True)
    assert permit.state == "approved"
    # reinstalling does not replace a workflow the workspace has edited
    db.commit()
    from app.models.workflow import Workflow
    row = db.get(Workflow, wf["uid"])
    row.name = "Our permit flow"
    db.commit()
    installer.install(db, ws, ["safety"])
    db.commit()
    assert db.get(Workflow, wf["uid"]).name == "Our permit flow"
    db.close()


def test_code_validators_are_enforced_when_a_record_is_saved(spaces):
    from fastapi import HTTPException
    from app.services.attribute_validation import validate_attributes
    ws = spaces(["tech-transfer", "administration"])
    db = SessionLocal()
    patent = db.get(Schema, asset_types.type_uid(ws, "Patent"))
    with pytest.raises(HTTPException) as e:
        validate_attributes(db, patent, {"application_number": "not a number"}, ws, Asset)
    assert "patent" in str(e.value.detail).lower()
    validate_attributes(db, patent, {"application_number": "EP 25123456.7"}, ws, Asset)
    output = db.get(Schema, asset_types.type_uid(ws, "Research Output"))
    with pytest.raises(HTTPException):
        validate_attributes(db, output, {"author_orcids": ["0000-0002-1825-0098"]}, ws, Asset)   # bad check digit
    validate_attributes(db, output, {"author_orcids": ["0000-0002-1825-0097"], "doi": "10.1103/PhysRevLett.126.014801"},
                        ws, Asset)
    contract = db.get(Schema, asset_types.type_uid(ws, "Contract"))
    assert {"cig", "cup", "special_terms"} <= {a["key"] for a in contract.attributes}, "administration extends it"
    with pytest.raises(HTTPException):
        validate_attributes(db, contract, {"cig": "too-short"}, ws, Asset)
    db.close()


def test_a_typed_relation_is_refused_between_the_wrong_types(spaces):
    from app.packages import relations
    ws = spaces(["civil-access"])
    db = SessionLocal()
    door, zone, crane = (asset_types.type_uid(ws, n) for n in ("Door", "Access Zone", "Overhead Crane"))
    assert relations.check(db, "gives access to", door, zone) is None
    assert "the source is not one" in relations.check(db, "gives access to", crane, zone)
    assert relations.check(db, "located in", crane, zone) is None, "a verb no package declares: not checked here"
    from app.services.causal_model import classify
    assert classify("controls door").layer == "access" and classify("controls door").carries == "function"
    from app.ledger.registry import ENDPOINTS
    assert "Door" in ENDPOINTS["gives access to"][0][1]
    db.close()


def test_restricted_fields_and_classes_come_from_the_packages(spaces):
    from app.services.visibility import Grants, hidden_fields, restricted_classes
    classes = restricted_classes()
    assert {"costs", "unpublished_invention", "commercial_terms", "source_security", "physical_security",
            "license_keys"} <= set(classes)
    ws = spaces(["tech-transfer"])
    db = SessionLocal()
    from app.ledger import service
    lic = service.create_record(db, ws, "t", uid=str(uuid.uuid4()), key=f"{ws}-LIC", name="Licence",
                                schema_uid=asset_types.type_uid(ws, "License Agreement"), type_name="License Agreement",
                                attributes={"royalty_rate_pct": 3.5, "contract_value": 100000})
    db.commit()
    assert {"royalty_rate_pct", "contract_value"} <= hidden_fields(db, lic, Grants())
    assert hidden_fields(db, lic, Grants({"commercial_terms", "costs"})) == set()
    db.close()


def test_an_importer_declares_what_it_needs_and_a_package_only_names_importers_that_exist():
    from app.packages.importers import IMPORTERS
    for p in available().values():
        for i in p.section("imports") or []:
            assert i["importer"] in IMPORTERS
    assert IMPORTERS["glpi"]["requires"] == ["it-catalogue", "records", "tickets", "documents"]
    from app.services import epik8s_import, pbs_import
    assert epik8s_import.REQUIRES == ("accelerator-catalogue",) and pbs_import.REQUIRES == ("accelerator-catalogue",)


def test_a_locations_import_needs_an_object_catalogue(spaces):
    from app.packages.requirements import MissingPrerequisite
    from app.services.spatial import import_locations
    ws = spaces(["tech-transfer"])
    db = SessionLocal()
    with pytest.raises(MissingPrerequisite):
        import_locations(db, ws, [{"key": "X", "latitude": 1, "longitude": 2}], source_name="t", actor="t")
    db.close()


# --------------------------------------------------------------------------- compatibility

def _release(tmp_path, monkeypatch) -> Path:
    old = tmp_path / "release-1.35.25"
    shutil.copytree(RELEASE_1_35_25, old)
    monkeypatch.setenv("ARGUS_PACKAGES_DIR", str(old))
    loader.reload()
    return old


def _today(monkeypatch):
    monkeypatch.delenv("ARGUS_PACKAGES_DIR")
    loader.reload()


def test_an_accelerator_workspace_of_1_35_25_upgrades_with_nothing_lost(spaces, tmp_path, monkeypatch):
    _release(tmp_path, monkeypatch)
    ws = spaces(["accelerator"])
    db = SessionLocal()
    before = {s.uid: (s.name, s.parent_schema_uid) for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}
    pump = Asset(uid=str(uuid.uuid4()), workspace_id=ws, key=f"{ws}-IP1", name="Ion pump 1", type="Ion Pump",
                 schema_uid=asset_types.type_uid(ws, "Ion Pump"), attributes={"argus_criticality": "Beam-critical"})
    ticket = Issue(uid=str(uuid.uuid4()), workspace_id=ws, title="Gun vacuum", state="new", labels=[],
                   schema_uid=f"{ws}:argus-ticket:bug", attributes={"argus_impact": "Beam down"})
    db.add_all([pump, ticket])
    db.commit()
    _today(monkeypatch)

    preview = installer.plan(db, ws, ["accelerator"])
    db.rollback()
    steps = {s.package_id: s for s in preview.steps}
    for pid in ("core-facility", "core-objects", "it", "accelerator"):
        assert steps[pid].action == "upgrade" and steps[pid].result["needs_decision"] == [], pid
    for pid in ("core-records", "safety", "vacuum-cryo", "optics-alignment"):
        assert steps[pid].action == "install", pid
    moved = {c["subject"] for c in steps["accelerator"].result["changes"] if c["what"] == "moved"}
    assert {"Ion Pump", "Laser System", "Radiation Monitor"} <= moved
    kept = [c for c in steps["core-facility"].result["changes"] if c["what"] == "moved"]
    assert {c["element"] for c in kept} == {"argus_impact:beam_down", "argus_impact:beam_degraded",
                                           "argus_impact:no_beam_impact"}

    installer.install(db, ws, ["accelerator"], actor="tester")
    db.commit()
    after = {s.uid: (s.name, s.parent_schema_uid) for s in db.scalars(select(Schema).where(Schema.workspace_id == ws))}
    assert {u: v for u, v in after.items() if u in before} == before, "every type and kind where it was"
    base = db.get(Schema, f"{ws}:argus-ticket")
    impact = {o["id"] for a in base.attributes if a["key"] == "argus_impact" for o in a["options"]}
    assert {"beam_down", "beam_degraded", "no_beam_impact", "service_down"} <= impact
    item = db.get(Schema, asset_types.type_uid(ws, "Item"))
    crit = {o["id"] for a in item.attributes if a["key"] == "argus_criticality" for o in a["options"]}
    assert {"beam_critical", "degrades"} <= crit
    assert db.get(Asset, pump.uid).attributes["argus_criticality"] == "Beam-critical"
    assert db.get(Issue, ticket.uid).attributes["argus_impact"] == "Beam down"
    assert {"Fire Extinguisher", "Cryostat", "Laser Oscillator", "Contract"} <= _types(db, ws)
    assert installer.installed(db, ws)["accelerator"].version == available()["accelerator"].version
    db.close()


def test_a_workspace_without_the_accelerator_decides_about_the_beam_options_it_had(spaces, tmp_path, monkeypatch):
    _release(tmp_path, monkeypatch)
    ws = spaces(["it"])
    _today(monkeypatch)
    db = SessionLocal()
    preview = installer.plan(db, ws, ["it"])
    db.rollback()
    core = next(s for s in preview.steps if s.package_id == "core-facility")
    assert set(core.result["needs_decision"]) == {
        f"ticket_types/base/attributes/argus_impact/options/{o}/removed" for o in ("beam_down", "beam_degraded",
                                                                                 "no_beam_impact")}
    objects = next(s for s in preview.steps if s.package_id == "core-objects")
    assert set(objects.result["needs_decision"]) == {
        f"object_types/Item/attributes/argus_criticality/options/{o}/removed" for o in ("beam_critical", "degrades")}
    keep = {c: "keep" for s in preview.steps for c in s.result.get("needs_decision", [])}
    installer.install(db, ws, ["it"], decisions=keep, actor="tester")
    db.commit()
    base = db.get(Schema, f"{ws}:argus-ticket")
    impact = {o["id"] for a in base.attributes if a["key"] == "argus_impact" for o in a["options"]}
    assert {"beam_down", "service_down"} <= impact, "kept as the workspace had them, the neutral ones added"
    assert {"Software License", "Contract"} <= _types(db, ws)
    db.close()


def test_a_workspace_with_a_moved_type_is_not_taken_to_have_its_new_package(spaces):
    """Radiation Monitor was the accelerator's and is safety's now: one type does not make a package."""
    ws = spaces()
    db = SessionLocal()
    from app.routers.workspaces import seed_default_global_values, seed_default_ticket_types
    seed_default_global_values(db, ws)
    seed_default_ticket_types(db, ws)
    asset_types.ensure_asset_types(db, ws, specs=[s for s in asset_types.specs_of("core-objects")], only=None)
    db.flush()
    from app.packages import compile as c
    rm = next(t for t in c.object_types(available()["safety"], defaults.option_sets()) if t.name == "Radiation Monitor")
    db.add(Schema(uid=asset_types.type_uid(ws, rm.name), workspace_id=ws, name=rm.name, applies_to="objects",
                  parent_schema_uid=asset_types.type_uid(ws, "Asset"), attributes=list(rm.attributes)))
    db.commit()
    installer.detect_workspace(db, ws)
    db.commit()
    assert "safety" not in installer.installed(db, ws)
    db.close()
