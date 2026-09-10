from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from .models import SubscriptionSummary, TheaterChoice


class AlertService(Protocol):
    async def search_theaters(self, query: str) -> Sequence[TheaterChoice]: ...

    async def list_current_movies(
        self, *, theater_id: str, show_date: date, keyword: str
    ) -> Sequence[str]: ...

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
    ) -> SubscriptionSummary: ...

    async def list_subscriptions(self, user_id: int) -> Sequence[SubscriptionSummary]: ...

    async def delete_subscription(self, *, user_id: int, subscription_id: str) -> None: ...


class NotificationSender(Protocol):
    async def send(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        channel_id: int,
        theater_name: str,
        show_date: date,
        keyword: str,
        movie_titles: tuple[str, ...],
        discovered_at: datetime | None = None,
    ) -> str: ...
