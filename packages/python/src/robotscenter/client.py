from __future__ import annotations

import random
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Self, cast
from urllib.parse import quote

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    PaymentRequiredError,
    QuotaError,
    RateLimitError,
    TransportError,
    ValidationError,
)

Json = dict[str, Any] | list[Any] | str | int | float | bool | None
RETRYABLE_STATUS = {429, 502, 503, 504}
RETRYABLE_METHODS = {"GET"}


def _error(response: httpx.Response) -> APIError:
    try:
        decoded = response.json()
        body = decoded if isinstance(decoded, dict) else {"detail": decoded}
    except ValueError:
        body = {"detail": response.text or response.reason_phrase}
    message = str(body.get("detail") or body.get("message") or body.get("title") or response.reason_phrase)
    extra_value = body.get("extra")
    extra: dict[str, Any] = extra_value if isinstance(extra_value, dict) else {}
    code = body.get("code") or body.get("error") or extra.get("code")
    code_text = str(code) if code is not None else None
    details = body
    request_id_value = response.headers.get("x-request-id") or body.get("request_id")
    request_id = str(request_id_value) if request_id_value is not None else None
    if response.status_code == 401:
        return AuthenticationError(message, response.status_code, code_text, details, request_id)
    if response.status_code == 403:
        return AuthorizationError(message, response.status_code, code_text, details, request_id)
    if response.status_code == 429:
        if code_text in {"quota_exceeded", "workspace_quota_exceeded"}:
            return QuotaError(message, response.status_code, code_text, details, request_id)
        retry = response.headers.get("retry-after")
        return RateLimitError(message, response.status_code, code_text, details, request_id, retry_after=_retry_after(retry))
    if response.status_code == 402:
        return PaymentRequiredError(message, response.status_code, code_text, details, request_id)
    if response.status_code == 404:
        return NotFoundError(message, response.status_code, code_text, details, request_id)
    if response.status_code == 409:
        return ConflictError(message, response.status_code, code_text, details, request_id)
    if response.status_code == 422:
        return ValidationError(message, response.status_code, code_text, details, request_id)
    return APIError(message, response.status_code, code_text, details, request_id)


