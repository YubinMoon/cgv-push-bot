# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import uuid4

import discord

from ...drafts import DraftStore, parse_show_date, upcoming_dates
from ...protocols import AlertService
from .._base import OwnedView, send_ephemeral
from .keywords import show_keyword_view


class DateSelect(discord.ui.Select[Any]):
    def __init__(self, dates: Sequence[date]) -> None:
        if not dates:
            raise ValueError("at least one date is required")
        super().__init__(
            custom_id=f"alert:date:{uuid4().hex[:16]}",
            placeholder="빠른 날짜 선택",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=f"{chosen:%m/%d} ({chosen:%a})",
                    value=chosen.isoformat(),
                )
                for chosen in dates[:25]
            ],
        )


class DateSelectionView(OwnedView):
    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        draft_id: str,
        dates: Sequence[date] | None = None,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id
        self.dates = tuple(dates or upcoming_dates(count=14))
        self.date_select = DateSelect(self.dates)
        self.date_select.callback = self._on_date_select
        self.add_item(self.date_select)
        self.custom_date_button = discord.ui.Button(
            label="직접 입력",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:date-custom:{uuid4().hex[:16]}",
        )
        self.custom_date_button.callback = self._on_custom_date
        self.add_item(self.custom_date_button)

    async def _on_date_select(self, interaction: discord.Interaction[Any]) -> None:
        if not self.date_select.values:
            await send_ephemeral(interaction, "날짜를 선택해 주세요.")
            return
        try:
            selected = parse_show_date(self.date_select.values[0])
            self.draft_store.update(self.draft_id, owner_id=self.owner_id, show_date=selected)
        except (KeyError, ValueError):
            await send_ephemeral(interaction, "날짜 선택이 만료되었습니다. 다시 시도해 주세요.")
            return
        await show_keyword_view(
            interaction,
            owner_id=self.owner_id,
            service=self.service,
            draft_store=self.draft_store,
            draft_id=self.draft_id,
        )

    async def _on_custom_date(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.send_modal(
            CustomDateModal(
                owner_id=self.owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=self.draft_id,
            )
        )


class CustomDateModal(discord.ui.Modal, title="상영 날짜 직접 입력"):
    date_input = discord.ui.TextInput(
        label="날짜 (YYYY-MM-DD)",
        placeholder="2026-08-20",
        min_length=10,
        max_length=10,
        required=True,
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
        try:
            selected = parse_show_date(str(self.date_input.value))
            self.draft_store.update(self.draft_id, owner_id=self.owner_id, show_date=selected)
        except (KeyError, ValueError) as exc:
            await send_ephemeral(interaction, str(exc) or "올바른 날짜를 입력해 주세요.")
            return
        await show_keyword_view(
            interaction,
            owner_id=self.owner_id,
            service=self.service,
            draft_store=self.draft_store,
            draft_id=self.draft_id,
        )


__all__ = ["CustomDateModal", "DateSelect", "DateSelectionView"]
