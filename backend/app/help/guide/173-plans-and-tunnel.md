---
title: Floor plans by layer, and the tunnel
summary: A floor plan with what is on it, layer by layer — rooms and accesses, beamline, racks (one point each, opening their elevation), main fixed plant, other devices, cables and pipes, zones, open tickets and activities — and the tunnel along a beam path, with the hardware installed at each element and where it is.
keywords: [3D, three dimensions, relations, floor plan, plan, layers, layer, rack, room, zone, cable, pipe, ticket, activity, tunnel, beamline, s, longitudinal, beam path, where is]
order: 173
---

## A plan, layer by layer

Open a plan with **With layers** (on a place's page, under its plans, or from **On the floor plan**). The
drawing is the plan as it was uploaded; ARGUS draws the records over it and never writes on the drawing.

Turn layers on and off with the chips above the plan; your choice is remembered on this browser.

- On at first: **Rooms and accesses**, **Beamline**, **Racks**, **Main fixed plant** (klystrons, modulators,
  chillers, switchboards, UPS, air handling units…).
- Off at first: **Other devices**, **Cables and pipes**, **Zones** (radiation, fire, access), **Open tickets**
  and **Activities** (planned or under way, from yesterday to the next 30 days). Tickets and activities show as
  small counters next to the record they concern.

A **rack is one point**, a square, however many units it holds: what is mounted in it, or said to be in it, is
not drawn on its own. Click the square to open the rack's elevation. A ticket on a server in the rack is
counted on the rack.

Rooms, zones and cables come from their outlines and routes on the map, so they appear only on a plan that is
placed on the map. On a plan drawn by ARGUS a cable or pipe from another building starts at the wall it comes
through, named there, and a dot marks where it arrives. Rooms of another floor of the same building are left out.

From a record looked for — `?focus=` in the address, as the tunnel and Ask ARGUS use it — the plan opens around
it. A unit in a rack is shown as its rack, with a link that opens the rack with that unit selected.

## In 3D

**3D view** on the plan opens the same plan in three dimensions: the drawing on the floor, rooms as glass walls,
racks as cabinets with each unit at its height, front or rear, beamline, plant and devices. Drag to turn, scroll to
zoom, right-drag to move; **Reset view** comes back.

**Relations** draws how the records are related as coloured arcs — what powers what, what feeds, cools, controls
or connects to what. By default only those of the record you click; untick *only those of the record selected* to
see them all, and choose the types. Where a record is (its room, its rack) is shown by placing it, not as a line.

## The tunnel

**Beam model → Tunnel with the hardware** (or **/tunnel**) draws a beam path to scale along `s`: each element
of the model, the rooms the path crosses as bands above it, and a dot under each element.

- grey: no hardware installed at that position;
- amber: hardware installed, but no room known for it;
- green: hardware installed and placed;
- red: the hardware has open tickets.

Click an element to see the hardware installed there: its serial, its room, its rack, its point on a floor
plan (a link opens the plan around it), what powers it and in which rack that supply is, and its open tickets.
Nothing is guessed: an element with nothing installed says so.

## Putting a record on the plan of the place it is in

A record said to be in a place — its **Located in**, or a `located in` relation — whose place has a floor plan
(its own, or the building's plan the room is drawn on) but which has no point on any plan yet, shows in **Indoors**:
*It is in … which has a floor plan, but it is on none of them yet*, with **Put it on the plan**. That opens the
placement already in that place and on that plan: click where it is and **Save** (top right). Right after a new
record is saved, the same is asked once. A unit in a rack is not offered it: it is shown where its rack is.

