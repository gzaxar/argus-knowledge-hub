import re
from typing import Optional, Type, Union

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.document import Document
from app.models.issue import Issue
from app.models.schema import Schema
from app.models.user import User

AttributeOwner = Union[Type[Asset], Type[Issue], Type[Document]]


def _descendant_schema_uids(db: Session, root_uid: str) -> set[str]:
    children_map: dict[str, list[str]] = {}
    rows = db.execute(select(Schema.uid, Schema.parent_schema_uid)).all()
    for uid, parent_uid in rows:
        if parent_uid:
            children_map.setdefault(parent_uid, []).append(uid)

    result: set[str] = set()
    stack = [root_uid]
    while stack:
        current = stack.pop()
        for child in children_map.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)
    return result


def effective_attributes(db: Session, schema: Schema) -> list[dict]:
    """A schema's own attributes plus everything inherited from its ancestor
    chain (root-most first). A child redefining an ancestor's key overrides
    it in place rather than duplicating it."""
    chain: list[Schema] = []
    seen: set[str] = set()
    current: Optional[Schema] = schema
    while current is not None and current.uid not in seen:
        chain.append(current)
        seen.add(current.uid)
        current = db.get(Schema, current.parent_schema_uid) if current.parent_schema_uid else None
    chain.reverse()  # root-most ancestor first, schema itself last

    merged: dict[str, dict] = {}
    for s in chain:
        for attr in s.attributes or []:
            key = attr.get("key") or attr.get("name")
            if key:
                merged[key] = attr
    return list(merged.values())


def _is_reference_visible(db: Session, target: Asset, workspace_id: str) -> bool:
    return target.workspace_id == workspace_id or bool(target.is_global)


def _is_duplicate(
    db: Session,
    owner: AttributeOwner,
    schema_uid: str,
    key: str,
    value: object,
    exclude_uid: Optional[str],
    schema_uid_attr: str,
) -> bool:
    rows = db.scalars(select(owner).where(getattr(owner, schema_uid_attr) == schema_uid)).all()
    for row in rows:
        if exclude_uid is not None and row.uid == exclude_uid:
            continue
        existing = (row.attributes or {}).get(key)
        if existing is not None and str(existing) == str(value):
            return True
    return False


def _check_single_attribute(
    db: Session,
    attr: dict,
    value: object,
    workspace_id: str,
    owner: AttributeOwner,
    schema_uid: str,
    exclude_uid: Optional[str],
    skip_reference: bool,
    schema_uid_attr: str,
    skip_unique: bool,
) -> Optional[str]:
    """Returns a human-readable violation message for this one attribute, or
    None if the value is fine. Never raises."""
    key = attr.get("key") or attr.get("name")
    if not key:
        return None
    name = attr.get("name", key)
    multi = bool(attr.get("multiValue"))
    is_empty = value is None or value == "" or (isinstance(value, list) and len(value) == 0)

    if attr.get("required") and is_empty:
        return f"{name} is required"
    if is_empty:
        return None

    if multi and not isinstance(value, list):
        return f"{name} must be given as a list of values"
    if not multi and isinstance(value, list):
        return f"{name} does not allow multiple values"

    if multi:
        count = len(value)
        min_c = attr.get("minCardinality")
        max_c = attr.get("maxCardinality")
        if min_c is not None and count < min_c:
            return f"{name} requires at least {min_c} value(s)"
        if max_c is not None and count > max_c:
            return f"{name} allows at most {max_c} value(s)"

    values = value if isinstance(value, list) else [value]
    attr_type = attr.get("type")

    regex = attr.get("regex")
    if regex and attr_type in ("string", "text"):
        try:
            pattern = re.compile(regex)
        except re.error:
            pattern = None
        if pattern is not None:
            for v in values:
                if not pattern.search(str(v)):
                    return f"{name} does not match the required format"

    if attr.get("validator"):
        # A check a package names by id and ARGUS implements (app/packages/validators.py). An id this release
        # does not know (a newer package's) is not enforced rather than blocking every save.
        from app.packages.validators import VALIDATORS, check
        if attr["validator"] in VALIDATORS:
            problem = check(attr["validator"], values)
            if problem:
                return f"{name}: {problem}"

    if attr_type == "enumeration":
        options = attr.get("options") or []
        allowed_values = {str(o.get("value")).lower() for o in options if o.get("value") is not None}
        if allowed_values:
            for v in values:
                if str(v).lower() not in allowed_values:
                    return f"{name} must be one of the configured choices"

    if attr_type == "reference" and not skip_reference:
        ref_schema_uid = attr.get("referenceSchemaUid")
        if ref_schema_uid:
            allowed = {ref_schema_uid}
            if attr.get("includeChildren"):
                allowed |= _descendant_schema_uids(db, ref_schema_uid)
            for v in values:
                target = db.get(Asset, v)
                if target is None or target.schema_uid not in allowed:
                    return f"{name} must reference an object of the correct type"
                if not _is_reference_visible(db, target, workspace_id):
                    return f"{name} references an object that is not accessible"

    if attr_type == "user":
        for v in values:
            if db.get(User, v) is None:
                return f"{name} must reference a registered user"

    if attr_type == "group":
        from app.models.group import Group
        for v in values:
            if db.get(Group, v) is None:
                return f"{name} must reference a group"

    if attr.get("unique") and not skip_unique:
        for v in values:
            if _is_duplicate(db, owner, schema_uid, key, v, exclude_uid, schema_uid_attr):
                return f"{name} must be unique: this value is already in use"

    return None


def check_attributes(
    db: Session,
    schema: Optional[Schema],
    attributes: dict,
    workspace_id: str,
    owner: AttributeOwner,
    exclude_uid: Optional[str] = None,
    skip_reference: bool = False,
    schema_uid_attr: str = "schema_uid",
    skip_unique: bool = False,
) -> list[str]:
    """Non-raising validation: returns every violation message found (empty
    list if the value set is fine). `skip_reference` is for bulk-import
    pipelines whose reference-attribute values aren't asset uids (they're
    resolved through a separate relation mechanism instead), so checking them
    here would only produce false positives. `schema_uid_attr` names the
    column on `owner` that holds the type/schema uid — "schema_uid" for
    Asset/Issue. `skip_unique` is for owners (like Document) whose attributes
    don't live on the same row as the type/schema uid, so the built-in
    same-table uniqueness query can't apply — callers handle it themselves."""
    if schema is None:
        return []
    violations = []
    for attr in effective_attributes(db, schema):
        key = attr.get("key") or attr.get("name")
        if not key:
            continue
        msg = _check_single_attribute(
            db, attr, attributes.get(key), workspace_id, owner, schema.uid, exclude_uid,
            skip_reference, schema_uid_attr, skip_unique,
        )
        if msg:
            violations.append(msg)
    return violations


def validate_attributes(
    db: Session,
    schema: Optional[Schema],
    attributes: dict,
    workspace_id: str,
    owner: AttributeOwner,
    exclude_uid: Optional[str] = None,
    schema_uid_attr: str = "schema_uid",
    skip_unique: bool = False,
) -> None:
    """Validate a set of attribute values against their schema's per-attribute
    rules (required, cardinality, regex, uniqueness, reference type), raising
    a 422 on the first violation. No-op when the record has no schema (e.g. a
    generic ticket)."""
    violations = check_attributes(
        db, schema, attributes, workspace_id, owner, exclude_uid,
        schema_uid_attr=schema_uid_attr, skip_unique=skip_unique,
    )
    if violations:
        raise HTTPException(status_code=422, detail=violations[0])
