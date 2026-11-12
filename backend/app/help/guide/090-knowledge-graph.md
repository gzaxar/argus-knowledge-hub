---
title: The knowledge graph
summary: Seeing how records are connected, what is about the same thing by meaning, what stops if something fails, and what could cause a fault.
keywords: [graph, knowledge graph, connections, relations, impact, what depends, root cause, causes, failure, blast radius, single point of failure, depends on, delivered by, redundant, hosted on, it service, semantic, similar, related by meaning, meaning, rag]
order: 90
---

The **Knowledge graph** (side bar) shows records and their relations: what powers what, what is part of what,
which IOC acts on which equipment, which documents apply. Beside it, the **semantic graph** shows what is
*about the same thing*, from what is written, even where nobody linked it.

## Explore

1. Open **Knowledge graph** and pick a record (or open it from a record's page).
2. **Centre here** on any record to move around. *Inbound* and *Outbound* show the two directions of a
   relation.
3. Choose the **layers** (control, power, cooling, vacuum, timing…) to follow only those kinds of relation.

## Related by meaning (the semantic graph)

ARGUS indexes what is written: procedures, tickets and their comments, comments on equipment, and the text of
attached files (see *AI settings*). For a piece of equipment, a ticket or a document, **Related by meaning**
finds the other records whose written passages are closest in meaning to its own, in any language:

- each with **how close** it is, from 0 to 1, and **why**: the two passages, its and yours, that are closest;
- only what you may read: restricted records, other workspaces' private documents and *riservato* documents
  never appear;
- equipment with nothing written about it yet is compared by its key, name, type and description.

Where to see it:

- on the web, the **Related by meaning** card on an asset's, a ticket's and a document's page, and the **related
  by meaning** switch in an asset's relation graph, which adds them as a column joined by dashed lines;
- in the mobile app, the **Graph** tab (start from equipment, a ticket or a document: what it is *connected* to,
  and what is *related by meaning*; tap a neighbour to walk on), and the **Related by meaning** section of each
  record.

A link by meaning was found, not made by anyone: it is a **lead to check**, such as an earlier fault fixed the
same way or a procedure that applies, not a fact. What has not been indexed yet cannot be found: the index is
updated when a document is published and on a schedule (*AI settings*).

## What stops if it fails?

Pick a record and ask **What stops if it fails?**: ARGUS follows the recorded dependencies the way a failure
travels and lists what could be affected and by which path. Losing a power supply and losing an IOC have
different effects: a magnet stops without its supply, while devices an IOC reads keep working, unread.

IT services follow the same rules. A service **depends on** another: that one stops, so does this one. It is
**delivered by** the one system it cannot run without (a mail service by its mail server), and **redundantly
delivered by** each of several that share the work (a Wi-Fi service by its access points): losing one of those
only degrades it. A virtual machine is **hosted on** its host, and stops with it. Contracts, licences and the
software a host runs carry no failure.

## It misbehaves: find causes

For a fault, use **It misbehaves: find causes**: add what misbehaves and, if you know, what still works. ARGUS
walks back to the records that could explain all of it, most likely first.

Ask ARGUS can do both in words: "what depends on the chiller CHL01?", "the gun vacuum and the RF both tripped:
what could cause it?".

## Read the results with care

The graph knows only the relations that were recorded: a missing or wrong relation gives an incomplete answer.
A suggested cause is a candidate to investigate, not a diagnosis, and its ranking is an order, not a measured
probability. A record that does not appear is not thereby unaffected.

Open the records behind each result and compare them with what you observe, the tickets and the procedures.
The graph describes how things are connected, not how the machine is running right now.
