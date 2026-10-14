"""What a loaded package is: its manifest, its sections as written, and where each came from."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Problem:
    """One thing wrong with a package: in which file, where in it, and what."""
    package: str
    file: str
    where: str
    message: str

    def __str__(self) -> str:
        at = f"{self.file}" + (f" › {self.where}" if self.where else "")
        return f"{self.package}: {at}: {self.message}"


@dataclass
class Package:
    id: str
    version: str
    name: str
    description: str
    owner: str
    depends: dict[str, str]
    provides: list[str]
    path: Path
    checksum: str
    # section name -> its content, merged across the package's files
    sections: dict[str, Any] = field(default_factory=dict)
    # section name -> the file it came from (for error reports)
    origin: dict[str, str] = field(default_factory=dict)
    # problems found while reading (unreadable YAML, unknown keys); validate() adds the rest
    read_problems: list[Problem] = field(default_factory=list)

    def section(self, name: str, default: Any = None) -> Any:
        return self.sections.get(name, default)

    def summary(self) -> dict:
        """What it holds, counted: for listings and previews."""
        objects = self.section("object_types") or {}
        tickets = self.section("ticket_types") or {}
        documents = self.section("document_types") or {}
        classes = self.section("equipment_classes") or {}
        return {
            "object_types": len(objects.get("types") or []),
            "enumerations": len(self.section("enumerations") or []),
            "ticket_types": (1 if tickets.get("base") else 0) + len(tickets.get("kinds") or []),
            "document_types": (1 if documents.get("base") else 0) + len(documents.get("kinds") or []),
            "workflows": len(self.section("workflows") or []),
            "equipment_classes": len(classes.get("classes") or []),
            "map_layers": len(self.section("map_layers") or []),
            "extensions": len(self.section("extends") or []),
            "relation_types": len(self.section("relation_types") or []),
            "roles": len(self.section("roles") or []),
            "restricted_classes": len(self.section("restricted_classes") or []),
            "queries": len(self.section("queries") or []),
        }

    def describe(self) -> dict:
        return {"id": self.id, "version": self.version, "name": self.name, "description": self.description,
                "owner": self.owner, "depends": self.depends, "provides": self.provides,
                "checksum": self.checksum, "contents": self.summary()}


def option_list(options: Optional[list]) -> list[dict]:
    """Options as stored: `{id, value, …}`; extra keys (responsible, meaning) are kept."""
    out = []
    for o in options or []:
        out.append({"id": str(o["id"]), "value": str(o["value"]),
                    **{k: v for k, v in o.items() if k not in ("id", "value")}})
    return out
