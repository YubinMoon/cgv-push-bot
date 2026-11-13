from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any, cast

import httpx
import pytest

from cgv_push_bot.db.base import Base
from cgv_push_bot.db.models import (
    MonitorTarget,
    Notification,
    NotificationStatus,
    Subscription,
    SubscriptionMovie,
    SubscriptionStatus,
)
from cgv_push_bot.db.session import create_engine, create_session_factory
from cgv_push_bot.web.app import create_app


class Names:
    def resolve(self, kind: str, identifier: str) -> str | None:
        return {("user", "10"): "홍길동", ("guild", "20"): "영화 서버"}.get((kind, identifier))


class Service:
    def __init__(self) -> None:
        self.deleted: list[int] = []

    async def admin_delete_subscription(self, subscription_id: int) -> None:
        self.deleted.append(subscription_id)


class Delivery:
    def __init__(self) -> None:
        self.retried: list[int] = []

    async def retry_failed(self, notification_id: int) -> None:
        self.retried.append(notification_id)


@pytest.fixture
async def app_parts() -> AsyncIterator[tuple[Any, Service, Delivery]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    async with sessions() as session, session.begin():
        target = MonitorTarget(
            theater_id="T1",
            theater_name="용산",
            show_date=date(2026, 9, 18),
            last_success_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        session.add(target)
        await session.flush()
        subscription = Subscription(
            discord_user_id="10",
            guild_id="20",
            channel_id="30",
            target_id=target.id,
            keyword="듄",
        )
        session.add(subscription)
        await session.flush()
        notification = Notification(
            subscription_id=subscription.id,
            status=NotificationStatus.FAILED,
            attempts=2,
        )
        session.add(notification)
        await session.flush()
        session.add(
            SubscriptionMovie(
                subscription_id=subscription.id,
                movie_id="M1",
                movie_title="듄",
                notification_id=notification.id,
            )
        )
    service = Service()
    delivery = Delivery()
    app = create_app(
        sessions=sessions,
        service=service,
        delivery=delivery,
        names=Names(),
        is_ready=lambda: True,
        password="secret",
    )
    try:
        yield app, service, delivery
    finally:
        await engine.dispose()


@pytest.fixture
async def empty_app_parts() -> AsyncIterator[tuple[Any, Service, Delivery]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    service = Service()
    delivery = Delivery()
    app = create_app(
        sessions=sessions,
        service=service,
        delivery=delivery,
        names=Names(),
        is_ready=lambda: True,
        password="secret",
    )
    try:
        yield app, service, delivery
    finally:
        await engine.dispose()


@pytest.fixture
async def many_app_parts() -> AsyncIterator[tuple[Any, Service, Delivery]]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = create_session_factory(engine)
    async with sessions() as session, session.begin():
        first_target = MonitorTarget(
            theater_id="T1",
            theater_name="용산",
            show_date=date(2026, 9, 18),
            last_success_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        second_target = MonitorTarget(
            theater_id="T2",
            theater_name="강남",
            show_date=date(2026, 9, 19),
            last_error="poll failed",
            error_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        session.add_all([first_target, second_target])
        await session.flush()
        first_subscription = Subscription(
            discord_user_id="10",
            guild_id="20",
            channel_id="30",
            target_id=first_target.id,
            keyword="듄",
            status=SubscriptionStatus.ACTIVE,
        )
        second_subscription = Subscription(
            discord_user_id="11",
            guild_id="21",
            channel_id="31",
            target_id=second_target.id,
            keyword="아바타",
            status=SubscriptionStatus.EXPIRED,
        )
        session.add_all([first_subscription, second_subscription])
        await session.flush()
        session.add_all(
            [
                Notification(
                    subscription_id=first_subscription.id,
                    status=NotificationStatus.PENDING,
                ),
                Notification(
                    subscription_id=first_subscription.id,
                    status=NotificationStatus.SENT,
                ),
                Notification(
                    subscription_id=second_subscription.id,
                    status=NotificationStatus.FAILED,
                ),
            ]
        )
    service = Service()
    delivery = Delivery()
    app = create_app(
        sessions=sessions,
        service=service,
        delivery=delivery,
        names=Names(),
        is_ready=lambda: True,
        password="secret",
    )
    try:
        yield app, service, delivery
    finally:
        await engine.dispose()


async def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _login(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"password": "secret"},
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


@pytest.mark.asyncio
async def test_login_protects_dashboard_and_returns_names(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    async with await _client(app) as client:
        assert (await client.get("/api/overview")).status_code == 401
        csrf = await _login(client)
        overview = await client.get("/api/overview")
        subscriptions = await client.get("/api/subscriptions?status=active")
        detail = await client.get("/api/subscriptions/1")

    assert overview.json()["bot_connected"] is True
    assert overview.json()["failed_notifications"] == 1
    item = subscriptions.json()["items"][0]
    assert item["user_name"] == "홍길동"
    assert item["guild_name"] == "영화 서버"
    assert item["id"] == "1"
    assert detail.status_code == 200
    assert detail.json()["notifications"][0]["movie_titles"] == ["듄"]
    assert csrf


@pytest.mark.asyncio
async def test_overview_counts_empty_tables(
    empty_app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = empty_app_parts
    async with await _client(app) as client:
        await _login(client)
        response = await client.get("/api/overview")

    assert response.status_code == 200
    assert response.json() == {
        "bot_connected": True,
        "active_subscriptions": 0,
        "expired_subscriptions": 0,
        "poll_errors": 0,
        "pending_notifications": 0,
        "sent_notifications": 0,
        "failed_notifications": 0,
    }


@pytest.mark.asyncio
async def test_overview_and_lists_have_independent_counts_and_filters(
    many_app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = many_app_parts
    async with await _client(app) as client:
        await _login(client)
        overview = await client.get("/api/overview")
        subscriptions_page_one = await client.get("/api/subscriptions?page=1&page_size=1")
        subscriptions_page_two = await client.get("/api/subscriptions?page=2&page_size=1")
        active_subscriptions = await client.get("/api/subscriptions?status=active")
        notifications_page_one = await client.get("/api/notifications?page=1&page_size=2")
        notifications_page_two = await client.get("/api/notifications?page=2&page_size=2")
        failed_notifications = await client.get("/api/notifications?status=failed")
        subscription_notifications = await client.get("/api/notifications?subscription_id=1")

    assert overview.json() == {
        "bot_connected": True,
        "active_subscriptions": 1,
        "expired_subscriptions": 1,
        "poll_errors": 1,
        "pending_notifications": 1,
        "sent_notifications": 1,
        "failed_notifications": 1,
    }
    assert subscriptions_page_one.json()["total"] == 2
    assert subscriptions_page_one.json()["page"] == 1
    assert subscriptions_page_one.json()["page_size"] == 1
    assert len(subscriptions_page_one.json()["items"]) == 1
    assert subscriptions_page_two.json()["total"] == 2
    assert len(subscriptions_page_two.json()["items"]) == 1
    assert active_subscriptions.json()["total"] == 1
    assert active_subscriptions.json()["items"][0]["status"] == "active"
    assert notifications_page_one.json()["total"] == 3
    assert len(notifications_page_one.json()["items"]) == 2
    assert len(notifications_page_two.json()["items"]) == 1
    assert failed_notifications.json()["total"] == 1
    assert failed_notifications.json()["items"][0]["status"] == "failed"
    assert subscription_notifications.json()["total"] == 2


@pytest.mark.asyncio
async def test_missing_details_return_not_found(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    async with await _client(app) as client:
        await _login(client)
        subscription = await client.get("/api/subscriptions/999")
        notification = await client.get("/api/notifications/999")
        invalid_subscription_status = await client.get("/api/subscriptions?status=unknown")
        invalid_notification_status = await client.get("/api/notifications?status=unknown")

    assert subscription.status_code == 404
    assert notification.status_code == 404
    assert invalid_subscription_status.status_code == 422
    assert invalid_notification_status.status_code == 422


@pytest.mark.asyncio
async def test_all_dashboard_routes_require_authentication(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    async with await _client(app) as client:
        responses = [
            await client.get("/api/overview"),
            await client.get("/api/subscriptions"),
            await client.get("/api/subscriptions/1"),
            await client.get("/api/notifications"),
            await client.get("/api/notifications/1"),
            await client.delete("/api/subscriptions/1", headers={"Origin": "http://test"}),
            await client.post("/api/notifications/1/retry", headers={"Origin": "http://test"}),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)


@pytest.mark.asyncio
async def test_mutations_require_csrf_and_same_origin(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, service, delivery = app_parts
    async with await _client(app) as client:
        csrf = await _login(client)
        assert (
            await client.post("/api/notifications/1/retry", headers={"Origin": "http://test"})
        ).status_code == 403
        response = await client.post(
            "/api/notifications/1/retry",
            headers={"Origin": "http://test", "X-CSRF-Token": csrf},
        )

    assert response.status_code == 204
    assert delivery.retried == [1]
    assert service.deleted == []


@pytest.mark.asyncio
async def test_login_and_mutations_reject_cross_origin_requests(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, delivery = app_parts
    async with await _client(app) as client:
        cross_origin_login = await client.post(
            "/api/auth/login",
            json={"password": "secret"},
            headers={"Origin": "http://evil"},
        )
        csrf = await _login(client)
        cross_origin_retry = await client.post(
            "/api/notifications/1/retry",
            headers={"Origin": "http://evil", "X-CSRF-Token": csrf},
        )

    assert cross_origin_login.status_code == 403
    assert cross_origin_retry.status_code == 403
    assert delivery.retried == []


@pytest.mark.asyncio
async def test_logout_invalidates_session(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    async with await _client(app) as client:
        csrf = await _login(client)
        logout = await client.post(
            "/api/auth/logout",
            headers={"Origin": "http://test", "X-CSRF-Token": csrf},
        )
        session = await client.get("/api/auth/session")
        overview = await client.get("/api/overview")

    assert logout.status_code == 204
    assert session.status_code == 401
    assert overview.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("oversized", ["2147483648", "3000000000", "9223372036854775808"])
async def test_dashboard_ids_reject_values_outside_database_integer_range(
    app_parts: tuple[Any, Service, Delivery],
    oversized: str,
) -> None:
    app, service, delivery = app_parts
    async with await _client(app) as client:
        csrf = await _login(client)
        mutation_headers = {"Origin": "http://test", "X-CSRF-Token": csrf}
        responses = [
            await client.get(f"/api/subscriptions/{oversized}"),
            await client.delete(f"/api/subscriptions/{oversized}", headers=mutation_headers),
            await client.get(f"/api/notifications/{oversized}"),
            await client.post(f"/api/notifications/{oversized}/retry", headers=mutation_headers),
            await client.get(f"/api/notifications?subscription_id={oversized}"),
        ]

    assert [response.status_code for response in responses] == [422] * len(responses)
    assert service.deleted == []
    assert delivery.retried == []


@pytest.mark.asyncio
async def test_dashboard_ids_accept_database_integer_maximum(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, service, delivery = app_parts
    maximum = 2_147_483_647
    async with await _client(app) as client:
        csrf = await _login(client)
        mutation_headers = {"Origin": "http://test", "X-CSRF-Token": csrf}
        subscription = await client.get(f"/api/subscriptions/{maximum}")
        notification = await client.get(f"/api/notifications/{maximum}")
        filtered = await client.get(f"/api/notifications?subscription_id={maximum}")
        deleted = await client.delete(f"/api/subscriptions/{maximum}", headers=mutation_headers)
        retried = await client.post(f"/api/notifications/{maximum}/retry", headers=mutation_headers)

    assert subscription.status_code == 404
    assert notification.status_code == 404
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0
    assert deleted.status_code == 204
    assert retried.status_code == 204
    assert service.deleted == [maximum]
    assert delivery.retried == [maximum]


@pytest.mark.asyncio
async def test_page_numbers_reject_values_outside_database_integer_range(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    oversized = "2147483648"
    async with await _client(app) as client:
        responses = [
            await client.get(f"/api/notifications?page={oversized}"),
            await client.get(f"/api/subscriptions?page={oversized}"),
        ]

    assert [response.status_code for response in responses] == [422] * len(responses)


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_password(
    app_parts: tuple[Any, Service, Delivery],
) -> None:
    app, _service, _delivery = app_parts
    async with await _client(app) as client:
        wrong_type = await client.post(
            "/api/auth/login",
            json={"password": {"secret": "do-not-echo"}},
            headers={"Origin": "http://test"},
        )
        oversized = await client.post(
            "/api/auth/login",
            json={"password": "x" * 1_025},
            headers={"Origin": "http://test"},
        )

    assert wrong_type.status_code == 422
    assert oversized.status_code == 422
    assert "do-not-echo" not in wrong_type.text
    assert "x" * 1_025 not in oversized.text
    assert wrong_type.json() == {"detail": "요청 형식이 올바르지 않습니다."}


@pytest.mark.asyncio
async def test_secure_cookie_accepts_https_origin_behind_http_proxy() -> None:
    app = create_app(
        sessions=cast(Any, None),
        service=Service(),
        delivery=Delivery(),
        names=Names(),
        is_ready=lambda: True,
        password="secret",
        cookie_secure=True,
    )
    async with await _client(app) as client:
        response = await client.post(
            "/api/auth/login",
            json={"password": "secret"},
            headers={"Origin": "https://test"},
        )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
