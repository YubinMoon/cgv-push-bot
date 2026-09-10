from pathlib import Path

import pytest

from cgv_push_bot.config import ConfigError, Settings


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "secret")
    for name in (
        "DATABASE_URL",
        "POLL_INTERVAL_SECONDS",
        "POLL_OFFSET_SECONDS",
        "LOG_LEVEL",
        "HISTORY_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults() -> None:
    settings = Settings.load(dotenv_path="/does/not/exist")
    assert settings.poll_interval_seconds == 300
    assert settings.poll_offset_seconds == 1
    assert settings.log_level == "INFO"
    assert settings.history_retention_days == 90
    assert settings.sqlite_path() == Path("data/movie-bot.sqlite3")


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("POLL_INTERVAL_SECONDS", "abc", "must be an integer"),
        ("POLL_INTERVAL_SECONDS", "59", "at least 60"),
        ("POLL_OFFSET_SECONDS", "abc", "must be an integer"),
        ("POLL_OFFSET_SECONDS", "-1", "must be at least 0"),
        ("POLL_OFFSET_SECONDS", "300", "less than POLL_INTERVAL_SECONDS"),
        ("HISTORY_RETENTION_DAYS", "abc", "must be an integer"),
        ("HISTORY_RETENTION_DAYS", "-1", "between 0 and 36500"),
        ("HISTORY_RETENTION_DAYS", "36501", "between 0 and 36500"),
        ("LOG_LEVEL", "TRACE", "LOG_LEVEL must be one of"),
    ],
)
def test_settings_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, message: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=message):
        Settings.load(dotenv_path="/does/not/exist")


def test_settings_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="DISCORD_TOKEN is required"):
        Settings.load(dotenv_path="/does/not/exist")


@pytest.mark.parametrize("days", [0, 30, 36500])
def test_history_retention_setting(monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    monkeypatch.setenv("HISTORY_RETENTION_DAYS", str(days))
    assert Settings.load(dotenv_path="/does/not/exist").history_retention_days == days
