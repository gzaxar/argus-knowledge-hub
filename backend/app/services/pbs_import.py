"""Product-breakdown (PBS) workbook import.

A control configuration says how software reaches hardware that exists. A PBS
workbook says what will be built, who builds it, what it costs and what the
building has to supply — the same components, from the other end of their
life. This reads the second kind into the object catalogue
(services/asset_types.py) so that when the first arrives it can attach to
objects that are already there instead of making a second copy.

One component row becomes one object of the type its component code names,
plus — only where the row has something to say — a Utility Requirement and a
Procurement Record. The workbook's legend sheets become Work Packages,
Sections and Areas; its MODULES column, which carries a station and a module
in one label, becomes Machine Modules and RF Stations with `composed of`
edges.

The workbook is a document people are still filling in, and it shows: a flow
rate of "4,2  (l/m oppure l/h)????????", a column headed "min-max" that
holds one number, a column headed "phases" that holds 129. None of that is
coerced. A value that is not what its column says is reported with its cell
and kept as the words it was written in, on the object, rather than turned
into a number somebody then trusts.

Nothing is invented where a cell is empty, and nothing a person has since
added to an object is overwritten: a re-read updates what the workbook says
and leaves the rest.
"""
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset, Relation
from app.services.asset_types import catalogue_of, resolve_type_uids

# The packages a workspace must have before a PBS import (their `provides`).
REQUIRES = ("accelerator-catalogue",)
from app.services.relations import rebuild_asset_relations

SOURCE_LABEL = "PBS workbook"
MAX_WARNINGS = 200

# The Engineered Item written when a component code is not in the table below:
# honest about being unclassified, rather than a guess at a type.
UNCLASSIFIED = "Engineered Item"

# COMPONENT ID -> the catalogue type. The codes are the workbook's own (the
# SYSTEM ZONE sheet lists them); a structure the beam passes through is a
# functional object with an s-position, a coupler in the waveguide feeding it
# is a box with a serial number and no place in the lattice.
TYPE_BY_COMPONENT = {
    "RFG": "RF Gun", "SB3": "Accelerating Structure", "SB1.5": "Accelerating Structure",
    "XBD": "Accelerating Structure", "XLN": "Accelerating Structure",
    "MOD": "Modulator", "PCMP": "RF Pulse Compressor", "HYB": "RF Hybrid",
    "WIN": "RF Window", "ATT": "RF Attenuator", "PHS": "RF Phase Shifter",
    "MCV": "RF Mode Converter", "ISL": "RF Isolator", "BDC": "Directional Coupler",
    "RFL": "RF Load", "LOAD": "RF Load", "WGS": "Waveguide Section",
}

DESIGN_STATUS = {"S": "Study", "D": "Defined", "A": "Approved"}

