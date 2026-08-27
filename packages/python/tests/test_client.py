import json

import httpx
import pytest

from robotscenter import APIError, AsyncClient, Client


def test_sync_client_auth_and_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/agents/me"
        assert request.headers["authorization"] == "Bearer agk_test"
        return httpx.Response(200, json={"id": "agent-1"})

    with Client(token="agk_test", transport=httpx.MockTransport(handler)) as client:
        assert client.me() == {"id": "agent-1"}


def test_sync_client_maps_problem_error() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(422, json={"title": "Invalid request", "code": "invalid"})
    )
    with Client(token="test", transport=transport) as client, pytest.raises(APIError) as raised:
        client.send_message({"recipient": {}})
    assert raised.value.status == 422
    assert raised.value.code == "invalid"


@pytest.mark.asyncio
async def test_async_client_request() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"items": []}))
    async with AsyncClient(token="test", transport=transport) as client:
        assert await client.request("GET", "/api/v1/messages") == {"items": []}


def test_send_reuses_body_message_id_on_retry() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(503 if len(bodies) == 1 else 202, json={"accepted": True})

    with Client(token="test", max_retries=1, transport=httpx.MockTransport(handler)) as client:
        assert client.send_message({"message_id": "stable", "recipient": {"agent_id": "a"}, "payload": {}}) == {
            "accepted": True
        }
    assert bodies[0]["message_id"] == bodies[1]["message_id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/agents"),
        ("GET", "/api/v1/tasks"),
        ("GET", "/api/v1/groups"),
        ("GET", "/api/v1/queue"),
    ],
)
def test_resource_methods_use_contract_paths(method: str, path: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    with Client(token="test", transport=httpx.MockTransport(handler)) as client:
        if path.endswith("agents"):
            client.agents()
        elif path.endswith("tasks"):
            client.tasks()
        elif path.endswith("groups"):
            client.groups()
        else:
            client.queue()
    assert requests[0].method == method
    assert requests[0].url.path == path
