from datetime import datetime, timedelta, timezone

import pytest

from src.domain.broadcast.broadcast_message import (
    DEFAULT_MISFIRE_GRACE_MINUTES,
    DueScheduleAction,
    SCHEDULE_CLOCK_TOLERANCE,
    ensure_schedulable,
    evaluate_due_schedule,
)

NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
PAST_MESSAGE = r"^scheduled_at cannot be in the past$"


def test_tolerance_is_sixty_seconds():
    assert SCHEDULE_CLOCK_TOLERANCE == timedelta(seconds=60)


def test_default_misfire_grace_minutes_is_thirty():
    assert DEFAULT_MISFIRE_GRACE_MINUTES == 30
    assert DueScheduleAction.WAIT.value == "WAIT"
    assert DueScheduleAction.DISPATCH.value == "DISPATCH"
    assert DueScheduleAction.MISFIRE.value == "MISFIRE"


def test_evaluate_due_schedule_waits_for_future_schedule():
    grace = timedelta(minutes=DEFAULT_MISFIRE_GRACE_MINUTES)
    assert evaluate_due_schedule(NOW + timedelta(seconds=1), now=NOW, grace_window=grace) is DueScheduleAction.WAIT


def test_evaluate_due_schedule_dispatches_at_or_within_grace_window():
    grace = timedelta(minutes=30)
    assert evaluate_due_schedule(NOW, now=NOW, grace_window=grace) is DueScheduleAction.DISPATCH
    assert evaluate_due_schedule(NOW - timedelta(minutes=15), now=NOW, grace_window=grace) is DueScheduleAction.DISPATCH
    assert evaluate_due_schedule(NOW - timedelta(minutes=30), now=NOW, grace_window=grace) is DueScheduleAction.DISPATCH


def test_evaluate_due_schedule_misfires_past_grace_window():
    grace = timedelta(minutes=30)
    assert (
        evaluate_due_schedule(NOW - timedelta(minutes=30, microseconds=1), now=NOW, grace_window=grace)
        is DueScheduleAction.MISFIRE
    )
    assert (
        evaluate_due_schedule(NOW - timedelta(hours=5), now=NOW, grace_window=grace)
        is DueScheduleAction.MISFIRE
    )


def test_evaluate_due_schedule_rejects_naive_scheduled_at():
    grace = timedelta(minutes=30)
    with pytest.raises(ValueError, match=r"^scheduled_at must include a timezone$"):
        evaluate_due_schedule(datetime(2026, 10, 22, 11, 30, 0), now=NOW, grace_window=grace)


def test_evaluate_due_schedule_rejects_negative_grace_window():
    with pytest.raises(ValueError, match=r"^grace_window cannot be negative$"):
        evaluate_due_schedule(NOW, now=NOW, grace_window=timedelta(seconds=-1))
    assert evaluate_due_schedule(NOW, now=NOW, grace_window=timedelta(0)) is DueScheduleAction.DISPATCH
    assert (
        evaluate_due_schedule(NOW - timedelta(microseconds=1), now=NOW, grace_window=timedelta(0))
        is DueScheduleAction.MISFIRE
    )


def test_accepts_future_and_the_exact_tolerance_boundary():
    ensure_schedulable(NOW + timedelta(hours=1), now=NOW)
    ensure_schedulable(NOW, now=NOW)
    ensure_schedulable(NOW - timedelta(seconds=60), now=NOW)


def test_rejects_anything_older_than_the_tolerance():
    with pytest.raises(ValueError, match=PAST_MESSAGE):
        ensure_schedulable(NOW - timedelta(seconds=60, microseconds=1), now=NOW)
    with pytest.raises(ValueError, match=PAST_MESSAGE):
        ensure_schedulable(NOW - timedelta(days=1), now=NOW)


def test_rejects_naive_datetimes():
    with pytest.raises(ValueError, match=r"^scheduled_at must include a timezone$"):
        ensure_schedulable(datetime(2026, 10, 22, 13, 0, 0), now=NOW)


def test_compares_instants_across_timezones():
    sao_paulo = timezone(timedelta(hours=-3))
    ensure_schedulable(datetime(2026, 10, 22, 9, 0, 0, tzinfo=sao_paulo), now=NOW)
    with pytest.raises(ValueError, match=PAST_MESSAGE):
        ensure_schedulable(datetime(2026, 10, 22, 8, 58, 0, tzinfo=sao_paulo), now=NOW)
