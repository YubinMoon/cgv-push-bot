from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy import update

import cgv_push_bot.alerts.service as service_module
from cgv_push_bot.alerts.service import MovieAlertService
from cgv_push_bot.cgv import Movie
from cgv_push_bot.cgv.gateway import CgvGateway
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import MonitorTarget
from cgv_push_bot.db.session import create_engine, create_session_factory


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


class TimedGateway:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.work: dict[str, tuple[float, Exception | None]] = {}
        self.calls: list[tuple[str, date, float]] = []

    async def get_movies(self, theater_id: str, show_date: date) -> tuple[Movie, ...]:
        self.calls.append((theater_id, show_date, self.clock.now))
        duration, error = self.work.get(theater_id, (0.0, None))
        self.clock.now += duration
        if error is not None:
            raise error
        return ()


async def _database() -> tuple[Any, Any]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, create_session_factory(engine)


@pytest.mark.asyncio
async def test_poll_paces_fast_slow_and_error_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, sessions = await _database()
    clock = FakeClock()
    gateway = TimedGateway(clock)
    service = MovieAlertService(sessions, cast(CgvGateway, gateway))
    monkeypatch.setattr(service_module, "monotonic", clock.monotonic)
    monkeypatch.setattr(service_module, "sleep", clock.sleep)

    for user_id, theater_id in enumerate(("fast", "error", "slow", "last"), start=1):
        await service.register_subscription(
            user_id=user_id,
            guild_id=None,
            channel_id=user_id,
            theater_id=theater_id,
            theater_name=theater_id,
            show_date=date(2026, 8, 20),
            keyword="",
        )
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))

    gateway.calls.clear()
    clock.now = 100.0
    gateway.work = {
        "fast": (0.1, None),
        "error": (0.1, RuntimeError("temporary")),
        "slow": (0.8, None),
        "last": (0.1, None),
    }

    assert await service.poll_once(now=datetime(2026, 8, 14, tzinfo=UTC)) == 0
    assert [call[0] for call in gateway.calls] == ["fast", "error", "slow", "last"]
    assert [call[2] for call in gateway.calls] == pytest.approx([100.0, 100.5, 101.0, 101.8])
    assert clock.sleeps == pytest.approx([0.4, 0.4])
    await engine.dispose()


@pytest.mark.asyncio
async def test_poll_orders_targets_by_show_date_and_deduplicates_shared_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _database()
    clock = FakeClock()
    gateway = TimedGateway(clock)
    service = MovieAlertService(sessions, cast(CgvGateway, gateway))
    monkeypatch.setattr(service_module, "monotonic", clock.monotonic)
    monkeypatch.setattr(service_module, "sleep", clock.sleep)

    registrations = (
        (1, "late", date(2026, 8, 22)),
        (2, "early-b", date(2026, 8, 20)),
        (3, "early-a", date(2026, 8, 20)),
        (4, "early-b", date(2026, 8, 20)),
    )
    for user_id, theater_id, show_date in registrations:
        await service.register_subscription(
            user_id=user_id,
            guild_id=None,
            channel_id=user_id,
            theater_id=theater_id,
            theater_name=theater_id,
            show_date=show_date,
            keyword="",
        )
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))

    gateway.calls.clear()
    assert await service.poll_once(now=datetime(2026, 8, 14, tzinfo=UTC)) == 0
    assert [(theater_id, show_date) for theater_id, show_date, _ in gateway.calls] == [
        ("early-b", date(2026, 8, 20)),
        ("early-a", date(2026, 8, 20)),
        ("late", date(2026, 8, 22)),
    ]
    await engine.dispose()
