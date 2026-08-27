import pytest

from robotscenter import Realtime
from robotscenter.realtime import _socket_url


def test_socket_url() -> None:
    assert (
        _socket_url("https://robotscenter.net", "signed token")
        == "wss://robotscenter.net/socket/websocket?vsn=2.0.0&socket_token=signed+token"
    )


def test_realtime_requires_token_source() -> None:
    with pytest.raises(ValueError):
        Realtime(base_url="https://example.test")


@pytest.mark.asyncio
async def test_subscription_registry_is_replayable() -> None:
    realtime = Realtime(
        base_url="https://example.test", socket_token="token", service_agent_id="agent"
    )

    async def push(event: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        return {"event": event, "payload": payload or {}}

    realtime.push = push  # type: ignore[method-assign]
    await realtime.subscribe_tasks(["task-1"])
    await realtime.subscribe_groups(["group-1"])
    await realtime.subscribe_presence(["agent-2"])
    await realtime.subscribe_queue()
    assert len(realtime._subscriptions) == 4
