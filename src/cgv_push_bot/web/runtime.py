from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Generator
from contextlib import contextmanager

import uvicorn

SERVER_SHUTDOWN_TIMEOUT = 10


class ApiServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


async def _serve(server: uvicorn.Server) -> None:
    try:
        await server.serve()
    except SystemExit:
        raise RuntimeError("API server failed to start") from None


async def _wait_for_shutdown(task: asyncio.Task[None]) -> BaseException | None:
    try:
        await task
    except BaseException as error:
        return error
    return None


async def _shutdown_server(
    server: uvicorn.Server, server_task: asyncio.Task[None]
) -> list[BaseException]:
    if server_task.done():
        error = await _wait_for_shutdown(server_task)
        return [] if error is None or isinstance(error, asyncio.CancelledError) else [error]

    server.should_exit = True
    try:
        await asyncio.wait_for(asyncio.shield(server_task), SERVER_SHUTDOWN_TIMEOUT)
    except TimeoutError:
        server_task.cancel()
        error = await _wait_for_shutdown(server_task)
        return [] if error is None or isinstance(error, asyncio.CancelledError) else [error]
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            raise
        return [error]
    return []


async def _cancel_bot(bot_task: asyncio.Task[None]) -> list[BaseException]:
    if not bot_task.done():
        bot_task.cancel()
    error = await _wait_for_shutdown(bot_task)
    return [] if error is None or isinstance(error, asyncio.CancelledError) else [error]


async def serve_with_bot(server: uvicorn.Server, bot_start: Awaitable[None]) -> None:
    server_task = asyncio.create_task(_serve(server))
    bot_task = asyncio.ensure_future(bot_start)

    try:
        done, _ = await asyncio.wait((server_task, bot_task), return_when=asyncio.FIRST_COMPLETED)
        finished = server_task if server_task in done else bot_task
        await finished
        name = "API server" if finished is server_task else "Discord bot"
        raise RuntimeError(f"{name} stopped unexpectedly")
    except BaseException as error:
        cleanup_errors = await _shutdown_server(server, server_task)
        cleanup_errors.extend(await _cancel_bot(bot_task))
        for cleanup_error in cleanup_errors:
            error.add_note(f"Background task cleanup failed: {type(cleanup_error).__name__}")
        raise


__all__ = ["ApiServer", "serve_with_bot"]
