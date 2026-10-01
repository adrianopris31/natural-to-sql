"use client";

import { useCallback, useRef, useState } from "react";
import { cancelTurn as cancelTurnApi, chatStream, runTurnStream } from "@/lib/api";
import { ConversationDetail, SSEEvent, Turn, TurnKind, TurnQuery, TurnStatus } from "@/lib/types";

export interface UseChatReturn {
  turns: Turn[];
  isStreaming: boolean;
  activeConversationId: string | undefined;
  activeStatus: TurnStatus | null;
  sendMessage: (message: string, convId?: string, mode?: TurnKind) => Promise<void>;
  send: (message: string, mode?: TurnKind, convId?: string) => Promise<void>;
  /** Approve a previewed turn. `editedSql[i]` replaces query i (null/undefined = unchanged). */
  runTurn: (turnId: string, editedSql?: (string | null)[]) => Promise<void>;
  cancelTurn: (turnId: string) => Promise<void>;
  stopGeneration: () => void;
  retry: (turnId: string) => Promise<void>;
  loadConversation: (detail: ConversationDetail) => void;
  reset: () => void;
  setActiveConversationId: (id: string | undefined) => void;
}

// Errors on a run attempt that the user can fix by editing SQL: keep the preview open.
const RECOVERABLE_RUN_ERRORS = new Set(["VALIDATION_FAILED", "EXPLAIN_FAILED", "BLOCKED_BY_EXPLAIN"]);

function applyResult(queries: TurnQuery[] | null | undefined, ev: Extract<SSEEvent, { type: "result" }>) {
  const index = ev.data.index ?? 0;
  return (queries ?? []).map((q) =>
    q.index === index
      ? {
          ...q,
          sql: ev.data.sql ?? q.sql,
          columns: ev.data.columns,
          rows: ev.data.rows,
          row_count: ev.data.row_count,
          truncated: ev.data.truncated,
          error: ev.data.error ?? null,
        }
      : q
  );
}

