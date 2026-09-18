from __future__ import annotations

import asyncio
from typing import cast

import pytest
import uvicorn

from cgv_push_bot.web.runtime import ApiServer, serve_with_bot


class FakeServer:
    def __init__(self) -> None:
        self.should_exit = False
        self.stopped = asyncio.Event()

    async def serve(self) -> None:
        while not self.should_exit:
            await asyncio.sleep(0)
        self.stopped.set()


def test_api_server_does_not_capture_signals() -> None:
    server = ApiServer(uvicorn.Config("example:app"))

    with server.capture_signals():
        pass


@pytest.mark.asyncio
async def test_server_normal_completion_cancels_bot() -> None:
    server = FakeServer()
    bot_cancelled = False

    async def bot() -> None:
        nonlocal bot_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            bot_cancelled = True
            raise

    server.should_exit = True
    with pytest.raises(RuntimeError, match="API server stopped unexpectedly"):
        await serve_with_bot(cast(uvicorn.Server, server), bot())

    assert bot_cancelled


@pytest.mark.asyncio
async def test_bot_normal_completion_shuts_down_server() -> None:
    server = FakeServer()

    async def bot() -> None:
        return

    with pytest.raises(RuntimeError, match="Discord bot stopped unexpectedly"):
        await serve_with_bot(cast(uvicorn.Server, server), bot())

    assert server.should_exit
    assert server.stopped.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("server"), SystemExit(1)])
async def test_server_failure_is_propagated_without_leaving_bot(
    failure: BaseException,
) -> None:
    bot_cancelled = False

    class FailingServer(FakeServer):
        async def serve(self) -> None:
            raise failure

    async def bot() -> None:
        nonlocal bot_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            bot_cancelled = True
            raise

    expected = RuntimeError if isinstance(failure, SystemExit) else type(failure)
    message = "API server failed to start" if isinstance(failure, SystemExit) else "server"
    with pytest.raises(expected, match=message):
        await serve_with_bot(cast(uvicorn.Server, FailingServer()), bot())

    assert bot_cancelled


@pytest.mark.asyncio
async def test_bot_failure_is_propagated_and_server_is_stopped() -> None:
    server = FakeServer()

    async def bot() -> None:
        raise RuntimeError("bot failure")

    with pytest.raises(RuntimeError, match="bot failure"):
        await serve_with_bot(cast(uvicorn.Server, server), bot())

    assert server.should_exit
    assert server.stopped.is_set()


@pytest.mark.asyncio
async def test_cancellation_drains_server_and_cancels_bot() -> None:
    server = FakeServer()
    bot_cancelled = False

    async def bot() -> None:
        nonlocal bot_cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            bot_cancelled = True
            raise

    task = asyncio.create_task(serve_with_bot(cast(uvicorn.Server, server), bot()))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert server.should_exit
    assert server.stopped.is_set()
    assert bot_cancelled
