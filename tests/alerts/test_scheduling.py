from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from cgv_push_bot.alerts.scheduling import next_poll_slot

SEOUL = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 8, 0, 0, 0), datetime(2026, 9, 8, 0, 0, 1)),
        (datetime(2026, 9, 8, 0, 0, 1), datetime(2026, 9, 8, 0, 5, 1)),
        (datetime(2026, 9, 8, 0, 5, 0), datetime(2026, 9, 8, 0, 5, 1)),
        (datetime(2026, 9, 8, 0, 5, 1), datetime(2026, 9, 8, 0, 10, 1)),
        (datetime(2026, 9, 8, 23, 59, 59), datetime(2026, 9, 9, 0, 0, 1)),
    ],
)
def test_five_minute_slots_start_one_second_after_kst_midnight(
    now: datetime, expected: datetime
) -> None:
    # The production poller supplies UTC, while the schedule is anchored in KST.
    assert next_poll_slot(
        now.replace(tzinfo=SEOUL).astimezone(UTC),
        interval_seconds=300,
        offset_seconds=1,
    ) == expected.replace(tzinfo=SEOUL).astimezone(UTC)


@pytest.mark.parametrize(
    ("now", "interval", "expected"),
    [
        (
            datetime(2026, 8, 14, 0, 0, 1, tzinfo=SEOUL),
            60,
            datetime(2026, 8, 14, 0, 0, 2, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 8, 14, 0, 0, 2, tzinfo=SEOUL),
            60,
            datetime(2026, 8, 14, 0, 1, 2, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 8, 14, 0, 1, 3, tzinfo=SEOUL),
            60,
            datetime(2026, 8, 14, 0, 2, 2, tzinfo=SEOUL),
        ),
        (
            datetime(2026, 8, 14, 0, 0, 3, tzinfo=SEOUL),
            300,
            datetime(2026, 8, 14, 0, 5, 2, tzinfo=SEOUL),
        ),
    ],
)
def test_next_poll_slot_is_aligned_to_kst_midnight(
    now: datetime, interval: int, expected: datetime
) -> None:
    assert next_poll_slot(now, interval_seconds=interval, offset_seconds=2) == expected


@pytest.mark.parametrize(
    ("interval", "offset"),
    [(0, 0), (60, -1), (60, 60)],
)
def test_next_poll_slot_rejects_invalid_ranges(interval: int, offset: int) -> None:
    with pytest.raises(ValueError):
        next_poll_slot(
            datetime(2026, 8, 14, tzinfo=SEOUL),
            interval_seconds=interval,
            offset_seconds=offset,
        )
