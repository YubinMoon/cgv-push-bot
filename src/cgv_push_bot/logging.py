from __future__ import annotations

import logging

from .config import Settings, level_number


class _DiscordLogFilter(logging.Filter):
    """Keep Discord library severity signals without retaining payload details."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "discord" or record.name.startswith("discord."):
            record.msg = "event=discord_library_log"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=level_number(settings),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Drop debug/info payload dumps. Warnings and errors are retained, but the
    # handler filter strips their potentially sensitive arguments and tracebacks.
    logging.getLogger("discord").setLevel(logging.WARNING)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if not any(isinstance(item, _DiscordLogFilter) for item in handler.filters):
            handler.addFilter(_DiscordLogFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)
