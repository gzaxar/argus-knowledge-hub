"""GLPI as a source for the IT package (docs/glpi.md).

ARGUS reads GLPI through the interfaces the installation actually exposes — never its database — into a
snapshot (`source`), works out what that installation is (`discovery`: version, APIs, entities, item types,
custom assets and fields, plugins), maps it onto ARGUS's own types (`mapping`), proposes workspace types and
fields for what GLPI defines and ARGUS does not (`schema`, applied only once reviewed), and imports it
(`importer`): records through the fact ledger, bound to stable GLPI identities so a re-import is
idempotent, local edits kept by an explicit authority policy, nothing retired without a person deciding.
"""
