from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord
import pytest

from cgv_push_bot.discord_ui import (
    CgvPushBot,
    DraftStore,
    build_alert_message,
    normalize_keyword,
    parse_show_date,
)
from cgv_push_bot.discord_ui.protocols import SubscriptionSummary, TheaterChoice
from cgv_push_bot.discord_ui.views.dashboard import DashboardView
from cgv_push_bot.discord_ui.views.deletion import DeleteSubscriptionView
from cgv_push_bot.discord_ui.views.registration import (
    ConfirmationView,
    DateSelectionView,
    KeywordView,
    TheaterSearchModal,
    TheaterSelectView,
    channel_can_receive_alert,
)
from cgv_push_bot.discord_ui.views.subscriptions import SubscriptionListView


class FakeService:
    def __init__(self, movie_titles: tuple[str, ...] = ()) -> None:
        self.movie_titles = movie_titles
        self.list_current_movies_calls: list[dict[str, object]] = []

    async def search_theaters(self, query: str):
        return (TheaterChoice("1", query),)

    async def list_current_movies(self, **kwargs: object):
        self.list_current_movies_calls.append(kwargs)
        return self.movie_titles

    async def register_subscription(self, **kwargs: object):
        return SubscriptionSummary("sub", "용산", date(2026, 8, 20))

    async def list_subscriptions(self, user_id: int):
        return ()

    async def delete_subscription(self, *, user_id: int, subscription_id: str):
        return None


class FakeResponse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str, **kwargs: object) -> None:
        self.calls.append((content, kwargs))
        self._done = True

    async def edit_message(self, **kwargs: object) -> None:
        self.calls.append(("edit", kwargs))
        self._done = True

    async def defer(self, **kwargs: object) -> None:
        self.calls.append(("defer", kwargs))
        self._done = True

    async def send_modal(self, modal: object) -> None:
        self.calls.append(("modal", {"modal": modal}))
        self._done = True


@dataclass
class Clock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


def interaction(user_id: int) -> Any:
    return SimpleNamespace(user=SimpleNamespace(id=user_id), response=FakeResponse())


def test_alert_command_and_default_intents() -> None:
    bot = CgvPushBot(service=FakeService())
    assert bot.tree.get_command("alert") is not None
    assert bot.intents.message_content is False
    assert bot.intents.members is False
    assert bot.intents.presences is False
    assert bot.allowed_mentions is not None
    assert bot.allowed_mentions.everyone is False
    payload = bot.alert_command.to_dict(bot.tree)
    assert payload["integration_types"] == [0, 1]
    assert payload["contexts"] == [0, 1]


@pytest.mark.asyncio
async def test_bot_syncs_commands_globally(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = CgvPushBot(service=FakeService())
    sync = AsyncMock(return_value=[])
    monkeypatch.setattr(bot.tree, "sync", sync)
    await bot.setup_hook()
    sync.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_dashboard_rejects_other_user() -> None:
    view = DashboardView(owner_id=7, service=FakeService(), draft_store=DraftStore())
    candidate = interaction(8)
    assert await view.interaction_check(candidate) is False
    assert candidate.response.calls[0][1]["ephemeral"] is True


@pytest.mark.asyncio
async def test_component_edit_uses_initial_response_before_webhook() -> None:
    view = DashboardView(owner_id=7, service=FakeService(), draft_store=DraftStore())
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()
    await view.close_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]
    assert candidate.response.calls[0][0] == "edit"
    candidate.edit_original_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_list_defers_before_editing_webhook() -> None:
    view = DashboardView(owner_id=7, service=FakeService(), draft_store=DraftStore())
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()
    await view.list_alert_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]
    assert candidate.response.calls[0][0] == "defer"
    candidate.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_theater_modal_updates_dashboard_message() -> None:
    store = DraftStore()
    store.create(draft_id="d", owner_id=7, guild_id=None, channel_id=3)
    modal = TheaterSearchModal(
        owner_id=7,
        service=FakeService(),
        draft_store=store,
        draft_id="d",
    )
    query_field = "query"
    query_input = getattr(modal, query_field)
    query_input._value = "용산"
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()

    await modal.on_submit(candidate)

    assert candidate.response.calls == [("defer", {})]
    candidate.edit_original_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmation_shows_movies_matching_current_conditions() -> None:
    service = FakeService(("Dune", "Dune: Part Two"))
    store = DraftStore()
    store.create(draft_id="d", owner_id=7, guild_id=None, channel_id=3)
    store.update(
        "d",
        owner_id=7,
        theater_id="T1",
        theater_name="용산",
        show_date=date(2026, 8, 20),
    )
    view = KeywordView(owner_id=7, service=service, draft_store=store, draft_id="d")
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()

    await view.no_keyword_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]

    assert candidate.response.calls == [("defer", {})]
    service_call = service.list_current_movies_calls[0]
    assert service_call == {
        "theater_id": "T1",
        "show_date": date(2026, 8, 20),
        "keyword": "",
    }
    edit_call = candidate.edit_original_response.await_args
    assert edit_call is not None
    content = edit_call.kwargs["content"]
    assert "현재 조건으로 이미 등록된 영화:\n- Dune\n- Dune: Part Two" in content
    assert content.endswith("이 내용으로 알림을 등록할까요?")


