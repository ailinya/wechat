"""Collection scheduling: timezone-aware window keys and cron matching (task 3.5)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def task_timezone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _field_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for expr in field.split(","):
        expr = expr.strip()
        if not expr:
            continue
        base, sep, step_text = expr.partition("/")
        step = int(step_text) if sep else 1
        if step < 1:
            continue
        if base == "*":
            low, high = minimum, maximum
        elif "-" in base:
            low_text, high_text = base.split("-", 1)
            low, high = int(low_text), int(high_text)
        else:
            low = high = int(base)
        for value in range(low, high + 1, step):
            if minimum <= value <= maximum:
                values.add(value)
    return values


def cron_matches(expr: str, moment: datetime) -> bool:
    """Match a 5-field cron expression (minute hour dom month dow, 0=Sunday)."""
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    iso_dow = (moment.weekday() + 1) % 7
    return (
        moment.minute in _field_values(minute, 0, 59)
        and moment.hour in _field_values(hour, 0, 23)
        and moment.day in _field_values(dom, 1, 31)
        and moment.month in _field_values(month, 1, 12)
        and iso_dow in _field_values(dow, 0, 6)
    )


def compute_window_key(
    frequency: str,
    cron_expr: str | None,
    timezone_name: str,
    now: datetime | None = None,
) -> str | None:
    """Return the dedup window key for a scheduled task, or None if not due."""
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(task_timezone(timezone_name))
    if frequency == "hourly":
        return f"hourly:{local:%Y-%m-%dT%H}"
    if frequency == "daily":
        return f"daily:{local:%Y-%m-%d}"
    if frequency == "weekly":
        iso = local.isocalendar()
        return f"weekly:{iso.year}-W{iso.week:02d}"
    if frequency == "cron":
        if not cron_expr or not cron_matches(cron_expr, local):
            return None
        return f"cron:{local:%Y-%m-%dT%H:%M}"
    return None  # manual tasks are never scheduled
