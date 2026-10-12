"""The kinds of documentation an accelerator actually keeps.

Seeded so a workspace has somewhere to put a document on day one, and so
an import has a type to map onto rather than dropping everything into an
untyped pile.

The set is drawn from how accelerator and large-experiment documentation
is actually organised: a controlled procedure is a different object from
a shift logbook entry, and ARGUS has to tell them apart — an operator
asking "how do I recover the vacuum" wants the procedure, while "what
happened last Tuesday" wants the logbook. Same words, different
documents.

Fields are argus_* for the same reason tickets' are: this is the
application's model, and Confluence or Git is a source that maps onto it.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import Schema

BASE_UID_SUFFIX = "argus-document"
BASE_TYPE_NAME = "Document"

# The kinds of document (ordered roughly by how binding they are) and the fields every document carries:
# the core-facility package (backend/packages/core-facility/document_types.yaml). The operational keys are
# the ones tickets use, so a system names one thing across the hub; document control says which version
# is in force; where it came from is kept, read-only.
def _definitions():
    from app.packages import defaults
    return defaults.document_types()


DEFAULT_DOCUMENT_TYPES = [(name, description) for name, description, _ in _definitions().kinds]
BASE_DESCRIPTION = _definitions().base_description


def base_attributes() -> list[dict]:
    return [dict(a) for a in _definitions().base_attributes]


def type_uid(workspace_id: str, name: str) -> str:
    return f"{workspace_id}:{BASE_UID_SUFFIX}:{name.lower().replace(' ', '-')}"


def ensure_document_types(
    db: Session, workspace_id: str, extra_names: set[str] | None = None
) -> dict:
    """Create (or refresh) the base document type and one child per kind.
    Returns name -> schema uid.

    Idempotent: the base type's field set is kept current so a release that
    adds a field reaches existing workspaces, while children are left alone
    once created, since a workspace may have added fields of its own.
    """
    base_uid = f"{workspace_id}:{BASE_UID_SUFFIX}"
    base = db.get(Schema, base_uid)
    if base is None:
        base = Schema(
            uid=base_uid,
            workspace_id=workspace_id,
            name=BASE_TYPE_NAME,
            description=BASE_DESCRIPTION,
            applies_to="documents",
            is_concrete=False,
            attributes=base_attributes(),
            metadata_json={"source": "argus"},
        )
        db.add(base)
    else:
        base.attributes = base_attributes()
    db.flush()

    wanted = {name: description for name, description in DEFAULT_DOCUMENT_TYPES}
    for name in sorted(extra_names or set()):
        wanted.setdefault(name, None)

    out: dict[str, str] = {}
    for name, description in wanted.items():
        child_uid = type_uid(workspace_id, name)
        child = db.get(Schema, child_uid)
        if child is None:
            child = Schema(
                uid=child_uid,
                workspace_id=workspace_id,
                name=name,
                description=description,
                applies_to="documents",
                parent_schema_uid=base.uid,
                attributes=[],
                metadata_json={"source": "argus"},
            )
            db.add(child)
        out[name] = child_uid
    db.flush()
    # Each type its default icon, where it has none (catalogue_icons); never over one chosen or imported.
    from app.services import catalogue_icons
    # Every document type of the workspace, imported ones included (they take the base type's icon).
    from sqlalchemy import select as _select
    every = {s.name: s.uid for s in db.scalars(_select(Schema).where(Schema.workspace_id == workspace_id,
                                                                    Schema.applies_to == "documents"))}
    catalogue_icons.apply(db, workspace_id, every, False, icon_of=catalogue_icons.document_icon)
    return out


def existing_document_type_uids(db: Session, workspace_id: str) -> list[str]:
    base_uid = f"{workspace_id}:{BASE_UID_SUFFIX}"
    return list(
        db.scalars(
            select(Schema.uid).where(
                Schema.workspace_id == workspace_id,
                Schema.parent_schema_uid == base_uid,
            )
        )
    ) + [base_uid]
