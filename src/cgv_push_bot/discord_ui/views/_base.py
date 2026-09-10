from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from contextlib import suppress
from typing import Any, cast

import discord


async def maybe_await[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def _response_done(interaction: discord.Interaction[Any]) -> bool:
    response = interaction.response
    marker = getattr(response, "is_done", False)
    return bool(marker() if callable(marker) else marker)


async def send_ephemeral(
    interaction: discord.Interaction[Any],
    content: str,
    *,
    view: discord.ui.View | None = None,
) -> Any:
    if _response_done(interaction):
        if view is None:
            return await interaction.followup.send(content, ephemeral=True)
        return await interaction.followup.send(content, ephemeral=True, view=view)
    if view is None:
        return await interaction.response.send_message(content, ephemeral=True)
    return await interaction.response.send_message(content, ephemeral=True, view=view)


async def edit_response(
    interaction: discord.Interaction[Any],
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
) -> Any:
    if not _response_done(interaction):
        return await interaction.response.edit_message(content=content, embed=embed, view=view)
    editor = getattr(interaction, "edit_original_response", None)
    if editor is None:
        return await interaction.response.edit_message(content=content, embed=embed, view=view)
    return await editor(content=content, embed=embed, view=view)


class OwnedView(discord.ui.View):
    """A view whose controls can only be used by its creating Discord user."""

    def __init__(self, *, owner_id: int, timeout: float = 900.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction[Any]) -> bool:
        user = getattr(interaction, "user", None)
        if user is not None and getattr(user, "id", None) == self.owner_id:
            return True
        await send_ephemeral(interaction, "이 알림 화면을 만든 사용자만 사용할 수 있습니다.")
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        message = getattr(self, "message", None)
        if message is not None:
            with suppress(discord.HTTPException, discord.NotFound):
                await message.edit(view=self)


def interaction_channel_id(interaction: discord.Interaction[Any], fallback: int = 0) -> int:
    channel = getattr(interaction, "channel", None)
    value = getattr(channel, "id", None)
    return int(value) if value is not None else fallback


def interaction_guild_id(interaction: discord.Interaction[Any]) -> int | None:
    guild = getattr(interaction, "guild", None)
    value = getattr(guild, "id", None)
    return int(value) if value is not None else None


def value_from_object(value: object, name: str, default: object = "") -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return mapping.get(name, default)
    return getattr(value, name, default)


__all__ = [
    "OwnedView",
    "edit_response",
    "interaction_channel_id",
    "interaction_guild_id",
    "maybe_await",
    "send_ephemeral",
    "value_from_object",
]
