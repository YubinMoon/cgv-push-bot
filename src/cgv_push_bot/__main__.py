from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config as AlembicConfig

from .alerts.delivery import DeliveryService, DeliveryWorker
from .alerts.poller import Poller
from .alerts.service import MovieAlertService
from .cgv import CgvClient
from .cgv.gateway import CgvGateway
from .config import ConfigError, Settings
from .db.session import create_engine, create_session_factory
from .discord_ui.bot import create_bot
from .discord_ui.notifications import DiscordNotificationSender
from .logging import configure_logging
from .web.app import create_app
from .web.names import DiscordNameResolver
from .web.runtime import ApiServer, serve_with_bot

LOGGER = logging.getLogger(__name__)


def migrate(database_url: str) -> None:
    configuration = AlembicConfig()
    configuration.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parent / "db" / "migrations"),
    )
    configuration.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(configuration, "head")


async def run(settings: Settings) -> None:
    sqlite_path = settings.sqlite_path()
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(migrate, settings.database_url)

    async with AsyncExitStack() as resources:
        engine = create_engine(settings.database_url)
        resources.push_async_callback(engine.dispose)
        gateway = CgvGateway(CgvClient())
        resources.push_async_callback(gateway.close)
        sessions = create_session_factory(engine)
        subscription_lock = asyncio.Lock()
        service = MovieAlertService(
            sessions,
            gateway,
            poll_interval_seconds=settings.poll_interval_seconds,
            poll_offset_seconds=settings.poll_offset_seconds,
            history_retention_days=settings.history_retention_days,
            subscription_lock=subscription_lock,
        )
        bot = create_bot(service)
        await resources.enter_async_context(bot)
        poller = Poller(
            service,
            settings.poll_interval_seconds,
            settings.poll_offset_seconds,
        )
        resources.push_async_callback(poller.close)
        delivery_service = DeliveryService(
            sessions, DiscordNotificationSender(bot), subscription_lock=subscription_lock
        )
        delivery = DeliveryWorker(delivery_service)
        resources.push_async_callback(delivery.close)

        async def start_workers() -> None:
            poller.start()
            delivery.start()

        bot.add_listener(start_workers, "on_ready")
        if not settings.dashboard_password:
            await bot.start(settings.discord_token)
            return
        names = DiscordNameResolver(bot)
        resources.push_async_callback(names.close)
        app = create_app(
            sessions=sessions,
            service=service,
            delivery=delivery_service,
            names=names,
            is_ready=bot.is_ready,
            password=settings.dashboard_password,
            cookie_secure=settings.dashboard_cookie_secure,
        )
        server = ApiServer(
            uvicorn.Config(
                app,
                host="0.0.0.0",
                port=8000,
                workers=1,
                access_log=False,
                log_config=None,
                proxy_headers=False,
                timeout_graceful_shutdown=5,
            )
        )
        await serve_with_bot(server, bot.start(settings.discord_token))


def main() -> int:
    try:
        settings = Settings.load()
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    configure_logging(settings)
    LOGGER.info(
        "event=service_started poll_interval_seconds=%s",
        settings.poll_interval_seconds,
    )
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    finally:
        LOGGER.info("event=service_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
