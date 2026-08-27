import {afterEach, describe, expect, it, vi} from "vitest";
import {Realtime, RealtimeError} from "../src/index.js";

type ReplyMode = "ok" | "terminal-join";

class FakeSocket {
  readyState = 0;
  bufferedAmount = 0;
  binaryType = "arraybuffer";
  onopen: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onmessage: ((event: unknown) => void) | null = null;
  readonly sent: string[] = [];
  closed = false;

  constructor(readonly url: string, readonly replyMode: ReplyMode = "ok") {
    queueMicrotask(() => { this.readyState = 1; this.onopen?.({}); });
  }

  send(data: string): void {
    this.sent.push(data);
    const [joinRef, ref, topic, event] = JSON.parse(data) as [string | null, string, string, string, unknown];
    if (event === "disconnect") return;
    const response = event === "phx_join" && this.replyMode === "terminal-join"
      ? {status: "error", response: {reason: "workspace_frozen"}}
      : {status: "ok", response: {event}};
    queueMicrotask(() => this.message([joinRef, ref, topic, "phx_reply", response]));
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = 3;
    this.onclose?.({code: 1000, reason: "client cleanup"});
  }

  fail(reason: string): void {
    this.readyState = 3;
    this.onclose?.({code: 4000, reason});
  }

  serverEvent(event: string, payload: Record<string, unknown>): void {
    const join = this.sent.map((item) => JSON.parse(item) as unknown[]).find((item) => item[3] === "phx_join");
    this.message([join?.[0], null, join?.[2], event, payload]);
  }

  private message(frame: unknown[]): void {
    this.onmessage?.({data: JSON.stringify(frame)});
  }
}

const frame = (socket: FakeSocket, event: string) => socket.sent.map((item) => JSON.parse(item) as unknown[]).find((item) => item[3] === event);

