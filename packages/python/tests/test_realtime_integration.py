from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from websockets.asyncio.server import ServerConnection, serve

from robotscenter import Realtime, RealtimeError

Handler = Callable[[ServerConnection], Awaitable[None]]


@asynccontextmanager
async def phoenix_server(handler: Handler) -> AsyncIterator[str]:
    server = await serve(handler, "127.0.0.1", 0, max_size=65_536)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def frame(connection: ServerConnection) -> list[Any]:
    value = json.loads(await connection.recv())
    assert isinstance(value, list) and len(value) == 5
    return value


async def reply(connection: ServerConnection, request: list[Any], status: str = "ok", response: Any = None) -> None:
    await connection.send(json.dumps([request[0], request[1], request[2], "phx_reply", {"status": status, "response": response or {}}]))


@pytest.mark.asyncio
async def test_initial_join_fresh_token_reconnect_and_validated_subscription_replay() -> None:
    tokens: list[str] = []
    replayed = asyncio.Event()
    connections = 0

    async def handler(connection: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        tokens.append(parse_qs(urlparse(connection.request.path).query)["socket_token"][0])
        join = await frame(connection)
        assert join[3] == "phx_join"
        await reply(connection, join)
        subscription = await frame(connection)
        assert subscription[3] == "queue.subscribe"
        await reply(connection, subscription, response={"subscribed": True})
        if connections == 1:
            await connection.close(code=1012, reason="restart")
        else:
            replayed.set()
            await connection.wait_closed()

    calls = 0

    async def token_provider() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"socket_token": f"fresh-{calls}", "service_agent_id": "agent-1"}

    async with phoenix_server(handler) as url:
        realtime = Realtime(base_url=url, token_provider=token_provider, max_reconnect_delay=0.01)
        await realtime.connect()
        await realtime.subscribe_queue()
        await asyncio.wait_for(replayed.wait(), 2)
        assert tokens == ["fresh-1", "fresh-2"]
        await realtime.close()


@pytest.mark.asyncio
async def test_terminal_channel_error_stops_reconnect() -> None:
    calls = 0

    async def handler(connection: ServerConnection) -> None:
        join = await frame(connection)
        await reply(connection, join)
        await connection.send(json.dumps([join[0], None, join[2], "phx_error", {"reason": "workspace_frozen"}]))
        await connection.wait_closed()

    async def token_provider() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"socket_token": f"token-{calls}", "service_agent_id": "agent-1"}

    async with phoenix_server(handler) as url:
        realtime = Realtime(base_url=url, token_provider=token_provider, max_reconnect_delay=0.01)
        await realtime.connect()
        event, payload = await asyncio.wait_for(anext(realtime.events()), 1)
        assert event == "error" and "workspace_frozen" in payload["reason"]
        await asyncio.sleep(0.05)
        assert calls == 1
        await realtime.close()


@pytest.mark.asyncio
async def test_rejected_subscription_replay_stops_reconnect() -> None:
    connections = 0
    tokens = 0

    async def handler(connection: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        join = await frame(connection)
        await reply(connection, join)
        subscription = await frame(connection)
        if connections == 1:
            await reply(connection, subscription, response={"subscribed": True})
            await connection.close(code=1012, reason="restart")
        else:
            await reply(connection, subscription, "error", {"reason": "unauthorized"})
            await connection.wait_closed()

    async def token_provider() -> dict[str, str]:
        nonlocal tokens
        tokens += 1
        return {"socket_token": f"token-{tokens}", "service_agent_id": "agent-1"}

    async with phoenix_server(handler) as url:
        realtime = Realtime(base_url=url, token_provider=token_provider, max_reconnect_delay=0.01)
        await realtime.connect()
        await realtime.subscribe_queue()
        event, payload = await asyncio.wait_for(anext(realtime.events()), 2)
        if event == "reconnected":
            event, payload = await asyncio.wait_for(anext(realtime.events()), 2)
        assert event == "error" and "unauthorized" in payload["reason"]
        await asyncio.sleep(0.05)
        assert tokens == 2
        await realtime.close()


@pytest.mark.asyncio
async def test_transport_and_agent_heartbeats_use_configured_test_interval() -> None:
    received: set[str] = set()
    complete = asyncio.Event()

    async def handler(connection: ServerConnection) -> None:
        join = await frame(connection)
        await reply(connection, join)
        while len(received) < 2:
            item = await frame(connection)
            received.add(f"{item[2]}:{item[3]}")
        complete.set()
        await connection.wait_closed()

    async with phoenix_server(handler) as url:
        realtime = Realtime(
            base_url=url,
            socket_token="static",
            service_agent_id="agent-1",
            heartbeat_interval=0.01,
        )
        await realtime.connect()
        await asyncio.wait_for(complete.wait(), 1)
        assert received == {"phoenix:heartbeat", "agent:agent-1:agent.heartbeat"}
        await realtime.close()


@pytest.mark.asyncio
async def test_rejected_replay_is_terminal_and_disconnect_has_no_leave_race() -> None:
    disconnect_events: list[str] = []

    async def handler(connection: ServerConnection) -> None:
        join = await frame(connection)
        await reply(connection, join)
        item = await frame(connection)
        disconnect_events.append(item[3])
        if item[3] == "queue.subscribe":
            await reply(connection, item, "error", {"reason": "unauthorized"})
        await connection.close()

    async with phoenix_server(handler) as url:
        realtime = Realtime(base_url=url, socket_token="static", service_agent_id="agent-1")
        await realtime.connect()
        with pytest.raises(RealtimeError):
            await realtime.subscribe_queue()
        assert realtime._subscriptions == {}
        await realtime.disconnect()
        assert "phx_leave" not in disconnect_events
        assert realtime._socket is None


def test_exact_64kib_frame_boundary() -> None:
    realtime = Realtime(base_url="https://example.test", socket_token="token", service_agent_id="agent")
    realtime.topic = "agent:agent"
    realtime._join_ref = "1"
    prefix = len(realtime._frame("event", {"body": ""}, ref="2").encode())
    exact = realtime._frame("event", {"body": "x" * (65_536 - prefix)}, ref="2")
    assert len(exact.encode()) == 65_536
    with pytest.raises(RealtimeError, match="64 KiB"):
        realtime._frame("event", {"body": "x" * (65_537 - prefix)}, ref="2")


@pytest.mark.asyncio
async def test_join_failure_cleans_socket_state() -> None:
    async def handler(connection: ServerConnection) -> None:
        await frame(connection)
        await connection.close()

    async with phoenix_server(handler) as url:
        realtime = Realtime(base_url=url, socket_token="static", service_agent_id="agent-1")
        with pytest.raises(RealtimeError):
            await realtime.connect()
        assert realtime._socket is None
        assert realtime._join_ref is None
