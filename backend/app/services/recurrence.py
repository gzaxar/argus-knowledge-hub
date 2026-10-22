"""Recurring activities: a practical subset of iCalendar RRULE (RFC 5545), expanded on demand.

    FREQ=DAILY|WEEKLY|MONTHLY   INTERVAL=n   BYDAY=MO,WE (weekly, and daily on chosen weekdays)
    BYMONTHDAY=15 (monthly)     COUNT=n | UNTIL=YYYYMMDD (local date, inclusive)

A series keeps its first occurrence as a **local** date and time plus an IANA time zone. Occurrences are
computed in local time and only then placed on the UTC timeline, so "every Monday at 09:00 Europe/Rome" stays
at 09:00 across daylight-saving changes (07:00 UTC in summer, 08:00 UTC in winter). A local time that does not
exist on a spring-forward day moves forward by the gap; one that happens twice on a fall-back day takes the
first.

Nothing is stored per occurrence until something happens to it (completed, skipped, rescheduled, edited):
`between` expands only the requested window, with a hard limit, so an unbounded series never makes unbounded
rows or work.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
FREQS = ("DAILY", "WEEKLY", "MONTHLY")
MAX_EXPANSION = 2000            # occurrences looked at per series per request, at most


class RuleError(ValueError):
    pass


@dataclass
class Rule:
    freq: str
    interval: int = 1
    byday: list[int] = field(default_factory=list)      # 0 = Monday
    bymonthday: Optional[int] = None
    count: Optional[int] = None
    until: Optional[date] = None                         # local date, inclusive

    def text(self) -> str:
        parts = [f"FREQ={self.freq}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.byday:
            parts.append("BYDAY=" + ",".join(WEEKDAYS[d] for d in sorted(set(self.byday))))
        if self.bymonthday:
            parts.append(f"BYMONTHDAY={self.bymonthday}")
        if self.count:
            parts.append(f"COUNT={self.count}")
        if self.until:
            parts.append(f"UNTIL={self.until:%Y%m%d}")
        return ";".join(parts)


def parse(rule: str) -> Rule:
    """The rule, checked: what this subset supports and nothing else."""
    if not rule or len(rule) > 300:
        raise RuleError("a recurrence rule is required")
    fields = {}
    for part in rule.strip().removeprefix("RRULE:").split(";"):
        if not part:
            continue
        k, _, v = part.partition("=")
        fields[k.strip().upper()] = v.strip().upper()
    unknown = set(fields) - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "COUNT", "UNTIL"}
    if unknown:
        raise RuleError(f"not supported in a recurrence: {', '.join(sorted(unknown))}")
    freq = fields.get("FREQ")
    if freq not in FREQS:
        raise RuleError("FREQ must be DAILY, WEEKLY or MONTHLY")
    r = Rule(freq=freq)
    try:
        r.interval = int(fields.get("INTERVAL", "1"))
        if not 1 <= r.interval <= 366:
            raise ValueError
    except ValueError:
        raise RuleError("INTERVAL must be a whole number from 1 to 366")
    if "BYDAY" in fields:
        days = [d for d in fields["BYDAY"].split(",") if d]
        if not days or any(d not in WEEKDAYS for d in days):
            raise RuleError("BYDAY takes MO, TU, WE, TH, FR, SA, SU")
        if freq == "MONTHLY":
            raise RuleError("BYDAY is for daily and weekly rules")
        r.byday = sorted({WEEKDAYS.index(d) for d in days})
    if "BYMONTHDAY" in fields:
        if freq != "MONTHLY":
            raise RuleError("BYMONTHDAY is for monthly rules")
        try:
            r.bymonthday = int(fields["BYMONTHDAY"])
            if not 1 <= r.bymonthday <= 31:
                raise ValueError
        except ValueError:
            raise RuleError("BYMONTHDAY must be a day of the month, 1 to 31")
    if "COUNT" in fields and "UNTIL" in fields:
        raise RuleError("a rule ends by COUNT or by UNTIL, not both")
    if "COUNT" in fields:
        try:
            r.count = int(fields["COUNT"])
            if not 1 <= r.count <= 10000:
                raise ValueError
        except ValueError:
            raise RuleError("COUNT must be a whole number from 1 to 10000")
    if "UNTIL" in fields:
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(T\d{6}Z?)?", fields["UNTIL"])
        if not m:
            raise RuleError("UNTIL must be a date, YYYYMMDD")
        r.until = date(int(m[1]), int(m[2]), int(m[3]))
    return r


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise RuleError(f"unknown time zone {name!r}")


def to_utc(local: datetime, tz: ZoneInfo) -> datetime:
    """A local wall-clock time placed on the UTC timeline: a time skipped by spring-forward moves forward by
    the gap; a repeated time (fall-back) takes its first occurrence."""
    # fold=0: the earlier of a repeated time; for a skipped one, the offset before the change, which lands the
    # instant after the gap — the wall time read back is the local time moved forward by the gap.
    return local.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)


def local_starts(rule: Rule, first: datetime) -> Iterator[datetime]:
    """The series' local start times, in order, from `first` (naive, local): honouring COUNT and UNTIL."""
    produced = 0
    looked = 0

    def done(d: datetime) -> bool:
        return (rule.count is not None and produced >= rule.count) or (rule.until is not None and d.date() > rule.until)

    if rule.freq == "DAILY":
        day = first
        while True:
            looked += 1
            if looked > MAX_EXPANSION * 50 or done(day):
                return
            if not rule.byday or day.weekday() in rule.byday:
                produced += 1
                yield day
            day += timedelta(days=rule.interval)
    elif rule.freq == "WEEKLY":
        days = rule.byday or [first.weekday()]
        week_start = first - timedelta(days=first.weekday())
        while True:
            for wd in days:
                d = week_start + timedelta(days=wd)
                if d < first:
                    continue
                looked += 1
                if looked > MAX_EXPANSION * 50 or done(d):
                    return
                produced += 1
                yield d
            week_start += timedelta(weeks=rule.interval)
    else:                                                    # MONTHLY: that day of the month, skipped where absent
        mday = rule.bymonthday or first.day
        y, m = first.year, first.month
        while True:
            looked += 1
            if looked > MAX_EXPANSION * 50:
                return
            if mday <= calendar.monthrange(y, m)[1]:
                d = datetime.combine(date(y, m, mday), first.time())
                if d >= first:
                    if done(d):
                        return
                    produced += 1
                    yield d
            elif rule.until is not None and date(y, m, 1) > rule.until:
                return
            m += rule.interval
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1


