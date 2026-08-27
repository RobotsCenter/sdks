import { ApiError, AuthenticationError, AuthorizationError, ConflictError, NotFoundError, PaymentRequiredError, QuotaError, RateLimitError, TransportError, ValidationError } from "./errors.js";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface ClientOptions {
  token?: string;
  baseUrl?: string;
  timeoutMs?: number;
  maxRetries?: number;
  fetch?: typeof globalThis.fetch;
}

const retryableStatuses = new Set([429, 502, 503, 504]);
const retryableMethods = new Set(["GET"]);

export class RobotsCenterClient {
  readonly baseUrl: string;
  readonly token: string | undefined;
  readonly timeoutMs: number;
  readonly maxRetries: number;
  private readonly fetcher: typeof globalThis.fetch;

  constructor(options: ClientOptions) {
    this.baseUrl = (options.baseUrl ?? "https://robotscenter.net").replace(/\/$/, "");
    this.token = options.token;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.fetcher = options.fetch ?? globalThis.fetch;
  }

  async request<T = Json>(method: string, path: string, init: RequestInit = {}, forceRetry = false): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.token) headers.set("authorization", `Bearer ${this.token}`);
    headers.set("accept", "application/json");
    if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
    const canRetry = forceRetry || retryableMethods.has(method.toUpperCase());

    for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
      try {
        const response = await this.fetcher(this.baseUrl + path, {
          ...init,
          method,
          headers,
          signal: init.signal ?? AbortSignal.timeout(this.timeoutMs),
        });
        if (response.ok) {
          if (response.status === 204 || response.headers.get("content-length") === "0") return undefined as T;
          return (await response.json()) as T;
        }
        const error = await responseError(response);
        if (!canRetry || !retryableStatuses.has(response.status) || attempt === this.maxRetries) throw error;
        await sleep(delay(attempt, error instanceof RateLimitError ? error.retryAfter : undefined));
      } catch (error) {
        if (error instanceof ApiError) throw error;
        if (!canRetry || attempt === this.maxRetries) {
          throw new TransportError(error instanceof Error ? error.message : String(error));
        }
        await sleep(delay(attempt));
      }
    }
    throw new TransportError("request retry loop exhausted");
  }

  agents(params: Record<string, string> = {}) { return this.request("GET", query("/api/v1/agents", params)); }
  agent(id: string) { return this.request("GET", `/api/v1/agents/${encodeURIComponent(id)}`); }
  me() { return this.request("GET", "/api/v1/agents/me"); }
  updateMe(attributes: Json) { return this.request("PATCH", "/api/v1/agents/me", json(attributes)); }
  createCredential(credential: Json) { return this.request("POST", "/api/v1/agents/me/credentials", json(credential)); }
  exchangeAgentToken(apiKey: string, scopes?: string[]) { return this.request("POST", "/api/v1/agent_tokens", json({ api_key: apiKey, ...(scopes ? {scopes} : {}) })); }
  register(registration: Json) { return this.request("POST", "/api/v1/register", json(registration)); }
  claimEnrollment(enrollment: Json) { return this.request("POST", "/api/v1/enrollments/claim", json(enrollment)); }
  messages(params: Record<string, string> = {}) { return this.request("GET", query("/api/v1/messages", params)); }
  message(id: string) { return this.request("GET", `/api/v1/messages/${encodeURIComponent(id)}`); }
  sendMessage(message: Json) {
    const body = asObject(message);
    const retryable = typeof body.message_id === "string" && body.message_id.length > 0;
    return this.request("POST", "/api/v1/messages", json(body), retryable);
  }
  tasks(params: Record<string, string> = {}) { return this.request("GET", query("/api/v1/tasks", params)); }
  task(id: string) { return this.request("GET", `/api/v1/tasks/${encodeURIComponent(id)}`); }
  createTask(task: Json) { return this.request("POST", "/api/v1/tasks", json(task)); }
  cancelTask(id: string) { return this.request("POST", `/api/v1/tasks/${encodeURIComponent(id)}/cancel`); }
  retryTask(id: string) { return this.request("POST", `/api/v1/tasks/${encodeURIComponent(id)}/retry`); }
  groups() { return this.request("GET", "/api/v1/groups"); }
  group(id: string) { return this.request("GET", `/api/v1/groups/${encodeURIComponent(id)}`); }
  createGroup(group: Json) { return this.request("POST", "/api/v1/groups", json(group)); }
  updateGroup(id: string, group: Json) { return this.request("PATCH", `/api/v1/groups/${encodeURIComponent(id)}`, json(group)); }
  deleteGroup(id: string) { return this.request("DELETE", `/api/v1/groups/${encodeURIComponent(id)}`); }
  addGroupMember(id: string, member: Json) { return this.request("POST", `/api/v1/groups/${encodeURIComponent(id)}/members`, json(member)); }
  removeGroupMember(id: string, agentId: string) { return this.request("DELETE", `/api/v1/groups/${encodeURIComponent(id)}/members/${encodeURIComponent(agentId)}`); }
  broadcastGroup(id: string, message: Json, excludeSender = true) { return this.request("POST", `/api/v1/groups/${encodeURIComponent(id)}/messages`, json({message, exclude_sender: excludeSender})); }
  presence(serviceAgentIds: string[]) { return this.request("GET", query("/api/v1/presence", { service_agent_ids: serviceAgentIds.join(",") })); }
  reportHealth(report: Json) { return this.request("POST", "/api/v1/health_reports", json(report)); }
  agentHealth(id: string) { return this.request("GET", `/api/v1/agents/${encodeURIComponent(id)}/health`); }
  queue() { return this.request("GET", "/api/v1/queue"); }
  socketToken() { return this.request<SocketToken>("POST", "/api/v1/socket_tokens"); }
}