function fixture(replyModes: ReplyMode[] = []) {
  const sockets: FakeSocket[] = [];
  const factory = class {
    constructor(url: string) {
    const socket = new FakeSocket(url, replyModes[sockets.length] ?? "ok");
    sockets.push(socket);
      return socket;
    }
  };
  return {sockets, factory: factory as never};
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Realtime Phoenix v2 lifecycle", () => {
  it("uses a fresh token, exact v2 frame, and both 20-second heartbeats", async () => {
    vi.useFakeTimers();
    const {sockets, factory} = fixture();
    const provider = vi.fn(async () => ({socket_token: "fresh token", service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});

    const connected = realtime.connect();
    await vi.runAllTicks();
    await expect(connected).resolves.toEqual({event: "phx_join"});
    expect(provider).toHaveBeenCalledTimes(1);
    const url = new URL(sockets[0]!.url);
    expect(url.pathname).toBe("/socket/websocket");
    expect(url.searchParams.get("vsn")).toBe("2.0.0");
    expect(url.searchParams.get("socket_token")).toBe("fresh token");
    const join = frame(sockets[0]!, "phx_join")!;
    expect(join).toHaveLength(5);
    expect(join[0]).toBe(join[1]);
    expect(join.slice(2)).toEqual(["agent:agent", "phx_join", {}]);

    await vi.advanceTimersByTimeAsync(20_000);
    expect(frame(sockets[0]!, "heartbeat")?.[2]).toBe("phoenix");
    expect(frame(sockets[0]!, "agent.heartbeat")?.[2]).toBe("agent:agent");
    realtime.close();
  });

  it("has one reconnect controller, refreshes token, replays active arrays, and retains exact handlers", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const {sockets, factory} = fixture();
    let token = 0;
    const provider = vi.fn(async () => ({socket_token: `token-${++token}`, service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await connected;
    await realtime.subscribePresence(["a", "b"]);
    await realtime.unsubscribePresence(["a"]);

    const kept = vi.fn();
    const removed = vi.fn();
    realtime.on("message.receive", kept);
    const removedRef = realtime.on("message.receive", removed);
    realtime.off("message.receive", removedRef);

    sockets[0]!.fail("network_lost");
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.runAllTicks();
    expect(provider).toHaveBeenCalledTimes(2);
    expect(sockets).toHaveLength(2);
    expect(sockets[0]!.readyState).toBe(3);
    expect(frame(sockets[1]!, "presence.subscribe")?.[4]).toEqual({service_agent_ids: ["b"]});

    sockets[1]!.serverEvent("message.receive", {message_id: "m-1"});
    expect(kept).toHaveBeenCalledWith({message_id: "m-1"});
    expect(removed).not.toHaveBeenCalled();
    realtime.close();
  });

  it("classifies terminal channel replies and closes without reconnect", async () => {
    vi.useFakeTimers();
    const {sockets, factory} = fixture(["terminal-join"]);
    const provider = vi.fn(async () => ({socket_token: "token", service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await expect(connected).rejects.toMatchObject({terminal: true});
    await vi.advanceTimersByTimeAsync(60_000);
    expect(provider).toHaveBeenCalledTimes(1);
    expect(sockets[0]!.closed).toBe(true);
  });

  it("classifies terminal socket close payloads and does not reconnect", async () => {
    vi.useFakeTimers();
    const {sockets, factory} = fixture();
    const provider = vi.fn(async () => ({socket_token: "token", service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await connected;
    sockets[0]!.fail("workspace_archived");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(provider).toHaveBeenCalledTimes(1);
  });

  it("classifies terminal Phoenix channel events and cancels queued reconnect", async () => {
    vi.useFakeTimers();
    const {sockets, factory} = fixture();
    const provider = vi.fn(async () => ({socket_token: "token", service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await connected;
    sockets[0]!.serverEvent("phx_error", {reason: "workspace_paused"});
    await vi.advanceTimersByTimeAsync(60_000);
    expect(provider).toHaveBeenCalledTimes(1);
    expect(sockets[0]!.readyState).toBe(3);
  });

  it("does not loop when a reconnect token provider returns HTTP 401", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    const {sockets, factory} = fixture();
    const provider = vi.fn()
      .mockResolvedValueOnce({socket_token: "token", service_agent_id: "agent"})
      .mockRejectedValueOnce({status: 401, code: "unauthorized"});
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await connected;
    sockets[0]!.fail("network_lost");
    await vi.advanceTimersByTimeAsync(1_000);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(provider).toHaveBeenCalledTimes(2);
    expect(sockets).toHaveLength(1);
  });

  it("checks and cleans up an oversized join frame", async () => {
    const {sockets, factory} = fixture();
    const realtime = new Realtime({
      socketToken: "token",
      serviceAgentId: "agent",
      joinPayload: {metadata: "x".repeat(66_000)},
      transport: factory,
    });
    await expect(realtime.connect()).rejects.toThrow("64 KiB");
    expect(sockets).toHaveLength(1);
    expect(sockets[0]!.closed).toBe(true);
  });

  it("uses the complete encoded frame for the exact 65,536-byte boundary", async () => {
    const {sockets, factory} = fixture();
    const realtime = new Realtime({socketToken: "token", serviceAgentId: "agent-id-long", transport: factory});
    const connected = realtime.connect();
    await vi.waitFor(() => expect(sockets).toHaveLength(1));
    await connected;

    let low = 0;
    let high = 65_536;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      try { await realtime.push("event", {body: "x".repeat(middle)}); low = middle; }
      catch { high = middle - 1; }
    }
    await expect(realtime.push("event", {body: "x".repeat(low)})).resolves.toEqual({event: "event"});
    expect(new TextEncoder().encode(sockets[0]!.sent.at(-1)!).byteLength).toBeLessThanOrEqual(65_536);
    await expect(realtime.push("event", {body: "x".repeat(low + 1)})).rejects.toThrow("64 KiB");
    realtime.close();
  });

  it("disconnect sends the canonical no-reply event and performs terminal cleanup", async () => {
    vi.useFakeTimers();
    const {sockets, factory} = fixture();
    const provider = vi.fn(async () => ({socket_token: "token", service_agent_id: "agent"}));
    const realtime = new Realtime({tokenProvider: provider, transport: factory});
    const connected = realtime.connect();
    await vi.runAllTicks();
    await connected;
    realtime.disconnect();
    expect(frame(sockets[0]!, "disconnect")).toBeTruthy();
    expect(sockets[0]!.closed).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(provider).toHaveBeenCalledTimes(1);
  });

  it("does not retain rejected subscriptions", async () => {
    const realtime = new Realtime({socketToken: "token", serviceAgentId: "agent"});
    realtime.push = vi.fn(async () => { throw new RealtimeError("failure"); });
    await expect(realtime.subscribeQueue()).rejects.toBeInstanceOf(RealtimeError);
    expect((realtime as unknown as {subscriptions: Map<string, unknown>}).subscriptions.size).toBe(0);
  });
});
