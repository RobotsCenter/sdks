import {describe, expectTypeOf, test} from "vitest";

import type {
  Agent,
  AgentHealth,
  CredentialCreateResponse,
  Group,
  Message,
  MessageCreateRequest,
  MessageDispatchResponse,
  PresenceResponse,
  Problem,
  QueueStatsResponse,
  RegistrationResponse,
  SocketTokenResponse,
  Task,
  TaskListResponse,
  TokenResponse,
} from "../src/models.js";

describe("public REST models", () => {
  test("required response fields preserve OpenAPI scalar and collection types", () => {
    expectTypeOf<Agent>().toHaveProperty("service_agent_id").toEqualTypeOf<string>();
    expectTypeOf<Agent>().toHaveProperty("metadata").toEqualTypeOf<Record<string, unknown>>();
    expectTypeOf<Message>().toHaveProperty("cost_cents").toEqualTypeOf<string>();
    expectTypeOf<Message>().toHaveProperty("recipient_discovery").toEqualTypeOf<"direct" | "broadcast" | "capability_match">();
    expectTypeOf<Task>().toHaveProperty("retry_count").toEqualTypeOf<number>();
    expectTypeOf<Group>().toHaveProperty("members").toMatchTypeOf<Array<{service_agent_id: string}>>();
    expectTypeOf<TaskListResponse>().toHaveProperty("pagination").toEqualTypeOf<{offset: number; limit: number}>();
  });

  test("request, dispatch, auth, and operational response types are public", () => {
    expectTypeOf<MessageCreateRequest>().toHaveProperty("recipient").toMatchTypeOf<{discovery?: string}>();
    expectTypeOf<MessageDispatchResponse>().toHaveProperty("recipients").toEqualTypeOf<string[]>();
    expectTypeOf<CredentialCreateResponse>().toHaveProperty("secret").toEqualTypeOf<string>();
    expectTypeOf<TokenResponse>().toHaveProperty("credential_id").toEqualTypeOf<string>();
    expectTypeOf<SocketTokenResponse>().toHaveProperty("socket_path").toEqualTypeOf<string>();
    expectTypeOf<RegistrationResponse>().toHaveProperty("api_key").toMatchTypeOf<{type: "api_key"}>();
    expectTypeOf<PresenceResponse>().toHaveProperty("agents").toEqualTypeOf<Record<string, {status: "online" | "offline" | "busy"; service_agent_id: string; last_seen?: string | null}>>();
    expectTypeOf<AgentHealth>().toHaveProperty("timestamp").toEqualTypeOf<string>();
    expectTypeOf<QueueStatsResponse>().toHaveProperty("by_priority").toEqualTypeOf<Record<string, number>>();
  });

  test("RFC 9457 problem fields have their contract nullability", () => {
    expectTypeOf<Problem>().toHaveProperty("type").toEqualTypeOf<string>();
    expectTypeOf<Problem>().toHaveProperty("detail").toEqualTypeOf<string>();
    expectTypeOf<Problem>().toHaveProperty("request_id").toEqualTypeOf<string | null | undefined>();
  });
});
