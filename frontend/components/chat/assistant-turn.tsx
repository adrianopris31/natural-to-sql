"use client";

import { Turn, TurnQuery } from "@/lib/types";
import { StatusStepper } from "./status-stepper";
import { SqlBlock } from "./sql-block";
import { ResultTable } from "./result-table";
import { MarkdownAnswer } from "./markdown-answer";
import { ClarificationCard } from "./clarification-card";
import { ErrorAlert } from "./error-alert";
import { ExplainSummary } from "./explain-summary";
import { QueryPreview } from "./query-preview";
import { RefusedCard } from "./refused-card";
import { DocsAnswer } from "./docs-answer";
import { Bot, FileText } from "lucide-react";

interface AssistantTurnProps {
  turn: Turn;
  isStreaming?: boolean;
  onRetry?: () => void;
  onRun?: (editedSql?: (string | null)[]) => void;
  onCancel?: () => void;
}

function ExecutedQuery({ query, total, isComplete }: { query: TurnQuery; total: number; isComplete: boolean }) {
  const hasResults = !!(query.columns && query.columns.length > 0 && query.rows);
  return (
    <div className="space-y-1.5">
      {total > 1 && (
        <p className="text-xs font-medium">
          <span className="text-muted-foreground">Query {query.index + 1}: </span>
          {query.purpose}
        </p>
      )}
      <SqlBlock sql={query.sql} isComplete={isComplete || hasResults} className="my-0" />
      {query.explain && <ExplainSummary explain={query.explain} compact />}
      {query.error ? (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {query.error}
        </p>
      ) : (
        hasResults && (
          <ResultTable
            columns={query.columns!}
            rows={query.rows!}
            rowCount={query.row_count ?? undefined}
            truncated={query.truncated ?? false}
          />
        )
      )}
    </div>
  );
}

export function AssistantTurn({ turn, isStreaming = false, onRetry, onRun, onCancel }: AssistantTurnProps) {
  const isComplete = turn.status === "done";
  const queries = turn.queries ?? null;
  const isAwaitingApproval = turn.status === "awaiting_approval" && !!queries?.length;
  const isCancelled = turn.status === "cancelled";
  const isClarification = turn.status === "clarification";
  const isError = turn.status === "error";

  // Legacy turns (before the preview flow) only have single-query fields
  const legacyHasSql = !queries && !!turn.sql;
  const legacyHasResults = !queries && !!(turn.columns && turn.columns.length > 0 && turn.rows);

  // Handle docs turns
  if (turn.kind === "docs") {
    return (
      <div className="flex gap-3 my-4">
        {/* Docs Avatar */}
        <div className="flex size-8 shrink-0 select-none items-center justify-center rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
          <FileText className="size-4" />
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <StatusStepper status={turn.status} kind="docs" />

          {isError && (
            <ErrorAlert message={turn.error || "An unknown error occurred"} onRetry={onRetry} />
          )}

          {!isError && (
            <DocsAnswer turn={turn} isStreaming={isStreaming && !isComplete} />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 my-4">
      {/* Bot Avatar */}
      <div className="flex size-8 shrink-0 select-none items-center justify-center rounded-full bg-secondary text-secondary-foreground border border-border">
        <Bot className="size-4" />
      </div>

      <div className="flex-1 min-w-0 space-y-2">
        <StatusStepper status={turn.status} kind="sql" />

        {isAwaitingApproval && queries && (
          <QueryPreview
            queries={queries}
            error={turn.error}
            disabled={isStreaming}
            onRun={(edits) => onRun?.(edits)}
            onCancel={() => onCancel?.()}
          />
        )}

        {isCancelled && queries && (
          <div className="space-y-1.5 opacity-70">
            <p className="text-xs text-muted-foreground">Cancelled. Nothing was run.</p>
            {queries.map((q) => (
              <SqlBlock key={q.index} sql={q.sql} isComplete className="my-0" />
            ))}
          </div>
        )}

        {!isAwaitingApproval && !isCancelled && queries && (
          <div className="space-y-4">
            {queries.map((q) => (
              <ExecutedQuery key={q.index} query={q} total={queries.length} isComplete={isComplete} />
            ))}
          </div>
        )}

        {legacyHasSql && <SqlBlock sql={turn.sql!} isComplete={isComplete || legacyHasResults} />}
        {legacyHasResults && (
          <ResultTable
            columns={turn.columns!}
            rows={turn.rows!}
            rowCount={turn.row_count ?? undefined}
            truncated={turn.truncated ?? false}
          />
        )}

        {turn.answer && (
          <MarkdownAnswer content={turn.answer} isStreaming={isStreaming && !isComplete} />
        )}

        {isClarification && turn.error && <ClarificationCard question={turn.error} />}

        {turn.status === "refused" && (
          <RefusedCard message={turn.error || "Not performed: this assistant is read-only."} />
        )}

        {isError && (
          <ErrorAlert message={turn.error || "An unknown error occurred"} onRetry={onRetry} />
        )}
      </div>
    </div>
  );
}