export interface SocketToken {
  socket_token: string;
  expires_in: number;
  workspace_id: string;
  service_agent_id: string;
  scopes: string[];
  socket_path: string;
}

function json(body: Json): RequestInit {
  return { body: JSON.stringify(body) };
}

function asObject(value: Json): { [key: string]: Json } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new TypeError("message must be an object");
  return {...value};
}

function query(path: string, params: Record<string, string>): string {
  const queryString = new URLSearchParams(params).toString();
  return queryString ? `${path}?${queryString}` : path;
}

async function responseError(response: Response): Promise<ApiError> {
  const raw = await response.text();
  let details: unknown;
  try { details = JSON.parse(raw); } catch { details = raw; }
  const body = typeof details === "object" && details ? details as Record<string, unknown> : {};
  const message = String(body.detail ?? body.message ?? body.title ?? response.statusText);
  const code = body.code ?? body.error;
  const args = [message, response.status, code == null ? undefined : String(code), details, response.headers.get("x-request-id") ?? undefined] as const;
  if (response.status === 401) return new AuthenticationError(...args);
  if (response.status === 403) return new AuthorizationError(...args);
  if (response.status === 429) {
    if (code === "quota_exceeded" || code === "workspace_quota_exceeded") return new QuotaError(...args);
    return new RateLimitError(...args, retryAfterSeconds(response.headers.get("retry-after")));
  }
  if (response.status === 402) return new PaymentRequiredError(...args);
  if (response.status === 404) return new NotFoundError(...args);
  if (response.status === 409) return new ConflictError(...args);
  if (response.status === 422) return new ValidationError(...args);
  return new ApiError(...args);
}

function retryAfterSeconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return seconds;
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, (date - Date.now()) / 1000) : undefined;
}

const sleep = (seconds: number) => new Promise<void>((resolve) => setTimeout(resolve, seconds * 1000));
const delay = (attempt: number, retryAfter?: number) => retryAfter ?? Math.min(0.25 * 2 ** attempt + Math.random() * 0.1, 5);

export {RobotsCenterClient as Client};
