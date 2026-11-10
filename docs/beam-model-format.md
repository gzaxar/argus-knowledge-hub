# The ARGUS beam model format (`argus.beam-model/2`, `*.beam.json`)

The canonical, simulator-independent description of accelerators and beam-transport systems. The
Accelerator Model Toolbox and the Knowledge Hub share it. Simulator files (MAD-X, Xsuite, Bmad, Elegant,
Accelerator Toolbox…) are turned into it by converters ([§ 11](#11-converters-and-native-data)).

The model answers:

> *What exists along the beam path, where is it, how is it connected, what does it do to or measure from
> the beam, and which physical asset implements it?*

What a unit is, how it is powered and controlled, its state, documents and history are the Knowledge Hub's
and the control system's ([beam-asset-sync.md](beam-asset-sync.md) links the two).

* The library is `backend/app/beam_model_core/`: pure Python, no database, the same code in the Toolbox, a
  CI job and the hub.
* The JSON Schema is [`beam-model.schema.json`](beam-model.schema.json), generated from the object model and
  served at `GET /v1/beam-model/schema`. The v1 schema stays at
  [`beam-model-1.schema.json`](beam-model-1.schema.json) (`?version=1`).
* How the hub stores and serves models: [beam-model.md](beam-model.md).

Units are SI unless a field says otherwise: m, rad, m⁻² for `k1`, m⁻³ for `k2`, GeV for beam energies, MeV/c²
for rest masses, nm for wavelengths.

## 0. Assumptions reviewed

Before the schema, each concept was checked against the assumptions a lattice format usually makes. The core
model does **not** assume any of these:

| Assumption it does not make | How |
|---|---|
| a circular machine | a ring is a path with `topology: closed`; nothing else in the model knows about rings |
| charged particles | a beam is `particle` or `photon`; `charge`, `species`, `wavelength` are optional fields; capabilities say `particle_transport` or `photon_transport` |
| one beam, one path | `beams` and `paths` are lists; a path names the beams it carries; a component may be placed on several paths (a collider's interaction region) |
| one-dimensional topology | topology is the order of placements on each path plus explicit `connections` (branch, merge, continue) — a network, not a line |
| MAD-X naming or types | the vocabulary is the model's own; a simulator's class and parameters are kept in `native`; name-based kind guesses are a converter option, never the core's |
| every component acts on the beam | behaviour is capabilities; a girder or a fiducial is a component with no transport capability |
| every diagnostic is non-interceptive | `interceptive` / `non_interceptive` are capabilities; a screen intercepts, a BPM does not |
| aperture belongs to magnets | a boundary belongs to whatever produces it — a chamber, a bellows, a valve, a collimator, an iris — or lies along a path |
| every component has a physical asset | bindings are optional; virtual components (markers, reference points, interaction points) expect none |
| every model has optics, or geometry | both are datasets; a model with topology only is valid ([§ 12](#12-validation-and-completeness-levels)) |
| `s` identifies an object | `s` is a dataset value along one path; identity is the component id; a placement id disambiguates a component passed twice |
| element names equal asset names | assets are matched on many kinds of evidence, and a name match only proposes ([beam-asset-sync.md](beam-asset-sync.md)) |
| physics components and assets are one-to-one | a BPM has one primary asset plus hardware the Knowledge Hub connects; assets may have no component, components no asset |

What the v1 format did assume, and v2 drops:
* one path per element;
* a closed list of 20 kinds;
* diagnostics recognised by kind;
* bindings by name only;
* provenance per dataset only.

v1 documents are still read: they are upgraded without loss ([§ 13](#13-version-1-documents)).

## 1. The object model

```
Document  (schema_version: argus.beam-model/2)
├── model            id, name, source, version, git_commit, simulator, dataset
├── facility         id, name, namespace (stable names: dafne/accumulator/QUAA101), site
├── systems[]        a ring, a linac, a transfer line, a laser transport, an injector, an experiment line
├── beams[]          particle or photon; species, charge, rest_mass, reference_energy/momentum, wavelength
├── paths[]          ordered placements of components; open or closed; reference (s = 0), length
│   └── placements[] component (+ id when passed twice, + s/length for a single-dataset model, + reversed)
├── connections[]    branch | merge | continue between paths — explicit topology
├── definitions[]    reusable: type, capabilities, parameters, geometry, boundaries, material, states, native
├── components[]     instances: id, type or definition, family, aliases, capabilities, parameters, geometry
│                    (length, physical placement, alignment), boundaries, material, states, measurement_model,
│                    observes, mounted_on, contained_in, fiducials, native, provenance, tags
├── boundaries[]     restrictions along a path (s range) or of a component, not tied to one definition
├── observables[]    quantities beyond the built-in ones
├── datasets[]       design, nominal, commissioning, measured, current_model, snapshot…
│   ├── values{}     per component (or placement): s, reference-trajectory pose, physics, optics, native,
│   │                per-value provenance
│   ├── fields[]     a quantity along a path: [[s, value], …] (pressure, temperature, loss, field)
│   └── boundaries[] an aperture model for this configuration
├── external_bindings[]  component → physical asset: relation, target, status, authority, confidence,
│                        evidence, source (method, matcher, version), confirmed_by, timestamp
└── provenance       where the document came from: converter, source files
```

**Definitions and placements.** A definition is what a simulator reuses: `QUA1, type = quadrupole,
L = 0.3 m`. A component is an instance, with an identity that does not depend on the physical device
implementing it (`QUAA101`). Its *placement* is its place on a path. A component's effective description is
its definition, then its own fields, then the vocabulary's defaults (capabilities, a state set for a valve or
a screen).

**The physics position and the device are different things.** `QUAA101` is a position and a function; the
magnet installed there is a physical asset, bound by an external binding. Replacing the magnet changes the
binding, never the component.

## 2. Topology: a directed beam network

Nodes are placements; edges are:

| Edge | From → to | Example |
|---|---|---|
| next | consecutive placements of a path | `Q1 → BPM1` |
| closes | the last placement of a `closed` path → its first | the accumulator ring |
| branch | a placement on one path → the start (or a named placement) of another | `SEPT1 → line1`, `BSP01 → CAM01` |
| merge | the end of a path → a placement on another | injection into a ring |
| continue | the end of a path → the start of another | injector → main line |

`s` is never used to order anything. Each path has its own `s`, from its `reference`, and a branch starts
again from 0 if it likes ([fixture C](#14-test-models)). Every shape the requirements list needs no special
case:

```
LINAC            GUN01 → BUN01 → ACC01 → QUAL01 → BPML01 → ACC02 → DIPL01 → SCRL01 → DMPL01
STORAGE RING     SEPA101 → … → CHVA102 ─closes→ SEPA101 (one closed path)
TRANSFER NETWORK injector ─continue→ main: A_Q1 → B_BPM1 → SEPT1 ─branch→ line1 (… → DUMP1)
                                                                 └branch→ line2 (… → EXP1)
LASER            LSR01 → MIR01 → LNS01 → IRS01 → BSP01 → IP01;  BSP01 ─branch→ diagnostic-leg: CAM01
COLLIDER IR      positron-ring: ARC_P1 → QD0L → IP1 → QD0R → ARC_P2   (closed)
                 electron-ring: ARC_E1 → QD0R → IP1 → QD0L → ARC_E2   (closed; the same placements reversed)
```

Multiple sources, dumps, beams and interaction points are just more paths, placements and capabilities
(`beam_source`, `beam_destination`, `interaction_point`).

## 3. Components

```json
{"id": "QUAA101", "type": "quadrupole", "definition": "QUA1", "family": "QF", "aliases": ["MAG-ACC-QF01"],
 "capabilities": ["particle_transport", "focusing", "powered", "alignment_sensitive"],
 "parameters": {"length": 0.3},
 "geometry": {"alignment": {"design": {"x": 1.5833, "y": 0, "z": 0}, "surveyed": {"x": 1.5838, "y": 0, "z": 0.0002},
                            "offset": {"dx": 0.0005, "dz": 0.0002}, "surveyed_at": "2026-04-02"}},
 "mounted_on": "GIRDER_01",
 "native": {"format": "madx", "type": "QUADRUPOLE", "name": "QUAA101", "file": "dafne_accumulator.madx"}}
```

| Field | What |
|---|---|
| `id` | identity in the model; stable across versions |
| `type` | from [§ 5](#5-component-vocabulary); taken from the definition when absent. A type outside the vocabulary is kept, with a warning: it is then described by its capabilities and native data |
| `definition` | a `definitions[]` id |
| `family` | the model's own family name (QF, QD), not the vocabulary family |
| `aliases` | other names it is known by (an asset tag, a control name) — evidence for matching |
| `capabilities` | what it does ([§ 4](#4-capabilities)); defaults by type |
| `parameters` | normalised parameters that do not depend on a configuration (length, a design gradient) |
| `geometry` | `length`, `reference_point` (entry, centre, exit), `placement` (the physical object's pose in the hall), `alignment` (design, surveyed, offset, surveyed_at) |
| `boundaries` | [§ 6](#6-beam-boundaries-and-apertures) |
| `material` | [§ 7](#7-material-interaction) |
| `states` | [§ 8](#8-states) |
| `measurement_model`, `observes` | [§ 9](#9-diagnostics-observables-and-measurement-models) |
| `mounted_on`, `contained_in`, `fiducials` | [§ 10](#10-geometry-alignment-supports) |
| `native`, `provenance` | [§ 11](#11-converters-and-native-data) |

## 4. Capabilities

Capabilities are first-class: a component may have many, and they decide behaviour — a valve is
`aperture_limiting` like a collimator, a screen is `interceptive` like a wire. The vocabulary, which a model
may extend (unknown capabilities are kept, with a warning):

| Capability | Meaning |
|---|---|
| `particle_transport` | a charged or neutral particle beam passes through it |
| `photon_transport` | a photon (laser, synchrotron light) beam passes through it |
| `focusing` | focuses the beam in at least one plane |
| `defocusing` | defocuses the beam in at least one plane |
| `bending` | changes the direction of the reference trajectory |
| `steering` | deflects the beam by a small, adjustable angle |
| `horizontal_steering` | steers in the horizontal plane |
| `vertical_steering` | steers in the vertical plane |
| `acceleration` | changes the beam's energy |
| `deceleration` | takes energy from the beam |
| `deflection` | deflects the beam (transversely, in time or between paths) |
| `bunching` | changes the longitudinal bunch structure |
| `chromatic_correction` | corrects chromatic effects |
| `nonlinear_correction` | corrects or drives non-linear dynamics |
| `radiation_emission` | makes the beam radiate (undulator, wiggler, bend) |
| `branching` | sends the beam, or part of it, onto another path |
| `merging` | brings another path's beam onto this one |
| `pulsed` | acts only during a pulse (kicker, pulsed septum) |
| `beam_source` | where a beam is produced |
| `beam_destination` | where a beam ends: a dump, a target, an experiment |
| `interaction_point` | where beams collide or interact with a target |
| `diagnostic` | measures something about the beam |
| `interceptive` | puts material in the beam when in use |
| `non_interceptive` | measures without intercepting the beam |
| `beam_position_measurement` | measures the beam's centroid position |
| `beam_angle_measurement` | measures the beam's angle |
| `beam_profile_measurement` | measures the transverse distribution |
| `beam_size_measurement` | measures the beam size |
| `beam_intensity_measurement` | measures current, charge or particle number |
| `beam_energy_measurement` | measures energy or energy spread |
| `beam_loss_measurement` | detects beam losses |
| `beam_timing_measurement` | measures arrival time or bunch length |
| `optical_measurement` | measures a property of a photon beam (power, spectrum, wavefront…) |
| `aperture_limiting` | restricts the space available to the beam |
| `material_interaction` | the beam passes through or hits material |
| `vacuum_boundary` | is part of the vacuum envelope around the beam |
| `vacuum_isolation` | can separate two vacuum sections |
| `beam_protection` | protects equipment or people from the beam |
| `beam_interception` | stops or absorbs the beam on purpose |
| `powered` | needs a power supply to act on the beam |
| `movable` | can change position |
| `retractable` | can be moved in and out of the beam |
| `interlocked` | takes part in an interlock |
| `alignment_sensitive` | its alignment affects the beam |
| `survey_reference` | is a survey or alignment reference |
| `mechanical_support` | carries other components |
| `virtual` | a model concept with no physical object (marker, reference point, observation point) |

## 5. Component vocabulary

Families group types for filters and asset matching; they are not a class hierarchy. Each type's default
capabilities, and the catalogue type a position of that type is in the Knowledge Hub:

| Family | Type | Default capabilities | Hub catalogue type |
|---|---|---|---|
| magnet | `dipole` | particle_transport, powered, alignment_sensitive, bending | Dipole |
| magnet | `quadrupole` | particle_transport, powered, alignment_sensitive, focusing | Quadrupole |
| magnet | `sextupole` | particle_transport, powered, alignment_sensitive, chromatic_correction | Sextupole |
| magnet | `octupole` | particle_transport, powered, alignment_sensitive, nonlinear_correction | Generic Beam Element |
| magnet | `multipole` | particle_transport, powered, alignment_sensitive | Generic Beam Element |
| magnet | `solenoid` | particle_transport, powered, alignment_sensitive, focusing | Solenoid |
| magnet | `corrector` | particle_transport, powered, steering | Corrector |
| magnet | `kicker` | particle_transport, powered, steering, pulsed | Kicker |
| magnet | `septum` | particle_transport, powered, branching, aperture_limiting | Septum |
| magnet | `undulator` | particle_transport, radiation_emission, alignment_sensitive | Undulator |
| magnet | `wiggler` | particle_transport, radiation_emission, alignment_sensitive | Undulator |
| magnet | `generic_magnet` | particle_transport, powered, alignment_sensitive | Generic Beam Element |
| rf | `rf_cavity` | particle_transport, powered, acceleration | RF Cavity |
| rf | `accelerating_structure` | particle_transport, powered, acceleration | Accelerating Structure |
| rf | `buncher` | particle_transport, powered, bunching | RF Cavity |
| rf | `decelerating_structure` | particle_transport, powered, deceleration | RF Cavity |
| rf | `rf_deflector` | particle_transport, powered, deflection | RF Deflector |
| rf | `crab_cavity` | particle_transport, powered, deflection | RF Cavity |
| rf | `rf_gun` | particle_transport, powered, beam_source, acceleration | RF Gun |
| rf | `generic_rf` | particle_transport, powered | RF Cavity |
| diagnostic | `bpm` | diagnostic, non_interceptive, beam_position_measurement | Beam Position Monitor |
| diagnostic | `screen` | diagnostic, interceptive, beam_profile_measurement, material_interaction, retractable | Screen Station |
| diagnostic | `profile_monitor` | diagnostic, beam_profile_measurement | Generic Monitor |
| diagnostic | `wire_scanner` | diagnostic, interceptive, beam_profile_measurement, material_interaction, movable | Wire Scanner |
| diagnostic | `current_transformer` | diagnostic, non_interceptive, beam_intensity_measurement | Beam Charge Monitor |
| diagnostic | `dc_current_transformer` | diagnostic, non_interceptive, beam_intensity_measurement | Beam Charge Monitor |
| diagnostic | `wall_current_monitor` | diagnostic, non_interceptive, beam_intensity_measurement, beam_timing_measurement | Beam Charge Monitor |
| diagnostic | `faraday_cup` | diagnostic, interceptive, beam_intensity_measurement, beam_interception | Faraday Cup |
| diagnostic | `beam_loss_monitor` | diagnostic, non_interceptive, beam_loss_measurement | Beam Loss Monitor |
| diagnostic | `spectrometer` | diagnostic, beam_energy_measurement | Spectrometer Station |
| diagnostic | `bunch_length_monitor` | diagnostic, beam_timing_measurement | Bunch Length Monitor |
| diagnostic | `beam_arrival_monitor` | diagnostic, non_interceptive, beam_timing_measurement | Beam Arrival Monitor |
| diagnostic | `synchrotron_light_monitor` | diagnostic, non_interceptive, beam_size_measurement, beam_profile_measurement | Generic Monitor |
| diagnostic | `camera` | diagnostic, optical_measurement, beam_profile_measurement | Generic Monitor |
| diagnostic | `photodiode` | diagnostic, optical_measurement | Generic Monitor |
| diagnostic | `power_meter` | diagnostic, optical_measurement, interceptive | Generic Monitor |
| diagnostic | `wavefront_sensor` | diagnostic, optical_measurement | Generic Monitor |
| diagnostic | `optical_spectrometer` | diagnostic, optical_measurement | Generic Monitor |
| diagnostic | `emittance_meter` | diagnostic, beam_size_measurement | Emittance Meter |
| diagnostic | `generic_monitor` | diagnostic | Generic Monitor |
| injection_extraction | `stripping_foil` | particle_transport, material_interaction, interceptive | Material Element |
| injection_extraction | `injection_foil` | particle_transport, material_interaction, interceptive | Material Element |
| injection_extraction | `injection_element` | particle_transport, merging | Generic Beam Element |
| injection_extraction | `extraction_element` | particle_transport, branching | Generic Beam Element |
| interception | `collimator` | particle_transport, aperture_limiting, beam_protection, material_interaction | Collimator |
| interception | `scraper` | particle_transport, aperture_limiting, movable, material_interaction | Collimator |
| interception | `mask` | particle_transport, aperture_limiting, beam_protection | Collimator |
| interception | `absorber` | particle_transport, beam_interception, material_interaction, beam_protection | Collimator |
| interception | `beam_stopper` | particle_transport, beam_interception, beam_protection, retractable, interlocked | Beam Stopper |
| interception | `beam_dump` | beam_destination, beam_interception, material_interaction | Beam Dump |
| interception | `target` | beam_destination, material_interaction, interceptive | Material Element |
| interception | `protection_block` | beam_protection, aperture_limiting | Collimator |
| vacuum | `beam_pipe` | particle_transport, vacuum_boundary, aperture_limiting | Vacuum Element |
| vacuum | `vacuum_chamber` | particle_transport, vacuum_boundary, aperture_limiting | Vacuum Element |
| vacuum | `bellows` | particle_transport, vacuum_boundary, aperture_limiting | Vacuum Element |
| vacuum | `flange` | particle_transport, vacuum_boundary | Vacuum Element |
| vacuum | `transition` | particle_transport, vacuum_boundary, aperture_limiting | Vacuum Element |
| vacuum | `gate_valve` | particle_transport, vacuum_boundary, vacuum_isolation, aperture_limiting, movable, interlocked | Vacuum Element |
| vacuum | `fast_valve` | particle_transport, vacuum_boundary, vacuum_isolation, aperture_limiting, movable, interlocked | Vacuum Element |
| vacuum | `vacuum_window` | particle_transport, vacuum_boundary, vacuum_isolation, material_interaction | Vacuum Element |
| vacuum | `differential_pumping_section` | particle_transport, vacuum_boundary, aperture_limiting | Vacuum Element |
| vacuum | `pump_port` | particle_transport, vacuum_boundary | Vacuum Element |
| vacuum | `gauge_port` | particle_transport, vacuum_boundary | Vacuum Element |
| vacuum | `generic_vacuum` | particle_transport, vacuum_boundary | Vacuum Element |
| material | `foil` | material_interaction, interceptive | Material Element |
| material | `window` | material_interaction | Material Element |
| material | `wire` | material_interaction, interceptive | Material Element |
| material | `converter` | material_interaction, beam_source | Material Element |
| material | `gas_target` | material_interaction, interaction_point | Material Element |
| material | `gas_jet` | material_interaction, interaction_point | Material Element |
| material | `crystal` | material_interaction, deflection | Material Element |
| material | `generic_material` | material_interaction | Material Element |
| optical | `mirror` | photon_transport, steering, alignment_sensitive | Mirror |
| optical | `lens` | photon_transport, focusing, alignment_sensitive | Lens |
| optical | `beam_splitter` | photon_transport, branching, alignment_sensitive | Beam Splitter |
| optical | `polarizer` | photon_transport | Optical Element |
| optical | `waveplate` | photon_transport | Optical Element |
| optical | `optical_crystal` | photon_transport, material_interaction | Optical Element |
| optical | `grating` | photon_transport, deflection | Optical Element |
| optical | `prism` | photon_transport, deflection | Optical Element |
| optical | `aperture` | photon_transport, aperture_limiting | Optical Element |
| optical | `iris` | photon_transport, aperture_limiting, movable | Optical Element |
| optical | `optical_filter` | photon_transport, material_interaction | Optical Element |
| optical | `optical_amplifier` | photon_transport, powered | Optical Element |
| optical | `generic_optical` | photon_transport | Optical Element |
| source_destination | `electron_source` | beam_source, powered | Beam Source |
| source_destination | `positron_source` | beam_source, material_interaction | Beam Source |
| source_destination | `ion_source` | beam_source, powered | Beam Source |
| source_destination | `proton_source` | beam_source, powered | Beam Source |
| source_destination | `laser_source` | beam_source, photon_transport, powered | Beam Source |
| source_destination | `photon_source` | beam_source, photon_transport | Beam Source |
| source_destination | `generic_source` | beam_source | Beam Source |
| source_destination | `experimental_target` | beam_destination, material_interaction | Generic Beam Element |
| source_destination | `interaction_point` | interaction_point, virtual | Generic Beam Element |
| source_destination | `beam_destination` | beam_destination | Generic Beam Element |
| mechanical | `girder` | mechanical_support | Support Element |
| mechanical | `support` | mechanical_support | Support Element |
| mechanical | `mover` | mechanical_support, movable, powered | Support Element |
| mechanical | `translation_stage` | mechanical_support, movable, powered | Support Element |
| mechanical | `rotation_stage` | mechanical_support, movable, powered | Support Element |
| mechanical | `fiducial` | survey_reference | Support Element |
| mechanical | `alignment_reference` | survey_reference | Support Element |
| model | `drift` | particle_transport | Drift |
| model | `marker` | virtual | Generic Beam Element |
| model | `reference_point` | virtual | Generic Beam Element |
| model | `observation_point` | virtual | Generic Beam Element |
| model | `thin_lens` | particle_transport, virtual | Generic Beam Element |
| model | `generic` | — | Generic Beam Element |

Spellings normalised on read: `bend` → `dipole`, `blm` → `beam_loss_monitor`, `cavity` → `rf_cavity`, `dcct` → `dc_current_transformer`, `dump` → `beam_dump`, `hkicker` → `corrector`, `ict` → `current_transformer`, `instrument` → `generic_monitor`, `ip` → `interaction_point`, `monitor` → `generic_monitor`, `otr` → `screen`, `rbend` → `dipole`, `rfcavity` → `rf_cavity`, `sbend` → `dipole`, `slm` → `synchrotron_light_monitor`, `source` → `generic_source`, `valve` → `gate_valve`, `vkicker` → `corrector`, `wcm` → `wall_current_monitor`, `yag` → `screen`.

## 6. Beam boundaries and apertures

The space available to the beam, whatever restricts it. A boundary is a `profile` and where it applies:

```json
{"id": "VLV1-open", "when_state": "OPEN", "profile": {"shape": "circle", "radius": 0.018}}
{"id": "model-aperture", "path": "line", "s_start": 0.4, "s_end": 0.6, "kind": "model",
 "profile": {"shape": "ellipse", "semi_axis_x": 0.03, "semi_axis_y": 0.019}}
```

* **Shapes:**
  * `circle` (radius);
  * `ellipse` (semi_axis_x, semi_axis_y);
  * `rectangle` (half_width_x, half_height_y);
  * `racetrack` (+ corner_radius);
  * `polygon` and `custom` (points).

  Each takes `offset_x`/`offset_y` from the beam axis.
* **Where it applies:**
  * On a component (or its definition), `s_start`/`s_end` are relative to the component's entry, the whole
    length by default.
  * Along a path (`path` given) they are along that path.
  * In a dataset, it is an aperture model for that configuration.
* **State.** `when_state` limits a boundary to a state: a scraper `IN`, a valve's bore when `OPEN`.

`GET /v1/beam-models/{id}/aperture?path=&from=&to=&state=SCP1:IN` (or `queries.limiting_aperture`) answers
*what is the limiting aperture between A and B, and which component produces it*. Every boundary reduces to
one shape-independent measure: the free half-aperture along ±x and ±y from the axis, and the inscribed
radius (exact for centred circles, ellipses, rectangles and racetracks; offset shapes and polygons by ray
casting). The answer names the component, its type and family, the boundary and the state assumed. In
fixture E the vertical limit is the collimator's jaws (6 mm) and the horizontal limit the partly closed
valve's bore (18 mm), not a magnet. With the scraper `IN`, it is the scraper (3 mm).

## 7. Material interaction

What the beam meets, for engines that simulate it; the model only describes:

```json
"material": {"material": "YAG:Ce", "thickness": 1e-4, "density": 4.57, "radiation_length": 0.0254,
             "interaction_length": null, "orientation": {"angle": 0.785}}
```

Any component may carry one: windows, foils, screens, wires, targets, converters, crystals, collimator jaws.

## 8. States

Possible states and what each means for the beam — never the current state, which the control system
supplies:

```json
"states": {"states": [{"name": "OPEN", "meaning": {"beam_passes": true}},
                      {"name": "CLOSED", "meaning": {"beam_passes": false}},
                      {"name": "MOVING", "meaning": {"beam_passes": false}},
                      {"name": "FAULT", "meaning": {"beam_passes": null}}],
           "default": "OPEN",
           "mappings": [{"signal": "status", "value": 1, "state": "OPEN"}, {"signal": "status", "value": 0, "state": "CLOSED"}]}
```

* **`default`** is the state the static model assumes (normal operation), used by the aperture query.
* **`mappings`** turn an external signal's value into a semantic state. The signal's identity lives in the
  Knowledge Hub.
* **Defaults by type:** movable types without their own state set get these, the first being the default:

| Type | States |
|---|---|
| `gate_valve` | **OPEN**, CLOSED, MOVING, FAULT |
| `fast_valve` | **OPEN**, CLOSED, MOVING, FAULT |
| `screen` | **OUT**, IN, MOVING |
| `beam_stopper` | **RETRACTED**, INSERTED, MOVING |
| `kicker` | **OFF**, READY, ARMED, FAULT |
| `scraper` | **OUT**, IN, MOVING |
| `wire_scanner` | **PARKED**, SCANNING |

## 9. Diagnostics, observables and measurement models

A diagnostic is a component with the `diagnostic` capability that `observes` quantities. A measurement model
says, optionally, how it derives them; channel names and values are never here (they are external bindings
and the control system).

```json
{"id": "BPSA11", "type": "bpm", "capabilities": ["diagnostic", "beam_position_measurement", "non_interceptive"],
 "observes": ["beam.position.x", "beam.position.y"],
 "measurement_model": {"type": "centroid", "observables": ["beam.position.x", "beam.position.y"]}}
```

Measurement models: `centroid`, `current`, `custom`, `energy`, `histogram`, `image`, `integrated_charge`, `loss_rate`, `polarization`, `power`, `profile`, `spectrum`, `time_of_arrival`, `wavefront`. Built-in observables (others are declared in `observables`, lowercase dotted):

| Quantity | Unit | Domain | Plane |
|---|---|---|---|
| `beam.position.x` | mm | particle | x |
| `beam.position.y` | mm | particle | y |
| `beam.angle.x` | mrad | particle | x |
| `beam.angle.y` | mrad | particle | y |
| `beam.size.x` | mm | particle | x |
| `beam.size.y` | mm | particle | y |
| `beam.profile.x` | — | particle | x |
| `beam.profile.y` | — | particle | y |
| `beam.intensity` | mA | particle | none |
| `beam.charge` | nC | particle | none |
| `beam.energy` | MeV | particle | none |
| `beam.energy_spread` | — | particle | none |
| `beam.loss` | — | particle | none |
| `beam.bunch_length` | ps | particle | z |
| `beam.arrival_time` | ps | particle | z |
| `optical.power` | W | optical | none |
| `optical.energy` | J | optical | none |
| `optical.profile` | — | optical | none |
| `optical.spectrum` | — | optical | none |
| `optical.wavefront` | — | optical | none |
| `optical.polarization` | — | optical | none |
| `optical.pulse_duration` | fs | optical | z |
| `optical.position.x` | mm | optical | x |
| `optical.position.y` | mm | optical | y |

The chain the hub resolves from a BPM: physics observable → diagnostic model → physical diagnostic (bound) →
electronics (`connected to`) → control signal (`signal for`/`measures`) → live value (control system).

## 10. Geometry, alignment, supports

* **The reference trajectory** at a component is a dataset value: `values.geometry` (`x y z yaw pitch roll`,
  facility frame, the entry point). A `survey` dataset gives it for a whole path. Converters compute one from
  lengths and bends, and a ring whose bends sum to 2π closes.
* **The physical object** is `geometry.placement` (its own pose) and `geometry.alignment` (design, surveyed,
  offset, survey date). Neither is required.
* **Viewers** draw unrolled (along `s`, each component its length wide) or in 2D/3D from either pose. A ring,
  a linac, a transfer line and a laser line use the same fields.
* **Supports.** `mounted_on` names the girder, support or mover a component sits on; supports may themselves
  be mounted on movers. `fiducials` names the fiducials that locate a component or a support. This answers
  *which beam elements move if GIRDER_01 moves* (`queries.moves_with`) and *which fiducials define the
  alignment of Q1* (`queries.fiducials_of`: its own, else its supports').
* **Containment.** `contained_in` names an assembly or chamber.

```
Q1 ─┐
Q2 ─┼── mounted_on → GIRDER_01 ── fiducials: FID_G01_A, FID_G01_B
Q3 ─┘
```

## 11. Converters and native data

Importing must not throw away what the simulator said:

* **The component's native identity:** `native` holds `format`, `file`, `name`, `type` and `location`
  (file:line when known).
* **Native parameters, per dataset:** each dataset value keeps the simulator's own `native.parameters`
  whole.
* **Value provenance:** `provenance` per value says where a normalised value came from:

```json
"QUAA101": {"s": 1.4333, "physics": {"length": 0.3, "k1": 4.30926},
            "native": {"format": "madx", "type": "QUADRUPOLE", "parameters": {"L": 0.3, "K1": 4.30926}},
            "provenance": {"k1": {"source": "madx", "file": "strengths.str", "symbol": "qk1", "line": 12}}}
```

**MAD-X mapping example.**

```
qf: quadrupole, l=0.3;                    definitions: {"id": "QF", "type": "quadrupole", "parameters": {"length": 0.3},
quaa101: qf, k1=kqf;                                      "native": {"format": "madx", "type": "QUADRUPOLE", "name": "QF"}}
acc: sequence, l=32.56, refer=centre;     components:  {"id": "QUAA101", "type": "quadrupole", "definition": "QF",
  quaa101, at=1.5833;                                     "family": "QF", "native": {"format": "madx", "type": "QUADRUPOLE",
endsequence;                                              "name": "QUAA101", "file": "acc.madx"}}
                                          paths:       {"id": "acc", "topology": "closed", "placements": ["QUAA101", …]}
                                          values:      {"s": 1.4333 (centre − L/2), "physics": {"length": 0.3, "k1": 4.30926},
                                                        "native": {"parameters": {"L": 0.3, "K1": 4.30926}},
                                                        "provenance": {"k1": {"source": "madx", "symbol": "K1"}}}
```

**Converters provided.** Each is a pure function, in `backend/app/beam_converters/`. They are reached through
`POST /v1/beam-model/convert` (the result is shown before anything is imported) or as a library.

| Converter | Reads |
|---|---|
| `madx` | sequences (`REFER`, `AT … FROM`), `LINE`s with repetition and reversal, variables (`:=` deferred), inheritance (an element made from a user's definition gets it as `definition` and `family`), `BEAM`, `USE`. Several sequences and no `USE`: one path each, in one model, a component once however many paths place it, with what differs reported (`conversion.differs`, `conversion.conflicts`). `same_element_suffixes` makes `Q_IN` and `Q_OUT` one component. Macros, `IF`/`WHILE`, `CALL` are reported, not executed |
| `madx-tfs` | a TWISS table: positions, strengths, optics columns |
| `elegant` | `.lte`: definitions, RPN expressions with `sto`, `LINE`s, `USE` |
| `bmad` | `.bmad`: variables, inheritance, `LINE`s, `USE`, `parameter[particle/e_tot/p0c]`, bends by `angle`, `g` or `rho`, collimator limits as boundaries; `call`/`superimpose`/`overlay`/`group` reported |
| `xsuite` | a line as JSON (`element_names`, `elements`, `particle_ref`): thick and thin elements, order-0 multipoles as correctors, `Limit*` apertures as path boundaries |
| `at` | pyAT JSON: `FamName` families as definitions, `PolynomB` (k_n / n!) to k-values, `KickAngle`, cavities, `EApertures`/`RApertures` as boundaries |

Every converter:
* **Kinds:** takes the kind from the simulator's class. Only where the class cannot say does the name refine
  it (`KCK…` kicker, `SEP…`/`SPT…` septum, `BPM…` bpm); `name_hints: false` turns that off.
* **Drifts and markers:** leaves them out unless asked (`keep_drifts`, `keep_markers`).
* **Repeats:** names repeated elements `QF`, `QF#2`, and makes their definition.
* **Survey:** computes the survey.
* **Output:** writes v2 (`output: "1"` for the old form).

The same ring written in all six formats gives one model (`tests/test_beam_converters.py`). Other tools
(laser optics, custom formats) write canonical JSON directly or register a converter.

## 12. Validation and completeness levels

`validation.load(doc)` (and `POST /v1/beam-model/validate`) returns errors, warnings and the completeness
levels reached. A model need not hold everything:

| Level | Requires | Means |
|---|---|---|
| TOPOLOGY | — | paths, components and connections are consistent |
| LATTICE | TOPOLOGY | every beam-acting component on a path has a strength (dipole angle, quadrupole k1, cavity voltage…; correctors may be at zero) |
| GEOMETRY | LATTICE | every placement has coordinates (a survey dataset, or the object's placement) |
| OPTICS | LATTICE | an optics dataset on every path |
| PHYSICAL | TOPOLOGY | the beam's surroundings: boundaries, or vacuum or interception components |
| INTEGRATED | TOPOLOGY | every physical component is bound to an asset (confirmed) |

A topology-only model is valid; a MAD-X sequence without survey is LATTICE (and GEOMETRY once the converter's
survey is in); an asset binding is never required. The report's `gaps` say what is missing for each level.

**Errors** (the document is refused):
* duplicate ids;
* references to unknown systems, beams, paths, components, definitions, fiducials, supports or observables;
* a component without a type and without a definition;
* `mounted_on` or `contained_in` pointing at itself;
* connections naming unknown paths or placements;
* a reference not placed on its path;
* duplicate placement ids on a path;
* boundaries naming neither a path nor a component;
* malformed profiles;
* `s_end` before `s_start`;
* field samples out of order;
* dataset values for components not on the dataset's path;
* a measurement model deriving what the component does not observe;
* states naming undefined states;
* bindings with an unknown relation.

**Warnings** (kept, reported):
* types or capabilities outside the vocabulary;
* a component observing without the `diagnostic` capability;
* `mounted_on` a component that does not declare `mechanical_support`;
* an unknown measurement-model kind;
* empty paths.

## 13. Version 1 documents

`argus.beam-model/1` documents are upgraded on read (`upgrade.upgrade`):
* `elements` become components, and `paths[].elements` become placements;
* `branches` become `branch` connections;
* beams embedded in systems become top-level beams;
* kinds map (`source` → `generic_source`, `dump` → `beam_dump`);
* capabilities map (`beam_transport` → `particle_transport`, or `photon_transport` on a photon line);
* element-level values are filed into datasets as v1 did.

The hub keeps validating v1 documents by the v1 rules (its closed kind list, one path per element). When a
v1 document updates a model stored as v2 (an old client), what v1 cannot say is carried over. The web editor edits v2.
`?format=1` exports the old form; v1 bundles (`argus.beam-model-bundle/1`) and v2 bundles
(`argus.beam-model-bundle/2`, key `schema_version`) are both read.

## 14. Test models

Fixtures are in `backend/tests/fixtures/beam_model/`, written by `make_v2_fixtures.py`:

| | Fixture | Shows |
|---|---|---|
| A | `ring.beam.json` + `ring_assets.json` | closed ring with extraction branch; dipoles, quadrupoles (definition `QUA1`), sextupoles, correctors, kickers (states), septa, BPMs (measurement model), vacuum chamber, bellows, gate valves (states, open bore), a girder with fiducials and alignment, a marker; design, measured and vacuum-snapshot datasets; mock Knowledge Hub assets with matching and non-matching names |
| B | `linac.beam.json` | source → buncher → RF → quadrupole → BPM → RF → dipole → screen (material, image model) → dump; open |
| C | `transfer.beam.json` | injector ─continue→ main → septum ─branch→ line 1 → dump, ─branch→ line 2 → experiment; every path its own `s` |
| D | `laser.beam.json` | photon beam; laser → mirror → lens → iris → beam splitter → IP, camera on a branch; survey |
| E | `aperture.beam.json` | magnet bore, chamber, bellows, partly restrictive valve, collimator, scraper, a model aperture along the path |
| F | `collider_ir.beam.json` | two beams, two closed paths sharing an interaction region passed in opposite directions |

## 15. Examples

**Canonical document** (abridged from fixture A):

```json
{
  "schema_version": "argus.beam-model/2",
  "model": {"id": "dafne-accumulator-v2", "name": "DAΦNE Accumulator", "version": "2026.2", "simulator": "madx"},
  "facility": {"id": "dafne", "name": "DAΦNE", "namespace": "dafne/accumulator", "site": "LNF"},
  "systems": [{"id": "dafne-accumulator", "kind": "Accumulator", "beams": ["e-"]}],
  "beams": [{"id": "e-", "kind": "particle", "species": "electron", "charge": -1, "reference_energy": 0.51,
             "systems": ["dafne-accumulator"]}],
  "paths": [{"id": "accumulator-ring", "system": "dafne-accumulator", "topology": "closed", "length": 32.56,
             "reference": "SEPA101", "placements": ["SEPA101", "VLVA101", "KCKA101", "QUAA101", "BLWA101", "…"]},
            {"id": "extraction-line", "system": "dafne-accumulator", "placements": ["QUAT101", "BPST101", "DHPT101", "DMPT101"]}],
  "connections": [{"kind": "branch", "from": {"path": "accumulator-ring", "component": "SEPA102"},
                   "to": {"path": "extraction-line"}}],
  "definitions": [{"id": "QUA1", "type": "quadrupole", "parameters": {"length": 0.3},
                   "boundaries": [{"profile": {"shape": "circle", "radius": 0.025}, "note": "magnet bore"}]}],
  "components": [{"id": "QUAA101", "type": "quadrupole", "definition": "QUA1", "family": "QF", "mounted_on": "GIRDER_01"},
                 {"id": "GIRDER_01", "type": "girder", "fiducials": ["FID_G01_A", "FID_G01_B"]}],
  "datasets": [{"id": "design-2026", "kind": "design", "path": "accumulator-ring",
                "values": {"QUAA101": {"s": 1.4333, "physics": {"length": 0.3, "k1": 4.30926},
                                       "optics": {"beta_x": 3.665, "beta_y": 4.667, "dx": 0.377}}}},
               {"id": "vacuum-2026-06-01", "kind": "snapshot", "category": "vacuum", "path": "accumulator-ring",
                "fields": [{"quantity": "vacuum.pressure", "path": "accumulator-ring", "unit": "mbar",
                            "samples": [[0.0, 2.1e-9], [8.0, 2.3e-9], [16.0, 7.8e-9]]}]}],
  "external_bindings": [{"component": "QUAA101", "relation": "implemented_by",
                         "target": {"namespace": "kh", "id": "92ac…", "name": "MAG-ACC-QF01"},
                         "status": "confirmed", "authority": "human_confirmed", "confidence": 0.95,
                         "evidence": ["exact_name", "type_match", "beamline_match", "position_match"],
                         "source": {"method": "asset_sync", "matcher": "beamline_asset_matcher", "matcher_version": "1.0"},
                         "confirmed_by": {"type": "user", "id": "alice@lnf.infn.it"}, "timestamp": "2026-10-04T09:12:00Z"}]
}
```

**Diagnostic.** See [§ 9](#9-diagnostics-observables-and-measurement-models). A screen is interceptive, made
of material, and derives a profile from an image:

```json
{"id": "SCRL01", "type": "screen", "observes": ["beam.profile.x", "beam.profile.y", "beam.size.x"],
 "material": {"material": "YAG:Ce", "thickness": 1e-4},
 "measurement_model": {"type": "image", "observables": ["beam.profile.x", "beam.profile.y"]}}
```

**Vacuum component.** The beam model holds only what concerns the beam. The valve's manufacturer, actuator,
PLC, interlock, vacuum sector and maintenance are the Knowledge Hub's, reached through the binding:

```json
{"id": "VLVA101", "type": "gate_valve", "aliases": ["VV-ACC-01"], "geometry": {"length": 0.07},
 "boundaries": [{"profile": {"shape": "circle", "radius": 0.032}, "when_state": "OPEN", "note": "open bore"}]}
```

Capabilities `vacuum_boundary, vacuum_isolation, aperture_limiting, movable, interlocked` and the
OPEN/CLOSED/MOVING/FAULT state set come by default.

**Laser.** Fixture D: a photon beam (`wavelength: 800`), the same placements and connections as a particle
line, an iris boundary, an interaction point that is virtual, and a camera on the splitter's branch observing
`optical.profile` with an `image` measurement model.

**Knowledge Hub binding.** As in the document above. Bindings are made and reviewed in the hub
([beam-asset-sync.md](beam-asset-sync.md)); an export carries the confirmed ones with their provenance, never
a copy of the asset's data.

## 16. Relation semantics

Inside the model:

| Relation | From → to | Meaning |
|---|---|---|
| placement on a path | component → path (one or several) | where it is along a beam's route |
| next / closes / branch / merge / continue | placement → placement | [§ 2](#2-topology-a-directed-beam-network) |
| `definition` | component → definition | what it instantiates |
| `mounted_on` | component → support component | moves with it |
| `contained_in` | component → assembly component | part of it |
| `fiducials` | component → fiducial components | define its alignment |
| `observes` | component → observable | what it measures |

To external assets (`external_bindings[].relation`):

| Relation | Meaning |
|---|---|
| `implemented_by` | the physical device that realises this component (the normal binding) |
| `mounted_on` | the physical support it sits on (when the model has no support component for it) |
| `contained_in` | the physical assembly or chamber it is part of |
| `measured_by` | the physical instrument that measures at this model location |
| `associated_with` | related, without a stronger claim |

How the hub stores each (ledger relations and their causal semantics) is in [beam-model.md](beam-model.md) § 4.
