from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from cgv_push_bot.alerts.delivery import DeliveryService
from cgv_push_bot.alerts.service import MovieAlertService, expiration_for
from cgv_push_bot.cgv import Movie
from cgv_push_bot.cgv.gateway import CgvGateway
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionMovie,
    SubscriptionStatus,
)
from cgv_push_bot.db.session import create_engine, create_session_factory


class FakeGateway:
    def __init__(self, movies: tuple[Movie, ...] = ()) -> None:
        self.movies = movies
        self.calls = 0
        self.error: Exception | None = None

    async def get_movies(self, _theater_id: str, _show_date: date) -> tuple[Movie, ...]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.movies


class FakeSender:
    def __init__(self) -> None:
        self.error: Exception | None = RuntimeError("Discord unavailable")

    async def send(self, **_values: object) -> str:
        if self.error is not None:
            raise self.error
        return "123"


@pytest.mark.asyncio
async def test_list_current_movies_filters_keyword_and_deduplicates_titles() -> None:
    gateway = FakeGateway(
        (
            Movie("1", "Dune"),
            Movie("2", "DUNE: Part Two"),
            Movie("3", "Elemental"),
            Movie("4", "Dune"),
        )
    )
    service = MovieAlertService(
        cast(Any, None),
        cast(CgvGateway, gateway),
    )

    movies = await service.list_current_movies(
        theater_id="T1", show_date=date(2026, 8, 20), keyword=" dune "
    )

    assert movies == ("Dune", "DUNE: Part Two")
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_baseline_new_movie_keyword_and_no_duplicate_reappearance() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    gateway = FakeGateway((Movie("old", "Existing"),))
    service = MovieAlertService(sessions, cast(CgvGateway, gateway), poll_interval_seconds=60)
    await service.register_subscription(
        user_id=1,
        guild_id=2,
        channel_id=3,
        theater_id="T1",
        theater_name="Theater",
        show_date=date(2026, 8, 20),
        keyword=" dune ",
    )
    async with sessions() as session:
        baseline = await session.scalar(
            select(func.count())
            .select_from(SubscriptionMovie)
            .where(SubscriptionMovie.is_baseline.is_(True))
        )
        notifications = await session.scalar(select(func.count()).select_from(Notification))
    assert baseline == 1
    assert notifications == 0

    gateway.movies = (
        Movie("old", "Existing"),
        Movie("new", "DUNE: Part Two"),
        Movie("other", "Elemental"),
    )
    now = datetime(2026, 8, 14, tzinfo=UTC)
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))
    assert await service.poll_once(now=now) == 1
    async with sessions() as session:
        observed = await session.scalar(select(func.count()).select_from(SubscriptionMovie))
        notifications = await session.scalar(select(func.count()).select_from(Notification))
    assert observed == 3
    assert notifications == 1

    gateway.movies = (Movie("old", "Existing"), Movie("new", "DUNE: Part Two"))
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))
    assert await service.poll_once(now=now + timedelta(minutes=2)) == 0
    gateway.movies = (Movie("old", "Existing"),)
    assert await service.poll_once(now=now + timedelta(minutes=4)) == 0
    gateway.movies = (Movie("old", "Existing"), Movie("new", "DUNE: Part Two"))
    assert await service.poll_once(now=now + timedelta(minutes=6)) == 0
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Notification)) == 1
    assert gateway.calls == 5

    async with sessions() as session, session.begin():
        subscription = await session.scalar(select(Subscription))
        assert subscription is not None
        subscription.status = SubscriptionStatus.EXPIRED
    replacement = await service.register_subscription(
        user_id=1,
        guild_id=2,
        channel_id=3,
        theater_id="T1",
        theater_name="Theater",
        show_date=date(2026, 8, 20),
        keyword=" dune ",
    )
    assert replacement.status == "active"
    await engine.dispose()


