"""Keys for new records, made by the hub instead of typed by a person.

A key is unique across the whole installation, not only in its workspace,
and people were asked to invent one on every new record. Each workspace has
a pattern instead, and a record created without a key gets the next one:

    {WS}-{TYPE}-{SEQ:4}   ->   SPARC-IP-0042

Tokens:
    {WS}      the workspace id, upper case
    {TYPE}    the type's code: its metadata "key_prefix" when set, else the
              initials of its name ("Ion Pump" -> IP), or the first three
              letters of a one-word name ("Magnet" -> MAG)
    {YYYY}    the current year; {YY} its last two digits
    {SEQ}     the sequence number; {SEQ:n} pads it to n digits

A pattern has exactly one {SEQ}. The sequence counts per rendered prefix: with
{TYPE} in the pattern each type counts on its own, without it the workspace
has one sequence. A number already used as a key (by an import, or by hand) is
skipped rather than refused.

A key typed by a person is still accepted; generation only fills a blank.

Tickets get theirs from the same pattern, with TCK as their type ({WS}-TCK-0042), when they are created
however they are created. So do the records a beam model brings, instead of the name in the model file.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.schema import Schema
from app.models.workspace import Workspace

DEFAULT_PATTERN = "{WS}-{TYPE}-{SEQ:4}"

TOKEN = re.compile(r"\{([A-Z]+)(?::(\d+))?\}")
KNOWN = {"WS", "TYPE", "YYYY", "YY", "SEQ"}
# Outside the tokens: what the importers' keys already use.
LITERAL = re.compile(r"^[A-Za-z0-9._:/-]*$")
MAX_TRIES = 1000


class KeyPatternError(ValueError):
    pass


def validate_pattern(pattern: str) -> str:
    pattern = (pattern or "").strip()
    if not pattern:
        raise KeyPatternError("The pattern is empty.")
    seqs = 0
    for m in TOKEN.finditer(pattern):
        if m.group(1) not in KNOWN:
            raise KeyPatternError(f"Unknown token {{{m.group(1)}}}. Use {', '.join('{' + k + '}' for k in sorted(KNOWN))}.")
        if m.group(2) is not None and m.group(1) != "SEQ":
            raise KeyPatternError(f"Only {{SEQ}} takes a width, not {{{m.group(1)}}}.")
        if m.group(1) == "SEQ":
            seqs += 1
            if m.group(2) is not None and not 1 <= int(m.group(2)) <= 12:
                raise KeyPatternError("The {SEQ} width must be between 1 and 12.")
    if seqs != 1:
        raise KeyPatternError("The pattern needs exactly one {SEQ}, so every key is different.")
    if not LITERAL.match(TOKEN.sub("", pattern)):
        raise KeyPatternError("Outside the tokens, use only letters, digits and . _ : / -")
    return pattern


def pattern_for(workspace: Optional[Workspace]) -> str:
    return (workspace.asset_key_pattern if workspace is not None else None) or DEFAULT_PATTERN


def type_code(schema: Optional[Schema]) -> str:
    if schema is None:
        return "X"
    explicit = (schema.metadata_json or {}).get("key_prefix")
    if explicit:
        return re.sub(r"[^A-Za-z0-9]", "", str(explicit)).upper() or "X"
    words = re.findall(r"[A-Za-z0-9]+", schema.name or "")
    if not words:
        return "X"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words).upper()


def _split(pattern: str, workspace_id: str, schema: Optional[Schema], now: datetime) -> tuple[str, str, int]:
    """(text before {SEQ}, text after it, width), with the other tokens filled."""
    values = {"WS": workspace_id.upper(), "TYPE": type_code(schema),
              "YYYY": f"{now.year:04d}", "YY": f"{now.year % 100:02d}"}
    seq = next(m for m in TOKEN.finditer(pattern) if m.group(1) == "SEQ")
    fill = lambda part: TOKEN.sub(lambda m: values[m.group(1)], part)  # noqa: E731
    return fill(pattern[:seq.start()]), fill(pattern[seq.end():]), int(seq.group(2) or 1)


TICKET_CODE = "TCK"


def ticket_type() -> Schema:
    """What a ticket's key is made from: a type of its own, whatever kind of ticket it is."""
    return Schema(name="Ticket", metadata_json={"key_prefix": TICKET_CODE})


def _taken(db: Session, key: str) -> bool:
    from app.models.issue import Issue
    return (db.scalar(select(Asset.uid).where(Asset.key == key)) is not None
            or db.scalar(select(Issue.uid).where(Issue.key == key)) is not None)


def _free(db: Session, before: str, after: str, width: int, start: int) -> tuple[str, int]:
    n = start
    for _ in range(MAX_TRIES):
        key = f"{before}{n:0{width}d}{after}"
        if not _taken(db, key):
            return key, n
        n += 1
    raise KeyPatternError(f"No free key after {MAX_TRIES} tries from {before}{start:0{width}d}{after}.")


def preview(db: Session, workspace_id: str, schema: Optional[Schema]) -> str:
    """The key the next record would get. Nothing is reserved: another
    record created meanwhile may take it, and this one then gets the next."""
    pattern = pattern_for(db.get(Workspace, workspace_id))
    before, after, width = _split(pattern, workspace_id, schema, datetime.now(timezone.utc))
    scope = before + "#" + after
    current = db.execute(text("SELECT next_value FROM asset_key_counters WHERE workspace_id = :w AND scope = :s"),
                         {"w": workspace_id, "s": scope}).scalar()
    return _free(db, before, after, width, current or 1)[0]


def allocate(db: Session, workspace_id: str, schema: Optional[Schema]) -> str:
    """The next key, taken. The counter row is locked until the caller's
    transaction ends, so two records created at once never get the same key,
    and a creation that fails rolls its number back."""
    pattern = pattern_for(db.get(Workspace, workspace_id))
    before, after, width = _split(pattern, workspace_id, schema, datetime.now(timezone.utc))
    scope = before + "#" + after
    db.execute(text("INSERT INTO asset_key_counters (workspace_id, scope, next_value) VALUES (:w, :s, 1) "
                    "ON CONFLICT DO NOTHING"), {"w": workspace_id, "s": scope})
    current = db.execute(text("SELECT next_value FROM asset_key_counters WHERE workspace_id = :w AND scope = :s "
                              "FOR UPDATE"), {"w": workspace_id, "s": scope}).scalar_one()
    key, used = _free(db, before, after, width, current)
    db.execute(text("UPDATE asset_key_counters SET next_value = :n WHERE workspace_id = :w AND scope = :s"),
               {"n": used + 1, "w": workspace_id, "s": scope})
    return key


def example(pattern: str, workspace_id: str) -> str:
    """What the pattern gives for a first Ion Pump, to show beside the setting."""
    before, after, width = _split(pattern, workspace_id, Schema(name="Ion Pump", metadata_json={}),
                                  datetime.now(timezone.utc))
    return f"{before}{1:0{width}d}{after}"


def backfill_ticket_keys(db: Session, workspace_id: str) -> list[tuple[str, str]]:
    """Keys for the tickets made before tickets had keys, oldest first. (uid, key) of each; the caller commits."""
    from app.models.issue import Issue
    done = []
    for issue in db.scalars(select(Issue).where(Issue.workspace_id == workspace_id, Issue.key.is_(None))
                            .order_by(Issue.created_at, Issue.uid)):
        issue.key = allocate(db, workspace_id, ticket_type())
        done.append((issue.uid, issue.key))
    db.flush()
    return done
