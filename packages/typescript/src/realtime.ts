import { Channel, Socket, type SocketConnectOption } from "phoenix";
import { RealtimeError } from "./errors.js";

const MAX_FRAME_BYTES = 65_536;
const HEARTBEAT_INTERVAL_MS = 20_000;
const INTERNAL_RECONNECT_DISABLED_MS = 86_400_000;
const RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 30_000] as const;
const TERMINAL_REASONS = new Set([
  "unauthorized", "workspace_frozen", "workspace_paused", "workspace_archived", "workspace_unavailable",
]);

type Handler = (payload: Record<string, unknown>) => void;
type TransportConstructor = SocketConnectOption["transport"];
type HandlerBinding = {event: string; handler: Handler; liveRef?: number};

export interface RealtimeOptions {
  baseUrl?: string;
  socketToken?: string;
  serviceAgentId?: string;
  tokenProvider?: () => Promise<{socket_token: string; service_agent_id: string}>;
  joinPayload?: Record<string, unknown>;
  timeoutMs?: number;
  logger?: (kind: string, message: string, data?: unknown) => void;
  reconnect?: boolean;
  /** Custom Phoenix transport for deterministic tests or a Node WebSocket polyfill. */
  transport?: TransportConstructor;
}

export class Realtime {
  socket: Socket | undefined;
  channel: Channel | undefined;
  private readonly timeoutMs: number;
  private readonly options: RealtimeOptions;
  private heartbeatTimer: ReturnType<typeof setInterval> | undefined;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private reconnectAttempt = 0;
  private explicitlyClosed = false;
  private terminal = false;
  private readonly subscriptions = new Map<string, [string, Record<string, unknown>]>();
  private readonly handlers = new Map<number, HandlerBinding>();
  private nextHandlerRef = 1;

