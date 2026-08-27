export type JsonObject = Record<string, unknown>;
export type Availability = "online" | "offline" | "busy";
export type Priority = "low" | "normal" | "high" | "urgent";
export type Discovery = "direct" | "broadcast" | "capability_match";
export type MessageType = "task" | "conversation" | "rpc_request" | "rpc_response" |
  "rpc_error" | "capability_advertisement" | "heartbeat" | "control";

export interface ProblemExtra {
  errors?: Record<string, string[]>;
  payment_intent?: JsonObject;
  required_scopes?: string[];
  retry_after_seconds?: number;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  error?: string | null;
  extra?: ProblemExtra;
  instance?: string | null;
  request_id?: string | null;
}

export type AgentCommunicationProblem = Problem;

export interface Agent {
  id: string;
  name: string;
  metadata: JsonObject;
  slug: string;
  service_agent_id: string;
  capabilities: string[];
  availability: Availability;
  agent_type?: string | null;
  description?: string | null;
  framework?: string | null;
  framework_version?: string | null;
  inserted_at?: string;
  last_seen_at?: string | null;
  status?: "active" | "paused" | "revoked" | Availability;
  updated_at?: string;
}

export interface AgentUpdateRequest {
  agent_type?: string;
  capabilities?: string[];
  description?: string;
  framework?: string;
  framework_version?: string;
  metadata?: JsonObject;
  name?: string;
}

export interface AgentListResponse { count: number; agents: Agent[] }

export interface MessageRecipient {
  agent_id?: string;
  capability_filter?: string[];
  discovery?: Discovery;
  max_recipients?: number;
  priority?: Priority;
  queue_if_offline?: boolean;
  retention_days?: number;
}

export interface MessageCreateRequest {
  payload: JsonObject;
  recipient: MessageRecipient;
  conversation_id?: string;
  correlation_id?: string;
  message_id?: string;
  message_type?: MessageType;
  metadata?: JsonObject;
}

export interface Message {
  status: "pending" | "queued" | "delivered" | "read" | "failed";
  metadata: JsonObject;
  payload: JsonObject;
  inserted_at: string;
  updated_at: string;
  message_id: string;
  message_type: MessageType;
  cost_cents: string;
  recipient_discovery: Discovery;
  sender_service_agent_id: string;
  size_bytes: number;
  conversation_id?: string | null;
  correlation_id?: string | null;
  error?: JsonObject | null;
  recipient_service_agent_id?: string | null;
}

export interface MessageDispatchResponse {
  status: string;
  inserted_at: string;
  updated_at: string;
  idempotency: string;
  message_id: string;
  billed_amount_cents: string;
  recipients: string[];
  error?: JsonObject | null;
  remaining_balance_cents?: string | null;
}

export interface MessageListResponse { count: number; messages: Message[] }

export interface TaskCreateRequest {
  task_type: string;
  max_retries?: number;
  payload?: JsonObject;
  priority?: Priority;
  recipient_service_agent_id?: string;
  scheduled_at?: string;
  task_id?: string;
  timeout_seconds?: number;
}

export interface Task {
  priority: Priority;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  payload: JsonObject;
  inserted_at: string;
  updated_at: string;
  sender_service_agent_id: string;
  max_retries: number;
  retry_count: number;
  task_id: string;
  task_type: string;
  timeout_seconds: number;
  completed_at?: string | null;
  error_message?: string | null;
  recipient_service_agent_id?: string | null;
  result?: JsonObject | null;
  scheduled_at?: string | null;
  started_at?: string | null;
}

export interface Pagination { offset: number; limit: number }
export interface TaskListResponse { count: number; pagination: Pagination; tasks: Task[] }

export interface GroupMember {
  role: "leader" | "member";
  service_agent_id: string;
  joined_at: string;
}

export interface GroupMemberCreateRequest {
  service_agent_id: string;
  role?: "leader" | "member";
}

export interface GroupCreateRequest {
  name: string;
  capabilities?: string[];
  description?: string;
  group_id?: string;
  metadata?: JsonObject;
}

export interface GroupUpdateRequest {
  capabilities?: string[];
  description?: string;
  group_id?: string;
  metadata?: JsonObject;
  name?: string;
}

export interface Group {
  name: string;
  metadata: JsonObject;
  members: GroupMember[];
  inserted_at: string;
  updated_at: string;
  capabilities: string[];
  group_id: string;
  leader_service_agent_id: string;
  description?: string | null;
}

export interface GroupListResponse { count: number; groups: Group[] }
export interface GroupBroadcastRequest { message: JsonObject; exclude_sender?: boolean }
export interface GroupBroadcastResponse { group_id: string; recipients: string[] }

export interface CredentialCreateRequest {
  expires_at?: string;
  metadata?: JsonObject;
  name?: string;
  scopes?: string[];
}

export interface CredentialCreateResponse {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  service_agent_id: string;
  secret: string;
  expires_at?: string | null;
}

export interface TokenExchangeRequest { api_key?: string; scopes?: string[] }

export interface TokenResponse {
  token: string;
  scopes: string[];
  workspace_id: string;
  service_agent_id: string;
  expires_in: number;
  credential_id: string;
}

export interface SocketTokenResponse {
  socket_token: string;
  expires_in: number;
  workspace_id: string;
  service_agent_id: string;
  scopes: string[];
  socket_path: string;
}

export interface RegistrationRequest {
  password: string;
  workspace_name: string;
  email: string;
  agent_name: string;
  name?: string;
}

export interface RegistrationUser {
  id: string;
  email: string;
  confirmed_at?: string | null;
  name?: string;
}

export interface RegistrationAPIKey {
  type: "api_key";
  key: string;
  scopes: string[];
  service_agent_id: string;
  credential_id: string;
}

export interface RegistrationAccessToken {
  type: "bearer";
  token: string;
  scopes: string[];
  service_agent_id: string;
  expires_in: number;
  credential_id: string;
}

export interface RegistrationWorkspace {
  id: string;
  name: string;
  status: string;
  plan: string;
  slug: string;
}

export interface RegistrationServiceAgent { id: string; name: string; status: string; slug: string }

export interface RegistrationResponse {
  user: RegistrationUser;
  api_key: RegistrationAPIKey;
  access_token: RegistrationAccessToken;
  workspace: RegistrationWorkspace;
  service_agent: RegistrationServiceAgent;
}

export type BootstrapRequest = RegistrationRequest;
export type BootstrapResponse = RegistrationResponse;

export interface EnrollmentClaimRequest {
  token: string;
  agent?: JsonObject;
  serial_number?: string;
}

// The current OpenAPI contract intentionally exposes this response as an open object.
export type EnrollmentClaimResponse = JsonObject;

export interface PresenceEntry {
  status: Availability;
  service_agent_id: string;
  last_seen?: string | null;
}

export interface PresenceResponse { agents: Record<string, PresenceEntry> }

export interface HealthReportRequest {
  cpu_usage?: number;
  custom_metrics?: JsonObject;
  error_rate?: number;
  memory_usage?: number;
  message_throughput?: number;
  response_time_avg?: number;
}

export interface HealthReportResponse { status: "recorded" }

export interface AgentHealth {
  timestamp: string;
  workspace_id: string;
  service_agent_id: string;
  connection_quality?: number | null;
  cpu_usage?: number;
  custom_metrics?: JsonObject;
  error_rate?: number;
  health_score?: number | null;
  memory_usage?: number;
  message_throughput?: number;
  response_time_avg?: number;
}

export interface QueueStatsResponse { by_priority: Record<string, number>; total_pending: number }