class _Resources:
    def __init__(self, client: Client) -> None:
        self._client = client

    def agents(self, **params: Any) -> Json:
        return self._client.request("GET", "/api/v1/agents", params=params)

    def agent(self, agent_id: str) -> Json:
        return self._client.request("GET", f"/api/v1/agents/{_id(agent_id)}")

    def me(self) -> Json:
        return self._client.request("GET", "/api/v1/agents/me")

    def update_me(self, **attributes: Any) -> Json:
        return self._client.request("PATCH", "/api/v1/agents/me", json=attributes)

    def create_credential(self, credential: Mapping[str, Any]) -> Json:
        return self._client.request(
            "POST", "/api/v1/agents/me/credentials", json=dict(credential)
        )

    def exchange_agent_token(self, api_key: str, scopes: list[str] | None = None) -> Json:
        return self._client.request(
            "POST", "/api/v1/agent_tokens", json={"api_key": api_key, **({"scopes": scopes} if scopes else {})}
        )

    def register(self, registration: Mapping[str, Any]) -> Json:
        return self._client.request("POST", "/api/v1/register", json=dict(registration))

    def claim_enrollment(self, enrollment: Mapping[str, Any]) -> Json:
        return self._client.request(
            "POST", "/api/v1/enrollments/claim", json=dict(enrollment)
        )

    def messages(self, **params: Any) -> Json:
        return self._client.request("GET", "/api/v1/messages", params=params)

    def message(self, message_id: str) -> Json:
        return self._client.request("GET", f"/api/v1/messages/{_id(message_id)}")

    def send_message(self, message: Mapping[str, Any]) -> Json:
        body = dict(message)
        retryable = isinstance(body.get("message_id"), str) and bool(body["message_id"])
        return self._client.request("POST", "/api/v1/messages", json=body, _retryable=retryable)

    def tasks(self, **params: Any) -> Json:
        return self._client.request("GET", "/api/v1/tasks", params=params)

    def create_task(self, task: Mapping[str, Any]) -> Json:
        return self._client.request("POST", "/api/v1/tasks", json=dict(task))

    def task(self, task_id: str) -> Json:
        return self._client.request("GET", f"/api/v1/tasks/{task_id}")

    def cancel_task(self, task_id: str) -> Json:
        return self._client.request("POST", f"/api/v1/tasks/{task_id}/cancel")

    def retry_task(self, task_id: str) -> Json:
        return self._client.request("POST", f"/api/v1/tasks/{task_id}/retry")

    def groups(self) -> Json:
        return self._client.request("GET", "/api/v1/groups")

    def create_group(self, group: Mapping[str, Any]) -> Json:
        return self._client.request("POST", "/api/v1/groups", json=dict(group))

    def group(self, group_id: str) -> Json:
        return self._client.request("GET", f"/api/v1/groups/{group_id}")

    def update_group(self, group_id: str, group: Mapping[str, Any]) -> Json:
        return self._client.request("PATCH", f"/api/v1/groups/{group_id}", json=dict(group))

    def delete_group(self, group_id: str) -> Json:
        return self._client.request("DELETE", f"/api/v1/groups/{group_id}")

    def add_group_member(self, group_id: str, member: Mapping[str, Any]) -> Json:
        return self._client.request(
            "POST", f"/api/v1/groups/{group_id}/members", json=dict(member)
        )

    def remove_group_member(self, group_id: str, service_agent_id: str) -> Json:
        return self._client.request(
            "DELETE", f"/api/v1/groups/{group_id}/members/{service_agent_id}"
        )

    def broadcast_group(self, group_id: str, message: Mapping[str, Any], *, exclude_sender: bool = True) -> Json:
        return self._client.request(
            "POST", f"/api/v1/groups/{_id(group_id)}/messages", json={"message": dict(message), "exclude_sender": exclude_sender}
        )

    def presence(self, service_agent_ids: list[str]) -> Json:
        return self._client.request(
            "GET", "/api/v1/presence", params={"service_agent_ids": ",".join(service_agent_ids)}
        )

    def report_health(self, report: Mapping[str, Any]) -> Json:
        return self._client.request("POST", "/api/v1/health_reports", json=dict(report))

    def agent_health(self, agent_id: str) -> Json:
        return self._client.request("GET", f"/api/v1/agents/{agent_id}/health")

    def queue(self) -> Json:
        return self._client.request("GET", "/api/v1/queue")

    def socket_token(self) -> Json:
        return self._client.request("POST", "/api/v1/socket_tokens")


