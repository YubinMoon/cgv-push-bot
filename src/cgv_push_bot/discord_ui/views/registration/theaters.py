# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

import discord

from ...drafts import DraftStore
from ...protocols import AlertService
from .._base import OwnedView, edit_response, maybe_await, send_ephemeral, value_from_object
from .dates import DateSelectionView


def theater_choice_fields(choice: object) -> tuple[str, str]:
    theater_id = str(value_from_object(choice, "id")).strip()
    name = str(value_from_object(choice, "name", theater_id)).strip()
    return theater_id, name


def theater_page_content(page: int, page_count: int) -> str:
    if page_count <= 1:
        return "영화관을 하나 선택해 주세요."
    return f"영화관을 하나 선택해 주세요. (페이지 {page + 1}/{page_count})"


class TheaterSearchModal(discord.ui.Modal, title="영화관 검색"):
    query = discord.ui.TextInput(
        label="영화관 이름",
        placeholder="예: 용산",
        min_length=1,
        max_length=100,
        required=True,
    )

    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        draft_id: str,
        query: str | None = None,
    ) -> None:
        super().__init__(timeout=900.0)
        self.owner_id = owner_id
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id
        if query is not None:
            self.query.default = query

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        if getattr(getattr(interaction, "user", None), "id", None) != self.owner_id:
            await send_ephemeral(interaction, "이 등록 화면을 만든 사용자만 사용할 수 있습니다.")
            return
        draft = self.draft_store.get(self.draft_id, owner_id=self.owner_id)
        if draft is None:
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        query = str(self.query.value).strip()
        await interaction.response.defer()
        try:
            found = await maybe_await(self.service.search_theaters(query))
            choices = tuple(found)
        except Exception:
            await edit_response(
                interaction,
                content="영화관을 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                view=TheaterSearchRetryView(
                    owner_id=self.owner_id,
                    service=self.service,
                    draft_store=self.draft_store,
                    draft_id=self.draft_id,
                    query=query,
                ),
            )
            return
        if not choices:
            await edit_response(
                interaction,
                content="검색 결과가 없습니다. 다른 이름으로 다시 검색해 주세요.",
                view=TheaterSearchRetryView(
                    owner_id=self.owner_id,
                    service=self.service,
                    draft_store=self.draft_store,
                    draft_id=self.draft_id,
                    query=query,
                ),
            )
            return
        await edit_response(
            interaction,
            content=theater_page_content(0, max(1, (len(choices) + 24) // 25)),
            view=TheaterSelectView(
                owner_id=self.owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=self.draft_id,
                choices=choices,
            ),
        )


class TheaterSearchRetryView(OwnedView):
    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        draft_id: str,
        query: str,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id
        self.query = query
        self.retry_button = discord.ui.Button(
            label="다시 검색",
            style=discord.ButtonStyle.primary,
            custom_id=f"alert:theater-retry:{uuid4().hex[:16]}",
        )
        self.retry_button.callback = self._on_retry
        self.add_item(self.retry_button)

    async def _on_retry(self, interaction: discord.Interaction[Any]) -> None:
        if self.draft_store.get(self.draft_id, owner_id=self.owner_id) is None:
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        await interaction.response.send_modal(
            TheaterSearchModal(
                owner_id=self.owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=self.draft_id,
                query=self.query,
            )
        )


class TheaterSelect(discord.ui.Select[Any]):
    def __init__(self, choices: Sequence[object]) -> None:
        options: list[discord.SelectOption] = []
        for choice in choices[:25]:
            theater_id, name = theater_choice_fields(choice)
            if not theater_id:
                continue
            options.append(discord.SelectOption(label=name[:100], value=theater_id[:100]))
        if not options:
            raise ValueError("at least one theater choice is required")
        super().__init__(
            custom_id=f"alert:theater:{uuid4().hex[:16]}",
            placeholder="영화관 선택",
            min_values=1,
            max_values=1,
            options=options,
        )


class TheaterSelectView(OwnedView):
    page_size = 25

    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        draft_store: DraftStore,
        draft_id: str,
        choices: Sequence[object],
        page: int = 0,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.draft_store = draft_store
        self.draft_id = draft_id
        self.all_choices = tuple(choice for choice in choices if theater_choice_fields(choice)[0])
        self.page = max(0, page)
        self.page = min(self.page, self.page_count - 1)
        current_choices = self.current_choices
        self.choices: Mapping[str, object] = {
            theater_choice_fields(choice)[0]: choice for choice in current_choices
        }
        self.select = TheaterSelect(tuple(self.choices.values()))
        self.select.callback = self._on_select
        self.add_item(self.select)
        self.previous_button = discord.ui.Button(
            label="이전",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:theater-prev:{uuid4().hex[:16]}",
            disabled=self.page <= 0,
        )
        self.previous_button.callback = self._on_previous
        self.add_item(self.previous_button)
        self.next_button = discord.ui.Button(
            label="다음",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:theater-next:{uuid4().hex[:16]}",
            disabled=self.page >= self.page_count - 1,
        )
        self.next_button.callback = self._on_next
        self.add_item(self.next_button)

    @property
    def page_count(self) -> int:
        return max(1, (len(self.all_choices) + self.page_size - 1) // self.page_size)

    @property
    def current_choices(self) -> tuple[object, ...]:
        start = self.page * self.page_size
        return self.all_choices[start : start + self.page_size]

    def _replacement(self, page: int) -> TheaterSelectView:
        return TheaterSelectView(
            owner_id=self.owner_id,
            service=self.service,
            draft_store=self.draft_store,
            draft_id=self.draft_id,
            choices=self.all_choices,
            page=page,
        )

    async def _on_previous(self, interaction: discord.Interaction[Any]) -> None:
        if self.page <= 0:
            await send_ephemeral(interaction, "첫 페이지입니다.")
            return
        await edit_response(
            interaction,
            content=theater_page_content(self.page - 1, self.page_count),
            view=self._replacement(self.page - 1),
        )

    async def _on_next(self, interaction: discord.Interaction[Any]) -> None:
        if self.page >= self.page_count - 1:
            await send_ephemeral(interaction, "마지막 페이지입니다.")
            return
        await edit_response(
            interaction,
            content=theater_page_content(self.page + 1, self.page_count),
            view=self._replacement(self.page + 1),
        )

    async def _on_select(self, interaction: discord.Interaction[Any]) -> None:
        selected_id = self.select.values[0] if self.select.values else ""
        choice = self.choices.get(selected_id)
        if choice is None:
            await send_ephemeral(interaction, "영화관 선택이 만료되었습니다. 다시 검색해 주세요.")
            return
        _, name = theater_choice_fields(choice)
        try:
            self.draft_store.update(
                self.draft_id,
                owner_id=self.owner_id,
                theater_id=selected_id,
                theater_name=name,
            )
        except (KeyError, ValueError):
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        await edit_response(
            interaction,
            content="상영 날짜를 선택해 주세요.",
            view=DateSelectionView(
                owner_id=self.owner_id,
                service=self.service,
                draft_store=self.draft_store,
                draft_id=self.draft_id,
            ),
        )


__all__ = [
    "TheaterSearchModal",
    "TheaterSearchRetryView",
    "TheaterSelect",
    "TheaterSelectView",
    "theater_choice_fields",
    "theater_page_content",
]
