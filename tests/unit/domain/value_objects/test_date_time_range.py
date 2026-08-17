import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.value_objects.date_time_range import DateTimeRange


def _dt(hour: int) -> datetime:
    return datetime(2026, 8, 4, hour, 0, tzinfo=UTC)


def test_creates_date_time_range_with_start_before_end():
    date_range = DateTimeRange(start=_dt(9), end=_dt(10))

    assert date_range.start == _dt(9)
    assert date_range.end == _dt(10)


def test_date_time_range_is_frozen():
    date_range = DateTimeRange(start=_dt(9), end=_dt(10))

    with pytest.raises(dataclasses.FrozenInstanceError):
        date_range.start = _dt(8)  # type: ignore[misc]


def test_rejects_start_equal_to_end():
    with pytest.raises(ValueError, match="start must be before end"):
        DateTimeRange(start=_dt(9), end=_dt(9))


def test_rejects_start_after_end():
    with pytest.raises(ValueError, match="start must be before end"):
        DateTimeRange(start=_dt(10), end=_dt(9))


def test_duration_returns_time_delta_between_start_and_end():
    date_range = DateTimeRange(start=_dt(9), end=_dt(10, ))

    assert date_range.duration() == timedelta(hours=1)


def test_duration_reflects_a_different_span():
    date_range = DateTimeRange(start=_dt(14), end=_dt(15))

    assert date_range.duration() == timedelta(hours=1)


def test_contains_returns_true_for_moment_inside_range():
    date_range = DateTimeRange(start=_dt(9), end=_dt(10))

    assert date_range.contains(datetime(2026, 8, 4, 9, 30, tzinfo=UTC)) is True


def test_contains_returns_false_for_moment_outside_range():
    date_range = DateTimeRange(start=_dt(9), end=_dt(10))

    assert date_range.contains(datetime(2026, 8, 4, 11, 0, tzinfo=UTC)) is False