class RobotsCenterClient(_Resources):
    def __init__(
        self,
        *,
        base_url: str = "https://robotscenter.net",
        token: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout, transport=transport)
        super().__init__(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Json:
        force_retry = bool(kwargs.pop("_retryable", False))
        headers = {"accept": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        headers.update(kwargs.pop("headers", {}))
        retryable = force_retry or method.upper() in RETRYABLE_METHODS
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.request(method, self.base_url + path, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if not retryable or attempt == self.max_retries:
                    raise TransportError(str(exc)) from exc
                time.sleep(_delay(attempt, None))
                continue
            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return None
                return cast(Json, response.json())
            error = _error(response)
            if response.status_code not in RETRYABLE_STATUS or not retryable or attempt == self.max_retries:
                raise error
            retry_after = error.retry_after if isinstance(error, RateLimitError) else None
            time.sleep(_delay(attempt, retry_after))
        raise AssertionError("unreachable")


class AsyncRobotsCenterClient:
    def __init__(
        self,
        *,
        base_url: str = "https://robotscenter.net",
        token: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_retries = max_retries
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    async def agents(self, **params: Any) -> Json:
        return await self.request("GET", "/api/v1/agents", params=params)

    async def agent(self, agent_id: str) -> Json:
        return await self.request("GET", f"/api/v1/agents/{agent_id}")

    async def me(self) -> Json:
        return await self.request("GET", "/api/v1/agents/me")

    async def update_me(self, **attributes: Any) -> Json:
        return await self.request("PATCH", "/api/v1/agents/me", json=attributes)

    async def create_credential(self, credential: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/agents/me/credentials", json=dict(credential))

    async def exchange_agent_token(self, api_key: str, scopes: list[str] | None = None) -> Json:
        return await self.request("POST", "/api/v1/agent_tokens", json={"api_key": api_key, **({"scopes": scopes} if scopes else {})})

    async def register(self, registration: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/register", json=dict(registration))

    async def claim_enrollment(self, enrollment: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/enrollments/claim", json=dict(enrollment))

    async def messages(self, **params: Any) -> Json:
        return await self.request("GET", "/api/v1/messages", params=params)

    async def message(self, message_id: str) -> Json:
        return await self.request("GET", f"/api/v1/messages/{message_id}")

    async def send_message(self, message: Mapping[str, Any]) -> Json:
        body = dict(message)
        retryable = isinstance(body.get("message_id"), str) and bool(body["message_id"])
        return await self.request("POST", "/api/v1/messages", json=body, _retryable=retryable)

    async def tasks(self, **params: Any) -> Json:
        return await self.request("GET", "/api/v1/tasks", params=params)

    async def create_task(self, task: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/tasks", json=dict(task))

    async def task(self, task_id: str) -> Json:
        return await self.request("GET", f"/api/v1/tasks/{task_id}")

    async def cancel_task(self, task_id: str) -> Json:
        return await self.request("POST", f"/api/v1/tasks/{task_id}/cancel")

    async def retry_task(self, task_id: str) -> Json:
        return await self.request("POST", f"/api/v1/tasks/{task_id}/retry")

    async def groups(self) -> Json:
        return await self.request("GET", "/api/v1/groups")

    async def create_group(self, group: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/groups", json=dict(group))

    async def group(self, group_id: str) -> Json:
        return await self.request("GET", f"/api/v1/groups/{group_id}")

    async def update_group(self, group_id: str, group: Mapping[str, Any]) -> Json:
        return await self.request("PATCH", f"/api/v1/groups/{group_id}", json=dict(group))

    async def delete_group(self, group_id: str) -> Json:
        return await self.request("DELETE", f"/api/v1/groups/{group_id}")

    async def add_group_member(self, group_id: str, member: Mapping[str, Any]) -> Json:
        return await self.request("POST", f"/api/v1/groups/{group_id}/members", json=dict(member))

    async def remove_group_member(self, group_id: str, service_agent_id: str) -> Json:
        return await self.request("DELETE", f"/api/v1/groups/{group_id}/members/{service_agent_id}")

    async def broadcast_group(self, group_id: str, message: Mapping[str, Any], *, exclude_sender: bool = True) -> Json:
        return await self.request("POST", f"/api/v1/groups/{_id(group_id)}/messages", json={"message": dict(message), "exclude_sender": exclude_sender})

    async def presence(self, service_agent_ids: list[str]) -> Json:
        return await self.request(
            "GET", "/api/v1/presence", params={"service_agent_ids": ",".join(service_agent_ids)}
        )

    async def report_health(self, report: Mapping[str, Any]) -> Json:
        return await self.request("POST", "/api/v1/health_reports", json=dict(report))

    async def agent_health(self, agent_id: str) -> Json:
        return await self.request("GET", f"/api/v1/agents/{agent_id}/health")

    async def queue(self) -> Json:
        return await self.request("GET", "/api/v1/queue")

    async def socket_token(self) -> Json:
        return await self.request("POST", "/api/v1/socket_tokens")

    async def request(self, method: str, path: str, **kwargs: Any) -> Json:
        import asyncio

        force_retry = bool(kwargs.pop("_retryable", False))
        headers = {"accept": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        headers.update(kwargs.pop("headers", {}))
        retryable = force_retry or method.upper() in RETRYABLE_METHODS
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http.request(method, self.base_url + path, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if not retryable or attempt == self.max_retries:
                    raise TransportError(str(exc)) from exc
                await asyncio.sleep(_delay(attempt, None))
                continue
            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return None
                return cast(Json, response.json())
            error = _error(response)
            if response.status_code not in RETRYABLE_STATUS or not retryable or attempt == self.max_retries:
                raise error
            retry_after = error.retry_after if isinstance(error, RateLimitError) else None
            await asyncio.sleep(_delay(attempt, retry_after))
        raise AssertionError("unreachable")


def _delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return float(min(retry_after, 30.0))
    return float(min(0.25 * (2**attempt) + random.uniform(0.0, 0.1), 5.0))


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


def _id(value: str) -> str:
    return quote(value, safe="")


Client = RobotsCenterClient
AsyncClient = AsyncRobotsCenterClient
