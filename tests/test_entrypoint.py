from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import Coroutine
from contextlib import closing
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from cgv_push_bot.__main__ import main, migrate
from cgv_push_bot.config import Settings


def test_module_entrypoint_fails_before_network_without_token() -> None:
    environment = os.environ.copy()
    environment["DISCORD_TOKEN"] = ""
    result = subprocess.run(
        [sys.executable, "-m", "cgv_push_bot"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 2
    assert "DISCORD_TOKEN is required" in result.stderr


def test_packaged_migration_can_upgrade_sqlite(tmp_path: Path) -> None:
    database = tmp_path / "movie.sqlite3"
    migrate(f"sqlite+aiosqlite:///{database}")
    with closing(sqlite3.connect(database)) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {
            "monitor_targets",
            "subscriptions",
            "subscription_movies",
            "notifications",
        } <= names
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() is not None


def test_main_logs_service_lifecycle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = Settings("token", "sqlite+aiosqlite:///:memory:", 300, 2, "INFO")
    monkeypatch.setattr("cgv_push_bot.__main__.Settings.load", lambda: settings)

    def ignore_logging(_settings: Settings) -> None:
        pass

    monkeypatch.setattr("cgv_push_bot.__main__.configure_logging", ignore_logging)

    def close_coroutine(coroutine: Coroutine[Any, Any, None]) -> None:
        coroutine.close()

    monkeypatch.setattr("cgv_push_bot.__main__.asyncio.run", close_coroutine)
    caplog.set_level(logging.INFO, logger="cgv_push_bot.__main__")

    assert main() == 0
    assert "event=service_started poll_interval_seconds=300" in caplog.text
    assert "event=service_stopped" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["client", "bot", "start", "delivery_close", None])
async def test_run_releases_resources_on_initialization_and_shutdown_failures(
    monkeypatch: pytest.MonkeyPatch, failure_stage: str | None
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from cgv_push_bot.__main__ import run

    events: list[str] = []

    def record(name: str, *_args: object) -> None:
        events.append(name)
        if failure_stage == name:
            raise RuntimeError(name)

    engine = MagicMock()
    engine.dispose = AsyncMock(side_effect=lambda: record("engine_close"))
    gateway = MagicMock()
    gateway.close = AsyncMock(side_effect=lambda: record("gateway_close"))
    bot = MagicMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(side_effect=partial(record, "bot_close"))
    bot.start = AsyncMock(side_effect=partial(record, "start"))
    poller = MagicMock()
    poller.close = AsyncMock(side_effect=lambda: record("poller_close"))
    delivery = MagicMock()
    delivery.close = AsyncMock(side_effect=lambda: record("delivery_close"))

    def create_client() -> MagicMock:
        record("client")
        return MagicMock()

    def create_test_bot(_service: object) -> MagicMock:
        record("bot")
        return bot

    module = "cgv_push_bot.__main__"
    monkeypatch.setattr(f"{module}.migrate", MagicMock())
    monkeypatch.setattr(f"{module}.create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(f"{module}.CgvClient", create_client)
    monkeypatch.setattr(f"{module}.CgvGateway", MagicMock(return_value=gateway))
    monkeypatch.setattr(f"{module}.create_bot", create_test_bot)
    monkeypatch.setattr(f"{module}.Poller", MagicMock(return_value=poller))
    monkeypatch.setattr(f"{module}.DeliveryWorker", MagicMock(return_value=delivery))
    settings = Settings("token", "sqlite+aiosqlite:///:memory:", 300, 1, "INFO")

    if failure_stage is None:
        await run(settings)
    else:
        with pytest.raises(RuntimeError, match=failure_stage):
            await run(settings)

    if failure_stage == "client":
        assert events == ["client", "engine_close"]
    elif failure_stage == "bot":
        assert events == ["client", "bot", "gateway_close", "engine_close"]
    else:
        assert events == [
            "client",
            "bot",
            "start",
            "delivery_close",
            "poller_close",
            "bot_close",
            "gateway_close",
            "engine_close",
        ]
