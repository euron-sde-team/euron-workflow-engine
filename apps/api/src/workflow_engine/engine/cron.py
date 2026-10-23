"""Five-field cron schedules, evaluated in an IANA time zone.

    minute hour day-of-month month day-of-week      e.g. "30 8 * * MON-FRI"

Supported: `*`, lists (`1,15`), ranges (`1-5`), steps (`*/15`, `10-50/10`, `5/20`), month
and weekday names, `7` as Sunday, and the macros `@yearly`, `@annually`, `@monthly`,
`@weekly`, `@daily`, `@midnight`, `@hourly`. Day matching follows Vixie cron: when both
day fields are restricted, a day matches if either does.

Schedules are wall-clock schedules. Around daylight-saving changes:

- a time that does not exist (the hour skipped in spring) fires once, when the gap ends;
- a time that happens twice (the hour repeated in autumn) fires once, the first time.

An every-few-minutes schedule therefore pauses during a repeated hour; the interval trigger
measures absolute time instead and never does.

The search jumps by month, day, hour and minute instead of stepping minute by minute, so a
yearly schedule costs no more than a minutely one.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_MONTHS = {
    name: index
    for index, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}
_WEEKDAYS = {
    name: index for index, name in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])
}
# A schedule that has not fired within this horizon never will (for example February 30).
# Eight years covers the longest legitimate gap: February 29 across a skipped leap year.
_HORIZON_YEARS = 9
_MINUTE = timedelta(minutes=1)


class CronError(ValueError):
    """The expression or time zone is invalid; the message says which part and why."""


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    low: int
    high: int
    names: dict[str, int] | None = None


_FIELDS = (
    _Field("minute", 0, 59),
    _Field("hour", 0, 23),
    _Field("day of month", 1, 31),
    _Field("month", 1, 12, _MONTHS),
    _Field("day of week", 0, 7, _WEEKDAYS),
)


def _value(token: str, field: _Field) -> int:
    upper = token.upper()
    if field.names and upper in field.names:
        return field.names[upper]
    if not token.isdigit():
        raise CronError(f"{field.name}: '{token}' is not a number")
    number = int(token)
    if not field.low <= number <= field.high:
        raise CronError(f"{field.name}: {number} is outside {field.low}-{field.high}")
    return number


def _parse_field(text: str, field: _Field) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{field.name}: empty list item")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) == 0:
                raise CronError(f"{field.name}: step '{step_text}' must be a positive number")
            step = int(step_text)
        if base == "*":
            start, end = field.low, field.high
        elif "-" in base:
            low_text, _, high_text = base.partition("-")
            start, end = _value(low_text, field), _value(high_text, field)
            if start > end:
                raise CronError(f"{field.name}: range {base} runs backwards")
        else:
            start = _value(base, field)
            # "5/20" means every 20 starting at 5, through the end of the range.
            end = field.high if step_text else start
        values.update(range(start, end + 1, step))
    if field.name == "day of week" and 7 in values:
        values.discard(7)
        values.add(0)
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class CronSchedule:
    expression: str
    timezone: str
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    days: frozenset[int]
    months: tuple[int, ...]
    weekdays: frozenset[int]
    days_restricted: bool
    weekdays_restricted: bool

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def _day_matches(self, moment: datetime) -> bool:
        day_ok = moment.day in self.days
        weekday_ok = (moment.weekday() + 1) % 7 in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return day_ok or weekday_ok
        if self.days_restricted:
            return day_ok
        if self.weekdays_restricted:
            return weekday_ok
        return True

    def _next_wall_time(self, start: datetime) -> datetime | None:
        """The first wall-clock minute at or after `start` (naive) that matches every field."""
        moment = start.replace(second=0, microsecond=0)
        limit = start.year + _HORIZON_YEARS
        while moment.year <= limit:
            if moment.month not in self.months:
                index = bisect.bisect_right(self.months, moment.month)
                if index < len(self.months):
                    moment = datetime(moment.year, self.months[index], 1)
                else:
                    moment = datetime(moment.year + 1, self.months[0], 1)
                continue
            if not self._day_matches(moment):
                moment = datetime(moment.year, moment.month, moment.day) + timedelta(days=1)
                continue
            if moment.hour not in self.hours:
                index = bisect.bisect_right(self.hours, moment.hour)
                if index < len(self.hours):
                    moment = moment.replace(hour=self.hours[index], minute=0)
                else:
                    moment = datetime(moment.year, moment.month, moment.day) + timedelta(days=1)
                continue
            if moment.minute not in self.minutes:
                index = bisect.bisect_right(self.minutes, moment.minute)
                if index < len(self.minutes):
                    moment = moment.replace(minute=self.minutes[index])
                else:
                    moment = moment.replace(minute=0) + timedelta(hours=1)
                continue
            return moment
        return None

    def _instant(self, wall: datetime) -> datetime:
        """The UTC instant a wall-clock time fires at: its first occurrence, or the gap's end."""
        zone = self.zone
        candidate = wall
        for _ in range(24 * 60):
            aware = candidate.replace(tzinfo=zone, fold=0)
            instant = aware.astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == candidate:
                return instant
            candidate += _MINUTE  # inside a spring-forward gap: walk to where it ends
        raise CronError(f"time zone {self.timezone} has no valid time near {wall.isoformat()}")

    def next_after(self, after: datetime) -> datetime | None:
        """The first fire time strictly after `after` (aware), in UTC, or None if never."""
        if after.tzinfo is None:
            raise ValueError("next_after needs an aware datetime")
        wall = after.astimezone(self.zone).replace(tzinfo=None, second=0, microsecond=0)
        candidate: datetime | None = wall + _MINUTE
        while candidate is not None:
            candidate = self._next_wall_time(candidate)
            if candidate is None:
                return None
            instant = self._instant(candidate)
            if instant > after:
                return instant
            # The first occurrence of a repeated time, or a gap already fired: move on.
            candidate += _MINUTE
        return None

    def upcoming(self, after: datetime, count: int) -> list[datetime]:
        times: list[datetime] = []
        moment = after
        while len(times) < count:
            following = self.next_after(moment)
            if following is None:
                break
            times.append(following)
            moment = following
        return times


