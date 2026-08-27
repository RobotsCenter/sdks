import { Channel, Socket } from "phoenix";
import { RealtimeError } from "./errors.js";

export interface RealtimeOptions {
  baseUrl?: string;
  socketToken?: string;
  serviceAgentId?: string;
  tokenProvider?: () => Promise<{socket_token: string; service_agent_id: string}>;
  joinPayload?: Record<string, unknown>;
  timeoutMs?: number;
  logger?: (kind: string, message: string, data?: unknown) => void;
  reconnect?: boolean;
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
  private readonly subscriptions = new Map<string, [string, Record<string, unknown>]>();
  private readonly handlers = new Map<number, [string, (payload: Record<string, unknown>) => void]>();
  private nextHandlerRef = 1;
  private joining = false;

  constructor(options: RealtimeOptions) {
    if (!options.tokenProvider && options.reconnect === true) throw new RealtimeError("reconnect requires tokenProvider so expired socket tokens are never reused");
    this.options = options;
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  async connect(): Promise<Record<string, unknown>> {
    this.explicitlyClosed = false;
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.channel?.leave();
    this.socket?.disconnect();
    const fresh = this.options.tokenProvider ? await this.options.tokenProvider() : undefined;
    const socketToken = fresh?.socket_token ?? this.options.socketToken;
    const serviceAgentId = fresh?.service_agent_id ?? this.options.serviceAgentId;
    if (!socketToken || !serviceAgentId) throw new RealtimeError("tokenProvider or socketToken and serviceAgentId are required");
    const base = (this.options.baseUrl ?? "https://robotscenter.net").replace(/^http/, "ws").replace(/\/$/, "");
    const socketOptions = {
      params: { socket_token: socketToken },
      reconnectAfterMs: () => 86_400_000,
      heartbeatIntervalMs: 20_000,
      ...(this.options.logger ? {logger: this.options.logger} : {}),
    };
    this.socket = new Socket(`${base}/socket`, socketOptions);
    this.socket.onClose(() => { if (!this.joining) this.scheduleReconnect(); });
    this.socket.onError(() => { if (!this.joining) this.scheduleReconnect(); });
    this.channel = this.socket.channel(`agent:${serviceAgentId}`, this.options.joinPayload ?? {});
    this.assertFrameSize("phx_join", this.options.joinPayload ?? {}, `agent:${serviceAgentId}`);
    this.socket.connect();
    let response: Record<string, unknown>;
    this.joining = true;
    try {
      response = await pushPromise(this.channel.join(this.timeoutMs), "channel join");
    } catch (error) {
      if (error instanceof RealtimeError && error.terminal) this.explicitlyClosed = true;
      else this.scheduleReconnect();
      throw error;
    } finally {
      this.joining = false;
    }
    this.reconnectAttempt = 0;
    for (const [, [event, handler]] of this.handlers) this.channel.on(event, handler);
    for (const [event, payload] of this.subscriptions.values()) await pushPromise(this.channel.push(event, payload, this.timeoutMs), event);
    this.heartbeatTimer = setInterval(() => this.channel?.push("agent.heartbeat", {}, this.timeoutMs), 20_000);
    return response;
  }

  close(): void {
    this.explicitlyClosed = true;
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = undefined;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
    this.channel?.leave();
    this.socket?.disconnect();
    this.channel = undefined;
    this.socket = undefined;
  }

  push(event: string, payload: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    try { this.assertFrameSize(event, payload, this.channel?.topic ?? "agent"); }
    catch (error) { return Promise.reject(error); }
    if (!this.channel) return Promise.reject(new RealtimeError("realtime channel is not connected"));
    return pushPromise(this.channel.push(event, payload, this.timeoutMs), event);
  }

  on(event: string, handler: (payload: Record<string, unknown>) => void): number {
    const ref = this.nextHandlerRef++;
    this.handlers.set(ref, [event, handler]);
    this.channel?.on(event, handler);
    return ref;
  }

  off(event: string, ref?: number): void {
    if (ref !== undefined) this.handlers.delete(ref);
    else for (const [key, value] of this.handlers) if (value[0] === event) this.handlers.delete(key);
    this.channel?.off(event);
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
    for (const [key, [event, payload]] of this.subscriptions) {
      if (event !== "presence.subscribe") continue;
      this.subscriptions.delete(key);
      const remaining = ((payload.service_agent_ids as string[] | undefined) ?? []).filter((id) => !removed.has(id));
      if (remaining.length) {
        const next = {service_agent_ids: remaining};
        this.subscriptions.set(`${event}:${JSON.stringify(next)}`, [event, next]);
      }
    }
    return result;
  }
  reportHealth(metrics: Record<string, unknown>) { return this.push("health.report", {metrics}); }
  rpcResponse(correlationId: string, result: unknown) { return this.push("rpc.response", {correlation_id: correlationId, result}); }
  queueStats() { return this.push("queue.stats"); }
  unsubscribeQueue() { for (const [key, value] of this.subscriptions) if (value[0] === "queue.subscribe") this.subscriptions.delete(key); return this.push("queue.unsubscribe"); }
  commandAccepted(commandId: string, resultPayload: Record<string, unknown> = {}) { return this.push("command.accepted", {command_id: commandId, result_payload: resultPayload}); }
  commandProgress(commandId: string, resultPayload: Record<string, unknown>) { return this.push("command.progress", {command_id: commandId, result_payload: resultPayload}); }
  commandComplete(commandId: string, resultPayload: Record<string, unknown> = {}, status: "succeeded" | "cancelled" = "succeeded") { return this.push("command.complete", {command_id: commandId, result_payload: resultPayload, status}); }
  commandFail(commandId: string, errorPayload: Record<string, unknown>, status: "failed" | "cancelled" = "failed") { return this.push("command.fail", {command_id: commandId, error_payload: errorPayload, status}); }

  private async subscribe(event: string, payload: Record<string, unknown>) {
    const response = await this.push(event, payload);
    this.subscriptions.set(`${event}:${JSON.stringify(payload)}`, [event, payload]);
    return response;
  }

  private scheduleReconnect(): void {
    const reconnect = this.options.reconnect ?? Boolean(this.options.tokenProvider);
    if (!reconnect || this.explicitlyClosed || this.reconnectTimer) return;
    this.socket?.disconnect();
    const schedule = [1_000, 2_000, 5_000, 10_000, 30_000];
    const base = schedule[Math.min(this.reconnectAttempt, schedule.length - 1)]!;
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      void this.connect().catch(() => this.scheduleReconnect());
    }, base * (0.8 + Math.random() * 0.4));
  }

  private assertFrameSize(event: string, payload: Record<string, unknown>, topic: string): void {
    const bytes = new TextEncoder().encode(JSON.stringify([null, null, topic, event, payload])).byteLength;
    if (bytes > 65_536) throw new RealtimeError("Phoenix frame exceeds the 64 KiB payload limit");
  }
}

function pushPromise(push: ReturnType<Channel["push"]>, operation: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    push.receive("ok", (response) => resolve(response as Record<string, unknown>));
    push.receive("error", (response) => reject(new RealtimeError(`${operation} failed: ${JSON.stringify(response)}`, isTerminal(response))));
    push.receive("timeout", () => reject(new RealtimeError(`${operation} timed out`)));
  });
}

function isTerminal(value: unknown): boolean {
  if (typeof value === "string") return ["unauthorized", "workspace_frozen", "workspace_paused", "workspace_archived", "workspace_unavailable"].includes(value);
  if (!value || typeof value !== "object") return false;
  return Object.values(value as Record<string, unknown>).some(isTerminal);
}
