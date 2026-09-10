from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from cgv_push_bot.db import (
    Base,
    MonitorTargetRepository,
    Notification,
    NotificationRepository,
    SubscriptionMovieRepository,
    SubscriptionRepository,
    create_engine,
    create_session_factory,
)


async def _new_database(tmp_path: Path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'database.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, create_session_factory(engine)


@pytest.mark.asyncio
async def test_sqlite_pragmas_and_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.sqlite3"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")

    await asyncio.to_thread(command.upgrade, config, "head")

    connection = sqlite3.connect(database_path)
    try:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        connection.close()
    assert {"monitor_targets", "subscriptions", "subscription_movies", "notifications"} <= names

    engine = create_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.connect() as async_connection:
        foreign_keys = await async_connection.scalar(text("PRAGMA foreign_keys"))
        journal_mode = await async_connection.scalar(text("PRAGMA journal_mode"))
        assert foreign_keys == 1
        assert str(journal_mode).lower() == "wal"
    await engine.dispose()


@pytest.mark.asyncio
async def test_constraints_and_owned_crud(tmp_path: Path) -> None:
    engine, session_factory = await _new_database(tmp_path)
    try:
        async with session_factory() as session:
            targets = MonitorTargetRepository(session)
            target = await targets.get_or_create(
                theater_id="001",
                theater_name="강남",
                show_date=date(2030, 1, 1),
            )
            same_target = await targets.get_or_create(
                theater_id="001",
                theater_name="강남 CGV",
                show_date=date(2030, 1, 1),
            )
            assert target.id == same_target.id
            assert same_target.theater_name == "강남 CGV"

            subscriptions = SubscriptionRepository(session)
            first = await subscriptions.create(
                discord_user_id=100,
                guild_id=200,
                channel_id=300,
                target_id=target.id,
                keyword="  \uff21  ",
            )
            assert first.normalized_keyword == "a"
            assert await subscriptions.get_owned(first.id, 999) is None
            assert [row.id for row in await subscriptions.list_owned(100)] == [first.id]
            await session.commit()

        async with session_factory() as session:
            subscriptions = SubscriptionRepository(session)
            with pytest.raises(IntegrityError):
                await subscriptions.create(
                    discord_user_id="100",
                    guild_id="200",
                    channel_id="300",
                    target_id=target.id,
                    keyword="a",
                )
            await session.rollback()

            assert not await subscriptions.delete_owned(first.id, 999)
            assert await subscriptions.delete_owned(first.id, 100)
            await session.commit()

        async with session_factory() as session:
            assert await MonitorTargetRepository(session).get(target.id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_baseline_and_outbox_are_idempotent(tmp_path: Path) -> None:
    engine, session_factory = await _new_database(tmp_path)
    try:
        async with session_factory() as session:
            target = await MonitorTargetRepository(session).get_or_create(
                theater_id="001",
                theater_name="강남",
                show_date=date(2030, 1, 1),
            )
            subscription = await SubscriptionRepository(session).create(
                discord_user_id="100",
                channel_id="300",
                target_id=target.id,
            )
            movies = SubscriptionMovieRepository(session)
            await movies.insert_baseline(
                subscription.id,
                [("m1", "Movie 1"), ("m2", "Movie 2")],
            )
            assert await session.scalar(select(Notification.id)) is None
            await movies.add(subscription.id, "m3", "Movie 3")
            notification_repo = NotificationRepository(session)
            notification = await notification_repo.create_for_movies(subscription.id, ["m3"])
            assert notification is not None
            assert await notification_repo.create_for_movies(subscription.id, ["m3"]) is None
            pending = await notification_repo.get_pending()
            assert [item.id for item in pending] == [notification.id]
            await notification_repo.mark_failed(
                notification.id,
                "temporary failure",
                at=datetime.now(UTC),
            )
            assert await notification_repo.get_pending(now=datetime.now(UTC)) == []
            await session.commit()
    finally:
        await engine.dispose()
