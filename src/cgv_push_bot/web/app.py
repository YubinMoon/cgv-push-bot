# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Annotated, Protocol

from fastapi import (
    Cookie,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cgv_push_bot.alerts.service import MAX_INT4_ID, SubscriptionNotFoundError
from cgv_push_bot.db.models import Notification, Subscription

from .auth import SESSION_COOKIE, Session, SessionStore
from .models import (
    LoginRequest,
    NotificationDetail,
    NotificationResponse,
    OverviewResponse,
    PageResponse,
    SessionResponse,
    SubscriptionDetail,
    SubscriptionResponse,
)
from .repository import DashboardRepository

DashboardID = Annotated[int, Path(ge=1, le=MAX_INT4_ID)]


class NameResolver(Protocol):
    def resolve(self, kind: str, identifier: str) -> str | None: ...


class AdminService(Protocol):
    async def admin_delete_subscription(self, subscription_id: int) -> None: ...


class Delivery(Protocol):
    async def retry_failed(self, notification_id: int) -> None: ...


def create_app(
    *,
    sessions: async_sessionmaker[AsyncSession],
    service: AdminService,
    delivery: Delivery,
    names: NameResolver,
    is_ready: Callable[[], bool],
    password: str | None,
    cookie_secure: bool = False,
) -> FastAPI:
    repository = DashboardRepository(sessions)
    auth = SessionStore(password)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "요청 형식이 올바르지 않습니다."},
        )

    @app.middleware("http")
    async def disable_api_caching(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            key=SESSION_COOKIE,
            value=token,
            httponly=True,
            samesite="strict",
            secure=cookie_secure,
            path="/api",
        )

    def delete_session_cookie(response: Response) -> None:
        response.delete_cookie(key=SESSION_COOKIE, secure=cookie_secure, path="/api")

    def unauthorized() -> HTTPException:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증이 필요합니다.")

    def current_session(token: str | None) -> Session:
        session = auth.get(token)
        if session is None:
            raise unauthorized()
        return session

    def require_same_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        scheme = "https" if cookie_secure else request.url.scheme
        expected = f"{scheme}://{request.url.netloc}"
        if origin is None or origin.rstrip("/") != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="허용되지 않은 요청입니다."
            )

    def require_mutation(
        request: Request,
        token: str | None,
        csrf_token: str | None,
    ) -> Session:
        session = current_session(token)
        require_same_origin(request)
        if not auth.valid_csrf(session, csrf_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="허용되지 않은 요청입니다."
            )
        return session

    @app.post("/api/auth/login", response_model=SessionResponse)
    async def login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> SessionResponse:
        require_same_origin(request)
        if not auth.enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="인증이 설정되지 않았습니다.",
            )
        result = auth.authenticate(payload.password)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="비밀번호가 올바르지 않습니다."
            )
        token, session = result
        set_session_cookie(response, token)
        return SessionResponse(csrf_token=session.csrf_token)

    @app.get("/api/auth/session", response_model=SessionResponse)
    async def session_status(
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> SessionResponse:
        session = current_session(dashboard_session)
        return SessionResponse(csrf_token=session.csrf_token)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        response: Response,
        x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Response:
        require_mutation(request, dashboard_session, x_csrf_token)
        auth.revoke(dashboard_session)
        delete_session_cookie(response)
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @app.get("/api/overview", response_model=OverviewResponse)
    async def overview(
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> OverviewResponse:
        current_session(dashboard_session)
        values = await repository.overview()
        return OverviewResponse(bot_connected=is_ready(), **values)

    @app.get("/api/subscriptions", response_model=PageResponse[SubscriptionResponse])
    async def subscriptions(
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
        page: int = Query(default=1, ge=1, le=2_147_483_647),
        page_size: int = Query(default=25, ge=1, le=100),
        status_filter: str | None = Query(default=None, alias="status"),
        user_id: str | None = None,
        guild_id: str | None = None,
        channel_id: str | None = None,
        theater_id: str | None = None,
        show_date: date | None = None,
        keyword: str | None = None,
    ) -> PageResponse[SubscriptionResponse]:
        current_session(dashboard_session)
        _check_status(status_filter, ("active", "expired"))
        rows, total = await repository.list_subscriptions(
            page=page,
            page_size=page_size,
            status=status_filter,
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
            theater_id=theater_id,
            show_date=show_date,
            keyword=keyword,
        )
        return PageResponse(
            items=[_subscription_response(row, names) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/subscriptions/{subscription_id}", response_model=SubscriptionDetail)
    async def subscription_detail(
        subscription_id: DashboardID,
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> SubscriptionDetail:
        current_session(dashboard_session)
        subscription = await repository.get_subscription(subscription_id)
        if subscription is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="알림을 찾을 수 없습니다."
            )
        result = _subscription_response(subscription, names)
        notifications = [
            _notification_response(item, names, parent=subscription)
            for item in subscription.notifications
        ]
        return SubscriptionDetail(
            **result.model_dump(),
            movies=[movie.movie_title for movie in subscription.movies],
            notifications=notifications,
        )

    @app.delete("/api/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_subscription(
        subscription_id: DashboardID,
        request: Request,
        response: Response,
        x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Response:
        require_mutation(request, dashboard_session, x_csrf_token)
        try:
            await service.admin_delete_subscription(subscription_id)
        except SubscriptionNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="알림을 찾을 수 없습니다."
            ) from error
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    @app.get("/api/notifications", response_model=PageResponse[NotificationResponse])
    async def notifications(
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
        page: int = Query(default=1, ge=1, le=2_147_483_647),
        page_size: int = Query(default=25, ge=1, le=100),
        status_filter: str | None = Query(default=None, alias="status"),
        subscription_id: int | None = Query(default=None, ge=1, le=MAX_INT4_ID),
    ) -> PageResponse[NotificationResponse]:
        current_session(dashboard_session)
        _check_status(status_filter, ("pending", "sent", "failed"))
        rows, total = await repository.list_notifications(
            page=page,
            page_size=page_size,
            status=status_filter,
            subscription_id=subscription_id,
        )
        return PageResponse(
            items=[_notification_response(row, names) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    @app.get("/api/notifications/{notification_id}", response_model=NotificationDetail)
    async def notification_detail(
        notification_id: DashboardID,
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> NotificationDetail:
        current_session(dashboard_session)
        notification = await repository.get_notification(notification_id)
        if notification is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="알림을 찾을 수 없습니다."
            )
        return NotificationDetail(**_notification_response(notification, names).model_dump())

    @app.post(
        "/api/notifications/{notification_id}/retry",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def retry_notification(
        notification_id: DashboardID,
        request: Request,
        response: Response,
        x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
        dashboard_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> Response:
        require_mutation(request, dashboard_session, x_csrf_token)
        try:
            await delivery.retry_failed(notification_id)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="알림을 찾을 수 없습니다."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="현재 상태에서는 재시도할 수 없습니다."
            ) from error
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    return app


def _check_status(value: str | None, allowed: tuple[str, ...]) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="유효하지 않은 상태입니다."
        )


def _subscription_response(subscription: Subscription, names: NameResolver) -> SubscriptionResponse:
    target = subscription.target
    return SubscriptionResponse(
        id=str(subscription.id),
        user_id=subscription.discord_user_id,
        guild_id=subscription.guild_id,
        channel_id=subscription.channel_id,
        user_name=_resolve_name(names, "user", subscription.discord_user_id),
        guild_name=_resolve_name(names, "guild", subscription.guild_id),
        channel_name=_resolve_name(names, "channel", subscription.channel_id),
        theater_id=target.theater_id,
        theater_name=target.theater_name,
        show_date=target.show_date,
        keyword=subscription.keyword,
        status=str(subscription.status),
        created_at=_required_utc(subscription.created_at),
        expires_at=_utc(subscription.expires_at),
        last_success_at=_utc(target.last_success_at),
        last_error=target.last_error,
        pending_count=sum(
            1 for item in subscription.notifications if str(item.status) == "pending"
        ),
        failed_count=sum(1 for item in subscription.notifications if str(item.status) == "failed"),
    )


def _notification_response(
    notification: Notification,
    names: NameResolver,
    *,
    parent: Subscription | None = None,
) -> NotificationResponse:
    subscription = parent or notification.subscription
    target = subscription.target
    return NotificationResponse(
        id=str(notification.id),
        subscription_id=str(subscription.id),
        status=str(notification.status),
        attempts=notification.attempts,
        last_error=notification.last_error,
        created_at=_required_utc(notification.created_at),
        sent_at=_utc(notification.sent_at),
        next_retry_at=_utc(notification.next_retry_at),
        movie_titles=[movie.movie_title for movie in notification.movies],
        user_id=subscription.discord_user_id,
        user_name=_resolve_name(names, "user", subscription.discord_user_id),
        guild_id=subscription.guild_id,
        guild_name=_resolve_name(names, "guild", subscription.guild_id),
        channel_id=subscription.channel_id,
        channel_name=_resolve_name(names, "channel", subscription.channel_id),
        theater_name=target.theater_name,
        show_date=target.show_date,
        keyword=subscription.keyword,
    )


def _resolve_name(names: NameResolver, kind: str, identifier: str | None) -> str | None:
    if identifier is None:
        return None
    try:
        return names.resolve(kind, identifier)
    except Exception:
        return None


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    result = _utc(value)
    assert result is not None
    return result


__all__ = ["NameResolver", "create_app"]
