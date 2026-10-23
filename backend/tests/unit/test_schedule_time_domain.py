from datetime import datetime, timedelta, timezone

import pytest

from src.domain.broadcast.broadcast_message import SCHEDULE_CLOCK_TOLERANCE, ensure_schedulable

NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=timezone.utc)
PAST_MESSAGE = r"^scheduled_at cannot be in the past$"


def test_tolerance_is_sixty_seconds():
    assert SCHEDULE_CLOCK_TOLERANCE == timedelta(seconds=60)


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
