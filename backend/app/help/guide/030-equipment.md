---
title: Equipment (assets)
summary: Registering equipment and positions, types and attributes, relations, labels and QR codes, attachments, history and provenance, bulk changes.
keywords: [asset, assets, equipment, object, record, type, schema, attribute, relation, label, labels, qr code, serial, barcode, scan, history, provenance, bulk change, catalogue, position, installation, spare, lifecycle, custody, attachment, photo, video, related by meaning, duplicate]
order: 30
---

An **asset** (also *object* or *record*) is a piece of equipment, a place in the machine where equipment goes
(a **position**), or anything else worth tracking: a rack, a cable run, a software service. Every asset has
a **type**, which decides its attributes.

## Find equipment

- **Assets**: choose a type in the type panel, search by name, key, label or serial, and filter by the type's fields;
  **Map** shows the same records on the map.
- The **search box** at the top (Ctrl K / ⌘ K) finds assets, tickets and documents together.
- **Ask ARGUS** answers in your own words ("which ion pumps are in the gun area?").
- On the phone, **Scan label** reads its QR code, barcode, serial or printed nameplate; the **Assets** tab
  browses, searches and sorts the workspace's equipment (see *The mobile app (ARGUS Field)*).

## Register a new asset

1. **+ New → Asset**.
2. **Type**: start typing what it is (*ion pump*, *power supply*…) and pick the type. The type decides which
   attributes the form asks for.
3. **Name**, and the **Attributes** you know: manufacturer, model, serial number, inventory number… The
   **key** is made for you from the workspace's pattern (**Keys**), unless you type one.
4. **Save**.

The side panel helps while you type: the **Checklist** says what is missing or wrong (a key already taken, a
serial number another record holds, a likely duplicate) and what to answer next. With an AI endpoint
configured, **Describe it** fills the form from a sentence, a nameplate photo or a datasheet (see *Guided and
AI-assisted entry*). On the phone, **Register equipment** does the same from a nameplate photo, and can start
from a similar unit you scan.

## Check possible duplicates

Open a record the checklist suggests and compare its identifiers, type and location. Several units may share
a model name; a matching serial or inventory number needs a closer look.

If it is the same item, use the existing record. If its identity is still uncertain, ask the inventory
steward before creating another one. Follow the agreed naming rules and do not invent values you do not
know.

## An asset page

| Part | What it holds |
|---|---|
| Attributes | the typed values; a value maintained from a source shows where it came from |
| Relations | links to other records: what powers it, what it is part of, where it is installed… |
| Comments | notes from people |
| Attachments | files: datasheets, photos, drawings, videos, recorded notes, recorded locations |
| History | every change, who made it and when (see below) |
| Labels | its QR code, serial, barcode, inventory number and other labels: what a scan finds it by |
| Provenance | for each value, the source and the decisions behind it |
| Lifecycle & custody | state (in use, spare, under repair…), custodian, location, with their history |
| Related by meaning | records whose written knowledge is about the same thing (see *The knowledge graph*) |

It also lists the asset's tickets and the documents that apply to it (its own, its model's and its type's).

**History** shows what was imported or written there, and also, as a line each: every edit a person makes
(which fields, from what to what, for example *Manufacturer: Agilent → Pfeiffer*), every label put on or taken
off, and every file attached. Each of these also moves the asset's *last changed* time, so it shows in the
cockpit's recent activity and in lists sorted by change.

## Relate two assets

On the asset's **Relations**, add a relation, choose its kind (for example *powers*, *part of*, *composed of*,
*acts on*) and the other record (*Target asset…*). ARGUS refuses a relation its rules forbid (wrong kinds of
record at either end, too many of one kind, a loop) and says why.

A relation that a source or an installation maintains is marked as such: change its source, not the relation.

## Types and the catalogue

**Assets → Type catalogue** shows every type you can use: where it sits in the tree, what it means, its
attributes (own and inherited), the names imports know it by, and how many records it has. Types are shared
between workspaces through a catalogue workspace; a workspace's own types sit under them.

## Labels and QR codes

A label is how a unit in front of you is found: its **QR code**, **serial number**, **barcode**,
**DataMatrix**, **inventory number**, **asset tag**, **RFID** or another name it is known by.

- **Assets → Labels & QR codes** prints labels for many assets at once. A QR code opens the asset's page.
- On an asset's page, add a label by typing it or **scanning** the one already on the equipment; remove one
  that is wrong. On the phone: the asset's **Labels** section, **Add label** (the kind, then type or scan the
  value).

When anyone scans or types a value, ARGUS looks for **every record it names**, in every workspace you can
open, ignoring capital letters:

- its **key**, and a **former key** it had before a rename, a merge or a migration;
- a **label** of any kind: QR code, barcode, serial, inventory number, asset tag, an **alias** such as an old
  Service Desk address (`…/ShowObject.jspa?id=…`), an old Insight object number;
- the **serial**, **inventory** number and **MAC** written in its fields.

When nothing carries the value as written, ARGUS tries it again **without what a nameplate prints around
it**: *S/N:*, *Serial No.*, *Matricola*, *Inv.*, *P/N*, or a GS1 barcode's *(21)*.

- One record carries it: it opens, in its own workspace (the app moves there and says so).
- A QR code carried by one record opens that record, even if another unit has the same value as a serial.
- Several records carry it — a serial on two units, an old record and the one it was migrated to (one has
  the key, the other has it as a former key or alias) — then none opens: you **choose** the one in front of
  you, with each one's key, type, workspace and identifiers.

The search boxes (on the web, *Assets* and the search at the top; on the phone, Home and Assets) find
equipment by the same names: key, name, former key, alias, any label, serial and inventory number.

## Change many at once

**Assets → Bulk changes** sets an attribute on, or retires, many records at once. It always shows a
**preview** first; above 100 records a second person approves it; it is applied, and can be undone, as one
batch.

Before applying, check the preview, the selection and the value. The batch's history is where to look when
reviewing or undoing it.

## Positions, installations and spares

A **position** is a place in the machine (a slot in the lattice, a rack position); **equipment** is the unit
installed there. Installing, swapping or removing a unit keeps the position's history: "what was installed
here on 3 March" has an answer. **Spares** show which positions they fit.

## Keep positions and physical units apart

A position identifies a place in the machine; a unit identifies the equipment occupying it. For example, the
ion-pump position can first hold serial 77120 and later a replacement with another serial.

Record the installation change and keep both units. Do not overwrite the old unit's serial to turn it into
the replacement. A control channel or IOC is also separate from the equipment it monitors or controls:
connect them with the appropriate relation.

## Shared equipment

Equipment flagged as **shared** (global) is visible in every workspace, with its attachments; only its own
workspace changes it.

## Global values and equipment classes

- **Assets → Global values**: shared lists (statuses, priorities…) used by many types.
- **Assets → Equipment classes**: the classes of equipment with no type of its own (*Other Equipment*), and
  when one deserves a type.
