"""Workspace-serialised navigation writes; document/revision content is untouched."""
from sqlalchemy import select

from app.models.document import Document, DocumentRelation
from app.models.document_navigation import DocumentFolder, DocumentPlacement
from app.models.workspace import Workspace
from app.services.document_navigation_graph import assert_parent_move, navigation_nodes


def lock_workspace(db, workspace_id):
    if db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update()) is None:
        raise ValueError("Workspace not found.")


def folder_dict(folder):
    return {"uid": folder.uid, "name": folder.name, "parent_uid": folder.parent_uid,
            "workspace_id": folder.workspace_id}


def placement_dict(row):
    return {"document_uid": row.document_uid, "folder_uid": row.folder_uid,
            "parent_document_uid": row.parent_document_uid}


def graph(db, workspace_id, documents, recover_cycles=True):
    folders = db.scalars(select(DocumentFolder).where(DocumentFolder.workspace_id == workspace_id)).all()
    placements = db.scalars(select(DocumentPlacement).where(DocumentPlacement.workspace_id == workspace_id)).all()
    relations = db.scalars(select(DocumentRelation).where(
        DocumentRelation.workspace_id == workspace_id, DocumentRelation.to_type == "document",
        DocumentRelation.relation_type == "child_of",
    )).all()
    nodes, warnings = navigation_nodes(
        [folder_dict(f) for f in folders], documents, [placement_dict(p) for p in placements],
        [{"from_document_uid": r.from_document_uid, "to_uid": r.to_uid} for r in relations], workspace_id, recover_cycles=recover_cycles,
    )
    return folders, nodes, warnings


def all_parent_ids(db, workspace_id):
    docs = db.scalars(select(Document).where(Document.workspace_id == workspace_id)).all()
    _, nodes, _ = graph(db, workspace_id, [
        {"uid": d.uid, "title": "", "workspace_id": workspace_id} for d in docs
    ], recover_cycles=False)
    return {n["id"]: n["parent_id"] for n in nodes}


def owned_folder(db, workspace_id, uid):
    folder = db.get(DocumentFolder, uid)
    if folder is None or folder.workspace_id != workspace_id:
        raise ValueError("Folder not found in this workspace.")
    return folder


def write_folder(db, workspace_id, folder, name, parent_uid):
    name = name.strip()
    parent_uid = parent_uid or None
    if not name or len(name) > 240:
        raise ValueError("Give the folder a name of 1–240 characters.")
    if parent_uid:
        owned_folder(db, workspace_id, parent_uid)
    assert_parent_move(all_parent_ids(db, workspace_id), f"f:{folder.uid}", f"f:{parent_uid}" if parent_uid else None)
    siblings = db.scalars(select(DocumentFolder).where(
        DocumentFolder.workspace_id == workspace_id, DocumentFolder.parent_uid == parent_uid,
    )).all()
    if any(f.uid != folder.uid and f.name.casefold() == name.casefold() for f in siblings):
        raise ValueError("A folder with that name already exists under this parent.")
    folder.name, folder.parent_uid = name, parent_uid
    db.add(folder)


def set_document_location(db, workspace_id, uid, folder_uid=None, parent_document_uid=None):
    """Caller holds the workspace lock and has checked visibility of source/parent."""
    folder_uid, parent_document_uid = folder_uid or None, parent_document_uid or None
    if folder_uid and parent_document_uid:
        raise ValueError("Choose either a folder or a parent document.")
    doc = db.get(Document, uid)
    if doc is None or doc.workspace_id != workspace_id:
        raise ValueError("Document not found in this workspace.")
    if folder_uid:
        owned_folder(db, workspace_id, folder_uid)
    if parent_document_uid:
        parent = db.get(Document, parent_document_uid)
        if parent is None or parent.workspace_id != workspace_id:
            raise ValueError("The parent document must belong to this workspace.")
    parent_id = f"f:{folder_uid}" if folder_uid else (f"d:{parent_document_uid}" if parent_document_uid else None)
    assert_parent_move(all_parent_ids(db, workspace_id), f"d:{uid}", parent_id)
    placement = db.get(DocumentPlacement, uid)
    if placement is None:
        placement = DocumentPlacement(document_uid=uid, workspace_id=workspace_id)
    elif placement.workspace_id != workspace_id:
        # A controlled document can be moved by ARGUS's existing transfer flow.
        # Its old workspace's navigation override is not a location in the new one.
        placement.workspace_id = workspace_id
    placement.folder_uid, placement.parent_document_uid = folder_uid, parent_document_uid
    db.add(placement)
