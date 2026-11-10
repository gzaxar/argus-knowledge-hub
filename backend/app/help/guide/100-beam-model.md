---
title: The beam model
summary: The machine's beam-transport model: importing it from MAD-X and other codes, markers and vacuum elements, editing it, removing it, and linking its components to the equipment.
keywords: [beam model, lattice, mad-x, madx, tfs, elegant, bmad, xsuite, accelerator toolbox, optics, aperture, beam path, component, element, marker, vacuum pump, valve, gauge, asset sync, binding, remove model, delete model]
order: 100
---

The **beam model** describes how the beam travels: beam systems and beams, paths of components (open lines and
rings, with branches and merges), each component's definition, apertures, alignment and datasets such as
optics. It is independent of any simulation code, and linked to the real equipment.

## Bring a model in

1. **+ New → Beam model**.
2. Upload a file: the canonical `*.beam.json`, or one to convert:

   | Format | Files |
   |---|---|
   | MAD-X sequence or line | `.madx`, `.seq`, `.str`, `.mad` |
   | MAD-X TFS table (twiss) | `.tfs` |
   | Elegant lattice | `.lte` |
   | Bmad lattice | `.bmad`, `.lat` |
   | Xsuite line | `.json` |
   | Accelerator Toolbox (pyAT) | `.json` |

   Or start one from scratch in the editor.
3. ARGUS checks it and says how complete it is, level by level (topology, lattice, geometry, optics, physical,
   integrated) and what is missing for the next level.

## A file with several sequences

A MAD-X file with several sequences and no `USE` becomes **one model with one path per sequence**. An element
that several sequences place is one component on all those paths, so it is one record, with one supply and one
history; each path keeps its own positions and values. Below the file, the upload says how many times the elements
were placed on how many paths, which elements have different values from path to path, and any name given two
different types (the first stays). **Sequences** can read just one of them. With `USE`, the file has already chosen.

When a simulator needs one label per configuration, as `DHPTT001_IN` and `DHPTT001_OUT` for one magnet bending
either way, put the endings in **Same element, name endings** (`_IN, _OUT`): they become `DHPTT001`, on both paths,
each keeping its own angle. It is off unless you ask, since an ending does not mean this in every file.

Do not import each sequence as its own model: the same magnet would then be several records, and a control channel
of that name could not tell which one it powers.

## Markers, and what a simulation does not compute

A lattice places with **markers** what its simulation computes nothing for: a vacuum pump, a valve, a gauge,
a reference point. The beam model is not one simulator's view of the machine, so markers are **kept** by
default (untick *keep markers* to leave them out). A marker whose name follows the usual conventions becomes
what it names:

| Name starts with | Becomes |
|---|---|
| VPI, SIP, IGP, TMP, NGP, PMP, PUMP | vacuum pump |
| VG, GAUGE, PIG | vacuum gauge |
| FV, VFV | fast valve |
| VV, GV, VLV, VALVE | gate valve |
| BEL, BLW, BELLOW | bellows |
| WIN | vacuum window |

Any other marker stays a **marker**. The viewer draws each kind with its own symbol. A model imported before
markers were kept does not have them: import it again to add them.

## Check an imported model

Look at its paths, the order of its components, positions, units and the datasets it has. Completeness says
which kinds of information are there; it does not say the model matches the machine installed, nor that it is
valid for a particular calculation. Keep the source file, note which configuration it describes, and read the
conversion warnings before relying on it.

## Look at and edit a model

**Beam model** (side bar) lists the models. Open one to see its paths, components and their positions along the
beam. The editor changes the model, its definitions and datasets, boundaries along paths, alignment, state
mappings and value provenance; saving keeps a new revision.

A component's id is what identifies it. Change the id, or remove the component, and the old record is **retired**
and a new one made; change only its values and it stays the same record. A retired record keeps its history and
opens from its link, marked **Retired**, but search, lists, the map and Ask no longer offer it. To see them, tick
**Show retired** on the Assets page, or search for `status = Retired`.

A save that would remove more than a tenth of the model (at least 10 records), or a record with tickets, documents
or a confirmed installation, is not applied at once. The editor says so: approve it in the review queue, then save
again.

## Remove a model

On the **Beam model** page, **remove** beside a model's name takes the whole model out of the workspace:

- its systems, paths, elements and datasets are **retired**, with their history; tickets and installations that
  point at them stay as they were;
- its values, stored documents and asset bindings are deleted.

Importing the same model again brings it back as the same records.

## Link components to equipment

From a model, open its **asset synchronisation**:

1. ARGUS proposes which physical asset implements each component, from names, aliases, type, beamline,
   position, order and neighbours, each with a confidence and the evidence.
2. Confirm, correct or reject each proposal. A confirmed link makes the asset installed at that position.
3. Confirmed links are kept on later synchronisations; only new or changed components are proposed again.

Before confirming, check the unit's identifier and the evidence: a similar name or a neighbouring position is
a clue, not proof. Do not confirm a planned or future model as the current installation unless that is what
you mean to record.
