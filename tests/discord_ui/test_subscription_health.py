# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from cgv_push_bot.discord_ui.protocols import AlertService, SubscriptionSummary
from cgv_push_bot.discord_ui.views.subscriptions import (
    SubscriptionListView,
    _format_last_success,
    _poll_health_description,
)


class FakeResponse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def is_done(self) -> bool:
        return False

    async def edit_message(self, **kwargs: object) -> None:
        self.calls.append(("edit", kwargs))


class FakeService:
    async def delete_subscription(self, *, user_id: int, subscription_id: str) -> None:
        return None


def _summary(
    *,
    last_success_at: datetime | None = None,
    poll_failed: bool = False,
    pending_notifications: int = 0,
    failed_notifications: int = 0,
) -> SubscriptionSummary:
    return SubscriptionSummary(
        "sub",
        "용산",
        date(2030, 1, 1),
        channel_id=123,
        last_success_at=last_success_at,
        poll_failed=poll_failed,
        pending_notifications=pending_notifications,
        failed_notifications=failed_notifications,
    )


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (
            _summary(last_success_at=datetime(2026, 9, 15, 3, 0), poll_failed=False),
            "마지막 조회 성공",
        ),
        (_summary(last_success_at=None, poll_failed=False), "첫 조회 대기 중"),
        (_summary(last_success_at=None, poll_failed=True), "최근 조회 실패"),
    ],
)
def test_poll_health_is_user_facing(summary: SubscriptionSummary, expected: str) -> None:
    description = _poll_health_description(summary)
    assert expected in description
    assert "RuntimeError" not in description


def test_last_success_naive_database_time_is_displayed_in_kst() -> None:
    assert _format_last_success(datetime(2026, 9, 15, 3, 0)) == "2026-09-15 12:00 KST"
    assert _format_last_success(datetime(2026, 9, 15, 3, 0, tzinfo=UTC)) == "2026-09-15 12:00 KST"


@pytest.mark.asyncio
async def test_subscription_detail_shows_health_and_delivery_counts() -> None:
    summary = _summary(
        last_success_at=datetime(2026, 9, 15, 3, 0),
        pending_notifications=2,
        failed_notifications=1,
    )
    view = SubscriptionListView(
        owner_id=7,
        service=cast(AlertService, FakeService()),
        subscriptions=[summary],
    )
    assert view.subscription_select is not None
    view.subscription_select._values = ["sub"]
    response = FakeResponse()
    interaction = SimpleNamespace(response=response, user=SimpleNamespace(id=7))

    await view._on_select(cast(Any, interaction))

    content = response.calls[0][1]["content"]
    assert isinstance(content, str)
    assert "마지막 조회 성공: 2026-09-15 12:00 KST" in content
    assert "알림 전송 대기: **2건**" in content
    assert "알림 전송 실패: **1건**" in content
    assert "RuntimeError" not in content
