"use client";

import { useCallback, useRef, useState } from "react";
import { chatStream } from "@/lib/api";
import { ConversationDetail, SSEEvent, Turn, TurnStatus } from "@/lib/types";

export interface UseChatReturn {
  turns: Turn[];
  isStreaming: boolean;
  activeConversationId: string | undefined;
  activeStatus: TurnStatus | null;
  sendMessage: (message: string, convId?: string) => Promise<void>;
  stopGeneration: () => void;
  retry: (turnId: string) => Promise<void>;
  loadConversation: (detail: ConversationDetail) => void;
  reset: () => void;
  setActiveConversationId: (id: string | undefined) => void;
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

  const sendMessage = useCallback(
    async (message: string, convId?: string) => {
      if (!message.trim() || isStreaming) {
        return;
      }

      stopGeneration();

      const turnId = `turn-${Date.now()}`;
      const conversationId = convId ?? activeConversationId;

      const newTurn: Turn = {
        id: turnId,
        question: message.trim(),
        sql: null,
        columns: null,
        rows: null,
        row_count: null,
        truncated: null,
        answer: null,
        status: "generating_sql",
        error: null,
        created_at: new Date().toISOString(),
      };

      setTurns((prev) => [...prev, newTurn]);
      setIsStreaming(true);
      setActiveStatus("generating_sql");

      const controller = new AbortController();
      abortControllerRef.current = controller;

      const updateTurn = (updater: (prevTurn: Turn) => Turn) => {
        setTurns((allTurns) =>
          allTurns.map((t) => (t.id === turnId ? updater(t) : t))
        );
      };

      try {
        await chatStream(
          message.trim(),
          conversationId,
          (ev: SSEEvent) => {
            switch (ev.type) {
              case "status":
                setActiveStatus(ev.data);
                updateTurn((t) => ({ ...t, status: ev.data }));
                break;
              case "sql":
                updateTurn((t) => ({ ...t, sql: ev.data }));
                break;
              case "result":
                updateTurn((t) => ({
                  ...t,
                  columns: ev.data.columns,
                  rows: ev.data.rows,
                  row_count: ev.data.row_count,
                  truncated: ev.data.truncated,
                }));
                break;
              case "answer_delta":
                updateTurn((t) => ({
                  ...t,
                  status: "answering",
                  answer: (t.answer || "") + ev.data,
                }));
                setActiveStatus("answering");
                break;
              case "done":
                if (ev.data.conversation_id) {
                  setActiveConversationId(ev.data.conversation_id);
                }
                updateTurn((t) => ({
                  ...t,
                  status: "done",
                  id: ev.data.turn_id || t.id,
                }));
                setActiveStatus("done");
                break;
              case "clarification":
                updateTurn((t) => ({
                  ...t,
                  status: "clarification",
                  error: ev.data.question,
                }));
                setActiveStatus("clarification");
                break;
              case "error":
                updateTurn((t) => ({
                  ...t,
                  status: "error",
                  error: ev.data.message,
                }));
                setActiveStatus("error");
                break;
            }
          },
          controller.signal
        );
      } catch (err: unknown) {
        if (controller.signal.aborted) {
          updateTurn((t) => ({
            ...t,
            status: t.answer ? "done" : "error",
            error: t.answer ? null : "Generation stopped by user",
          }));
        } else {
          const errMsg = err instanceof Error ? err.message : "Failed to execute query";
          updateTurn((t) => ({
            ...t,
            status: "error",
            error: errMsg,
          }));
          setActiveStatus("error");
        }
      } finally {
        setIsStreaming(false);
        abortControllerRef.current = null;
      }
    },
    [activeConversationId, isStreaming, stopGeneration]
  );

  const retry = useCallback(
    async (turnId: string) => {
      const targetTurn = turns.find((t) => t.id === turnId);
      if (targetTurn) {
        // Remove the failed turn and re-send its question
        setTurns((prev) => prev.filter((t) => t.id !== turnId));
        await sendMessage(targetTurn.question, activeConversationId);
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
    stopGeneration,
    retry,
    loadConversation,
    reset,
    setActiveConversationId,
  };
}
