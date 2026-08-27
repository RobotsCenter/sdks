#!/usr/bin/env python3
"""Strict, dependency-free validation for the committed SDK contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def fail(message: str) -> None:
    raise AssertionError(message)


def resolve_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("#/"):
        fail(f"only local JSON references are permitted: {pointer}")
    value = document
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def walk_refs(value: Any, document: Any) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            resolve_pointer(document, value["$ref"])
        for child in value.values():
            walk_refs(child, document)
    elif isinstance(value, list):
        for child in value:
            walk_refs(child, document)


def validate_openapi(document: dict[str, Any]) -> None:
    assert document["openapi"] == "3.1.0"
    assert document["info"]["title"] == "Robots Center Agent Communication API"
    walk_refs(document, document)
    operation_ids: set[str] = set()
    for path, path_item in document["paths"].items():
        assert ":" not in path, f"Phoenix path syntax leaked into OpenAPI: {path}"
        template_names = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path))
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            assert operation_id and operation_id not in operation_ids, f"duplicate operationId: {operation_id}"
            operation_ids.add(operation_id)
            declared = {
                parameter["name"]
                for parameter in operation.get("parameters", []) + path_item.get("parameters", [])
                if parameter.get("in") == "path"
            }
            assert declared == template_names, f"path parameters differ for {method.upper()} {path}"
            if operation.get("security"):
                scopes = operation.get("x-required-scopes")
                assert isinstance(scopes, list) and scopes, f"missing exact scopes: {method.upper()} {path}"
            assert operation.get("responses"), f"missing responses: {method.upper()} {path}"


def validate_realtime(document: dict[str, Any]) -> None:
    assert document["schema_version"] == "1.0.0"
    assert document["protocol"] == {
        "name": "phoenix_channels",
        "version": "2.0",
        "frame": ["join_ref", "ref", "topic", "event", "payload"],
        "serializer": "json",
    }
    assert document["connection"]["websocket_path"] == "/socket/websocket"
    assert document["connection"]["token_endpoint"] == "/api/v1/socket_tokens"
    assert document["connection"]["token_param"] == "socket_token"
    assert document["connection"]["token_ttl_seconds"] == 600
    assert document["limits"] == {
        "agent_heartbeat_interval_seconds": 20,
        "connection_timeout_seconds": 60,
        "max_frame_bytes": 65_536,
        "transport_heartbeat_interval_seconds": 20,
    }
    lifecycle = document["lifecycle"]
    assert lifecycle["reconnect_delays_seconds"] == [1, 2, 5, 10, 30]
    assert lifecycle["jitter"] is True
    assert lifecycle["mint_new_socket_token_on_reconnect"] is True
    assert lifecycle["reconnect_after_explicit_close"] is False
    assert lifecycle["rejoin_topic_after_reconnect"] is True
    assert lifecycle["replay_local_subscriptions_after_reconnect"] is True
    assert lifecycle["terminal_reasons"] == [
        "unauthorized",
        "workspace_frozen",
        "workspace_paused",
        "workspace_archived",
        "workspace_unavailable",
    ]
    clients = document["client_events"]
    servers = document["server_events"]
    assert len(clients) == 30
    assert len(servers) == 18
    assert len({event["name"] for event in clients}) == len(clients)
    assert len({event["name"] for event in servers}) == len(servers)
    assert all(isinstance(event["required_scopes"], list) for event in clients + servers)
    command_events = [event for event in servers if event["name"].startswith("command.")]
    assert command_events and all(event["required_scopes"] == ["agent_commands:read"] for event in command_events)


def validate_source_metadata() -> None:
    source = json.loads((ROOT / "contracts/source.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{7,40}", source["source_commit"])
    for filename in ("openapi.json", "realtime.json"):
        expected = source["surfaces"][filename]["sha256"]
        actual = __import__("hashlib").sha256((ROOT / "contracts" / filename).read_bytes()).hexdigest()
        assert actual == expected, f"{filename} does not match contracts/source.json"


def main() -> None:
    openapi = json.loads((ROOT / "contracts/openapi.json").read_text())
    realtime = json.loads((ROOT / "contracts/realtime.json").read_text())
    validate_openapi(openapi)
    validate_realtime(realtime)
    validate_source_metadata()
    print("contracts are internally valid")


if __name__ == "__main__":
    main()
