"use client";

import { Turn } from "@/lib/types";
import { StatusStepper } from "./status-stepper";
import { SqlBlock } from "./sql-block";
import { ResultTable } from "./result-table";
import { MarkdownAnswer } from "./markdown-answer";
import { ClarificationCard } from "./clarification-card";
import { ErrorAlert } from "./error-alert";
import { Bot } from "lucide-react";

interface AssistantTurnProps {
  turn: Turn;
  isStreaming?: boolean;
  onRetry?: () => void;
}

export function AssistantTurn({ turn, isStreaming = false, onRetry }: AssistantTurnProps) {
  const isComplete = turn.status === "done";
  const hasSql = !!turn.sql;
  const hasResults = !!(turn.columns && turn.columns.length > 0 && turn.rows);
  const isClarification = turn.status === "clarification";
  const isError = turn.status === "error";

  return (
    <div className="flex gap-3 my-4">
      {/* Bot Avatar */}
      <div className="flex size-8 shrink-0 select-none items-center justify-center rounded-full bg-secondary text-secondary-foreground border border-border">
        <Bot className="size-4" />
      </div>

      {/* Main turn content in required order */}
      <div className="flex-1 min-w-0 space-y-2">
        {/* 1. Status Stepper */}
        <StatusStepper status={turn.status} />

        {/* 2. SQL Block (collapsed once complete) */}
        {hasSql && (
          <SqlBlock sql={turn.sql!} isComplete={isComplete || hasResults} />
        )}

        {/* 3. ResultTable */}
        {hasResults && (
          <ResultTable
            columns={turn.columns!}
            rows={turn.rows!}
            rowCount={turn.row_count ?? undefined}
            truncated={turn.truncated ?? false}
          />
        )}

        {/* 4. Streamed Markdown Answer */}
        {turn.answer && (
          <MarkdownAnswer content={turn.answer} isStreaming={isStreaming && !isComplete} />
        )}

        {/* Clarification state */}
        {isClarification && turn.error && (
          <ClarificationCard question={turn.error} />
        )}

        {/* Error state with retry */}
        {isError && (
          <ErrorAlert
            message={turn.error || "An unknown error occurred"}
            onRetry={onRetry}
          />
        )}
      </div>
    </div>
  );
}
