# Object schema design for a large-scale accelerator

*A type catalogue for the ARGUS Knowledge Hub, sized for a facility with thousands of
devices, and for bringing the control configuration in as equipment rather than as a file.*

> **Baseline and evidence document — not the current production specification.**
> [`asset-model-revision.md`](asset-model-revision.md) is normative. Where the two disagree —
> provenance, installation history, connectivity, relation governance, identity reconciliation,
> ownership, Jira/Insight, or the production type set — the revision wins. The measurements and
> source analysis below remain evidence for that revision.

The current model makes four corrections that are essential when reading this document:

1. A configuration name denotes a stable **Position**, not a serialised physical unit. Physical
   **Equipment** is created and maintained in ARGUS inventory, and valid-time **Installations** join
   it to Positions.
2. Imported, inferred, resolved, and manual facts enter the append-only fact ledger. Attributes and
   asserted edges are projections; shortcuts such as `realized by` are derived.
3. The initial production catalogue is the governed core in the revision. The 122-type tree below
   is a target ontology whose extensions are activated only with a source, owner, and query.
4. ARGUS replaces Jira and Insight as the system of record. Their identifiers and history are
   migrated as aliases and evidence; they are not continuing authorities after domain cutover.
5. AI-assisted entry (photographs, nameplates, datasheets, spreadsheets) produces **proposals**,
   not records. An extracted serial, model or type is an AI claim that a person confirms. An
   Equipment record or an Installation exists only by an authorized decision (§16 below;
   revision §23).
6. The Flutter field client ([`flutter-app-design.md`](flutter-app-design.md)) goes through the
   same ledger. A unit registered or replaced at the rack is a request to the API, and offline it
   is a pending command. It never establishes physical identity directly (§16 below; revision §24).

---

## 1. Why this document exists

The hub ships two seeded type catalogues and is missing the third:

| Section | Catalogue | Where |
|---|---|---|
| Tickets | `Ticket` + 5 kinds, 30 attributes | `backend/app/services/ticket_types.py` |
| Documents | `Document` + 14 kinds, 16 attributes | `backend/app/services/document_types.py` |
| **Objects** | **none** | — |

Every object type that exists today was created by an importer, with `attributes: []`:

- `backend/app/services/epik8s_import.py:54` — five structural types (Facility, IOC, Control
  Device, Access Point, Control Service).
- `tools/epik8s-devices/epik8s_devices/hub.py` — one flat type per `device_class`
  (Power Supply, Vacuum, Motion Controller, …).

So objects carry free-form attribute bags that nothing validates, nothing autocompletes and
no UI column can be built from. Worse, the two sets are live at the same time and describe the
same hardware differently.

### The gap, stated by the data itself

`tools/epik8s-devices/sparc-devices.csv` holds 340 scanned SPARC devices, with a `needs`
column saying what each row is missing. **234 of 340 rows** are missing at least one of:

```
"element it serves"            — what this channel physically acts on
"model"                        — which product this is an instance of
"link to the physical asset"   — which serialised box is installed
```

Those are not three missing fields. They are three missing **planes** of the model. A single
object cannot be the quadrupole, the magnet, the product type and the EPICS channel at once —
not once the magnet is swapped and the quadrupole stays.

---

## 2. The design in one picture

Six roots under one abstract `Item`: four planes, plus place and the engineering record.

```
    FUNCTIONAL          "what the machine is"        survives every hardware swap
    GUNQUA01   Quadrupole, s = 1.42 m, k1 = 3.2
        ▲
        │ realized by
        │
    PHYSICAL            "which box is in it now"     carries serial, PO, warranty
    SPARC-PS-0027   CAEN ELS Hi-Star, s/n 84321, rack B12
        │                                    ▲
        │ instance of                        │ located in
        ▼                                    │
    CATALOGUE                              LOCATION
    Hi-Star (CAEN ELS)                     Rack B12 → Area LINAC → Building SPARC Hall
        ▲
        │ templated from
        │
    CONTROL             "how it is driven"           the configuration, as objects
    IOC histar ──drives──▶ SPARC-PS-0027
        │                        ▲
        │ provides               │ acts on
        ▼                        │
    Control Device SPARC:MAG:HISTAR:GUNQUA01 ──reached through──▶ Access Point 192.168.0.27
        │
        │ declared in
        ▼
    Control Configuration  epik8-sparc @ main
```

Each plane answers a question no other plane can:

| Plane | Root | The question it owns |
|---|---|---|
| Functional | `Functional Element` | What is the machine made of, and where along the beam? |
| Physical | `Asset` | Which serialised box is installed, since when, under warranty until? |
| Catalogue | `Catalog Item` | What kind of thing is it, and what does the vendor say about it? |
| Control | `Control Item` | How is it driven, by which IOC, through which wire, declared where? |
| Location | `Location` | Where is it, and what are the access rules to reach it? |
| Engineering | `Engineering Record` | What does the design say it needs, costs and belongs to? |

A composite element — a screen station, an RF station, an assembled module — is a functional
object with `composed of` edges to its parts, so the camera can be swapped without rewriting
the element and a motion fault does not look like an imaging fault. See §4.

---

## 3. What the platform can express

Verified against the code, because the catalogue must fit the machinery that will enforce it.

