"use client";

import { DocsSource, Turn } from "@/lib/types";
import { MarkdownAnswer } from "./markdown-answer";
import { FileQuestion, FileText, Hash, Ticket, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

interface DocsAnswerProps {
  turn: Turn;
  isStreaming?: boolean;
}

function SourceIcon({ type }: { type: string }) {
  const normalized = type.toLowerCase();
  if (normalized === "jira") {
    return <Ticket className="size-3.5 text-blue-500 shrink-0" aria-hidden="true" />;
  }
  if (normalized === "slack") {
    return <Hash className="size-3.5 text-emerald-500 shrink-0" aria-hidden="true" />;
  }
  return <FileText className="size-3.5 text-amber-500 shrink-0" aria-hidden="true" />;
}

export function DocsAnswer({ turn, isStreaming = false }: DocsAnswerProps) {
  const isRefused =
    turn.answer?.toLowerCase().includes("not contain information") ||
    turn.answer?.toLowerCase().includes("don't contain the answer") ||
    turn.answer?.toLowerCase().includes("documents don't answer") ||
    (turn.sources?.length === 0 && Boolean(turn.answer && turn.status === "done" && !turn.sql));

  // If the documents didn't contain the answer, show distinct card
  if (isRefused && turn.answer && !isStreaming) {
    return (
      <div className="space-y-3">
        <div
          role="region"
          aria-label="Not found in the documents"
          className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3.5 dark:bg-amber-500/15"
        >
          <div className="flex items-start gap-2.5">
            <FileQuestion
              className="size-5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400"
              aria-hidden="true"
            />
            <div className="space-y-1 text-xs">
              <p className="font-semibold text-amber-800 dark:text-amber-300">
                Not found in the documents
              </p>
              <div className="text-foreground/90">
                <MarkdownAnswer content={turn.answer} isStreaming={false} />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {turn.answer && (
        <MarkdownAnswer content={turn.answer} isStreaming={isStreaming} />
      )}

      {/* Sources list */}
      {turn.sources && turn.sources.length > 0 && (
        <div className="pt-2 border-t border-border/50">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            Sources cited ({turn.sources.length})
          </p>
          <div className="flex flex-wrap gap-2" role="list" aria-label="Cited sources">
            {turn.sources.map((source: DocsSource) => (
              <a
                key={source.id}
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                role="listitem"
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-muted/50 px-2.5 py-1 text-xs font-medium text-foreground/90 transition-colors",
                  "hover:bg-muted hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                )}
                title={`${source.id}: ${source.title}`}
              >
                <SourceIcon type={source.source_type} />
                <span className="font-semibold text-foreground/80">{source.id}</span>
                <span className="max-w-[200px] truncate text-muted-foreground">
                  {source.title}
                </span>
                <ExternalLink className="size-2.5 opacity-50 shrink-0" aria-hidden="true" />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
