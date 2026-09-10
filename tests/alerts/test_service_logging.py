import logging
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from cgv_push_bot.alerts.service import MovieAlertService, SubscriptionNotFoundError
from cgv_push_bot.cgv import Movie, Theater
from cgv_push_bot.cgv.gateway import CgvGateway
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import MonitorTarget
from cgv_push_bot.db.session import create_engine, create_session_factory

LOGGER_NAME = "cgv_push_bot.alerts.service"
SHOW_DATE = date(2026, 8, 20)
NOW = datetime(2026, 8, 14, tzinfo=UTC)


class FakeGateway:
    def __init__(self, movies: tuple[Movie, ...] = ()) -> None:
        self.movies = movies
        self.search_error: Exception | None = None
        self.movies_error: Exception | None = None

    async def search_theaters(self, _query: str) -> tuple[Theater, ...]:
        if self.search_error is not None:
            raise self.search_error
        return (Theater("T1", "Theater", "R1"),)

    async def get_movies(self, _theater_id: str, _show_date: date) -> tuple[Movie, ...]:
        if self.movies_error is not None:
            raise self.movies_error
        return self.movies


async def make_service(
    gateway: FakeGateway,
) -> tuple[MovieAlertService, Any, Any]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    return MovieAlertService(sessions, cast(CgvGateway, gateway)), sessions, engine


