"""Workspace templates: the definitions a workspace starts from, as versioned YAML packages.

A package (`backend/packages/<id>/`) is a manifest, `package.yaml`, and the section files it lists:

    id: accelerator                  # stable, never reused for something else
    version: 1.0.0                   # semantic version: a release that changes a definition raises it
    name: Accelerator catalogue
    description: …
    owner: INFN ARGUS                # who answers for it
    depends: {core-facility: ">=1.0,<2"}
    provides: [object-catalogue]     # capabilities an importer may require (docs/packages.md)
    contents: [object_types.yaml, …]

What a section holds:

    option_sets          named lists of options, used by attributes as `option_set: <name>`
    enumerations         a workspace's shared enumerations (global values): status, priority…
    object_types         the object catalogue: types, their parents, attributes, icons, behaviours, map layers
    ticket_types         the base ticket type's fields and the kinds of ticket
    document_types       the base document type's fields and the kinds of document
    workflows            ticket workflows (states and transitions)
    equipment_classes    the governed vocabulary of "Other Equipment"
    reference_relations  reference fields that are edges of the knowledge graph, and their verb
    map_layers           the layers records of a locatable type are shown on

A package holds definitions only: no site data (no coordinates, no records), no code. It is read with a
safe YAML loader, and every key it may contain is known: anything else is an error.

`load` reads a package, `validate` reports what is wrong with it (and with what it depends on), `available`
lists the packages this installation ships, `install` (app.packages.install) puts them in a workspace.
"""
from app.packages.model import Package, Problem  # noqa: F401
from app.packages.loader import available, get, load, packages_dir  # noqa: F401
from app.packages.validate import validate  # noqa: F401
