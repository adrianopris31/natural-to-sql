"use client";

import { useMemo } from "react";
import { Download, Table as TableIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ResultTableProps {
  columns: string[];
  rows: (string | number | boolean | null)[][];
  rowCount?: number;
  truncated?: boolean;
  className?: string;
}

function formatCell(val: string | number | boolean | null): React.ReactNode {
  if (val === null || val === undefined) {
    return <span className="italic text-muted-foreground/60 select-none">NULL</span>;
  }
  if (typeof val === "boolean") {
    return <span className="font-mono text-xs">{val ? "TRUE" : "FALSE"}</span>;
  }
  if (typeof val === "number") {
    return (
      <span className="font-mono text-xs">
        {Number.isInteger(val)
          ? val.toLocaleString()
          : val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
      </span>
    );
  }
  return <span className="break-words">{String(val)}</span>;
}

export function ResultTable({
  columns,
  rows,
  rowCount,
  truncated = false,
  className,
}: ResultTableProps) {
  const isNumberCol = useMemo(() => {
    return columns.map((_, colIdx) => {
      // Check if all non-null values in this column are numbers
      let hasValue = false;
      for (const row of rows) {
        const val = row[colIdx];
        if (val !== null && val !== undefined) {
          hasValue = true;
          if (typeof val !== "number") return false;
        }
      }
      return hasValue;
    });
  }, [columns, rows]);

  const handleExportCsv = () => {
    if (columns.length === 0) return;

    const escapeCell = (val: string | number | boolean | null): string => {
      if (val === null || val === undefined) return "";
      const str = String(val);
      if (str.includes(",") || str.includes('"') || str.includes("\n")) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const headerLine = columns.map((col) => escapeCell(col)).join(",");
    const rowLines = rows.map((row) =>
      row.map((val) => escapeCell(val)).join(",")
    );

    const csvContent = [headerLine, ...rowLines].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `query_results_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  if (!columns || columns.length === 0 || rows.length === 0) {
    return (
      <div
        className={cn(
          "my-3 rounded-xl border border-dashed border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground",
          className
        )}
      >
        <TableIcon className="mx-auto size-6 opacity-40 mb-2" />
        <p>Query returned no rows</p>
      </div>
    );
  }

  const displayCount = rows.length;
  const totalCount = rowCount ?? displayCount;

  return (
    <div
      className={cn(
        "my-3 rounded-xl border border-border bg-card shadow-xs overflow-hidden",
        className
      )}
    >
      {/* Top action / info bar */}
      <div className="flex items-center justify-between border-b border-border bg-muted/40 px-3 py-2 text-xs">
        <div className="flex items-center gap-2">
          <TableIcon className="size-3.5 text-muted-foreground" />
          <span className="font-medium text-foreground">Query Results</span>
          {truncated ? (
            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400">
              Showing {displayCount} of {totalCount} (truncated)
            </span>
          ) : (
            <span className="text-[11px] text-muted-foreground">
              {displayCount} {displayCount === 1 ? "row" : "rows"}
            </span>
          )}
        </div>

        <Button
          variant="outline"
          size="xs"
          onClick={handleExportCsv}
          className="gap-1 text-[11px] h-6 px-2"
          aria-label="Export results as CSV"
        >
          <Download className="size-3" />
          <span>Export CSV</span>
        </Button>
      </div>

      {/* Table with sticky header & scroll */}
      <div className="max-h-80 overflow-auto">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur-xs shadow-xs border-b border-border">
            <tr>
              {columns.map((col, idx) => (
                <th
                  key={col}
                  scope="col"
                  className={cn(
                    "px-3 py-2 font-semibold text-foreground/90 whitespace-nowrap",
                    isNumberCol[idx] && "text-right"
                  )}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {rows.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className="hover:bg-muted/40 transition-colors"
              >
                {row.map((cell, colIdx) => (
                  <td
                    key={colIdx}
                    className={cn(
                      "px-3 py-2 text-foreground/80 align-top",
                      isNumberCol[colIdx] && "text-right"
                    )}
                  >
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
