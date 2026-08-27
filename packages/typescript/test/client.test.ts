import { describe, expect, it, vi } from "vitest";
import { ApiError, Client } from "../src/index.js";

describe("Client", () => {
  it("sends bearer auth to the v1 path", async () => {
    const fetcher = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      expect(String(input)).toBe("https://example.test/api/v1/agents/me");
      expect(new Headers(init?.headers).get("authorization")).toBe("Bearer agk_test");
      return new Response(JSON.stringify({ id: "agent-1" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    const client = new Client({ token: "agk_test", baseUrl: "https://example.test", fetch: fetcher as typeof fetch });
    await expect(client.me()).resolves.toEqual({ id: "agent-1" });
  });

  it("maps problem details", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ title: "Invalid", code: "invalid" }), {
      status: 422,
      headers: { "content-type": "application/problem+json" },
    }));
    const client = new Client({ token: "test", fetch: fetcher as typeof fetch });
    await expect(client.sendMessage({})).rejects.toMatchObject({ status: 422, code: "invalid" } satisfies Partial<ApiError>);
  });

  it("reuses supplied body message_id across a retry", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    const fetcher = vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return new Response(JSON.stringify({accepted: true}), {
        status: bodies.length === 1 ? 503 : 202,
        headers: {"content-type": "application/json"},
      });
    });
    const client = new Client({token: "test", fetch: fetcher as typeof fetch, maxRetries: 1});
    await client.sendMessage({message_id: "stable", recipient: {agent_id: "a"}, payload: {}});
    expect(bodies).toHaveLength(2);
    expect(bodies[0]?.message_id).toBe(bodies[1]?.message_id);
  });

  it.each([
    ["agents", "/api/v1/agents"],
    ["tasks", "/api/v1/tasks"],
    ["groups", "/api/v1/groups"],
    ["queue", "/api/v1/queue"],
  ])("calls the %s resource contract", async (resource, path) => {
    const fetcher = vi.fn(async (input: string | URL | Request) => {
      expect(new URL(String(input)).pathname).toBe(path);
      return new Response("{}", {status: 200, headers: {"content-type": "application/json"}});
    });
    const client = new Client({token: "test", fetch: fetcher as typeof fetch});
    await (client[resource as "agents" | "tasks" | "groups" | "queue"] as () => Promise<unknown>)();
  });
});
