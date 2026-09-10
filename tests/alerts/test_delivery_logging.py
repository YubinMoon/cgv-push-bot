from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cgv_push_bot.alerts.delivery import DeliveryService
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionStatus,
)
from cgv_push_bot.db.session import create_engine, create_session_factory


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def send(self, **_values: object) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return "secret-message-id"


async def _delivery_service(
    sender: FakeSender,
    *,
    max_attempts: int = 8,
    subscription_status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    expires_at: datetime | None = None,
) -> tuple[DeliveryService, AsyncEngine]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    async with sessions() as session, session.begin():
        target = MonitorTarget(
            theater_id="T1",
            theater_name="Allowed Theater",
            show_date=date(2026, 8, 20),
        )
        session.add(target)
        await session.flush()
        subscription = Subscription(
            discord_user_id="987654321",
            guild_id="444555666",
            channel_id="555666777",
            target_id=target.id,
            keyword="sensitive keyword",
            normalized_keyword="sensitive keyword",
            status=subscription_status,
            expires_at=expires_at,
        )
        session.add(subscription)
        await session.flush()
        session.add(
            Notification(
                subscription_id=subscription.id,
                next_retry_at=datetime(2026, 8, 14, tzinfo=UTC),
            )
        )
    return DeliveryService(sessions, sender, max_attempts=max_attempts), engine


@pytest.mark.asyncio
async def test_delivery_retry_logs_success_without_sensitive_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = FakeSender(RuntimeError("sensitive-discord-detail"))
    service, engine = await _delivery_service(sender)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    caplog.set_level(logging.INFO, logger="cgv_push_bot.alerts.delivery")

    assert await service.deliver_once(now=now) == 0
    assert "notification_delivery_failed" not in caplog.text

    assert await service.deliver_once(now=now + timedelta(seconds=59)) == 0
    assert sender.calls == 1

    sender.error = None
    assert await service.deliver_once(now=now + timedelta(seconds=60)) == 1
    assert "event=notification_delivery_succeeded" in caplog.text
    assert "notification_id=1 subscription_id=1 attempt_count=2" in caplog.text
    assert "987654321" not in caplog.text
    assert "555666777" not in caplog.text
    assert "secret-message-id" not in caplog.text
    assert "sensitive keyword" not in caplog.text
    assert "sensitive-discord-detail" not in caplog.text
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subscription_status", "expires_at", "expected_sent"),
    [
        (SubscriptionStatus.ACTIVE, datetime(2026, 8, 14, 0, 1, tzinfo=UTC), True),
        (SubscriptionStatus.EXPIRED, datetime(2026, 8, 14, 0, 1, tzinfo=UTC), False),
        (SubscriptionStatus.ACTIVE, datetime(2026, 8, 14, tzinfo=UTC), False),
        (SubscriptionStatus.ACTIVE, datetime(2026, 8, 13, 23, 59, tzinfo=UTC), False),
    ],
)
async def test_delivery_skips_inactive_or_expired_subscriptions(
    subscription_status: SubscriptionStatus,
    expires_at: datetime,
    expected_sent: bool,
) -> None:
    sender = FakeSender()
    service, engine = await _delivery_service(
        sender,
        subscription_status=subscription_status,
        expires_at=expires_at,
    )
    try:
        now = datetime(2026, 8, 14, tzinfo=UTC)
        assert await service.deliver_once(now=now) == (1 if expected_sent else 0)
        assert sender.calls == (1 if expected_sent else 0)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_logs_only_terminal_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender = FakeSender(RuntimeError("sensitive-discord-detail"))
    service, engine = await _delivery_service(sender, max_attempts=2)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    caplog.set_level(logging.INFO, logger="cgv_push_bot.alerts.delivery")

    assert await service.deliver_once(now=now) == 0
    assert "notification_delivery_failed" not in caplog.text

    assert await service.deliver_once(now=now + timedelta(seconds=60)) == 0
    assert "event=notification_delivery_failed" in caplog.text
    assert "notification_id=1 subscription_id=1 attempt_count=2" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "sensitive-discord-detail" not in caplog.text
    assert "987654321" not in caplog.text
    assert "555666777" not in caplog.text
    sessions = create_session_factory(engine)
    async with sessions() as session:
        notification = await session.get(Notification, 1)
        assert notification is not None
        assert notification.status == NotificationStatus.FAILED
        assert notification.attempts == 2
        assert notification.next_retry_at is None
        assert notification.last_error == "RuntimeError"
        assert "sensitive-discord-detail" not in notification.last_error
    caplog.clear()
    assert await service.deliver_once(now=now + timedelta(hours=2)) == 0
    assert sender.calls == 2
    assert not caplog.records
    await engine.dispose()
