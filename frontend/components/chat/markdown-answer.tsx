"use client";

import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";

interface MarkdownAnswerProps {
  content: string;
  isStreaming?: boolean;
  className?: string;
}

export function MarkdownAnswer({
  content,
  isStreaming = false,
  className,
}: MarkdownAnswerProps) {
  if (!content && !isStreaming) {
    return null;
  }

  return (
    <div
      className={cn(
        "my-2 text-sm leading-relaxed text-foreground/90 space-y-2",
        className
      )}
      aria-live="polite"
      aria-busy={isStreaming}
    >
      <ReactMarkdown
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0 leading-normal">{children}</p>,
          ul: ({ children }) => <ul className="my-2 ml-4 list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 ml-4 list-decimal space-y-1">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          code: ({ children }) => (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground font-medium">
              {children}
            </code>
          ),
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-primary/40 pl-3 italic text-muted-foreground my-2">
              {children}
            </blockquote>
          ),
        }}
      >
        {content}
      </ReactMarkdown>

      {isStreaming && (
        <span
          className="inline-block size-2 animate-pulse rounded-full bg-primary ml-1"
          aria-hidden="true"
        />
      )}
    </div>
  );
}
