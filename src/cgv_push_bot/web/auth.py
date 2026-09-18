from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest

SESSION_COOKIE = "cgv_dashboard_session"
SESSION_TTL = timedelta(hours=8)
MAX_SESSIONS = 1_024


@dataclass(frozen=True, slots=True)
class Session:
    csrf_token: str
    expires_at: datetime


class SessionStore:
    def __init__(
        self,
        password: str | None,
        *,
        ttl: timedelta = SESSION_TTL,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self._password = password if password and password.strip() else ""
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._password)

    def authenticate(
        self, password: str, *, now: datetime | None = None
    ) -> tuple[str, Session] | None:
        if not self.enabled or not _secure_equal(password, self._password):
            return None
        current = _utc(now or datetime.now(UTC))
        self._remove_expired(current)
        while len(self._sessions) >= self._max_sessions:
            oldest = min(self._sessions, key=lambda token: self._sessions[token].expires_at)
            del self._sessions[oldest]
        token = secrets.token_urlsafe(32)
        session = Session(
            csrf_token=secrets.token_urlsafe(32),
            expires_at=current + self._ttl,
        )
        self._sessions[token] = session
        return token, session

    def get(self, token: str | None, *, now: datetime | None = None) -> Session | None:
        if not self.enabled or not token:
            return None
        current = _utc(now or datetime.now(UTC))
        self._remove_expired(current)
        return self._sessions.get(token)

    def revoke(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def valid_csrf(self, session: Session, token: str | None) -> bool:
        return bool(token) and _secure_equal(session.csrf_token, token)

    def _remove_expired(self, now: datetime) -> None:
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            del self._sessions[token]


def _secure_equal(left: str, right: str) -> bool:
    try:
        return compare_digest(left.encode("utf-8"), right.encode("utf-8"))
    except UnicodeError:
        return False


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["MAX_SESSIONS", "SESSION_COOKIE", "SESSION_TTL", "Session", "SessionStore"]
