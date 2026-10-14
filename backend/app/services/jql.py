"""Advanced query over tickets, equipment and documents, in the query language Jira's searches use.

What a Jira user already writes works here:

    status = "In Progress" AND assignee = currentUser() ORDER BY priority DESC, updated DESC
    project in (sparc, eli) AND created >= -7d AND summary ~ "vacuum leak"
    type = "Ion Pump" AND serial ~ "VPI-" AND label = LNFMAC-128463
    status = published AND updated > startOfMonth() ORDER BY key

The grammar is Jira's: clauses `field operator value` joined by AND, OR and NOT, grouped with parentheses,
then an optional ORDER BY. Operators: = != ~ !~ > >= < <= IN, NOT IN, IS EMPTY, IS NOT EMPTY (NULL is EMPTY).
Values: words, "quoted strings", numbers, lists `(a, b)`, dates (`2026-10-01`, `"2026-10-01 14:00"`), relative
dates (`-7d`, `-2w`, `-4h`, `-30m`, `1y`) and the functions currentUser(), now(), startOfDay(),
endOfDay(), startOfWeek(), endOfWeek(), startOfMonth(), endOfMonth(), startOfYear(), endOfYear() — each
taking an optional offset such as startOfDay(-1) or startOfMonth("-1M").

Each kind of record has its fields (`FIELDS`); any other name is one of the record's attributes (a custom
field), also written `cf[name]` or `"Field name"`. `text ~ word` looks in everything written.

The query is compiled into SQL: nothing is evaluated in Python but the visibility of each record (I-ACL-1).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import Numeric, String, and_, case, cast, false, func, not_, or_, select, true
from sqlalchemy.orm import Session


class JqlError(ValueError):
    """A query that cannot be read or run; `position` is where in it (0-based), when known."""

    def __init__(self, message: str, position: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.position = position


# --------------------------------------------------------------------------- tokens

KEYWORDS = {"AND", "OR", "NOT", "IN", "IS", "EMPTY", "NULL", "ORDER", "BY", "ASC", "DESC", "WAS", "CHANGED"}
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<op>!=|!~|>=|<=|=|~|>|<)
  | (?P<punct>[(),])
  | (?P<amp>&&|\|\|)
  | (?P<word>[^\s"'(),=!~<>&|]+(?:\[[^\]]*\])?)
""", re.X)


@dataclass
class Tok:
    kind: str          # string | op | punct | word | end
    value: str
    pos: int
    quoted: bool = False

    @property
    def upper(self) -> str:
        return self.value.upper() if self.kind == "word" else ""


def tokenize(text: str) -> list[Tok]:
    out, i = [], 0
    while i < len(text):
        m = _TOKEN.match(text, i)
        if m is None:
            raise JqlError(f"Unexpected character {text[i]!r}", i)
        kind = m.lastgroup
        raw = m.group(kind)
        if kind == "string":
            body = raw[1:-1]
            out.append(Tok("string", re.sub(r"\\(.)", r"\1", body), i, True))
        elif kind == "amp":
            out.append(Tok("word", "AND" if raw == "&&" else "OR", i))
        elif kind != "ws":
            out.append(Tok(kind, raw, i))
        i = m.end()
    out.append(Tok("end", "", len(text)))
    return out


# --------------------------------------------------------------------------- syntax tree

@dataclass
class Value:
    text: str
    pos: int
    quoted: bool = False
    function: Optional[str] = None
    args: list[str] = field(default_factory=list)


@dataclass
class Clause:
    field: str
    op: str                 # = != ~ !~ > >= < <= IN NOT IN IS IS NOT
    values: list[Value]
    pos: int


@dataclass
class Bool:
    op: str                 # AND | OR | NOT
    items: list[Any]


