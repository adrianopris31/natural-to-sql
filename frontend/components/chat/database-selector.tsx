"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDatabases } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Check, ChevronDown, Database } from "lucide-react";
import { cn } from "@/lib/utils";

interface DatabaseSelectorProps {
  currentDatabase?: string | null;
  onSelectDatabase?: (databaseId: string) => void;
  className?: string;
}

export function DatabaseSelector({
  currentDatabase,
  onSelectDatabase,
  className,
}: DatabaseSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { data: databases, isLoading } = useQuery({
    queryKey: ["databases"],
    queryFn: fetchDatabases,
  });

  // Automatically select the default database when databases load if none is selected
  useEffect(() => {
    if (!currentDatabase && databases && databases.length > 0) {
      const defaultDb = databases.find((d) => d.is_default) ?? databases[0];
      if (defaultDb && onSelectDatabase) {
        onSelectDatabase(defaultDb.id);
      }
    }
  }, [currentDatabase, databases, onSelectDatabase]);

  // Close dropdown on outside click or Escape key
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const activeDb =
    databases?.find((d) => d.id === currentDatabase) ??
    databases?.find((d) => d.is_default) ??
    databases?.[0];

  const displayLabel =
    activeDb?.name || currentDatabase || (isLoading ? "Loading..." : "Select Database");

  return (
    <div className={cn("relative inline-block text-left", className)} ref={dropdownRef}>
      <Button
        variant="outline"
        size="sm"
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className="h-8 gap-1.5 px-2.5 text-xs font-normal border-border bg-background hover:bg-muted"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label="Select database"
      >
        <Database className="size-3.5 text-muted-foreground shrink-0" />
        <span className="truncate max-w-[120px] font-medium">{displayLabel}</span>
        {activeDb?.is_default && (
          <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-medium text-muted-foreground hidden sm:inline">
            Default
          </span>
        )}
        <ChevronDown className="size-3 text-muted-foreground ml-0.5 shrink-0 opacity-70" />
      </Button>

      {isOpen && (
        <div
          role="listbox"
          aria-label="Database list"
          className="absolute right-0 z-50 mt-1 min-w-[200px] overflow-hidden rounded-md border border-border bg-popover p-1 shadow-md animate-in fade-in-0 zoom-in-95"
        >
          <div className="px-2 py-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
            Databases
          </div>
          {databases && databases.length > 0 ? (
            databases.map((db) => {
              const isSelected = (currentDatabase ?? activeDb?.id) === db.id;
              return (
                <button
                  key={db.id}
                  role="option"
                  aria-selected={isSelected}
                  type="button"
                  onClick={() => {
                    onSelectDatabase?.(db.id);
                    setIsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-xs text-left transition-colors",
                    isSelected
                      ? "bg-accent text-accent-foreground font-medium"
                      : "text-foreground hover:bg-muted"
                  )}
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <Database className="size-3.5 shrink-0 opacity-70" />
                    <span className="truncate">{db.name}</span>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {db.is_default && (
                      <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-medium text-muted-foreground">
                        Default
                      </span>
                    )}
                    {isSelected && <Check className="size-3.5 text-primary" />}
                  </div>
                </button>
              );
            })
          ) : (
            <div className="px-2 py-2 text-xs text-muted-foreground text-center">
              {isLoading ? "Loading databases..." : "No databases available"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
