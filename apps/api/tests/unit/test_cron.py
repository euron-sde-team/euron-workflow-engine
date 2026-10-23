from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from workflow_engine.engine.cron import CronError, describe, parse

NEW_YORK = ZoneInfo("America/New_York")


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def test_steps_lists_and_ranges() -> None:
    schedule = parse("*/15 * * * *")
    assert schedule.next_after(utc(2026, 10, 23, 10, 7)) == utc(2026, 10, 23, 10, 15)
    assert schedule.next_after(utc(2026, 10, 23, 10, 45)) == utc(2026, 10, 23, 11, 0)
    office = parse("0 9-17/2 * JAN,JUL *")
    assert office.hours == (9, 11, 13, 15, 17)
    assert office.months == (1, 7)
    assert parse("5/20 * * * *").minutes == (5, 25, 45)


def test_weekdays_skip_the_weekend() -> None:
    schedule = parse("30 8 * * MON-FRI")
    friday_after = utc(2026, 10, 23, 9, 0)  # a Friday
    assert schedule.next_after(friday_after) == utc(2026, 10, 26, 8, 30)


def test_restricted_day_fields_match_either_day() -> None:
    schedule = parse("0 0 1 * MON")
    fires = schedule.upcoming(utc(2026, 10, 23), 4)
    assert fires == [utc(2026, 10, 26), utc(2026, 11, 1), utc(2026, 11, 2), utc(2026, 11, 9)]


def test_seven_is_sunday_and_macros_expand() -> None:
    assert parse("0 0 * * 7").weekdays == frozenset({0})
    assert parse("@daily").expression == "@daily"
    assert parse("@hourly").next_after(utc(2026, 1, 1, 0, 30)) == utc(2026, 1, 1, 1, 0)
    assert parse("@yearly").next_after(utc(2026, 6, 1)) == utc(2027, 1, 1)


def test_leap_day_schedules_wait_for_the_next_leap_year() -> None:
    assert parse("0 0 29 2 *").next_after(utc(2026, 3, 1)) == utc(2028, 2, 29)


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("* * * *", "expected 5 fields"),
        ("60 * * * *", "outside 0-59"),
        ("*/0 * * * *", "positive number"),
        ("5-1 * * * *", "runs backwards"),
        ("@sometimes", "unknown macro"),
        ("0 0 30 2 *", "never fires"),
        ("a * * * *", "not a number"),
        ("1,,2 * * * *", "empty list item"),
    ],
)
def test_invalid_expressions_say_what_is_wrong(expression: str, message: str) -> None:
    with pytest.raises(CronError, match=message):
        parse(expression)


def test_unknown_time_zones_are_rejected() -> None:
    with pytest.raises(CronError, match="unknown time zone"):
        parse("0 8 * * *", "Mars/Olympus_Mons")


def test_schedules_run_in_their_time_zone() -> None:
    schedule = parse("0 8 * * *", "Asia/Kolkata")
    assert schedule.next_after(utc(2026, 10, 23, 0, 0)) == utc(2026, 10, 23, 2, 30)


def test_a_time_skipped_in_spring_fires_once_when_the_gap_ends() -> None:
    schedule = parse("30 2 * * *", "America/New_York")
    # 2026-03-08: clocks jump from 02:00 EST to 03:00 EDT, so 02:30 does not exist.
    fired = schedule.next_after(utc(2026, 3, 8, 5, 0))
    assert fired == utc(2026, 3, 8, 7, 0)
    assert fired is not None
    assert fired.astimezone(NEW_YORK).strftime("%H:%M %Z") == "03:00 EDT"
    assert schedule.next_after(fired) == utc(2026, 3, 9, 6, 30)


def test_every_fifteen_minutes_through_the_spring_gap() -> None:
    schedule = parse("*/15 * * * *", "America/New_York")
    fires = schedule.upcoming(utc(2026, 3, 8, 6, 40), 4)  # 01:40 EST
    local = [f.astimezone(NEW_YORK).strftime("%H:%M") for f in fires]
    assert local == ["01:45", "03:00", "03:15", "03:30"]


