# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from typing import Any
from uuid import uuid4

import discord

from ..protocols import AlertService
from ._base import OwnedView, edit_response, maybe_await, send_ephemeral


class DeleteSubscriptionView(OwnedView):
    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        subscription_id: str,
        summary: object | None = None,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.subscription_id = subscription_id
        self.summary = summary
        self.delete_button = discord.ui.Button(
            label="삭제 확인",
            style=discord.ButtonStyle.danger,
            custom_id=f"alert:delete:{uuid4().hex[:16]}",
        )
        self.delete_button.callback = self._on_delete
        self.add_item(self.delete_button)
        self.cancel_button = discord.ui.Button(
            label="취소",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:delete-cancel:{uuid4().hex[:16]}",
        )
        self.cancel_button.callback = self._on_cancel
        self.add_item(self.cancel_button)

    async def _on_delete(self, interaction: discord.Interaction[Any]) -> None:
        # The service receives the user id and must re-check ownership in its
        # transaction.  Never trust a subscription id from a component alone.
        user_id = getattr(getattr(interaction, "user", None), "id", None)
        if user_id != self.owner_id:
            await send_ephemeral(interaction, "이 알림을 등록한 사용자만 삭제할 수 있습니다.")
            return
        await interaction.response.defer()
        try:
            await maybe_await(
                self.service.delete_subscription(
                    user_id=self.owner_id,
                    subscription_id=self.subscription_id,
                )
            )
        except Exception:
            await send_ephemeral(
                interaction, "알림을 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요."
            )
            return
        self.stop()
        for item in self.children:
            item.disabled = True
        await edit_response(interaction, content="알림을 삭제했습니다.", view=self)

    async def _on_cancel(self, interaction: discord.Interaction[Any]) -> None:
        await edit_response(interaction, content="알림 삭제를 취소했습니다.", view=self)


__all__ = ["DeleteSubscriptionView"]
