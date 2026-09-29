"use client";

import { AlertOctagon, AlertTriangle, Info } from "lucide-react";
import { RiskReport } from "@/lib/types";
import { cn } from "@/lib/utils";

interface RiskFlagsProps {
  risk: RiskReport;
  className?: string;
}

const STYLES = {
  high: { icon: AlertOctagon, text: "text-destructive", box: "border-destructive/40 bg-destructive/5" },
  medium: {
    icon: AlertTriangle,
    text: "text-amber-700 dark:text-amber-300",
    box: "border-amber-500/40 bg-amber-500/5",
  },
  info: { icon: Info, text: "text-muted-foreground", box: "border-border bg-muted/30" },
} as const;

/** Red/amber flags for a previewed query. Renders nothing for a clean query. */
export function RiskFlags({ risk, className }: RiskFlagsProps) {
  if (!risk.flags.length) return null;
  const level = risk.level === "none" ? "info" : risk.level;
  return (
    <ul
      className={cn("space-y-1 rounded-lg border px-3 py-2 text-xs", STYLES[level].box, className)}
      aria-label={`Risk flags (${risk.level})`}
    >
      {risk.flags.map((flag, i) => {
        const style = STYLES[flag.severity];
        const Icon = style.icon;
        return (
          <li key={`${flag.code}-${i}`} className={cn("flex items-start gap-1.5", style.text)}>
            <Icon className="size-3.5 mt-px shrink-0" aria-hidden="true" />
            <span>
              <span className="sr-only">{flag.severity} risk: </span>
              {flag.message}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