def test_a_time_repeated_in_autumn_fires_once() -> None:
    schedule = parse("30 1 * * *", "America/New_York")
    # 2026-11-01: 01:00 to 01:59 happens twice (EDT, then EST).
    first = schedule.next_after(utc(2026, 11, 1, 4, 0))
    assert first == utc(2026, 11, 1, 5, 30)  # 01:30 EDT
    assert first is not None
    assert schedule.next_after(first) == utc(2026, 11, 2, 6, 30)  # 01:30 EST, next day


def test_frequent_schedules_pause_during_the_repeated_hour() -> None:
    schedule = parse("*/30 * * * *", "America/New_York")
    fires = schedule.upcoming(utc(2026, 11, 1, 4, 50), 4)  # 00:50 EDT
    assert [f.astimezone(NEW_YORK).strftime("%H:%M %Z") for f in fires] == [
        "01:00 EDT",
        "01:30 EDT",
        "02:00 EST",
        "02:30 EST",
    ]
    # Restarted inside the repeated hour: nothing fires until the wall clock passes it.
    inside = utc(2026, 11, 1, 6, 10)  # 01:10 EST
    assert schedule.next_after(inside) == utc(2026, 11, 1, 7, 0)  # 02:00 EST


def test_next_after_requires_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        parse("* * * * *").next_after(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    ("expression", "summary"),
    [
        ("* * * * *", "Every minute"),
        ("*/5 * * * *", "Every 5 minutes"),
        ("7 * * * *", "Every hour at minute 7"),
        ("0 */6 * * *", "Every 6 hours at minute 0"),
        ("0 8 * * *", "Every day at 08:00"),
        ("30 8 * * 1-5", "Every weekdays at 08:30"),
        ("0 9 * * MON,THU", "Every Mon, Thu at 09:00"),
        ("0 6 1,15 * *", "Day 1, 15 of every month at 06:00"),
        ("0 0 1 1 *", "Cron 0 0 1 1 *"),
    ],
)
def test_descriptions(expression: str, summary: str) -> None:
    assert describe(parse(expression)) == summary


_minute_field = st.sampled_from(["*", "*/5", "0", "15,45", "10-20", "*/7", "3/20"])
_hour_field = st.sampled_from(["*", "*/2", "8", "9-17", "0,12"])
_day_field = st.sampled_from(["*", "1", "*/3", "10-20"])
_weekday_field = st.sampled_from(["*", "MON-FRI", "0", "SAT,SUN", "3"])


@settings(max_examples=60, deadline=None)
@given(
    minute=_minute_field,
    hour=_hour_field,
    day=_day_field,
    weekday=_weekday_field,
    offset_minutes=st.integers(min_value=0, max_value=60 * 24 * 40),
)
def test_matches_a_brute_force_scan_in_utc(
    minute: str, hour: str, day: str, weekday: str, offset_minutes: int
) -> None:
    schedule = parse(f"{minute} {hour} {day} * {weekday}")
    after = utc(2026, 1, 1) + timedelta(minutes=offset_minutes, seconds=17)
    expected = None
    probe = after.replace(second=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 40):
        weekday_ok = (probe.weekday() + 1) % 7 in schedule.weekdays
        day_ok = probe.day in schedule.days
        if schedule.days_restricted and schedule.weekdays_restricted:
            date_ok = day_ok or weekday_ok
        elif schedule.days_restricted:
            date_ok = day_ok
        elif schedule.weekdays_restricted:
            date_ok = weekday_ok
        else:
            date_ok = True
        if date_ok and probe.hour in schedule.hours and probe.minute in schedule.minutes:
            expected = probe
            break
        probe += timedelta(minutes=1)
    assert schedule.next_after(after) == expected
