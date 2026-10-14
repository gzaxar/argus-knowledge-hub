"""Records from a CSV or Excel file: the columns profiled, the type found or created under the workspace's
types (with every default property), each column placed by rules or the AI, every row checked before
anything is written, and the import through the ledger, row by row."""
import io
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.db import SessionLocal
from app.main import app
from app.models.asset import Asset
from app.models.import_job import ImportJob
from app.models.schema import Schema
from app.models.workspace import Workspace
from app.packages.install import install
from app.services import asset_types
from app.services import spreadsheet_import as svc
from app.services.attribute_validation import effective_attributes
from tests.test_ledger_transition import token

client = TestClient(app)

CSV = (
    "﻿Nome;Matricola;Produttore;Ubicazione;Potenza (kW);Data installazione;Stato;Classe;Note vuote\n"
    "Chiller 1;SN-001;Carrier;Hall A;12,5;03/02/2021;In service;A;\n"
    "Chiller 2;SN-002;Carrier;Hall A;15;04/02/2021;In service;B;\n"
    "Chiller 3;SN-003;Daikin;Hall B;9,75;05/02/2021;Standby;A;\n"
    "Chiller 4;SN-004;Daikin;Hall A;11;06/02/2021;In service;B;\n"
)


@pytest.fixture()
def world():
    t = secrets.token_hex(3)
    ws = f"sheet-{t}"
    db = SessionLocal()
    db.add(Workspace(id=ws, name=ws))
    db.flush()
    install(db, ws, ["core-objects"])
    location = asset_types.type_uid(ws, "Location")
    for name in ("Hall A", "Hall B"):
        db.add(Asset(uid=str(uuid.uuid4()), workspace_id=ws, schema_uid=location, key=f"{t}-{name[-1]}",
                     name=name, type="Location", attributes={}, record_status="Active"))
    # A workspace type the rows of a register of extinguishers fit.
    db.add(Schema(uid=f"{ws}:extinguisher", workspace_id=ws, name="Fire Extinguisher", applies_to="objects",
                  is_concrete=True, parent_schema_uid=asset_types.type_uid(ws, "Asset"), attributes=[
                      {"id": "a", "key": "agent", "name": "Agent", "type": "enumeration",
                       "options": [{"id": "co2", "value": "CO2"}, {"id": "powder", "value": "Powder"}]},
                      {"id": "c", "key": "capacity_kg", "name": "Capacity kg", "type": "float"},
                      {"id": "s", "key": "site_notes", "name": "Site notes", "type": "string",
                       "restricted": "site_security"}]))
    headers = token(db, ws)
    db.commit()
    db.close()
    yield {"ws": ws, "t": t, "headers": headers}
    db = SessionLocal()
    from app.ledger.audit import allow_purge
    allow_purge(db)
    db.delete(db.get(Workspace, ws))
    db.commit()
    db.close()


def _post(w, path, content, name="impianti_frigo.csv", **form):
    data = {k: (json.dumps(v) if isinstance(v, dict) else str(v).lower() if isinstance(v, bool) else v)
            for k, v in form.items()}
    return client.post(f"/v1/spreadsheet-imports/{path}", headers=w["headers"],
                       files={"file": (name, content, "application/octet-stream")}, data=data)


