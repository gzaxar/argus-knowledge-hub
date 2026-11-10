"""Pure navigation graph rules. No database, UI or source-content processing."""
import re


def assert_parent_move(parents: dict, node: str, parent: str | None) -> None:
    seen = set()
    current = parent
    while current is not None:
        if current == node:
            raise ValueError("A node cannot be placed inside itself or one of its descendants.")
        if current in seen:
            raise ValueError("The proposed parent already belongs to a cycle; repair that hierarchy first.")
        seen.add(current)
        current = parents.get(current)


def navigation_nodes(folders: list[dict], documents: list[dict], placements: list[dict],
                     relations: list[dict], workspace_id: str, recover_cycles: bool = True) -> tuple[list[dict], list[str]]:
    """Resolve visible records only. Damaged/missing source links never hide a page."""
    nodes = {}
    warnings = set()
    own_docs = {d["uid"] for d in documents if d["workspace_id"] == workspace_id}
    for folder in folders:
        uid = folder["uid"]
        nodes[f"f:{uid}"] = dict(id=f"f:{uid}", kind="folder", uid=uid, title=folder["name"],
                                  parent_id=f"f:{folder['parent_uid']}" if folder.get("parent_uid") else None)
    source_parents = {}
    for link in relations:
        if link["from_document_uid"] in own_docs and link["to_uid"] in own_docs:
            source_parents.setdefault(link["from_document_uid"], set()).add(link["to_uid"])
    overrides = {p["document_uid"]: p for p in placements}
    for doc in documents:
        uid = doc["uid"]
        parent = None
        if uid in own_docs:
            if uid in overrides:
                p = overrides[uid]
                parent = f"f:{p['folder_uid']}" if p.get("folder_uid") else (
                    f"d:{p['parent_document_uid']}" if p.get("parent_document_uid") else None)
            else:
                candidates = source_parents.get(uid, set())
                if len(candidates) == 1:
                    parent = f"d:{next(iter(candidates))}"
                elif len(candidates) > 1:
                    warnings.add("Some source pages have multiple parents; they are shown in Unfiled documents until organised.")
        nodes[f"d:{uid}"] = dict(id=f"d:{uid}", kind="document", uid=uid, title=doc["title"], parent_id=parent)
    # WP overview pages are subsystem roots, including leaf WP pages.
    # Decide before recovery so damaged links/cycles stay in the repair group.
    source_children = {link["from_document_uid"] for link in relations}
    subsystem_roots = {
        node["id"] for node in nodes.values()
        if node["kind"] == "document" and node["uid"] in own_docs
        and node["parent_id"] is None
        and re.match(r"^WP[\s_-]*[0-9]+(?=$|[\s_:–—-])", node["title"].strip(), re.IGNORECASE)
        and (node["uid"] in overrides or node["uid"] not in source_children)
    }
    for node in nodes.values():
        if node["parent_id"] and node["parent_id"] not in nodes:
            node["parent_id"] = None
            warnings.add("Some navigation parents are unavailable; their visible items are shown at the root.")
    # Clear every member of a cycle, not just an arbitrary edge, and keep all records visible.
    if recover_cycles:
        finished = set()
        for start in nodes:
            path, positions = [], {}
            current = start
            while current is not None and current not in finished:
                if current in positions:
                    for member in path[positions[current]:]:
                        nodes[member]["parent_id"] = None
                    warnings.add("A cycle in source navigation was detected; affected items are shown at the root.")
                    break
                positions[current] = len(path)
                path.append(current)
                current = nodes[current]["parent_id"]
            finished.update(path)
    unfiled, shared = False, False
    for node in list(nodes.values()):
        if node["kind"] == "document" and node["parent_id"] is None:
            if node["id"] in subsystem_roots:
                continue
            if node["uid"] in own_docs:
                node["parent_id"] = "group:unfiled"
                unfiled = True
            else:
                node["parent_id"] = "group:shared"
                shared = True
    for present, ident, title in ((unfiled, "group:unfiled", "Unfiled documents"), (shared, "group:shared", "Shared documents")):
        if present:
            nodes[ident] = dict(id=ident, kind="group", uid=ident, title=title, parent_id=None)
    return sorted(nodes.values(), key=lambda n: (n["title"].casefold(), n["id"])), sorted(warnings)
