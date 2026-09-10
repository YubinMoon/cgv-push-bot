from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

SQLITE_BUSY_TIMEOUT_MS = 5_000


def create_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """Configure SQLite pragmas on every pooled DB-API connection."""

    if not database_url.strip():
        raise ValueError("database_url must not be empty")

    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        # aiosqlite accepts timeout as a sqlite3 connection argument.  The
        # PRAGMA below is retained as the authoritative setting for pooled
        # connections.
        connect_args["timeout"] = SQLITE_BUSY_TIMEOUT_MS / 1000

    engine = create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=pool_pre_ping,
        connect_args=connect_args,
    )

    if database_url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

    return engine


def create_session_factory(
    engine: AsyncEngine,
    *,
    expire_on_commit: bool = False,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=expire_on_commit,
        autoflush=True,
    )


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transaction-backed session and roll back on failure.

    A successful scope commits once.  Callers that need multiple independent
    transactions should create separate scopes; callers that need finer
    control can use the factory directly.
    """

    async with session_factory() as session:
        try:
            async with session.begin():
                yield session
        except BaseException:
            # ``session.begin`` already rolls back.  Keeping this explicit
            # makes the ownership contract clear for cancellation paths.
            await session.rollback()
            raise


async def close_engine(engine: AsyncEngine) -> None:
    await engine.dispose()


def _configure_sqlite_connection(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


__all__ = [
    "SQLITE_BUSY_TIMEOUT_MS",
    "close_engine",
    "create_engine",
    "create_session_factory",
    "session_scope",
]