def parse(expression: str, timezone: str = "UTC") -> CronSchedule:
    text = " ".join(expression.split())
    if not text:
        raise CronError("the expression is empty")
    source = MACROS.get(text.lower(), text)
    if source.startswith("@"):
        raise CronError(f"unknown macro {text}; use one of {', '.join(sorted(MACROS))}")
    parts = source.split(" ")
    if len(parts) != len(_FIELDS):
        raise CronError(
            f"expected 5 fields (minute hour day-of-month month day-of-week), got {len(parts)}"
        )
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"unknown time zone '{timezone}'") from exc
    minute, hour, day, month, weekday = (
        _parse_field(part, field) for part, field in zip(parts, _FIELDS, strict=True)
    )
    schedule = CronSchedule(
        expression=text,
        timezone=timezone,
        minutes=tuple(sorted(minute)),
        hours=tuple(sorted(hour)),
        days=day,
        months=tuple(sorted(month)),
        weekdays=weekday,
        days_restricted=not parts[2].startswith("*"),
        weekdays_restricted=not parts[4].startswith("*"),
    )
    if schedule.next_after(datetime(2026, 1, 1, tzinfo=UTC)) is None:
        raise CronError("this schedule never fires (check the day and month fields)")
    return schedule


def describe(schedule: CronSchedule) -> str:
    """A short English summary for the editor; precise for common shapes, generic otherwise."""
    minutes, hours = schedule.minutes, schedule.hours
    every_day = not schedule.days_restricted and not schedule.weekdays_restricted
    all_months = len(schedule.months) == 12
    if len(minutes) == 60 and len(hours) == 24 and every_day and all_months:
        return "Every minute"
    if len(hours) == 24 and every_day and all_months:
        if len(minutes) == 1:
            return f"Every hour at minute {minutes[0]}"
        step = _even_step(minutes, 60)
        if step:
            return f"Every {step} minutes"
    hour_step = _even_step(hours, 24)
    if len(minutes) == 1 and hour_step and every_day and all_months:
        return f"Every {hour_step} hours at minute {minutes[0]}"
    if len(minutes) == 1 and len(hours) == 1 and all_months:
        at = f"{hours[0]:02d}:{minutes[0]:02d}"
        if every_day:
            return f"Every day at {at}"
        if schedule.weekdays_restricted and not schedule.days_restricted:
            names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            days = sorted(schedule.weekdays)
            label = "weekdays" if days == [1, 2, 3, 4, 5] else ", ".join(names[d] for d in days)
            return f"Every {label} at {at}"
        if schedule.days_restricted and not schedule.weekdays_restricted:
            days_list = ", ".join(str(d) for d in sorted(schedule.days))
            return f"Day {days_list} of every month at {at}"
    return f"Cron {schedule.expression}"


def _even_step(values: tuple[int, ...], span: int) -> int | None:
    if len(values) < 2 or values[0] != 0:
        return None
    step = values[1] - values[0]
    if span % step == 0 and values == tuple(range(0, span, step)):
        return step
    return None
