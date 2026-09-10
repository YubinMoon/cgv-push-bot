"""Repositories flush without committing so callers can compose atomic workflows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any, cast
from unicodedata import normalize

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import Select

from .models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionMovie,
    SubscriptionStatus,
    utc_now,
)

type MovieInput = object


def normalize_keyword(keyword: str | None) -> str:
    if not keyword:
        return ""
    return normalize("NFKC", keyword.strip()).casefold()


class MonitorTargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, target_id: int) -> MonitorTarget | None:
        return await self.session.get(MonitorTarget, target_id)

    async def get_by_theater_date(
        self,
        theater_id: str,
        show_date: date,
    ) -> MonitorTarget | None:
        result = await self.session.execute(
            select(MonitorTarget).where(
                MonitorTarget.theater_id == theater_id,
                MonitorTarget.show_date == show_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        *,
        theater_id: str,
        theater_name: str,
        show_date: date,
        next_poll_at: datetime | None = None,
    ) -> MonitorTarget:
        target = await self.get_by_theater_date(theater_id, show_date)
        if target is not None:
            if theater_name and target.theater_name != theater_name:
                target.theater_name = theater_name
            if next_poll_at is not None:
                target.next_poll_at = next_poll_at
            await self.session.flush()
            return target

        target = MonitorTarget(
            theater_id=theater_id,
            theater_name=theater_name,
            show_date=show_date,
            next_poll_at=next_poll_at or utc_now(),
        )
        self.session.add(target)
        try:
            await self.session.flush()
        except IntegrityError:
            # A caller that races another registration can recover by looking
            # up the row after its surrounding transaction handles the error.
            # We intentionally do not swallow the exception: the transaction
            # must use a savepoint to remain usable after a failed flush.
            raise
        return target

    async def get_or_create_target(self, **kwargs: Any) -> MonitorTarget:
        return await self.get_or_create(**kwargs)

    async def list_due(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[MonitorTarget]:
        current = now or utc_now()
        statement = (
            select(MonitorTarget)
            .where(
                MonitorTarget.next_poll_at.is_not(None),
                MonitorTarget.next_poll_at <= current,
            )
            .order_by(MonitorTarget.next_poll_at, MonitorTarget.id)
        )
        if limit is not None:
            if limit < 1:
                return []
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def get_due_targets(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[MonitorTarget]:
        return await self.list_due(now=now, limit=limit)

    async def mark_success(
        self,
        target_id: int,
        *,
        at: datetime | None = None,
        next_poll_at: datetime | None = None,
    ) -> MonitorTarget | None:
        target = await self.get(target_id)
        if target is None:
            return None
        target.last_success_at = at or utc_now()
        target.last_error = None
        target.error_at = None
        if next_poll_at is not None:
            target.next_poll_at = next_poll_at
        await self.session.flush()
        return target

    async def mark_error(
        self,
        target_id: int,
        error: str,
        *,
        at: datetime | None = None,
        next_poll_at: datetime | None = None,
    ) -> MonitorTarget | None:
        target = await self.get(target_id)
        if target is None:
            return None
        target.last_error = error[:2_000]
        target.error_at = at or utc_now()
        if next_poll_at is not None:
            target.next_poll_at = next_poll_at
        await self.session.flush()
        return target

    async def delete_if_unused(self, target_id: int) -> bool:
        target = await self.get(target_id)
        if target is None:
            return False
        subscription_count = await self.session.scalar(
            select(func.count(Subscription.id)).where(Subscription.target_id == target_id)
        )
        if subscription_count:
            return False
        await self.session.delete(target)
        await self.session.flush()
        return True

    async def delete_if_no_subscriptions(self, target_id: int) -> bool:
        return await self.delete_if_unused(target_id)


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, subscription_id: int) -> Subscription | None:
        return await self.session.get(Subscription, subscription_id)

    async def create(
        self,
        *,
        discord_user_id: str | int | None = None,
        user_id: str | int | None = None,
        guild_id: str | int | None = None,
        channel_id: str | int,
        target_id: int | None = None,
        target: MonitorTarget | None = None,
        keyword: str | None = None,
        keyword_original: str | None = None,
        expires_at: datetime | None = None,
        created_at: datetime | None = None,
        status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    ) -> Subscription:
        owner = discord_user_id if discord_user_id is not None else user_id
        if owner is None:
            raise ValueError("discord_user_id is required")
        if target_id is None and target is None:
            raise ValueError("target_id or target is required")
        if target_id is None and target is not None:
            await self.session.flush()
            target_id = target.id
        assert target_id is not None
        original = keyword if keyword is not None else keyword_original
        original = original or ""
        subscription = Subscription(
            discord_user_id=str(owner),
            guild_id=None if guild_id is None else str(guild_id),
            channel_id=str(channel_id),
            target_id=target_id,
            keyword=original.strip(),
            normalized_keyword=normalize_keyword(original),
            status=status,
            created_at=created_at or utc_now(),
            expires_at=expires_at,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def create_subscription(self, **kwargs: Any) -> Subscription:
        return await self.create(**kwargs)

    async def list_owned(
        self,
        discord_user_id: str | int,
        *,
        include_expired: bool = False,
    ) -> list[Subscription]:
        conditions = [Subscription.discord_user_id == str(discord_user_id)]
        if not include_expired:
            conditions.append(Subscription.status == SubscriptionStatus.ACTIVE)
        result = await self.session.execute(
            select(Subscription)
            .where(*conditions)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        )
        return list(result.scalars())

    async def list_for_user(
        self,
        discord_user_id: str | int,
        *,
        include_expired: bool = False,
    ) -> list[Subscription]:
        return await self.list_owned(discord_user_id, include_expired=include_expired)

    async def get_owned(
        self,
        subscription_id: int,
        discord_user_id: str | int,
    ) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.id == subscription_id,
                Subscription.discord_user_id == str(discord_user_id),
            )
        )
        return result.scalar_one_or_none()

    async def get_owned_subscription(
        self,
        subscription_id: int,
        discord_user_id: str | int,
    ) -> Subscription | None:
        return await self.get_owned(subscription_id, discord_user_id)

    async def delete_owned(
        self,
        subscription_id: int,
        discord_user_id: str | int,
    ) -> bool:
        subscription = await self.get_owned(subscription_id, discord_user_id)
        if subscription is None:
            return False
        target_id = subscription.target_id
        await self.session.delete(subscription)
        await self.session.flush()
        await MonitorTargetRepository(self.session).delete_if_unused(target_id)
        return True

    async def delete(self, subscription_id: int, discord_user_id: str | int) -> bool:
        return await self.delete_owned(subscription_id, discord_user_id)

    async def expire_due(self, *, now: datetime | None = None) -> int:
        current = now or utc_now()
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(Subscription)
                .where(
                    Subscription.status == SubscriptionStatus.ACTIVE,
                    Subscription.expires_at.is_not(None),
                    Subscription.expires_at <= current,
                )
                .values(status=SubscriptionStatus.EXPIRED)
            ),
        )
        await self.session.flush()
        return int(result.rowcount or 0)


class SubscriptionMovieRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, subscription_id: int, movie_id: str) -> SubscriptionMovie | None:
        result = await self.session.execute(
            select(SubscriptionMovie).where(
                SubscriptionMovie.subscription_id == subscription_id,
                SubscriptionMovie.movie_id == movie_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_subscription(self, subscription_id: int) -> list[SubscriptionMovie]:
        result = await self.session.execute(
            select(SubscriptionMovie)
            .where(SubscriptionMovie.subscription_id == subscription_id)
            .order_by(SubscriptionMovie.first_seen_at, SubscriptionMovie.id)
        )
        return list(result.scalars())

    async def add(
        self,
        subscription_id: int,
        movie_id: str,
        movie_title: str,
        *,
        is_baseline: bool = False,
        first_seen_at: datetime | None = None,
    ) -> SubscriptionMovie:
        existing = await self.get(subscription_id, movie_id)
        if existing is not None:
            if is_baseline and not existing.is_baseline:
                existing.is_baseline = True
                await self.session.flush()
            return existing
        movie = SubscriptionMovie(
            subscription_id=subscription_id,
            movie_id=movie_id,
            movie_title=movie_title,
            is_baseline=is_baseline,
            first_seen_at=first_seen_at or utc_now(),
        )
        self.session.add(movie)
        await self.session.flush()
        return movie

    async def insert_baseline(
        self,
        subscription_id: int,
        movies: Iterable[MovieInput],
        *,
        first_seen_at: datetime | None = None,
    ) -> list[SubscriptionMovie]:
        result: list[SubscriptionMovie] = []
        for movie_id, title in (_movie_values(movie) for movie in movies):
            result.append(
                await self.add(
                    subscription_id,
                    movie_id,
                    title,
                    is_baseline=True,
                    first_seen_at=first_seen_at,
                )
            )
        return result

    async def add_baseline(
        self,
        subscription_id: int,
        movies: Iterable[MovieInput],
        *,
        first_seen_at: datetime | None = None,
    ) -> list[SubscriptionMovie]:
        return await self.insert_baseline(
            subscription_id,
            movies,
            first_seen_at=first_seen_at,
        )

    async def mark_notification(
        self,
        subscription_id: int,
        movie_ids: Iterable[str],
        notification_id: int,
    ) -> int:
        ids = tuple(dict.fromkeys(movie_ids))
        if not ids:
            return 0
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(SubscriptionMovie)
                .where(
                    SubscriptionMovie.subscription_id == subscription_id,
                    SubscriptionMovie.movie_id.in_(ids),
                    SubscriptionMovie.notification_id.is_(None),
                )
                .values(notification_id=notification_id)
            ),
        )
        await self.session.flush()
        return int(result.rowcount or 0)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, notification_id: int) -> Notification | None:
        return await self.session.get(Notification, notification_id)

    async def create(
        self,
        subscription_id: int,
        *,
        movie_ids: Iterable[str] = (),
        created_at: datetime | None = None,
    ) -> Notification | None:
        """Create one outbox row and link each not-yet-notified movie.

        If every supplied movie is already linked to an outbox row, ``None``
        is returned.  This makes retries and poller replays idempotent without
        requiring a second application-level lock.
        """

        ids = tuple(dict.fromkeys(movie_ids))
        if ids:
            rows = list(
                (
                    await self.session.execute(
                        select(SubscriptionMovie).where(
                            SubscriptionMovie.subscription_id == subscription_id,
                            SubscriptionMovie.movie_id.in_(ids),
                        )
                    )
                ).scalars()
            )
            unlinked = [row for row in rows if row.notification_id is None]
            if not unlinked:
                return None
        else:
            unlinked = []

        notification = Notification(
            subscription_id=subscription_id,
            status=NotificationStatus.PENDING,
            attempts=0,
            created_at=created_at or utc_now(),
        )
        self.session.add(notification)
        await self.session.flush()
        for movie in unlinked:
            movie.notification_id = notification.id
        await self.session.flush()
        return notification

    async def create_for_movies(
        self,
        subscription_id: int,
        movie_ids: Iterable[str],
        *,
        created_at: datetime | None = None,
    ) -> Notification | None:
        return await self.create(subscription_id, movie_ids=movie_ids, created_at=created_at)

    async def get_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[Notification]:
        current = now or utc_now()
        statement = (
            select(Notification)
            .where(
                or_(
                    Notification.status == NotificationStatus.PENDING,
                    and_(
                        Notification.status == NotificationStatus.FAILED,
                        or_(
                            Notification.next_retry_at.is_(None),
                            Notification.next_retry_at <= current,
                        ),
                    ),
                )
            )
            .order_by(Notification.created_at, Notification.id)
        )
        if limit is not None:
            if limit < 1:
                return []
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def list_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> list[Notification]:
        return await self.get_pending(now=now, limit=limit)

    async def list_deliverable_ids(
        self,
        *,
        now: datetime,
        limit: int | None = None,
    ) -> list[int]:
        if limit is not None and limit < 1:
            return []
        statement = self._deliverable_statement(now=now).with_only_columns(Notification.id)
        statement = statement.order_by(Notification.created_at, Notification.id)
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars())

    async def get_deliverable(
        self,
        notification_id: int,
        *,
        now: datetime,
    ) -> Notification | None:
        statement = self._deliverable_statement(now=now).where(Notification.id == notification_id)
        statement = statement.options(
            joinedload(Notification.subscription).joinedload(Subscription.target),
            selectinload(Notification.movies),
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    def _deliverable_statement(*, now: datetime) -> Select[tuple[Notification]]:
        return (
            select(Notification)
            .join(Notification.subscription)
            .where(
                Notification.status == NotificationStatus.PENDING,
                Subscription.status == SubscriptionStatus.ACTIVE,
                (Subscription.expires_at.is_(None)) | (Subscription.expires_at > now),
                (Notification.next_retry_at.is_(None)) | (Notification.next_retry_at <= now),
            )
        )

    async def mark_sent(
        self,
        notification_id: int,
        *,
        discord_message_id: str | int,
        sent_at: datetime | None = None,
    ) -> Notification | None:
        notification = await self.get(notification_id)
        if notification is None:
            return None
        notification.status = NotificationStatus.SENT
        notification.discord_message_id = str(discord_message_id)
        notification.sent_at = sent_at or utc_now()
        notification.next_retry_at = None
        notification.last_error = None
        await self.session.flush()
        return notification

    async def mark_failed(
        self,
        notification_id: int,
        error: str,
        *,
        next_retry_at: datetime | None = None,
        at: datetime | None = None,
        base_delay: float = 30.0,
        max_delay: float = 3_600.0,
    ) -> Notification | None:
        notification = await self.get(notification_id)
        if notification is None:
            return None
        notification.attempts += 1
        notification.status = NotificationStatus.FAILED
        notification.last_error = error[:2_000]
        if next_retry_at is None:
            delay = min(max_delay, base_delay * 2 ** max(notification.attempts - 1, 0))
            next_retry_at = (at or utc_now()) + timedelta(seconds=delay)
        notification.next_retry_at = next_retry_at
        await self.session.flush()
        return notification


def _movie_values(value: MovieInput) -> tuple[str, str]:
    """Extract ``(movie_id, title)`` without coupling DB to CGV models."""

    if isinstance(value, str):
        return value, value
    if isinstance(value, Mapping):
        item = cast(Mapping[Any, Any], value)
        movie_id: object = item.get("id") or item.get("movie_id")
        title: object = item.get("title") or item.get("movie_title")
        if isinstance(movie_id, str) and isinstance(title, str):
            return movie_id, title
    if isinstance(value, tuple):
        tuple_value = cast(tuple[object, ...], value)
        if len(tuple_value) != 2:
            raise TypeError("movie must provide string id and title")
        movie_id, title = tuple_value
        if isinstance(movie_id, str) and isinstance(title, str):
            return movie_id, title
    raw_value = cast(object, value)
    movie_id: object = getattr(raw_value, "id", None)
    title: object = getattr(raw_value, "title", None)
    if isinstance(movie_id, str) and isinstance(title, str):
        return movie_id, title
    raise TypeError("movie must provide string id and title")


__all__ = [
    "MonitorTargetRepository",
    "NotificationRepository",
    "SubscriptionMovieRepository",
    "SubscriptionRepository",
    "normalize_keyword",
]
