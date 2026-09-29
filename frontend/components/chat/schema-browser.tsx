"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSchema, refreshSchema } from "@/lib/api";
import { CompactTable } from "@/lib/types";
import { ChevronDown, ChevronRight, Database, Key, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SchemaBrowser() {
  const queryClient = useQueryClient();
  const [isSectionOpen, setIsSectionOpen] = useState(true);
  const [expandedTables, setExpandedTables] = useState<Record<string, boolean>>({});

  const { data: schema, isLoading, error } = useQuery({
    queryKey: ["schema"],
    queryFn: fetchSchema,
  });

  const refreshMutation = useMutation({
    mutationFn: refreshSchema,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schema"] });
    },
  });

  const toggleTable = (tableName: string) => {
    setExpandedTables((prev) => ({
      ...prev,
      [tableName]: !prev[tableName],
    }));
  };

  return (
    <div className="flex flex-col border-t border-border pt-3">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1">
        <button
          type="button"
          onClick={() => setIsSectionOpen((prev) => !prev)}
          className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
          aria-expanded={isSectionOpen}
          aria-controls="schema-browser-content"
        >
          {isSectionOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          <Database className="size-3.5" />
          <span>Database Schema</span>
        </button>

        <Button
          variant="ghost"
          size="icon-xs"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          title="Refresh schema"
          aria-label="Refresh database schema"
        >
          <RefreshCw
            className={`size-3 text-muted-foreground ${
              refreshMutation.isPending ? "animate-spin" : ""
            }`}
          />
        </Button>
      </div>

      {/* Content */}
      {isSectionOpen && (
        <div id="schema-browser-content" className="mt-2 space-y-1 overflow-y-auto px-1 max-h-60 text-xs">
          {isLoading && (
            <div className="px-2 py-3 text-center text-muted-foreground">
              Loading schema...
            </div>
          )}

          {error && (
            <div className="px-2 py-2 text-destructive">
              Failed to load schema
            </div>
          )}

          {schema?.tables.map((table: CompactTable) => {
            const isExpanded = !!expandedTables[table.name];
            return (
              <div key={table.name} className="rounded-md border border-border/50 bg-background/50">
                <button
                  type="button"
                  onClick={() => toggleTable(table.name)}
                  className="flex w-full items-center justify-between px-2 py-1.5 text-left font-medium hover:bg-muted/50 rounded-md"
                  aria-expanded={isExpanded}
                >
                  <span className="truncate">{table.name}</span>
                  <span className="text-muted-foreground">
                    {isExpanded ? (
                      <ChevronDown className="size-3" />
                    ) : (
                      <ChevronRight className="size-3" />
                    )}
                  </span>
                </button>

                {isExpanded && (
                  <div className="border-t border-border/40 px-2 py-1.5 space-y-1 bg-muted/20">
                    {table.comment && (
                      <p className="text-[11px] text-muted-foreground italic mb-1">
                        {table.comment}
                      </p>
                    )}
                    <ul className="space-y-0.5" role="list">
                      {table.columns.map((col) => (
                        <li
                          key={col.name}
                          className="flex items-center justify-between text-[11px] py-0.5 text-foreground/80 font-mono"
                        >
                          <div className="flex items-center gap-1 truncate">
                            {col.is_pk && (
                              <span title="Primary Key" className="inline-flex items-center">
                                <Key
                                  className="size-2.5 text-amber-500 shrink-0"
                                  aria-label="Primary Key"
                                />
                              </span>
                            )}
                            <span className="truncate">{col.name}</span>
                            {col.is_fk && col.fk_target && (
                              <span
                                className="text-[10px] text-blue-500 font-sans"
                                title={`Foreign key -> ${col.fk_target}`}
                              >
                                →{col.fk_target.split(".")[0]}
                              </span>
                            )}
                          </div>
                          <span className="text-muted-foreground text-[10px] ml-1 shrink-0 font-sans">
                            {col.type}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
