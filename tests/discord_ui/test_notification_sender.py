from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cgv_push_bot.alerts.delivery import DeliveryService
from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import MonitorTarget, Notification, NotificationStatus, Subscription
from cgv_push_bot.db.session import create_engine, create_session_factory
from cgv_push_bot.discord_ui.notifications import DiscordNotificationSender


def _message() -> Mock:
    return Mock(id=1234)


def _sender_mocks() -> tuple[Mock, Mock, Mock]:
    client = Mock(spec=discord.Client)
    user = Mock(spec=discord.User)
    channel = Mock(spec=discord.DMChannel)
    cast(Any, user).create_dm = AsyncMock(return_value=channel)
    cast(Any, channel).send = AsyncMock(return_value=_message())
    return client, user, channel


async def _send_dm(sender: DiscordNotificationSender) -> str:
    return await sender.send(
        user_id=123,
        guild_id=None,
        channel_id=456,
        theater_name="CGV Yongsan",
        show_date=date(2026, 8, 20),
        keyword="dune",
        movie_titles=("Dune: Part Two",),
    )


@pytest.mark.asyncio
async def test_dm_uses_cached_user_and_creates_dm() -> None:
    client, user, channel = _sender_mocks()
    cast(Any, client).get_user.return_value = user
    cast(Any, client).fetch_user = AsyncMock()

    assert await _send_dm(DiscordNotificationSender(cast(discord.Client, client))) == "1234"

    cast(Any, client).get_user.assert_called_once_with(123)
    cast(Any, client).fetch_user.assert_not_awaited()
    cast(Any, user).create_dm.assert_awaited_once_with()
    cast(Any, channel).send.assert_awaited_once()
    assert cast(Any, channel).send.await_args.kwargs["content"] == "<@123>"


@pytest.mark.asyncio
async def test_dm_fetches_user_when_not_cached() -> None:
    client, user, channel = _sender_mocks()
    cast(Any, client).get_user.return_value = None
    cast(Any, client).fetch_user = AsyncMock(return_value=user)

    assert await _send_dm(DiscordNotificationSender(cast(discord.Client, client))) == "1234"

    cast(Any, client).get_user.assert_called_once_with(123)
    cast(Any, client).fetch_user.assert_awaited_once_with(123)
    cast(Any, user).create_dm.assert_awaited_once_with()
    cast(Any, channel).send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [True, False])
async def test_guild_uses_cached_or_fetched_channel(cached: bool) -> None:
    client, _user, _dm_channel = _sender_mocks()
    guild_channel = Mock(spec=discord.TextChannel)
    cast(Any, guild_channel).send = AsyncMock(return_value=_message())
    cast(Any, client).get_channel.return_value = guild_channel if cached else None
    cast(Any, client).fetch_channel = AsyncMock(return_value=guild_channel)

    sender = DiscordNotificationSender(cast(discord.Client, client))
    message_id = await sender.send(
        user_id=123,
        guild_id=789,
        channel_id=456,
        theater_name="CGV Yongsan",
        show_date=date(2026, 8, 20),
        keyword="dune",
        movie_titles=("Dune: Part Two",),
    )

    assert message_id == "1234"
    cast(Any, client).get_channel.assert_called_once_with(456)
    if cached:
        cast(Any, client).fetch_channel.assert_not_awaited()
    else:
        cast(Any, client).fetch_channel.assert_awaited_once_with(456)
    cast(Any, guild_channel).send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["create_dm", "send"])
async def test_dm_failure_is_recorded_for_delivery_retry(failure_stage: str) -> None:
    client, user, channel = _sender_mocks()
    cast(Any, client).get_user.return_value = user
    error = RuntimeError(f"DM {failure_stage} failed")
    if failure_stage == "create_dm":
        cast(Any, user).create_dm = AsyncMock(side_effect=error)
    else:
        cast(Any, channel).send = AsyncMock(side_effect=error)
    service, engine = await _delivery_service(
        DiscordNotificationSender(cast(discord.Client, client))
    )

    now = datetime(2026, 8, 14, tzinfo=UTC)
    assert await service.deliver_once(now=now) == 0

    sessions = create_session_factory(engine)
    async with sessions() as session:
        notification = await session.get(Notification, 1)
        assert notification is not None
        assert notification.status == NotificationStatus.PENDING
        assert notification.attempts == 1
        assert notification.next_retry_at is not None
        assert notification.next_retry_at.replace(tzinfo=UTC) == now + timedelta(seconds=60)
        assert notification.last_error == "RuntimeError"
    await engine.dispose()


async def _delivery_service(
    sender: DiscordNotificationSender,
) -> tuple[DeliveryService, AsyncEngine]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    async with sessions() as session, session.begin():
        target = MonitorTarget(
            theater_id="T1",
            theater_name="CGV Yongsan",
            show_date=date(2026, 8, 20),
        )
        session.add(target)
        await session.flush()
        subscription = Subscription(
            discord_user_id="123",
            guild_id=None,
            channel_id="456",
            target_id=target.id,
            keyword="dune",
            normalized_keyword="dune",
        )
        session.add(subscription)
        await session.flush()
        session.add(
            Notification(
                subscription_id=subscription.id,
                next_retry_at=datetime(2026, 8, 14, tzinfo=UTC),
            )
        )
    return DeliveryService(sessions, sender), engine


async def test_summary_and_persisted_discovery_time_reach_discord_without_files() -> None:
    client, user, channel = _sender_mocks()
    cast(Any, client).get_user.return_value = user
    titles = tuple(f"{index} " + "긴 영화 제목" * 20 for index in range(20))
    discovered_at = datetime(2026, 8, 14, 1, 23, tzinfo=UTC)
    sender = DiscordNotificationSender(cast(discord.Client, client))
    assert (
        await sender.send(
            user_id=123,
            guild_id=None,
            channel_id=456,
            theater_name="용산",
            show_date=date(2026, 8, 20),
            keyword="",
            movie_titles=titles,
            discovered_at=discovered_at,
        )
        == "1234"
    )
    values = cast(Any, channel).send.await_args.kwargs
    embed = cast(discord.Embed, values["embed"])
    assert embed.footer.text == "발견 시각: 2026-08-14 10:23 KST"
    displayed = embed.fields[0].value
    assert isinstance(displayed, str)
    lines = displayed.splitlines()
    shown_count = len(lines) - 1
    assert 0 < shown_count < len(titles)
    assert lines[:-1] == [f"• {title}" for title in titles[:shown_count]]
    assert lines[-1] == f"외 {len(titles) - shown_count}편"
    assert len(displayed) <= 1024
    assert "file" not in values
    assert "files" not in values
    assert values["content"] == "<@123>"
    mentions = cast(discord.AllowedMentions, values["allowed_mentions"])
    assert not mentions.everyone
    assert not mentions.roles
