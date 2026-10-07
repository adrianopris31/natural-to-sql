import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useChat } from "@/hooks/use-chat";
import { server } from "./mocks/server";
import { lastChatRequest, lastRunRequest, mockConversationDetail } from "./mocks/handlers";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  lastRunRequest.body = null;
  lastChatRequest.body = null;
});
afterAll(() => server.close());

describe("useChat Hook", () => {
  it("stops at a preview and only runs after approval", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Show me users");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(result.current.turns).toHaveLength(1);
    let turn = result.current.turns[0];
    expect(turn.question).toBe("Show me users");
    expect(turn.status).toBe("awaiting_approval");
    expect(turn.id).toBe("turn-mock-456");
    expect(turn.queries).toHaveLength(1);
    expect(turn.queries![0].sql).toBe("SELECT id, name FROM users LIMIT 10");
    expect(turn.queries![0].explain?.tables[0].table).toBe("users");
    expect(turn.queries![0].rows).toBeNull();
    expect(turn.answer).toBeNull();

    await act(async () => {
      await result.current.runTurn("turn-mock-456");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    turn = result.current.turns[0];
    expect(lastRunRequest.body).toEqual({});
    expect(turn.status).toBe("done");
    expect(turn.queries![0].columns).toEqual(["id", "name"]);
    expect(turn.queries![0].rows).toEqual([
      [1, "Alice"],
      [2, "Bob"],
    ]);
    expect(turn.answer).toBe("Found 2 users in the database.");
  });

  it("previews multiple queries", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("Tell me two things");
    });
    const turn = result.current.turns[0];
    expect(turn.queries!.map((q) => q.purpose)).toEqual(["Users", "Order count"]);
  });

  it("sends edited SQL when running", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("Show me users");
    });
    await act(async () => {
      await result.current.runTurn("turn-mock-456", ["SELECT id, name FROM users LIMIT 2"]);
    });
    expect(lastRunRequest.body).toEqual({ queries: ["SELECT id, name FROM users LIMIT 2"] });
    expect(result.current.turns[0].queries![0].sql).toBe("SELECT id, name FROM users LIMIT 2");
    expect(result.current.turns[0].status).toBe("done");
  });

  it("keeps the preview open when an edited query is rejected", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("Show me users");
    });
    await act(async () => {
      await result.current.runTurn("turn-mock-456", ["DROP TABLE users"]);
    });
    const turn = result.current.turns[0];
    expect(turn.status).toBe("awaiting_approval");
    expect(turn.error).toContain("rejected for safety");
    expect(turn.queries![0].rows).toBeNull();
  });

  it("marks blocked queries in the preview", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("something blocked");
    });
    expect(result.current.turns[0].queries![0].explain?.blocked).toBe(true);
  });

  it("cancels a previewed turn", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("Show me users");
    });
    await act(async () => {
      await result.current.cancelTurn("turn-mock-456");
    });
    expect(result.current.turns[0].status).toBe("cancelled");
  });

  it("handles clarification event", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Please clarify something");
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    const turn = result.current.turns[0];
    expect(turn.status).toBe("clarification");
    expect(turn.error).toContain("Did you mean");
  });

  it("handles error event", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("Trigger error please");
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    const turn = result.current.turns[0];
    expect(turn.status).toBe("error");
    expect(turn.error).toBe("Failed to parse query safely");
  });

  it("marks the turn as error when the stream closes without a terminal event", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("simulate cutoff");
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    const turn = result.current.turns[0];
    expect(turn.status).toBe("error");
    expect(turn.error).toContain("closed before the answer finished");
  });

  it("keeps the clarification visible when done follows it", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("Please clarify something");
    });
    expect(result.current.turns[0].status).toBe("clarification");
    expect(result.current.turns[0].error).toContain("Did you mean");
  });

  it("shows a read-only refusal for delete requests", async () => {
    const { result } = renderHook(() => useChat());
    await act(async () => {
      await result.current.sendMessage("delete user");
    });
    const turn = result.current.turns[0];
    expect(turn.status).toBe("refused");
    expect(turn.id).toBe("turn-refused-1");
    expect(turn.error).toContain("read-only");
    expect(turn.queries).toBeNull();
  });

  it("loads conversation history and resets properly", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.loadConversation(mockConversationDetail);
    });

    expect(result.current.activeConversationId).toBe("conv-1");
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0].question).toBe("Top 10 users by total spend");

    act(() => {
      result.current.reset();
    });

    expect(result.current.activeConversationId).toBeUndefined();
    expect(result.current.turns).toHaveLength(0);
  });

  it("streams docs questions directly to done without entering awaiting_approval gate", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.send("How do we deploy to production?", "docs");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(result.current.turns).toHaveLength(1);
    const turn = result.current.turns[0];
    expect(turn.kind).toBe("docs");
    expect(turn.status).toBe("done");
    expect(turn.queries).toBeNull();
    expect(turn.sql).toBeNull();
    expect(turn.answer).toContain("According to deployment documentation");
    expect(turn.sources).toHaveLength(3);
    expect(turn.sources![0].source_type).toBe("jira");
    expect(turn.sources![1].source_type).toBe("doc");
    expect(turn.sources![2].source_type).toBe("slack");
  });

  it("handles docs questions with refusal (not found in documents)", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.send("Topic not found in any docs", "docs");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(result.current.turns).toHaveLength(1);
    const turn = result.current.turns[0];
    expect(turn.kind).toBe("docs");
    expect(turn.status).toBe("done");
    expect(turn.sources).toHaveLength(0);
    expect(turn.answer).toContain("do not contain information");
  });

  it("tracks currentDatabase and sends it in chat requests", async () => {
    const { result } = renderHook(() => useChat());

    expect(result.current.currentDatabase).toBeNull();

    act(() => {
      result.current.setCurrentDatabase("analytics_db");
    });
    expect(result.current.currentDatabase).toBe("analytics_db");

    await act(async () => {
      await result.current.sendMessage("Count orders");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(lastChatRequest.body?.database).toBe("analytics_db");
    expect(result.current.turns[0].database).toBe("analytics_db");
  });

  it("updates currentDatabase when loading a conversation with database set", async () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.loadConversation({
        ...mockConversationDetail,
        database: "analytics_db",
      });
    });

    expect(result.current.currentDatabase).toBe("analytics_db");
    expect(result.current.activeConversationId).toBe("conv-1");
  });

  it("switches to new conversation when database changes while in a historical conversation", async () => {
    const { result } = renderHook(() => useChat());

    // Load a conversation for default_db
    act(() => {
      result.current.loadConversation({
        ...mockConversationDetail,
        database: "default_db",
      });
    });
    expect(result.current.activeConversationId).toBe("conv-1");
    expect(result.current.currentDatabase).toBe("default_db");

    // User switches to analytics_db
    act(() => {
      result.current.setCurrentDatabase("analytics_db");
    });

    // Sending a message without explicit convId detaches from conv-1 and uses analytics_db
    await act(async () => {
      await result.current.sendMessage("New query for analytics");
    });
    await waitFor(() => expect(result.current.isStreaming).toBe(false));

    expect(lastChatRequest.body?.conversation_id).toBeUndefined();
    expect(lastChatRequest.body?.database).toBe("analytics_db");
  });
});
