"""The committed API contract (asset-model-revision §24.3, flutter-app-design §3.1).

`openapi/openapi.json` is the whole contract. `openapi/field-client.json` is
the subset the Flutter field client is generated from: the operations
listed in FIELD_OPERATIONS, and the schemas they reference. Both are
written by `python -m app.contract`. A test fails when the running API
and the committed contract differ, so a change to the API is a deliberate
change to the contract, reviewed with it (docs/api-policy.md).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "openapi"

# (method, path) the field client calls. Adding one here is how the field client starts using it.
FIELD_OPERATIONS = [
    ("get", "/v1/meta/api"),
    ("get", "/v1/me"),
    ("get", "/v1/me/workspaces"),
    ("post", "/v1/devices"),
    ("get", "/v1/devices"),
    ("post", "/v1/devices/{device_id}/revoke"),
    ("get", "/v1/links/resolve"),
    ("get", "/v1/lookup/{identifier}"),
    ("get", "/v1/hub/search"),
    ("get", "/v1/graph"),
    ("get", "/v1/graph/semantic"),
    ("get", "/v1/hub/overview"),
    ("get", "/v1/assets/{uid}"),
    ("get", "/v1/hub/assets/{uid}/context"),
    ("get", "/v1/installations"),
    ("get", "/v1/schemas/{uid}"),
    ("get", "/v1/issues/{uid}"),
    ("get", "/v1/hub/tickets/{uid}/context"),
    ("get", "/v1/documents/{uid}"),
    ("get", "/v1/documents/{uid}/current"),
    ("get", "/v1/hub/documents/{uid}/context"),
    # Writes (M0: every one accepts Idempotency-Key; edits take If-Match with the version read)
    ("put", "/v1/assets/{uid}"),
    ("post", "/v1/installations/swap"),
    ("post", "/v1/issues"),
    ("put", "/v1/issues/{uid}"),
    ("post", "/v1/issues/{uid}/transition"),
    ("get", "/v1/issues/{uid}/comments"),
    ("post", "/v1/issues/{uid}/comments"),
    ("get", "/v1/issues/{uid}/attachments"),
    ("post", "/v1/uploads"),
    ("get", "/v1/uploads/{uid}"),
    ("put", "/v1/uploads/{uid}"),
    ("post", "/v1/uploads/{uid}/complete"),
    ("post", "/v1/uploads/{uid}/attach/ticket/{issue_uid}"),
    ("post", "/v1/uploads/{uid}/attach/asset/{asset_uid}"),
    ("post", "/v1/uploads/{uid}/attach/document/{doc_uid}/revision/{rev_uid}"),
    ("get", "/v1/documents/{uid}/revisions/{rev_uid}/attachments"),
    # Capture and tickets (M2)
    ("get", "/v1/schemas"),
    ("get", "/v1/assets"),
    ("get", "/v1/assets/type-counts"),
    ("post", "/v1/assets"),
    ("get", "/v1/issues/{uid}/transitions"),
    ("post", "/v1/intake/guide/asset"),
    ("post", "/v1/intake/guide/ticket"),
    ("post", "/v1/intake/assist/ticket"),
    ("post", "/v1/intake/assist/{kind}/file"),
    ("post", "/v1/intake/runs/{run_id}/outcome"),
    ("get", "/v1/notifications"),
    ("post", "/v1/notifications/{nid}/read"),
    ("get", "/v1/notifications/subscriptions"),
    ("put", "/v1/notifications/subscriptions/{workspace_id}"),
    ("get", "/v1/notifications/everywhere"),
    ("post", "/v1/notifications/everywhere/{nid}/read"),
    ("post", "/v1/notifications/everywhere/read-all"),
    ("get", "/v1/notifications/following"),
    ("get", "/v1/notifications/following/{subject}/{uid}"),
    ("put", "/v1/notifications/following/{subject}/{uid}"),
    ("delete", "/v1/notifications/following/{subject}/{uid}"),
    ("get", "/v1/hub/my-work"),
    ("get", "/v1/search/jql"),
    ("get", "/v1/search/jql/fields"),
    ("get", "/v1/assets/{uid}/location"),
    ("post", "/v1/assets/{uid}/location/observations"),
    ("get", "/v1/map/nearby"),
    ("get", "/v1/workspaces/{workspace_id}/capabilities"),
    ("get", "/v1/location-reviews"),
    ("post", "/v1/location-reviews/{obs_id}/accept"),
    ("post", "/v1/location-reviews/{obs_id}/reject"),
    # Next to the equipment: what else references it, its files, and what people have said and done to it
    ("get", "/v1/assets/{asset_uid}/comments"),
    ("post", "/v1/assets/{asset_uid}/comments"),
    ("get", "/v1/assets/{asset_uid}/history"),
    ("get", "/v1/assets/{asset_uid}/labels"),
    ("post", "/v1/assets/{asset_uid}/labels"),
    ("delete", "/v1/assets/{asset_uid}/labels/{label_uid}"),
    ("get", "/v1/attachments"),
    ("get", "/v1/attachments/{uid}"),
    # Replacement and review (M3)
    ("post", "/v1/installations/replace"),
    ("get", "/v1/ledger/review/mine"),
    ("post", "/v1/ledger/review/replacements/{conflict_id}/confirm"),
    ("post", "/v1/ledger/review/replacements/{conflict_id}/reject"),
    ("post", "/v1/ledger/review/stale/{conflict_id}/close"),
    ("post", "/v1/intake/proposals/{claim_id}"),
    # Offline (M4): the assigned tickets prefetched for offline use; also the ticket list
    ("get", "/v1/issues"),
    # Tickets' priorities and states, in the order the workspace defines them
    ("get", "/v1/global-values"),
    # Documents: the list, writing one, and its revisions' draft → review → approval → publication
    ("get", "/v1/documents"),
    ("post", "/v1/documents"),
    ("put", "/v1/documents/{uid}"),
    ("post", "/v1/documents/{uid}/relations"),
    ("get", "/v1/documents/{uid}/revisions"),
    ("post", "/v1/documents/{uid}/revisions"),
    ("put", "/v1/documents/{uid}/revisions/{rev_uid}"),
    ("post", "/v1/documents/{uid}/revisions/{rev_uid}/submit"),
    ("post", "/v1/documents/{uid}/revisions/{rev_uid}/approve"),
    ("post", "/v1/documents/{uid}/revisions/{rev_uid}/publish"),
    # Ask: questions answered from the workspace's records, as a conversation. The chat's answer is
    # server-sent events, which the generated client cannot stream: the app reads them itself.
    ("get", "/v1/ai/status"),
    ("post", "/v1/ai/transcribe"),
    ("post", "/v1/ai/draft-document"),
    ("post", "/v1/ai/chat"),
    ("get", "/v1/ai/conversations"),
    ("get", "/v1/ai/conversations/{conversation_id}"),
]


def full() -> dict:
    from app.main import app
    return app.openapi()


def _refs(node, found: set) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for v in node.values():
            _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)


def field_subset(spec: dict) -> dict:
    """The field client's operations, and every schema they reach."""
    out = {k: copy.deepcopy(v) for k, v in spec.items() if k not in ("paths", "components")}
    out["info"] = {**spec.get("info", {}), "title": "ARGUS field client API"}
    out["paths"] = {}
    for method, path in FIELD_OPERATIONS:
        op = spec["paths"].get(path, {}).get(method)
        if op is None:
            raise KeyError(f"{method.upper()} {path} is not in the API")
        op = copy.deepcopy(op)
        # FastAPI's operation id is "<function>_v1_<path>_<method>"; the function name reads better in a client.
        op["operationId"] = op.get("operationId", "").split("_v1_")[0] or op.get("operationId")
        out["paths"].setdefault(path, {})[method] = op
    ids = [o["operationId"] for p in out["paths"].values() for o in p.values()]
    if len(ids) != len(set(ids)):
        raise ValueError(f"field-client operation ids are not unique: {sorted(ids)}")
    schemas = spec.get("components", {}).get("schemas", {})
    needed: set = set()
    _refs(out["paths"], needed)
    while True:
        before = set(needed)
        for name in list(needed):
            _refs(schemas.get(name, {}), needed)
        if needed == before:
            break
    out["components"] = {"schemas": {k: schemas[k] for k in sorted(needed) if k in schemas}}
    return _for_generators(out)


