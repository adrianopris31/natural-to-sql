"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/lib/api";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function HealthBanner() {
  const { data: health, error, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });

  const dbDown = health?.db === "error";
  const ollamaDown = health?.ollama === "error";
  const networkError = !!error;

  const isDegraded = dbDown || ollamaDown || networkError;

  if (!isDegraded) {
    return null;
  }

  const issues: string[] = [];
  if (dbDown) issues.push("Target Database unreachable");
  if (ollamaDown) issues.push("Ollama LLM service unreachable");
  if (networkError && !dbDown && !ollamaDown) issues.push("Backend API connection failed");

  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 border-b border-amber-500/40 bg-amber-500/15 px-4 py-2 text-xs text-amber-900 dark:text-amber-200"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0 text-amber-600 dark:text-amber-400" />
        <span className="font-semibold">Service Warning:</span>
        <span>{issues.join("; ")}. Please verify local services.</span>
      </div>

      <Button
        variant="ghost"
        size="xs"
        onClick={() => refetch()}
        disabled={isFetching}
        className="h-6 gap-1 px-2 text-xs text-amber-900 dark:text-amber-200 hover:bg-amber-500/20"
        aria-label="Retry connection check"
      >
        <RefreshCw className={`size-3 ${isFetching ? "animate-spin" : ""}`} />
        <span>Check Again</span>
      </Button>
    </div>
  );
}
