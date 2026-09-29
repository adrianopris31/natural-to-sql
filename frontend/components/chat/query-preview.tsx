"use client";

import { useState } from "react";
import { AlertOctagon, Pencil, Play, RotateCcw, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TurnQuery } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ExplainSummary } from "./explain-summary";
import { RiskFlags } from "./risk-flags";
import { SqlBlock } from "./sql-block";

interface QueryPreviewProps {
  queries: TurnQuery[];
  /** Error from a previous run attempt (e.g. an edited query was rejected). */
  error?: string | null;
  disabled?: boolean;
  onRun: (editedSql?: (string | null)[]) => void;
  onCancel: () => void;
}

/**
 * Approval gate: nothing runs against the database until the user clicks Run.
 * Edited SQL is re-validated and re-EXPLAINed on the server before execution.
 */
export function QueryPreview({ queries, error, disabled = false, onRun, onCancel }: QueryPreviewProps) {
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [editing, setEditing] = useState<Record<number, boolean>>({});
  const [riskAcknowledged, setRiskAcknowledged] = useState(false);

  const isEdited = (q: TurnQuery) => drafts[q.index] !== undefined && drafts[q.index].trim() !== q.sql;
  // A blocked query can still be run if the user has edited it (the server re-checks).
  const blockedUnedited = queries.some((q) => q.explain?.blocked && !isEdited(q));
  const anyEdited = queries.some(isEdited);
  // High-risk flags (e.g. the model first wrote a DELETE, cross join) need an explicit confirmation.
  const highRisk = queries.filter((q) => q.risk?.level === "high" && !isEdited(q));
  const needsAck = highRisk.length > 0 && !riskAcknowledged;

  const handleRun = () => {
    const edits = anyEdited ? queries.map((q) => (isEdited(q) ? drafts[q.index].trim() : null)) : undefined;
    onRun(edits);
  };

  return (
    <section
      className="rounded-xl border border-primary/30 bg-primary/[0.03] p-3 space-y-3"
      aria-label="Review queries before running"
    >
      <header className="flex items-start gap-2">
        <ShieldCheck className="size-4 mt-0.5 shrink-0 text-primary" aria-hidden="true" />
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold">
            Review {queries.length === 1 ? "the query" : `${queries.length} queries`} before running
          </h3>
          <p className="text-xs text-muted-foreground">
            Nothing has run yet. Read-only, validated, and checked with EXPLAIN.
          </p>
        </div>
      </header>

      {highRisk.length > 0 && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          <AlertOctagon className="size-4 shrink-0 mt-px" aria-hidden="true" />
          <p>
            <span className="font-semibold">Potentially dangerous or unexpected query.</span>{" "}
            {highRisk.length === 1 && queries.length > 1 ? `Query ${highRisk[0].index + 1} has` : "It has"}{" "}
            high-risk flags below. It still can only read data, but check it matches what you asked
            before running.
          </p>
        </div>
      )}

      {queries.map((q) => {
        const isEditing = editing[q.index] ?? false;
        const value = drafts[q.index] ?? q.sql;
        return (
          <div key={q.index} className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium">
                {queries.length > 1 && <span className="text-muted-foreground">Query {q.index + 1}: </span>}
                {q.purpose || (queries.length === 1 ? "Query" : "")}
                {isEdited(q) && <span className="ml-2 text-[11px] text-amber-600 dark:text-amber-400">edited</span>}
              </p>
              <div className="flex gap-1">
                {isEdited(q) && (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() =>
                      setDrafts((d) => {
                        const next = { ...d };
                        delete next[q.index];
                        return next;
                      })
                    }
                    aria-label={`Revert query ${q.index + 1}`}
                  >
                    <RotateCcw /> Revert
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setEditing((e) => ({ ...e, [q.index]: !isEditing }))}
                  aria-pressed={isEditing}
                  aria-label={`${isEditing ? "Stop editing" : "Edit"} query ${q.index + 1}`}
                >
                  <Pencil /> {isEditing ? "Done" : "Edit"}
                </Button>
              </div>
            </div>

            {isEditing ? (
              <textarea
                value={value}
                onChange={(e) => setDrafts((d) => ({ ...d, [q.index]: e.target.value }))}
                spellCheck={false}
                rows={Math.min(12, Math.max(3, value.split("\n").length + 1))}
                aria-label={`SQL for query ${q.index + 1}`}
                className="w-full rounded-lg border border-border bg-zinc-950 p-3 font-mono text-xs text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            ) : (
              <SqlBlock sql={value} isComplete={false} className="my-0" />
            )}

            {q.risk && !isEdited(q) && <RiskFlags risk={q.risk} />}

            {q.explain &&
              (isEdited(q) ? (
                <p className="text-xs text-muted-foreground">
                  Edited query will be validated and checked with EXPLAIN again when you run it.
                </p>
              ) : (
                <ExplainSummary explain={q.explain} />
              ))}
          </div>
        );
      })}

      {error && (
        <p role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}

      {highRisk.length > 0 && (
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={riskAcknowledged}
            onChange={(e) => setRiskAcknowledged(e.target.checked)}
            className="size-3.5 accent-destructive"
          />
          I reviewed the flagged {highRisk.length === 1 ? "query" : "queries"} and want to run anyway
        </label>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button
          onClick={handleRun}
          disabled={disabled || blockedUnedited || needsAck}
          variant={highRisk.length > 0 ? "destructive" : "default"}
        >
          <Play />{" "}
          {highRisk.length > 0 ? "Run anyway" : queries.length > 1 ? "Run queries" : "Run query"}
        </Button>
        <Button variant="outline" onClick={onCancel} disabled={disabled}>
          <X /> Cancel
        </Button>
        {blockedUnedited && (
          <span className={cn("text-xs text-destructive")}>A blocked query must be edited before running.</span>
        )}
      </div>
    </section>
  );
}
