"use client";

import { ShieldX } from "lucide-react";
import { cn } from "@/lib/utils";

interface RefusedCardProps {
  message: string;
  className?: string;
}

/** Shown when the user asked to change data: the app is read-only and ran nothing. */
export function RefusedCard({ message, className }: RefusedCardProps) {
  return (
    <div
      role="region"
      aria-label="Request not performed"
      className={cn(
        "my-3 rounded-xl border border-destructive/30 bg-destructive/5 p-3.5 dark:bg-destructive/10",
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        <ShieldX className="size-5 shrink-0 mt-0.5 text-destructive" aria-hidden="true" />
        <div className="space-y-1 text-xs">
          <p className="font-semibold text-destructive">Not performed (read-only)</p>
          <p className="text-foreground/90">{message}</p>
        </div>
      </div>
    </div>
  );
}