  constructor(options: RealtimeOptions) {
    if (!options.tokenProvider && options.reconnect === true) {
      throw new RealtimeError("reconnect requires tokenProvider so expired socket tokens are never reused");
    }
    this.options = options;
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  async connect(): Promise<Record<string, unknown>> {
    this.explicitlyClosed = false;
    this.terminal = false;
    this.cancelReconnect();
    try {
      return await this.openConnection();
    } catch (error) {
      const realtimeError = asRealtimeError(error, "connection failed");
      this.cleanupConnection();
      if (realtimeError.terminal) this.terminal = true;
      else this.scheduleReconnect();
      throw realtimeError;
    }
  }

  close(): void {
    this.explicitlyClosed = true;
    this.terminal = true;
    this.cancelReconnect();
    this.cleanupConnection(true);
  }

  disconnect(): void {
    this.explicitlyClosed = true;
    this.terminal = true;
    this.cancelReconnect();
    try { if (this.channel) this.pushChecked(this.channel, "disconnect", {}); }
    finally { this.cleanupConnection(false); }
  }

  push(event: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    if (!this.channel) return Promise.reject(new RealtimeError("realtime channel is not connected"));
    try { return pushPromise(this.pushChecked(this.channel, event, payload), event); }
    catch (error) { return Promise.reject(asRealtimeError(error, `${event} failed`)); }
  }

  on(event: string, handler: Handler): number {
    const ref = this.nextHandlerRef++;
    const binding: HandlerBinding = {event, handler};
    if (this.channel) binding.liveRef = bindHandler(this.channel, binding);
    this.handlers.set(ref, binding);
    return ref;
  }

  off(event: string, ref?: number): void {
    if (ref === undefined) {
      for (const [key, binding] of this.handlers) {
        if (binding.event !== event) continue;
        if (binding.liveRef !== undefined) this.channel?.off(event, binding.liveRef);
        this.handlers.delete(key);
      }
      return;
    }
    const binding = this.handlers.get(ref);
    if (!binding || binding.event !== event) return;
    if (binding.liveRef !== undefined) this.channel?.off(event, binding.liveRef);
    this.handlers.delete(ref);
  }

  ready(metadata: Record<string, unknown> = {}) { return this.push("agent.ready", metadata); }
  heartbeat(metadata: Record<string, unknown> = {}) { return this.push("agent.heartbeat", metadata); }
  sendMessage(message: Record<string, unknown>) { return this.push("message.send", {message}); }
  discover(query: Record<string, unknown>) { return this.push("agent.discover", query); }
  createTask(task: Record<string, unknown>) { return this.push("task.create", {task}); }
  rpc(request: Record<string, unknown>) { return this.push("rpc.request", {message: request}); }
  subscribeTasks(taskIds: string[]) { return this.subscribe("task.subscribe", {task_ids: taskIds}); }
  subscribeGroups(groupIds: string[]) { return this.subscribe("group.subscribe", {group_ids: groupIds}); }
  subscribePresence(serviceAgentIds: string[]) { return this.subscribe("presence.subscribe", {service_agent_ids: serviceAgentIds}); }
  subscribeQueue() { return this.subscribe("queue.subscribe", {}); }
  acknowledgeMessage(messageId: string) { return this.push("message.delivered", {message_id: messageId}); }
  completeTask(taskId: string, result: Record<string, unknown> = {}, retryCount = 0) { return this.push("task.complete", {task_id: taskId, result, retry_count: retryCount}); }
  failTask(taskId: string, errorMessage: string, retryCount = 0) { return this.push("task.fail", {task_id: taskId, error_message: errorMessage, retry_count: retryCount}); }
  cancelTask(taskId: string) { return this.push("task.cancel", {task_id: taskId}); }
  retryTask(taskId: string) { return this.push("task.retry", {task_id: taskId}); }
  createGroup(group: Record<string, unknown>) { return this.push("group.create", {group}); }
  listGroups() { return this.push("group.list"); }
  addGroupMember(groupId: string, serviceAgentId: string, role = "member") { return this.push("group.add_member", {group_id: groupId, service_agent_id: serviceAgentId, role}); }
  removeGroupMember(groupId: string, serviceAgentId: string) { return this.push("group.remove_member", {group_id: groupId, service_agent_id: serviceAgentId}); }
  broadcastGroup(groupId: string, message: Record<string, unknown>) { return this.push("group.broadcast", {group_id: groupId, message}); }

  async unsubscribePresence(serviceAgentIds: string[]) {
    const result = await this.push("presence.unsubscribe", {service_agent_ids: serviceAgentIds});
    const removed = new Set(serviceAgentIds);
    for (const [key, [event, payload]] of [...this.subscriptions]) {
      if (event !== "presence.subscribe") continue;
      this.subscriptions.delete(key);
      const remaining = ((payload.service_agent_ids as string[] | undefined) ?? []).filter((id) => !removed.has(id));
      if (remaining.length) {
        const next = {service_agent_ids: remaining};
        this.subscriptions.set(subscriptionKey(event, next), [event, next]);
      }
    }
    return result;
  }

  reportHealth(metrics: Record<string, unknown>) { return this.push("health.report", {metrics}); }
  rpcResponse(correlationId: string, result: unknown) { return this.push("rpc.response", {correlation_id: correlationId, result}); }
  queueStats() { return this.push("queue.stats"); }
  async unsubscribeQueue() {
    const result = await this.push("queue.unsubscribe");
    for (const [key, value] of this.subscriptions) if (value[0] === "queue.subscribe") this.subscriptions.delete(key);
    return result;
  }
  commandAccepted(commandId: string, resultPayload: Record<string, unknown> = {}) { return this.push("command.accepted", {command_id: commandId, result_payload: resultPayload}); }
  commandProgress(commandId: string, resultPayload: Record<string, unknown>) { return this.push("command.progress", {command_id: commandId, result_payload: resultPayload}); }
  commandComplete(commandId: string, resultPayload: Record<string, unknown> = {}, status: "succeeded" | "cancelled" = "succeeded") { return this.push("command.complete", {command_id: commandId, result_payload: resultPayload, status}); }
  commandFail(commandId: string, errorPayload: Record<string, unknown>, status: "failed" | "cancelled" = "failed") { return this.push("command.fail", {command_id: commandId, error_payload: errorPayload, status}); }

  private async openConnection(): Promise<Record<string, unknown>> {
    this.cleanupConnection();
    const fresh = this.options.tokenProvider ? await this.options.tokenProvider() : undefined;
    const socketToken = fresh?.socket_token ?? this.options.socketToken;
    const serviceAgentId = fresh?.service_agent_id ?? this.options.serviceAgentId;
    if (!socketToken || !serviceAgentId) throw new RealtimeError("tokenProvider or socketToken and serviceAgentId are required");

    const socketOptions: Partial<SocketConnectOption> = {
      params: {socket_token: socketToken},
      heartbeatIntervalMs: HEARTBEAT_INTERVAL_MS,
      reconnectAfterMs: () => INTERNAL_RECONNECT_DISABLED_MS,
      rejoinAfterMs: () => INTERNAL_RECONNECT_DISABLED_MS,
      encode: encodeFrame,
      decode: decodeFrame,
      ...(this.options.logger ? {logger: this.options.logger} : {}),
      ...(this.options.transport ? {transport: this.options.transport} : {}),
    };
    const socket = new Socket(socketEndpoint(this.options.baseUrl ?? "https://robotscenter.net"), socketOptions);
    const channel = socket.channel(`agent:${serviceAgentId}`, this.options.joinPayload ?? {});
    this.socket = socket;
    this.channel = channel;
    socket.onClose((reason) => this.handleConnectionLoss(reason));
    socket.onError((reason) => this.handleConnectionLoss(reason));
    channel.onClose((reason) => this.handleConnectionLoss(reason));
    channel.onError((reason) => this.handleConnectionLoss(reason));
    socket.connect();

    this.assertNextFrameSize(channel, "phx_join", this.options.joinPayload ?? {}, true);
    const response = await pushPromise(channel.join(this.timeoutMs), "channel join");
    for (const binding of this.handlers.values()) binding.liveRef = bindHandler(channel, binding);
    for (const [event, payload] of this.subscriptions.values()) await pushPromise(this.pushChecked(channel, event, payload), event);
    this.reconnectAttempt = 0;
    this.startAgentHeartbeat();
    return response;
  }

  private handleConnectionLoss(reason: unknown): void {
    const terminal = isTerminal(reason);
    if (terminal) {
      this.terminal = true;
      this.cancelReconnect();
      this.cleanupConnection();
      return;
    }
    if (this.explicitlyClosed || (!this.socket && !this.channel)) return;
    this.cleanupConnection();
    this.scheduleReconnect();
  }

  private async subscribe(event: string, payload: Record<string, unknown>) {
    const response = await this.push(event, payload);
    this.subscriptions.set(subscriptionKey(event, payload), [event, payload]);
    return response;
  }

  private startAgentHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      this.push("agent.heartbeat").catch((error) => this.handleConnectionLoss(error));
    }, HEARTBEAT_INTERVAL_MS);
  }

  private pushChecked(channel: Channel, event: string, payload: Record<string, unknown>) {
    this.assertNextFrameSize(channel, event, payload, false);
    return channel.push(event, payload, this.timeoutMs);
  }

  private assertNextFrameSize(channel: Channel, event: string, payload: Record<string, unknown>, joining: boolean): void {
    const socket = this.socket;
    if (!socket) throw new RealtimeError("realtime channel is not connected");
    const currentRef = (socket as unknown as {ref: number}).ref;
    const nextNumber = currentRef + 1 === currentRef ? 0 : currentRef + 1;
    const ref = String(nextNumber);
    const joinRef = joining ? ref : (channel as unknown as {joinRef(): string | null}).joinRef();
    const encoded = JSON.stringify([joinRef, ref, channel.topic, event, payload]);
    if (new TextEncoder().encode(encoded).byteLength > MAX_FRAME_BYTES) {
      throw new RealtimeError("Phoenix frame exceeds the 64 KiB payload limit");
    }
  }

  private scheduleReconnect(): void {
    const reconnect = this.options.reconnect ?? Boolean(this.options.tokenProvider);
    if (!reconnect || this.explicitlyClosed || this.terminal || this.reconnectTimer) return;
    const base = RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)]!;
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.openConnection().catch((error) => {
        const realtimeError = asRealtimeError(error, "reconnect failed");
        this.cleanupConnection();
        if (realtimeError.terminal) this.terminal = true;
        else this.scheduleReconnect();
      });
    }, base * (0.8 + Math.random() * 0.4));
  }

  private cleanupConnection(leave = false): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = undefined;
    const channel = this.channel;
    const socket = this.socket;
    this.channel = undefined;
    this.socket = undefined;
    for (const binding of this.handlers.values()) delete binding.liveRef;
    if (leave && channel) {
      try { channel.leave(this.timeoutMs); } catch { /* Already closed. */ }
    }
    if (socket) {
      try { socket.disconnect(); } catch { /* Already closed. */ }
    }
  }

  private cancelReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
  }
}

