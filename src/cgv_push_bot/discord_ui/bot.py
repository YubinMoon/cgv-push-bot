from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from .commands import register_alert_command
from .drafts import DraftStore
from .protocols import AlertService


class CgvPushBot(commands.Bot):
    def __init__(
        self,
        *,
        service: AlertService,
        draft_store: DraftStore | None = None,
    ) -> None:
        # Intents.default() deliberately excludes message content, members,
        # presence, and every other privileged intent.
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.alert_service = service
        self.alert_draft_store = draft_store or DraftStore()
        self.alert_command: discord.app_commands.Command[Any, Any, Any] = register_alert_command(
            self.tree,
            service=self.alert_service,
            draft_store=self.alert_draft_store,
        )

    async def setup_hook(self) -> None:
        await self.tree.sync()


def create_bot(
    service: AlertService,
    *,
    draft_store: DraftStore | None = None,
) -> CgvPushBot:
    return CgvPushBot(service=service, draft_store=draft_store)


__all__ = ["CgvPushBot", "create_bot"]