# Header (upper-cased, whitespace collapsed) prefix -> where it goes.
#   where: name | component | utility | procurement
# `exact` matters where a short header is the start of longer ones.
COLUMNS = [
    # (prefix, exact, where, key, kind)
    ("DESCRIPTION", False, "name", "name", "str"),
    ("ID", True, "component", "sequence_index", "int"),
    ("COMPONENT ID", False, "component", "component_id", "str"),
    ("WBS CODE", False, "component", "wbs_code", "str"),
    ("AREA/ZONE", False, "component", "pbs_area", "str"),
    ("SYSTEM", False, "component", "pbs_system", "str"),
    ("FAMILY", False, "component", "pbs_family", "str"),
    ("TYPE", True, "component", "pbs_type", "str"),
    ("SEQUENTIAL", False, "component", "pbs_sequential", "seq"),
    ("PBS-CODE", False, "component", "pbs_code", "str"),
    ("MODULES", False, "component", "modules", "modules"),
    ("STATUS", False, "component", "design_status", "status"),
    ("NUM. OF UNITS", False, "component", "unit_count", "int"),
    ("COMMENTS", False, "component", "description", "str"),
    ("UNIT COST", False, "procurement", "unit_cost_eur", "float"),
    ("TOTAL COST", False, "procurement", "total_cost_eur", "float"),
    ("TO YEAR", False, "procurement", "target_year", "int"),
    ("TO SEMESTER", False, "procurement", "target_semester", ("H1", "H2")),
    ("PROCUREMENT", False, "procurement", "procurement_route", "str"),
    ("PRODUCTION TIME", False, "procurement", "production_time_months", "float"),
    ("DELIVERY TIME", False, "procurement", "delivery_time_months", "float"),
    ("SUPPLIER", False, "procurement", "supplier", "str"),
    ("RUP", False, "procurement", "rup_as_written", "note"),
    ("FUNDING LINE", False, "procurement", "funding_line", "str"),
    ("CIG", False, "procurement", "cig", "str"),
    ("ELECTRICAL PHASES", False, "utility", "electrical_phases", ("3P+N", "1P+N")),
    ("UNDER UPS", False, "utility", "under_ups", "bool"),
    ("NOMINAL CURRENT", False, "utility", "nominal_current_a", "float"),
    ("MAX CURRENT", False, "utility", "max_inrush_current_a", "float"),
    ("NOMINAL ELECTRICAL", False, "utility", "nominal_power_kva", "float"),
    ("EXPECTED ELETTRICAL ACTIVE", False, "utility", "active_power_kw", "float"),
    ("COS(PHI)", False, "utility", "cos_phi", "float"),
    ("RACK UNITS", False, "utility", "rack_units", "int"),
    ("CONNECTIVITY", False, "utility", "connectivity", "multi"),
    ("HEAT DISSIPATION IN AIR", False, "utility", "heat_in_air_kw", "float"),
    ("NOMINAL HEAT DISSIPATION IN WATER", False, "utility", "heat_in_water_nominal_kw", "float"),
    ("EXPECTED MIN HEAT DISSIPATION IN WATER", False, "utility", "heat_in_water_min_kw", "float"),
    ("WATER TEMPERATURE INPUT NOMINAL", False, "utility", "water_temp_in_c", "float"),
    ("WATER TEMPERATURE SETPOINT", False, "utility", "water_temp_setpoint", "setpoint"),
    ("WATER TEMPERATURE STABILITY", False, "utility", "water_temp_stability_c", "float"),
    ("WATER FLOW RATE", False, "utility", "water_flow_l_min", "float"),
    ("WATER NOMINAL PRESSURE", False, "utility", "water_pressure_in_bar", "float"),
    ("WATER PRESSURE DROP", False, "utility", "water_pressure_drop_bar", "float"),
    ("WATER MAX PRESSURE", False, "utility", "water_pressure_max_bar", "float"),
    ("WATER ΔT", False, "utility", "water_delta_t_c", "float"),
    ("MAX ACCEPTABLE TEMPERATURE", False, "utility", "water_max_acceptable_temp_c", "float"),
    ("AIR TEMPERATURE NOMINAL", False, "utility", "air_temp_nominal_c", "float"),
    ("AIR TEMPERATURE STABILITY", False, "utility", "air_temp_stability_c", "float"),
    ("RELATIVE HUMIDITY", False, "utility", "relative_humidity_pct", "float"),
    ("RH STABILITY", False, "utility", "rh_stability_pct", "float"),
    ("COMPRESSED AIR PRESSURE NOMINAL", False, "utility", "compressed_air_nominal_bar", "float"),
    ("COMPRESSED AIR PRESSURE MAX", False, "utility", "compressed_air_max_bar", "float"),
    ("COMPRESSED AIR PRESSURE MIN", False, "utility", "compressed_air_min_bar", "float"),
    ("COMPRESSED AIR PRESSURE FLOW", False, "utility", "compressed_air_flow_l_min", "float"),
    ("OTHER GASES TYPE", False, "utility", "gas_type", "str"),
    ("OTHER GASES QUANTITY", False, "utility", "gas_quantity_m3_h", "float"),
]
# A spacer the workbook's authors left, not a quantity.
IGNORED_HEADERS = ("DO NOT COMPILE",)

