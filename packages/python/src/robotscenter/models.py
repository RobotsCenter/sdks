from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class Problem(TypedDict):
    type: NotRequired[str]
    title: str
    status: int
    detail: NotRequired[str]
    instance: NotRequired[str]
    code: NotRequired[str]
    errors: NotRequired[dict[str, Any]]


class Agent(TypedDict):
    id: str
    name: str
    capabilities: list[str]
    framework: NotRequired[str | None]
    framework_version: NotRequired[str | None]
    description: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any]]


class Message(TypedDict):
    message_id: str
    message_type: str
    payload: dict[str, Any]
    recipient: dict[str, Any]
    sender: NotRequired[dict[str, Any]]
    conversation_id: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    status: NotRequired[str]


class Task(TypedDict):
    task_id: str
    status: str
    priority: str
    operation: NotRequired[str]
    input_data: NotRequired[dict[str, Any]]
    result: NotRequired[dict[str, Any] | None]
    error: NotRequired[dict[str, Any] | None]


class Group(TypedDict):
    group_id: str
    name: str
    description: NotRequired[str | None]
    members: NotRequired[list[dict[str, Any]]]
    metadata: NotRequired[dict[str, Any]]


class SocketToken(TypedDict):
    socket_token: str
    expires_in: int
    workspace_id: str
    service_agent_id: str
    scopes: list[str]
    socket_path: str
