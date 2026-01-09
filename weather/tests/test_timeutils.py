from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from weather.timeutils import local_day_bounds_to_utc


def test_local_day_bounds_to_utc_for_utc_zone() -> None:
    tz = ZoneInfo("UTC")
    day = date(2024, 1, 15)

    start, end = local_day_bounds_to_utc(day, tz)

    assert start == datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
    assert end == datetime(
        2024,
        1,
        15,
        time.max.hour,
        time.max.minute,
        time.max.second,
        time.max.microsecond,
        tzinfo=UTC,
    )
