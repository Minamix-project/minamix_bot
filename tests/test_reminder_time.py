from datetime import datetime, timezone

import pytest

from src.utils.reminder_time import parse_reminder_time

NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(("value", "expected"), [
    ("2h", datetime(2026, 9, 7, 14, tzinfo=timezone.utc)),
    ("1d 30m", datetime(2026, 9, 8, 12, 30, tzinfo=timezone.utc)),
    ("1j 30m", datetime(2026, 9, 8, 12, 30, tzinfo=timezone.utc)),
    ("1sem2j3h4m5s", datetime(2026, 9, 16, 15, 4, 5, tzinfo=timezone.utc)),
    ("1w2d3h4m5s", datetime(2026, 9, 16, 15, 4, 5, tzinfo=timezone.utc)),
    ("tomorrow 18:00", datetime(2026, 9, 8, 16, tzinfo=timezone.utc)),
    ("demain 18:00", datetime(2026, 9, 8, 16, tzinfo=timezone.utc)),
    ("today 18:00", datetime(2026, 9, 7, 16, tzinfo=timezone.utc)),
    ("aujourd'hui 18:00", datetime(2026, 9, 7, 16, tzinfo=timezone.utc)),
    ("18:00", datetime(2026, 9, 7, 16, tzinfo=timezone.utc)),
    ("15/09/2026 20:00", datetime(2026, 9, 15, 18, tzinfo=timezone.utc)),
    ("2026-12-15 20:00", datetime(2026, 12, 15, 19, tzinfo=timezone.utc)),
])
def test_supported_schedules(value, expected):
    assert parse_reminder_time(value, now=NOW) == int(expected.timestamp())


@pytest.mark.parametrize("value", ["", "0s", "-2h", "2hours", "yesterday 18:00", "tomorrow", "12:00",
                                  "31/09/2026 20:00", "01/01/2020 20:00", "2000w", "tomorrow 25:00"])
def test_invalid_or_past_schedules(value):
    with pytest.raises(ValueError):
        parse_reminder_time(value, now=NOW)


@pytest.mark.parametrize("value", ["29/03/2026 02:30", "25/10/2026 02:30"])
def test_daylight_saving_gaps_and_overlaps_are_rejected(value):
    with pytest.raises(ValueError, match="changement d'heure"):
        parse_reminder_time(value, now=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_elapsed_duration_across_daylight_saving_and_relative_local_day():
    now = datetime(2026, 3, 28, 12, tzinfo=timezone.utc)
    assert parse_reminder_time("1d", now=now) == int(now.timestamp()) + 86400
    assert parse_reminder_time("tomorrow 13:00", now=now) == int(now.timestamp()) + 23 * 3600
    late_utc = datetime(2026, 9, 7, 23, tzinfo=timezone.utc)
    assert parse_reminder_time("tomorrow 18:00", now=late_utc) == int(
        datetime(2026, 9, 9, 16, tzinfo=timezone.utc).timestamp()
    )


def test_explicit_timezone_and_invalid_zone():
    assert parse_reminder_time("18:00", "UTC", now=NOW) == int(NOW.timestamp()) + 6 * 3600
    with pytest.raises(ValueError, match="Fuseau horaire inconnu"):
        parse_reminder_time("2h", "Invalid/Zone", now=NOW)