@pytest.mark.asyncio
async def test_search_failures_log_only_safe_context(caplog: pytest.LogCaptureFixture) -> None:
    gateway = FakeGateway()
    service, _sessions, engine = await make_service(gateway)
    try:
        gateway.search_error = RuntimeError("raw query and user=123")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await service.search_theaters("secret query")
        message = caplog.records[-1].getMessage()
        assert "event=search_failed" in message
        assert "operation=theater_search" in message
        assert "error_type=RuntimeError" in message
        assert "secret query" not in message
        assert "raw query" not in message
        assert "123" not in message

        caplog.clear()
        gateway.movies_error = RuntimeError("raw movie response")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await service.list_current_movies(
                theater_id="T1", show_date=SHOW_DATE, keyword="secret keyword"
            )
        message = caplog.records[-1].getMessage()
        assert "operation=movie_search" in message
        assert "theater_id=T1" in message
        assert "show_date=2026-08-20" in message
        assert "error_type=RuntimeError" in message
        assert "raw movie response" not in message
        assert "secret keyword" not in message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_successful_searches_do_not_log(caplog: pytest.LogCaptureFixture) -> None:
    gateway = FakeGateway((Movie("m1", "Movie"),))
    service, _sessions, engine = await make_service(gateway)
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await service.search_theaters("Theater")
            await service.list_current_movies(theater_id="T1", show_date=SHOW_DATE, keyword="Movie")
        assert not caplog.records
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_lookup_failure_logs_safe_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway()
    gateway.movies_error = RuntimeError("raw registration response user=123")
    service, _sessions, engine = await make_service(gateway)
    try:
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME), pytest.raises(RuntimeError):
            await service.register_subscription(
                user_id=123,
                guild_id=456,
                channel_id=789,
                theater_id="T1",
                theater_name="Theater Name",
                show_date=SHOW_DATE,
                keyword="secret keyword",
            )
        message = caplog.records[-1].getMessage()
        assert "event=subscription_registration_failed stage=lookup" in message
        assert "theater_id=T1" in message
        assert "theater_name='Theater Name'" in message
        assert "show_date=2026-08-20" in message
        assert "error_type=RuntimeError" in message
        assert "raw registration response" not in message
        assert "secret keyword" not in message
        assert "user=123" not in message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_persistence_failure_logs_safe_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway()
    service, _sessions, engine = await make_service(gateway)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    try:
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME), pytest.raises(OperationalError):
            await service.register_subscription(
                user_id=123,
                guild_id=456,
                channel_id=789,
                theater_id="T1",
                theater_name="Theater Name",
                show_date=SHOW_DATE,
                keyword="secret keyword",
            )
        message = caplog.records[-1].getMessage()
        assert "event=subscription_registration_failed stage=persist" in message
        assert "theater_id=T1" in message
        assert "theater_name='Theater Name'" in message
        assert "show_date=2026-08-20" in message
        assert "error_type=OperationalError" in message
        assert "secret keyword" not in message
        assert "123" not in message
        assert "456" not in message
        assert "789" not in message
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_and_deletion_log_after_successful_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway((Movie("m1", "Movie"),))
    service, _sessions, engine = await make_service(gateway)
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            summary = await service.register_subscription(
                user_id=123,
                guild_id=456,
                channel_id=789,
                theater_id="T1",
                theater_name="Theater",
                show_date=SHOW_DATE,
                keyword="Movie",
            )
        registration = caplog.records[-1].getMessage()
        assert "event=subscription_registered" in registration
        assert f"subscription_id={summary.id}" in registration
        assert "target_id=1" in registration
        assert "theater_id=T1" in registration
        assert "theater_name='Theater'" in registration
        assert "show_date=2026-08-20" in registration
        assert "baseline_count=1" in registration
        assert "123" not in registration
        assert "456" not in registration
        assert "789" not in registration

        caplog.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            await service.delete_subscription(user_id=123, subscription_id=summary.id)
        deletion = caplog.records[-1].getMessage()
        assert "event=subscription_deleted" in deletion
        assert f"subscription_id={summary.id}" in deletion
        assert "target_id=1" in deletion
        assert "target_removed=True" in deletion

        caplog.clear()
        with (
            caplog.at_level(logging.INFO, logger=LOGGER_NAME),
            pytest.raises(SubscriptionNotFoundError),
        ):
            await service.delete_subscription(user_id=123, subscription_id="not-an-id")
        assert not caplog.records
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_logging_supports_expire_on_commit_sessions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway()
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=True)
    service = MovieAlertService(sessions, cast(CgvGateway, gateway))
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            summary = await service.register_subscription(
                user_id=123,
                guild_id=456,
                channel_id=789,
                theater_id="T1",
                theater_name="Theater",
                show_date=SHOW_DATE,
                keyword="",
            )
        assert summary.id == "1"
        assert "event=subscription_registered subscription_id=1 target_id=1" in caplog.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_expiration_logs_only_when_subscriptions_expire(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway()
    service, _sessions, engine = await make_service(gateway)
    try:
        await service.register_subscription(
            user_id=123,
            guild_id=456,
            channel_id=789,
            theater_id="T1",
            theater_name="Theater",
            show_date=SHOW_DATE,
            keyword="secret keyword",
        )
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert (
                await service.expire_subscriptions(now=datetime(2026, 8, 20, 22, tzinfo=UTC)) == 1
            )
        assert caplog.records[-1].getMessage() == "event=subscriptions_expired count=1"

        caplog.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert (
                await service.expire_subscriptions(now=datetime(2026, 8, 20, 23, tzinfo=UTC)) == 0
            )
        assert not caplog.records
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_poll_failure_logs_once_and_recovery_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway((Movie("m1", "Movie"),))
    service, sessions, engine = await make_service(gateway)
    try:
        await service.register_subscription(
            user_id=1,
            guild_id=None,
            channel_id=2,
            theater_id="T1",
            theater_name="Theater",
            show_date=SHOW_DATE,
            keyword="",
        )
        gateway.movies_error = RuntimeError("raw poll failure")
        async with sessions() as session, session.begin():
            await session.execute(update(MonitorTarget).values(next_poll_at=None))

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert await service.poll_once(now=NOW) == 0
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 1
        warning = warnings[0].getMessage()
        assert "event=poll_failed" in warning
        assert "target_id=1" in warning
        assert "theater_id=T1" in warning
        assert "theater_name='Theater'" in warning
        assert "show_date=2026-08-20" in warning
        assert "error_type=RuntimeError" in warning
        assert "raw poll failure" not in warning
        assert "next_poll_at=" in warning
        async with sessions() as session:
            target = await session.get(MonitorTarget, 1)
        assert target is not None
        assert target.last_error == "RuntimeError"
        assert "raw poll failure" not in target.last_error

        caplog.clear()
        async with sessions() as session, session.begin():
            await session.execute(update(MonitorTarget).values(next_poll_at=None))
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert await service.poll_once(now=NOW) == 0
        assert not caplog.records

        gateway.movies_error = None
        caplog.clear()
        async with sessions() as session, session.begin():
            await session.execute(update(MonitorTarget).values(next_poll_at=None))
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await service.poll_once(now=NOW) == 0
        recovery = [record for record in caplog.records if record.levelno == logging.INFO]
        assert len(recovery) == 1
        assert "event=poll_recovered" in recovery[0].getMessage()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_notification_log_is_committed_and_excludes_movie_title(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = FakeGateway((Movie("old", "Baseline"),))
    service, sessions, engine = await make_service(gateway)
    try:
        await service.register_subscription(
            user_id=1,
            guild_id=None,
            channel_id=2,
            theater_id="T1",
            theater_name="Theater",
            show_date=SHOW_DATE,
            keyword="New",
        )
        gateway.movies = (Movie("old", "Baseline"), Movie("new", "Secret New Title"))
        async with sessions() as session, session.begin():
            await session.execute(update(MonitorTarget).values(next_poll_at=None))
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            assert await service.poll_once(now=NOW) == 1
        notification = [
            record
            for record in caplog.records
            if "event=notification_created" in record.getMessage()
        ]
        assert len(notification) == 1
        message = notification[0].getMessage()
        assert "notification_id=1" in message
        assert "subscription_id=1" in message
        assert "target_id=1" in message
        assert "theater_id=T1" in message
        assert "theater_name='Theater'" in message
        assert "show_date=2026-08-20" in message
        assert "match_count=1" in message
        assert "Secret New Title" not in message
    finally:
        await engine.dispose()
