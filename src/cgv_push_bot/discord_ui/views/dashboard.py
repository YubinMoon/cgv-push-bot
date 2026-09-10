# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright; application-facing values remain explicitly typed.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from typing import Any
from uuid import uuid4

import discord

from ..drafts import DraftStore
from ..protocols import AlertService
from ._base import OwnedView, edit_response, maybe_await, send_ephemeral
from .registration import TheaterSearchModal
from .subscriptions import SubscriptionListView


class DashboardView(OwnedView):
    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        timeout: float = 900.0,
    ) -> None:
        super().__init__(owner_id=owner_id, timeout=timeout)
        self.service = service
        self.draft_store = draft_store

        self.new_alert_button = discord.ui.Button(
            label="새 알림 등록",
            style=discord.ButtonStyle.primary,
            custom_id=f"alert:new:{uuid4().hex[:16]}",
        )
        self.new_alert_button.callback = self._on_new_alert
        self.add_item(self.new_alert_button)

        self.list_alert_button = discord.ui.Button(
            label="내 알림 확인",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:list:{uuid4().hex[:16]}",
        )
        self.list_alert_button.callback = self._on_list_alerts
        self.add_item(self.list_alert_button)

        self.close_button = discord.ui.Button(
            label="닫기",
            style=discord.ButtonStyle.danger,
            custom_id=f"alert:close:{uuid4().hex[:16]}",
        )
        self.close_button.callback = self._on_close
        self.add_item(self.close_button)

    async def _on_new_alert(self, interaction: discord.Interaction[Any]) -> None:
        user = getattr(interaction, "user", None)
        owner_id = int(getattr(user, "id", self.owner_id))
        draft_id = uuid4().hex
        channel_id = interaction.channel_id
        guild_id = interaction.guild_id
        if channel_id is None:
            await send_ephemeral(
                interaction, "알림을 받을 채널을 확인하지 못했습니다. /alert를 다시 실행해 주세요."
            )
            return
        self.draft_store.create(
            draft_id=draft_id,
            owner_id=owner_id,
            guild_id=int(guild_id) if guild_id is not None else None,
            channel_id=channel_id,
        )
        await interaction.response.send_modal(
            TheaterSearchModal(
                owner_id=owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=draft_id,
            )
        )

    async def _on_list_alerts(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer()
        try:
            subscriptions = await maybe_await(self.service.list_subscriptions(self.owner_id))
        except Exception:
            await send_ephemeral(
                interaction, "알림 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
            )
            return
        await edit_response(
            interaction,
            content="내 알림 목록",
            view=SubscriptionListView(
                owner_id=self.owner_id,
                service=self.service,
                subscriptions=tuple(subscriptions),
            ),
        )

    async def _on_close(self, interaction: discord.Interaction[Any]) -> None:
        self.stop()
        for item in self.children:
            item.disabled = True
        await edit_response(interaction, content="알림 화면을 닫았습니다.", view=self)


__all__ = ["DashboardView"]