NUMBER = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(.*?)\s*$", re.S)
MODULE_CODE = re.compile(r"\b([A-Z]{2,4})-LA-?(\d{3})(?:/(\d{3}))?\b")
STATION = re.compile(r"\b([A-Z]+-BAND STATION(?: \d+)?)\b")


@dataclass
class Component:
    sheet: str
    row: int
    name: str = ""
    component: dict = field(default_factory=dict)
    utility: dict = field(default_factory=dict)
    procurement: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)          # as written, for the utility record
    station: Optional[str] = None
    modules: list = field(default_factory=list)


@dataclass
class Workbook:
    components: list = field(default_factory=list)
    work_packages: dict = field(default_factory=dict)  # WP-04 -> description
    zones: dict = field(default_factory=dict)          # INJ -> Injector
    areas: dict = field(default_factory=dict)          # MHX3 -> Modulator Hall X-Band 3
    warnings: list = field(default_factory=list)


@dataclass
class PbsResult:
    counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    seeded: list = field(default_factory=list)


def _norm(header: Any) -> str:
    return " ".join(str(header).split()).upper() if header is not None else ""


def _text(cell: Any) -> Optional[str]:
    if cell is None:
        return None
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    text = str(cell).strip()
    return text or None


# --- reading ------------------------------------------------------------------

