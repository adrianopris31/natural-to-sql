"use client";

import { TurnStatus } from "@/lib/types";
import { Check, Loader2, AlertCircle, Wrench } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusStepperProps {
  status: TurnStatus;
  className?: string;
}

interface StepDef {
  key: TurnStatus;
  label: string;
}

const STEPS: StepDef[] = [
  { key: "generating_sql", label: "Generating SQL" },
  { key: "validating", label: "Validating" },
  { key: "executing", label: "Executing" },
  { key: "answering", label: "Answering" },
];

export function StatusStepper({ status, className }: StatusStepperProps) {
  // If status is done, show compact completed indicator
  if (status === "done") {
    return (
      <div
        className={cn("flex items-center gap-1.5 text-xs text-muted-foreground py-1", className)}
        role="status"
        aria-label="Query completed"
      >
        <div className="flex size-4 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
          <Check className="size-2.5 stroke-[3]" />
        </div>
        <span className="font-medium text-emerald-600 dark:text-emerald-400">
          Completed
        </span>
      </div>
    );
  }

  // If status is clarification, show clarification step
  if (status === "clarification") {
    return (
      <div
        className={cn("flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400 py-1", className)}
        role="status"
      >
        <AlertCircle className="size-4" />
        <span className="font-medium">Clarification needed</span>
      </div>
    );
  }

  // If status is error, show error step
  if (status === "error") {
    return (
      <div
        className={cn("flex items-center gap-1.5 text-xs text-destructive py-1", className)}
        role="status"
      >
        <AlertCircle className="size-4" />
        <span className="font-medium">Execution failed</span>
      </div>
    );
  }

  const stepOrder: TurnStatus[] = ["generating_sql", "validating", "executing", "answering"];
  const currentIdx = stepOrder.indexOf(status === "repairing" ? "validating" : status);

  return (
    <div
      className={cn("flex flex-wrap items-center gap-2 py-2 text-xs", className)}
      role="status"
      aria-label="Generation progress"
    >
      {STEPS.map((step, idx) => {
        const isCurrent = status === step.key;
        const isPast = currentIdx > idx;
        const isRepairing = status === "repairing" && step.key === "validating";

        return (
          <div key={step.key} className="flex items-center gap-1.5">
            {idx > 0 && <div className="h-px w-3 bg-border" aria-hidden="true" />}

            <div
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium transition-colors",
                isCurrent && !isRepairing
                  ? "bg-primary/10 text-primary border border-primary/20 shadow-xs"
                  : isRepairing
                  ? "bg-amber-500/10 text-amber-600 border border-amber-500/20"
                  : isPast
                  ? "bg-muted text-muted-foreground"
                  : "text-muted-foreground/60"
              )}
            >
              {isPast ? (
                <Check className="size-3 text-emerald-600 dark:text-emerald-400 stroke-[3]" />
              ) : isRepairing ? (
                <Wrench className="size-3 animate-spin text-amber-600" />
              ) : isCurrent ? (
                <Loader2 className="size-3 animate-spin text-primary" />
              ) : (
                <span className="size-1.5 rounded-full bg-muted-foreground/40" />
              )}
              <span>{isRepairing ? "Repairing SQL" : step.label}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
