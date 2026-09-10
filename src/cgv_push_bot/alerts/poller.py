from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from .scheduling import next_poll_slot
from .service import MovieAlertService

LOGGER = logging.getLogger(__name__)


class Poller:
    def __init__(
        self,
        service: MovieAlertService,
        interval_seconds: int,
        offset_seconds: int,
    ) -> None:
        self._service = service
        self._interval = interval_seconds
        self._offset = offset_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="movie-poller")

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            now = datetime.now(UTC)
            next_slot = next_poll_slot(
                now,
                interval_seconds=self._interval,
                offset_seconds=self._offset,
            )
            await asyncio.sleep((next_slot - now).total_seconds())
            try:
                await self._service.poll_once(now=next_slot)
            except Exception as error:
                LOGGER.error(
                    "event=poll_worker_failed error_type=%s",
                    type(error).__name__,
                )
