import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { server } from "./mocks/server";
import { lastChatRequest } from "./mocks/handlers";
import {
  chatStream,
  sendChatStream,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchDatabases,
  fetchHealth,
  fetchSchema,
  refreshSchema,
  runTurnStream,
  cancelTurn,
  fetchSources,
  saveJiraSource,
  saveSlackSource,
  testSource,
  deleteSource,
  refreshDocuments,
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
      knowledge_bot: {
        configured: true,
        reachable: true,
      },
      settings_ui_enabled: true,
    });
  });

  it("fetches databases list", async () => {
    const databases = await fetchDatabases();
    expect(databases).toHaveLength(2);
    expect(databases[0]).toEqual({
      id: "default_db",
      name: "default_db",
      is_default: true,
    });
    expect(databases[1]).toEqual({
      id: "analytics_db",
      name: "analytics_db",
      is_default: false,
    });
  });

  it("fetches schema and triggers refresh with optional database", async () => {
    const defaultSchema = await fetchSchema();
    expect(defaultSchema.tables.length).toBeGreaterThan(0);
    expect(defaultSchema.tables[0].name).toBe("users");

    const refreshDefault = await refreshSchema();
    expect(refreshDefault.tables).toBe(defaultSchema.tables.length);

    // Explicit database query
    const analyticsSchema = await fetchSchema("analytics_db");
    expect(analyticsSchema.tables).toHaveLength(1);
    expect(analyticsSchema.tables[0].name).toBe("events");

    const refreshAnalytics = await refreshSchema("analytics_db");
    expect(refreshAnalytics.tables).toBe(1);
  });

  it("sends database parameter in chatStream and sendChatStream", async () => {
    await chatStream("Show users", undefined, undefined, undefined, "sql", "analytics_db");
    expect(lastChatRequest.body?.database).toBe("analytics_db");

    await sendChatStream("Show events", undefined, "sql", "default_db");
    expect(lastChatRequest.body?.database).toBe("default_db");
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

  it("streams docs answer directly for docs mode", async () => {
    const events: SSEEvent[] = [];
    await chatStream(
      "How to deploy?",
      undefined,
      (ev) => {
        events.push(ev);
      },
      undefined,
      "docs"
    );

    expect(events[0]).toEqual({ type: "status", data: "searching_docs" });
    const docsAnswer = events.find((e) => e.type === "docs_answer");
    expect(docsAnswer).toBeDefined();
    if (docsAnswer && docsAnswer.type === "docs_answer") {
      expect(docsAnswer.data.answer).toContain("According to deployment documentation");
      expect(docsAnswer.data.sources).toHaveLength(3);
    }
    expect(events.some((e) => e.type === "done")).toBe(true);
  });

  it("handles settings API operations (fetch, save, test, delete, refresh)", async () => {
    // Fetch sources
    const sourcesRes = await fetchSources();
    expect(sourcesRes.sources).toHaveLength(2);
    expect(sourcesRes.sources[0].source).toBe("jira");

    // Save Jira
    const updatedJira = await saveJiraSource({
      base_url: "https://custom.atlassian.net",
      auth_mode: "token",
      email: "test@custom.com",
    });
    expect(updatedJira.fields.base_url).toBe("https://custom.atlassian.net");

    // Save Slack
    const updatedSlack = await saveSlackSource({
      channels: ["dev", "random"],
      days_back: 7,
    });
    expect(updatedSlack.fields.channels).toEqual(["dev", "random"]);

    // Test connection
    const testResult = await testSource("jira");
    expect(testResult.ok).toBe(true);

    // Delete source
    await expect(deleteSource("jira")).resolves.toBeUndefined();

    // Refresh documents
    const refreshRes = await refreshDocuments();
    expect(refreshRes.documents).toBe(42);
  });
});
