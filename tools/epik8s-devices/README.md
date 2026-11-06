# epik8s-devices

Turns a beamline's EPIK8s configuration into an inventory of equipment you
can read, correct, and then load into an ARGUS Knowledge Hub.

It runs on your machine, against files and repositories you already have.
It never writes to the control configuration: `deploy/values.yaml` deploys
the accelerator, and this only reads it.

## Why it is a separate tool

The control configuration is the record that works. The inventory is the
record that is incomplete. Pulling the first into the second used to produce a
second parallel tree of objects that nobody reconciled: the hub's import made
its structure under one set of keys, and this tool made devices under another.

Both now write to the same objects, under the same keys, so the review is added
to the structure instead of standing beside it. What is left for a person is
what no file states: what class of hardware a channel drives, what it acts on,
and which physical asset that is.

So the steps are separate, and a person sits between reading and writing:

    scan    read the configuration        → devices.yaml, yours to correct
    match   propose which physical asset  → evidence, not decisions
    push    add the review to the hub     → names the workspace first

The hub reads the same configuration itself (`backend/scripts/import_epik8s.py`, or the
import page) and makes the structure: the beamline, the configuration, IOCs, templates,
devices, access points, networks, services, mounts. What only a person can add is the
review: which class of hardware a device is, which element it serves, and which physical
asset it acts on. `push` adds exactly that, to the objects the import made.

## What a device is

One row per thing that can fail. The configuration is organised around
IOCs — software — but an IOC drives eight ion pumps, and it is a pump that
trips.

Each row carries what the configuration knows and says plainly what it
does not:

    key, name, pv                the handles
    device_class, vendor, model  what the equipment is
    element                      what it acts on: quadrupole, ion pump, slit
    system, zones                where it belongs
    connection                   direct, through a terminal server, or on
                                 the instrument itself — with host and port
    model_spec                   the ps:/motor: rating: polarity, current
                                 limits, ramp, velocity, resolution
    physical_asset, model_asset  empty, for you or `match` to fill
    needs                        what is missing from this row

## Where the classification comes from

Not from a table written here. `infn-epics-ioc/ibek-templates` already
states it in its directory tree:

    templates/<category>/<vendor>/<template>.yaml.j2
    templates/ps/ocem/ocem.yaml.j2          → Power Supply, OCEM
    templates/vac/agilent/agilent-vac.yaml.j2 → Vacuum, Agilent

so the catalogue is read from that repository and stays true as templates
are added. Point `--templates` at your checkout. Four templates have no
ibek file because the IOC runs on the instrument over ssh (Libera, STEMlab,
MRF); those have a built-in fallback. Anything else comes out with its
class empty and `needs` saying so, rather than guessed.

The element — what the device acts on — is read from the name, which at
LNF is a code: `QUATB002` is a quadrupole, `GUNSIP01` the gun's first
sputter-ion pump, `FI8-CAM-06` a camera in FI8. A name that matches no
convention gets no element rather than a wrong one.

## Use

    python -m epik8s_devices scan ../epik8-sparc/deploy/values.yaml \
        --templates ../infn-epics-ioc/ibek-templates \
        --out sparc-devices.yaml

    # or a spreadsheet to go through with the people who own the hardware
    python -m epik8s_devices scan ../epik8-sparc/deploy/values.yaml \
        --format csv --out sparc-devices.csv

    python -m epik8s_devices match sparc-devices.yaml \
        --hub https://assets-api.example.infn.it --token "$ARGUS_TOKEN"

    python -m epik8s_devices push sparc-devices.yaml \
        --hub https://assets-api.example.infn.it --token "$ARGUS_TOKEN" --dry-run

`push` asks you to type the workspace id before it writes anything. The
token decides the workspace, and a token for the wrong one is easy to have.

## What `push` writes

Objects of the hub's own catalogue types, not types of its own. Seed them first with
`backend/scripts/seed_asset_types.py`; `push` says so if the workspace has none.

- **A device is a `Control Device`**, under the key the hub's import gives it
  (`SPARC-DEV-histar-GUNQUA01`) and the same uid, so the two tools write to one object
  instead of two trees nobody reconciles. The class of hardware is a value it carries
  (`device_class`), not a type. There is no `Power Supply` type made by this tool.
- **A device the import already made** gains only what your review adds: `device_class`,
  `element`, `vendor`, `model_code` and what is still missing (`argus_keywords`). An empty
  cell never erases a value somebody entered in the hub, and running `push` again writes
  nothing.
- **An IOC-only row** (an IOC that lists no devices) is an IOC, made by the import. `push`
  does not write it as a device with the IOC's name; if you gave it a `physical_asset` it
  writes the link, `drives`. A device's `physical_asset` becomes `acts on`.
- **A device the import has not made** is created, with everything the scan read.

## Requirements

Python 3.9+, `pyyaml`. `match` and `push` also need network access to the
hub; `scan` needs nothing but the files.
