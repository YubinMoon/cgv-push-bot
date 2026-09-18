from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    password: str = Field(max_length=1_024)


class SessionResponse(BaseModel):
    csrf_token: str


class MessageResponse(BaseModel):
    message: str


class OverviewResponse(BaseModel):
    bot_connected: bool
    active_subscriptions: int
    expired_subscriptions: int
    poll_errors: int
    pending_notifications: int
    sent_notifications: int
    failed_notifications: int


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    guild_id: str | None
    channel_id: str
    user_name: str | None
    guild_name: str | None
    channel_name: str | None
    theater_id: str
    theater_name: str
    show_date: date
    keyword: str
    status: str
    created_at: datetime
    expires_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    pending_count: int
    failed_count: int


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    subscription_id: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    next_retry_at: datetime | None
    movie_titles: list[str]
    user_id: str
    user_name: str | None
    guild_id: str | None
    guild_name: str | None
    channel_id: str
    channel_name: str | None
    theater_name: str
    show_date: date
    keyword: str


class SubscriptionDetail(SubscriptionResponse):
    movies: list[str]
    notifications: list[NotificationResponse]


class NotificationDetail(NotificationResponse):
    pass


class PageResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


__all__ = [
    "LoginRequest",
    "MessageResponse",
    "NotificationDetail",
    "NotificationResponse",
    "OverviewResponse",
    "PageResponse",
    "SessionResponse",
    "SubscriptionDetail",
    "SubscriptionResponse",
]