def test_draft_store_expires_after_fifteen_minutes_and_enforces_owner() -> None:
    clock = Clock(datetime(2026, 8, 14, tzinfo=UTC))
    store = DraftStore(ttl=timedelta(minutes=15), clock=clock)
    store.create(draft_id="d", owner_id=7, guild_id=1, channel_id=2)
    assert store.get("d", owner_id=8) is None
    assert store.get("d", owner_id=7) is not None
    clock.value += timedelta(minutes=15)
    assert store.get("d", owner_id=7) is None


def test_keyword_normalization_and_date_validation() -> None:
    assert normalize_keyword("  \uff2d\uff4f\uff56\uff49\uff45  ") == "movie"
    assert parse_show_date("2026-08-20", today=date(2026, 8, 14)) == date(2026, 8, 20)
    with pytest.raises(ValueError):
        parse_show_date("2026-08-13", today=date(2026, 8, 14))
    with pytest.raises(ValueError):
        parse_show_date("20260820", today=date(2026, 8, 14))


def test_registration_and_subscription_views_respect_discord_limits() -> None:
    service = FakeService()
    store = DraftStore()
    store.create(draft_id="d", owner_id=7, guild_id=None, channel_id=3)
    theater_view = TheaterSelectView(
        owner_id=7,
        service=service,
        draft_store=store,
        draft_id="d",
        choices=[TheaterChoice(str(i), f"극장 {i}") for i in range(30)],
    )
    assert len(theater_view.select.options) == 25
    date_view = DateSelectionView(
        owner_id=7,
        service=service,
        draft_store=store,
        draft_id="d",
    )
    assert len(date_view.date_select.options) == 14
    subscriptions = [
        SubscriptionSummary(str(i), "극장", date(2026, 8, 14), channel_id=3) for i in range(30)
    ]
    page = SubscriptionListView(owner_id=7, service=service, subscriptions=subscriptions)
    assert page.page_count == 2
    assert page.subscription_select is not None
    assert len(page.subscription_select.options) == 25


@pytest.mark.asyncio
async def test_delete_rechecks_owner_before_calling_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeService()
    delete = AsyncMock()
    monkeypatch.setattr(service, "delete_subscription", delete)
    view = DeleteSubscriptionView(owner_id=7, service=service, subscription_id="sub")
    candidate = interaction(8)
    await view.delete_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]
    assert candidate.response.calls[0][1]["ephemeral"] is True
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_rejects_registration_without_embed_links_permission() -> None:
    permissions = SimpleNamespace(view_channel=True, send_messages=True, embed_links=False)

    def permissions_for(_: object) -> SimpleNamespace:
        return permissions

    channel = SimpleNamespace(permissions_for=permissions_for)
    candidate = cast(Any, SimpleNamespace(channel=channel, guild=SimpleNamespace(me=object())))

    assert await channel_can_receive_alert(candidate, FakeService()) is False


def test_alert_message_allows_only_target_user_mention() -> None:
    message = build_alert_message(
        user_id=123,
        theater_name="용산",
        show_date=date(2026, 8, 20),
        movie_titles=["A", "B"],
    )
    assert message.content == "<@123>"
    mentions = message.allowed_mentions
    assert mentions.everyone is False
    assert mentions.roles is False
    assert mentions.replied_user is False
    users = cast(list[Any], mentions.users)
    assert [user.id for user in users] == [123]


@pytest.mark.parametrize("guild_id", [None, 42])
async def test_new_draft_uses_interaction_ids_without_cached_channel(guild_id: int | None) -> None:
    store = DraftStore()
    view = DashboardView(owner_id=7, service=FakeService(), draft_store=store)
    candidate = interaction(7)
    candidate.guild_id = guild_id
    candidate.channel_id = 123
    candidate.channel = None

    await view.new_alert_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]

    modal = cast(TheaterSearchModal, candidate.response.calls[0][1]["modal"])
    draft = store.get(modal.draft_id, owner_id=7)
    assert draft is not None
    assert (draft.guild_id, draft.channel_id) == (guild_id, 123)


