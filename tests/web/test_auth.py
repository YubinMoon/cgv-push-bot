from datetime import UTC, datetime, timedelta

from cgv_push_bot.web.auth import SessionStore


def test_store_supports_unicode_passwords_and_csrf_tokens() -> None:
    store = SessionStore("비밀 🔐")
    result = store.authenticate("비밀 🔐")

    assert result is not None
    token, session = result
    assert store.get(token) == session
    assert store.valid_csrf(session, session.csrf_token)
    assert not store.valid_csrf(session, session.csrf_token + "x")


def test_store_expires_sessions_and_evicts_oldest() -> None:
    start = datetime(2026, 9, 18, tzinfo=UTC)
    store = SessionStore("secret", ttl=timedelta(seconds=10), max_sessions=1)
    first = store.authenticate("secret", now=start)
    second = store.authenticate("secret", now=start + timedelta(seconds=1))

    assert first is not None and second is not None
    assert store.get(first[0], now=start + timedelta(seconds=1)) is None
    assert store.get(second[0], now=start + timedelta(seconds=11)) is None