class _Reader:
    def __init__(self) -> None:
        self.wb = Workbook()

    def warn(self, message: str) -> None:
        if len(self.wb.warnings) < MAX_WARNINGS:
            self.wb.warnings.append(message)

    def number(self, cell, where: str, header: str) -> tuple:
        """(value, as-written) — as-written only when the cell was not just a number."""
        if isinstance(cell.value, bool):
            return None, str(cell.value)
        if isinstance(cell.value, (int, float)):
            return float(cell.value), None
        raw = _text(cell.value)
        m = NUMBER.match(raw)
        if not m:
            self.warn(f"{where}: {header} is not a number — kept as written: {raw!r}")
            return None, raw
        value = float(m.group(1).replace(",", "."))
        if re.match(r"^[-–/]\s*\d", m.group(2)):
            # "50-88" is a range. Reading its first number would put a value in
            # the record that the cell never said.
            self.warn(f"{where}: {header} is a range, not a number — kept as written: {raw!r}")
            return None, raw
        if m.group(2):
            self.warn(f"{where}: {header} is more than a number — read {value:g}, "
                      f"kept as written: {raw!r}")
            return value, raw
        return value, None

    def read_matrix(self, ws) -> None:
        rows = ws.iter_rows()
        header = next(rows, None)
        if header is None:
            return
        norm = [_norm(c.value) for c in header]
        plan = {}     # column index -> (where, key, kind, header text)
        for prefix, exact, where, key, kind in COLUMNS:
            for i, h in enumerate(norm):
                if i in plan or not h:
                    continue
                if (h == prefix) if exact else h.startswith(prefix):
                    plan[i] = (where, key, kind, str(header[i].value).split("\n")[0].strip())
                    break
        for i, h in enumerate(norm):
            if h and i not in plan and not h.startswith(IGNORED_HEADERS):
                self.warn(f"{ws.title}: column {header[i].coordinate} “{h[:50]}” is not imported")

        code_col = next((i for i, v in plan.items() if v[1] == "pbs_code"), None)
        if code_col is None:
            return
        for cells in rows:
            if len(cells) <= code_col or not _text(cells[code_col].value):
                continue
            comp = Component(sheet=ws.title, row=cells[code_col].row)
            for i, (where, key, kind, label) in plan.items():
                if i >= len(cells) or cells[i].value in (None, ""):
                    continue
                self.cell(comp, cells[i], where, key, kind, label)
            self.wb.components.append(comp)

    def cell(self, comp: Component, cell, where: str, key: str, kind, label: str) -> None:
        at = f"{comp.sheet}!{cell.coordinate}"
        target = {"component": comp.component, "utility": comp.utility,
                  "procurement": comp.procurement, "name": comp.component}[where]
        if kind == "str":
            target[key] = _text(cell.value)
        elif kind == "seq":
            v = cell.value
            target[key] = f"{int(v):03d}" if isinstance(v, (int, float)) else _text(v)
        elif kind == "int":
            v, raw = self.number(cell, at, label)
            if v is not None:
                target[key] = int(round(v))
        elif kind in ("float", "setpoint"):
            self.float_cell(comp, cell, where, key, kind, label, at, target)
        elif kind == "bool":
            text = (_text(cell.value) or "").upper()
            if text in ("YES", "Y", "SI", "SÌ", "TRUE", "1"):
                target[key] = True
            elif text in ("NO", "N", "FALSE", "0"):
                target[key] = False
            else:
                self.warn(f"{at}: {label} is not Yes or No: {text!r}")
                comp.notes.append(f"{label} as written: {text!r}")
        elif kind == "status":
            code = (_text(cell.value) or "").upper()
            if code in DESIGN_STATUS:
                target[key] = DESIGN_STATUS[code]
            else:
                self.warn(f"{at}: status {code!r} is not S, D or A")
        elif kind == "modules":
            comp.station, comp.modules = parse_modules(_text(cell.value))
        elif kind == "multi":
            target[key] = [p.strip() for p in re.split(r"[,;/]", _text(cell.value) or "") if p.strip()]
        elif kind == "note":
            comp.notes.append(f"{label} as written: {_text(cell.value)!r}")
        elif isinstance(kind, tuple):
            text = _text(cell.value)
            match = next((o for o in kind if o.upper() == (text or "").upper()), None)
            if match:
                target[key] = match
            else:
                self.warn(f"{at}: {label} is {text!r}, not one of {', '.join(kind)} — kept as written")
                comp.notes.append(f"{label} as written: {text!r}")

    def float_cell(self, comp, cell, where, key, kind, label, at, target) -> None:
        if kind == "setpoint":
            raw = _text(cell.value) or ""
            span = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*[-–/]\s*([-+]?\d+(?:[.,]\d+)?)\s*$", raw)
            if span:
                lo, hi = (float(g.replace(",", ".")) for g in span.groups())
                target["water_temp_setpoint_min_c"], target["water_temp_setpoint_max_c"] = lo, hi
                return
            # The column is headed "min-max"; one number is a setpoint, not a range.
            v, extra = self.number(cell, at, label)
            if v is not None:
                target["water_temp_setpoint_c"] = v
            if extra:
                comp.notes.append(f"{label} as written: {extra!r}")
            return
        v, extra = self.number(cell, at, label)
        if v is not None:
            target[key] = v
        if extra:
            comp.notes.append(f"{label} as written: {extra!r}")

    def read_legends(self, wb) -> None:
        def pairs(ws):
            for row in ws.iter_rows(values_only=True):
                if row and row[0] is not None and len(row) > 1:
                    yield _text(row[0]), _text(row[1])
        if "WBS CODE" in wb.sheetnames:
            for code, desc in pairs(wb["WBS CODE"]):
                if code and re.match(r"^WP-\d+$", code):
                    self.wb.work_packages[code] = desc
        if "SYSTEM ZONE" in wb.sheetnames:
            for code, desc in pairs(wb["SYSTEM ZONE"]):
                if code == "ID_COMPONENT":
                    break                       # what follows are component codes
                if code and code != "SYSTEM ZONE":
                    self.wb.zones[code] = desc
        if "AREA" in wb.sheetnames:
            for code, desc in pairs(wb["AREA"]):
                if code and code != "MODULO":
                    self.wb.areas[code] = desc


def parse_modules(text: Optional[str]) -> tuple:
    """`X-BAND STATION 3 LEL-LA-002` -> ("X-BAND STATION 3", ["LEL-LA-002"]).

    The workbook puts a station and a module in one cell. `INJ-LA002/003` is
    two modules, and a module with no station is just a module.
    """
    if not text:
        return None, []
    upper = text.upper()
    station = STATION.search(upper)
    modules = []
    for m in MODULE_CODE.finditer(upper):
        modules.append(f"{m.group(1)}-LA-{m.group(2)}")
        if m.group(3):
            modules.append(f"{m.group(1)}-LA-{m.group(3)}")
    return (station.group(1) if station else None), modules


