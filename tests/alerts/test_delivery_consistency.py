import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cgv_push_bot.alerts.delivery import DeliveryService
from cgv_push_bot.alerts.service import MovieAlertService
from cgv_push_bot.cgv.gateway import CgvGateway
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionMovie,
)
from cgv_push_bot.db.session import create_engine, create_session_factory

NOW = datetime(2026, 9, 16, tzinfo=UTC)
DISCOVERED = NOW - timedelta(hours=1)


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            target = MonitorTarget(
                theater_id="T1", theater_name="용산", show_date=date(2026, 9, 16)
            )
            session.add(target)
            await session.flush()
            for user_id in (1, 2):
                subscription = Subscription(
                    discord_user_id=str(user_id),
                    channel_id="10",
                    target_id=target.id,
                    expires_at=NOW + timedelta(minutes=1),
                )
                session.add(subscription)
                await session.flush()
                notification = Notification(subscription_id=subscription.id, created_at=DISCOVERED)
                session.add(notification)
                await session.flush()
                session.add(
                    SubscriptionMovie(
                        subscription_id=subscription.id,
                        movie_id="movie",
                        movie_title="영화",
                        notification_id=notification.id,
                    )
                )
        yield factory
    finally:
        await engine.dispose()


async def test_rechecks_deleted_subscription_after_loading_batch(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    calls: list[object] = []

    class Sender:
        async def send(self, **values: object) -> str:
            calls.append(values["user_id"])
            if len(calls) == 1:
                async with sessions() as session, session.begin():
                    await session.execute(delete(Subscription).where(Subscription.id == 2))
            return "message"

    assert await DeliveryService(sessions, Sender()).deliver_once(now=NOW) == 1
    assert calls == [1]


async def test_rechecks_expiration_using_current_time_between_sends(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    current = NOW
    calls: list[object] = []

    class Sender:
        async def send(self, **values: object) -> str:
            nonlocal current
            calls.append(values["user_id"])
            current += timedelta(minutes=1)
            return "message"

    service = DeliveryService(sessions, Sender(), clock=lambda: current)
    assert await service.deliver_once() == 1
    assert calls == [1]
    async with sessions() as session:
        notification = await session.get(Notification, 2)
        assert notification is not None
        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 0


@pytest.mark.parametrize("deleted_user", [1, 2])
async def test_delete_waits_for_inflight_send_and_prevents_later_sends(
    sessions: async_sessionmaker[AsyncSession],
    deleted_user: int,
) -> None:
    lock = asyncio.Lock()
    sending = asyncio.Event()
    release = asyncio.Event()
    deleting = asyncio.Event()
    calls: list[object] = []

    class Sender:
        async def send(self, **values: object) -> str:
            calls.append(values["user_id"])
            if len(calls) == 1:
                sending.set()
                await release.wait()
            return "message"

    alerts = MovieAlertService(sessions, cast(CgvGateway, None), subscription_lock=lock)
    delivery = DeliveryService(sessions, Sender(), subscription_lock=lock)

    async def delete_subscription() -> None:
        deleting.set()
        await alerts.delete_subscription(user_id=deleted_user, subscription_id=str(deleted_user))

    async with asyncio.timeout(5):
        async with asyncio.TaskGroup() as group:
            send_task = group.create_task(delivery.deliver_once(now=NOW))
            await sending.wait()
            delete_task = group.create_task(delete_subscription())
            await deleting.wait()
            assert not delete_task.done()
            release.set()
    assert send_task.result() == (2 if deleted_user == 1 else 1)
    assert calls == ([1, 2] if deleted_user == 1 else [1])
    async with sessions() as session:
        assert await session.get(Subscription, deleted_user) is None
    assert await delivery.deliver_once(now=NOW) == 0


async def test_retry_keeps_persisted_discovery_timestamp(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    received: list[object] = []

    class Sender:
        async def send(self, **values: object) -> str:
            received.append(values["discovered_at"])
            if len(received) == 1:
                raise RuntimeError("temporary failure")
            return "message"

    # Keep one unexpired subscription for an hour-delayed retry.
    async with sessions() as session, session.begin():
        await session.execute(delete(Subscription).where(Subscription.id == 2))
        subscription = await session.get(Subscription, 1)
        assert subscription is not None
        subscription.expires_at = NOW + timedelta(days=1)
    delivery = DeliveryService(sessions, Sender())
    assert await delivery.deliver_once(now=NOW) == 0
    assert await delivery.deliver_once(now=NOW + timedelta(hours=1)) == 1
    assert received == [DISCOVERED, DISCOVERED]
    async with sessions() as session:
        notification = await session.scalar(select(Notification))
        assert notification is not None
        assert notification.attempts == 2
        assert notification.status == NotificationStatus.SENT
