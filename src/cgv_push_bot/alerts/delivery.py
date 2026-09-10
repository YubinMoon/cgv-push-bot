from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cgv_push_bot.db.models import Notification, NotificationStatus
from cgv_push_bot.db.repositories import NotificationRepository

from .protocols import NotificationSender

LOGGER = logging.getLogger(__name__)


class DeliveryService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        sender: NotificationSender,
        *,
        max_attempts: int = 8,
        subscription_lock: asyncio.Lock | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._sender = sender
        self._max_attempts = max_attempts
        self._delivery_lock = asyncio.Lock()
        # Shared with subscription deletion.
        self._subscription_lock = subscription_lock or asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def deliver_once(self, *, now: datetime | None = None, limit: int = 25) -> int:
        async with self._delivery_lock:
            return await self._deliver_once(now=now, limit=limit)

    async def _deliver_once(self, *, now: datetime | None = None, limit: int = 25) -> int:
        current = now or self._clock()
        async with self._sessions() as session:
            identifiers = tuple(
                await NotificationRepository(session).list_deliverable_ids(
                    now=current,
                    limit=limit,
                )
            )
        sent = 0
        for identifier in identifiers:
            async with self._subscription_lock:
                sent += await self._deliver_notification(identifier, now=now)
        return sent

    async def _deliver_notification(self, identifier: int, *, now: datetime | None) -> int:
        # A batch may wait on slow sends. Re-read state and time after acquiring the
        # deletion lock; never send using the batch's stale subscription snapshot.
        current = now or self._clock()
        async with self._sessions() as session:
            notification = await NotificationRepository(session).get_deliverable(
                identifier,
                now=current,
            )
        if notification is None:
            return 0
        subscription = notification.subscription
        target = subscription.target
        discovered_at = notification.created_at
        if discovered_at.tzinfo is None:
            # SQLite returns naive timestamps; persisted timestamps are UTC.
            discovered_at = discovered_at.replace(tzinfo=UTC)
        try:
            message_id = await self._sender.send(
                user_id=int(subscription.discord_user_id),
                guild_id=None if subscription.guild_id is None else int(subscription.guild_id),
                channel_id=int(subscription.channel_id),
                theater_name=target.theater_name,
                show_date=target.show_date,
                keyword=subscription.keyword,
                movie_titles=tuple(movie.movie_title for movie in notification.movies),
                discovered_at=discovered_at,
            )
        except Exception as error:
            failure = await self._mark_failure(notification.id, error, now or self._clock())
            if failure is not None:
                attempt_count, terminal = failure
                if terminal:
                    LOGGER.error(
                        "event=notification_delivery_failed "
                        "notification_id=%s subscription_id=%s "
                        "attempt_count=%s error_type=%s",
                        notification.id,
                        subscription.id,
                        attempt_count,
                        type(error).__name__,
                    )
        else:
            attempt_count = await self._mark_sent(notification.id, message_id, now or self._clock())
            if attempt_count is not None:
                LOGGER.info(
                    "event=notification_delivery_succeeded "
                    "notification_id=%s subscription_id=%s attempt_count=%s",
                    notification.id,
                    subscription.id,
                    attempt_count,
                )
                return 1
        return 0

    async def _mark_sent(self, notification_id: int, message_id: str, now: datetime) -> int | None:
        attempt_count = None
        async with self._sessions() as session, session.begin():
            notification = await session.get(Notification, notification_id)
            if notification is not None:
                notification.status = NotificationStatus.SENT
                notification.attempts += 1
                notification.discord_message_id = message_id
                notification.sent_at = now
                notification.last_error = None
                attempt_count = notification.attempts
        return attempt_count

    async def _mark_failure(
        self, notification_id: int, error: Exception, now: datetime
    ) -> tuple[int, bool] | None:
        result = None
        async with self._sessions() as session, session.begin():
            notification = await session.get(Notification, notification_id)
            if notification is None:
                return None
            notification.attempts += 1
            notification.last_error = type(error).__name__
            if notification.attempts >= self._max_attempts:
                notification.status = NotificationStatus.FAILED
                notification.next_retry_at = None
            else:
                delay = min(3600, 60 * (2 ** (notification.attempts - 1)))
                notification.next_retry_at = now + timedelta(seconds=delay)
            result = (
                notification.attempts,
                notification.status == NotificationStatus.FAILED,
            )
        return result


class DeliveryWorker:
    def __init__(self, service: DeliveryService, *, interval_seconds: float = 5.0) -> None:
        self._service = service
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="notification-delivery")

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self._service.deliver_once()
            except Exception as error:
                LOGGER.error(
                    "event=delivery_worker_failed error_type=%s",
                    type(error).__name__,
                )
            await asyncio.sleep(self._interval)
