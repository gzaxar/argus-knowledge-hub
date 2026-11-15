---
title: Racks
summary: What is mounted in a rack and where — the elevation front and rear, placing and moving units by dragging or by a form, shelves, reserved spaces and 0U devices, the preview before a change is saved, what is refused (overlaps, units outside the rack), and the rack's history.
keywords: [rack, elevation, rack unit, U, mount, mounting, front, rear, full depth, shelf, reserved, 0U, PDU, overlap, capacity, move, history, editor, drag]
order: 172
---

A **Rack** record has an **elevation**: what is mounted in it, at which rack units, on the front or the rear.
Open the rack and choose **Edit the rack**.

## Reading it

Units are numbered from the bottom (U1). A block is a unit, as high as the units it takes; a block with a thick
left edge goes through the rack (front and rear). Amber is a shelf, dashed grey a space kept for something.
What takes no unit — a vertical PDU — stands as a violet strip along the side of its face, the whole height, with
what feeds it ("feed A from UPS-SRV"); it is also listed under the drawing as **0U**. Click a block to see what it is and
open its record, with its ports, cables, tickets, documents and photos.

## Changing it

- **Mount a unit**: search by name, key or serial, choose **Mount** (or **Move here** when it is in another
  rack), say the first unit, the height and the side. The height offered is the product model's; change it when
  the unit in front of you is different.
- **Move**: drag the block to another unit or to the other side, or change the numbers in its panel.
- **Shelf or reserved space**: give the units and a name. A unit can then be mounted *standing on* a shelf.
- **Take out**: in the block's panel.

Nothing is saved while you work. **Changes to confirm** lists each change in words — "Server 3: U4–U5 front →
U10–U11 front" — and the drawing shows the rack as it would be. **Confirm** saves them together.

## What is refused

A change is not saved when a unit would stick out of the rack, when two things would share a unit on the same
side, or when a shelf that still carries something would be removed. The message names the units and what is
there already.

## History

**History** lists every mounting the rack has had: what stood where, from when until when, and who changed it.
A move is two lines — the old place, closed, and the new one.

A unit placed in a rack is *located in* it: its location, the floor plan and the impact analysis follow.