@pytest.mark.asyncio
async def test_poll_error_preserves_baseline_and_delivery_retries() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    gateway = FakeGateway((Movie("old", "Existing"),))
    service = MovieAlertService(sessions, cast(CgvGateway, gateway), poll_interval_seconds=60)
    await service.register_subscription(
        user_id=1,
        guild_id=None,
        channel_id=3,
        theater_id="T1",
        theater_name="Theater",
        show_date=date(2026, 8, 20),
        keyword="",
    )
    now = datetime(2026, 8, 14, tzinfo=UTC)
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))
    gateway.error = RuntimeError("temporary CGV error")
    assert await service.poll_once(now=now) == 0
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SubscriptionMovie)) == 1
        target = await session.scalar(select(MonitorTarget))
        assert target is not None and target.last_error == "RuntimeError"

    gateway.error = None
    gateway.movies = (Movie("old", "Existing"), Movie("new", "New Movie"))
    async with sessions() as session, session.begin():
        await session.execute(update(MonitorTarget).values(next_poll_at=None))
    assert await service.poll_once(now=now) == 1
    sender = FakeSender()
    delivery = DeliveryService(sessions, sender)
    assert await delivery.deliver_once(now=now) == 0
    async with sessions() as session:
        notification = await session.scalar(select(Notification))
        assert notification is not None
        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1
    sender.error = None
    assert await delivery.deliver_once(now=now + timedelta(seconds=60)) == 1
    async with sessions() as session:
        notification = await session.scalar(select(Notification))
        assert notification is not None
        assert notification.status == NotificationStatus.SENT
        assert notification.discord_message_id == "123"
    await engine.dispose()


def test_subscription_expiration_is_six_am_kst_next_day() -> None:
    assert expiration_for(date(2026, 8, 20)) == datetime(2026, 8, 20, 21, tzinfo=UTC)


async def test_failed_movie_save_rolls_back_notification_and_can_be_retried() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        gateway = FakeGateway((Movie("old", "Existing"),))
        service = MovieAlertService(sessions, cast(CgvGateway, gateway))
        await service.register_subscription(
            user_id=1,
            guild_id=None,
            channel_id=3,
            theater_id="T1",
            theater_name="Theater",
            show_date=date(2030, 1, 1),
            keyword="",
        )
        async with sessions() as session, session.begin():
            await session.execute(update(MonitorTarget).values(next_poll_at=None))
            await session.execute(
                text(
                    "CREATE TRIGGER reject_new_movie BEFORE INSERT ON subscription_movies "
                    "WHEN NEW.is_baseline = 0 "
                    "BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
                )
            )

        gateway.movies = (Movie("old", "Existing"), Movie("new", "New movie"))
        now = datetime(2026, 9, 16, tzinfo=UTC)
        with pytest.raises(IntegrityError):
            await service.poll_once(now=now)
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification)) == 0
            assert await session.scalar(select(func.count()).select_from(SubscriptionMovie)) == 1
            target = await session.scalar(select(MonitorTarget))
            assert target is not None
            assert target.last_success_at is None

        async with sessions() as session, session.begin():
            await session.execute(text("DROP TRIGGER reject_new_movie"))
        assert await service.poll_once(now=now) == 1
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Notification)) == 1
            assert await session.scalar(select(func.count()).select_from(SubscriptionMovie)) == 2
    finally:
        await engine.dispose()


@pytest.mark.parametrize("guild_id", [None, 42])
async def test_subscription_summary_preserves_destination_and_owner(guild_id: int | None) -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        service = MovieAlertService(create_session_factory(engine), cast(CgvGateway, FakeGateway()))
        summary = await service.register_subscription(
            user_id=7,
            guild_id=guild_id,
            channel_id=123,
            theater_id="T1",
            theater_name="용산",
            show_date=date(2030, 1, 1),
            keyword="",
        )
        assert (summary.guild_id, summary.channel_id) == (guild_id, 123)
        owned = await service.list_subscriptions(7)
        assert len(owned) == 1
        assert (owned[0].guild_id, owned[0].channel_id) == (guild_id, 123)
        assert await service.list_subscriptions(8) == ()
        await service.delete_subscription(user_id=7, subscription_id=summary.id)
        assert await service.list_subscriptions(7) == ()
    finally:
        await engine.dispose()