export function useChat(initialConversationId?: string): UseChatReturn {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>(
    initialConversationId
  );
  const [activeStatus, setActiveStatus] = useState<TurnStatus | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setActiveStatus(null);
  }, []);

  const reset = useCallback(() => {
    stopGeneration();
    setTurns([]);
    setActiveConversationId(undefined);
    setActiveStatus(null);
  }, [stopGeneration]);

  const loadConversation = useCallback(
    (detail: ConversationDetail) => {
      stopGeneration();
      setActiveConversationId(detail.id);
      setTurns(detail.turns || []);
    },
    [stopGeneration]
  );

  /**
   * Streams one SSE request into the turn identified by `initialId`.
   * The turn's id may change mid-stream (preview carries the server turn id).
   */
  const streamIntoTurn = useCallback(
    async (
      initialId: string,
      start: (onEvent: (ev: SSEEvent) => void, signal: AbortSignal) => Promise<void>,
      mode: "plan" | "run"
    ) => {
      const idRef = { current: initialId };
      const updateTurn = (updater: (prevTurn: Turn) => Turn) => {
        // Capture the id now: React may run the updater after a later event changed idRef.
        const targetId = idRef.current;
        setTurns((allTurns) => allTurns.map((t) => (t.id === targetId ? updater(t) : t)));
      };

      const controller = new AbortController();
      abortControllerRef.current = controller;
      setIsStreaming(true);
      let receivedTerminalEvent = false;

      try {
        await start((ev: SSEEvent) => {
          switch (ev.type) {
            case "status":
              if (mode === "run" && (ev.data === "validating" || ev.data === "explaining")) {
                break;
              }
              setActiveStatus(ev.data);
              updateTurn((t) => ({ ...t, status: ev.data }));
              break;
            case "sql":
              updateTurn((t) => ({ ...t, sql: ev.data }));
              break;
            case "preview": {
              receivedTerminalEvent = true;
              const serverId = ev.data.turn_id || idRef.current;
              updateTurn((t) => {
                if (t.kind === "docs") return t;
                return {
                  ...t,
                  id: serverId,
                  status: "awaiting_approval",
                  queries: ev.data.queries,
                  sql: ev.data.queries.map((q) => q.sql).join("\n\n"),
                  error: null,
                };
              });
              idRef.current = serverId;
              if (ev.data.conversation_id) setActiveConversationId(ev.data.conversation_id);
              setActiveStatus((s) => (s === "searching_docs" ? s : "awaiting_approval"));
              break;
            }
            case "result":
              updateTurn((t) => ({ ...t, queries: applyResult(t.queries, ev) }));
              break;
            case "answer_delta":
              updateTurn((t) => ({
                ...t,
                status: "answering",
                answer: (t.answer || "") + ev.data,
              }));
              setActiveStatus("answering");
              break;
            case "docs_answer":
              updateTurn((t) => ({
                ...t,
                answer: ev.data.answer,
                sources: ev.data.sources,
                status: "answering",
              }));
              setActiveStatus("answering");
              break;
            case "done":
              receivedTerminalEvent = true;
              if (ev.data.conversation_id) {
                setActiveConversationId(ev.data.conversation_id);
              }
              // `done` follows a clarification too: keep that status (it must stay visible)
              updateTurn((t) => ({
                ...t,
                status: t.status === "clarification" || t.status === "refused" ? t.status : "done",
                id: ev.data.turn_id || t.id,
              }));
              setActiveStatus((s) => (s === "clarification" || s === "refused" ? s : "done"));
              break;
            case "refused": {
              receivedTerminalEvent = true;
              const serverId = ev.data.turn_id || idRef.current;
              updateTurn((t) => ({ ...t, id: serverId, status: "refused", error: ev.data.message }));
              idRef.current = serverId;
              if (ev.data.conversation_id) setActiveConversationId(ev.data.conversation_id);
              setActiveStatus("refused");
              break;
            }
            case "clarification":
              receivedTerminalEvent = true;
              updateTurn((t) => ({ ...t, status: "clarification", error: ev.data.question }));
              setActiveStatus("clarification");
              break;
            case "error": {
              receivedTerminalEvent = true;
              const recoverable = mode === "run" && RECOVERABLE_RUN_ERRORS.has(ev.data.code ?? "");
              const status: TurnStatus = recoverable ? "awaiting_approval" : "error";
              updateTurn((t) => ({ ...t, status, error: ev.data.message }));
              setActiveStatus(status);
              break;
            }
          }
        }, controller.signal);
        if (!receivedTerminalEvent && !controller.signal.aborted) {
          throw new Error("Connection to the server closed before the answer finished");
        }
      } catch (err: unknown) {
        if (controller.signal.aborted) {
          updateTurn((t) => ({
            ...t,
            status: t.answer ? "done" : "error",
            error: t.answer ? null : "Generation stopped by user",
          }));
        } else {
          const errMsg = err instanceof Error ? err.message : "Failed to execute query";
          updateTurn((t) => ({ ...t, status: "error", error: errMsg }));
          setActiveStatus("error");
        }
      } finally {
        setIsStreaming(false);
        abortControllerRef.current = null;
      }
    },
    []
  );

  const sendMessage = useCallback(
    async (message: string, convId?: string, mode: TurnKind = "sql") => {
      if (!message.trim() || isStreaming) {
        return;
      }

      stopGeneration();

      const turnId = `turn-${Date.now()}`;
      const conversationId = convId ?? activeConversationId;
      const initialStatus: TurnStatus = mode === "docs" ? "searching_docs" : "generating_sql";

      const newTurn: Turn = {
        id: turnId,
        kind: mode,
        question: message.trim(),
        sql: null,
        columns: null,
        rows: null,
        row_count: null,
        truncated: null,
        queries: null,
        answer: null,
        sources: null,
        status: initialStatus,
        error: null,
        created_at: new Date().toISOString(),
      };

      setTurns((prev) => [...prev, newTurn]);
      setActiveStatus(initialStatus);

      await streamIntoTurn(
        turnId,
        (onEvent, signal) => chatStream(message.trim(), conversationId, onEvent, signal, mode),
        "plan"
      );
    },
    [activeConversationId, isStreaming, stopGeneration, streamIntoTurn]
  );

  const send = useCallback(
    async (message: string, mode: TurnKind = "sql", convId?: string) => {
      return sendMessage(message, convId, mode);
    },
    [sendMessage]
  );

  const runTurn = useCallback(
    async (turnId: string, editedSql?: (string | null)[]) => {
      if (isStreaming) return;
      setTurns((prev) =>
        prev.map((t) =>
          t.id === turnId ? { ...t, status: "executing", error: null, answer: null } : t
        )
      );
      setActiveStatus("executing");
      await streamIntoTurn(
        turnId,
        (onEvent, signal) => runTurnStream(turnId, editedSql, onEvent, signal),
        "run"
      );
    },
    [isStreaming, streamIntoTurn]
  );

  const cancelTurn = useCallback(async (turnId: string) => {
    try {
      await cancelTurnApi(turnId);
    } catch {
      // Already not pending on the server; reflect cancellation locally anyway
    }
    setTurns((prev) =>
      prev.map((t) => (t.id === turnId ? { ...t, status: "cancelled", error: null } : t))
    );
    setActiveStatus("cancelled");
  }, []);

  const retry = useCallback(
    async (turnId: string) => {
      const targetTurn = turns.find((t) => t.id === turnId);
      if (targetTurn) {
        // Remove the failed turn and re-send its question
        setTurns((prev) => prev.filter((t) => t.id !== turnId));
        await sendMessage(targetTurn.question, activeConversationId, targetTurn.kind || "sql");
      }
    },
    [turns, activeConversationId, sendMessage]
  );

  return {
    turns,
    isStreaming,
    activeConversationId,
    activeStatus,
    sendMessage,
    send,
    runTurn,
    cancelTurn,
    stopGeneration,
    retry,
    loadConversation,
    reset,
    setActiveConversationId,
  };
}
