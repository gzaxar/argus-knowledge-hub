"""Which recorded objects a piece of text actually mentions.

Deliberately not a model's job. Asking a model which equipment a document
refers to invites a confident answer about a magnet that does not exist,
and a wrong edge in the knowledge graph is worse than a missing one — it
is a fact the graph will happily repeat.

So the text is matched against the inventory: an object key is a key, and
a name that appears in the prose is a name. What comes back is a list of
things that are certainly there.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.asset import Asset

# The shape an object key takes here: letters, a hyphen, digits.
KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,8}\b")

# Any key as written, whatever its shape ("B12-HALL", "LINAC-TEST-STAND-IP-0001"): a whole word of letters, digits
# and the joiners keys use. A key shorter than this is too easily a coincidence ("A1").
WORD = re.compile(r"[A-Z0-9][A-Z0-9_.:-]*[A-Z0-9]|[A-Z0-9]")
MIN_KEY_LENGTH = 3

# A plant tag inside a name ("Gun ion pump IP-01"): letters, an optional hyphen, digits. People write the tag, not
# the name, so a tag that only one object carries names that object.
TAG = re.compile(r"(?<![A-Z0-9_.:-])([A-Z]{1,6}-?\d{1,4}[A-Z]?)(?![A-Z0-9_:-]|\.[A-Z0-9])")
MIN_TAG_LENGTH = 4

# Shorter names match too much — "PLC", "Rack" and "Cam" appear in prose
# that has nothing to do with a particular object.
MIN_NAME_LENGTH = 6


def objects_mentioned(db: Session, workspace_id: str, *texts: str) -> list[dict]:
    """Objects this text names, by key or by name.

    Each result says which it was, because the two are not equally strong:
    a key is an identifier somebody wrote down deliberately, a name could
    be a coincidence of words.
    """
    haystack = "\n".join(t for t in texts if t)
    if not haystack.strip():
        return []
    upper = haystack.upper()

    assets: list[Asset] = list(db.scalars(
        select(Asset).where(Asset.workspace_id == workspace_id, Asset.deleted_at.is_(None))
    ))

    found: dict[str, dict] = {}
    keys_in_text = set(KEY_PATTERN.findall(upper)) | {w for w in WORD.findall(upper) if len(w) >= MIN_KEY_LENGTH}
    tags_in_text = {t for t in TAG.findall(upper) if len(t) >= MIN_TAG_LENGTH}

    from app.services.visibility import can_see
    visible = [a for a in assets if can_see(a)]     # a restricted record is never named without its grant (I-ACL-1)
    carriers: dict[str, list[Asset]] = {}
    for asset in visible:
        for tag in set(TAG.findall((asset.name or "").upper())):
            if tag in tags_in_text and tag != (asset.key or "").upper():
                carriers.setdefault(tag, []).append(asset)
    by_tag = {a.uid: tag for tag, owners in carriers.items() if len(owners) == 1 for a in owners}

    for asset in visible:
        if asset.key and asset.key.upper() in keys_in_text:
            found[asset.uid] = {
                "uid": asset.uid,
                "key": asset.key,
                "name": asset.name,
                "matched_on": "key",
            }
            continue
        if asset.uid in by_tag:
            found[asset.uid] = {
                "uid": asset.uid,
                "key": asset.key,
                "name": asset.name,
                "matched_on": "tag",
                "matched": by_tag[asset.uid],
            }
            continue
        name = (asset.name or "").strip()
        if len(name) >= MIN_NAME_LENGTH and name.upper() in upper:
            found.setdefault(asset.uid, {
                "uid": asset.uid,
                "key": asset.key,
                "name": asset.name,
                "matched_on": "name",
            })

    # Keys first: they are the stronger evidence.
    strength = {"key": 0, "tag": 1, "name": 2}
    return sorted(found.values(), key=lambda row: (strength[row["matched_on"]], row["name"] or ""))
