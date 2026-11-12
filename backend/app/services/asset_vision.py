"""Reading a photograph of equipment into a draft object.

Somebody standing in front of a rack with a phone knows more than they
can be bothered to type. A photograph carries the type of thing, its
manufacturer, often a model number, and — if the label is in shot — the
object key that ties it to everything already recorded about it.

What comes back is a draft for a form, not a record. The model is told
which object types this workspace actually has, so it cannot invent one,
and any key it reads is checked against the inventory rather than
believed: a key that matches is a real link, and a key that matches
nothing is shown as text somebody can correct.
"""
import json
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.schema import Schema
from app.services.ai_suggestions import CODE_FENCE, THINK_BLOCK
from app.services.llm import Endpoint, look

# Anything larger is a phone photograph at full resolution; the model gains
# nothing from the extra pixels and the request gets slower for everyone.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# The shape an object key takes here — letters, then digits.
KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,8}\b")

SYSTEM_PROMPT = (
    "You identify equipment in photographs taken in a laboratory or technical facility, "
    "for an inventory.\n"
    "Answer with JSON only, no prose and no markdown fences:\n"
    '{"type": "<one of the given type names, or null>", '
    '"name": "<a short descriptive name>", '
    '"manufacturer": "<or null>", "model": "<or null>", '
    '"serial": "<or null>", '
    '"visible_text": ["<any text, labels or codes legible in the photo>"], '
    '"description": "<one or two sentences about what is shown>", '
    '"confidence": "high|medium|low"}\n'
    "Report only what you can actually see. If you cannot tell what something is, "
    "say so with a null type and low confidence rather than guessing."
)


def parse_identification(reply: str, valid_types: set[str]) -> Optional[dict]:
    """The JSON object inside whatever the model said, with its claims
    about type restricted to types that exist here."""
    text = THINK_BLOCK.sub("", reply or "").strip()
    fenced = CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    proposed_type = data.get("type")
    if not isinstance(proposed_type, str) or proposed_type not in valid_types:
        # A type this workspace does not have is not a type. Everything
        # else the model saw is still worth keeping.
        data["type"] = None

    visible = data.get("visible_text")
    if isinstance(visible, str):
        visible = [visible]
    data["visible_text"] = [v for v in (visible or []) if isinstance(v, str)]

    for field in ("name", "manufacturer", "model", "serial", "description"):
        value = data.get(field)
        data[field] = value.strip() if isinstance(value, str) and value.strip() else None

    if data.get("confidence") not in ("high", "medium", "low"):
        data["confidence"] = "low"
    return data


def identify(
    db: Session,
    workspace_id: str,
    endpoint: Endpoint,
    image: bytes,
    mime_type: str,
) -> dict:
    """What is in this photograph, as a draft for the new-object form."""
    types = {
        s.name: s.uid
        for s in db.scalars(
            select(Schema).where(
                Schema.workspace_id == workspace_id,
                Schema.applies_to == "objects",
            )
        )
        if s.name
    }

    catalogue = ", ".join(sorted(types)) or "(this workspace has no object types yet)"
    reply = look(
        endpoint,
        image,
        mime_type,
        SYSTEM_PROMPT,
        f"Object types available in this inventory: {catalogue}\n\n"
        "Identify the equipment in this photograph.",
    )

    data = parse_identification(reply, set(types))
    if data is None:
        return {
            "type_uid": None,
            "type_name": None,
            "name": None,
            "manufacturer": None,
            "model": None,
            "serial": None,
            "description": None,
            "visible_text": [],
            "confidence": "low",
            "matches": [],
            "unmatched_keys": [],
            "error": "The model's answer could not be read.",
        }

    # Any key it read, checked against what is actually recorded. A key
    # that resolves is a link worth proposing; one that does not is text
    # somebody can correct, not a relation to invent.
    candidates: set[str] = set()
    for text in [*data["visible_text"], data.get("serial") or "", data.get("name") or ""]:
        candidates.update(KEY_PATTERN.findall(text.upper()))

    matches, unmatched = [], []
    for key in sorted(candidates):
        asset = db.scalar(
            select(Asset).where(Asset.workspace_id == workspace_id, Asset.key == key)
        )
        if asset is not None:
            matches.append({"uid": asset.uid, "key": asset.key, "name": asset.name})
        else:
            unmatched.append(key)

    return {
        "type_uid": types.get(data["type"]) if data.get("type") else None,
        "type_name": data.get("type"),
        "name": data.get("name"),
        "manufacturer": data.get("manufacturer"),
        "model": data.get("model"),
        "serial": data.get("serial"),
        "description": data.get("description"),
        "visible_text": data["visible_text"],
        "confidence": data["confidence"],
        "matches": matches,
        "unmatched_keys": unmatched,
        "error": None,
    }
