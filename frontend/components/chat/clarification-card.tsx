"use client";

import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface ClarificationCardProps {
  question: string;
  className?: string;
}

export function ClarificationCard({ question, className }: ClarificationCardProps) {
  return (
    <div
      role="region"
      aria-label="Clarification request"
      className={cn(
        "my-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3.5 text-foreground dark:bg-amber-500/15",
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        <HelpCircle className="size-5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
        <div className="space-y-1 text-xs">
          <p className="font-semibold text-amber-700 dark:text-amber-300">
            Clarification requested
          </p>
          <p className="text-foreground/90 font-medium">{question}</p>
          <p className="text-[11px] text-muted-foreground pt-1">
            Please reply below with additional details to help refine the query.
          </p>
        </div>
      </div>
    </div>
  );
}