def read_workbook(source) -> Workbook:
    """Read every matrix sheet (one with a PBS-CODE column) and the legends."""
    wb = openpyxl.load_workbook(source, data_only=True)
    reader = _Reader()
    reader.read_legends(wb)
    for ws in wb.worksheets:
        first = next(ws.iter_rows(max_row=1, values_only=True), ())
        if any(_norm(h) == "PBS-CODE" for h in first):
            reader.read_matrix(ws)
    return reader.wb


# --- writing ------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class _Writer:
    def __init__(self, db: Session, workspace_id: str, facility: str, source_ref: str,
                 uids: dict) -> None:
        self.db, self.ws, self.facility, self.ref, self.types = db, workspace_id, facility, source_ref, uids
        self.touched: dict[str, Asset] = {}
        self.counts: dict[str, int] = {}
        self.warnings: list = []

    def count(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def upsert(self, type_name: str, key: str, name: str, attributes: dict,
               keep: tuple = ()) -> Asset:
        uid = "pbs-" + hashlib.sha1(f"{self.ws}:{key}".encode()).hexdigest()[:24]
        asset = self.db.get(Asset, uid)
        if asset is None:
            clash = self.db.scalar(select(Asset).where(Asset.key == key))
            if clash is not None:
                raise ValueError(
                    f"“{key}” already exists in workspace “{clash.workspace_id}”. Object keys "
                    f"are unique across the installation; give this import a facility code of "
                    f"its own.")
        stamped = {k: v for k, v in {
            **attributes, "argus_facility": self.facility, "argus_source": SOURCE_LABEL,
            "argus_source_ref": self.ref}.items() if v not in (None, "", [])}
        if asset is None:
            asset = Asset(uid=uid, workspace_id=self.ws, schema_uid=self.types[type_name],
                          key=key, name=name, type=type_name, attributes=stamped)
            self.db.add(asset)
        else:
            merged = {**(asset.attributes or {}), **stamped}
            for k in keep:                # a later decision by a person outranks the workbook
                if k in (asset.attributes or {}):
                    merged[k] = asset.attributes[k]
            asset.name, asset.type, asset.schema_uid = name, type_name, self.types[type_name]
            asset.attributes = merged
        self.db.flush()
        self.touched[asset.uid] = asset
        return asset

    def relate(self, source: Asset, target: Asset, relation_type: str) -> None:
        if source.uid == target.uid:
            return
        exists = self.db.scalar(select(Relation).where(
            Relation.workspace_id == self.ws, Relation.from_asset_uid == source.uid,
            Relation.to_asset_uid == target.uid, Relation.relation_type == relation_type))
        if exists is None:
            self.db.add(Relation(workspace_id=self.ws, from_asset_uid=source.uid,
                                 to_asset_uid=target.uid, relation_type=relation_type))
            self.count("relations")

    def warn(self, message: str) -> None:
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)


