from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cgv_push_bot.alerts.service import MovieAlertService
from cgv_push_bot.cgv import Theater
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


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


async def seed(
    sessions: async_sessionmaker[AsyncSession],
    *,
    expires_at: datetime | None,
    status: SubscriptionStatus = SubscriptionStatus.EXPIRED,
    user_id: str = "1",
    target_id: int | None = None,
) -> tuple[int, int]:
    async with sessions() as session, session.begin():
        if target_id is None:
            target = MonitorTarget(
                theater_id=user_id,
                theater_name="용산",
                show_date=date(2025, 1, 1),
                last_success_at=datetime(2025, 1, 1, tzinfo=UTC),
                last_error="RuntimeError",
            )
            session.add(target)
            await session.flush()
            target_id = target.id
        subscription = Subscription(
            discord_user_id=user_id,
            channel_id="10",
            target_id=target_id,
            status=status,
            expires_at=expires_at,
        )
        session.add(subscription)
        await session.flush()
        for notification_status in NotificationStatus:
            notification = Notification(subscription_id=subscription.id, status=notification_status)
            session.add(notification)
            await session.flush()
            session.add(
                SubscriptionMovie(
                    subscription_id=subscription.id,
                    movie_id=notification_status.value,
                    movie_title="영화",
                    notification_id=notification.id,
                )
            )
        return subscription.id, target_id


async def test_cleanup_boundary_cascades_and_preserves_shared_targets(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    cutoff = now - timedelta(days=90)
    old, shared_target = await seed(sessions, expires_at=cutoff)
    recent, _ = await seed(sessions, expires_at=cutoff + timedelta(seconds=1), user_id="2")
    active, _ = await seed(
        sessions,
        expires_at=cutoff,
        status=SubscriptionStatus.ACTIVE,
        user_id="3",
        target_id=shared_target,
    )
    unknown, _ = await seed(sessions, expires_at=None, user_id="4")
    removed, removed_target = await seed(sessions, expires_at=cutoff, user_id="5")
    service = MovieAlertService(sessions, cast(CgvGateway, None))
    assert await service.cleanup_history(now=now) == 2
    async with sessions() as session:
        assert set(await session.scalars(select(Subscription.id))) == {recent, active, unknown}
        assert await session.get(MonitorTarget, shared_target) is not None
        assert await session.get(MonitorTarget, removed_target) is None
        assert not tuple(
            await session.scalars(
                select(Notification).where(Notification.subscription_id.in_((old, removed)))
            )
        )
        assert not tuple(
            await session.scalars(
                select(SubscriptionMovie).where(
                    SubscriptionMovie.subscription_id.in_((old, removed))
                )
            )
        )
    assert await service.cleanup_history(now=now) == 0


async def test_cleanup_disabled(sessions: async_sessionmaker[AsyncSession]) -> None:
    identifier, _ = await seed(sessions, expires_at=datetime(2020, 1, 1, tzinfo=UTC))
    service = MovieAlertService(sessions, cast(CgvGateway, None), history_retention_days=0)
    assert await service.cleanup_history() == 0
    async with sessions() as session:
        assert await session.get(Subscription, identifier) is not None


async def test_health_counts_are_scoped_to_subscription_and_owner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, target_id = await seed(sessions, expires_at=None, status=SubscriptionStatus.ACTIVE)
    await seed(
        sessions,
        expires_at=None,
        status=SubscriptionStatus.ACTIVE,
        user_id="2",
        target_id=target_id,
    )
    service = MovieAlertService(sessions, cast(CgvGateway, None))
    summaries = await service.list_subscriptions(1)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.poll_failed
    assert summary.last_success_at is not None
    assert summary.last_success_at.replace(tzinfo=UTC) == datetime(2025, 1, 1, tzinfo=UTC)
    assert summary.pending_notifications == 1
    assert summary.failed_notifications == 1
    assert await service.list_subscriptions(3) == ()


async def test_theater_search_does_not_truncate(sessions: async_sessionmaker[AsyncSession]) -> None:
    class Gateway:
        async def search_theaters(self, query: str) -> tuple[Theater, ...]:
            return tuple(Theater(id=str(index), name=query, region_id="R1") for index in range(60))

    service = MovieAlertService(sessions, cast(CgvGateway, Gateway()))
    assert len(await service.search_theaters("CGV")) == 60


async def test_poll_expires_and_cleans_old_history(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    identifier, target_id = await seed(
        sessions,
        expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        status=SubscriptionStatus.ACTIVE,
    )
    service = MovieAlertService(sessions, cast(CgvGateway, None))
    assert await service.poll_once(now=datetime(2026, 9, 15, tzinfo=UTC)) == 0
    async with sessions() as session:
        assert await session.get(Subscription, identifier) is None
        assert await session.get(MonitorTarget, target_id) is None


async def test_cleanup_limits_each_batch(sessions: async_sessionmaker[AsyncSession]) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    async with sessions() as session, session.begin():
        target = MonitorTarget(theater_id="T1", theater_name="용산", show_date=date(2020, 1, 1))
        session.add(target)
        await session.flush()
        session.add_all(
            Subscription(
                discord_user_id=str(index),
                channel_id="10",
                target_id=target.id,
                status=SubscriptionStatus.EXPIRED,
                expires_at=now - timedelta(days=91),
            )
            for index in range(501)
        )
        target_id = target.id
    service = MovieAlertService(sessions, cast(CgvGateway, None))
    assert await service.cleanup_history(now=now) == 500
    async with sessions() as session:
        assert await session.get(MonitorTarget, target_id) is not None
    assert await service.cleanup_history(now=now) == 1
    async with sessions() as session:
        assert await session.get(MonitorTarget, target_id) is None
