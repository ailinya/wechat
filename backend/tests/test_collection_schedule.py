"""Unit tests for collection scheduling windows (task 3.5)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules.collection import schedule

NOW = datetime(2026, 11, 18, 1, 30, tzinfo=timezone.utc)  # 09:30 Asia/Shanghai


def test_manual_never_scheduled() -> None:
    assert schedule.compute_window_key("manual", None, "Asia/Shanghai", NOW) is None


def test_hourly_window_uses_task_timezone() -> None:
    key = schedule.compute_window_key("hourly", None, "Asia/Shanghai", NOW)
    assert key == "hourly:2026-11-18T09"


def test_daily_and_weekly_windows() -> None:
    assert schedule.compute_window_key("daily", None, "Asia/Shanghai", NOW) == "daily:2026-11-18"
    assert schedule.compute_window_key("weekly", None, "Asia/Shanghai", NOW) == "weekly:2026-W47"


def test_unknown_timezone_falls_back_to_utc() -> None:
    key = schedule.compute_window_key("daily", None, "Not/AZone", NOW)
    assert key == "daily:2026-11-18"


def test_cron_matches_and_nonmatch() -> None:
    local = NOW.astimezone(schedule.task_timezone("Asia/Shanghai"))
    assert schedule.cron_matches("30 9 * * *", local) is True  # 09:30, any day
    assert schedule.cron_matches("0 9 * * *", local) is False
    assert schedule.cron_matches("*/15 9 * * *", local) is True  # minute 30 is a 15-min step
    assert schedule.cron_matches("30 9 * * 1-5", local) is True  # Wednesday
    assert schedule.cron_matches("30 9 * * 0,6", local) is False


def test_cron_window_only_when_due() -> None:
    due = schedule.compute_window_key("cron", "30 9 * * *", "Asia/Shanghai", NOW)
    assert due == "cron:2026-11-18T09:30"
    not_due = schedule.compute_window_key("cron", "0 9 * * *", "Asia/Shanghai", NOW)
    assert not_due is None


def test_invalid_cron_returns_no_window() -> None:
    assert schedule.compute_window_key("cron", "bad expr", "Asia/Shanghai", NOW) is None
