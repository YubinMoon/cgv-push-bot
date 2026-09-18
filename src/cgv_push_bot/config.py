from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    database_url: str
    poll_interval_seconds: int
    poll_offset_seconds: int
    log_level: str
    history_retention_days: int = 90
    dashboard_password: str = field(default="", repr=False)
    dashboard_cookie_secure: bool = False

    @classmethod
    def load(cls, *, dotenv_path: str | Path | None = None) -> Settings:
        load_dotenv(dotenv_path=dotenv_path, override=False)
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is required and must not be empty")

        poll_interval = _integer(
            os.getenv("POLL_INTERVAL_SECONDS", "300"),
            "POLL_INTERVAL_SECONDS",
        )
        if poll_interval < 60:
            raise ConfigError("POLL_INTERVAL_SECONDS must be at least 60")
        poll_offset = _integer(
            os.getenv("POLL_OFFSET_SECONDS", "1"),
            "POLL_OFFSET_SECONDS",
        )
        if not 0 <= poll_offset < poll_interval:
            raise ConfigError(
                "POLL_OFFSET_SECONDS must be at least 0 and less than POLL_INTERVAL_SECONDS"
            )

        retention_days = _integer(
            os.getenv("HISTORY_RETENTION_DAYS", "90"), "HISTORY_RETENTION_DAYS"
        )
        if not 0 <= retention_days <= 36_500:
            raise ConfigError("HISTORY_RETENTION_DAYS must be between 0 and 36500")

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        valid_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if log_level not in valid_levels:
            raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(sorted(valid_levels))}")

        database_url = os.getenv(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./data/movie-bot.sqlite3",
        ).strip()
        if not database_url:
            raise ConfigError("DATABASE_URL must not be empty")
        cookie_secure = os.getenv("DASHBOARD_COOKIE_SECURE", "false").strip().lower()
        if cookie_secure not in {"true", "false"}:
            raise ConfigError("DASHBOARD_COOKIE_SECURE must be true or false")
        password = os.getenv("DASHBOARD_PASSWORD", "")
        if len(password) > 1_024:
            raise ConfigError("DASHBOARD_PASSWORD must be at most 1024 characters")
        return cls(
            token,
            database_url,
            poll_interval,
            poll_offset,
            log_level,
            retention_days,
            password if password.strip() else "",
            cookie_secure == "true",
        )

    def sqlite_path(self) -> Path | None:
        parsed = urlparse(self.database_url)
        if parsed.scheme != "sqlite+aiosqlite":
            return None
        raw_path = unquote(parsed.path)
        if raw_path in {"", "/:memory:"}:
            return None
        if raw_path.startswith("//"):
            return Path(raw_path[1:])
        return Path(raw_path.removeprefix("/"))


def _integer(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ConfigError(f"{name} must be an integer") from error


def level_number(settings: Settings) -> int:
    return int(getattr(logging, settings.log_level))
