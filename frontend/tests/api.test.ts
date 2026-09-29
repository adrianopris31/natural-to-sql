import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { server } from "./mocks/server";
import {
  chatStream,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchHealth,
  fetchSchema,
  refreshSchema,
} from "@/lib/api";
import { SSEEvent } from "@/lib/types";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("API Client (lib/api.ts)", () => {
  it("fetches health status", async () => {
    const health = await fetchHealth();
    expect(health).toEqual({
      db: "ok",
      ollama: "ok",
      model: "qwen2.5-coder:7b",
      db_version: "9.0.1",
    });
  });

  it("fetches schema and triggers refresh", async () => {
    const schema = await fetchSchema();
    expect(schema.tables.length).toBeGreaterThan(0);
    expect(schema.tables[0].name).toBe("users");

    const refresh = await refreshSchema();
    expect(refresh.tables).toBe(schema.tables.length);
  });

  it("manages conversations (list, detail, delete)", async () => {
    const list = await fetchConversations();
    expect(list).toHaveLength(2);
    expect(list[0].id).toBe("conv-1");

    const detail = await fetchConversation("conv-1");
    expect(detail.id).toBe("conv-1");
    expect(detail.turns).toHaveLength(1);

    await expect(deleteConversation("conv-1")).resolves.toBeUndefined();
  });

  it("streams chat events properly", async () => {
    const events: SSEEvent[] = [];
    await chatStream("Show users", undefined, (ev) => {
      events.push(ev);
    });

    expect(events.length).toBeGreaterThan(0);
    expect(events[0]).toEqual({ type: "status", data: "generating_sql" });
    const sqlEvent = events.find((e) => e.type === "sql");
    expect(sqlEvent).toBeDefined();
    const resultEvent = events.find((e) => e.type === "result");
    expect(resultEvent).toBeDefined();
    const doneEvent = events.find((e) => e.type === "done");
    expect(doneEvent).toBeDefined();
  });

  it("streams clarification event when requested", async () => {
    const events: SSEEvent[] = [];
    await chatStream("Please clarify", undefined, (ev) => {
      events.push(ev);
    });

    const clarEvent = events.find((e) => e.type === "clarification");
    expect(clarEvent).toBeDefined();
    if (clarEvent && clarEvent.type === "clarification") {
      expect(clarEvent.data.question).toContain("Did you mean");
    }
  });

  it("streams error event when requested", async () => {
    const events: SSEEvent[] = [];
    await chatStream("Trigger error", undefined, (ev) => {
      events.push(ev);
    });

    const errEvent = events.find((e) => e.type === "error");
    expect(errEvent).toBeDefined();
    if (errEvent && errEvent.type === "error") {
      expect(errEvent.data.message).toBe("Failed to parse query safely");
    }
  });
});
