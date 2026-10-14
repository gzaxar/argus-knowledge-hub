---
title: Domain packages
summary: What a workspace can hold, by domain: safety and radiation protection, vacuum and cryogenics, buildings and access control, lasers and alignment, environmental monitoring, contracts and administration, technology transfer, IT — and how to choose them, what they bring, and what they do not promise.
keywords: [package, packages, domain, safety, fire, radiation, vacuum, cryogenics, gas, civil, building, access control, door, laser, optics, alignment, environment, monitoring, contract, procurement, administration, technology transfer, patent, licence, invention, workspace, template, compliance, approval, permit]
order: 165
---

A workspace's types — the kinds of record, ticket and document it holds, with their fields, choices,
workflows and suggested roles — come from **packages**. Every workspace has the **core**: tickets, documents,
the review queue, permissions and history, and nothing of any one domain. Everything else is chosen.

## The packages

| Package | What it holds | Stands on |
|---|---|---|
| Core objects | equipment, products and vendors, places (buildings, areas, racks, stores), ports, cables | core |
| Core records | parties (companies, universities, agencies) and agreements (contracts) — records that are not equipment | core |
| IT | network and computing equipment, software, licences; incidents, requests, problems, changes; GLPI | core objects, core records |
| Safety, fire protection and radiation protection | detectors, extinguishers, suppression, gas and radiation monitors, shielding, sources, dosimeters; fire zones and radiation areas; inspections, findings, incidents, permits to work | core objects |
| Vacuum, cryogenics and gas handling | pumps, gauges, valves, chambers; cryostats, cryocoolers, dewars, cold boxes; cylinders, regulators, relief devices; leak tests, bake-outs | core objects |
| Civil works, buildings and access control | rooms, access zones, doors, badge readers, controllers, elevators, cranes; building defects, civil works and access requests | core objects |
| Optical systems, lasers and alignment | lasers and optics, optical tables, survey reference points and instruments, laser controlled areas; alignment surveys, laser work authorisations | core objects |
| Environmental and monitoring networks | networks, stations, sensors, loggers, sampling points; calibrations, sampling, threshold exceedances | core objects |
| Administrative and contract management | budget lines, grant agreements, purchase orders, invoices; procurement requests, renewals, goods receipts | core records |
| Technology transfer and research valorization | invention disclosures, patent families and patents, licence and confidentiality agreements, spin-offs, valorization projects, research outputs | core records |
| Electrical, hydraulic, HVAC, plant | the technical plant | core objects |
| Accelerator | the machine as functions, magnets, RF, diagnostics, control — with safety, vacuum and optics | core objects, IT, safety, vacuum, optics |

A workspace with only technology transfer has records, tickets and documents, and no equipment pages, no map
and no beam model — the menus show only what the workspace has. A workspace with only IT has no patents.

## Choosing them

When an administrator makes a workspace (*Administration › Workspaces › New*), they tick the packages it
starts from. **Preview the installation** shows each package that would go in, with what it needs, its exact
version and checksum, and the types, kinds and workflows it creates. A new workspace is **private** — nobody
but its creator sees it until roles are given — and holds **no records**, only their types.

Packages can be added later on the workspace's **Packages** page, previewed the same way; a newer version is an
**upgrade**, whose changes are listed, and any that would remove or tighten something wait for a decision.

## What a package brings

- **Types and fields**, with units (kg, bar, µSv/h…) and fixed choices. Some fields are checked by ARGUS
  itself: a patent number as an office prints it, a DOI, an ORCID iD with its check digit, a tender code (CIG),
  a project code (CUP), a laser wavelength.
- **Relations** with a meaning: a detector *reports to* its panel, a reader *controls* a door, an amplifier is
  *seeded by* an oscillator. They are refused between the wrong kinds of record, and the knowledge graph knows
  which way a failure travels along them.
- **Ticket and document kinds** with their own fields, and **workflows** for them. A step marked as an approval
  — approving a permit to work, an access request, a procurement request — can only be taken by someone who may
  approve tickets in the workspace.
- **Suggested roles** (a fire safety officer, a contract manager, a technology transfer officer…), offered as
  role templates on *Access reviews*. Nothing is granted by installing a package.
- **Restricted classes**: unpublished inventions, commercial terms, source security, physical security, licence
  keys. A field in one is hidden — in pages, search, the map, exports and Ask ARGUS — from anyone not given the
  class.
- **Example questions**: each package answers a few representative queries over sample records, and ARGUS
  checks those answers on every release.

## What they do not do

The safety, radiation protection, access control, contract and technology-transfer packages are a **structure
to start from**. They do not make a site compliant with any regulation, and their definitions and workflows
are to be approved by the people responsible for each domain before they are relied on.