PRIMITIVES = {"string", "integer", "number", "boolean"}


def _untyped(schema) -> bool:
    return isinstance(schema, dict) and not (set(schema) & {"type", "$ref", "anyOf", "oneOf", "allOf", "enum"})


def _nullable(schema) -> bool:
    if not isinstance(schema, dict):
        return False
    options = schema.get("anyOf") or schema.get("oneOf") or []
    return schema.get("nullable") is True or schema.get("type") == "null" or any(
        isinstance(o, dict) and o.get("type") == "null" for o in options)


def _for_generators(node):
    """Client generators cannot type a value that is one of several primitive types (FastAPI's
    validation-error `loc` is a string or an integer). Such a value becomes "any value". Nor can
    they type a list of "any value" (the Dart generator emits `Object.listFromJson`), so such a
    list becomes "any value" too. Object defaults are dropped (see below)."""
    if isinstance(node, dict):
        options = node.get("anyOf")
        if isinstance(options, list) and len(options) > 1 and all(
                isinstance(o, dict) and set(o) <= {"type"} and o.get("type") in PRIMITIVES for o in options) \
                and len({o["type"] for o in options}) > 1:
            node = {k: v for k, v in node.items() if k != "anyOf"}
        node = {k: _for_generators(v) for k, v in node.items()}
        # A property that may be null is not "required" to a generator: the Dart one asserts that a
        # required key is non-null, and "present and null" and "absent" mean the same to a client.
        props, required = node.get("properties"), node.get("required")
        if isinstance(props, dict) and isinstance(required, list):
            kept = [r for r in required if not _nullable(props.get(r))]
            node = {**node, "required": kept} if kept else {k: v for k, v in node.items() if k != "required"}
        # An object default ({}) becomes a non-constant default in Dart; the server applies it anyway.
        if isinstance(node.get("default"), dict):
            node = {k: v for k, v in node.items() if k != "default"}
        # So does an enum's default: the Dart generator falls back to the bare string, not the enum value.
        if "enum" in node and "default" in node:
            node = {k: v for k, v in node.items() if k != "default"}
        if node.get("type") == "array" and _untyped(node.get("items")):
            node = {k: v for k, v in node.items() if k not in ("type", "items")}
        # One of "any value" (such a list, made so just above) or something else is any value, null included;
        # the Dart generator cannot process an untyped option inside anyOf at all.
        options = node.get("anyOf")
        if isinstance(options, list) and any(_untyped(o) for o in options):
            node = {k: v for k, v in node.items() if k != "anyOf"}
        return node
    if isinstance(node, list):
        return [_for_generators(v) for v in node]
    return node


def dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write() -> list[Path]:
    ROOT.mkdir(exist_ok=True)
    spec = full()
    files = {ROOT / "openapi.json": spec, ROOT / "field-client.json": field_subset(spec)}
    for path, content in files.items():
        path.write_text(dump(content))
    return list(files)


if __name__ == "__main__":
    for p in write():
        print(f"wrote {p}")
    sys.exit(0)
