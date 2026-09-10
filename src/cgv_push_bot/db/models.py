from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Final

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


def _enum_values(enum_type: Any) -> list[str]:
    return [str(member.value) for member in enum_type]


_SUBSCRIPTION_STATUS: Final[SqlEnum] = SqlEnum(
    SubscriptionStatus,
    name="subscription_status",
    native_enum=False,
    values_callable=_enum_values,
)
_NOTIFICATION_STATUS: Final[SqlEnum] = SqlEnum(
    NotificationStatus,
    name="notification_status",
    native_enum=False,
    values_callable=_enum_values,
)


class MonitorTarget(Base):
    __tablename__ = "monitor_targets"
    __table_args__ = (
        UniqueConstraint("theater_id", "show_date", name="uq_monitor_targets_theater_date"),
        Index("ix_monitor_targets_next_poll_at", "next_poll_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    theater_id: Mapped[str] = mapped_column(String(64), nullable=False)
    theater_name: Mapped[str] = mapped_column(String(255), nullable=False)
    show_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "discord_user_id",
            "channel_id",
            "target_id",
            "normalized_keyword",
            name="uq_subscriptions_owner_channel_target_keyword",
        ),
        Index("ix_subscriptions_user_status", "discord_user_id", "status"),
        Index("ix_subscriptions_target_status", "target_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # A NULL guild_id represents a subscription created in a DM.
    guild_id: Mapped[str | None] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("monitor_targets.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    normalized_keyword: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[SubscriptionStatus] = mapped_column(
        _SUBSCRIPTION_STATUS,
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    target: Mapped[MonitorTarget] = relationship(back_populates="subscriptions")
    movies: Mapped[list[SubscriptionMovie]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def keyword_original(self) -> str:
        return self.keyword

    @property
    def keyword_normalized(self) -> str:
        return self.normalized_keyword


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_status_retry", "status", "next_retry_at"),
        Index("ix_notifications_subscription", "subscription_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        _NOTIFICATION_STATUS,
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    discord_message_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscription: Mapped[Subscription] = relationship(back_populates="notifications")
    movies: Mapped[list[SubscriptionMovie]] = relationship(back_populates="notification")

    @property
    def attempt_count(self) -> int:
        return self.attempts


class SubscriptionMovie(Base):
    __tablename__ = "subscription_movies"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "movie_id",
            name="uq_subscription_movies_subscription_movie",
        ),
        Index("ix_subscription_movies_notification", "notification_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[str] = mapped_column(String(64), nullable=False)
    movie_title: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL")
    )

    subscription: Mapped[Subscription] = relationship(back_populates="movies")
    notification: Mapped[Notification | None] = relationship(back_populates="movies")


__all__ = [
    "MonitorTarget",
    "Notification",
    "NotificationStatus",
    "Subscription",
    "SubscriptionMovie",
    "SubscriptionStatus",
    "utc_now",
]
