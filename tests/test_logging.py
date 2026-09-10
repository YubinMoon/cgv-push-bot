from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from cgv_push_bot.config import Settings
from cgv_push_bot.logging import configure_logging


def test_logging_is_console_only_and_suppresses_discord_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    basic_config = Mock()
    monkeypatch.setattr(logging, "basicConfig", basic_config)
    discord_logger = logging.getLogger("discord")
    httpx_logger = logging.getLogger("httpx")
    root_handlers = tuple(logging.getLogger().handlers)
    previous_filters = {handler: tuple(handler.filters) for handler in root_handlers}
    previous_discord_level = discord_logger.level
    previous_httpx_level = httpx_logger.level
    settings = Settings("token", "sqlite+aiosqlite:///:memory:", 300, 2, "INFO")

    try:
        configure_logging(settings)

        basic_config.assert_called_once_with(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        assert discord_logger.level == logging.WARNING
        assert httpx_logger.level == logging.WARNING
        assert root_handlers
        record = logging.LogRecord(
            "discord.http",
            logging.WARNING,
            __file__,
            1,
            "POST /channels/%s/messages payload=%s",
            ("555666777", "secret content"),
            None,
        )
        assert root_handlers[0].filter(record)
        assert record.getMessage() == "event=discord_library_log"
    finally:
        for handler, filters in previous_filters.items():
            handler.filters[:] = filters
        discord_logger.setLevel(previous_discord_level)
        httpx_logger.setLevel(previous_httpx_level)
