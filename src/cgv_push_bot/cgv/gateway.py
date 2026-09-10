from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date

from .client import CgvClient
from .models import Movie, Theater


class CgvGateway:
    """Serialize access to one client and run blocking calls off the event loop."""

    def __init__(self, client: CgvClient) -> None:
        self._client = client
        self._lock = asyncio.Lock()

    async def search_theaters(self, query: str) -> tuple[Theater, ...]:
        async with self._lock:
            return await _finish_thread_on_cancellation(self._client.search_theaters, query)

    async def get_movies(self, theater_id: str, show_date: date) -> tuple[Movie, ...]:
        async with self._lock:
            return await _finish_thread_on_cancellation(
                self._client.get_movies, theater_id, show_date
            )

    async def close(self) -> None:
        async with self._lock:
            await _finish_thread_on_cancellation(self._client.close)


async def _finish_thread_on_cancellation[**P, T](
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Keep the gateway lock held until a cancelled worker thread actually finishes."""

    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
