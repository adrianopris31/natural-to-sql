"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ErrorAlertProps {
  message: string;
  code?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorAlert({ message, code, onRetry, className }: ErrorAlertProps) {
  return (
    <div
      role="alert"
      className={cn(
        "my-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-3.5 text-destructive dark:bg-destructive/15",
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        <AlertCircle className="size-5 shrink-0 mt-0.5 text-destructive" />
        <div className="space-y-0.5 text-xs">
          <p className="font-semibold text-destructive">Query error</p>
          <p className="text-destructive/90">{message}</p>
          {code && (
            <span className="inline-block font-mono text-[10px] text-destructive/70 bg-destructive/10 px-1.5 py-0.2 rounded mt-1">
              Code: {code}
            </span>
          )}
        </div>
      </div>

      {onRetry && (
        <Button
          variant="outline"
          size="sm"
          onClick={onRetry}
          className="self-end sm:self-center gap-1.5 border-destructive/40 text-destructive hover:bg-destructive/15 hover:text-destructive h-7 px-3 text-xs shrink-0"
          aria-label="Retry query"
        >
          <RefreshCw className="size-3.5" />
          <span>Retry</span>
        </Button>
      )}
    </div>
  );
}