function encodeFrame(message: object, callback: (encoded: string) => void | Promise<void>): void {
  const value = message as {join_ref?: string | null; ref?: string | null; topic?: string; event?: string; payload?: unknown};
  const encoded = JSON.stringify([value.join_ref ?? null, value.ref ?? null, value.topic, value.event, value.payload]);
  if (new TextEncoder().encode(encoded).byteLength > MAX_FRAME_BYTES) throw new RealtimeError("Phoenix frame exceeds the 64 KiB payload limit");
  void callback(encoded);
}

function decodeFrame(raw: string, callback: (decoded: object) => void | Promise<void>): void {
  if (new TextEncoder().encode(raw).byteLength > MAX_FRAME_BYTES) throw new RealtimeError("Phoenix frame exceeds the 64 KiB payload limit");
  const frame: unknown = JSON.parse(raw);
  if (!Array.isArray(frame) || frame.length !== 5) throw new RealtimeError("invalid Phoenix v2 frame");
  const [join_ref, ref, topic, event, payload] = frame;
  void callback({join_ref, ref, topic, event, payload});
}

function socketEndpoint(baseUrl: string): string {
  return `${baseUrl.replace(/^http/, "ws").replace(/\/$/, "")}/socket`;
}

function subscriptionKey(event: string, payload: Record<string, unknown>): string {
  return `${event}:${JSON.stringify(payload)}`;
}

function bindHandler(channel: Channel, binding: HandlerBinding): number {
  return channel.on(binding.event, (payload) => binding.handler(asPayload(payload)));
}

function pushPromise(push: ReturnType<Channel["push"]>, operation: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    push.receive("ok", (response) => resolve(asPayload(response)));
    push.receive("error", (response) => reject(new RealtimeError(`${operation} failed: ${JSON.stringify(response)}`, isTerminal(response))));
    push.receive("timeout", () => reject(new RealtimeError(`${operation} timed out`)));
  });
}

function asPayload(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {value};
}

function isTerminal(value: unknown): boolean {
  if (typeof value === "string") return TERMINAL_REASONS.has(value);
  if (!value || typeof value !== "object") return false;
  if ("status" in value && (value as {status?: unknown}).status === 401) return true;
  return Object.values(value as Record<string, unknown>).some(isTerminal);
}

function asRealtimeError(error: unknown, prefix: string): RealtimeError {
  if (error instanceof RealtimeError) return error;
  const message = typeof error === "string" ? error : JSON.stringify(error);
  return new RealtimeError(`${prefix}: ${message}`, isTerminal(error));
}
