import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from cgv_push_bot.alerts import poller as poller_module
from cgv_push_bot.alerts.poller import Poller
from cgv_push_bot.alerts.service import MovieAlertService


async def test_long_poll_skips_missed_slots_without_overlapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 15:00 UTC is midnight in Korea.
    current = datetime(2026, 9, 7, 15, 0, 0, tzinfo=UTC)
    starts: list[datetime] = []
    sleeps: list[float] = []

    def now(_tz: object) -> datetime:
        return current

    async def sleep(seconds: float) -> None:
        nonlocal current
        sleeps.append(seconds)
        current += timedelta(seconds=seconds)

    class SlowService:
        async def poll_once(self, *, now: datetime) -> int:
            nonlocal current
            starts.append(now)
            if len(starts) == 2:
                raise asyncio.CancelledError
            current += timedelta(seconds=301)
            return 0

    monkeypatch.setattr(poller_module, "datetime", SimpleNamespace(now=now))
    monkeypatch.setattr(
        poller_module,
        "asyncio",
        SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError),
    )
    poller = Poller(cast(MovieAlertService, SlowService()), 300, 1)
    with pytest.raises(asyncio.CancelledError):
        await poller._run()  # pyright: ignore[reportPrivateUsage]

    assert starts == [
        datetime(2026, 9, 7, 15, 0, 1, tzinfo=UTC),
        datetime(2026, 9, 7, 15, 10, 1, tzinfo=UTC),
    ]
    assert sleeps == [1, 299]
