from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class TheaterChoice:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class SubscriptionSummary:
    id: str
    theater_name: str
    show_date: date
    keyword: str = ""
    channel_id: int | None = None
    status: str = "active"
    created_at: datetime | None = None
    guild_id: int | None = None
    last_success_at: datetime | None = None
    poll_failed: bool = False
    pending_notifications: int = 0
    failed_notifications: int = 0
