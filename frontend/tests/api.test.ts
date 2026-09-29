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
  runTurnStream,
  cancelTurn,
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

  it("streams plan events ending in a preview (nothing executed)", async () => {
    const events: SSEEvent[] = [];
    await chatStream("Show users", undefined, (ev) => {
      events.push(ev);
    });

    expect(events[0]).toEqual({ type: "status", data: "generating_sql" });
    expect(events.map((e) => e.type)).not.toContain("result");
    const last = events[events.length - 1];
    expect(last.type).toBe("preview");
    if (last.type === "preview") {
      expect(last.data.turn_id).toBe("turn-mock-456");
      expect(last.data.queries[0].explain?.blocked).toBe(false);
    }
  });

  it("runs an approved turn and streams results", async () => {
    const events: SSEEvent[] = [];
    await runTurnStream("turn-mock-456", undefined, (ev) => {
      events.push(ev);
    });
    const result = events.find((e) => e.type === "result");
    expect(result).toBeDefined();
    if (result && result.type === "result") {
      expect(result.data.index).toBe(0);
      expect(result.data.row_count).toBe(2);
    }
    expect(events.some((e) => e.type === "done")).toBe(true);
  });

  it("cancels a previewed turn", async () => {
    await expect(cancelTurn("turn-mock-456")).resolves.toBeUndefined();
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