def _plan(w, content=CSV.encode(), **form):
    resp = _post(w, "analyse", content, use_ai=False, **form)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _xlsx(sheet: str, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- reading

def test_a_csv_is_read_whatever_its_delimiter_encoding_and_number_format():
    table = svc.read_table("impianti_frigo.csv", CSV.encode())
    assert table.columns[0] == "Nome" and len(table.rows) == 4
    kinds = {p["column"]: p["kind"] for p in svc.profile(table)}
    assert kinds["Potenza (kW)"] == "float" and kinds["Data installazione"] == "date"
    assert kinds["Classe"] == "enumeration" and kinds["Nome"] == "string"
    latin = svc.read_table("x.csv", "Name,Città\nPump,Forlì\n".encode("cp1252"))
    assert latin.rows == [{"Name": "Pump", "Città": "Forlì"}]


def test_an_excel_sheet_is_read_from_its_first_named_row_and_old_xls_is_refused():
    content = _xlsx("Fire extinguishers", [[], ["Name", "Agent", None, "Capacity kg"], ["E-1", "CO2", None, 5],
                                           ["E-2", "powder", None, 6.5]])
    table = svc.read_table("register.xlsx", content)
    assert table.sheet == "Fire extinguishers" and table.title == "Fire extinguishers"
    assert table.columns == ["Name", "Agent", "Column 3", "Capacity kg"] and table.rows[1]["Capacity kg"] == 6.5
    with pytest.raises(svc.SpreadsheetError, match="xlsx or .csv"):
        svc.read_table("old.xls", b"\xd0\xcf\x11\xe0 not a zip")
    with pytest.raises(svc.SpreadsheetError, match="no sheet named"):
        svc.read_table("register.xlsx", content, "Elsewhere")


# --------------------------------------------------------------------------- the plan

def test_rows_nothing_fits_become_a_new_type_under_asset_with_the_columns_placed(world):
    out = _plan(world)
    target = out["plan"]["target"]
    assert target["mode"] == "new" and target["name"] == "Impianti frigo"
    assert target["parent_uid"] == asset_types.type_uid(world["ws"], "Asset")
    where = {c["column"]: c["target"] for c in out["plan"]["columns"]}
    assert where["Nome"] == svc.NAME and where["Matricola"] == "serial" and where["Produttore"] == "manufacturer"
    assert where["Ubicazione"] == "argus_location" and where["Stato"] == "argus_lifecycle"
    assert where["Data installazione"] == "installed_on" and where["Note vuote"] == svc.DROP
    new = {c["column"]: c["new"] for c in out["plan"]["columns"] if c["target"] == svc.NEW}
    assert new["Potenza (kW)"]["type"] == "float" and new["Potenza (kW)"]["key"] == "potenza_kw"
    assert new["Classe"] == {"key": "classe", "name": "Classe", "type": "enumeration", "options": ["A", "B"]}
    # The defaults a new type gets: every property of the types above it.
    assert {"description", "argus_lifecycle", "argus_owner", "serial", "argus_location"} <= {
        p["key"] for p in out["properties"]}


def test_rows_that_fit_an_existing_type_go_to_it(world):
    content = _xlsx("Fire extinguishers", [["Name", "Agent", "Capacity kg", "Serial"], ["E-1", "CO2", 5, "X1"],
                                           ["E-2", "Powder", 6, "X2"]])
    out = _plan(world, content, name="register.xlsx")
    assert out["candidates"][0]["name"] == "Fire Extinguisher"
    assert out["plan"]["target"] == {**out["plan"]["target"], "mode": "existing",
                                     "schema_uid": f"{world['ws']}:extinguisher"}
    where = {c["column"]: c["target"] for c in out["plan"]["columns"]}
    assert where == {"Name": svc.NAME, "Agent": "agent", "Capacity kg": "capacity_kg", "Serial": "serial"}


def test_the_ai_places_what_the_rules_cannot_and_nothing_it_invents(world, monkeypatch):
    monkeypatch.setattr(svc, "_ai_endpoint", lambda db, ws: (_endpoint(), None, None))
    answer = {"type": {"existing": None, "new_name": "Chiller", "parent": "Asset", "confidence": 0.9,
                       "reason": "cooling units"},
              "columns": [{"column": "Potenza (kW)", "target": "__new__", "type": "float", "confidence": 0.9},
                          {"column": "Classe", "target": "argus_criticality", "confidence": 0.7},
                          {"column": "Note vuote", "target": "made_up_property", "confidence": 0.9}]}
    seen = {}

    def complete(_ep, system, user, **_):
        seen["user"] = user
        return json.dumps(answer)
    monkeypatch.setattr("app.services.llm.complete", complete)
    resp = _post(world, "analyse", CSV.encode(), use_ai=True)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["ai"]["used"] is True and out["plan"]["target"]["name"] == "Chiller"
    assert out["plan"]["target"]["source"] == "ai"
    where = {c["column"]: c for c in out["plan"]["columns"]}
    assert where["Classe"]["target"] == "argus_criticality" and where["Classe"]["source"] == "ai"
    assert where["Note vuote"]["target"] == svc.DROP                     # an invented property is not taken
    assert where["Matricola"]["target"] == "serial" and where["Matricola"]["source"] == "rule"
    assert "<spreadsheet>" in seen["user"] and "Chiller 1" in seen["user"]


def _endpoint():
    from app.services.llm import Endpoint
    return Endpoint("https://ai.example/v1", "m-1")


# --------------------------------------------------------------------------- preview and import

def _with_new_type(world):
    plan = _plan(world)["plan"]
    plan["target"]["name"] = f"Chiller {world['t']}"
    return plan


def test_every_row_is_checked_before_anything_is_written(world):
    bad = CSV.replace("Hall B", "Hall Z").replace("Standby", "Sleeping").replace("15;", "fifteen;")
    plan = _with_new_type(world)
    resp = _post(world, "preview", bad.encode(), plan=plan)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["counts"] == {"create": 2, "update": 0, "unchanged": 0, "error": 2}
    problems = {r["row"]: r["problems"] for r in out["rows"] if r["problems"]}
    assert any("Hall Z" in p for p in problems[4]) and any("Sleeping" in p for p in problems[4])
    assert any("fifteen" in p for p in problems[3])
    assert out["type"]["new_properties"][0]["key"] == "potenza_kw"
    db = SessionLocal()
    assert db.query(Schema).filter_by(workspace_id=world["ws"], name=plan["target"]["name"]).count() == 0
    db.close()


def test_the_import_creates_the_type_and_the_records_through_the_ledger_and_reimporting_updates(world):
    plan = _with_new_type(world)
    resp = _post(world, "run", CSV.encode(), plan=plan)
    assert resp.status_code == 202, resp.text
    job_uid, type_uid = resp.json()["job_uid"], resp.json()["type_uid"]
    db = SessionLocal()
    job = db.get(ImportJob, job_uid)
    assert job.status == "succeeded", job.error
    assert job.counts["created"] == 4 and job.counts["failed"] == 0
    schema = db.get(Schema, type_uid)
    assert schema.parent_schema_uid == asset_types.type_uid(world["ws"], "Asset") and schema.is_concrete
    assert {a["key"] for a in schema.attributes} == {"potenza_kw", "classe"}
    assert {"argus_lifecycle", "serial", "argus_location"} <= {a["key"] for a in effective_attributes(db, schema)}
    rows = {a.name: a for a in db.query(Asset).filter_by(schema_uid=type_uid)}
    one = rows["Chiller 1"]
    assert one.attributes["serial"] == "SN-001" and one.attributes["potenza_kw"] == 12.5
    assert one.attributes["installed_on"] == "2021-02-03" and one.attributes["argus_lifecycle"] == "In service"
    hall_a = db.query(Asset).filter_by(workspace_id=world["ws"], name="Hall A").one()
    assert one.attributes["argus_location"] == hall_a.uid and one.attributes["classe"] == "A"
    assert one.attributes["argus_source_ref"] == "impianti_frigo.csv › row 2"
    from app.models.ledger import RecordEvent
    assert db.query(RecordEvent).filter_by(uid=one.uid, kind="created").count() == 1
    keys = {a.name: a.key for a in rows.values()}
    db.close()

    # The same sheet with the keys it was given, one value changed: an update, three unchanged.
    again = "Codice;" + CSV.splitlines()[0].lstrip("﻿") + "\n" + "\n".join(
        f"{keys[line.split(';')[0]]};{line}" for line in CSV.splitlines()[1:])
    again = again.replace("SN-003", "SN-003b")
    plan2 = _plan(world, again.encode(), target={"mode": "existing", "schema_uid": type_uid})["plan"]
    assert {c["column"]: c["target"] for c in plan2["columns"]}["Codice"] == svc.KEY
    preview = _post(world, "preview", again.encode(), plan=plan2).json()
    assert preview["counts"] == {"create": 0, "update": 1, "unchanged": 3, "error": 0}
    resp = _post(world, "run", again.encode(), plan=plan2)
    db = SessionLocal()
    job = db.get(ImportJob, resp.json()["job_uid"])
    assert (job.counts["updated"], job.counts["unchanged"], job.counts["created"]) == (1, 3, 0)
    assert db.query(Asset).filter_by(schema_uid=type_uid, name="Chiller 3").one().attributes["serial"] == "SN-003b"
    db.close()


def test_a_plan_that_does_not_hold_is_refused(world):
    plan = _with_new_type(world)
    plan["columns"][1]["target"] = "no_such_property"
    resp = _post(world, "preview", CSV.encode(), plan=plan)
    assert resp.status_code == 422 and "does not have" in resp.json()["detail"]["error"]
    plan = _with_new_type(world)
    plan["target"]["name"] = "Fire Extinguisher"
    assert "already exists" in _post(world, "preview", CSV.encode(), plan=plan).json()["detail"]["error"]
    plan = _with_new_type(world)
    for c in plan["columns"]:
        if c["target"] == svc.NAME:
            c["target"] = svc.DROP
    assert "name" in _post(world, "preview", CSV.encode(), plan=plan).json()["detail"]["error"]
    resp = _post(world, "run", CSV.encode(), plan=_with_new_type(world), expect_digest="0" * 64)
    assert resp.status_code == 409


def test_a_column_cannot_be_written_to_a_field_its_importer_may_not_see(world):
    content = _xlsx("Fire extinguishers", [["Name", "Agent", "Where"], ["E-1", "CO2", "behind door 3"]])
    plan = {"target": {"mode": "existing", "schema_uid": f"{world['ws']}:extinguisher"}, "update_existing": True,
            "columns": [{"column": "Name", "target": svc.NAME}, {"column": "Agent", "target": "agent"},
                        {"column": "Where", "target": "site_notes"}]}
    db = SessionLocal()
    table = svc.read_table("r.xlsx", content)
    from app.services.visibility import Grants
    with pytest.raises(svc.SpreadsheetError, match="restricted class"):
        svc.plan_rows(db, world["ws"], table, plan, may_update=True, grants=Grants(()))
    assert svc.plan_rows(db, world["ws"], table, plan, may_update=True,
                         grants=Grants(("site_security",)))["counts"]["create"] == 1
    db.close()


def test_a_type_named_as_the_sheet_is_chosen_even_when_few_columns_say_so(world):
    """A register called "Fire extinguishers" with only generic columns is still a list of fire extinguishers."""
    content = _xlsx("Fire extinguishers", [["Name", "Serial", "Location"], ["E-1", "X1", "Hall A"]])
    out = _plan(world, content, name="register.xlsx")
    assert out["plan"]["target"]["mode"] == "existing"
    assert out["plan"]["target"]["schema_uid"] == f"{world['ws']}:extinguisher"
