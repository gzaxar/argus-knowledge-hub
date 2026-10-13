"""Every importer ARGUS has, and the package capabilities it needs before it writes anything.

The importers read their requirements from here (`requires(<id>)`) and a package names the importers it
supports (`imports:`) by these ids, which the package validator checks. An importer never installs a package:
a workspace without what it needs is told what to install (packages/requirements.py).
"""
IMPORTERS: dict[str, dict] = {
    "epik8s": {"name": "EPIK8s control configuration", "requires": ["accelerator-catalogue"]},
    "pbs": {"name": "PBS workbook", "requires": ["accelerator-catalogue"]},
    # Insight and Git bring their own types (the source's object schema): nothing to install first.
    "jira": {"name": "Jira Insight objects", "requires": []},
    "jira-issues": {"name": "Jira issues", "requires": ["tickets"]},
    "confluence": {"name": "Confluence pages", "requires": ["documents"]},
    "markdown": {"name": "Markdown files", "requires": ["documents"]},
    "olog": {"name": "Olog logbook", "requires": ["documents"]},
    "git": {"name": "Git repository of records", "requires": []},
    "locations": {"name": "Locations (CSV, GeoJSON)", "requires": ["object-catalogue"]},
    "glpi": {"name": "GLPI inventory and service desk", "requires": ["it-catalogue", "records", "tickets", "documents"]},
}


def requires(importer_id: str) -> tuple[str, ...]:
    return tuple(IMPORTERS[importer_id]["requires"])
