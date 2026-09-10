# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import discord

from ...drafts import DraftStore
from ...protocols import AlertService
from .._base import OwnedView, edit_response, maybe_await, send_ephemeral


def format_current_movies(movie_titles: Sequence[str], *, max_length: int = 1_200) -> str:
    titles = tuple(dict.fromkeys(title.strip() for title in movie_titles if title.strip()))
    if not titles:
        return "현재 조건으로 이미 등록된 영화가 없습니다."

    header = "현재 조건으로 이미 등록된 영화:"
    lines: list[str] = []
    for index, title in enumerate(titles):
        remaining = len(titles) - index
        suffix = f"\n- 외 {remaining}편" if remaining else ""
        line = f"- {title}"
        if len(header) + len("\n".join((*lines, line))) + len(suffix) + 1 > max_length:
            lines.append(f"- 외 {remaining}편")
            break
        lines.append(line)
    return "\n".join((header, *lines))


async def show_confirmation(
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
    if not draft.theater_id or not draft.theater_name or draft.show_date is None:
        return await send_ephemeral(
            interaction, "등록 정보가 완성되지 않았습니다. 처음부터 다시 시도해 주세요."
        )
    await interaction.response.defer()
    try:
        movie_titles = tuple(
            await maybe_await(
                service.list_current_movies(
                    theater_id=draft.theater_id,
                    show_date=draft.show_date,
                    keyword=draft.keyword,
                )
            )
        )
    except Exception:
        return await edit_response(
            interaction,
            content="현재 등록된 영화 목록을 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            view=MoviePreviewRetryView(
                owner_id=owner_id,
                service=service,
                draft_store=draft_store,
                draft_id=draft_id,
            ),
        )
    description = (
        f"영화관: **{draft.theater_name}**\n"
        f"상영 날짜: **{draft.show_date.isoformat()}**\n"
        f"키워드: **{draft.keyword or '전체 영화'}**\n\n"
        f"{format_current_movies(movie_titles)}\n\n"
        "이 내용으로 알림을 등록할까요?"
    )
    return await edit_response(
        interaction,
        content=description,
        view=ConfirmationView(
            owner_id=owner_id,
            service=service,
            draft_store=draft_store,
            draft_id=draft_id,
        ),
    )


class MoviePreviewRetryView(OwnedView):
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
        self.retry_button = discord.ui.Button(
            label="다시 조회",
            style=discord.ButtonStyle.primary,
            custom_id=f"alert:movie-preview-retry:{uuid4().hex[:16]}",
        )
        self.retry_button.callback = self._on_retry
        self.add_item(self.retry_button)

    async def _on_retry(self, interaction: discord.Interaction[Any]) -> None:
        if self.draft_store.get(self.draft_id, owner_id=self.owner_id) is None:
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


async def channel_can_receive_alert(
    interaction: discord.Interaction[Any],
    service: AlertService,
) -> bool:
    channel = getattr(interaction, "channel", None)
    guild = getattr(interaction, "guild", None)
    if getattr(interaction, "guild_id", None) is None and guild is None:
        return getattr(channel, "type", None) == discord.ChannelType.private
    checker = getattr(service, "can_send_alert", None)
    if checker is None:
        checker = getattr(service, "check_channel_permissions", None)
    if checker is not None:
        result = await maybe_await(checker(channel))
        return bool(result)
    me = getattr(guild, "me", None) if guild is not None else None
    permissions_for = getattr(channel, "permissions_for", None)
    if me is None or permissions_for is None:
        return False
    permissions = permissions_for(me)
    return bool(
        getattr(permissions, "view_channel", False)
        and getattr(permissions, "send_messages", False)
        and getattr(permissions, "embed_links", False)
    )


class ConfirmationView(OwnedView):
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
        self.confirm_button = discord.ui.Button(
            label="등록 확인",
            style=discord.ButtonStyle.success,
            custom_id=f"alert:confirm:{uuid4().hex[:16]}",
        )
        self.confirm_button.callback = self._on_confirm
        self.add_item(self.confirm_button)
        self.cancel_button = discord.ui.Button(
            label="취소",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:cancel:{uuid4().hex[:16]}",
        )
        self.cancel_button.callback = self._on_cancel
        self.add_item(self.cancel_button)

    async def _on_cancel(self, interaction: discord.Interaction[Any]) -> None:
        self.draft_store.remove(self.draft_id, owner_id=self.owner_id)
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        await edit_response(interaction, content="알림 등록을 취소했습니다.", view=self)

    async def _on_confirm(self, interaction: discord.Interaction[Any]) -> None:
        draft = self.draft_store.get(self.draft_id, owner_id=self.owner_id)
        if (
            draft is None
            or not draft.theater_id
            or not draft.theater_name
            or draft.show_date is None
        ):
            await send_ephemeral(
                interaction, "등록 화면이 만료되었습니다. /alert를 다시 실행해 주세요."
            )
            return
        if not await channel_can_receive_alert(interaction, self.service):
            await send_ephemeral(
                interaction,
                "이 채널에서 메시지 보기, 보내기 및 링크 임베드 권한이 필요합니다. "
                "권한을 확인한 뒤 다시 시도해 주세요.",
            )
            return
        await interaction.response.defer()
        channel_id = draft.channel_id
        if draft.guild_id is None:
            try:
                dm = await interaction.user.create_dm()
            except discord.HTTPException:
                self.confirm_button.label = "다시 시도"
                await edit_response(
                    interaction,
                    content="DM을 열지 못했습니다. 봇 차단 및 DM 수신 설정을 확인한 뒤 "
                    "다시 시도해 주세요.",
                    view=self,
                )
                return
            channel_id = dm.id
        try:
            await maybe_await(
                self.service.register_subscription(
                    user_id=self.owner_id,
                    guild_id=draft.guild_id,
                    channel_id=channel_id,
                    theater_id=draft.theater_id,
                    theater_name=draft.theater_name,
                    show_date=draft.show_date,
                    keyword=draft.keyword,
                )
            )
        except Exception:
            self.confirm_button.label = "다시 시도"
            await edit_response(
                interaction,
                content="알림을 등록하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                view=self,
            )
            return
        self.draft_store.remove(self.draft_id, owner_id=self.owner_id)
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        content = (
            "알림을 등록했습니다. 새 영화가 편성되면 이 봇의 DM으로 알려드립니다."
            if draft.guild_id is None
            else "알림을 등록했습니다. 새 영화가 편성되면 이 채널로 알려드립니다."
        )
        await edit_response(interaction, content=content, view=self)


__all__ = [
    "ConfirmationView",
    "MoviePreviewRetryView",
    "channel_can_receive_alert",
    "format_current_movies",
    "show_confirmation",
]
