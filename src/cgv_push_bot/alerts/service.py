from __future__ import annotations

import logging
from asyncio import Lock, sleep
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from cgv_push_bot.cgv.gateway import CgvGateway
from cgv_push_bot.cgv.models import Movie
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionMovie,
    SubscriptionStatus,
)
from cgv_push_bot.db.repositories import MonitorTargetRepository, SubscriptionRepository

from .matching import normalize_keyword, title_matches
from .models import SubscriptionSummary, TheaterChoice
from .scheduling import next_poll_slot

SEOUL = ZoneInfo("Asia/Seoul")
LOGGER = logging.getLogger(__name__)
POLL_TARGET_SPACING_SECONDS = 0.5


class DuplicateSubscriptionError(ValueError):
    pass


class SubscriptionNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class _CreatedNotification:
    notification_id: int
    subscription_id: int
    movie_count: int


class MovieAlertService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: CgvGateway,
        *,
        poll_interval_seconds: int = 300,
        poll_offset_seconds: int = 1,
        history_retention_days: int = 90,
        subscription_lock: Lock | None = None,
    ) -> None:
        if not 0 <= history_retention_days <= 36_500:
            raise ValueError("history_retention_days must be between 0 and 36500")
        self._history_retention_days = history_retention_days
        self._sessions = session_factory
        self._gateway = gateway
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_offset_seconds = poll_offset_seconds
        self._subscription_lock = subscription_lock or Lock()

    async def search_theaters(self, query: str) -> tuple[TheaterChoice, ...]:
        try:
            theaters = await self._gateway.search_theaters(query)
        except Exception as error:
            LOGGER.warning(
                "event=search_failed operation=theater_search error_type=%s",
                type(error).__name__,
            )
            raise
        return tuple(TheaterChoice(item.id, item.name) for item in theaters)

    async def list_current_movies(
        self, *, theater_id: str, show_date: date, keyword: str
    ) -> tuple[str, ...]:
        try:
            movies = await self._gateway.get_movies(theater_id, show_date)
        except Exception as error:
            LOGGER.warning(
                "event=search_failed operation=movie_search theater_id=%s show_date=%s "
                "error_type=%s",
                theater_id,
                show_date.isoformat(),
                type(error).__name__,
            )
            raise
        normalized = normalize_keyword(keyword) or None
        return tuple(
            dict.fromkeys(movie.title for movie in movies if title_matches(movie.title, normalized))
        )

    async def register_subscription(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        channel_id: int,
        theater_id: str,
        theater_name: str,
        show_date: date,
        keyword: str,
    ) -> SubscriptionSummary:
        # Query CGV before opening a transaction. Failure must not save an empty baseline.
        try:
            movies = await self._gateway.get_movies(theater_id, show_date)
        except Exception as error:
            LOGGER.warning(
                "event=subscription_registration_failed stage=lookup "
                "theater_id=%s theater_name=%r show_date=%s error_type=%s",
                theater_id,
                theater_name,
                show_date.isoformat(),
                type(error).__name__,
            )
            raise
        normalized = normalize_keyword(keyword) or ""
        expires_at = expiration_for(show_date)
        try:
            async with self._sessions() as session, session.begin():
                target = await session.scalar(
                    select(MonitorTarget).where(
                        MonitorTarget.theater_id == theater_id,
                        MonitorTarget.show_date == show_date,
                    )
                )
                if target is None:
                    target = MonitorTarget(
                        theater_id=theater_id,
                        theater_name=theater_name,
                        show_date=show_date,
                        next_poll_at=self._next_poll_at(datetime.now(UTC)),
                    )
                    session.add(target)
                    await session.flush()
                duplicate = await session.scalar(
                    select(Subscription).where(
                        Subscription.discord_user_id == str(user_id),
                        Subscription.channel_id == str(channel_id),
                        Subscription.target_id == target.id,
                        Subscription.normalized_keyword == normalized,
                    )
                )
                if duplicate is not None:
                    if duplicate.status == SubscriptionStatus.ACTIVE:
                        raise DuplicateSubscriptionError("동일한 알림이 이미 등록되어 있습니다.")
                    await session.delete(duplicate)
                    await session.flush()
                subscription = Subscription(
                    discord_user_id=str(user_id),
                    guild_id=None if guild_id is None else str(guild_id),
                    channel_id=str(channel_id),
                    target_id=target.id,
                    keyword=keyword.strip(),
                    normalized_keyword=normalized,
                    expires_at=expires_at,
                )
                session.add(subscription)
                await session.flush()
                session.add_all(
                    SubscriptionMovie(
                        subscription_id=subscription.id,
                        movie_id=movie.id,
                        movie_title=movie.title,
                        is_baseline=True,
                    )
                    for movie in movies
                )
                result = _subscription_summary(subscription, target)
                subscription_id = subscription.id
                target_id = target.id
        except DuplicateSubscriptionError:
            raise
        except Exception as error:
            LOGGER.error(
                "event=subscription_registration_failed stage=persist "
                "theater_id=%s theater_name=%r show_date=%s error_type=%s",
                theater_id,
                theater_name,
                show_date.isoformat(),
                type(error).__name__,
            )
            raise
        LOGGER.info(
            "event=subscription_registered subscription_id=%s target_id=%s theater_id=%s "
            "theater_name=%r show_date=%s baseline_count=%s",
            subscription_id,
            target_id,
            theater_id,
            theater_name,
            show_date.isoformat(),
            len(movies),
        )
        return result

    async def list_subscriptions(self, user_id: int) -> tuple[SubscriptionSummary, ...]:
        pending_count = (
            select(func.count(Notification.id))
            .where(
                Notification.subscription_id == Subscription.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .correlate(Subscription)
            .scalar_subquery()
        )
        failed_count = (
            select(func.count(Notification.id))
            .where(
                Notification.subscription_id == Subscription.id,
                Notification.status == NotificationStatus.FAILED,
            )
            .correlate(Subscription)
            .scalar_subquery()
        )
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Subscription, MonitorTarget, pending_count, failed_count)
                    .join(MonitorTarget)
                    .where(
                        Subscription.discord_user_id == str(user_id),
                        Subscription.status == SubscriptionStatus.ACTIVE,
                    )
                    .order_by(Subscription.created_at.desc())
                )
            ).all()
        return tuple(
            _subscription_summary(
                subscription, target, pending_notifications=pending, failed_notifications=failed
            )
            for subscription, target, pending, failed in rows
        )

    async def delete_subscription(self, *, user_id: int, subscription_id: str) -> None:
        async with self._subscription_lock:
            await self._delete_subscription(user_id=user_id, subscription_id=subscription_id)

    async def _delete_subscription(self, *, user_id: int, subscription_id: str) -> None:
        try:
            identifier = int(subscription_id)
        except ValueError as error:
            raise SubscriptionNotFoundError("알림을 찾을 수 없습니다.") from error
        try:
            async with self._sessions() as session, session.begin():
                subscription = await SubscriptionRepository(session).get_owned(identifier, user_id)
                if subscription is None:
                    raise SubscriptionNotFoundError("알림을 찾을 수 없습니다.")
                target_id = subscription.target_id
                await session.delete(subscription)
                await session.flush()
                target_removed = await MonitorTargetRepository(session).delete_if_unused(target_id)
        except SubscriptionNotFoundError:
            raise
        except Exception as error:
            LOGGER.error(
                "event=subscription_delete_failed subscription_id=%s error_type=%s",
                identifier,
                type(error).__name__,
            )
            raise
        LOGGER.info(
            "event=subscription_deleted subscription_id=%s target_id=%s target_removed=%s",
            identifier,
            target_id,
            target_removed,
        )

    async def poll_once(self, *, now: datetime | None = None) -> int:
        current = _as_utc(now or datetime.now(UTC))
        await self.expire_subscriptions(now=current)
        await self.cleanup_history(now=current)
        async with self._sessions() as session:
            targets = tuple(
                (
                    await session.scalars(
                        select(MonitorTarget)
                        .join(Subscription)
                        .where(
                            Subscription.status == SubscriptionStatus.ACTIVE,
                            (MonitorTarget.next_poll_at.is_(None))
                            | (MonitorTarget.next_poll_at <= current),
                        )
                        .order_by(MonitorTarget.show_date, MonitorTarget.id)
                        .distinct()
                    )
                ).all()
            )
        created = 0
        next_poll_start: float | None = None
        for target in targets:
            if next_poll_start is not None:
                remaining = next_poll_start - monotonic()
                if remaining > 0:
                    await sleep(remaining)
            poll_start = monotonic()
            next_poll_start = poll_start + POLL_TARGET_SPACING_SECONDS
            try:
                movies = await self._gateway.get_movies(target.theater_id, target.show_date)
            except Exception as error:
                await self._record_poll_error(target.id, error, current)
                continue
            created += await self._record_movies(target.id, movies, current)
        return created

    async def expire_subscriptions(self, *, now: datetime | None = None) -> int:
        current = _as_utc(now or datetime.now(UTC))
        async with self._sessions() as session, session.begin():
            expired_count = await SubscriptionRepository(session).expire_due(now=current)
        if expired_count:
            LOGGER.info("event=subscriptions_expired count=%s", expired_count)
        return expired_count

    async def cleanup_history(self, *, now: datetime | None = None) -> int:
        if self._history_retention_days == 0:
            return 0
        cutoff = _as_utc(now or datetime.now(UTC)) - timedelta(days=self._history_retention_days)
        async with self._sessions() as session, session.begin():
            identifiers = tuple(
                await session.scalars(
                    select(Subscription.id)
                    .where(
                        Subscription.status == SubscriptionStatus.EXPIRED,
                        Subscription.expires_at <= cutoff,
                    )
                    .order_by(Subscription.expires_at, Subscription.id)
                    .limit(500)
                )
            )
            if identifiers:
                # Foreign-key cascades remove notifications and observed movies together.
                await session.execute(delete(Subscription).where(Subscription.id.in_(identifiers)))
            orphan_ids = tuple(
                await session.scalars(
                    select(MonitorTarget.id)
                    .where(
                        MonitorTarget.show_date < cutoff.date(),
                        ~MonitorTarget.subscriptions.any(),
                    )
                    .order_by(MonitorTarget.id)
                    .limit(500)
                )
            )
            if orphan_ids:
                await session.execute(delete(MonitorTarget).where(MonitorTarget.id.in_(orphan_ids)))
        if identifiers or orphan_ids:
            LOGGER.info(
                "event=history_cleaned subscriptions=%s targets=%s",
                len(identifiers),
                len(orphan_ids),
            )
        return len(identifiers)

    async def _record_poll_error(self, target_id: int, error: Exception, now: datetime) -> None:
        error_type = type(error).__name__
        next_poll_at = self._next_poll_at(now)
        async with self._sessions() as session, session.begin():
            target = await session.get(MonitorTarget, target_id)
            if target is None:
                return
            first_failure = target.last_error is None
            theater_id = target.theater_id
            theater_name = target.theater_name
            show_date = target.show_date
            target.last_error = error_type
            target.error_at = now
            target.next_poll_at = next_poll_at
        if first_failure:
            LOGGER.warning(
                "event=poll_failed target_id=%s theater_id=%s theater_name=%r show_date=%s "
                "error_type=%s next_poll_at=%s",
                target_id,
                theater_id,
                theater_name,
                show_date.isoformat(),
                error_type,
                next_poll_at.isoformat(),
            )

    async def _record_movies(self, target_id: int, movies: Iterable[Movie], now: datetime) -> int:
        current_movies = tuple(movies)
        created_notifications: list[_CreatedNotification] = []
        async with self._sessions() as session, session.begin():
            target = await session.scalar(
                select(MonitorTarget)
                .where(MonitorTarget.id == target_id)
                .options(selectinload(MonitorTarget.subscriptions))
            )
            if target is None:
                return 0
            recovered = target.last_error is not None
            theater_id = target.theater_id
            theater_name = target.theater_name
            show_date = target.show_date
            target.last_success_at = now
            target.last_error = None
            target.error_at = None
            target.next_poll_at = self._next_poll_at(now)

            for subscription in target.subscriptions:
                if subscription.status != SubscriptionStatus.ACTIVE:
                    continue
                created = await self._record_new_subscription_movies(
                    session, subscription, current_movies, now
                )
                if created is not None:
                    created_notifications.append(created)

        if recovered:
            LOGGER.info(
                "event=poll_recovered target_id=%s theater_id=%s theater_name=%r show_date=%s",
                target_id,
                theater_id,
                theater_name,
                show_date.isoformat(),
            )
        for created in created_notifications:
            LOGGER.info(
                "event=notification_created notification_id=%s subscription_id=%s target_id=%s "
                "theater_id=%s theater_name=%r show_date=%s match_count=%s",
                created.notification_id,
                created.subscription_id,
                target_id,
                theater_id,
                theater_name,
                show_date.isoformat(),
                created.movie_count,
            )
        return len(created_notifications)

    async def _record_new_subscription_movies(
        self,
        session: AsyncSession,
        subscription: Subscription,
        current_movies: tuple[Movie, ...],
        now: datetime,
    ) -> _CreatedNotification | None:
        seen_movie_ids = set(
            await session.scalars(
                select(SubscriptionMovie.movie_id).where(
                    SubscriptionMovie.subscription_id == subscription.id
                )
            )
        )
        new_movies = [movie for movie in current_movies if movie.id not in seen_movie_ids]
        matching_movie_ids = {
            movie.id
            for movie in new_movies
            if title_matches(movie.title, subscription.normalized_keyword or None)
        }
        notification = None
        if matching_movie_ids:
            notification = Notification(
                subscription_id=subscription.id,
                status=NotificationStatus.PENDING,
                next_retry_at=now,
            )
            session.add(notification)
            await session.flush()

        for movie in new_movies:
            notification_id = None
            if notification is not None and movie.id in matching_movie_ids:
                notification_id = notification.id
            session.add(
                SubscriptionMovie(
                    subscription_id=subscription.id,
                    movie_id=movie.id,
                    movie_title=movie.title,
                    is_baseline=False,
                    notification_id=notification_id,
                )
            )
        if notification is None:
            return None
        return _CreatedNotification(notification.id, subscription.id, len(matching_movie_ids))

    def _next_poll_at(self, now: datetime) -> datetime:
        return next_poll_slot(
            now,
            interval_seconds=self._poll_interval_seconds,
            offset_seconds=self._poll_offset_seconds,
        )


def expiration_for(show_date: date) -> datetime:
    return datetime.combine(show_date + timedelta(days=1), time(6), SEOUL).astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _subscription_summary(
    subscription: Subscription,
    target: MonitorTarget,
    *,
    pending_notifications: int = 0,
    failed_notifications: int = 0,
) -> SubscriptionSummary:
    return SubscriptionSummary(
        id=str(subscription.id),
        theater_name=target.theater_name,
        show_date=target.show_date,
        keyword=subscription.keyword,
        channel_id=int(subscription.channel_id),
        status=subscription.status.value,
        created_at=subscription.created_at,
        last_success_at=target.last_success_at,
        poll_failed=target.last_error is not None,
        pending_notifications=pending_notifications,
        failed_notifications=failed_notifications,
        guild_id=None if subscription.guild_id is None else int(subscription.guild_id),
    )
