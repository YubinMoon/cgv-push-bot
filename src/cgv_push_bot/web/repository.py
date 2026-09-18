from __future__ import annotations

from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionStatus,
)


class DashboardRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def overview(self) -> dict[str, int]:
        async with self._sessions() as session:
            values = await session.execute(
                select(
                    _count_query(Subscription, Subscription.status == SubscriptionStatus.ACTIVE),
                    _count_query(Subscription, Subscription.status == SubscriptionStatus.EXPIRED),
                    _count_query(MonitorTarget, MonitorTarget.last_error.is_not(None)),
                    _count_query(Notification, Notification.status == NotificationStatus.PENDING),
                    _count_query(Notification, Notification.status == NotificationStatus.SENT),
                    _count_query(Notification, Notification.status == NotificationStatus.FAILED),
                )
            )
            row = values.one()
        (
            active,
            expired,
            poll_errors,
            pending,
            sent,
            failed,
        ) = (int(value or 0) for value in row)
        return {
            "active_subscriptions": active,
            "expired_subscriptions": expired,
            "poll_errors": poll_errors,
            "pending_notifications": pending,
            "sent_notifications": sent,
            "failed_notifications": failed,
        }

    async def list_subscriptions(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        user_id: str | None = None,
        guild_id: str | None = None,
        channel_id: str | None = None,
        theater_id: str | None = None,
        show_date: date | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Subscription], int]:
        conditions = _subscription_conditions(
            status=status,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            theater_id=theater_id,
            show_date=show_date,
            keyword=keyword,
        )
        statement = (
            select(Subscription)
            .join(Subscription.target)
            .options(joinedload(Subscription.target), selectinload(Subscription.notifications))
            .where(*conditions)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
        )
        return await self._paged(statement, page, page_size)

    async def get_subscription(self, subscription_id: int) -> Subscription | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(Subscription)
                .where(Subscription.id == subscription_id)
                .options(
                    joinedload(Subscription.target),
                    selectinload(Subscription.movies),
                    selectinload(Subscription.notifications).selectinload(Notification.movies),
                )
            )
            return result.scalar_one_or_none()

    async def list_notifications(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        subscription_id: int | None = None,
    ) -> tuple[list[Notification], int]:
        conditions: list[ColumnElement[bool]] = []
        if status is not None:
            conditions.append(Notification.status == status)
        if subscription_id is not None:
            conditions.append(Notification.subscription_id == subscription_id)
        statement = (
            select(Notification)
            .options(
                joinedload(Notification.subscription).joinedload(Subscription.target),
                selectinload(Notification.movies),
            )
            .where(*conditions)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
        )
        return await self._paged(statement, page, page_size)

    async def get_notification(self, notification_id: int) -> Notification | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(Notification)
                .where(Notification.id == notification_id)
                .options(
                    joinedload(Notification.subscription).joinedload(Subscription.target),
                    selectinload(Notification.movies),
                )
            )
            return result.scalar_one_or_none()

    async def _paged[T](
        self,
        statement: Select[tuple[T]],
        page: int,
        page_size: int,
    ) -> tuple[list[T], int]:
        async with self._sessions() as session:
            total = int(
                await session.scalar(
                    select(func.count()).select_from(statement.order_by(None).subquery())
                )
                or 0
            )
            result = await session.execute(
                statement.offset((page - 1) * page_size).limit(page_size)
            )
            return list(result.scalars().unique()), total


def _subscription_conditions(
    *,
    status: str | None,
    user_id: str | None,
    guild_id: str | None,
    channel_id: str | None,
    theater_id: str | None,
    show_date: date | None,
    keyword: str | None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if status is not None:
        conditions.append(Subscription.status == status)
    if user_id is not None:
        conditions.append(Subscription.discord_user_id == user_id)
    if guild_id is not None:
        conditions.append(Subscription.guild_id == guild_id)
    if channel_id is not None:
        conditions.append(Subscription.channel_id == channel_id)
    if theater_id is not None:
        conditions.append(MonitorTarget.theater_id == theater_id)
    if show_date is not None:
        conditions.append(MonitorTarget.show_date == show_date)
    if keyword is not None:
        conditions.append(Subscription.keyword.ilike(f"%{keyword}%"))
    return conditions


def _count_query(model: type[Base], condition: ColumnElement[bool]) -> ScalarSelect[int]:
    return select(func.count()).select_from(model).where(condition).scalar_subquery()


__all__ = ["DashboardRepository"]
