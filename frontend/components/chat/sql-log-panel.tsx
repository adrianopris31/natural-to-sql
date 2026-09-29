"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchAuditLog } from "@/lib/api";
import { AuditEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SqlLogPanelProps {
  open: boolean;
  onClose: () => void;
}

const STAGE_STYLES: Record<string, { label: string; className: string }> = {
  executed: { label: "Executed", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  validated: { label: "Validated", className: "bg-sky-500/15 text-sky-700 dark:text-sky-300" },
  edited: { label: "Edited by you", className: "bg-violet-500/15 text-violet-700 dark:text-violet-300" },
  rejected: { label: "Rejected", className: "bg-destructive/15 text-destructive" },
  blocked: { label: "Blocked (EXPLAIN)", className: "bg-destructive/15 text-destructive" },
  refused: { label: "Refused (read-only)", className: "bg-destructive/15 text-destructive" },
  explain_failed: { label: "EXPLAIN failed", className: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  execution_failed: {
    label: "Execution failed",
    className: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  },
};

function StageBadge({ stage }: { stage: string }) {
  const style = STAGE_STYLES[stage] ?? { label: stage, className: "bg-muted text-muted-foreground" };
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", style.className)}>
      {style.label}
    </span>
  );
}

function LogEntry({ entry }: { entry: AuditEntry }) {
  const sql = entry.safe_sql ?? entry.raw_sql;
  const showRaw = entry.raw_sql && entry.safe_sql && entry.raw_sql.trim() !== entry.safe_sql.trim();
  return (
    <li className="space-y-1.5 border-b border-border px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <StageBadge stage={entry.stage} />
        <time dateTime={entry.created_at}>{new Date(entry.created_at).toLocaleString()}</time>
        {entry.row_count !== null && <span>{entry.row_count.toLocaleString()} rows</span>}
        {entry.elapsed_ms !== null && <span>{Math.round(entry.elapsed_ms)} ms</span>}
      </div>
      {entry.question && <p className="text-xs font-medium">“{entry.question}”</p>}
      {sql && (
        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-zinc-950 p-2 font-mono text-[11px] text-zinc-100">
          {sql}
        </pre>
      )}
      {showRaw && (
        <details className="text-[11px] text-muted-foreground">
          <summary className="cursor-pointer">As generated (before re-rendering)</summary>
          <pre className="mt-1 whitespace-pre-wrap break-words font-mono">{entry.raw_sql}</pre>
        </details>
      )}
      {entry.reason && <p className="text-[11px] text-muted-foreground">{entry.reason}</p>}
    </li>
  );
}

/** Slide-over listing every SQL statement the app generated, edited, blocked or executed. */
export function SqlLogPanel({ open, onClose }: SqlLogPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["audit-log"],
    queryFn: () => fetchAuditLog(200),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="SQL log"
        className="relative flex h-full w-full max-w-xl flex-col border-l border-border bg-background shadow-xl"
      >
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">SQL log</h2>
            <p className="text-[11px] text-muted-foreground">
              Every query generated, edited, blocked or executed (newest first).
            </p>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon-sm" onClick={() => refetch()} aria-label="Refresh SQL log">
              <RefreshCw className={cn("size-4", isFetching && "animate-spin")} />
            </Button>
            <Button ref={closeRef} variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close SQL log">
              <X className="size-4" />
            </Button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto">
          {isLoading && <p className="p-4 text-xs text-muted-foreground">Loading…</p>}
          {isError && <p className="p-4 text-xs text-destructive">Could not load the SQL log.</p>}
          {data && data.length === 0 && (
            <p className="p-4 text-xs text-muted-foreground">No SQL has been generated yet.</p>
          )}
          {data && data.length > 0 && (
            <ul>
              {data.map((entry) => (
                <LogEntry key={entry.id} entry={entry} />
              ))}
            </ul>
          )}
        </div>
      </aside>
    </div>
  );
}
