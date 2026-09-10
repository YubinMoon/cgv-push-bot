from __future__ import annotations

from typing import Any, cast

import discord
from discord import app_commands

from .drafts import DraftStore
from .protocols import AlertService
from .views.dashboard import DashboardView

ALERT_DESCRIPTION = "영화관의 새 영화 편성 알림을 관리합니다."


async def handle_alert_command(
    interaction: discord.Interaction[Any],
    *,
    service: AlertService,
    draft_store: DraftStore,
) -> None:
    user = getattr(interaction, "user", None)
    owner_id = getattr(user, "id", None)
    if owner_id is None:
        await interaction.response.send_message(
            "사용자 정보를 확인하지 못했습니다.", ephemeral=True
        )
        return
    await interaction.response.send_message(
        "영화 알림 대시보드입니다.",
        ephemeral=True,
        view=DashboardView(
            owner_id=int(owner_id),
            service=service,
            draft_store=draft_store,
        ),
    )


def build_alert_command(
    *, service: AlertService, draft_store: DraftStore
) -> app_commands.Command[Any, Any, Any]:
    async def alert(interaction: discord.Interaction[Any]) -> None:
        await handle_alert_command(interaction, service=service, draft_store=draft_store)

    return cast(
        app_commands.Command[Any, Any, Any],
        app_commands.Command(
            name="alert",
            description=ALERT_DESCRIPTION,
            callback=alert,
            allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
            allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=False
            ),
        ),
    )


def register_alert_command(
    tree: app_commands.CommandTree[Any],
    *,
    service: AlertService,
    draft_store: DraftStore,
) -> app_commands.Command[Any, Any, Any]:
    command = build_alert_command(service=service, draft_store=draft_store)
    tree.add_command(command)
    return command


__all__ = [
    "ALERT_DESCRIPTION",
    "build_alert_command",
    "handle_alert_command",
    "register_alert_command",
]
