from __future__ import annotations

from typing import Any, Literal, NotRequired, Required, TypeAlias, TypedDict

JsonObject: TypeAlias = dict[str, Any]
Availability: TypeAlias = Literal["online", "offline", "busy"]
MessageType: TypeAlias = Literal[
    "task",
    "conversation",
    "rpc_request",
    "rpc_response",
    "rpc_error",
    "capability_advertisement",
    "heartbeat",
    "control",
]
MessageStatus: TypeAlias = Literal["pending", "queued", "delivered", "read", "failed"]
Discovery: TypeAlias = Literal["direct", "broadcast", "capability_match"]
Priority: TypeAlias = Literal["low", "normal", "high", "urgent"]


class ProblemExtra(TypedDict, total=False):
    errors: dict[str, list[str]]
    payment_intent: JsonObject
    required_scopes: list[str]
    retry_after_seconds: int


class Problem(TypedDict):
    """RFC 9457 problem returned by the agent communication API."""

    type: str
    title: str
    status: int
    detail: str
    error: NotRequired[str | None]
    extra: NotRequired[ProblemExtra]
    instance: NotRequired[str | None]
    request_id: NotRequired[str | None]


AgentCommunicationProblem = Problem


class Agent(TypedDict):
    id: str
    name: str
    metadata: JsonObject
    slug: str
    service_agent_id: str
    capabilities: list[str]
    availability: Availability
    agent_type: NotRequired[str | None]
    description: NotRequired[str | None]
    framework: NotRequired[str | None]
    framework_version: NotRequired[str | None]
    inserted_at: NotRequired[str]
    last_seen_at: NotRequired[str | None]
    status: NotRequired[Literal["active", "paused", "revoked", "online", "offline", "busy"]]
    updated_at: NotRequired[str]


class AgentUpdateRequest(TypedDict, total=False):
    agent_type: str
    capabilities: list[str]
    description: str
    framework: str
    framework_version: str
    metadata: JsonObject
    name: str


class AgentListResponse(TypedDict):
    count: int
    agents: list[Agent]


class MessageRecipient(TypedDict, total=False):
    agent_id: str
    capability_filter: list[str]
    discovery: Discovery
    max_recipients: int
    priority: Priority
    queue_if_offline: bool
    retention_days: int


class MessageCreateRequest(TypedDict, total=False):
    payload: Required[JsonObject]
    recipient: Required[MessageRecipient]
    conversation_id: str
    correlation_id: str
    message_id: str
    message_type: MessageType
    metadata: JsonObject


class Message(TypedDict):
    status: MessageStatus
    metadata: JsonObject
    payload: JsonObject
    inserted_at: str
    updated_at: str
    message_id: str
    message_type: MessageType
    cost_cents: str
    recipient_discovery: Discovery
    sender_service_agent_id: str
    size_bytes: int
    conversation_id: NotRequired[str | None]
    correlation_id: NotRequired[str | None]
    error: NotRequired[JsonObject | None]
    recipient_service_agent_id: NotRequired[str | None]


class MessageDispatchResponse(TypedDict):
    status: str
    inserted_at: str
    updated_at: str
    idempotency: str
    message_id: str
    billed_amount_cents: str
    recipients: list[str]
    error: NotRequired[JsonObject | None]
    remaining_balance_cents: NotRequired[str | None]


class MessageListResponse(TypedDict):
    count: int
    messages: list[Message]


class TaskCreateRequest(TypedDict, total=False):
    task_type: Required[str]
    max_retries: int
    payload: JsonObject
    priority: Priority
    recipient_service_agent_id: str
    scheduled_at: str
    task_id: str
    timeout_seconds: int


class Task(TypedDict):
    priority: Priority
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    payload: JsonObject
    inserted_at: str
    updated_at: str
    sender_service_agent_id: str
    max_retries: int
    retry_count: int
    task_id: str
    task_type: str
    timeout_seconds: int
    completed_at: NotRequired[str | None]
    error_message: NotRequired[str | None]
    recipient_service_agent_id: NotRequired[str | None]
    result: NotRequired[JsonObject | None]
    scheduled_at: NotRequired[str | None]
    started_at: NotRequired[str | None]


class Pagination(TypedDict):
    offset: int
    limit: int


class TaskListResponse(TypedDict):
    count: int
    pagination: Pagination
    tasks: list[Task]


