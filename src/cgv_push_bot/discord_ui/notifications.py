from __future__ import annotations

from datetime import date, datetime

import discord

from .embeds import build_alert_message


class DiscordNotificationSender:
    def __init__(self, client: discord.Client) -> None:
        self._client = client

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
    ) -> str:
        if guild_id is None:
            user = self._client.get_user(user_id)
            if user is None:
                user = await self._client.fetch_user(user_id)
            channel = await user.create_dm()
        else:
            channel = self._client.get_channel(channel_id)
            if channel is None:
                channel = await self._client.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise TypeError("stored Discord channel is not messageable")
        payload = build_alert_message(
            user_id=user_id,
            theater_name=theater_name,
            show_date=show_date,
            movie_titles=movie_titles,
            keyword=keyword,
            discovered_at=discovered_at,
        )
        message = await channel.send(
            content=payload.content,
            embed=payload.embed,
            allowed_mentions=payload.allowed_mentions,
        )
        return str(message.id)
