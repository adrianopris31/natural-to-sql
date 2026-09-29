import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useChat } from "@/hooks/use-chat";
import { server } from "./mocks/server";
import { mockConversationDetail } from "./mocks/handlers";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("useChat Hook", () => {
  it("sends message and processes full SSE streaming turn", async () => {
    const { result } = renderHook(() => useChat());

    expect(result.current.turns).toHaveLength(0);
    expect(result.current.isStreaming).toBe(false);

    await act(async () => {
      await result.current.sendMessage("Show me users");
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    expect(result.current.turns).toHaveLength(1);
    const turn = result.current.turns[0];
    expect(turn.question).toBe("Show me users");
    expect(turn.sql).toBe("SELECT id, name FROM users LIMIT 10");
    expect(turn.columns).toEqual(["id", "name"]);
    expect(turn.rows).toEqual([
      [1, "Alice"],
      [2, "Bob"],
    ]);
    expect(turn.status).toBe("done");
    expect(turn.answer).toBe("Found 2 users in the database.");
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
});
