import asyncio
import threading
import time
from datetime import date
from unittest.mock import Mock

import pytest

from cgv_push_bot.cgv import Movie
from cgv_push_bot.cgv.gateway import CgvGateway


@pytest.mark.asyncio
async def test_gateway_runs_client_calls_serially() -> None:
    active = 0
    maximum = 0

    def get_movies(_: str, __: date) -> tuple[Movie, ...]:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        time.sleep(0.01)
        active -= 1
        return (Movie("1", "Movie"),)

    client = Mock()
    client.get_movies.side_effect = get_movies
    gateway = CgvGateway(client)
    await asyncio.gather(
        gateway.get_movies("1", date(2026, 8, 14)),
        gateway.get_movies("1", date(2026, 8, 14)),
    )
    assert maximum == 1


@pytest.mark.asyncio
async def test_cancelled_call_finishes_its_thread_before_client_close() -> None:
    started = threading.Event()
    release = threading.Event()

    def get_movies(_: str, __: date) -> tuple[Movie, ...]:
        started.set()
        release.wait(timeout=2)
        return ()

    client = Mock()
    client.get_movies.side_effect = get_movies
    gateway = CgvGateway(client)
    request = asyncio.create_task(gateway.get_movies("1", date(2026, 8, 14)))
    assert await asyncio.to_thread(started.wait, 2)
    request.cancel()
    close = asyncio.create_task(gateway.close())
    await asyncio.sleep(0)
    assert not close.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await request
    await close
    client.close.assert_called_once_with()