def between(rule: Rule, first_local: datetime, tz_name: str, start: datetime, end: datetime,
            limit: int = MAX_EXPANSION) -> list[tuple[datetime, datetime]]:
    """(local start, UTC start) of the occurrences starting in [start, end) (UTC, aware), at most `limit`."""
    tz = zone(tz_name)
    out = []
    for local in local_starts(rule, first_local):
        at = to_utc(local, tz)
        if at >= end:
            break
        if at >= start:
            out.append((local, at))
            if len(out) >= limit:
                break
    return out


def occurrence_key(local: datetime) -> str:
    """An occurrence's name within its series: its original local start, which a reschedule does not change."""
    return local.strftime("%Y-%m-%dT%H:%M")


def is_occurrence(rule: Rule, first_local: datetime, local: datetime) -> bool:
    for d in local_starts(rule, first_local):
        if d == local:
            return True
        if d > local:
            return False
    return False


def remaining_after(rule: Rule, first_local: datetime, local: datetime) -> Optional[int]:
    """For a COUNT rule split at `local`: how many occurrences the new series keeps (that one included)."""
    if rule.count is None:
        return None
    before = 0
    for d in local_starts(rule, first_local):
        if d >= local:
            break
        before += 1
    return max(rule.count - before, 1)


def describe(rule: Rule, first_local: datetime, language: str = "en") -> str:
    """The rule in words, for a list: 'every Monday at 09:00', 'every 2 days', 'monthly on day 15'."""
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    at = "" if first_local.time() == time(0, 0) else f" at {first_local:%H:%M}"
    if rule.freq == "DAILY":
        base = "every day" if rule.interval == 1 else f"every {rule.interval} days"
        if rule.byday:
            base = "every " + ", ".join(names[d] for d in rule.byday)
    elif rule.freq == "WEEKLY":
        days = rule.byday or [first_local.weekday()]
        base = ("every " if rule.interval == 1 else f"every {rule.interval} weeks on ") + ", ".join(names[d] for d in days)
    else:
        base = ("monthly" if rule.interval == 1 else f"every {rule.interval} months") + \
            f" on day {rule.bymonthday or first_local.day}"
    end = f", {rule.count} times" if rule.count else (f", until {rule.until:%Y-%m-%d}" if rule.until else "")
    return base + at + end
