from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, Required, cast, get_args, get_origin, get_type_hints

from robotscenter import models

CONTRACT = Path(__file__).parents[3] / "contracts" / "openapi.json"


def _schema(name: str) -> dict[str, Any]:
    import json

    document = cast(dict[str, Any], json.loads(CONTRACT.read_text()))
    return cast(dict[str, Any], document["components"]["schemas"][name])


def _unwrap_required(annotation: object) -> object:
    return get_args(annotation)[0] if get_origin(annotation) is Required else annotation


def _required_keys(model: Any) -> frozenset[str]:
    hints = get_type_hints(model, include_extras=True)
    total = cast(bool, model.__total__)

    return frozenset(
        name
        for name, annotation in hints.items()
        if get_origin(annotation) is Required
        or (total and get_origin(annotation) is not NotRequired)
    )


def test_component_model_required_and_optional_keys_match_openapi() -> None:
    component_models: dict[str, Any] = {
        "Agent": models.Agent,
        "AgentHealth": models.AgentHealth,
        "AgentListResponse": models.AgentListResponse,
        "AgentUpdateRequest": models.AgentUpdateRequest,
        "CredentialCreateRequest": models.CredentialCreateRequest,
        "CredentialCreateResponse": models.CredentialCreateResponse,
        "Group": models.Group,
        "GroupBroadcastRequest": models.GroupBroadcastRequest,
        "GroupBroadcastResponse": models.GroupBroadcastResponse,
        "GroupCreateRequest": models.GroupCreateRequest,
        "GroupListResponse": models.GroupListResponse,
        "GroupMember": models.GroupMember,
        "GroupMemberCreateRequest": models.GroupMemberCreateRequest,
        "GroupUpdateRequest": models.GroupUpdateRequest,
        "HealthReportRequest": models.HealthReportRequest,
        "HealthReportResponse": models.HealthReportResponse,
        "Message": models.Message,
        "MessageCreateRequest": models.MessageCreateRequest,
        "MessageDispatchResponse": models.MessageDispatchResponse,
        "MessageListResponse": models.MessageListResponse,
        "PresenceResponse": models.PresenceResponse,
        "QueueStatsResponse": models.QueueStatsResponse,
        "Task": models.Task,
        "TaskCreateRequest": models.TaskCreateRequest,
        "TaskListResponse": models.TaskListResponse,
    }

    for schema_name, model in component_models.items():
        schema = _schema(schema_name)
        assert set(model.__annotations__) == set(schema["properties"])
        assert _required_keys(model) == frozenset(schema.get("required", []))


def test_nested_model_mappings_keep_typed_collections() -> None:
    group_hints = get_type_hints(models.Group)
    message_hints = get_type_hints(models.MessageListResponse)
    presence_hints = get_type_hints(models.PresenceResponse)

    assert group_hints["members"] == list[models.GroupMember]
    assert message_hints["messages"] == list[models.Message]
    assert presence_hints["agents"] == dict[str, models.PresenceEntry]
    assert (
        _unwrap_required(
            get_type_hints(models.MessageCreateRequest, include_extras=True)["payload"]
        )
        == models.JsonObject
    )


def test_inline_auth_and_bootstrap_models_capture_contract_fields() -> None:
    assert _required_keys(models.RegistrationRequest) == frozenset(
        {"password", "workspace_name", "email", "agent_name"}
    )
    assert _required_keys(models.RegistrationResponse) == frozenset(
        {"user", "api_key", "access_token", "workspace", "service_agent"}
    )
    assert _required_keys(models.TokenResponse) == frozenset(
        {"token", "scopes", "workspace_id", "service_agent_id", "expires_in", "credential_id"}
    )
    assert _required_keys(models.SocketTokenResponse) == frozenset(
        {"socket_token", "scopes", "workspace_id", "service_agent_id", "expires_in", "socket_path"}
    )
    assert _required_keys(models.EnrollmentClaimRequest) == frozenset({"token"})


def test_problem_is_the_required_rfc9457_shape() -> None:
    assert _required_keys(models.Problem) == frozenset({"type", "title", "status", "detail"})
    assert set(get_type_hints(models.ProblemExtra)) == {
        "errors",
        "payment_intent",
        "required_scopes",
        "retry_after_seconds",
    }