@dataclass
class Query:
    where: Optional[Any]
    order: list[tuple[str, bool]]   # (field, descending)


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.toks = tokenize(text)
        self.i = 0

    @property
    def tok(self) -> Tok:
        return self.toks[self.i]

    def take(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_word(self, word: str) -> None:
        if self.tok.upper != word:
            raise JqlError(f"Expected {word}", self.tok.pos)
        self.take()

    def parse(self) -> Query:
        where = None
        if not (self.tok.kind == "end" or self.tok.upper == "ORDER"):
            where = self.or_expr()
        order: list[tuple[str, bool]] = []
        if self.tok.upper == "ORDER":
            self.take()
            self.expect_word("BY")
            while True:
                t = self.take()
                if t.kind not in ("word", "string") or (t.kind == "word" and t.upper in KEYWORDS):
                    raise JqlError("Expected a field to order by", t.pos)
                desc = False
                if self.tok.upper in ("ASC", "DESC"):
                    desc = self.take().upper == "DESC"
                order.append((t.value, desc))
                if self.tok.kind == "punct" and self.tok.value == ",":
                    self.take()
                    continue
                break
        if self.tok.kind != "end":
            raise JqlError(f"Unexpected {self.tok.value!r}: expected AND, OR or ORDER BY", self.tok.pos)
        return Query(where, order)

    def or_expr(self):
        items = [self.and_expr()]
        while self.tok.upper == "OR":
            self.take()
            items.append(self.and_expr())
        return items[0] if len(items) == 1 else Bool("OR", items)

    def and_expr(self):
        items = [self.not_expr()]
        while self.tok.upper == "AND":
            self.take()
            items.append(self.not_expr())
        return items[0] if len(items) == 1 else Bool("AND", items)

    def not_expr(self):
        if self.tok.upper == "NOT" or (self.tok.kind == "op" and self.tok.value == "!" ):
            self.take()
            return Bool("NOT", [self.not_expr()])
        if self.tok.kind == "punct" and self.tok.value == "(":
            self.take()
            inner = self.or_expr()
            if not (self.tok.kind == "punct" and self.tok.value == ")"):
                raise JqlError("Expected )", self.tok.pos)
            self.take()
            return inner
        return self.clause()

    def clause(self) -> Clause:
        f = self.take()
        if f.kind not in ("word", "string") or (f.kind == "word" and f.upper in KEYWORDS):
            raise JqlError("Expected a field name", f.pos)
        t = self.tok
        if t.kind == "op":
            op = self.take().value
        elif t.upper == "IN":
            self.take()
            op = "IN"
        elif t.upper == "NOT":
            self.take()
            self.expect_word("IN")
            op = "NOT IN"
        elif t.upper == "IS":
            self.take()
            op = "IS"
            if self.tok.upper == "NOT":
                self.take()
                op = "IS NOT"
            if self.tok.upper not in ("EMPTY", "NULL"):
                raise JqlError("Expected EMPTY after IS", self.tok.pos)
            self.take()
            return Clause(f.value, op, [], f.pos)
        elif t.upper in ("WAS", "CHANGED"):
            raise JqlError(f"{t.upper} (history searches) is not supported", t.pos)
        else:
            raise JqlError(f"Expected an operator after {f.value!r}", t.pos)
        if op in ("IN", "NOT IN"):
            if not (self.tok.kind == "punct" and self.tok.value == "("):
                values = [self.value()]       # `status in Open` is accepted as a list of one
            else:
                self.take()
                values = [self.value()]
                while self.tok.kind == "punct" and self.tok.value == ",":
                    self.take()
                    values.append(self.value())
                if not (self.tok.kind == "punct" and self.tok.value == ")"):
                    raise JqlError("Expected ) to close the list", self.tok.pos)
                self.take()
        else:
            if self.tok.upper in ("EMPTY", "NULL"):
                self.take()
                return Clause(f.value, "IS" if op == "=" else "IS NOT" if op == "!=" else op, [], f.pos)
            values = [self.value()]
        return Clause(f.value, op, values, f.pos)

    def value(self) -> Value:
        t = self.take()
        if t.kind == "string":
            return Value(t.value, t.pos, quoted=True)
        if t.kind != "word" or t.upper in ("AND", "OR", "ORDER"):
            raise JqlError("Expected a value", t.pos)
        if self.tok.kind == "punct" and self.tok.value == "(":
            self.take()
            args = []
            while not (self.tok.kind == "punct" and self.tok.value == ")"):
                a = self.take()
                if a.kind == "end":
                    raise JqlError(f"Expected ) to close {t.value}(", a.pos)
                if a.kind == "punct" and a.value == ",":
                    continue
                args.append(a.value)
            self.take()
            return Value(t.value, t.pos, function=t.value.lower(), args=args)
        return Value(t.value, t.pos)


def parse(text: str) -> Query:
    return Parser(text or "").parse()


# --------------------------------------------------------------------------- values

_REL = re.compile(r"^([+-]?)(\d+)\s*([ywdhmMW]|mo)$")
_UNITS = {"y": 365 * 24 * 60, "M": 30 * 24 * 60, "mo": 30 * 24 * 60, "w": 7 * 24 * 60, "W": 7 * 24 * 60,
          "d": 24 * 60, "h": 60, "m": 1}


def _offset(spec: str) -> timedelta:
    m = _REL.match(spec.strip().strip("\"'"))
    if not m:
        raise JqlError(f"Not a time offset: {spec!r} (for example -7d, 2w, -4h)")
    sign = -1 if m.group(1) == "-" else 1
    return timedelta(minutes=sign * int(m.group(2)) * _UNITS[m.group(3)])


def _bounds(fn: str, at: datetime) -> datetime:
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    if fn == "startofday":
        return day
    if fn == "endofday":
        return day + timedelta(days=1) - timedelta(microseconds=1)
    if fn == "startofweek":
        return day - timedelta(days=day.weekday())
    if fn == "endofweek":
        return day - timedelta(days=day.weekday()) + timedelta(days=7) - timedelta(microseconds=1)
    if fn == "startofmonth":
        return day.replace(day=1)
    if fn == "endofmonth":
        first = day.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return nxt - timedelta(microseconds=1)
    if fn == "startofyear":
        return day.replace(month=1, day=1)
    if fn == "endofyear":
        return day.replace(year=day.year + 1, month=1, day=1) - timedelta(microseconds=1)
    raise JqlError(f"Unknown function {fn}()")


DATE_FUNCTIONS = {"now", "startofday", "endofday", "startofweek", "endofweek", "startofmonth", "endofmonth",
                  "startofyear", "endofyear"}


def to_datetime(v: Value, now: datetime) -> datetime:
    if v.function:
        if v.function not in DATE_FUNCTIONS:
            raise JqlError(f"{v.text}() is not a date", v.pos)
        base = now if v.function == "now" else _bounds(v.function, now)
        if v.args:
            # startOfDay(-1) is yesterday's start; startOfMonth("-1M") last month's.
            arg = v.args[0].strip("\"'")
            if re.fullmatch(r"[+-]?\d+", arg):
                unit = {"startofday": "d", "endofday": "d", "startofweek": "w", "endofweek": "w",
                        "startofmonth": "M", "endofmonth": "M", "startofyear": "y", "endofyear": "y"}.get(v.function, "d")
                arg = f"{arg}{unit}"
            if v.function in ("startofmonth", "endofmonth") and _REL.match(arg) and _REL.match(arg).group(3) in ("M", "mo"):
                months = int(_REL.match(arg).group(2)) * (-1 if arg.startswith("-") else 1)
                y, m = divmod(base.month - 1 + months, 12)
                anchor = base.replace(year=base.year + y, month=m + 1, day=1)
                return _bounds(v.function, anchor)
            base = base + _offset(arg)
        return base
    text = v.text.strip()
    if _REL.match(text):
        return now + _offset(text)
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise JqlError(f"Not a date: {v.text!r} (use 2026-10-01, \"2026-10-01 14:00\", -7d or startOfDay())", v.pos)


# --------------------------------------------------------------------------- compiling

@dataclass
class Ctx:
    db: Session
    user_ids: list[str]           # the signed-in person's id and e-mail: currentUser()
    now: datetime
    workspaces: list[str]         # those the person may search
    current_workspace: Optional[str]
    grants: Any = None            # what the person may see of restricted records and fields
    project_named: bool = False


@dataclass
class Field:
    """How one field of one kind of record is searched: its kind decides what the operators mean."""
    kind: str                                    # text | enum | date | user | number | bool | special
    column: Optional[Callable[[], Any]] = None    # the SQL expression
    match: Optional[Callable[[Ctx, str, list[Value]], Any]] = None   # for special fields
    order: Optional[Callable[[], Any]] = None
    help: str = ""
    attribute: Optional[str] = None               # the attribute key, when it is one


def _str_values(vals: list[Value], ctx: Ctx) -> list[str]:
    out = []
    for v in vals:
        if v.function == "currentuser":
            out.extend(ctx.user_ids)
        elif v.function in ("membersof",):
            raise JqlError("membersOf() is not supported", v.pos)
        elif v.function:
            raise JqlError(f"{v.text}() is not a value for this field", v.pos)
        else:
            out.append(v.text)
    return out


def _empty(col) -> Any:
    return or_(col.is_(None), cast(col, String) == "")


def _text(col, op: str, vals: list[Value], ctx: Ctx) -> Any:
    if op in ("IS", "IS NOT"):
        return _empty(col) if op == "IS" else not_(_empty(col))
    words = _str_values(vals, ctx)
    if op in ("~", "!~"):
        # Jira's ~ is a word search: every word must appear (a trailing * is a prefix, which ilike already is).
        terms = [t.strip("*") for w in words for t in re.findall(r'"[^"]+"|\S+', w)]
        clause = and_(*[col.ilike(f"%{t.strip(chr(34))}%") for t in terms if t.strip(chr(34))]) if terms else true()
        return clause if op == "~" else or_(col.is_(None), not_(clause))
    lowered = [w.lower() for w in words]
    if op in ("=", "IN"):
        return func.lower(col).in_(lowered)
    if op in ("!=", "NOT IN"):
        return or_(col.is_(None), func.lower(col).notin_(lowered))
    if op in (">", ">=", "<", "<="):
        return _compare(col, op, words[0])
    raise JqlError(f"{op} does not apply to this field")


def _compare(col, op: str, value: Any):
    return {">": col > value, ">=": col >= value, "<": col < value, "<=": col <= value}[op]


def _date(col, op: str, vals: list[Value], ctx: Ctx) -> Any:
    if op in ("IS", "IS NOT"):
        return col.is_(None) if op == "IS" else col.isnot(None)
    if op in ("~", "!~"):
        raise JqlError("~ does not apply to a date: use =, >, >=, <, <=")
    dates = [to_datetime(v, ctx.now) for v in vals]
    if op in ("=", "IN"):
        # A date without a time is that whole day.
        return or_(*[and_(col >= d, col < d + timedelta(days=1)) if (d.hour, d.minute) == (0, 0) and not v.function
                     and not _REL.match(v.text) else col == d for d, v in zip(dates, vals)])
    if op in ("!=", "NOT IN"):
        return or_(col.is_(None), not_(or_(*[and_(col >= d, col < d + timedelta(days=1)) for d in dates])))
    d, v = dates[0], vals[0]
    whole_day = (d.hour, d.minute) == (0, 0) and not v.function and not _REL.match(v.text)
    if whole_day and op == ">":
        return col >= d + timedelta(days=1)
    if whole_day and op == "<=":
        return col < d + timedelta(days=1)
    return _compare(col, op, d)


def _number(col, op: str, vals: list[Value], ctx: Ctx) -> Any:
    """An attribute holding a number, compared as one when it reads as one; text otherwise."""
    if op in ("IS", "IS NOT", "~", "!~", "=", "!=", "IN", "NOT IN"):
        return _text(col, op, vals, ctx)
    v = vals[0]
    if v.function in DATE_FUNCTIONS or (not v.function and _REL.match(v.text)):
        # A date attribute (stored as an ISO date or date-time) against now(), startOfMonth(), -30d…
        at = to_datetime(v, ctx.now)
        return _compare(col, op, at.date().isoformat() if (at.hour, at.minute) == (0, 0) else at.isoformat())
    try:
        n = float(vals[0].text)
    except ValueError:
        return _text(col, op, vals, ctx)
    numeric = case((col.op("~")(r"^\s*-?[0-9]+(\.[0-9]+)?\s*$"), cast(col, Numeric)), else_=None)
    return _compare(numeric, op, n)


def _user(col, op: str, vals: list[Value], ctx: Ctx) -> Any:
    """A person: currentUser(), an id, an e-mail, a username or part of a name."""
    from app.models.user import User
    if op in ("IS", "IS NOT"):
        return _empty(col) if op == "IS" else not_(_empty(col))
    ids: list[str] = []
    for w in _str_values(vals, ctx):
        ids.append(w)
        for u in ctx.db.scalars(select(User).where(or_(func.lower(User.email) == w.lower(),
                                                       func.lower(User.username) == w.lower(),
                                                       func.lower(User.name) == w.lower(), User.id == w))):
            ids.extend(x for x in (u.id, u.email) if x)
        if op in ("~", "!~"):
            for u in ctx.db.scalars(select(User).where(or_(User.name.ilike(f"%{w}%"), User.email.ilike(f"%{w}%")))):
                ids.extend(x for x in (u.id, u.email) if x)
    if op in ("=", "IN", "~"):
        return col.in_(ids) if ids else false()
    if op in ("!=", "NOT IN", "!~"):
        return or_(col.is_(None), col.notin_(ids)) if ids else true()
    raise JqlError(f"{op} does not apply to a person")


def _bool(col, op: str, vals: list[Value], ctx: Ctx) -> Any:
    if op in ("IS", "IS NOT"):
        return col.is_(None) if op == "IS" else col.isnot(None)
    truthy = [v.text.lower() in ("true", "yes", "1", "y", "si", "sì") for v in vals]
    if op in ("=", "IN"):
        return or_(*[col.is_(t) for t in truthy])
    if op in ("!=", "NOT IN"):
        return and_(*[col.isnot(t) for t in truthy])
    raise JqlError(f"{op} does not apply to yes/no")


KIND = {"text": _text, "enum": _text, "date": _date, "user": _user, "number": _number, "bool": _bool}


def _workspace_field(model):
    def match(ctx: Ctx, op: str, vals: list[Value]):
        ctx.project_named = True
        from app.models.workspace import Workspace
        names = [w.lower() for w in _str_values(vals, ctx)]
        ids = set()
        for ws in ctx.db.scalars(select(Workspace).where(Workspace.id.in_(ctx.workspaces))):
            if ws.id.lower() in names or (ws.name or "").lower() in names:
                ids.add(ws.id)
        if op in ("=", "IN"):
            return model.workspace_id.in_(ids) if ids else false()
        if op in ("!=", "NOT IN"):
            return model.workspace_id.notin_(ids) if ids else true()
        raise JqlError(f"{op} does not apply to project")
    return Field("special", match=match, order=lambda: model.workspace_id, help="the workspace (its id or name)")


def _schema_name_field(column):
    """The type, by name (or uid): a ticket's kind, a piece of equipment's type, a document's type."""
    def match(ctx: Ctx, op: str, vals: list[Value]):
        from app.models.schema import Schema
        if op in ("IS", "IS NOT"):
            return column().is_(None) if op == "IS" else column().isnot(None)
        words = [w.lower() for w in _str_values(vals, ctx)]
        if op in ("~", "!~"):
            uids = select(Schema.uid).where(or_(*[Schema.name.ilike(f"%{w}%") for w in words]))
        else:
            uids = select(Schema.uid).where(or_(func.lower(Schema.name).in_(words), Schema.uid.in_(words)))
        if op in ("=", "IN", "~"):
            return column().in_(uids)
        return or_(column().is_(None), column().notin_(uids))
    return Field("special", match=match, order=column, help="the type's name")


def _attr(model, name: str) -> Field:
    col = model.attributes[name].astext
    return Field("number", column=lambda: col, order=lambda: col, help="an attribute", attribute=name)


# --------------------------------------------------------------------------- the three kinds of record

def ticket_fields() -> dict[str, Field]:
    from app.models.issue import Issue
    from app.models.workflow import TicketWatcher
    source_key = Issue.attributes["argus_source_key"].astext

    def key_match(ctx: Ctx, op: str, vals: list[Value]):
        words = _str_values(vals, ctx)
        lowered = [w.lower() for w in words]
        hit = or_(Issue.uid.in_(words), func.lower(source_key).in_(lowered))
        if op in ("=", "IN"):
            return hit
        if op in ("!=", "NOT IN"):
            return not_(hit)
        if op in ("~", "!~"):
            like = or_(*[or_(Issue.uid.ilike(f"%{w}%"), source_key.ilike(f"%{w}%")) for w in words])
            return like if op == "~" else not_(like)
        raise JqlError(f"{op} does not apply to key")

    def text_match(ctx: Ctx, op: str, vals: list[Value]):
        if op not in ("~", "!~"):
            raise JqlError("text is searched with ~ (contains)")
        return _text(func.concat_ws(" ", Issue.title, Issue.description, source_key, Issue.uid), op, vals, ctx)

    def category_match(ctx: Ctx, op: str, vals: list[Value]):
        words = [w.lower().replace(" ", "") for w in _str_values(vals, ctx)]
        done = Issue.closed_at.isnot(None)
        parts = []
        for w in words:
            parts.append(done if w in ("done", "closed", "resolved") else not_(done))
        hit = or_(*parts) if parts else false()
        if op in ("=", "IN"):
            return hit
        if op in ("!=", "NOT IN"):
            return not_(hit)
        raise JqlError(f"{op} does not apply to statusCategory")

    def watcher_match(ctx: Ctx, op: str, vals: list[Value]):
        people = _str_values(vals, ctx)
        watched = select(TicketWatcher.issue_uid).where(TicketWatcher.user.in_(people))
        if op in ("=", "IN"):
            return Issue.uid.in_(watched)
        if op in ("!=", "NOT IN"):
            return Issue.uid.notin_(watched)
        raise JqlError(f"{op} does not apply to watcher")

    def asset_match(ctx: Ctx, op: str, vals: list[Value]):
        from app.models.asset import Asset
        from app.services.identifiers import exact_clause
        if op in ("IS", "IS NOT"):
            return Issue.asset_uid.is_(None) if op == "IS" else Issue.asset_uid.isnot(None)
        words = _str_values(vals, ctx)
        if op in ("~", "!~"):
            uids = select(Asset.uid).where(or_(*[or_(Asset.key.ilike(f"%{w}%"), Asset.name.ilike(f"%{w}%"))
                                                 for w in words]))
        else:
            uids = select(Asset.uid).where(or_(*[exact_clause(ctx.db, ctx.grants, w) for w in words]))
        if op in ("=", "IN", "~"):
            return Issue.asset_uid.in_(uids)
        return or_(Issue.asset_uid.is_(None), Issue.asset_uid.notin_(uids))

    def labels_match(ctx: Ctx, op: str, vals: list[Value]):
        if op in ("IS", "IS NOT"):
            empty = or_(Issue.labels.is_(None), func.jsonb_array_length(Issue.labels) == 0)
            return empty if op == "IS" else not_(empty)
        words = _str_values(vals, ctx)
        hit = or_(*[Issue.labels.contains([w]) for w in words])
        if op in ("=", "IN"):
            return hit
        if op in ("!=", "NOT IN"):
            return not_(hit)
        if op in ("~", "!~"):
            like = cast(Issue.labels, String).ilike(f"%{words[0]}%")
            return like if op == "~" else not_(like)
        raise JqlError(f"{op} does not apply to labels")

    key = Field("special", match=key_match, order=lambda: Issue.uid, help="the ticket's key (or its Jira key)")
    summary = Field("text", column=lambda: Issue.title, order=lambda: Issue.title, help="the title")
    status = Field("enum", column=lambda: Issue.state, order=lambda: Issue.state, help="the state")
    kind = _schema_name_field(lambda: Issue.schema_uid)
    return {
        "key": key, "issuekey": key, "id": key, "issue": key,
        "summary": summary, "title": summary,
        "description": Field("text", column=lambda: Issue.description, help="the description"),
        "text": Field("special", match=text_match, help="everything written: title, description, key"),
        "status": status, "state": status,
        "statuscategory": Field("special", match=category_match, help="Done or To Do / In Progress"),
        "priority": Field("enum", column=lambda: Issue.priority, order=lambda: _priority_rank(Issue.priority),
                          help="the priority"),
        "assignee": Field("user", column=lambda: Issue.assignee, order=lambda: Issue.assignee, help="who it is assigned to"),
        "reporter": Field("user", column=lambda: Issue.created_by, order=lambda: Issue.created_by, help="who reported it"),
        "creator": Field("user", column=lambda: Issue.created_by, help="who reported it"),
        "watcher": Field("special", match=watcher_match, help="who watches it"),
        "created": Field("date", column=lambda: Issue.created_at, order=lambda: Issue.created_at, help="when reported"),
        "createddate": Field("date", column=lambda: Issue.created_at, help="when reported"),
        "updated": Field("date", column=lambda: Issue.updated_at, order=lambda: Issue.updated_at, help="when last changed"),
        "updateddate": Field("date", column=lambda: Issue.updated_at, help="when last changed"),
        "resolved": Field("date", column=lambda: Issue.closed_at, order=lambda: Issue.closed_at, help="when closed"),
        "resolutiondate": Field("date", column=lambda: Issue.closed_at, help="when closed"),
        "due": Field("date", column=lambda: Issue.due_date, order=lambda: Issue.due_date, help="the due date"),
        "duedate": Field("date", column=lambda: Issue.due_date, order=lambda: Issue.due_date, help="the due date"),
        "type": kind, "issuetype": kind,
        "project": _workspace_field(Issue), "workspace": _workspace_field(Issue),
        "asset": Field("special", match=asset_match, help="the equipment (key, label, serial)"),
        "equipment": Field("special", match=asset_match, help="the equipment (key, label, serial)"),
        "labels": Field("special", match=labels_match, help="the ticket's labels"),
        "label": Field("special", match=labels_match, help="the ticket's labels"),
    }


def _priority_rank(col):
    return case({"highest": 5, "critical": 5, "blocker": 5, "high": 4, "major": 4, "medium": 3, "normal": 3,
                 "low": 2, "minor": 2, "lowest": 1, "trivial": 1}, value=func.lower(col), else_=0)


def _visible_attributes_like(ctx: Ctx, word: str):
    """Any attribute value containing the word — only where the viewer may see every attribute of that type."""
    from app.models.asset import Asset
    from app.models.schema import Schema
    from app.services.visibility import restricted_fields
    like = cast(Asset.attributes, String).ilike(f"%{word}%")
    if ctx.grants is None or getattr(ctx.grants, "everything", False):
        return like
    blocked = [uid for uid in ctx.db.scalars(select(Schema.uid))
               if any(not ctx.grants.allows(cls) for cls in restricted_fields(ctx.db, uid).values())]
    return and_(like, Asset.schema_uid.notin_(blocked)) if blocked else like


def asset_fields() -> dict[str, Field]:
    from app.models.asset import Asset
    from app.models.asset_subresources import AssetLabel
    from app.services.identifiers import IDENTIFIER_ATTRS

    def label_match(ctx: Ctx, op: str, vals: list[Value]):
        if op in ("IS", "IS NOT"):
            has = Asset.uid.in_(select(AssetLabel.asset_uid))
            return not_(has) if op == "IS" else has
        words = _str_values(vals, ctx)
        if op in ("~", "!~"):
            q = select(AssetLabel.asset_uid).where(or_(*[AssetLabel.value.ilike(f"%{w}%") for w in words]))
        else:
            q = select(AssetLabel.asset_uid).where(func.lower(AssetLabel.value).in_([w.lower() for w in words]))
        return Asset.uid.in_(q) if op in ("=", "IN", "~") else Asset.uid.notin_(q)

    def label_type_match(ctx: Ctx, op: str, vals: list[Value]):
        words = [w.lower() for w in _str_values(vals, ctx)]
        q = select(AssetLabel.asset_uid).where(func.lower(AssetLabel.type).in_(words))
        return Asset.uid.in_(q) if op in ("=", "IN") else Asset.uid.notin_(q)

    def text_match(ctx: Ctx, op: str, vals: list[Value]):
        if op not in ("~", "!~"):
            raise JqlError("text is searched with ~ (contains)")
        from app.services.identifiers import text_clause
        words = [t for w in _str_values(vals, ctx) for t in w.split()]
        hit = and_(*[or_(text_clause(ctx.db, ctx.grants, w), _visible_attributes_like(ctx, w)) for w in words])
        return hit if op == "~" else not_(hit)

    def key_match(ctx: Ctx, op: str, vals: list[Value]):
        words = _str_values(vals, ctx)
        lowered = [w.lower() for w in words]
        former = select(AssetLabel.asset_uid).where(AssetLabel.type.in_(("former_key", "alias")),
                                                    func.lower(AssetLabel.value).in_(lowered))
        hit = or_(func.lower(Asset.key).in_(lowered), Asset.uid.in_(words), Asset.uid.in_(former))
        if op in ("=", "IN"):
            return hit
        if op in ("!=", "NOT IN"):
            return not_(hit)
        if op in ("~", "!~"):
            like = or_(*[Asset.key.ilike(f"%{w}%") for w in words])
            return like if op == "~" else not_(like)
        raise JqlError(f"{op} does not apply to key")

    key = Field("special", match=key_match, order=lambda: Asset.key, help="the key, or a former key")
    name = Field("text", column=lambda: Asset.name, order=lambda: Asset.name, help="the name")
    kind = _schema_name_field(lambda: Asset.schema_uid)
    out = {
        "key": key, "id": key,
        "name": name, "summary": name, "title": name,
        "text": Field("special", match=text_match, help="key, name, labels, serial and every attribute"),
        "type": kind, "objecttype": kind,
        "category": Field("text", column=lambda: Asset.type, order=lambda: Asset.type, help="the type's family"),
        "status": Field("enum", column=lambda: Asset.record_status, order=lambda: Asset.record_status,
                        help="Active, Provisional or Retired"),
        "project": _workspace_field(Asset), "workspace": _workspace_field(Asset),
        "global": Field("bool", column=lambda: Asset.is_global, help="shared with every workspace"),
        "shared": Field("bool", column=lambda: Asset.is_global, help="shared with every workspace"),
        "created": Field("date", column=lambda: Asset.created_at, order=lambda: Asset.created_at, help="when registered"),
        "updated": Field("date", column=lambda: Asset.updated_at, order=lambda: Asset.updated_at, help="when last changed"),
        "label": Field("special", match=label_match, help="any label: QR code, barcode, former key, alias"),
        "labels": Field("special", match=label_match, help="any label: QR code, barcode, former key, alias"),
        "labeltype": Field("special", match=label_type_match, help="has a label of this type (qrcode, former_key…)"),
    }
    for a in IDENTIFIER_ATTRS:
        out[a] = _attr(Asset, a)
    return out


def document_fields() -> dict[str, Field]:
    from app.models.document import Document, DocumentRevision
    current = select(DocumentRevision.state).where(DocumentRevision.uid == Document.current_revision_uid) \
        .correlate(Document).scalar_subquery()
    latest = select(DocumentRevision.state).where(DocumentRevision.document_uid == Document.uid) \
        .order_by(DocumentRevision.revision_number.desc()).limit(1).correlate(Document).scalar_subquery()
    state = func.coalesce(case((Document.retired_at.isnot(None), "retired"), else_=None), latest)

    def text_match(ctx: Ctx, op: str, vals: list[Value]):
        if op not in ("~", "!~"):
            raise JqlError("text is searched with ~ (contains)")
        body = select(DocumentRevision.body_markdown).where(DocumentRevision.uid == Document.current_revision_uid) \
            .correlate(Document).scalar_subquery()
        return _text(func.concat_ws(" ", Document.code, Document.title, body), op, vals, ctx)

    key = Field("text", column=lambda: Document.code, order=lambda: Document.code, help="the document's code")
    title = Field("text", column=lambda: Document.title, order=lambda: Document.title, help="the title")
    status = Field("enum", column=lambda: state, order=lambda: state,
                   help="draft, in_review, approved, published, retired (of its latest revision)")
    kind = _schema_name_field(lambda: Document.document_type_uid)
    return {
        "key": key, "code": key, "id": key,
        "title": title, "summary": title, "name": title,
        "text": Field("special", match=text_match, help="code, title and the published text"),
        "status": status, "state": status,
        "published": Field("enum", column=lambda: current, help="the state of the revision people work from"),
        "type": kind, "documenttype": kind,
        "project": _workspace_field(Document), "workspace": _workspace_field(Document),
        "authority": Field("enum", column=lambda: Document.authority_level, order=lambda: Document.authority_level,
                           help="normativo, operativo, informativo…"),
        "confidentiality": Field("enum", column=lambda: Document.confidentiality, help="pubblico, interno, riservato"),
        "owner": Field("user", column=lambda: Document.owner_user_id, help="the document's owner"),
        "global": Field("bool", column=lambda: Document.is_global, help="shared with every workspace"),
        "created": Field("date", column=lambda: Document.created_at, order=lambda: Document.created_at, help="when created"),
        "updated": Field("date", column=lambda: Document.updated_at, order=lambda: Document.updated_at, help="when last changed"),
        "retired": Field("date", column=lambda: Document.retired_at, order=lambda: Document.retired_at, help="when retired"),
    }


ENTITIES = {"tickets": ticket_fields, "assets": asset_fields, "documents": document_fields}


def _model(entity: str):
    from app.models.asset import Asset
    from app.models.document import Document
    from app.models.issue import Issue
    return {"tickets": Issue, "assets": Asset, "documents": Document}[entity]


def _field(entity: str, fields: dict[str, Field], name: str, pos: int) -> Field:
    raw = name.strip()
    m = re.fullmatch(r"cf\[(.+)\]", raw, re.I)
    if m:
        raw = m.group(1).strip("\"'")
    else:
        f = fields.get(re.sub(r"[\s_]", "", raw.lower())) or fields.get(raw.lower())
        if f is not None:
            return f
    model = _model(entity)
    if not hasattr(model, "attributes"):
        raise JqlError(f"Unknown field {name!r}", pos)
    # Any other name is an attribute of the record: as written, else as an attribute key would be spelled.
    return _attr(model, raw if " " not in raw else re.sub(r"\s+", "_", raw.strip().lower()))


def compile_where(entity: str, node, ctx: Ctx, fields: dict[str, Field]):
    if node is None:
        return true()
    if isinstance(node, Bool):
        parts = [compile_where(entity, n, ctx, fields) for n in node.items]
        if node.op == "AND":
            return and_(*parts)
        if node.op == "OR":
            return or_(*parts)
        return not_(parts[0])
    f = _field(entity, fields, node.field, node.pos)
    try:
        if f.kind == "special":
            if node.op in ("IS", "IS NOT") and f.match is None:
                raise JqlError(f"{node.field} cannot be EMPTY")
            return f.match(ctx, node.op, node.values)
        if node.op in (">", ">=", "<", "<=") and f.kind in ("enum", "user", "bool"):
            raise JqlError(f"{node.op} does not apply to {node.field}")
        clause = KIND[f.kind](f.column(), node.op, node.values, ctx)
        if f.attribute and ctx.grants is not None:
            from app.services.identifiers import _blocked_schemas
            blocked = _blocked_schemas(ctx.db, ctx.grants, f.attribute)
            if blocked:
                clause = and_(clause, _model(entity).schema_uid.notin_(blocked))
        return clause
    except JqlError as e:
        raise JqlError(e.message, e.position if e.position is not None else node.pos) from None


def compile_order(entity: str, order: list[tuple[str, bool]], fields: dict[str, Field]) -> list:
    out = []
    for name, desc in order:
        f = _field(entity, fields, name, 0)
        col = (f.order or f.column)() if (f.order or f.column) else None
        if col is None:
            raise JqlError(f"Cannot order by {name}")
        out.append(col.desc().nulls_last() if desc else col.asc().nulls_last())
    return out


def field_reference() -> dict[str, list[dict]]:
    """For each kind of record, the fields it is searched by, what they mean and how they are compared."""
    out = {}
    for entity, make in ENTITIES.items():
        seen, rows = set(), []
        for name, f in make().items():
            if id(f) in seen:
                continue
            seen.add(id(f))
            rows.append({"field": name, "kind": f.kind, "help": f.help, "orderable": bool(f.order or f.column)})
        out[entity] = rows
    return out


# --------------------------------------------------------------------------- running a query

def run(db: Session, entity: str, text: str, *, user_ids: list[str], workspaces: list[str],
        current_workspace: Optional[str], visible: Callable[[Any], bool], grants=None,
        limit: int = 50, offset: int = 0) -> dict:
    """The records of this kind the query selects, in the workspaces given (the current one unless the query
    names a project), that the person may see; `visible` decides each record (I-ACL-1)."""
    if entity not in ENTITIES:
        raise JqlError(f"Search tickets, assets or documents, not {entity!r}")
    q = parse(text)
    fields = ENTITIES[entity]()
    ctx = Ctx(db=db, user_ids=user_ids, now=datetime.now(timezone.utc), workspaces=workspaces,
              current_workspace=current_workspace, grants=grants)
    where = compile_where(entity, q.where, ctx, fields)
    model = _model(entity)
    scope = model.workspace_id.in_(workspaces)
    if not ctx.project_named and current_workspace:
        scope = model.workspace_id == current_workspace
    if entity in ("assets", "documents"):
        # What is shared with every workspace is found from any of them.
        shared = model.is_global.is_(True)
        if entity == "documents":
            shared = and_(shared, model.confidentiality != "riservato")
        scope = or_(scope, shared) if not ctx.project_named else scope
    stmt = select(model).where(scope, where)
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))
    order = compile_order(entity, q.order, fields) if q.order else [model.updated_at.desc().nulls_last()]
    stmt = stmt.order_by(*order, model.uid)
    rows, skipped, total, fetched = [], 0, 0, 0
    # Visibility is decided record by record, so the page is filled from as many rows as it takes.
    for record in db.scalars(stmt.limit(5000)):
        fetched += 1
        if not visible(record):
            continue
        total += 1
        if skipped < offset:
            skipped += 1
            continue
        if len(rows) < limit:
            rows.append(record)
    return {"entity": entity, "total": total, "rows": rows, "capped": fetched >= 5000}
