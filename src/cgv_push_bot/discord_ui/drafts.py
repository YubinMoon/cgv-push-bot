from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now_kst() -> datetime:
    return datetime.now(SEOUL)


def today_kst() -> date:
    return now_kst().date()


def normalize_keyword(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def parse_show_date(value: str, *, today: date | None = None) -> date:
    candidate = value.strip()
    if not _DATE_RE.fullmatch(candidate):
        raise ValueError("날짜는 YYYY-MM-DD 형식으로 입력해 주세요.")
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("올바른 날짜를 입력해 주세요.") from exc
    if parsed < (today if today is not None else today_kst()):
        raise ValueError("과거 날짜는 선택할 수 없습니다.")
    return parsed


def upcoming_dates(*, count: int = 14, today: date | None = None) -> tuple[date, ...]:
    if count < 1:
        raise ValueError("count must be positive")
    first = today if today is not None else today_kst()
    return tuple(first + timedelta(days=offset) for offset in range(count))


@dataclass(frozen=True, slots=True)
class RegistrationDraft:
    id: str
    owner_id: int
    guild_id: int | None
    channel_id: int
    created_at: datetime
    expires_at: datetime
    theater_id: str | None = None
    theater_name: str | None = None
    show_date: date | None = None
    keyword: str = ""
    normalized_keyword: str = ""

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)

    def owned_by(self, user_id: int) -> bool:
        return self.owner_id == user_id


class DraftStore:
    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self._ttl = ttl
        self._clock = clock or (lambda: datetime.now(UTC))
        self._drafts: dict[str, RegistrationDraft] = {}

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def create(
        self, *, draft_id: str, owner_id: int, guild_id: int | None, channel_id: int
    ) -> RegistrationDraft:
        self.purge_expired()
        now = self._utc_now()
        draft = RegistrationDraft(
            id=draft_id,
            owner_id=owner_id,
            guild_id=guild_id,
            channel_id=channel_id,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._drafts[draft_id] = draft
        return draft

    def get(self, draft_id: str, *, owner_id: int | None = None) -> RegistrationDraft | None:
        self.purge_expired()
        draft = self._drafts.get(draft_id)
        if draft is None or (owner_id is not None and not draft.owned_by(owner_id)):
            return None
        return draft

    def update(
        self,
        draft_id: str,
        *,
        owner_id: int,
        **changes: object,
    ) -> RegistrationDraft:
        draft = self.get(draft_id, owner_id=owner_id)
        if draft is None:
            raise KeyError("draft not found or expired")
        if "keyword" in changes:
            keyword = changes["keyword"]
            if not isinstance(keyword, str):
                raise TypeError("keyword must be a string")
            changes.setdefault("normalized_keyword", normalize_keyword(keyword))
        allowed = {
            "theater_id",
            "theater_name",
            "show_date",
            "keyword",
            "normalized_keyword",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown draft fields: {', '.join(sorted(unknown))}")
        updated = replace(draft, **changes)
        self._drafts[draft_id] = updated
        return updated

    def remove(self, draft_id: str, *, owner_id: int | None = None) -> None:
        draft = self._drafts.get(draft_id)
        if draft is None or (owner_id is not None and not draft.owned_by(owner_id)):
            return
        self._drafts.pop(draft_id, None)

    def purge_expired(self) -> int:
        now = self._utc_now()
        expired = [draft_id for draft_id, draft in self._drafts.items() if draft.expires_at <= now]
        for draft_id in expired:
            self._drafts.pop(draft_id, None)
        return len(expired)

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


__all__ = [
    "DraftStore",
    "RegistrationDraft",
    "normalize_keyword",
    "now_kst",
    "parse_show_date",
    "today_kst",
    "upcoming_dates",
]