async def test_new_draft_rejects_missing_channel() -> None:
    view = DashboardView(owner_id=7, service=FakeService(), draft_store=DraftStore())
    candidate = interaction(7)
    candidate.guild_id = None
    candidate.channel_id = None
    await view.new_alert_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]
    assert "채널을 확인하지 못했습니다" in candidate.response.calls[0][0]


@pytest.mark.parametrize("guild_id", [None, 42])
async def test_confirmation_registers_dm_or_server_destination(
    monkeypatch: pytest.MonkeyPatch, guild_id: int | None
) -> None:
    service = FakeService()
    register = AsyncMock()
    monkeypatch.setattr(service, "register_subscription", register)
    store = DraftStore()
    store.create(draft_id="d", owner_id=7, guild_id=guild_id, channel_id=123)
    store.update("d", owner_id=7, theater_id="T1", theater_name="용산", show_date=date(2030, 1, 1))
    view = ConfirmationView(owner_id=7, service=service, draft_store=store, draft_id="d")
    candidate = interaction(7)
    candidate.guild_id = guild_id
    candidate.guild = None if guild_id is None else SimpleNamespace(me=object())

    def permissions_for(_: object) -> SimpleNamespace:
        return SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)

    candidate.channel = SimpleNamespace(
        type=discord.ChannelType.private if guild_id is None else discord.ChannelType.text,
        permissions_for=permissions_for,
    )
    create_dm = AsyncMock(return_value=SimpleNamespace(id=456))
    candidate.user.create_dm = create_dm
    candidate.edit_original_response = AsyncMock()

    await view.confirm_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]

    register.assert_awaited_once_with(
        user_id=7,
        guild_id=guild_id,
        channel_id=456 if guild_id is None else 123,
        theater_id="T1",
        theater_name="용산",
        show_date=date(2030, 1, 1),
        keyword="",
    )
    if guild_id is None:
        create_dm.assert_awaited_once_with()
    else:
        create_dm.assert_not_awaited()
    assert store.get("d", owner_id=7) is None
    assert candidate.response.calls == [("defer", {})]


async def test_dm_creation_failure_keeps_draft_without_registering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeService()
    register = AsyncMock()
    monkeypatch.setattr(service, "register_subscription", register)
    store = DraftStore()
    store.create(draft_id="d", owner_id=7, guild_id=None, channel_id=123)
    store.update("d", owner_id=7, theater_id="T1", theater_name="용산", show_date=date(2030, 1, 1))
    view = ConfirmationView(owner_id=7, service=service, draft_store=store, draft_id="d")
    candidate = interaction(7)
    candidate.guild_id = None
    candidate.guild = None
    candidate.channel = SimpleNamespace(type=discord.ChannelType.private)
    candidate.user.create_dm = AsyncMock(
        side_effect=discord.Forbidden(
            cast(Any, SimpleNamespace(status=403, reason="Forbidden")), ""
        )
    )
    candidate.edit_original_response = AsyncMock()

    await view.confirm_button.callback(candidate)  # pyright: ignore[reportUnknownMemberType]

    register.assert_not_awaited()
    assert store.get("d", owner_id=7) is not None
    edit_call = candidate.edit_original_response.await_args
    assert edit_call is not None
    assert "DM을 열지 못했습니다" in edit_call.kwargs["content"]


@pytest.mark.parametrize(
    "guild_id, channel_type", [(42, discord.ChannelType.text), (None, discord.ChannelType.group)]
)
async def test_registration_rejects_server_without_bot_and_group_dm(
    guild_id: int | None, channel_type: discord.ChannelType
) -> None:
    candidate = interaction(7)
    candidate.guild_id = guild_id
    candidate.guild = None
    candidate.channel = SimpleNamespace(type=channel_type)
    assert await channel_can_receive_alert(candidate, FakeService()) is False


def test_subscription_list_distinguishes_personal_dm_from_server_channel() -> None:
    summaries = [
        SubscriptionSummary("dm", "용산", date(2030, 1, 1), channel_id=123),
        SubscriptionSummary("server", "용산", date(2030, 1, 1), channel_id=456, guild_id=42),
    ]
    view = SubscriptionListView(owner_id=7, service=FakeService(), subscriptions=summaries)
    assert view.subscription_select is not None
    descriptions = [option.description or "" for option in view.subscription_select.options]
    assert "개인 DM" in descriptions[0]
    assert "채널 456" in descriptions[1]
