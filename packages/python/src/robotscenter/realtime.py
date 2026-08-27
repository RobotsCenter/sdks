from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Self
from urllib.parse import urlencode, urlparse, urlunparse

import websockets
from websockets.asyncio.client import ClientConnection

from .errors import RealtimeError


class Realtime:
    """Phoenix Channels v2 client for an authenticated agent topic."""

    def __init__(
        self,
        *,
        base_url: str,
        socket_token: str | None = None,
        service_agent_id: str | None = None,
        token_provider: Callable[[], Awaitable[Mapping[str, Any]]] | None = None,
        join_payload: Mapping[str, Any] | None = None,
        reconnect: bool = True,
        max_reconnect_delay: float = 30.0,
    ) -> None:
        if token_provider is None and (socket_token is None or service_agent_id is None):
            raise ValueError("provide token_provider or both socket_token and service_agent_id")
        self.base_url = base_url
        self.socket_token = socket_token
        self.service_agent_id = service_agent_id
        self.token_provider = token_provider
        self.url = ""
        self.topic = ""
        self.join_payload = dict(join_payload or {})
        self.reconnect = reconnect
        self.max_reconnect_delay = max_reconnect_delay
        self._socket: ClientConnection | None = None
        self._ref = 0
        self._join_ref: str | None = None
        self._stopping = False
        self._reader: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._connect_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._subscriptions: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._terminal = False

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        self._stopping = False
        self._terminal = False
        async with self._connect_lock:
            await self._open()
            if self._reader is None or self._reader.done():
                self._reader = asyncio.create_task(self._reader_loop())
            if self._heartbeat_task is None or self._heartbeat_task.done():
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self) -> None:
        self._stopping = True
        self._terminal = True
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._socket is not None:
            try:
                await self._send("phx_leave", {})
            finally:
                await self._socket.close()
                self._socket = None

    async def push(self, event: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if self._socket is None:
            raise RealtimeError("realtime connection is not open")
        ref = self._next_ref()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[ref] = future
        await self._send(event, dict(payload or {}), ref=ref)
        try:
            response = await asyncio.wait_for(future, timeout=10.0)
        finally:
            self._pending.pop(ref, None)
        if response.get("status") != "ok":
            raise RealtimeError(f"{event} failed: {response.get('response')}")
        value = response.get("response", {})
        return value if isinstance(value, dict) else {"value": value}

    async def heartbeat(self) -> None:
        if self._socket is None:
            raise RealtimeError("realtime connection is not open")
        ref = self._next_ref()
        await self._socket.send(json.dumps([None, ref, "phoenix", "heartbeat", {}]))

    async def subscribe_tasks(self, task_ids: list[str]) -> dict[str, Any]:
        return await self._subscribe("task.subscribe", {"task_ids": task_ids})

    async def subscribe_groups(self, group_ids: list[str]) -> dict[str, Any]:
        return await self._subscribe("group.subscribe", {"group_ids": group_ids})

    async def subscribe_presence(self, service_agent_ids: list[str]) -> dict[str, Any]:
        return await self._subscribe(
            "presence.subscribe", {"service_agent_ids": service_agent_ids}
        )

    async def subscribe_queue(self) -> dict[str, Any]:
        return await self._subscribe("queue.subscribe", {})

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        while not self._stopping:
            yield await self._events.get()

    async def _open(self) -> None:
        if self.token_provider is not None:
            token = await self.token_provider()
            self.socket_token = str(token["socket_token"])
            self.service_agent_id = str(token["service_agent_id"])
        assert self.socket_token is not None
        assert self.service_agent_id is not None
        self.url = _socket_url(self.base_url, self.socket_token)
        self.topic = f"agent:{self.service_agent_id}"
        self._socket = await websockets.connect(self.url, ping_interval=None, max_size=1_048_576)
        self._join_ref = self._next_ref()
        await self._send("phx_join", self.join_payload, ref=self._join_ref)
        reply = await self._receive()
        if reply[3] != "phx_reply" or reply[4].get("status") != "ok":
            await self._socket.close()
            self._socket = None
            raise RealtimeError(f"channel join failed: {reply[4]}")
        for event, payload in self._subscriptions.values():
            await self._send(event, payload)

    async def _subscribe(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = (event, json.dumps(payload, sort_keys=True))
        self._subscriptions[key] = (event, payload)
        return await self.push(event, payload)

    async def _heartbeat_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(20)
            if self._socket is not None:
                try:
                    await self.heartbeat()
                    await self._send("agent.heartbeat", {})
                except (OSError, websockets.ConnectionClosed, RealtimeError):
                    pass

    async def _reader_loop(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                message = await self._receive()
                attempt = 0
                event = message[3]
                payload = message[4] if isinstance(message[4], dict) else {"value": message[4]}
                ref = message[1]
                if event == "phx_reply" and ref in self._pending:
                    future = self._pending[ref]
                    if not future.done():
                        future.set_result(payload)
                elif event not in {"phx_reply", "phx_close"}:
                    await self._events.put((event, payload))
            except (OSError, websockets.ConnectionClosed) as exc:
                self._socket = None
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(RealtimeError(str(exc)))
                if not self.reconnect or self._stopping:
                    self._terminal = True
                    await self._events.put(("error", {"reason": str(exc)}))
                    return
                schedule = [1.0, 2.0, 5.0, 10.0, 30.0]
                delay = min(schedule[min(attempt, 4)] * random.uniform(0.8, 1.2), self.max_reconnect_delay)
                attempt += 1
                await asyncio.sleep(delay)
                try:
                    async with self._connect_lock:
                        await self._open()
                    await self._events.put(("reconnected", {}))
                except (OSError, RealtimeError):
                    continue

    async def _send(self, event: str, payload: dict[str, Any], *, ref: str | None = None) -> None:
        if self._socket is None:
            raise RealtimeError("realtime connection is not open")
        frame = json.dumps([self._join_ref, ref or self._next_ref(), self.topic, event, payload])
        if len(frame.encode()) > 65_536:
            raise RealtimeError("Phoenix frame exceeds the 64 KiB payload limit")
        await self._socket.send(frame)

    async def _receive(self) -> list[Any]:
        if self._socket is None:
            raise RealtimeError("realtime connection is not open")
        raw = json.loads(await self._socket.recv())
        if not isinstance(raw, list) or len(raw) != 5:
            raise RealtimeError(f"invalid Phoenix v2 frame: {raw!r}")
        return raw

    def _next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)


def _socket_url(base_url: str, socket_token: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/socket/websocket"
    query = urlencode({"vsn": "2.0.0", "socket_token": socket_token})
    return urlunparse((scheme, parsed.netloc, path, "", query, ""))
