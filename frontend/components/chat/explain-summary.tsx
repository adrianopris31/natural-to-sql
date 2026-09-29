"use client";

import { AlertTriangle, Ban, Gauge } from "lucide-react";
import { ExplainSummary as ExplainSummaryData } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ExplainSummaryProps {
  explain: ExplainSummaryData;
  /** Compact = one line (after execution); full = table of accesses (preview). */
  compact?: boolean;
  className?: string;
}

const ACCESS_LABELS: Record<string, string> = {
  ALL: "full scan",
  index: "index scan",
  range: "index range",
  ref: "index lookup",
  eq_ref: "unique lookup",
  const: "constant",
  system: "constant",
};

function formatNumber(n: number | null): string {
  if (n === null) return "n/a";
  return Math.round(n).toLocaleString();
}

export function ExplainSummary({ explain, compact = false, className }: ExplainSummaryProps) {
  const headline = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1 font-medium text-foreground/80">
        <Gauge className="size-3.5" aria-hidden="true" />
        EXPLAIN
      </span>
      <span>
        cost <span className="font-mono text-foreground/80">{formatNumber(explain.cost)}</span>
      </span>
      <span>
        ~<span className="font-mono text-foreground/80">{formatNumber(explain.estimated_rows)}</span>{" "}
        rows
      </span>
      <span>
        {explain.tables.length} table{explain.tables.length === 1 ? "" : "s"}
      </span>
    </div>
  );

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 space-y-2",
        explain.blocked
          ? "border-destructive/40 bg-destructive/5"
          : explain.warnings.length > 0
            ? "border-amber-500/40 bg-amber-500/5"
            : "border-border bg-muted/30",
        className
      )}
      aria-label="Query plan summary"
    >
      {headline}

      {!compact && explain.tables.length > 0 && (
        <ul className="grid gap-1 text-xs">
          {explain.tables.map((t, i) => (
            <li key={`${t.table}-${i}`} className="flex flex-wrap items-baseline gap-x-2 font-mono">
              <span className="text-foreground/90">{t.table}</span>
              <span
                className={cn(
                  "rounded px-1 text-[11px] font-sans",
                  t.access_type === "ALL"
                    ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                    : "bg-muted text-muted-foreground"
                )}
              >
                {ACCESS_LABELS[t.access_type] ?? t.access_type}
              </span>
              {t.key && <span className="text-muted-foreground">key {t.key}</span>}
              <span className="text-muted-foreground">
                ~{t.rows_examined.toLocaleString()} rows/scan
              </span>
            </li>
          ))}
        </ul>
      )}

      {explain.warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-amber-700 dark:text-amber-300">
          {explain.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5">
              <AlertTriangle className="size-3.5 mt-px shrink-0" aria-hidden="true" />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      {explain.blocked && (
        <p className="flex items-start gap-1.5 text-xs font-medium text-destructive">
          <Ban className="size-3.5 mt-px shrink-0" aria-hidden="true" />
          <span>Blocked: {explain.block_reason ?? "exceeds the configured limits"}. Edit it to narrow it down.</span>
        </p>
      )}
    </div>
  );
}
