# N2 — the whole NetBox Device Type Library in the IT domain

Status: **proposal, for approval** (2026-11-01). Follows docs/catalogue-collections.md §A and
docs/system-catalogue.md (C4, domains).

## Measured on the local copy (2026-11-01)

At the pinned commit of the fork (`infn` @ `25e998f`):

| | |
|---|---|
| Device types | **12,760**, from **392** manufacturers |
| Largest | Dahua 1,248 · Cisco 1,074 · HPE 535 · Vivotek 496 · TVT Digital 403 · i-PRO 354 · Uniview 353 · Hikvision 298 · Juniper 296 · Arista 291 · LILIN 282 · HiLook 244 |
| Manufacturers with an ARGUS vendor today | **2 of 392** (Moxa, Basler) |
| Reading each file with `git show` (today's code) | 28.7 ms a file → **about 6 minutes** for all, on every cold start |
| Creating a Product Model through the ledger | 38 ms each → **about 8 minutes** for all 12,760 (measured on 200, rolled back) |

Today, selecting `"*"` would fail before reading anything: one manufacturer without a vendor stops the whole
source (`sources.materialize`), and 390 have none.

## What changes

1. **Vendors from NetBox.** A NetBox manufacturer that matches no ARGUS vendor (by name or alias, as now) becomes
   a vendor of the `it-devices` collection, marked `origin: netbox`, with NetBox's name and slug. A manufacturer that
   does match keeps the ARGUS vendor (Cisco stays one Cisco). The one-manufacturer-one-entry check runs as today,
   across both sources. ARGUS's own vendors collection stays for the accelerator world.
2. **One batched read.** `git cat-file --batch` reads every selected file in one process (seconds, not minutes);
   the materialized tree is cached per pinned commit, as now.
3. **A preview that summarises.** New models need no decision: the plan counts them by manufacturer
   ("12,742 new models from 390 manufacturers") instead of listing them; it lists only those that may be a record
   already here (link or create) and those that change or retire. Installing adds the new ones in batches, with a
   progress report, through the ledger as every other record. Creating the records takes about 8 minutes
   (measured); the plan's matching against existing records adds to that, and is measured in N2b. Later upgrades
   only touch what changed.
4. **Classification stays optional.** A model without an `it-classification` entry carries NetBox's identity
   (vendor, model code and name; part number, U height, full depth, weight and airflow as specifications; its interface, console and power port counts; and its NetBox file as source) and no ARGUS device class; it is
   still offered to IT workspaces, found by search and by the navigator (under *—* for its class until classified).
5. **`select` becomes "everything, minus"** for this source: `select: ["*"]` with an optional `exclude:` list of
   patterns, so a family nobody at INFN will ever have (if any) can be left out without listing the rest.

## What it means for people

- IT workspaces are offered up to 12,760 models in the *Product model* picker (it searches; the 30 best matches
  show) and the navigator gains one IT domain with its manufacturers.
- GLPI matching considers them all: more devices matched exactly, and more near matches to review. A tie between
  two models is reported, never guessed, as today.
- A NetBox upgrade (a new pin) is a bigger preview, summarised the same way.
- Roughly a third of the library is video surveillance (Dahua, Vivotek, TVT, i-PRO, Uniview, Hikvision, LILIN,
  HiLook…). It is IT equipment and stays in; `exclude:` is there if INFN decides otherwise.

## As built: N2a (2026-11-01)

- **Vendors from NetBox.** `sources.materialize` makes a vendor of the `it-devices` collection from each manufacturer
  no ARGUS vendor is (by name or alias): NetBox's name, an id from it never already taken, its NetBox folder as
  source. Moxa and Basler keep ARGUS's.
- **Classification optional for NetBox models**: the validator no longer requires a device class of a model of a
  `netbox`-origin collection (Argus collections still need one).
- **`exclude:`** next to `select:` on a NetBox source.
- **Reading.** Sources are fetched without file contents (`--filter=blob:none`), then only the files read are
  fetched (those missing, in chunks), read in one `git cat-file --batch`, parsed with the C YAML parser. Trees
  read from the pinned sources are kept per folder in the process.

Measured on the local copy, from an empty cache, against GitHub:

| | Before | After |
|---|---|---|
| Today's lock (8 device types) | the fork's 841 MB fetched (rack elevation images) | **956 KB, 5 s**, the same tree (same checksum) |
| The whole library (`select: ["*"]`) | refused: 390 manufacturers without a vendor | **12,760 models, 390 vendors made; 11 MB**; read 17 s with the repository cached; the tree loads in 2 s, then from memory |
| Validation of the whole tree | — | 0.4 s; **one problem**: `Cisco/N2K-C2348TQ-10GE` and `Cisco/N2K-C2348TQ-10G-E` are the same product in the library itself — left out with `exclude: ["Cisco/N2K-C2348TQ-10GE"]` |

The first row matters today: the production pod already fetches the whole fork (841 MB into its temporary
storage) on its first catalogue read; this release ends that.

## Stages

- **N2a** — vendors from NetBox manufacturers; the batched read; `exclude:`. Tests; the local copy reads all
  12,760 with the time measured.
- **N2b** — the summarised preview and the batched install with progress. Tests; the local copy installs all of
  them, time and catalogue size measured, then the navigator, the picker and GLPI matching checked at that size.
- **N2c** — production, after review: the pin with `select: ["*"]`, preview, install.

## Not in this proposal

- Classifying the 12,760 (ARGUS device class, spares): done for what INFN uses, as it is found.
- Importing NetBox's module types, rack types or power data.
