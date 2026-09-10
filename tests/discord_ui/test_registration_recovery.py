# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportAttributeAccessIssue=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import discord
import pytest

from cgv_push_bot.discord_ui import DraftStore
from cgv_push_bot.discord_ui.protocols import AlertService, TheaterChoice
from cgv_push_bot.discord_ui.views.registration import (
    ConfirmationView,
    KeywordView,
    MoviePreviewRetryView,
    TheaterSearchModal,
    TheaterSearchRetryView,
    TheaterSelectView,
)


class FakeResponse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def defer(self, **kwargs: object) -> None:
        self.calls.append(("defer", kwargs))
        self._done = True

    async def edit_message(self, **kwargs: object) -> None:
        self.calls.append(("edit", kwargs))
        self._done = True

    async def send_message(self, content: str, **kwargs: object) -> None:
        self.calls.append((content, kwargs))
        self._done = True

    async def send_modal(self, modal: object) -> None:
        self.calls.append(("modal", {"modal": modal}))
        self._done = True


def interaction(user_id: int) -> Any:
    return SimpleNamespace(user=SimpleNamespace(id=user_id), response=FakeResponse())


class SearchService:
    def __init__(self, result: Sequence[TheaterChoice] | BaseException) -> None:
        self.result = result

    async def search_theaters(self, query: str) -> Sequence[TheaterChoice]:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class PreviewService:
    def __init__(self) -> None:
        self.fail = True

    async def list_current_movies(self, **kwargs: object) -> tuple[str, ...]:
        if self.fail:
            raise RuntimeError("temporary failure")
        return ("아바타",)


def prepared_store() -> DraftStore:
    store = DraftStore()
    store.create(draft_id="draft", owner_id=7, guild_id=None, channel_id=123)
    store.update(
        "draft",
        owner_id=7,
        theater_id="theater",
        theater_name="용산",
        show_date=date(2030, 1, 1),
    )
    return store


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [RuntimeError("temporary failure"), ()])
async def test_theater_search_failure_keeps_draft_and_offers_retry(
    result: Sequence[TheaterChoice] | BaseException,
) -> None:
    store = prepared_store()
    service = SearchService(result)
    modal = TheaterSearchModal(
        owner_id=7,
        service=cast(AlertService, service),
        draft_store=store,
        draft_id="draft",
        query="용산",
    )
    modal.query._value = "용산"
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()

    await modal.on_submit(candidate)

    edit_call = candidate.edit_original_response.await_args
    assert edit_call is not None
    retry_view = edit_call.kwargs["view"]
    assert isinstance(retry_view, TheaterSearchRetryView)
    assert store.get("draft", owner_id=7) is not None

    retry_interaction = interaction(7)
    await retry_view.retry_button.callback(retry_interaction)
    retry_modal = retry_interaction.response.calls[0][1]["modal"]
    assert isinstance(retry_modal, TheaterSearchModal)
    assert retry_modal.query.default == "용산"


@pytest.mark.asyncio
async def test_retry_rejects_expired_draft() -> None:
    store = prepared_store()
    view = TheaterSearchRetryView(
        owner_id=7,
        service=cast(AlertService, SearchService(())),
        draft_store=store,
        draft_id="draft",
        query="용산",
    )
    store.remove("draft", owner_id=7)
    candidate = interaction(7)

    await view.retry_button.callback(candidate)

    assert "만료" in candidate.response.calls[0][0]


def test_theater_results_are_paginated_without_dropping_choices() -> None:
    view = TheaterSelectView(
        owner_id=7,
        service=cast(AlertService, SearchService(())),
        draft_store=prepared_store(),
        draft_id="draft",
        choices=[TheaterChoice(str(index), f"극장 {index}") for index in range(51)],
    )

    assert view.page_count == 3
    assert len(view.select.options) == 25
    assert view.next_button.disabled is False


@pytest.mark.asyncio
async def test_theater_next_page_keeps_owner_and_exposes_remaining_choices() -> None:
    view = TheaterSelectView(
        owner_id=7,
        service=cast(AlertService, SearchService(())),
        draft_store=prepared_store(),
        draft_id="draft",
        choices=[TheaterChoice(str(index), f"극장 {index}") for index in range(30)],
    )
    candidate = interaction(7)

    await view.next_button.callback(candidate)

    replacement = candidate.response.calls[0][1]["view"]
    assert isinstance(replacement, TheaterSelectView)
    assert replacement.page == 1
    assert replacement.select.options[0].value == "25"
    assert replacement.draft_store.get("draft", owner_id=7) is not None


@pytest.mark.asyncio
async def test_movie_preview_failure_offers_retry_with_same_draft() -> None:
    store = prepared_store()
    service = PreviewService()
    view = KeywordView(
        owner_id=7,
        service=cast(AlertService, service),
        draft_store=store,
        draft_id="draft",
    )
    candidate = interaction(7)
    candidate.edit_original_response = AsyncMock()

    await view.no_keyword_button.callback(candidate)

    edit_call = candidate.edit_original_response.await_args
    assert edit_call is not None
    retry_view = edit_call.kwargs["view"]
    assert isinstance(retry_view, MoviePreviewRetryView)
    assert store.get("draft", owner_id=7) is not None

    service.fail = False
    retry_interaction = interaction(7)
    retry_interaction.edit_original_response = AsyncMock()
    await retry_view.retry_button.callback(retry_interaction)
    retry_edit_call = retry_interaction.edit_original_response.await_args
    assert retry_edit_call is not None
    assert retry_edit_call.kwargs["view"] is not None


@pytest.mark.asyncio
async def test_registration_failure_leaves_confirmation_retry_enabled() -> None:
    store = prepared_store()
    service = SimpleNamespace(
        can_send_alert=lambda channel: True,  # type: ignore[reportUnknownLambdaType]
        register_subscription=AsyncMock(side_effect=RuntimeError("temporary failure")),
    )
    view = ConfirmationView(
        owner_id=7,
        service=cast(AlertService, service),
        draft_store=store,
        draft_id="draft",
    )
    candidate = interaction(7)
    candidate.guild_id = None
    candidate.guild = None
    candidate.channel = SimpleNamespace(type=discord.ChannelType.private)
    candidate.user.create_dm = AsyncMock(return_value=SimpleNamespace(id=456))
    candidate.edit_original_response = AsyncMock()

    await view.confirm_button.callback(candidate)

    edit_call = candidate.edit_original_response.await_args
    assert edit_call is not None
    assert edit_call.kwargs["view"] is view
    assert view.confirm_button.label == "다시 시도"
    assert store.get("draft", owner_id=7) is not None
