from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from cgv_push_bot.web.names import DiscordNameResolver


@dataclass
class FakeObject:
    name: str
    global_name: str | None = None


class FakeClient:
    def __init__(self) -> None:
        self.ready = True
        self.cached: dict[str, dict[int, Any]] = {"user": {}, "guild": {}, "channel": {}}
        self.fetches: dict[str, Any] = {}

    def is_ready(self) -> bool:
        return self.ready

    def get_user(self, identifier: int) -> Any:
        return self.cached["user"].get(identifier)

    def get_guild(self, identifier: int) -> Any:
        return self.cached["guild"].get(identifier)

    def get_channel(self, identifier: int) -> Any:
        return self.cached["channel"].get(identifier)

    async def fetch_user(self, identifier: int) -> Any:
        return await self.fetches["user"](identifier)

    async def fetch_guild(self, identifier: int) -> Any:
        return await self.fetches["guild"](identifier)

    async def fetch_channel(self, identifier: int) -> Any:
        return await self.fetches["channel"](identifier)


@pytest.mark.asyncio
async def test_cached_objects_are_resolved_without_fetching() -> None:
    client = FakeClient()
    client.cached["user"][123] = FakeObject("account", global_name="display")
    client.cached["guild"][456] = FakeObject("server")
    client.cached["channel"][789] = FakeObject("alerts")
    client.fetches = {kind: _unexpected_fetch for kind in ("user", "guild", "channel")}
    resolver = DiscordNameResolver(client)

    assert resolver.resolve("user", "123") == "display"
    assert resolver.resolve("guild", "456") == "server"
    assert resolver.resolve("channel", "789") == "alerts"


@pytest.mark.asyncio
async def test_missing_name_is_fetched_in_background_and_deduplicated() -> None:
    client = FakeClient()
    calls = 0

    async def fetch(_: int) -> FakeObject:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return FakeObject("server")

    client.fetches["guild"] = fetch
    resolver = DiscordNameResolver(client)

    assert resolver.resolve("guild", "42") is None
    assert resolver.resolve("guild", "0042") is None
    name = resolver.resolve("guild", "42")
    while name is None:
        await asyncio.sleep(0)
        name = resolver.resolve("guild", "42")
    assert calls == 1
    assert name == "server"


@pytest.mark.asyncio
async def test_not_ready_client_does_not_fetch_but_can_use_cache() -> None:
    client = FakeClient()
    client.ready = False
    client.cached["channel"][12] = FakeObject("cached")
    client.fetches["channel"] = _unexpected_fetch
    resolver = DiscordNameResolver(client)

    assert resolver.resolve("channel", "12") == "cached"
    assert resolver.resolve("channel", "13") is None
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_success_and_failure_cache_ttls_use_injected_clock() -> None:
    client = FakeClient()
    current = 100.0
    calls = 0

    async def fetch(_: int) -> FakeObject:
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeObject("found")
        raise RuntimeError("temporary")

    client.fetches["channel"] = fetch
    resolver = DiscordNameResolver(
        client,
        success_ttl=10,
        failure_ttl=5,
        clock=lambda: current,
    )

    assert resolver.resolve("channel", "1") is None
    await asyncio.sleep(0)
    assert resolver.resolve("channel", "1") == "found"
    current += 11
    assert resolver.resolve("channel", "1") is None
    await asyncio.sleep(0)
    assert resolver.resolve("channel", "1") is None
    current += 6
    assert resolver.resolve("channel", "1") is None
    assert calls == 2


@pytest.mark.asyncio
async def test_fetches_are_limited_and_pending_work_is_bounded() -> None:
    client = FakeClient()
    active = 0
    maximum = 0
    calls = 0
    release = asyncio.Event()

    async def fetch(identifier: int) -> FakeObject:
        nonlocal active, maximum, calls
        calls += 1
        active += 1
        maximum = max(maximum, active)
        await release.wait()
        active -= 1
        return FakeObject(str(identifier))

    client.fetches["user"] = fetch
    resolver = DiscordNameResolver(client, max_pending=4, max_concurrent_fetches=2)
    for identifier in range(6):
        assert resolver.resolve("user", str(identifier + 1)) is None
    await asyncio.sleep(0)
    assert maximum == 2
    release.set()
    while calls < 4:
        await asyncio.sleep(0)
    assert calls == 4
    assert maximum == 2


@pytest.mark.asyncio
async def test_timeout_and_failure_are_cached() -> None:
    client = FakeClient()
    calls = 0
    never = asyncio.Event()

    async def fetch(_: int) -> Any:
        nonlocal calls
        calls += 1
        await never.wait()

    client.fetches["user"] = fetch
    resolver = DiscordNameResolver(client, fetch_timeout=0.001)
    assert resolver.resolve("user", "1") is None
    await asyncio.sleep(0.01)
    assert resolver.resolve("user", "1") is None
    assert calls == 1


@pytest.mark.asyncio
async def test_close_cancels_pending_fetches() -> None:
    client = FakeClient()
    started = asyncio.Event()
    never = asyncio.Event()
    calls = 0

    async def fetch(_: int) -> Any:
        nonlocal calls
        calls += 1
        started.set()
        await never.wait()

    client.fetches["guild"] = fetch
    resolver = DiscordNameResolver(client)
    resolver.resolve("guild", "1")
    await started.wait()
    await resolver.close()
    resolver.resolve("guild", "2")
    await asyncio.sleep(0)
    assert calls == 1


@pytest.mark.parametrize(
    "kind, identifier", [("role", "1"), ("user", ""), ("user", "-1"), ("user", "abc")]
)
def test_malformed_ids_are_ignored(kind: str, identifier: str) -> None:
    assert DiscordNameResolver(FakeClient()).resolve(kind, identifier) is None


def test_missing_name_is_ignored_without_running_event_loop() -> None:
    client = FakeClient()
    client.fetches["user"] = _unexpected_fetch

    assert DiscordNameResolver(client).resolve("user", "1") is None


async def _unexpected_fetch(_: int) -> Any:
    raise AssertionError("network fetch should not have been called")
