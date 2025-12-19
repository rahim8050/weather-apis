from __future__ import annotations

from datetime import date, datetime, time, timezone, tzinfo
from zoneinfo import ZoneInfo


def get_zone(tz_str: str) -> ZoneInfo:
    """Return a ZoneInfo instance or raise for invalid input."""

    try:
        return ZoneInfo(tz_str)
    except Exception as exc:  # pragma: no cover - zoneinfo raised
        raise ValueError(f"Invalid timezone: {tz_str}") from exc


def ensure_aware(dt: datetime, tz: tzinfo) -> datetime:
    """Attach or convert timezone information to a datetime."""

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def local_day_bounds_to_utc(
    day_local: date, tz: ZoneInfo
) -> tuple[datetime, datetime]:
    """Return UTC start/end datetimes for a local calendar day."""

    start_local = datetime.combine(day_local, time.min).replace(tzinfo=tz)
    end_local = datetime.combine(day_local, time.max).replace(tzinfo=tz)
    return start_local.astimezone(
        timezone.utc  # noqa: UP017
    ), end_local.astimezone(
        timezone.utc  # noqa: UP017
    )


def isoformat_with_tz(dt: datetime, tz: tzinfo | None = None) -> str:
    """Return an ISO8601 string with timezone offset."""

    zone = tz or dt.tzinfo or timezone.utc  # noqa: UP017
    aware = ensure_aware(dt, zone)
    return aware.isoformat()
