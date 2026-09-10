# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from typing import Any
from uuid import uuid4

import discord

from ...drafts import DraftStore
from ...protocols import AlertService
from .._base import OwnedView, edit_response, send_ephemeral
from .confirmation import show_confirmation


async def show_keyword_view(
    interaction: discord.Interaction[Any],
    *,
    owner_id: int,
    service: AlertService,
    draft_store: DraftStore,
    draft_id: str,
) -> Any:
    draft = draft_store.get(draft_id, owner_id=owner_id)
    if draft is None:
        return await send_ephemeral(
            interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
        )
    return await edit_response(
        interaction,
        content="영화 제목 키워드를 선택해 주세요.",
        view=KeywordView(
            owner_id=owner_id,
            service=service,
            draft_store=draft_store,
            draft_id=draft_id,
        ),
    )


class KeywordView(OwnedView):
    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        draft_id: str,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id
        self.keyword_button = discord.ui.Button(
            label="키워드 입력",
            style=discord.ButtonStyle.primary,
            custom_id=f"alert:keyword:{uuid4().hex[:16]}",
        )
        self.keyword_button.callback = self._on_keyword
        self.add_item(self.keyword_button)
        self.no_keyword_button = discord.ui.Button(
            label="키워드 없이 등록",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:no-keyword:{uuid4().hex[:16]}",
        )
        self.no_keyword_button.callback = self._on_no_keyword
        self.add_item(self.no_keyword_button)

    async def _on_keyword(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.send_modal(
            KeywordModal(
                owner_id=self.owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=self.draft_id,
            )
        )

    async def _on_no_keyword(self, interaction: discord.Interaction[Any]) -> None:
        try:
            self.draft_store.update(self.draft_id, owner_id=self.owner_id, keyword="")
        except (KeyError, ValueError):
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        await show_confirmation(
            interaction,
            owner_id=self.owner_id,
            service=self.service,
            draft_store=self.draft_store,
            draft_id=self.draft_id,
        )


class KeywordModal(discord.ui.Modal, title="영화 제목 키워드"):
    keyword_input = discord.ui.TextInput(
        label="포함할 키워드 (선택)",
        placeholder="예: 아바타",
        max_length=100,
        required=False,
    )

    def __init__(
        self, *, owner_id: int, service: AlertService, draft_store: DraftStore, draft_id: str
    ) -> None:
        super().__init__(timeout=900.0)
        self.owner_id = owner_id
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        if getattr(getattr(interaction, "user", None), "id", None) != self.owner_id:
            await send_ephemeral(interaction, "이 등록 화면을 만든 사용자만 사용할 수 있습니다.")
            return
        keyword = str(self.keyword_input.value).strip()
        try:
            self.draft_store.update(self.draft_id, owner_id=self.owner_id, keyword=keyword)
        except (KeyError, ValueError):
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        await show_confirmation(
            interaction,
            owner_id=self.owner_id,
            service=self.service,
            draft_store=self.draft_store,
            draft_id=self.draft_id,
        )


__all__ = ["KeywordModal", "KeywordView", "show_keyword_view"]