| Capability | Where | What it means for the catalogue |
|---|---|---|
| Single inheritance, unlimited depth, merged at read time by key; a child redefining a key overrides in place | `backend/app/services/attribute_validation.py:35` | Deep trees are free. Declare a shared key once, at the top. |
| `is_concrete` is **advisory** — nothing enforces it | model, pydantic and UI only | Abstract bases document intent; they do not prevent instantiation. |
| Attribute types: `string, text, integer, float, boolean, date, datetime, enumeration, reference, attachment, user, current_user` | `webapp/src/api/types.ts:25` | No unit type — put the unit in the display name, `Gradient (T/m)`. `date`/`datetime` are unparsed strings. `attachment` has no editor; real files belong to the attachments table. |
| `indexed: true` on a string is a **controlled vocabulary by derivation** — values already in use are offered as you type | `backend/app/routers/attribute_values.py` | Use `indexed` string wherever the set is open (vendor, system, zone, template). Reserve `enumeration` for genuinely closed sets. |
| `reference` validates target type (`referenceSchemaUid`, `includeChildren`) but creates **no graph edge** | `attribute_validation.py:145`; `backend/app/services/integrity.py:121` | Topology belongs in `Relation` rows. A reference becomes an edge only when `relink_workspace` runs — and it labels that edge with the attribute's `name`. |
| `Relation` rows carry **no attributes** — only `from`, `to`, `relation_type` | `backend/app/models/asset.py:31` | An edge's parameters (a pressure threshold, a cable length) must live on one endpoint. |
| `relation_type` is a free-form string; the graph walks edges from both ends | `backend/app/services/knowledge_graph.py` | The vocabulary in §6 is a convention. Nothing enforces it; the importers must agree on it. |
| `assets.key` is unique **across the whole installation**, not per workspace | `backend/app/models/asset.py:18`; `epik8s_import.py:260` | Every key must carry the facility. |
| MCP object search matches the type **name** as a substring | `backend/app/services/mcp_tools.py:126` | Type names must be the words operators use. "Ion Pump", not "VacuumDevice". This is the strongest argument for a wide catalogue. |
| Photo identification writes `manufacturer`, `model`, `serial`, `description`, and reads keys matching `^[A-Z][A-Z0-9]{1,9}-\d{1,8}$` | `backend/app/services/asset_vision.py:31` | Those four keys are **reserved**; the physical base must declare them unprefixed, and the key scheme must match that pattern. |
| `argus_system` / `argus_subsystem` / `argus_facility` / `argus_keywords` already mean something on tickets and documents | `ticket_types.py:72`; `document_types.py:77` | Objects must spell them identically, or "everything about the vacuum system" cannot be answered across sections. |
| A type flagged global is usable and inheritable from every workspace. **An object is readable outside its workspace only if it is itself flagged global**, and is editable only in the one that made it | `backend/app/services/visibility.py`; `schemas.py:46` | The shared types live in one catalogue workspace (§8). Sharing a type shares the *definition*; sharing an object is a separate, deliberate flag. (It used to be one rule, and every beamline's cameras appeared in every other beamline.) |
| An enumeration is **stored as its label**: the edit form writes `opt.value`, and the validator compares against labels (`attribute_validation.py:137`). The read view resolves ids, then falls back to showing the raw value | `AttributeInput.tsx:260`; `AttributeValue.tsx:56` | Importers must write labels (`"Approved"`), not ids (`"approved"`), or the first human edit of the object fails validation. `argus_source: "epik8s"` passes only because the label `EPIK8s` lower-cases to it. |
| Regex is `re.search`, not `fullmatch` | `attribute_validation.py:127` | Anchor every pattern `^…$`. |
| `unique` is scoped to one exact `schema_uid`, not the subtree | `attribute_validation.py:163` | A serial unique on `Asset` is *not* unique across its leaves. Put `unique` on the leaf, or accept it as advisory. |

---

## 4. The type catalogue

**150 types, 18 of them abstract, maximum depth 6.** (The beam model added 22: see `docs/beam-model.md`; the last four — `Vacuum Element`, `Material Element`, `Optical Element`, `Support Element` — came with `argus.beam-model/2`.) (The IT model added 11 to the 104 before it: `IT Equipment` and its tree, `IT Record`, `Serial Line`. Six came after the tree below was drawn: `Equipment Port` under `Engineered Item`, one physical port of a unit that it is `port of`; `Communication Path` and `Bus Segment` under `Control Item`, see `docs/it-model-design.md`; `Address Record` under `IT Record`; and under `Asset`, `Vacuum Component`, a passive part of the vacuum line such as a pipe, bellows, cross or tee, and `Vacuum Controller`, the box between a control line and the pumps or gauges it runs.) Abstract types are marked *(abstract)*.

```
Item (abstract)
├── Engineered Item (abstract)      anything in the product breakdown: PBS code, WBS, status, cost
│   ├── Functional Element (abstract)
│   │   ├── Facility                a beamline or accelerator  ← name reused by epik8s_import
│   │   ├── Section                  injector, linac, bunch compressor, undulator hall
│   │   ├── Machine System           the named system: Vacuum, RF, Magnets, Diagnostics
│   │   ├── Machine Module           an assembled module: INJ-LA-001, LEL-LA-002
│   │   ├── RF Station               modulator + klystron + compressor + waveguide + structures
│   │   └── Beam Element (abstract)  something the beam passes through or is acted on by
│   │       ├── Dipole               ├── Quadrupole            ├── Sextupole
│   │       ├── Corrector            ├── Solenoid              ├── Accelerating Structure
│   │       ├── RF Gun               ├── RF Deflector          ├── Undulator
│   │       ├── Plasma Module        ├── Collimator            ├── Beam Stopper
│   │       ├── Vacuum Sector        ├── Mirror
│   │       └── Diagnostic Element (abstract)
│   │           ├── Screen Station          camera + screen + actuator + optics
│   │           ├── Beam Position Monitor   ├── Beam Charge Monitor
│   │           ├── Faraday Cup             ├── Wire Scanner
│   │           ├── Emittance Meter         ├── Spectrometer Station
│   │           ├── Beam Loss Monitor       ├── Beam Arrival Monitor
│   │           └── Bunch Length Monitor
│   └── Asset (abstract)   the serialised box, with a purchase order
│       ├── Power Supply             ├── Magnet Assembly
│       ├── RF Amplifier             ├── Modulator             ├── Low-Level RF Unit
│       ├── Waveguide Component (abstract)
│       │   ├── Waveguide Section    ├── RF Load               ├── RF Window
│       │   ├── Directional Coupler  ├── RF Isolator           ├── RF Hybrid
│       │   ├── RF Pulse Compressor  ├── RF Attenuator         ├── RF Phase Shifter
│       │   └── RF Mode Converter
│       ├── Vacuum Pump (abstract)
│       │   ├── Ion Pump             ├── Turbo Pump
│       │   ├── Primary Pump         └── NEG Cartridge
│       ├── Vacuum Gauge             ├── Vacuum Valve          ├── Vacuum Chamber
│       ├── Motion Controller        ├── Motor Axis            ├── Actuator
│       ├── Camera                   ├── Optical Assembly      ├── Scintillator Screen
│       ├── Digitizer                ├── Instrument
│       ├── I/O Module               ├── PLC                   ├── Timing Module
│       ├── Electronics Crate        ├── Electronics Board
│       ├── Network Device           ├── Computing Node
│       ├── Chiller                  ├── Cooling Circuit Component
│       ├── Cryogenic Device
│       ├── Interlock Unit           ├── Radiation Monitor
│       ├── Laser System             ├── Cable Run
│       ├── Mechanical Support       └── Spare Part
├── Catalog Item (abstract)
│   ├── Product Model                a vendor's product: "Agilent IPCMini"
│   └── Vendor                       the company, its support contract and RMA route
├── Control Item (abstract)          the control configuration, as objects
│   ├── Control Configuration        one values.yaml at one git revision
│   ├── IOC Template                 an iocDefaults entry / ibek template
│   ├── IOC                          ← name reused by epik8s_import
│   ├── Control Device               ← name reused by epik8s_import
│   ├── Access Point                 ← name reused by epik8s_import
│   ├── Control Service              ← name reused by epik8s_import
│   ├── Control Network              a named network and its address range
│   └── Storage Mount                an NFS mount or backup target
├── Engineering Record (abstract)    what the design says a component needs, and what it costs
│   ├── Utility Requirement          power, cooling water, air, gases — one per component
│   ├── Procurement Record           cost, supplier, delivery, funding line, CIG
│   └── Work Package                 WP-01 … WP-13
└── Location (abstract)
    ├── Building                     ├── Area                  ├── Rack
    └── Storage Location
```

### Composite elements: one element, several boxes

Most diagnostics are not one device. A screen station is a scintillator, a camera, an
actuator to put the screen in the beam and the optics between them — four serialised items,
bought separately, replaced separately, driven by **two different IOCs**. Modelling it as one
object means the camera cannot be swapped without rewriting the element, and a motion fault
and an imaging fault look like the same fault.

So a composite is a `Functional Element` with `composed of` edges to its `Asset`
parts:

```
Screen Station  FLAG-INJ-001                  ← the element the beam sees
   ├── composed of ─▶ Scintillator Screen     YAG:Ce, 100 µm, ⌀25 mm
   ├── composed of ─▶ Camera                  Basler scA640-70gm, GigE
   ├── composed of ─▶ Actuator                pneumatic, 2 positions (IN / OUT)
   └── composed of ─▶ Optical Assembly        f = 50 mm, 0.5×, ND filter wheel
```

Three types in the catalogue exist only to make this work: `Scintillator Screen`,
`Optical Assembly` and `Actuator`. Without them the station's parts have nowhere to live and
end up as free text in a description.

**`composed of` is not `part of`.** `part of` is membership — this quadrupole is part of the
injector, this IOC is part of the vacuum system. `composed of` is assembly — the whole is a
different kind of thing from its parts, and removing a part breaks the whole. The graph walks
both, but they answer different questions and mixing them makes "what is in the injector"
return every screw.

The same pattern covers the other composites in the catalogue:

| Composite | Typically composed of |
|---|---|
| `Screen Station` | Scintillator Screen, Camera, Actuator, Optical Assembly |
| `Spectrometer Station` | Dipole (element), Screen Station, Faraday Cup |
| `Emittance Meter` | Screen Station, Actuator, and a Quadrupole it scans |
| `RF Station` | Modulator, RF Amplifier, RF Pulse Compressor, Waveguide Components, Accelerating Structures |
| `Machine Module` | whatever the assembled module contains — the PBS `MODULES` column |
| `Magnet Assembly` | Magnet Assembly, Power Supply, Cooling Circuit Component |

### Why the functional list and the hardware list are different lists

They barely overlap on purpose. `Quadrupole` is a lattice element with a gradient and an
s-position; `Power Supply` and `Magnet Assembly` are the two boxes that realise it. The one
place they nearly collide — `Vacuum Sector` (functional) against `Vacuum Chamber` (physical) —
is a real distinction: a sector is what a valve isolates, a chamber is what you unbolt.

`sparc-devices.csv` proves the two lists are already being kept separately by hand. Its
`element` column holds lattice words (Quadrupole, Solenoid, BPM, Flag, Undulator) **and**
hardware words (Ion pump, Chiller, Vacuum gauge). That is why `acts on` (§6) is deliberately
polymorphic: a control channel acts on whatever physically fails, which is sometimes an
element and sometimes a plain piece of equipment.

---

## 5. Attributes

A type with no attributes listed below has none of its own: it inherits everything from its
ancestors, which for most equipment types is already the serial number, manufacturer, model,
location, PBS code and lifecycle. The catalogue does not invent fields nobody has asked for.

### 5.1 `Item` and `Engineered Item` — the roots every object inherits

These are the keys that make an object joinable to tickets and documents. They are spelled
exactly as `ticket_types.py` and `document_types.py` spell them; changing one here breaks
"everything about the vacuum system" across all three sections.

| key | name | type | flags | notes |
|---|---|---|---|---|
| `description` | Description | text | | **reserved** — written by photo identification |
| `argus_facility` | Facility | string | indexed | SPARC, BTF, EuAPS |
| `argus_system` | System | string | indexed | same key as tickets and documents |
| `argus_subsystem` | Subsystem | string | indexed | same key |
| `argus_keywords` | Keywords | string | multiValue, indexed | same key as documents |
| `argus_lifecycle` | Lifecycle | enumeration | | Planned, In service, Standby, Under maintenance, Faulty, Decommissioned, Scrapped |
| `argus_criticality` | Criticality | enumeration | | Safety-critical, Beam-critical, Degrades beam, Non-critical |
| `argus_responsible` | Responsible | user | | the person; teams stay in the `groups` table |
| `argus_source` | Source | enumeration | readOnly | Created here, EPIK8s, epik8s-devices, Jira, Git, PBS workbook |
| `argus_source_ref` | Source revision | string | readOnly | already written by `epik8s_import.py` |

**`Engineered Item`** *(abstract)* sits between `Item` and the functional and physical planes,
and carries the product breakdown. It is deliberately **not** on `Item`: a control device, a
vendor or a spare part has no PBS code, and putting these thirteen keys at the very top would put
them on all 509 control devices as well.

| key | name | type | flags | notes |
|---|---|---|---|---|
| `pbs_code` | PBS code | string | unique, indexed, regex `^[A-Z0-9]+(-[A-Z0-9.]+){3,4}$` | `INJ-A-ACC-SB3M-001` |
| `pbs_area` | Area / zone | string | indexed | `INJ`, `LEL`, `MHX3` — legend in the AREA and SYSTEM ZONE sheets |
| `pbs_system` | PBS system | string | indexed | `A`, `R`, `I` |
| `pbs_family` | PBS family | string | indexed | `ACC`, `RF`, `WGS`, `WGX`, `RFS`, `RFX` |
| `pbs_type` | PBS type | string | indexed | `SB3M`, `BDC`, `LOAD`, `GUN` |
| `pbs_sequential` | Sequential number | string | | kept as a string: `001`, not `1` |
| `component_id` | Component id | string | indexed | `RFG`, `SB3`, `BDC` — the short component code |
| `wbs_code` | Work package | string | indexed | `WP-04`; the edge is `assigned to` |
| `module_code` | Module | string | indexed | `INJ-LA-001` |
| `station_name` | Station | string | indexed | `X-BAND STATION 3` |
| `design_status` | Design status | enumeration | | Study, Defined, Approved (`S` / `D` / `A`) |
| `unit_count` | Number of units | integer | | |
| `sequence_index` | Sequence in the PBS | integer | | the workbook's `ID` column: rises down the sheet and may be order along the machine — kept, **not** read as `s_position` |

`design_status` is the design-maturity axis and is orthogonal to `argus_lifecycle`: a component
can be *Approved* on paper and *Planned* in the tunnel. Both are needed — the first is what the
engineering review tracks, the second is what operations tracks.

### 5.2 `Functional Element` and `Beam Element`

`Functional Element` adds `argus_beamline` (string, indexed) and `zone` (string, multiValue,
indexed — the `zones:` of the configuration).

The three grouping types below `Functional Element` are what composites hang from:

- `Machine System` — `system_code` (indexed), `responsible_group`
- `Machine Module` — `module_code` (unique, indexed), `module_kind` (enum: Accelerating `LA`,
  Magnetic `LEL`, Diagnostic, Plasma, Other), `assembly_state` (enum: Designed, In assembly,
  Assembled, Installed)
- `RF Station` — `band` (enum: S-band, X-band, C-band), `station_number`, `frequency` (MHz),
  `peak_power` (MW), `pulse_length` (µs), `repetition_rate` (Hz)

`Beam Element` adds the lattice:

| key | name | type | flags |
|---|---|---|---|
| `lattice_name` | Lattice name | string | unique, indexed, regex `^[A-Z][A-Z0-9_]{2,15}$` |
| `s_position` | s position (m) | float | |
| `length` | Magnetic/effective length (m) | float | |
| `family` | Family | string | indexed |
| `design_value` | Design strength | float | |
| `design_unit` | Design strength unit | string | indexed |
| `polarity` | Polarity | enumeration | Positive, Negative, Bipolar |

Leaves add only their own physics, nothing else:

- `Dipole` — `bend_angle` (rad), `bend_radius` (m), `field` (T)
- `Quadrupole` — `gradient` (T/m), `k1` (1/m²), `aperture_radius` (mm)
- `Sextupole` — `k2` (1/m³)
- `Corrector` — `plane` (enum H/V/Combined), `max_kick` (mrad)
- `Solenoid` — `field_on_axis` (T)
- `Accelerating Structure` — `frequency` (MHz), `n_cells`, `gradient` (MV/m), `r_over_q`, `q0`
- `RF Gun` — `frequency` (MHz), `cathode_material`, `peak_field` (MV/m)
- `Undulator` — `period` (mm), `n_periods`, `k_value`, `gap_min`/`gap_max` (mm)
- `Collimator` / `Beam Stopper` — `aperture_min`/`aperture_max` (mm), `material`
- `Mirror` — `mirror_kind` (enum: Flat, Parabolic, Other), `beam` (laser line: main, probe; indexed),
  `coating`, `diameter_mm`, `substrate`. A laser-line mirror on a mount that motors tilt; made by
  the motor inference from its axes (§9.5).
- `Vacuum Sector` — `nominal_pressure` (mbar), `length` (m), `isolated_by` (reference → `Vacuum Valve`, multiValue)
- `Plasma Module` — `capillary_length` (mm), `capillary_diameter` (mm), `gas` (indexed),
  `discharge_voltage` (kV), `plasma_density` (cm⁻³)

**`Diagnostic Element`** *(abstract)* adds what every diagnostic has, whatever it measures:
`measures` (enum: Position, Charge, Profile, Emittance, Energy, Arrival time, Bunch length,
Loss), `is_invasive` (boolean — does using it stop the beam), `resolution`, `resolution_unit`
(indexed), `acquisition_rate` (Hz), `calibration_due` (date).

Its leaves:

- `Screen Station` — `screen_type` (enum: YAG:Ce, LYSO, OTR, Chromox, Scintillating fibre),
  `calibration_um_per_px` (float), `insertion_positions` (multiValue, indexed — `IN`, `OUT`,
  `CALIB`), `viewing_angle_deg`, `field_of_view_mm`. *Composite — see §4.* Formerly named
  `Screen Monitor`; renamed because the object is a station, not a single device.
- `Beam Position Monitor` — `pickup_kind` (enum: Button, Stripline, Cavity, Inductive),
  `n_electrodes`, `bandwidth` (MHz)
- `Beam Charge Monitor` — `monitor_kind` (enum: Integrating current transformer, Wall current,
  Faraday cup), `charge_range_pc`
- `Faraday Cup` — `material`, `is_retractable` (boolean)
- `Wire Scanner` — `wire_material`, `wire_diameter` (µm), `n_planes`
- `Emittance Meter` — `method` (enum: Pepper-pot, Quadrupole scan, Multi-screen, Slit-scan),
  `mask_pitch` (µm). *Composite.*
- `Spectrometer Station` — `dispersion` (m), `energy_range_min`/`energy_range_max` (MeV).
  *Composite.*
- `Beam Loss Monitor` — `detector_kind` (enum: Ion chamber, Scintillator, Cherenkov, PIN diode),
  `alarm_threshold`
- `Beam Arrival Monitor` — `time_resolution_fs`, `pickup_kind`
- `Bunch Length Monitor` — `method` (enum: Electro-optic sampling, Streak camera, CTR, CDR,
  RF deflector), `time_range_ps`

### 5.3 `Asset` — the serialised box

| key | name | type | flags | notes |
|---|---|---|---|---|
| `manufacturer` | Manufacturer | string | indexed | **reserved** — photo identification |
| `model` | Model | string | indexed | **reserved** — photo identification |
| `serial` | Serial number | string | indexed | **reserved** — photo identification |
| `product_model` | Instance of | reference → `Product Model` | | named for the relation, see §3 |
| `argus_location` | Located in | reference → `Location`, includeChildren | | named for the relation |
| `inventory_number` | Inventory number | string | unique, indexed | the INFN inventory number |
| `installed_on` | Installed on | date | | |
| `removed_on` | Removed on | date | | set when it comes out, not deleted |
| `warranty_until` | Warranty until | date | | |
| `condition` | Condition | enumeration | | New, Good, Degraded, Faulty, Beyond repair |
| `is_spare` | Held as spare | boolean | | a spare is the same type, on a shelf |
| `inventory_url` | Inventory link | string | | already written by `epik8s_import.py` from `asset:` |

Notable leaves:

- `Power Supply` — `n_channels`, `current_max` (A), `voltage_max` (V), `bipolar` (bool),
  `interface` (enum Modbus TCP/Serial/Ethernet/GPIB/CAN), `ramp_rate` (A/s)
- `Magnet Assembly` — `coil_resistance` (Ω), `cooling` (enum Air/Water/Cryogenic), `weight` (kg)
- `Ion Pump` — `pumping_speed` (l/s), `nominal_voltage` (V), `element_count`
- `Turbo Pump` — `pumping_speed` (l/s), `rotation_speed` (Hz), `backing_pump` (reference → `Primary Pump`)
- `Vacuum Gauge` — `gauge_kind` (enum Pirani/Penning/Cold cathode/Capacitive), `range_min`/`range_max` (mbar)
- `Vacuum Valve` — `valve_kind` (enum Gate/Angle/All-metal), `actuation` (enum Manual/Pneumatic/Electric), `interlocked` (bool)
- `Camera` — `sensor`, `resolution_x`/`resolution_y` (px), `pixel_size` (µm), `interface`
  (enum GigE/USB3/CameraLink/CoaXPress), `lens`, `px_calibration` (µm/px)
- `Motion Controller` — `n_axes`, `protocol`, `firmware_version`
- `Motor Axis` — `axis_id`, `travel_min`/`travel_max`, `resolution` (mm/step), `velocity_max` (mm/s), `has_home_switch` (bool)
- `Network Device` — `device_kind` (enum Switch/Terminal server/Media converter/Router), `n_ports`,
  `hostname` (indexed), `ip` (indexed), `fqdn`, `firmware_version`
- `Computing Node` — `hostname` (indexed), `ip`, `cpu`, `ram_gb`, `os`, `role`
- `Cable Run` *(abstract)* — `cable_label`, `cable_type`, `length_m`, `from_asset`, `from_connector`, `to_asset`, `to_connector`, `signal`. Children, by what they carry: `Ethernet Cable`, `Serial Cable` (`serial_standard`), `Fibre Cable`, `Power Cable`, `HV Cable`, `RF Cable`, `Signal Cable`.
- `Spare Part` — `spare_for` (reference → `Product Model`), `quantity`, `minimum_stock`,
  `storage_location` (reference → `Storage Location`)
- `Interlock Unit` — `interlock_kind` (enum PSS/MPS/Vacuum/Thermal), `sil_level`, `test_interval_months`
- `Radiation Monitor` — `detector_kind`, `alarm_threshold`, `calibration_due` (date)

The three added for composite diagnostics:

- `Scintillator Screen` — `screen_material` (enum: YAG:Ce, LYSO, OTR foil, Chromox, Alumina),
  `thickness_um`, `diameter_mm`, `mount_angle_deg`, `has_calibration_target` (boolean),
  `radiation_dose_budget`
- `Optical Assembly` — `focal_length_mm`, `magnification`, `aperture_f`, `filters`
  (multiValue, indexed), `mirror_count`, `working_distance_mm`
- `Actuator` — `actuator_kind` (enum: Pneumatic, Solenoid, Stepper, Piezo, Manual),
  `n_positions`, `position_labels` (multiValue, indexed), `stroke_mm`, `has_position_switch`
  (boolean), `fail_safe_position` (indexed)

And the waveguide family, which the EuPRAXIA PBS itemises one by one (§10). `Waveguide
Component` *(abstract)* carries `band` (enum: S-band, C-band, X-band), `waveguide_size`
(indexed, e.g. `WR284`, `WR90`), `flange_type`, `peak_power_rating` (MW),
`average_power_rating` (kW), `is_pressurised` (boolean), `gas` (indexed — SF6, N₂, vacuum).
Its leaves add only what distinguishes them:

| type | PBS code | own attributes |
|---|---|---|
| `Waveguide Section` | `WGS` | `length_mm`, `bend_angle_deg`, `is_flexible` |
| `RF Load` | `LOAD`, `RFL` | `load_kind` (Water, Dry, Ceramic), `vswr_max` |
| `RF Window` | `WIN` | `window_material` (Ceramic, Sapphire), `is_vacuum_barrier` |
| `Directional Coupler` | `BDC` | `coupling_db`, `directivity_db`, `is_bidirectional` |
| `RF Isolator` | `ISL` | `isolation_db`, `insertion_loss_db` |
| `RF Hybrid` | `HYB` | `hybrid_kind` (3 dB, Magic-T), `phase_balance_deg` |
| `RF Pulse Compressor` | `PCMP` | `compressor_kind` (SLED, BOC, Barrel), `gain_factor`, `q0` |
| `RF Attenuator` | `ATT` | `attenuation_db`, `is_variable` |
| `RF Phase Shifter` | `PHS` | `phase_range_deg`, `is_motorised` |
| `RF Mode Converter` | `MCV`, `MCNV` | `mode_in`, `mode_out` |

### 5.4 `Catalog Item`

`Product Model` is the type that pays for itself fastest: 46 of the 340 SPARC rows are
Agilent IPCMini pumps. A procedure, a spare-part list and a firmware note written once here
cover all 46, and `documents.is_global` already supports exactly that sharing.

| key | name | type | flags |
|---|---|---|---|
| `vendor` | Vendor | string | indexed |
| `vendor_ref` | Supplied by | reference → `Vendor` | |
| `model_code` | Model code | string | indexed |
| `device_class` | Device class | string | indexed |
| `datasheet_url` | Datasheet | string | |
| `firmware_version` | Current firmware | string | |
| `eol_date` | End of life | date | |
| `mtbf_hours` | MTBF (h) | integer | |
| `typical_spares` | Typical spares | string | multiValue, indexed |
| `inventory_url` | Inventory link | string | ← an `iocDefaults` template's `asset:` |

`Vendor` — `contact`, `support_contract`, `support_expires` (date), `rma_procedure` (text),
`website`.

### 5.5 `Location`

`Location` carries `site`, `floor`, `access_rule` (enum Free/Badge/Interlocked/Radiation-controlled).

- `Area` — `zone` (string, indexed — matches the configuration's `zones:`),
  `radiation_classification` (enum Supervised/Controlled/Prohibited), `interlock_group`
- `Rack` — `rack_units`, `position`, `power_feed`, `cooling`
- `Storage Location` — `shelf`, `bin`, `climate_controlled` (bool)

### 5.6 `Control Item` — and a warning about key names

The control plane declares the **bare** keys `epik8s_import.py` already writes — `beamline`,
`pv_prefix`, `system`, `function`, `devtype`, `zones`, `channel`, `axis`, `address`, `port`,
`interlock`, `geo`, `ioc`, `inventory_url`, `settings`. They are *not* renamed to `argus_*`,
because every row already imported holds values under them and a rename would orphan the lot.

This is a real inconsistency with tickets and documents — `epik8s_import.py:485` even says the
`system` key exists to match tickets' `argus_system`, and then writes `system`. The fix is the
one `ticket_types.py:121` already demonstrates: a `LEGACY_KEY_MAP` alias pass that rewrites the
bare keys onto `argus_*` once, at which point the catalogue can declare the prefixed names.
Until that runs, the catalogue must describe what is actually stored. See §14.

**`Facility`** carries what the importer writes on it, spelled as it writes it: `beamline`,
`namespace`, `cluster`, `git_url`, `git_revision`. `beamline` sits beside the inherited
`argus_beamline` until the alias pass of §14 runs. This was found by a test that runs the real
importer and asserts every key it writes is declared — the first version of the catalogue
missed all five.

**`Control Configuration`** — one object per `values.yaml` at one git revision:

| key | name | type | flags |
|---|---|---|---|
| `git_url` | Repository | string | indexed |
| `git_revision` | Revision | string | |
| `config_path` | Path in repository | string | |
| `namespace` | Kubernetes namespace | string | indexed |
| `cluster` | Cluster | string | indexed |
| `argocd_project` | ArgoCD project | string | |
| `epics_address_list` | EPICS address list | string | |
| `max_array_bytes` | Max array bytes | integer | |
| `base_ip` | Address range | string | |
| `ingress_class` | Ingress class | string | |
| `imported_at` | Read at | datetime | readOnly |

**`IOC Template`** — one per `iocDefaults` entry, i.e. one per ibek template:

`template_name` (unique, indexed), `chart_url`, `image`, `devgroup` (indexed), `devtype`
(indexed), `devfunc`, `opi`, `autosync` (bool), `pva` (bool), `product_model`
(reference → `Product Model`), `inventory_url`.

**`IOC`** — adds to what the importer already writes: `template` (indexed), `chart_url`,
`image`, `host` (indexed), `opi`, `autosync` (bool), `pva` (bool), `networks` (multiValue,
indexed), `ioc_init` (text), `ssh_nodeport`.

**`Control Device`** — `pv` (indexed), `devtype` (indexed), `element` (indexed),
`device_class` (indexed), `vendor` and `model_code` (as found, before a Product Model is
linked), `channel`, `axis`, `address`, `port`, `interlock` (bool), `geo`,
`settings` (text — the rating block, see below), `enable_pv`.

`pv` is **not** unique. It was, and the first push of a reviewed SPARC file failed on it: the
configuration puts `SPARC:TIM:ac1bpm01` and `SPARC:TIM:llrf1` on two IOCs each
(`ioc-time-profile` and `profile-sync-test`). A unique rule would make the hub refuse every later
edit of those four devices over a fact about the file, so both are recorded and the import
reports the pair instead.

> The rating sub-blocks in the configuration (`ps: {current: {max: 280}}`,
> `motor: {velo_max: 50, dhlm: …}`, `pump: [{name, prefix, suffix, tsh}]`) are
> *limits on this installation*, not properties of the product. They stay on the
> `Control Device` under `settings`, and the `pump:` thresholds additionally become
> `enabled by` edges (§6) — because `Relation` rows carry no attributes, the threshold
> itself has to live on an endpoint.

**`Access Point`** — as written today (`address`, `ip`, `hostname`, `fqdn`, `beamline`,
`argus_provenance`), plus `port_count` and `network` (indexed).

**`Control Service`** — `service` (indexed), `chart_url`, `chart_revision`, `image`,
`loadbalancer_ip`, `ingress` (bool), `url`, `replicas`, `inventory_url`.

**`Control Network`** — `network_name` (indexed), `cidr`, `annotation`, `vlan`, `address_list`.

**`Storage Mount`** — `mount_kind` (enum NFS/Local/S3), `server` (indexed), `export_path`,
`mount_path`, `size_gb`, `is_backup` (bool).

### 5.7 `Engineering Record` — requirements and procurement

These are the columns of the EuPRAXIA PBS workbook that are **not** properties of the component
but statements about it: what it will need from the building, and what it will cost. They are
separate objects rather than 30 more attributes on `Engineered Item`, for three reasons: only
11–31 of 179 rows carry them today, so they would be empty on almost everything; they have
their own maturity (`design_status` moves independently); and they are consumed by a different
work package (WP-13, Building and Infrastructures) than the one that owns the component.

**`Utility Requirement`** — one per component that needs something from the infrastructure:

| group | keys |
|---|---|
| Electrical | `electrical_phases` (enum: 3P+N, 1P+N), `under_ups` (boolean), `nominal_current_a`, `max_inrush_current_a`, `nominal_power_kva`, `active_power_kw`, `cos_phi`, `rack_units`, `connectivity` (multiValue, indexed: RJ45, Fiber, PoE, Serial) |
| Heat | `heat_in_air_kw`, `heat_in_water_nominal_kw`, `heat_in_water_min_kw` |
| Cooling water | `water_temp_in_c`, `water_temp_setpoint_c` (one number), `water_temp_setpoint_min_c` / `water_temp_setpoint_max_c` (a range), `water_temp_stability_c`, `water_flow_l_min`, `water_pressure_in_bar`, `water_pressure_drop_bar`, `water_pressure_max_bar`, `water_delta_t_c`, `water_max_acceptable_temp_c` |
| Air | `air_temp_nominal_c`, `air_temp_stability_c`, `relative_humidity_pct`, `rh_stability_pct` |
| Compressed air | `compressed_air_nominal_bar`, `compressed_air_min_bar`, `compressed_air_max_bar`, `compressed_air_flow_l_min` |
| Other gases | `gas_type` (indexed), `gas_quantity_m3_h` |

Every one of those is a `float` except the enumeration, the boolean, `rack_units` (integer) and
the two strings, and every display name carries its
unit — `Water flow rate (l/min)` — because the platform has no unit type (§3).

> The workbook already shows why this needs a schema. `WATER FLOW RATE (l/min)` holds
> `4,2  (l/m oppure l/h)????????` on one row and `4.2` on the next: a decimal comma, a unit the
> author was unsure of, and a question in a numeric column. A `float` attribute named
> `Water flow rate (l/min)` makes that value either right or visibly absent.

**`Procurement Record`** — `unit_cost_eur` (float), `total_cost_eur` (float), `currency`,
`target_year` (integer), `target_semester` (enum: H1, H2), `procurement_route` (indexed),
`production_time_months`, `delivery_time_months`, `supplier` (indexed),
`supplier_ref` (reference → `Vendor`), `rup` (user), `funding_line` (indexed), `cig` (indexed),
`order_reference`, `ordered_on` (date), `delivered_on` (date).

**`Work Package`** — `wbs_code` (unique, indexed), `leader` (user), `institute` (indexed),
`budget_eur`, `start_date`, `end_date`. Thirteen objects, one per row of the workbook's
`WBS CODE` sheet, so that responsibility and budget have somewhere to live and a component can
say which one it belongs to.

---

## 6. Relation vocabulary

The five phrases `epik8s_import.py` already writes are kept **verbatim**, so re-running an
import churns nothing: `deployed on`, `connects to`, `provided by`, `reached through`,
`enabled by`.

Added, with direction `from → to`:

| relation | from → to | the question it answers |
|---|---|---|
| `realized by` | Beam Element → Asset | which magnet is in the quadrupole *right now* |
| `instance of` | Asset → Product Model | the CSV's *"model"* |
| `acts on` | Control Device → Item | the CSV's *"element it serves"* — polymorphic on purpose |
| `drives` | IOC → Asset | the CSV's *"link to the physical asset"*, resolved from `asset:` |
| `templated from` | IOC → IOC Template | which recipe deployed it |
| `declared in` | IOC, Control Service, Control Device → Control Configuration | which revision said so |
| `configures` | Control Configuration → Facility | |
| `implemented by` | Access Point → Network Device | joins the control plane to the box with a purchase order |
| `on network` | IOC, Access Point → Control Network | |
| `mounts` | IOC, Control Service → Storage Mount | one NFS server down takes ten IOCs with it |
| `powers` | Power Supply → Magnet Assembly, Item | the README's own example chain |
| `cools` | Chiller → Item | |
| `measures` | diagnostic element → Beam Element, Section | |
| `interlocks` | Interlock Unit → Item | |
| `upstream of` | Beam Element → Beam Element | beam-path order, to propagate a fault downstream |
| `part of` | Item → Item | assemblies, sections, systems |
| `located in` | Asset → Location | |
| `spare for` | Spare Part → Product Model | |
| `replaced` | Asset → Asset | swap history, so a chronic failure becomes visible |
| `composed of` | Functional Element → Asset, Item | a screen station's camera, screen, actuator and optics |
| `requires` | Engineered Item → Utility Requirement | what the building has to supply |
| `procured under` | Engineered Item → Procurement Record | cost, supplier, delivery |
| `assigned to` | Engineered Item → Work Package | who is responsible for delivering it |

**Reference attribute, or `Relation` row?**

`composed of` and `part of` are both in the list and are **not** interchangeable — see §4.
`part of` is membership in a section, system or module; `composed of` is assembly, where the
whole is a different kind of thing from its parts.

- If the question is asked **from both ends**, it is a `Relation`. The knowledge graph walks
  those, and "what does this IOC drive" and "what drives this magnet" are the same row.
- If it is asked **from one end only**, a reference attribute is enough, and it gets validated.
- Reference attributes are **named with the relation phrase** — `Instance of`, `Located in`,
  `Spare for` — because `relink_workspace` labels the edge it materialises with the attribute's
  `name`. Calling the attribute "Product model" would produce an edge called "Product model";
  calling it "Instance of" produces the right one.

---

## 7. Naming rules

| Thing | Rule | Example |
|---|---|---|
| Type uid | `{workspace_id}:argus-object:{slug}` — the convention the other two seeders use | `sparc:argus-object:ion-pump` |
| Type name | The operator's word, singular, title case — MCP search matches the name | `Ion Pump`, not `VacuumPumpDevice` |
| Object key | `<FACILITY>-<FAMILY>-<NNNN>`, anchored `^[A-Z][A-Z0-9]{1,9}-\d{1,8}$` | `SPARC-QUA-0012` |
| Control-plane key | The importer's scheme, with its parts joined by `-`: a `:` reads as a PV name, which a key is not. The uid stays derived from the same parts joined by `:`, so a key's spelling never changes a uid | `SPARC-DEV-histar-GUNQUA01` |
| Attribute key | `argus_*` when shared with tickets or documents; bare for the four reserved by photo identification and for the control plane's existing keys | `argus_system`, `serial`, `pv_prefix` |

The facility prefix on object keys is **mandatory**, not cosmetic: `assets.key` is unique
across the whole installation, and `epik8s_import.py:260` exists purely to turn that collision
into a sentence an operator can act on.

`asset_vision.KEY_PATTERN` is `\b[A-Z][A-Z0-9]{1,9}-\d{1,8}\b` — **one** hyphen. A key that has
two, like the readable `SPARC-QUA-0012` used in the examples, is read out of a photograph as
`QUA-0012`, which matches nothing. For a label somebody will photograph, use the compact form
`SPQUA-0012` (letters and digits, at most ten, one hyphen, digits); for everything else the
readable form is fine. Extending the pattern to accept the three-part form is a one-line change
noted in §15.

---

## 8. Where the catalogue lives

**Two sets, seeded separately.** The types divide by what they describe, and each set goes
where its objects should be readable.

| | Global set — 76 types | Per-beamline set — 46 types |
|---|---|---|
| Where | one catalogue workspace, every type flagged global | each beamline's own workspace, not global |
| What | `Item`, `Engineered Item`, the whole **`Asset`** branch, the **`Catalog Item`** branch (`Product Model`, `Vendor`), the **`Location`** branch | the **`Functional Element`** branch (facility, sections, modules, lattice elements, screen stations…), the **`Control Item`** branch (configuration, IOCs, devices, access points…), the **`Engineering Record`** branch (utilities, procurement, work packages) |
| Meaning | what exists physically and can be bought: one inventory | how one machine is arranged, controlled and paid for |
| Objects | stay in the workspace that made them, **unless flagged global** (a product model, a vendor, a person, a company, an inventory document: what is meant to be shared) | stay in the workspace that made them |

A beamline type hangs from global parents (`Functional Element` from `Engineered Item`,
`Control Item` from `Item`), and inherits their attributes across workspaces. **Dependencies
point one way**: no global type has a beamline parent or refers to a beamline type, which a
test asserts, so a workspace that has the shared set never needs another beamline's.

```
catalogue   59 types, all global          Product Models, Vendors, and anything else made from them
   ▲ hang from
   ├── sparc    44 types   123 IOCs, 305 devices, 22 templates …
   ├── btf      44 types    27 IOCs,  69 devices, 10 templates …
   └── euaps    44 types    52 IOCs,  95 devices,  5 templates …  + the PBS import
```

### Seeding

```bash
python backend/scripts/seed_asset_types.py global   catalogue
python backend/scripts/seed_asset_types.py beamline sparc --catalogue catalogue
python backend/scripts/seed_asset_types.py beamline btf   --catalogue catalogue
python backend/scripts/seed_asset_types.py all      single   # everything in one workspace, if there is only one
```

Each takes `--dry-run`. Nothing runs when a workspace is created, unlike tickets (5 types) and
documents (14): a workspace that only holds tickets has no use for object types in its tree.

- **Additive.** Re-running adds the attributes a type lacks and never overwrites or drops one a
  workspace has, so a release that adds a field reaches every workspace and none loses an edit.
- **Adopting.** A type an EPIK8s importer already made (uid `epik8s-…`, no parent) is the same
  thing, empty, and is adopted rather than duplicated. Seeding before or after an import gives
  the same result.
- **Renaming in place.** A workspace seeded before `Equipment Item` and `Place` became `Asset` and
  `Location` is carried across: the row keeps its uid, so every child and object that points at it
  still does, and only the name changes. A stale catalogue is named, not worked around.
- **Refusing copies.** A workspace that already hangs from a catalogue cannot be seeded in full,
  which would copy the shared types into it. The importers need no `--catalogue` after the first
  seeding: a workspace's own types have their parents in the catalogue, so it is known.
- **Extendable.** A beamline that needs a field nobody else has adds a child type in its own
  workspace, which inherits everything.

### What sharing a type costs

Measured on the three real configurations and the PBS workbook, with the catalogue seeded once
and each beamline seeded against it: SPARC's token sees **176 objects** of EuAPS's PBS import
(156 RF loads, couplers, mode converters and other components of shared types, and 20 areas) and
**none** of its control, structure or cost objects. That was the trade under the old rule, in
which an object of a shared type was readable everywhere. It is no longer: an object is shared
only when flagged (below), and an object made in a global workspace is flagged as it is made.

It is also why the engineering records are the beamline's own. They were first classed as shared,
and the same measurement then showed SPARC reading 408 of EuAPS's objects, among them its 179
procurement records, which carry prices. A cost is not something a classification should
publish, so `Engineering Record` moved to the per-beamline set; it is one line (`BEAMLINE_ROOTS`
in `asset_types.py`) to move anything.

### What it does not do

- **Objects are private by default.** Sharing a *type* shares its definition; an object is visible in
  another workspace only if it is flagged global, and that is meant for what is genuinely shared
  (product models, vendors, people, companies, inventory documents) and not for a beamline's own
  cameras and pumps. Objects made in a global workspace are flagged when they are made, and a
  migration flagged those already there. Search opens on "This workspace only", with "shared" one
  click away, and a shared object carries a badge naming the workspace that owns it.
- **The sidebar tree has a "Shared" group** below a workspace's own types, one section per owning
  workspace, and every count is the total for the type and everything beneath it.
- **Document types are still seeded per workspace.** Creating a workspace makes its 14 document
  types (`ensure_document_types`). Sharing them means it stops doing that, which is a separate
  decision. Documents themselves are shared one at a time, or by flagging the catalogue workspace.
- **Creating an object does not check the type's workspace.** `create_asset` accepts any type uid,
  so a token can attach an object to another workspace's private type. It is not new, but it was
  harmless while types were per-workspace.
- **Toggling a shared type's flag reaches beamline types.** Turning a global type off and on
  cascades to every descendant, in any workspace (`_cascade_global_to_children`), which would make
  a beamline's child types global. The seeder creates the shared types global directly; do not
  toggle them.

---

## 9. Bringing the control configuration in, with its relations to assets

This is the point of the control plane, so it is worth being explicit: **the configuration is
not imported as a document, it is imported as objects**, and the edges it already contains are
the edges root-cause analysis most wants.

Three real configurations were read for this design. "Devices" counts what `tools/epik8s-devices`
emits — one row per named device, plus one row for an IOC that lists none (469 listed devices
and 40 such IOCs):

| Configuration | IOCs | Devices | Distinct network addresses | Shared addresses | Devices behind a shared address |
|---|---|---|---|---|---|
| `epik8-sparc/deploy/values.yaml` | 123 | 340 | 138 | 27 | 203 |
| `epik8s-btf/deploy/values.yaml` | 27 | 74 | 41 | 7 | 37 |
| `epik8s-euaps/deploy/values.yaml` | 52 | 95 | 23 | 8 | 79 |
| **Total** | **202** | **509** | **202** | **42** | **319** |

**319 of 509 devices sit behind an address that something else also uses.** One Moxa fronting
24 motion channels; one host fronting 21 Raspberry-Pi laser controllers. When that box dies,
24 faults are filed and nothing connects them — unless the address is an object. That is what
`Access Point` is for, and it is why the control plane earns its place in an asset model.

### 9.1 What each part of `values.yaml` becomes

| YAML | Object | Relations created |
|---|---|---|
| the file itself, at a git revision | `Control Configuration` | `configures` → Facility |
| `beamline`, `namespace`, `giturl`, `gitrev`, `baseIp` | attributes of the above | |
| `iocDefaults.<template>` | `IOC Template` | `instance of` → Product Model, when the template's `asset:` resolves |
| `epicsConfiguration.services.<name>` | `Control Service` | `deployed on` → Facility; `declared in` → Control Configuration; `mounts` → Storage Mount |
| `epicsConfiguration.iocs.<name>` | `IOC` | `deployed on` → Facility; `templated from` → IOC Template; `connects to` → Access Point; `on network` → Control Network; **`drives` → Asset** |
| `iocs.<n>.devices[]` | `Control Device` | `provided by` → IOC; `reached through` → Access Point; **`acts on` → Beam Element or Asset** |
| `iocparam.server` / `.port`, device `ip`/`id`/`addr` | `Access Point` | `implemented by` → Network Device, when the address matches one |
| `networks[]` + `baseIp` + `address_list` | `Control Network` | |
| `nfsMounts[]`, `nfsBackups[]` | `Storage Mount` | |
| `ps:`, `motor:`, `pump:` rating blocks | `Control Device.settings` | `pump:` also → `enabled by` edges |
| `zones:` | `zone` attribute, and `part of` → Area | |

**As built.** `backend/scripts/import_epik8s.py <workspace> <values.yaml>` (and the same code
behind the import page) creates everything in that table except three things, which are still
open: `drives` and `acts on` (they need the `asset:` resolution of §9.2), `instance of` from a
template, and `implemented by` from an Access Point to a Network Device. Choices worth knowing:

- Two networks can both be called `control`; the **annotation** tells them apart, so `sparc-magnets`
  and `sparc-br-cams` are two objects and every IOC on one shares it.
- A template only the IOCs name (`ocem`, `caenels`: the recipe lives in the chart repository) is
  still one object, so "which IOCs share this recipe" is a graph query. SPARC has 22, of which 6
  are in no `iocDefaults`.
- A mount that a service and the top level both name is **one** object, matched by server and
  path, whatever it is called in each place.
- Every object carries `argus_facility`, the key tickets and documents use, so "everything about
  SPARC" is one filter across all three.
- `--dry-run` reads and reports in full and keeps nothing.

Run on the three files:

| | Configuration | Templates | IOCs | Devices | Access Points | Networks | Mounts | Services | Relations |
|---|---|---|---|---|---|---|---|---|---|
| SPARC | 1 | 22 | 123 | 305 | 138 | 3 | 6 | 20 | 1,442 |
| BTF | 1 | 10 | 27 | 69 | 41 | 1 | 6 | 17 | 360 |
| EuAPS | 1 | 5 | 52 | 95 | 23 | 1 | 4 | 16 | 539 |

"Devices" here are the ones a file lists (469). The 40 IOCs that list none are IOC objects; the
`tools/epik8s-devices` scan counts them as rows, which is why it reports 340, 74 and 95 (509).

The import also **reports** what the file says that is odd: the 42 SPARC IOCs with no `asset:`
link, and the two PVs configured on two IOCs.

### 9.2 The `asset:` field is already the link you want

83 of the 202 IOCs, 17 devices, 16 templates and 11 services in these three files carry an
`asset:` key. Its values are real, resolvable references:

```yaml
# epik8-sparc, ioc "sparctemp00"
asset: https://confluence.infn.it/display/LDCG/ICP-23-0032

# epik8-sparc, ioc "vac-midivac"
asset: https://servicedesk.infn.it/secure/ObjectSchema.jspa?id=32&typeId=1444&objectId=129573

# epik8-sparc, iocDefaults "agilent-vac"  ← a template, so this is the PRODUCT
asset: https://servicedesk.infn.it/secure/ObjectSchema.jspa?id=44&typeId=2505&objectId=129491
```

Two rules make these into edges:

1. **On an IOC or a device, `asset:` is the individual box** → `drives` / `acts on` →
   `Asset`.
2. **On an `iocDefaults` template, `asset:` is the product**, not a unit — one template
   deploys forty pumps → `instance of` → `Product Model`.

The Jira Service Desk URLs resolve mechanically. `jira_import.py:338-348` stores every
imported Insight object's URL as an `AssetLabel` of type `qrcode`, with
`metadata_json = {"source": "jira", "jiraObjectId": <id>}`. So:

```
parse objectId=129573 from the URL
  → SELECT asset_uid FROM asset_labels
      WHERE type='qrcode' AND metadata->>'jiraObjectId' = '129573'
  → create Relation(from=<the IOC>, to=<that asset>, relation_type='drives')
```

A Confluence URL has no object behind it; it becomes an `inventory_url` attribute and, once
the Confluence import has run, a `document_relations` row of type `describes`. Either way the
link is kept rather than dropped.

### 9.3 Cross-system dependencies the configuration already states

`rf-conditioning-gun` in SPARC lists nine ion pumps and the pressure above which it will not
raise RF power:

```yaml
pump:
  - {name: GUNSIP01, prefix: "SPARC:VAC:GUNVPC:", suffix: ":PRES_RB", tsh: "3E-7"}
  - {name: KLY1SIP1, prefix: "SPARC:VAC:KLY12VPC:", suffix: ":PRES_RB", tsh: "2E-7"}
  ...
```

This is a causal edge between the vacuum system and the RF system, written down in a file
nobody can query. Each entry becomes `enabled by` from the RF conditioning device to the pump's
control device, with the threshold kept in the source device's `settings` — `Relation` rows
carry no attributes, so the number has to live on an endpoint.

`epik8s_import.py:_cross_references` already does this for `enablepv:` and `pv:` keys inside
`settings`. Extending it to the `pump:` block adds 9 + 14 + 6 edges in SPARC alone, all of them
between systems that otherwise look unrelated.

### 9.4 What must not come in

`epik8s-btf/deploy/values.yaml` contains a `token:` at top level, and several services carry
`user:` / `password:` keys. The importer must strip anything matching
`token|password|secret|key|credential` before writing attributes — the hub is read by more
people than the deployment repository is, and an attribute bag is not a secret store. This is
worth fixing in the configuration too.

### 9.5 Inferring what the channels drive

> **Current target behavior:** the rules in this section infer Positions and functional topology,
> not authoritative physical Equipment. Each result is a ledger claim with a semantic rule id and
> evidence. Advisory relations such as screen–camera pairing enter review. Equipment comes from
> ARGUS inventory, and a confirmed Installation joins it to the Position. The paragraphs below
> describe the implementation baseline from which the migration starts.

A values.yaml lists control channels. It never lists the ion pump behind `GUNSIP01`, the
quadrupole and its power supply behind `QUATB002`, the camera at `AC101` or the electronics of a
BPM, and each of those is what fails, gets replaced and turns up in a report. With
**`--infer-elements`** (or `infer_elements: true` on the import request) the import makes them.
It is off by default, because these are inferences and not statements in the file, and that is a
real trade: §15 argues a person should sit between the configuration and the inventory, and this
option removes that step in exchange for having the objects at all. What it keeps of that
argument is that every inferred object says so.

```bash
python backend/scripts/import_epik8s.py sparc values.yaml --infer-elements [--dry-run]
```

**How a channel is read.** Two things carry the information and both are used. The device
metadata (`devgroup`, `devfunc`, `devtype`, `template`) is chosen by whoever wrote the file to
say what the hardware is, so it gives the asset type. The name gives the lattice element, which
metadata cannot: every magnet supply is `mag`, and only `QUA` in the name says it powers a
quadrupole.

| A channel or IOC that is… | becomes | and, where the name says |
|---|---|---|
| `mag`, any template | `Power Supply` (limits from `ps:`, maker from the template) | `Quadrupole`, `Dipole`, `Corrector` (plane H or V), `Solenoid`, `Sextupole`, which it `powers` |
| `vac`, name `SIP`/`IONP` | `Ion Pump` | |
| `vac`, name `NEG` | `NEG Cartridge` (the name wins over the controller's `ion`) | |
| `vac`, `turbo` / `TRB` | `Turbo Pump` (a TwisTorr 305 is the pump) | |
| `vac`, `scroll` / `PRY` | `Primary Pump` | |
| `vac`, `pig` / `VGA` `VUG` / `img` | `Vacuum Gauge` | |
| `cam`, not a simulator | `Camera` (`Basler-scA640-70gm` gives maker and model) | |
| an IOC that is BPM electronics | `Digitizer` (Libera Single Pass, or Spectra) | `Beam Position Monitor`, `realized by` it |
| a Libera Spectra: one box, several channels | one `Digitizer` | a `Beam Position Monitor` per channel |
| `libera-llrf` | `Low-Level RF Unit`, one per IOC (its `ad1`, `ad2` are its channels) | |
| a modulator IOC with no channels | `Modulator`, the IOC being the unit | |
| a modulator IOC that lists channels | a `Modulator` per channel (ELI's four) | |
| a `motor` IOC's channel | `Motor Axis` (`axis_id` from `axid`) | |
| …whose name has `FLG` (a flag) | `Actuator`, its `poi` as `position_labels` | a `Screen Station`, `composed of` the actuator, with the `poi` as `insertion_positions` |
| …that is an axis of a mirror (`FI4-HMN-01`, `FI8-PRH-01`, `FI3-MMR-001`) | `Motor Axis` | a `Mirror` (`FI4-MMIR-001`), `composed of` its axes |

**The rest of the chain, as options** (`--infer-controllers`, `--link-inventory`, `--it-workspace`,
and in the web import the same plus the AI):

| Option | makes | linked |
|---|---|---|
| infer controllers | a `Vacuum Controller` (IPCMini, IPC MPC, TPG 366/300/500) or `Motion Controller` (Pollux, PI GCS2, Thorlabs, SmarAct) per IOC whose `devtype`, template or name names one, `n_channels`/`n_axes` from its channels | `powers` what each channel drives; `reached through` the IOC's Access Point |
| IT workspace | the `Serial Converter`, `Server` or `Workstation` a hostname names, once per site, shared; an `Equipment Port` per TCP port a line uses (4003 → `P3`) | the Access Point `implemented by` it; the port `port of` it |
| link to the inventory | nothing, where the inventory already has the unit (same zone, code and number, or the same network address) | the channel `acts on` it, proposed in *Channels ↔ hardware* for a person to confirm |
| AI for unrecognised channels | a Provisional unit of the type the model picks, from the catalogue's equipment types only (rule `ai.epik8s.classify/1`) | the channel `acts on` it, proposed; nothing is effective until accepted in the review queue |

The control device `acts on` what it drives; an IOC `drives` a unit. Assets are of shared types
and elements of the beamline's own; both stay in the beamline that imported them, and an asset
becomes visible elsewhere only by being flagged global (§8).

**The plant.** Chillers, timing and what gates RF are read as well (`docs/knowledge-graph-design.md`
§5): a chiller channel is a `Chiller` and `cools` the gun, section or structure its name gives (ELI's
`MOD` cools every modulator); event receivers are timed by the beamline's one generator and trigger
what their names say (`LLRF`, `CAM`); and an RF conditioning IOC, which lists the pumps and gauges
whose pressure it will not raise power above, is `enabled by` each of them.

**Motors.** The template says the channel is an axis, so every motor channel is a `Motor Axis`
whatever its group. What the axis moves is in the file only for two cases, and only those get an
element. **A flag is a screen:** `GUNFLG01`, `AC1FLG01`, `FELFLG03A` and BTF's `TESTFLG` carry the
LNF code for a screen, and list the positions they can be driven to (`YAG`, `calibration`, `OUT`),
so each becomes an `Actuator` and a `Screen Station` composed of it. **A mirror is named by the EuAPS Utility Matrix.** `docs/EuAPS Utility Matrix.xlsx` says what the
motor codes are: the third field of its codes is the object a motor belongs to (`MMIR` the
main-laser mirror, `PMIR` the probe-laser mirror, `PAR` the parabolic mirror) and the fourth
what the motor does (`HMOT`, `VMOT`, `RMOT`: horizontal, vertical, rotation). The configuration
abbreviates them, so the rule reads the abbreviations back:

| In the configuration | In the matrix | Becomes |
|---|---|---|
| `FI4-HMN-01`, `FI4-VMN-01` | `FI4-C-MMIR-HMOT-001`, `…VMOT-001` | the two axes of `FI4-MMIR-001`, laser line `main` |
| `FI1-HPB-01`, `FI1-VPB-01` | `FI1-C-PMIR-HMOT-001`, `…VMOT-001` | the two axes of `FI1-PMIR-001`, laser line `probe` |
| `FI8-PRH-01`, `FI8-PRV-01` | `FI8-C-PAR-HMOT-001`, `…VMOT-001` | the two axes of `FI8-PAR-001`, a `Parabolic` mirror |
| `FI3-MMR-001` | `FI3-C-MMIR-RMOT-001` | the third (rotation) axis of `FI3-MMIR-001` |

The mirror is named as the matrix names it, so importing the matrix later reaches the same
object. Every other code on the same controllers is an axis and nothing more: `MPB` is the probe
delay line and in/out stage in the matrix (`PDEL`, `PIO`), and `HEX`, `DIP`, `SLT` and `PBM` are
stages it labels *slitte?* itself. Adding a code is one line in `element_inference.py`.
Cross-check: the matrix lists 11 main-laser and 10 probe-laser mirrors in the two FLAME areas; the
configuration drives 11 and 7. Where the two disagree on the rotation axis, the matrix has it at
`FP4` and the configuration at `FP2` (`FP2-MMR-001`, whose port carries a `TODO check`), and the
rule follows the configuration.

**A screen and its camera.** The file lists a flag and its camera on two IOCs with nothing joining
them; the names do. `AC1FLG01` is read with `AC101`, `UTLFLG02` with `UTL02`, and `FELFLG03A` and
`FELFLG03B` are two screens that share `FEL03`, so a station is also `composed of` the camera its
name pairs it with. In SPARC that pairs 22 of the 23 flags; `GUNFLG01` has no camera by that name and
is left without one. A camera with no flag (`CAT01`, `EOS01`, `LCR02`…) is not made a screen.

**What is left alone, and counted.** I/O channels, chillers, scope channels and timing modules
have no rule: a scope channel that measures a BCM is not a BCM. They are counted by
`devgroup/template` in the report (SPARC: 26 `io/icpdas`, 16 `diag/tektronix`, 8 `cool/smc`). A name that matches no
magnet code gets a supply and no element, because a quadrupole that is really a corrector is
worse in an inventory than an unlabelled one. Simulated cameras are skipped.

**What it makes, measured** on the four configurations (SPARC, BTF, EuAPS, ELI), each into a
beamline workspace hanging from one catalogue:

| | Assets | Elements | Of which |
|---|---|---|---|
| SPARC | 249 | 114 | 81 power supplies, 50 ion pumps, 42 motor axes, 26 cameras, 23 actuators, 10 BPM electronics, 8 gauges, 4 LLRF, 3 modulators, 2 NEG; 44 correctors, 23 screen stations, 17 quadrupoles, 10 solenoids, 10 BPMs, 8 dipoles, 2 sextupoles (22 of the 23 screens paired with a camera) |
| BTF | 62 | 44 | 44 power supplies, 14 motor axes, 3 cameras, 1 actuator; 16 quadrupoles, 14 correctors, 13 dipoles, 1 screen station |
| EuAPS | 94 | 19 | 52 motor axes, 9 turbo pumps, 9 primary pumps, 9 gauges, 15 cameras; 19 mirrors (11 main, 7 probe, 1 parabolic; 40 of the axes) |
| ELI | 87 | 29 | 35 ion pumps, 24 power supplies, 6 gauges, 6 cameras, 6 motor axes, 4 LLRF, 4 modulators, 2 Spectra units; 14 correctors, 5 BPMs, 6 solenoids, 3 quadrupoles, 1 dipole |

**Properties that make it safe to run and re-run.**

- **Marked.** Each has `argus_keywords: inferred` and a `description` naming the channel and the
  rule, so "everything that is only a guess" is one filter.
- **A person outranks it.** What is already on an inferred object stays: a serial, a location or a
  rewritten description survives every later read. Inference only fills what is missing.
- **Stable.** An asset's key is its channel's (`SPARC:AST:vac-gunvpc:GUNSIP01`), an element's is
  its name (`SPARC-ELM-GUNQUA01`), so a re-read updates rather than duplicates, and turning the
  option on after an import adds to it without disturbing what was there.
- **Typed by the catalogue.** It needs the catalogue's types and says so if they are missing.

**Not done.** No `instance of` to a `Product Model`: those are global objects that belong in the
catalogue workspace, and one import writes one workspace. A screen station is composed of its actuator and, by name, its
camera, but not of a scintillator or optics, which the file never mentions, and a person should
confirm the camera pairing.
An inferred asset is not matched to one already in the inventory (§9.2), so if the same pump is
already an object there are now two, and the `asset:` link is kept as `inventory_url` for whoever
merges them.

---

## 10. The engineering matrix: PBS, utilities and procurement

`docs/2026-06-11 - EuPRAXIA PBS_ver2.xlsx` is the second kind of source the catalogue has to
absorb, and it is nothing like a control configuration. Where `values.yaml` says how software
reaches hardware that already exists, the PBS says what will be built, who builds it, what it
costs and what the building must supply. Both describe the same components, from opposite ends
of their life.

The workbook, as read:

| sheet | rows | what it is |
|---|---|---|
| `UTILITY RF` | 179 components | the matrix itself: 61 columns per component |
| `WBS CODE` | 13 | WP-01 … WP-13, the work packages |
| `SYSTEM ZONE` | 6 zones + 15 component codes | INJ, LEL, CMP, HEL, PLS, FEL; RFG, XLN, SB3, … |
| `MODULE` | 2 + 3 | LA = Accelerating Module, LEL = Magnetic Module; S/D/A status legend |
| `AREA` | 20 | LNT Linac Tunnel, FTN Fel Tunnel, MHX1…MHX8 Modulator Halls, … |

This is one work package's worth — `WBS CODE` is `WP-04` on all 179 rows. The same matrix will
exist for WP-07 (Magnets and undulators), WP-08 (Beam Instrumentation) and the rest, so the
schema has to generalise rather than fit these 179 rows.

### 10.1 The PBS code is a grammar, and the catalogue should keep it as one

```
INJ  -  A  -  ACC  -  SB3M  -  001
 │       │     │       │        └── sequential number, kept as a string ("001", not 1)
 │       │     │       └────────── TYPE      what kind: SB3M, BDC, LOAD, GUN
 │       │     └────────────────── FAMILY    ACC, RF, WGS, WGX, RFS, RFX
 │       └──────────────────────── SYSTEM    A, R, I
 └──────────────────────────────── AREA/ZONE INJ, LEL, HEL, MHS1…MHX8
```

Stored whole in `pbs_code` (unique, indexed) **and** decomposed into `pbs_area`,
`pbs_system`, `pbs_family`, `pbs_type`, `pbs_sequential`. Both, not one: the whole code is how
people refer to a component, and the parts are how you ask "everything in MHX3" or "every
S-band structure" without a LIKE query. Every part is an `indexed` string, so each becomes an
autocompleting vocabulary derived from what is actually in use (§3).

The code system is internally consistent, which is worth saying because it means the
decomposition is safe: SYSTEM maps cleanly onto FAMILY across all 179 rows —
`I` → WGS (82) and WGX (17), `R` → RF (46), RFX (8) and RFS (3), `A` → ACC (22). The one
exception is the RF gun, which is coded `A`/`RF` because it is both a structure and a source.

**The object key is `FACILITY:PBS-CODE`** — `EUAP:INJ-A-ACC-SB3M-001` — the colon form the
control-plane keys already use (`SPARC:DEV:histar:GUNQUA01`). The facility prefix is what makes
it unique across the installation, and the PBS code is what everybody already calls the
component. It cannot be a photograph-friendly key (§7) and does not need to be: a planned
component has no label on it yet. When the box is installed and labelled, the `Asset`
made for it gets a §7 key, and `realized by` joins the two.

### 10.2 Column by column

| columns | becomes |
|---|---|
| B `DESCRIPTION` | the object's `name` |
| C `ID` | `sequence_index` (integer). It rises monotonically down the sheet, so it is probably order along the machine — **confirm before treating it as position**; do not silently map it to `s_position` |
| D `COMPONENT ID` | `component_id` (indexed) |
| E `WBS CODE` | `wbs_code`, and `assigned to` → `Work Package` |
| F `AREA/ZONE` | `pbs_area`, and `part of` → `Section` or `Area` |
| G `SYSTEM` · H `FAMILY` · I `TYPE` · J `SEQUENTIAL NUMBER` | `pbs_system`, `pbs_family`, `pbs_type`, `pbs_sequential` |
| K `PBS-CODE` | `pbs_code` (unique, indexed) |
| L `MODULES` | `module_code` **and** `station_name` — see §10.3 |
| M `STATUS` | `design_status`: `S` → Study, `D` → Defined, `A` → Approved |
| N `UNIT COST` · AX `TOTAL COST` | `Procurement Record.unit_cost_eur` / `.total_cost_eur` |
| O `NUM. OF UNITS` | `unit_count` |
| P `COMMENTS` | `description` |
| Q–Y electrical, rack units, connectivity | `Utility Requirement`, electrical group |
| Z–AB heat dissipation | `Utility Requirement`, heat group |
| AC–AK cooling water | `Utility Requirement`, water group |
| AL–AO air and humidity | `Utility Requirement`, air group |
| AP–AS compressed air | `Utility Requirement`, compressed-air group |
| AT–AU other gases | `Utility Requirement`, gas group |
| AW `DO NOT COMPILE FROM HERE` | a spacer; not imported |
| AY–BG year, semester, procurement, production and delivery time, supplier, RUP, funding line, CIG | `Procurement Record` |

So one row becomes **one `Engineered Item`, at most one `Utility Requirement` and at most one
`Procurement Record`**, plus edges to a `Work Package`, a `Section` and — where the row is part
of an assembly — an `RF Station` or a `Machine Module`.

### 10.3 What the workbook already shows is missing

The matrix is honest about being in progress, and three of its gaps are exactly what a schema
fixes rather than papers over.

**The utility columns are 6–17% filled.** Of 179 rows, 11 carry electrical data, 11 carry water
temperatures, 31 carry a flow rate, 19 carry heat-in-air. That is the argument for
`Utility Requirement` as a separate object: as attributes on the component they would be empty
on nine rows in ten, and "not yet specified" would be indistinguishable from "needs nothing".
As an object, a component either has one or it does not.

**Units are being negotiated inside the cells.** `WATER FLOW RATE (l/min)` contains
`4,2  (l/m oppure l/h)????????` on one row and `4.2` on the next; `MAX ACCEPTABLE TEMPERATURE
IN (°C)` contains `35+/-0,1`, which is a tolerance in a column meant for a limit. A `float`
named `Water flow rate (l/min)` forces the question once. The importer reads the number it can
(`35` from `35+/-0,1`), reports the cell, and keeps the original words on the record. It does not
read `+/-0,1` as a stability: nothing in the cell says what the tolerance is *of*.

**`MODULES` is carrying two facts.** Its 27 distinct values include bare module codes
(`INJ-LA-004`, `LEL-LA-001`) and station-plus-module strings (`X-BAND STATION 3 LEL-LA-002`,
`S-BAND STATION 1 INJ-LA002/003`). Fifteen rows share `X-BAND STATION 1 LEL-LA-001` — that is
an assembly with fifteen parts, written as a label because there was nowhere to put the
relationship. In the catalogue it is an `RF Station` object with fifteen `composed of` edges,
and the column splits into `station_name` and `module_code`.

One more gap worth naming: the `SYSTEM` column's three codes (`A`, `R`, `I`) have **no legend
sheet**, unlike AREA, MODULE and WBS CODE. Their meaning is inferable from the FAMILY
correlation above but should not be guessed at in the import — seed them as an indexed
vocabulary and ask the design team for the three descriptions.

### 10.4 Two matrices, one machine

A component ends up described from both ends, and the planes keep the two apart without
either overwriting the other:

```
PBS row       INJ-A-ACC-SB3M-001   S-band 3 m structure, WP-04, Approved,
                                   150 k€, 4.2 l/min, ΔT 25 °C
      │
      ▼  becomes
Accelerating Structure  EUAP-SB3M-0001        ← Functional Element
      ├── requires ──────▶ Utility Requirement  (4.2 l/min, ΔT 25 °C, 3 bar drop)
      ├── procured under ▶ Procurement Record   (150 k€, WP-04 funding line)
      ├── assigned to ───▶ Work Package WP-04
      ├── part of ───────▶ Machine Module INJ-LA-002
      └── realized by ───▶ (nothing yet — it has not been built)

values.yaml   later, once it exists and is powered
      └── Control Device  EUAPS:RF:SB3M01  ──acts on──▶ the same Accelerating Structure
```

The functional object is created by the PBS import years before the control configuration
mentions it, and the control import attaches to it rather than creating a second one. That
only works because the two importers agree on the object's identity — which is what `pbs_code`
and the §7 key scheme are for.

---

## 11. Worked examples

### 11.1 A quadrupole in SPARC

The configuration says this much (`epik8-sparc/deploy/values.yaml`, IOC `histar`):

```yaml
histar:
  name: histar
  iocprefix: SPARC:MAG:HISTAR
  zones: LINAC
  template: caenels
  ps: {current: {max: 30}}
  networks: [{name: control, annotation: sparc-magnets}]
  devices:
    - {name: GUNQUA01, ip: 192.168.0.28, geo: 5}
    - {name: GUNQSK01, ip: 192.168.0.27, geo: 4}
    - {name: PTLQUA04, ip: 192.168.0.37, zones: [LINAC, FEL], geo: 35}
```

Seven objects, four planes:

| Type | key | what it holds |
|---|---|---|
| `Quadrupole` | `SPARC-QUA-0001` | `lattice_name: GUNQUA01`, `s_position: 1.42`, `gradient: 4.6`, `family: GUNQ` |
| `Magnet Assembly` | `SPARC-MAG-0044` | `serial`, `coil_resistance`, `installed_on`, `argus_location` → Rack |
| `Power Supply` | `SPARC-PS-0027` | `manufacturer: CAEN ELS`, `model: Hi-Star`, `current_max: 30`, `serial` |
| `Product Model` | `PM-CAENELS-HISTAR` | `vendor: CAEN ELS`, `model_code: Hi-Star`, `device_class: Power Supply` |
| `IOC` | `SPARC:IOC:histar` | `template: caenels`, `pv_prefix: SPARC:MAG:HISTAR`, `zones: [LINAC]` |
| `Control Device` | `SPARC:DEV:histar:GUNQUA01` | `pv: SPARC:MAG:HISTAR:GUNQUA01`, `address: 192.168.0.28`, `geo: 5`, `settings: {ps.current.max: 30}` |
| `Access Point` | `NET:sparc:192.168.0.28` | `ip: 192.168.0.28`, `network: sparc-magnets` |

and the edges:

```
Quadrupole GUNQUA01 ──realized by──▶ Magnet Assembly SPARC-MAG-0044
Power Supply SPARC-PS-0027 ──powers──▶ Magnet Assembly SPARC-MAG-0044
Power Supply SPARC-PS-0027 ──instance of──▶ Product Model PM-CAENELS-HISTAR
Control Device …:GUNQUA01 ──acts on──▶ Quadrupole GUNQUA01
Control Device …:GUNQUA01 ──provided by──▶ IOC histar
Control Device …:GUNQUA01 ──reached through──▶ Access Point 192.168.0.28
IOC histar ──templated from──▶ IOC Template caenels
IOC histar ──on network──▶ Control Network sparc-magnets
IOC histar ──deployed on──▶ Facility SPARC
IOC histar ──declared in──▶ Control Configuration epik8-sparc@main
```

Swap the power supply and only `SPARC-PS-0027` changes: a new `Power Supply` object, a
`replaced` edge to the old one, the `powers` edge re-pointed. The quadrupole, its gradient, its
history of faults and every document written about it are untouched. That is what the extra
plane buys.

### 11.2 An ion pump, and the fault that reaches the RF system

```yaml
vac-gunvpc:
  iocprefix: SPARC:VAC
  iocroot: GUNVPC
  template: agilent-vac              # iocDefaults: devtype ipcmini, devgroup vac, devfunc ion
  zones: [LINAC, GUN]                # asset: …objectId=129491  ← the PRODUCT
  iocparam:
    - {name: server, value: scsparcsipmxa001.lnf.infn.it}
    - {name: port,   value: 4003}
  devices:
    - {name: GUNSIP00, channel: 145}
    - {name: GUNSIP01, channel: 146}
    - {name: GUNSIP02, channel: 147}
    - {name: GUNNEG01, channel: 148}
```

Four `Control Device` objects, one `Access Point`
(`scsparcsipmxa001.lnf.infn.it:4003`), four `Ion Pump` / `NEG Cartridge` equipment items, and
one `Product Model` — Agilent IPCMini — reached from the **template's** `asset:` URL, covering
all 46 IPCMini pumps at SPARC at once.

Then, from `rf-conditioning-gun`:

```
Control Device SPARC:DEV:rf-conditioning-gun:… ──enabled by──▶ Control Device …:GUNSIP01
    (settings.pump[GUNSIP01].tsh = 3E-7)
```

So the root-cause walk from a beam-down ticket is one traversal:

```
Ticket "no RF, gun conditioning won't ramp"
  → affects → Control Device rf-conditioning-gun
  → enabled by → Control Device GUNSIP01     (threshold 3E-7 mbar)
  → acts on → Ion Pump SPARC-VAC-0112
  → instance of → Product Model Agilent IPCMini
      → described by → Procedure "IPCMini controller replacement"   (global document)
  → reached through → Access Point scsparcsipmxa001:4003
      → also reaches 3 other pumps                                  ← is it the pump or the Moxa?
```

The last line is the question the hub exists to answer, and it is answerable only because the
shared address is an object.

### 11.3 BTF: a serial number hiding in an IOC name

```yaml
ocem-dvl644-ser23001:
  iocprefix: DAFNE:ACC:MAG:OCEME642
  template: ocem                     # devtype E642, devgroup mag
  zones: SICUREZZE
  ps: {current: {max: 650}, voltage: {max: 40}}
  iocparam: [{name: server, value: 192.168.192.21}, {name: port, value: 4001}]
  devices: [{name: DHPTT001, id: 5}, {name: DHPTT011, id: 6}]
```

`ser23001` and `dvl644` are a serial number and an inventory number, written into an IOC name
because the model has nowhere else to put them. With this catalogue they become
`Power Supply.serial = "SER23001"` and `.inventory_number = "DVL644"`, and the IOC keeps its
name without carrying the inventory on its back. Eight BTF IOCs are named this way.

### 11.4 A screen station: one element, two IOCs, four boxes

This is the case the composite types exist for, and SPARC already has it — split in two, with
nothing joining the halves. From `sparc-devices.csv`:

```
SPARC:tml-ch1:AC1FLG01    ioc tml-ch1      SPARC:MOT:TML:AC1FLG01   Motion Controller  Flag
SPARC:accameras:AC101     ioc accameras    SPARC:CAM:AC101          Data Acquisition   (empty)
```

Two rows. Two IOCs. Two systems — `Motion` and `Cameras`. One is a `Flag`, the other has no
`element` at all. A person reading the names knows `AC1FLG01` and `AC101` are the screen and
the camera of the same station in the first accelerating section; nothing in the database
does. When the image goes black, whether the camera failed, the actuator stuck or the terminal
server dropped is a question you answer by asking three people.

With the catalogue it is one element and four parts:

```
Screen Station  SPARC-FLG-0003        "AC1 screen station"     ← Beam Element / Diagnostic Element
  argus_system: Diagnostics · measures: Profile · is_invasive: true
  screen_type: YAG:Ce · calibration_um_per_px: 16.67 · insertion_positions: [IN, OUT]
  s_position: 4.85
  │
  ├── composed of ─▶ Scintillator Screen  SPARC-SCR-0003   YAG:Ce, 100 µm, ⌀25 mm
  ├── composed of ─▶ Camera               SPARC-CAM-0011   Basler scA640-70gm, GigE, 192.168.110.26
  ├── composed of ─▶ Actuator             SPARC-ACT-0003   TML axis, 2 positions
  ├── composed of ─▶ Optical Assembly     SPARC-OPT-0003   f = 50 mm, 0.5×
  │
  ├── part of ──────▶ Section  "AC1"
  └── measures ─────▶ Section  "AC1"

Control Device  SPARC:MOT:TML:AC1FLG01 ──acts on──▶ Actuator SPARC-ACT-0003
                                       ──provided by──▶ IOC tml-ch1
                                       ──reached through──▶ Access Point scsparctmlmxa001:400x
Control Device  SPARC:CAM:AC101        ──acts on──▶ Camera SPARC-CAM-0011
                                       ──provided by──▶ IOC accameras
                                       ──reached through──▶ Access Point 192.168.110.26
```

`px_calibration: 16.67` is already in the configuration, on the camera's `iocinit` — it is a
property of the *station*, not of the camera, because it depends on the optics and the screen
angle. Swap the lens and it changes while the camera does not. That is the kind of fact that
only has a correct home once the station is an object.

Now the same walk answers the question:

```
Ticket "AC1 screen image is black"
  → affects → Screen Station SPARC-FLG-0003
  → composed of → Camera, Actuator, Screen, Optics
        Camera   ← acts on ← SPARC:CAM:AC101        ← provided by ← IOC accameras
        Actuator ← acts on ← SPARC:MOT:TML:AC1FLG01 ← provided by ← IOC tml-ch1
                                                    → reached through → scsparctmlmxa001
                                                        → also reaches 23 other devices
  → and 4 tickets on that Moxa in the last year
```

Twenty-three other motion devices behind the same terminal server is the answer, and it is one
hop away only because the station, the actuator and the access point are all objects.

**What this needs from an importer.** Nothing automatic. The element decoder in
`tools/epik8s-devices/epik8s_devices/elements.py` already reads `FLG` → Flag and `CAM` → Camera
from the LNF naming convention, so it can *propose* that `AC1FLG01` and `AC101` belong to one
station on the shared `AC1` prefix — but proposing is where it should stop. The CLI's own
README makes this argument about `match`: evidence, not decisions. Composition is a statement
about the hardware, and a person signs it.

### 11.5 An RF station: fifteen PBS rows that are one thing

`X-BAND STATION 3` in the EuPRAXIA PBS is fifteen rows sharing a label:

```
MHX-R-RFX-XBND-003     MOD    Modulator, X-band                1 200 000 €
MHX3-I-WGS-PCMP-001    PCMP   Pulse compressor                   100 000 €
MHX3-I-WGS-BDC-001…005 BDC    Bidirectional coupler × 5           10 000 € each
MHX3-I-WGS-HYB-002     HYB    Hybrid                               8 000 €
MHX3-I-WGX-MCNV-001,2  MCV    Mode converter × 2                   5 000 € each
MHX3-R-RF-LOAD-001…005 RFL    RF load × 5                          8 000 € each
```

One `RF Station` object, fifteen `composed of` edges, each part its own `Asset` with
its own `Procurement Record`. The station carries `band: X-band`, `station_number: 3`,
`pbs_area: MHX3`; the modulator sits in `MHX` rather than `MHX3` and is shared, which the edge
records and the label could not.

The total cost of the station is then a sum over an edge rather than a column nobody
maintains, and "what does modulator MHX-R-RFX-XBND-003 feed" is answerable — which matters
because it feeds more than one station.

---

---

## 12. The schemas, as the API takes them

Three types written out in full, as `POST /v1/schemas` bodies. The rest follow the same shape;
`document_types.py::_attribute` is the emitter to copy.

```json
{
  "uid": "catalog:argus-object:item",
  "name": "Item",
  "description": "Anything the inventory holds. Carries the keys shared with tickets and documents.",
  "is_concrete": false,
  "parent_schema_uid": null,
  "applies_to": "objects",
  "metadata": {"source": "argus"},
  "attributes": [
    {"id": "description", "key": "description", "name": "Description", "type": "text"},
    {"id": "argus_facility", "key": "argus_facility", "name": "Facility", "type": "string", "indexed": true},
    {"id": "argus_system", "key": "argus_system", "name": "System", "type": "string", "indexed": true},
    {"id": "argus_subsystem", "key": "argus_subsystem", "name": "Subsystem", "type": "string", "indexed": true},
    {"id": "argus_keywords", "key": "argus_keywords", "name": "Keywords", "type": "string", "multiValue": true, "indexed": true},
    {"id": "argus_lifecycle", "key": "argus_lifecycle", "name": "Lifecycle", "type": "enumeration",
     "options": [{"id": "planned", "value": "Planned"}, {"id": "in_service", "value": "In service"},
                 {"id": "standby", "value": "Standby"}, {"id": "maintenance", "value": "Under maintenance"},
                 {"id": "faulty", "value": "Faulty"}, {"id": "decommissioned", "value": "Decommissioned"},
                 {"id": "scrapped", "value": "Scrapped"}]},
    {"id": "argus_criticality", "key": "argus_criticality", "name": "Criticality", "type": "enumeration",
     "options": [{"id": "safety", "value": "Safety-critical"}, {"id": "beam_critical", "value": "Beam-critical"},
                 {"id": "degrades", "value": "Degrades beam"}, {"id": "non_critical", "value": "Non-critical"}]},
    {"id": "argus_responsible", "key": "argus_responsible", "name": "Responsible", "type": "user"},
    {"id": "argus_source", "key": "argus_source", "name": "Source", "type": "enumeration", "readOnly": true,
     "options": [{"id": "manual", "value": "Created here"}, {"id": "epik8s", "value": "EPIK8s"},
                 {"id": "epik8s-devices", "value": "epik8s-devices"}, {"id": "jira", "value": "Jira"},
                 {"id": "git", "value": "Git"}]},
    {"id": "argus_source_ref", "key": "argus_source_ref", "name": "Source revision", "type": "string", "readOnly": true}
  ]
}
```

```json
{
  "uid": "catalog:argus-object:ion-pump",
  "name": "Ion Pump",
  "description": "A sputter-ion pump: the thing that trips when the pressure rises.",
  "is_concrete": true,
  "parent_schema_uid": "catalog:argus-object:vacuum-pump",
  "applies_to": "objects",
  "metadata": {"source": "argus"},
  "attributes": [
    {"id": "pumping_speed", "key": "pumping_speed", "name": "Pumping speed (l/s)", "type": "float"},
    {"id": "nominal_voltage", "key": "nominal_voltage", "name": "Nominal voltage (V)", "type": "integer"},
    {"id": "element_count", "key": "element_count", "name": "Number of elements", "type": "integer"}
  ]
}
```

Everything else an ion pump has — `serial`, `manufacturer`, `model`, `product_model`,
`argus_location`, `argus_system`, `argus_lifecycle` — is inherited. Its own list holds three
fields. That is the point of the hierarchy: `effective_attributes` merges the ancestor chain at
read time, and the UI badges the difference as "3 own + 19 inherited".

```json
{
  "uid": "catalog:argus-object:control-device",
  "name": "Control Device",
  "description": "A channel, axis, gauge or supply an IOC drives — what fails.",
  "is_concrete": true,
  "parent_schema_uid": "catalog:argus-object:control-item",
  "applies_to": "objects",
  "metadata": {"source": "argus"},
  "attributes": [
    {"id": "pv", "key": "pv", "name": "PV", "type": "string", "indexed": true},
    {"id": "pv_prefix", "key": "pv_prefix", "name": "PV prefix", "type": "string", "indexed": true},
    {"id": "beamline", "key": "beamline", "name": "Beamline", "type": "string", "indexed": true},
    {"id": "ioc", "key": "ioc", "name": "IOC", "type": "string", "indexed": true},
    {"id": "system", "key": "system", "name": "System (devgroup)", "type": "string", "indexed": true},
    {"id": "function", "key": "function", "name": "Function (devfunc)", "type": "string", "indexed": true},
    {"id": "devtype", "key": "devtype", "name": "Device type", "type": "string", "indexed": true},
    {"id": "device_class", "key": "device_class", "name": "Device class", "type": "string", "indexed": true},
    {"id": "element", "key": "element", "name": "Element it serves", "type": "string", "indexed": true},
    {"id": "vendor", "key": "vendor", "name": "Vendor (as found)", "type": "string", "indexed": true},
    {"id": "model_code", "key": "model_code", "name": "Model (as found)", "type": "string", "indexed": true},
    {"id": "zones", "key": "zones", "name": "Zones", "type": "string", "multiValue": true, "indexed": true},
    {"id": "channel", "key": "channel", "name": "Channel", "type": "integer"},
    {"id": "axis", "key": "axis", "name": "Axis", "type": "integer"},
    {"id": "address", "key": "address", "name": "Address", "type": "string", "indexed": true},
    {"id": "port", "key": "port", "name": "Port", "type": "string"},
    {"id": "interlock", "key": "interlock", "name": "Interlocked", "type": "boolean"},
    {"id": "geo", "key": "geo", "name": "Geographic index", "type": "integer"},
    {"id": "enable_pv", "key": "enable_pv", "name": "Enable PV", "type": "string"},
    {"id": "settings", "key": "settings", "name": "Settings and limits", "type": "text"},
    {"id": "inventory_url", "key": "inventory_url", "name": "Inventory link", "type": "string"}
  ]
}
```

Note the bare keys, matching what `epik8s_import.py` already writes. `port` is a **string**: the
importer stores `str(port)`, and a schema that said integer would describe something the data
is not. `element` and
`device_class` are new and `indexed`, so the values the epik8s-devices scan already produces
(15 elements, 10 device classes) become an autocompleting vocabulary rather than free text.

---

## 13. Every existing value has a home

The catalogue is only right if nothing currently recorded falls out of it. Checked against all
340 rows of `sparc-devices.csv`:

**`device_class` → an attribute value on `Control Device`, and the physical type it suggests**

A row of `sparc-devices.csv` describes a control channel — a PV, an address, an IOC — so it is a
`Control Device` (§11.1), and `device_class` is what it records, not what type it is. The right
column is the `Asset` a person would link it to, and what `match` can propose.

| device_class | rows | `Control Device.device_class` | suggests physical type |
|---|---|---|---|
| Power Supply | 81 | `Power Supply` | `Power Supply` |
| Motion Controller | 63 | `Motion Controller` | `Motion Controller`, `Motor Axis` |
| Vacuum | 60 | `Vacuum` | `Ion Pump`, `Turbo Pump`, `Vacuum Gauge`, `NEG Cartridge` — by `element` |
| Data Acquisition | 60 | `Data Acquisition` | `Digitizer`, `Camera`, `Instrument` — by `devtype` |
| I/O | 26 | `I/O` | `I/O Module` |
| Low-Level RF | 8 | `Low-Level RF` | `Low-Level RF Unit` |
| Cooling | 8 | `Cooling` | `Chiller` |
| Timing | 3 | `Timing` | `Timing Module` |
| Modulator | 3 | `Modulator` | `Modulator` |
| *(empty)* | 28 | empty, with `needs` recorded — **never guessed** | none |

Only three of these ten names (`Power Supply`, `Motion Controller`, `Modulator`) are also
catalogue type names. The other seven are why `tools/epik8s-devices push`, which today creates
one type per `device_class`, would still create seven flat types beside the catalogue — see §14.4.

**`element` → the functional or physical object the control device `acts on`**

| element | rows | acts on | plane |
|---|---|---|---|
| Ion pump | 46 | `Ion Pump` | physical |
| Flag | 23 | `Screen Station` | functional |
| Laser | 21 | `Laser System` | physical |
| Quadrupole | 16 | `Quadrupole` | functional |
| Beam position monitor | 15 | `Beam Position Monitor` | functional |
| Solenoid | 12 | `Solenoid` | functional |
| Beam charge monitor | 8 | `Beam Charge Monitor` | functional |
| Chiller | 8 | `Chiller` | physical |
| Vacuum gauge | 8 | `Vacuum Gauge` | physical |
| Klystron | 4 | `RF Amplifier` | physical |
| Undulator | 4 | `Undulator` | functional |
| Camera | 3 | `Camera` | physical |
| Modulator | 3 | `Modulator` | physical |
| NEG pump | 2 | `NEG Cartridge` | physical |
| Sextupole | 2 | `Sextupole` | functional |
| *(empty)* | 165 | no `acts on` edge — the gap stays visible instead of being filled in | |

This table is also the proof that `acts on` had to be polymorphic: seven of the fifteen
element values are hardware, not lattice elements.

**`system` → `argus_system`**, as an `indexed` string so it autocompletes and matches the
identical key on tickets and documents: Magnets 81, Motion 61, Vacuum 60, Diagnostics 38,
Cameras 27, I/O 26, RF 24, Cooling 8, Timing 3, empty 12.

**EuPRAXIA PBS `COMPONENT ID` → the type it becomes.** All 17 distinct codes across the 179
rows, none left over:

| code | rows | type | plane |
|---|---|---|---|
| `RFL`, `LOAD` | 49 | `RF Load` | physical |
| `BDC` | 43 | `Directional Coupler` | physical |
| `XBD` | 16 | `Accelerating Structure` (X-band) | functional |
| `MCV` | 16 | `RF Mode Converter` | physical |
| `MOD` | 11 | `Modulator` | physical |
| `PCMP` | 10 | `RF Pulse Compressor` | physical |
| `HYB` | 10 | `RF Hybrid` | physical |
| `WIN` | 8 | `RF Window` | physical |
| `ATT` | 4 | `RF Attenuator` | physical |
| `SB3`, `SB1.5` | 4 | `Accelerating Structure` (S-band) | functional |
| `XLN` | 2 | `Accelerating Structure` (linearizer) | functional |
| `PHS` | 2 | `RF Phase Shifter` | physical |
| `WGS` | 2 | `Waveguide Section` | physical |
| `RFG` | 1 | `RF Gun` | functional |
| `ISL` | 1 | `RF Isolator` | physical |

Ten of the fifteen rows in that table are types added for this workbook (§5.3). The split
between planes is not arbitrary: a structure the beam passes through is functional and has an
s-position; a coupler in the waveguide feeding it is a box with a serial number and no place in
the lattice.

The `SYSTEM ZONE` sheet's six zone codes (`INJ`, `LEL`, `CMP`, `HEL`, `PLS`, `FEL`) become
`Section` objects; the `AREA` sheet's 20 codes (`LNT`, `FTN`, `USR`, `MHS1`…`MHX8`) become
`Area` objects under `Building`; the `WBS CODE` sheet's 13 rows become `Work Package` objects.
`CMP` (Bunch Compressor) and `PLS` (Plasma) have no rows in this WP-04 matrix yet — they are
seeded as empty sections rather than invented.

**CSV column → where it lands**

| column | lands on |
|---|---|
| `key`, `name` | the object's `key` and `name` |
| `beamline` | `beamline`, and `part of` → Facility |
| `ioc` | `ioc`, and `provided by` → IOC |
| `pv` | `Control Device.pv` |
| `device_class` | the type itself, and `device_class` |
| `vendor`, `model` | `Product Model.vendor` / `.model_code`, and `instance of` |
| `element` | `element`, and `acts on` |
| `system` | `argus_system` |
| `physical_asset` | `drives` / `acts on` → Asset |
| `needs` | `argus_keywords`, so "what is still incomplete" is one filter |
| `connection` | `Access Point`, and `reached through` |
| `model_spec` | `Control Device.settings` |

---

## 14. What has to change in the code

Ordered by what blocks what. Items 1, 3, 4, 9, 10, 11 and 12–15 are done; the rest are open.

1. **DONE — `epicsConfiguration.iocs` may be a list or a mapping.** The beamline repositories
   have been moving it from a list of `{name: …}` entries to a mapping keyed by IOC name
   (`epik8-sparc` commit `6bca015`, "Convert epicsConfiguration.iocs from list to map"), and
   both importers assumed the list. Read as a list, a mapping yields nothing and says nothing:
   every entry is a string key, fails `isinstance(entry, dict)`, and is skipped, so an import
   reported success with zero IOCs. It was never visible in the tests, because their fixture
   uses the list form. `sparc-devices.csv` (340 rows) was generated before that commit.

   Fixed in both places with the same small helper, `_ioc_entries`, which accepts either
   shape and calls a mapping entry that omits `name` by its key:
   `backend/app/services/epik8s_import.py` and `tools/epik8s-devices/epik8s_devices/scan.py`.
   Measured on the real files, before and after:

   | file | iocs | shape | devices before | devices after |
   |---|---|---|---|---|
   | `epik8-sparc/deploy/values.yaml` | 123 | mapping | 0 | 340 |
   | `epik8s-btf/deploy/values.yaml` | 27 | mapping | 0 | 74 |
   | `epik8s-euaps/deploy/values.yaml` | 52 | mapping | 0 | 95 |
   | `epik8-sparc.orig` (older checkout) | 90 | list | 262 | 262 |

   The SPARC figure equals the 340 rows of `sparc-devices.csv`. Through the server importer the
   same files give 305, 69 and 95 listed devices, the difference being the IOCs that list none.
   Three tests added to `backend/tests/test_epik8s_import.py` and two to
   `tools/epik8s-devices/tests/test_scan.py`, deriving the mapping form from the existing list
   fixture so one fixture proves both shapes agree; the three backend ones fail with
   `assert 0 == 3` when the fix is removed.

2. **Same question for `services`**, which is a mapping in both the fixture and the real files,
   and is already handled correctly (`_services` iterates `.items()`). No change; noted so the
   fix to 1 does not "tidy" it in the wrong direction.

3. **DONE — the catalogue is seeded, in two sets.** `backend/app/services/asset_types.py` holds
   all 150 types as data (`CATALOGUE`), of which 81 are global and 69 are a beamline's own
   (§8), with `ensure_asset_types(db, workspace_id, scope, catalogue_workspace_id)`,
   `resolve_type_uids()` and `catalogue_of()`. Run with `scripts/seed_asset_types.py` in three
   modes: `global`, `beamline --catalogue`, and `all` for a hub with one workspace.

   It follows `document_types.py` with differences that are deliberate: **additive** rather than
   "refresh the base, leave the children"; it **adopts** importer-made `epik8s-…` types; it
   **renames in place** what was seeded as `Equipment Item` and `Place`; and it is **not** wired
   into `create_workspace`, for the reason in §8.

   `backend/tests/test_asset_types.py` (45 tests) checks the shape against this document,
   that the shared keys are spelled as tickets and documents spell them, that the two sets
   partition the catalogue and no shared type depends on a beamline type, that seeding is
   idempotent and additive, that the rename carries a seeded workspace across, that **every key
   the real importer writes is declared by the type it writes to**, and, through the REST API,
   that an object of a shared type is *not* readable from another workspace unless flagged global
   (and then not editable there), that one made in a global workspace is flagged as it is made, and
   that one of a beamline type is not readable at all.

4. **DONE — seeding and importing, in either order.** `epik8s_import.ensure_types()` finds each
   type where the catalogue put it (a workspace's own, then the catalogue it hangs from, then any
   other global), and makes an empty one only if nobody has it. Seeding first uses the typed
   types; importing first and seeding after adopts the importer's empty ones. Both are tested,
   and so is the case with no catalogue at all.

5. **Resolve `asset:` into edges** — §9.2. A helper that parses `objectId=` out of a Jira
   Service Desk URL and looks up `asset_labels.metadata->>'jiraObjectId'`, used for `drives`,
   `acts on` and (on templates) `instance of`.

6. **Extend `_cross_references`** to the `pump:` blocks, not just `enablepv`/`pv`.

7. **Strip secrets** before writing attributes (§9.4).

8. **The `argus_*` alias pass** for the control plane's bare keys, following
   `ticket_types.py::migrate_legacy_attributes`. Only after 3 and 4 are in and stable.

9. **DONE — the two epik8s paths write to one set of objects.** `tools/epik8s-devices push` used
   to create one type per `device_class` and objects under its own keys, beside the hub's import.
   It now writes `Control Device` objects of the catalogue's type, under the key and uid the
   import gives them (`SPARC:DEV:histar:GUNQUA01`), and adds only what a review can: the class of
   hardware, the element, the vendor and model as found, and the link to a physical asset. Run
   against the real SPARC file after its import: 340 scanned rows are 305 devices and 35
   IOC-only rows, **0 created** (every device was already there), 305 updated, and a second
   push writes nothing. A test in each package pins the same uid literal, so neither can drift.

10. **DONE — a PBS importer.** `backend/app/services/pbs_import.py`, run with
    `scripts/import_pbs.py <workspace> <workbook.xlsx> --facility EUAP [--catalogue <ws>] [--dry-run]`.
    It seeds the types it needs if they are not there (only the beamline's own when the workspace
    hangs from a catalogue, given or known; the whole catalogue in a hub with one workspace),
    reads every sheet with a `PBS-CODE` column, and writes per §10.2. In a split hub the
    components of shared types (RF loads, couplers, areas) stay in the workspace that imported them
    unless flagged global, and the
    accelerating structures, modules and stations, and every utility, procurement and work-package
    record, stay in the beamline. Run on `2026-06-11 - EuPRAXIA PBS_ver2.xlsx` it produces **463 objects
    and 937 relations**:

    | | |
    |---|---|
    | 179 components | of 13 catalogue types, e.g. 49 `RF Load`, 43 `Directional Coupler`, 22 `Accelerating Structure` |
    | 179 procurement records | one per row — every row carries a cost |
    | 40 utility requirements | only where a row says anything about utilities |
    | 13 work packages, 6 sections, 20 areas | from the three legend sheets |
    | 15 machine modules, 11 RF stations | from the `MODULES` column |
    | 937 relations | 383 `part of`, 179 `assigned to`, 179 `procured under`, 156 `composed of`, 40 `requires` |

    `X-BAND STATION 3` is composed of exactly the 15 rows the workbook labels with it: five
    loads, five couplers, two mode converters, a pulse compressor, a hybrid and the modulator.

    It reads the sheet as delivered and reports 71 things about it rather than fixing them:
    values that are more than a number (`4,2  (l/m oppure l/h)????????`, `35+/-0,1`,
    `30 ( Diode mode)`), a range in a one-value column (`50-88`), and `129` in a column headed
    *Electrical phases*. Each is reported with its cell and **kept as the words it was written
    in** on the record; a number is read only where the cell says one. Enumerations are written
    as labels (§3). `argus_lifecycle` is set to *Planned* — every state a PBS row can name is a
    design state — and never overwritten on a re-read, so a later *In service* survives. Running
    it twice creates nothing.

    25 tests in `backend/tests/test_pbs_import.py`, including one over the real workbook when it
    is in `docs/`, and one asserting every attribute the importer writes is declared by the
    catalogue **and passes its validation** — so an edit through the API never fails on a value
    the importer itself wrote.

11. **DONE — the legend sheets became objects**: 13 `Work Package`, 6 `Section`, 20 `Area`. Not
    enumerations, so they can carry a leader, a budget and documents.

12. **DONE — `Equipment Item` is `Asset` and `Place` is `Location`.** Renamed throughout; a
    workspace seeded under the old names is carried across in place (§8).

13. **DONE — `scripts/import_epik8s.py`, and the import writes the whole configuration.** It
    reads a `values.yaml` from disk into a workspace as objects of the catalogue's types, with a
    `--dry-run` that runs the import for real inside a transaction and discards it (the importer
    commits as it goes, so a rollback at the end would undo nothing). New objects: the Control
    Configuration, IOC Templates, Control Networks and Storage Mounts, with `declared in`,
    `templated from`, `on network`, `mounts` and `part of` (§9.1). 14 tests in
    `test_epik8s_configuration.py`.

14. **DONE — found by running it.** Pushing the reviewed SPARC file failed on four devices
    because `pv` was unique and the file configures two PVs on two IOCs. `pv` is now indexed, not
    unique, and the import reports the pair (§5.6). A second push also rewrote every object; it
    now writes only what changed. And `push` wrote `vendor` and `model_code`, which no type
    declared, which the API stores without complaint; both sides now pin the same list of keys.

15. **DONE — `--infer-elements`: the pumps, magnets, supplies, cameras, BPMs, LLRF and
    modulators the channels refer to (§9.5).** `backend/app/services/element_inference.py` holds
    the rules as functions of the configuration alone; the import applies them behind an opt-in
    (`--infer-elements`, and `infer_elements` on the API request). Checked against the SPARC, BTF,
    EuAPS and ELI files, which found two patterns the first rules got wrong: a Libera Spectra is
    one box with a BPM per channel, and a modulator IOC that lists channels has one modulator
    each. 72 tests in `test_element_inference.py` and `test_epik8s_inference.py`, the first
    running the rules over the real files when they are next to this repository.
    **Extended to motors:** every motor channel is a `Motor Axis`; a flag is an `Actuator` and a
    `Screen Station` composed of it and of the camera its name pairs it with; the axes of an EuAPS
    mirror are one `Mirror`, named as the EuAPS Utility Matrix names it (new type, so a beamline
    workspace seeded earlier needs `seed_asset_types.py beamline` run again).

---

## 15. Open questions

This is the baseline document's original question list. The normative revision resolves ownership,
Position/Equipment separation, global visibility, strong-identifier uniqueness, review queues, and
Jira/Insight migration. Items about source meaning and missing source data remain valid until their
named stakeholders answer them.

- **Who owns the lattice?** `s_position`, `gradient` and `k1` really live in a MAD-X or elegant
  file. Typing them by hand here will produce a second, wrong copy. The alternative is an
  importer that reads the lattice file, which is the same argument `tools/epik8s-devices`
  already makes about the control configuration. Until that exists, `Beam Element` objects
  should be created with `lattice_name` and left otherwise empty rather than guessed at.
- **One catalogue workspace, or one per facility?** This document assumes one global catalogue
  (§8). If SPARC and BTF disagree about what "Power Supply" means, that assumption breaks and
  the catalogue has to be copied rather than shared.
- **Where does `scan` stop and the server start?** (item 9 above). The CLI's README argues a
  person must sit between the configuration and the inventory. That argument is right, and it
  is also the reason the server-side importer exists in parallel. Pick one.
- **`is_concrete` buys nothing today.** If abstract types matter — and with 8 of them it starts
  to — the object create endpoint should refuse a non-concrete `schema_uid`.
- **`unique` does not span subtypes.** A serial unique across all equipment needs either a
  check at the service layer or acceptance that it is advisory.
- **What do `A`, `R` and `I` mean?** The `SYSTEM` column has no legend sheet, but
  `2026-07-01 - Analysis of Utility Matrix.xlsx` groups the letters by sheet: `RF(A-R-I)` holds all
  three, and the other letters have a sheet each (`M` magnets, `V` vacuum, `U` undulators,
  `B` diagnostics, `A` plasma, `W` laser and optics, `X` experiments, `T` target). The members say
  what the three RF letters are: `A` the accelerating structures (23 rows: gun, linearizer, S- and
  X-band structures), `R` the RF power sources (57: modulators, loads) and `I` the waveguide
  interconnections (99: couplers, hybrids, windows, attenuators, phase shifters). `A` is also the
  plasma letter, so it reads as *accelerating*. That is a reading of the members, not a legend, and
  the design team should still write it down.
- **Which objects should be flagged global by default?** An object made in a global workspace is.
  Whether the `Catalog Item` types (product models, vendors) should be global wherever they are made,
  and whether people and companies belong in the catalogue's types at all, is not settled.
- **`drives` and `acts on` to assets already in the inventory are still not made.** They need the
  `asset:` resolution of §9.2. With `--infer-elements` they now reach the objects the import makes
  itself; matching those to what the inventory already holds is the remaining link.
- **Which of the channels no rule covers should be read?** Motor axes were the largest group and
  are read (§9.5): an axis is an asset, and a flag or a mirror axis is also part of a screen
  station or a mirror. What remains is the ICPDAS I/O (26 channels in SPARC, 25 in ELI: RTD
  temperature sensors, relays, digital I/O), scope channels and chillers.
- **Who composes?** Composition (`composed of`) is a statement about hardware that no file
  states outright. The PBS importer does write it, from the workbook's own `X-BAND STATION 3`
  label, because there the file says so in as many words. The control configuration only implies
  it, with a naming convention (`AC1FLG01`, `AC101`). The import now composes a screen station
  with the camera that convention pairs it with (22 of SPARC's 23), marked inferred like
  everything else it makes; whether it should instead *propose* and wait for a review, and who
  owns that review, is still open.
- **The PBS import writes, and marks what it wrote.** A component approved in the PBS does not
  exist yet, so 179 planned components make the inventory describe the future. The importer sets
  `argus_lifecycle: Planned` and `argus_source: PBS workbook` on all of them, so "what is really
  installed" is one filter — but only for as long as nobody removes it.
- **Workbook defects worth returning to its authors:** two component codes are used but missing
  from the `SYSTEM ZONE` legend (`LOAD` on 3 rows, `WGS` on 2); the `SYSTEM` column's `A`/`R`/`I`
  has no legend at all; the `MODULE` sheet calls `LEL` a *Magnetic Module* while `SYSTEM ZONE`
  calls it the *Low Energy Linac*; and 15 of the 40 utility records carry a value that is not
  what its column says.
- **Should `asset_vision.KEY_PATTERN` accept `SPARC-QUA-0012`?** It reads `QUA-0012` out of that
  today. Allowing an optional middle group, `\b[A-Z][A-Z0-9]{1,9}(?:-[A-Z][A-Z0-9]{1,9})?-\d{1,8}\b`,
  would let readable keys resolve from a photograph; it is a change to shipped behaviour, so it
  is a decision.

---

## 16. AI extraction versus authoritative Equipment and Installations

> **Normative source:** [`asset-model-revision.md`](asset-model-revision.md) §23. This section
> applies its rules to the types and attributes of this catalogue.

The AI Intake reads what people would otherwise type: a nameplate photographed in a rack, a
datasheet, a delivery note, an inventory spreadsheet. What it reads is a **proposal** about a
record, never the record itself.

| What the model reads or suggests | What it becomes | What makes it authoritative |
|---|---|---|
| `manufacturer`, `model` from a nameplate or datasheet (§5.3) | an `ai_extracted` claim with the image region or text span | the owner's confirmation. The `photo-serial` rule keeps the value advisory until then |
| `serial`, `inventory_number` | an `ai_extracted` claim, risk R2. These are **protected predicates** (owner: Inventory) | a person with edit rights on the Equipment. No policy may auto-accept them |
| an object key or an Insight objectId read from a label | an `ai_resolved` binding candidate | auto-accepted only on an exact, unique, immutable-identifier match that a second field corroborates (R2-auto); otherwise reviewed |
| the type (`Ion Pump`, `Turbo Pump`, `Other Equipment` + `equipment_class`) | an `ai_classified` claim, restricted to the types usable in the workspace (§8) | the person creating or editing the record |
| `product_model` | a candidate match to an existing Product Model, or a proposal for a new one, which goes to the catalogue steward | the catalogue steward (revision §5.5) |
| technical specifications | proposals for attributes the type declares. A specification with no attribute is reported as missing, never stored as an ad-hoc key | the owner |
| "this unit is at `GUNSIP01`" | an Installation **proposal** (risk R4), with the evidence (photograph location, label, ticket) | the owner of the Position's workspace (revision §4.1), through the Installation workflow (revision §8) |
| "this unit replaced that one" | a swap proposal: ending one Installation and starting another as one batch | the Position's owner. Port maps and safety-classed segments also need the specialist (revision §9.3, D14) |
| a duplicate of an existing record | an identity candidate | a reviewer (revision §10). Never an automatic merge |

**What a channel name never becomes.** The inference rules of §9.5 read a channel into a
**Position**, and so does the AI Intake. Neither creates Equipment from `GUNSIP01`,
`QUATB002`, a hostname or a PV. From a channel, the model may propose a Position under the
granularity rule (revision §5.3, D5) and candidate links to Equipment that already exists.
A physical unit enters ARGUS as Equipment only when a person creates it, or confirms a proposal
to create it from physical evidence such as a nameplate, a delivery or an inventory record.

**The schema constrains the model.** The output schema of every intake operation is generated
from this catalogue: the types usable in the workspace, their declared attributes with data
types, enumerations and regexes, and the relation types of the registry. A value outside them is
rejected by validation (revision §23.4), not stored under a new key. This keeps the reserved keys
of §5 and the naming rules of §7 intact under AI entry.

**Capture in the field.** The Flutter field client (revision §24) uses the same rules as the web
form, with the same checklist and the same AI Intake.
- **Registration:** a technician who photographs a nameplate and registers a unit sends the same
  create request, with the same identifier checks (I-ID-1, A35).
- **Replacement:** a technician who replaces a unit sends one replacement command, which the
  server confirms, or turns into a proposal for the Position's owner.
- **Offline:** registrations and replacements recorded offline are pending commands. The server
  applies them later, after checking permission, identity and the version the technician saw.
- **Never from a name:** a scanned Position label, channel name or hostname never yields
  Equipment (I-MOB-6).

---

## 17. Summary

This table summarizes the baseline design and measurements. It is not the production acceptance
manifest. The current core hierarchy, governed relations, and recomputation of disputed counts are
specified by [`asset-model-revision.md`](asset-model-revision.md).

| | |
|---|---|
| Types | 150 (18 abstract), maximum depth 6: 81 shared (global), 69 a beamline's own (§8) |
| Roots | `Item` → Functional, Physical, Catalogue, Control, Engineering, Location |
| Relations | 5 existing, kept verbatim; 23 added |
| Composites | `Screen Station`, `Spectrometer Station`, `Emittance Meter`, `RF Station`, `Machine Module`, via `composed of` |
| Reserved keys honoured | `description`, `manufacturer`, `model`, `serial`; `argus_system`, `argus_subsystem`, `argus_facility`, `argus_keywords` |
| Configurations it must map | SPARC, BTF, EuAPS — 202 IOCs, 509 device rows, 42 shared addresses |
| Matrices it must map | EuPRAXIA PBS `ver2` — 179 components, 17 component codes, 61 columns; imported: 463 objects, 937 relations (§14.10) |
| Gaps it closes | all three named in `sparc-devices.csv`'s `needs` column |
| Seeder | `asset_types.py` + `scripts/seed_asset_types.py`, 27 tests, per-workspace and additive (§8) |
| Defect found and fixed | both importers read 0 IOCs from all three production files; now 202 IOCs / 509 rows (§14.1) |
