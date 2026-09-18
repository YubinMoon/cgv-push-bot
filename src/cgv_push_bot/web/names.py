from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NameKind = str
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    name: str | None
    expires_at: float


class DiscordNameResolver:
    """Resolve Discord IDs without making the dashboard request wait on Discord."""

    _KINDS = frozenset(("user", "guild", "channel"))
    _MAX_DISCORD_ID = 2**64 - 1

    def __init__(
        self,
        client: Any,
        *,
        success_ttl: float = 15 * 60,
        failure_ttl: float = 60,
        max_cache_entries: int = 5_000,
        max_pending: int = 100,
        max_concurrent_fetches: int = 3,
        fetch_timeout: float = 5,
        clock: Clock = time.monotonic,
    ) -> None:
        if success_ttl <= 0 or failure_ttl <= 0 or fetch_timeout <= 0:
            raise ValueError("TTLs and fetch timeout must be positive")
        if max_cache_entries <= 0 or max_pending <= 0 or max_concurrent_fetches <= 0:
            raise ValueError("cache and task limits must be positive")

        self._client = client
        self._success_ttl = success_ttl
        self._failure_ttl = failure_ttl
        self._max_cache_entries = max_cache_entries
        self._max_pending = max_pending
        self._fetch_timeout = fetch_timeout
        self._clock = clock
        self._cache: OrderedDict[tuple[NameKind, str], _CacheEntry] = OrderedDict()
        self._pending: dict[tuple[NameKind, str], asyncio.Task[None]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_fetches)
        self._closed = False

    def resolve(self, kind: NameKind, identifier: str) -> str | None:
        """Return a known name and schedule a lookup when one is unavailable."""
        key = self._key(kind, identifier)
        if key is None:
            return None

        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None:
            if cached.expires_at > now and cached.name is not None:
                self._cache.move_to_end(key)
                return cached.name
            if cached.expires_at <= now:
                del self._cache[key]

        name = self._cached_name(*key)
        if name is not None:
            self._remember(key, name, now + self._success_ttl)
            return name

        if cached is not None and cached.expires_at > now:
            return None

        if self._closed or not self._is_ready() or key in self._pending:
            return None
        if len(self._pending) >= self._max_pending:
            return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        self._pending[key] = loop.create_task(self._fetch(key))
        return None

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._pending.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._pending.clear()

    def _key(self, kind: NameKind, identifier: str) -> tuple[NameKind, str] | None:
        if kind not in self._KINDS or not identifier.isascii() or not identifier.isdecimal():
            return None
        try:
            value = int(identifier)
        except ValueError:
            return None
        if value <= 0 or value > self._MAX_DISCORD_ID:
            return None
        return kind, str(value)

    def _cached_name(self, kind: NameKind, identifier: str) -> str | None:
        try:
            object_ = getattr(self._client, f"get_{kind}")(int(identifier))
        except Exception:
            return None
        return self._name_from_object(object_, kind)

    async def _fetch(self, key: tuple[NameKind, str]) -> None:
        try:
            async with self._semaphore:
                object_ = await asyncio.wait_for(
                    self._fetch_object(*key),
                    timeout=self._fetch_timeout,
                )
            name = self._name_from_object(object_, key[0])
            expires_in = self._success_ttl if name is not None else self._failure_ttl
            self._remember(key, name, self._clock() + expires_in)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._remember(key, None, self._clock() + self._failure_ttl)
        finally:
            task = asyncio.current_task()
            if self._pending.get(key) is task:
                del self._pending[key]

    async def _fetch_object(self, kind: NameKind, identifier: str) -> Any:
        fetch = getattr(self._client, f"fetch_{kind}")
        return await fetch(int(identifier))

    @staticmethod
    def _name_from_object(object_: Any, kind: NameKind) -> str | None:
        if object_ is None:
            return None
        if kind == "user":
            name = getattr(object_, "global_name", None) or getattr(object_, "name", None)
        else:
            name = getattr(object_, "name", None)
        return name if isinstance(name, str) and name else None

    def _remember(self, key: tuple[NameKind, str], name: str | None, expires_at: float) -> None:
        self._cache[key] = _CacheEntry(name, expires_at)
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_cache_entries:
            self._cache.popitem(last=False)

    def _is_ready(self) -> bool:
        try:
            return bool(self._client.is_ready())
        except Exception:
            return False


__all__ = ["DiscordNameResolver"]
