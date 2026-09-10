# discord.py's UI item generics are runtime-generated and expose unknown
# callback types to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord

from ..protocols import AlertService
from ._base import OwnedView, edit_response, send_ephemeral, value_from_object
from .deletion import DeleteSubscriptionView

_SEOUL = ZoneInfo("Asia/Seoul")


def _summary_id(summary: object) -> str:
    return str(value_from_object(summary, "id", "")).strip()


def _summary_date(summary: object) -> str:
    value = value_from_object(summary, "show_date", "")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _summary_label(summary: object) -> str:
    theater = str(value_from_object(summary, "theater_name", "영화관"))
    return f"{theater} · {_summary_date(summary)}"[:100]


def _summary_description(summary: object) -> str:
    keyword = str(value_from_object(summary, "keyword", "")).strip() or "전체 영화"
    channel_id = value_from_object(summary, "channel_id", None)
    channel = (
        "개인 DM" if value_from_object(summary, "guild_id", None) is None else f"채널 {channel_id}"
    )
    status = str(value_from_object(summary, "status", "active"))
    state = "활성" if status == "active" else "만료"
    return f"{keyword} · {channel} · {state}"[:100]


def _summary_count(summary: object, name: str) -> int:
    value = value_from_object(summary, name, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if not isinstance(value, str):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _format_last_success(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    # Database timestamps may be naive. They are stored as UTC by the alert
    # service, so attach UTC before converting to the user's display timezone.
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.astimezone(_SEOUL).strftime("%Y-%m-%d %H:%M KST")


def _poll_health_description(summary: object) -> str:
    last_success = _format_last_success(value_from_object(summary, "last_success_at", None))
    if bool(value_from_object(summary, "poll_failed", False)):
        if last_success is None:
            return "최근 조회 실패 · 잠시 후 다시 시도합니다."
        return f"최근 조회 실패 · 마지막 성공: {last_success}"
    if last_success is None:
        return "첫 조회 대기 중"
    return f"마지막 조회 성공: {last_success}"


class SubscriptionSelect(discord.ui.Select[Any]):
    def __init__(self, subscriptions: Sequence[object]) -> None:
        options = [
            discord.SelectOption(
                label=_summary_label(summary),
                description=_summary_description(summary),
                value=_summary_id(summary)[:100],
            )
            for summary in subscriptions[:25]
            if _summary_id(summary)
        ]
        if not options:
            raise ValueError("at least one subscription is required")
        super().__init__(
            custom_id=f"alert:subscription:{uuid4().hex[:16]}",
            placeholder="알림 선택",
            min_values=1,
            max_values=1,
            options=options,
        )


class SubscriptionListView(OwnedView):
    page_size = 25

    def __init__(
        self,
        *,
        owner_id: int,
        service: AlertService,
        subscriptions: Sequence[object],
        page: int = 0,
    ) -> None:
        super().__init__(owner_id=owner_id)
        self.service = service
        self.subscriptions = tuple(subscriptions)
        self.page = max(0, page)
        self._build_items()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.subscriptions) + self.page_size - 1) // self.page_size)

    @property
    def current_subscriptions(self) -> tuple[object, ...]:
        start = self.page * self.page_size
        return self.subscriptions[start : start + self.page_size]

    def _build_items(self) -> None:
        current = self.current_subscriptions
        if current:
            self.subscription_select = SubscriptionSelect(current)
            self.subscription_select.callback = self._on_select
            self.add_item(self.subscription_select)
        else:
            self.subscription_select = None

        self.previous_button = discord.ui.Button(
            label="이전",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:subscriptions-prev:{uuid4().hex[:16]}",
            disabled=self.page <= 0,
        )
        self.previous_button.callback = self._on_previous
        self.add_item(self.previous_button)
        self.next_button = discord.ui.Button(
            label="다음",
            style=discord.ButtonStyle.secondary,
            custom_id=f"alert:subscriptions-next:{uuid4().hex[:16]}",
            disabled=self.page >= self.page_count - 1,
        )
        self.next_button.callback = self._on_next
        self.add_item(self.next_button)

    def _replacement(self, page: int) -> SubscriptionListView:
        return SubscriptionListView(
            owner_id=self.owner_id,
            service=self.service,
            subscriptions=self.subscriptions,
            page=page,
        )

    async def _on_previous(self, interaction: discord.Interaction[Any]) -> None:
        if self.page <= 0:
            return await send_ephemeral(interaction, "첫 페이지입니다.")
        replacement = self._replacement(self.page - 1)
        await edit_response(interaction, content="내 알림 목록", view=replacement)

    async def _on_next(self, interaction: discord.Interaction[Any]) -> None:
        if self.page >= self.page_count - 1:
            return await send_ephemeral(interaction, "마지막 페이지입니다.")
        replacement = self._replacement(self.page + 1)
        await edit_response(interaction, content="내 알림 목록", view=replacement)

    async def _on_select(self, interaction: discord.Interaction[Any]) -> None:
        selected_id = (
            self.subscription_select.values[0]
            if self.subscription_select and self.subscription_select.values
            else ""
        )
        selected = next(
            (
                summary
                for summary in self.current_subscriptions
                if _summary_id(summary) == selected_id
            ),
            None,
        )
        if selected is None:
            await send_ephemeral(interaction, "알림을 찾을 수 없습니다. 목록을 새로고침해 주세요.")
            return
        theater = str(value_from_object(selected, "theater_name", "영화관"))
        keyword = str(value_from_object(selected, "keyword", "")).strip() or "전체 영화"
        status = str(value_from_object(selected, "status", "active"))
        channel_id = value_from_object(selected, "channel_id", None)
        destination = (
            "개인 DM" if value_from_object(selected, "guild_id", None) is None else str(channel_id)
        )
        pending_notifications = _summary_count(selected, "pending_notifications")
        failed_notifications = _summary_count(selected, "failed_notifications")
        description = (
            f"영화관: **{theater}**\n"
            f"상영 날짜: **{_summary_date(selected)}**\n"
            f"키워드: **{keyword}**\n"
            f"알림 수신: **{destination}**\n"
            f"상태: **{'활성' if status == 'active' else '만료'}**\n"
            f"조회 상태: **{_poll_health_description(selected)}**\n"
            f"알림 전송 대기: **{pending_notifications}건**\n"
            f"알림 전송 실패: **{failed_notifications}건**"
        )
        await edit_response(
            interaction,
            content=description,
            view=DeleteSubscriptionView(
                owner_id=self.owner_id,
                service=self.service,
                subscription_id=selected_id,
                summary=selected,
            ),
        )


__all__ = ["SubscriptionListView", "SubscriptionSelect"]
