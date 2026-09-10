from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from pathlib import Path

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
        delivery = DeliveryWorker(
            DeliveryService(
                sessions, DiscordNotificationSender(bot), subscription_lock=subscription_lock
            ),
        )
        resources.push_async_callback(delivery.close)

        async def start_workers() -> None:
            poller.start()
            delivery.start()

        bot.add_listener(start_workers, "on_ready")
        await bot.start(settings.discord_token)


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
