import {describe, expect, it, vi} from "vitest";
import {Realtime, RealtimeError} from "../src/index.js";

describe("Realtime", () => {
  it("requires a token source at connect time", async () => {
    const realtime = new Realtime({});
    await expect(realtime.connect()).rejects.toBeInstanceOf(RealtimeError);
  });

  it("retains subscriptions for reconnect replay", async () => {
    const realtime = new Realtime({socketToken: "token", serviceAgentId: "agent"});
    realtime.push = vi.fn(async () => ({}));
    await realtime.subscribeTasks(["task-1"]);
    await realtime.subscribeGroups(["group-1"]);
    await realtime.subscribePresence(["agent-2"]);
    await realtime.subscribeQueue();
    expect((realtime as unknown as {subscriptions: Map<string, unknown>}).subscriptions.size).toBe(4);
    realtime.close();
  });

  it("does not retain a failed subscription", async () => {
    const realtime = new Realtime({socketToken: "token", serviceAgentId: "agent"});
    realtime.push = vi.fn(async () => { throw new RealtimeError("failure"); });
    await expect(realtime.subscribeQueue()).rejects.toBeInstanceOf(RealtimeError);
    expect((realtime as unknown as {subscriptions: Map<string, unknown>}).subscriptions.size).toBe(0);
  });

  it("rejects oversized frames", async () => {
    const realtime = new Realtime({socketToken: "token", serviceAgentId: "agent"});
    await expect(realtime.push("event", {body: "x".repeat(66_000)})).rejects.toThrow("64 KiB");
  });
});
