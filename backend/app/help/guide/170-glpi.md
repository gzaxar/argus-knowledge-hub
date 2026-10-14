---
title: GLPI
summary: Bringing a GLPI 10 or 11 into an IT workspace: connecting it, what discovery finds, mapping entities to workspaces, approving GLPI's own types and fields, previewing and importing, who wins when both sides changed, and deciding about records GLPI no longer lists.
keywords: [glpi, inventory, import, it, computers, network equipment, software, licences, licenses, contracts, tickets, problems, changes, documents, entities, custom assets, custom fields, fields plugin, genericobject, authority, retirement, api token]
order: 170
---

ARGUS can host what a GLPI holds — computers, network equipment, peripherals, ports and addresses, software,
versions and licences, locations, suppliers, contracts, tickets, problems, changes and their documents — in a
workspace with the **IT** package. ARGUS keeps its own types: GLPI's are mapped onto them, and GLPI's own
custom types and fields come in only once someone approves them.

## Connecting

On the workspace's **GLPI** page (*Administration*), **Connect a GLPI**: its address, a **user token** and, if
the GLPI asks for one, an **application token**. The tokens are stored encrypted and never shown again. ARGUS
reads through GLPI's REST API, never its database, and opens read-only sessions. Give it a GLPI user whose
profile can only *read* the item types to import, in the entities to import, and an API client restricted to
ARGUS's address.

## Discovery

**Discover** reads GLPI and records what it is: its version, whether its high-level API is there (GLPI 11),
its entities and how many records each holds, every item type it exposes (and the ones the token may not
read, with why), GLPI 11's custom asset types and fields, GLPI 10's *fields* and *genericobject* plugins, and
its other plugins. Nothing is assumed: an installation without a plugin, or a token without a right, is simply
reported.

## Entities → workspaces

The mapping says which workspace each GLPI entity goes to; *with what is under it* includes its
sub-entities, unless one of them is mapped itself. An entity sent nowhere is not imported. You must be able to
create records and tickets in every workspace you name.

## GLPI's own schema

When GLPI has custom asset types or extra fields, ARGUS **proposes** what they become: an existing ARGUS type
or field of the same name is **reused**; otherwise a **new** workspace type (under IT Equipment) or field
(`glpi_<name>`) is proposed. A GLPI field type ARGUS has no equivalent for (a signature, a link to any item)
is listed as **not supported** and its values kept as GLPI gives them. Until you **Approve**, those types
are not imported and their fields are kept aside — nothing in ARGUS's schema changes. If GLPI's schema
changes later, the new proposal waits for review again, and the import keeps to what was approved.

## Preview, then import

**Preview** says, for each workspace: the records that would be created, updated (which fields) or left
unchanged; the fields edited in ARGUS that GLPI also changed; the records GLPI no longer lists; tickets and
documents; what waits for the schema review; what lies outside the entity mapping. **Import this** does exactly
that, and stops if GLPI changed in between (preview again).

Importing the same GLPI again changes nothing. Each record keeps its link to GLPI and its GLPI identity, so a
record renamed on either side is still the same record; the GLPI fields ARGUS does not map are kept on it
(*Other GLPI fields*). Licence keys are restricted: only people given *licence keys* see them.

## Who wins

- **ARGUS** (default): a field someone edited in ARGUS keeps its value; if GLPI changes it too, the preview
  says so and a review item records the difference.
- **GLPI**: GLPI's changes apply and it outranks other sources. A value a person confirmed in ARGUS is still
  never overwritten: the difference goes to the **review queue**. For tickets, GLPI's value applies.

## Records GLPI no longer lists

A record GLPI deleted, moved to its trash or stopped showing to the token is **never retired by the import**.
It stays as it was, and appears under *Records GLPI no longer lists* (and in the review queue). **Retire** it —
its history stays — or **Keep** it as an ARGUS record that GLPI no longer states.