class GroupMember(TypedDict):
    role: Literal["leader", "member"]
    service_agent_id: str
    joined_at: str


class GroupMemberCreateRequest(TypedDict):
    service_agent_id: str
    role: NotRequired[Literal["leader", "member"]]


class GroupCreateRequest(TypedDict, total=False):
    name: Required[str]
    capabilities: list[str]
    description: str
    group_id: str
    metadata: JsonObject


class GroupUpdateRequest(TypedDict, total=False):
    capabilities: list[str]
    description: str
    group_id: str
    metadata: JsonObject
    name: str


class Group(TypedDict):
    name: str
    metadata: JsonObject
    members: list[GroupMember]
    inserted_at: str
    updated_at: str
    capabilities: list[str]
    group_id: str
    leader_service_agent_id: str
    description: NotRequired[str | None]


class GroupListResponse(TypedDict):
    count: int
    groups: list[Group]


class GroupBroadcastRequest(TypedDict):
    message: JsonObject
    exclude_sender: NotRequired[bool]


class GroupBroadcastResponse(TypedDict):
    group_id: str
    recipients: list[str]


class CredentialCreateRequest(TypedDict, total=False):
    expires_at: str
    metadata: JsonObject
    name: str
    scopes: list[str]


class CredentialCreateResponse(TypedDict):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    service_agent_id: str
    secret: str
    expires_at: NotRequired[str | None]


class TokenExchangeRequest(TypedDict, total=False):
    api_key: str
    scopes: list[str]


class TokenResponse(TypedDict):
    token: str
    scopes: list[str]
    workspace_id: str
    service_agent_id: str
    expires_in: int
    credential_id: str


class SocketTokenResponse(TypedDict):
    socket_token: str
    expires_in: int
    workspace_id: str
    service_agent_id: str
    scopes: list[str]
    socket_path: str


SocketToken = SocketTokenResponse


class RegistrationRequest(TypedDict):
    password: str
    workspace_name: str
    email: str
    agent_name: str
    name: NotRequired[str]


class RegistrationUser(TypedDict):
    id: str
    email: str
    confirmed_at: NotRequired[str | None]
    name: NotRequired[str]


class RegistrationAPIKey(TypedDict):
    type: Literal["api_key"]
    key: str
    scopes: list[str]
    service_agent_id: str
    credential_id: str


class RegistrationAccessToken(TypedDict):
    type: Literal["bearer"]
    token: str
    scopes: list[str]
    service_agent_id: str
    expires_in: int
    credential_id: str


class RegistrationWorkspace(TypedDict):
    id: str
    name: str
    status: str
    plan: str
    slug: str


class RegistrationServiceAgent(TypedDict):
    id: str
    name: str
    status: str
    slug: str


class RegistrationResponse(TypedDict):
    user: RegistrationUser
    api_key: RegistrationAPIKey
    access_token: RegistrationAccessToken
    workspace: RegistrationWorkspace
    service_agent: RegistrationServiceAgent


BootstrapRequest = RegistrationRequest
BootstrapResponse = RegistrationResponse


class EnrollmentClaimRequest(TypedDict):
    token: str
    agent: NotRequired[JsonObject]
    serial_number: NotRequired[str]


# The current OpenAPI contract intentionally exposes this response as an open object.
EnrollmentClaimResponse: TypeAlias = JsonObject


class PresenceEntry(TypedDict):
    status: Availability
    service_agent_id: str
    last_seen: NotRequired[str | None]


class PresenceResponse(TypedDict):
    agents: dict[str, PresenceEntry]


class HealthReportRequest(TypedDict, total=False):
    cpu_usage: float
    custom_metrics: JsonObject
    error_rate: float
    memory_usage: float
    message_throughput: float
    response_time_avg: float


class HealthReportResponse(TypedDict):
    status: Literal["recorded"]


class AgentHealth(TypedDict):
    timestamp: str
    workspace_id: str
    service_agent_id: str
    connection_quality: NotRequired[float | None]
    cpu_usage: NotRequired[float]
    custom_metrics: NotRequired[JsonObject]
    error_rate: NotRequired[float]
    health_score: NotRequired[float | None]
    memory_usage: NotRequired[float]
    message_throughput: NotRequired[float]
    response_time_avg: NotRequired[float]


class QueueStatsResponse(TypedDict):
    by_priority: dict[str, int]
    total_pending: int