def import_pbs(db: Session, workspace_id: str, book: Workbook, facility: str,
               source_ref: str, dry_run: bool = False,
               catalogue_workspace_id: Optional[str] = None) -> PbsResult:
    """Write a read workbook into a workspace. `facility` prefixes every key,
    because object keys are unique across the whole installation.

    The workspace must have the accelerator catalogue (package `accelerator`), installed beforehand: the
    import writes objects of its types and never installs them. With `catalogue_workspace_id` the shared
    types are used from that catalogue; without it, from the one the workspace hangs from."""
    # The accelerator catalogue is a prerequisite, installed beforehand: an import never installs it.
    from app.packages.requirements import require
    require(db, workspace_id, *REQUIRES)
    catalogue_workspace_id = catalogue_workspace_id or catalogue_of(db, workspace_id)
    w = _Writer(db, workspace_id, facility, source_ref, resolve_type_uids(db, workspace_id, catalogue_workspace_id))
    w.warnings.extend(book.warnings)

    packages = {c: w.upsert("Work Package", f"{facility}:WP:{c}", f"{c} {d or ''}".strip(),
                            {"wbs_code": c, "description": d}) for c, d in book.work_packages.items()}
    sections = {c: w.upsert("Section", f"{facility}:SEC:{c}", d or c,
                            {"zone": [c], "pbs_area": c}) for c, d in book.zones.items()}
    areas = {c: w.upsert("Area", f"{facility}:AREA:{c}", d or c, {"zone": c, "description": d})
             for c, d in book.areas.items()}
    for kind, made in (("work_packages", packages), ("sections", sections), ("areas", areas)):
        w.counts[kind] = len(made)

    modules, stations = {}, {}

    def module(code: str) -> Asset:
        if code not in modules:
            kind = "Accelerating" if code.split("-")[1:2] == ["LA"] else "Other"
            modules[code] = w.upsert("Machine Module", f"{facility}:MOD:{code}", code,
                                     {"module_code": code, "module_kind": kind})
            w.count("modules")
        return modules[code]

    def station(name: str) -> Asset:
        if name not in stations:
            band = name.split("-BAND")[0].capitalize() + "-band"
            digits = re.search(r"(\d+)$", name)
            stations[name] = w.upsert("RF Station", f"{facility}:STN:{_slug(name)}", name, {
                "station_name": name, "band": band,
                "station_number": int(digits.group(1)) if digits else None})
            w.count("stations")
        return stations[name]

    for comp in book.components:
        where = f"{comp.sheet} row {comp.row}"
        code = (comp.component.get("pbs_code") or "").strip()
        component_id = comp.component.get("component_id")
        type_name = TYPE_BY_COMPONENT.get(component_id or "")
        if type_name is None:
            w.warn(f"{where}: component code {component_id!r} is not one this import knows — "
                   f"kept as an unclassified Engineered Item ({code})")
            type_name = UNCLASSIFIED
        attrs = {k: v for k, v in comp.component.items() if k not in ("name",)}
        if comp.station:
            attrs["station_name"] = comp.station
        if comp.modules:
            attrs["module_code"] = "/".join(comp.modules)
        attrs["argus_lifecycle"] = "Planned"     # every state a PBS row can name is a design state
        item = w.upsert(type_name, f"{facility}:{code}", comp.component.get("name") or code,
                        attrs, keep=("argus_lifecycle",))
        w.count("components")

        wp = comp.component.get("wbs_code")
        if wp:
            if wp in packages:
                w.relate(item, packages[wp], "assigned to")
            else:
                w.warn(f"{where}: work package {wp!r} is not in the WBS CODE sheet")
        area = comp.component.get("pbs_area")
        if area:
            place = sections.get(area) or areas.get(area)
            if place is not None:
                w.relate(item, place, "part of")
            else:
                w.warn(f"{where}: area/zone {area!r} is in neither the SYSTEM ZONE nor the AREA sheet")
        for code_ in comp.modules:
            w.relate(item, module(code_), "part of")
        if comp.station:
            st = station(comp.station)
            w.relate(st, item, "composed of")
            for code_ in comp.modules:
                w.relate(st, module(code_), "part of")

        if comp.utility or comp.notes:
            util = dict(comp.utility)
            if comp.notes:
                util["description"] = "; ".join(comp.notes)
            u = w.upsert("Utility Requirement", f"{facility}:{code}:UTIL", f"Utilities of {code}", util)
            w.relate(item, u, "requires")
            w.count("utility_requirements")
        if comp.procurement:
            p = w.upsert("Procurement Record", f"{facility}:{code}:PROC", f"Procurement of {code}",
                         comp.procurement)
            w.relate(item, p, "procured under")
            w.count("procurement_records")

    for uid in list(w.touched):
        rebuild_asset_relations(db, uid)
    counts = dict(w.counts)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return PbsResult(counts=counts, warnings=w.warnings)
