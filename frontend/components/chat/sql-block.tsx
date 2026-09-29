"use client";

import { useEffect, useState, useMemo } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface SqlBlockProps {
  sql: string;
  isComplete?: boolean;
  className?: string;
}

// Tokenizer for safe SQL syntax highlighting
function highlightSql(sql: string): React.ReactNode[] {
  const keywords = new Set([
    "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS",
    "ON", "GROUP", "BY", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "ALL", "AS",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "EXISTS", "CASE", "WHEN",
    "THEN", "ELSE", "END", "DESC", "ASC", "WITH", "DISTINCT", "SUM", "COUNT", "AVG",
    "MIN", "MAX", "COALESCE", "DATE", "DATE_FORMAT", "NOW", "CONCAT", "ROUND"
  ]);

  // Regex splitting by strings, comments, symbols, or word tokens
  const regex = /(--[^\n]*|\/\*[\s\S]*?\*\/|'(?:''|[^'])*'|"(?:""|[^"])*"|`[^`]*`|\b\w+\b|[^\w\s]|\s+)/g;
  const parts = sql.match(regex) || [sql];

  return parts.map((token, index) => {
    // Comments
    if (token.startsWith("--") || token.startsWith("/*")) {
      return (
        <span key={index} className="text-zinc-500 italic">
          {token}
        </span>
      );
    }
    // String literals
    if ((token.startsWith("'") && token.endsWith("'")) || (token.startsWith('"') && token.endsWith('"'))) {
      return (
        <span key={index} className="text-emerald-400 dark:text-emerald-300">
          {token}
        </span>
      );
    }
    // Backticked identifiers
    if (token.startsWith("`") && token.endsWith("`")) {
      return (
        <span key={index} className="text-sky-300 dark:text-sky-200">
          {token}
        </span>
      );
    }
    // Numbers
    if (/^\d+(\.\d+)?$/.test(token)) {
      return (
        <span key={index} className="text-amber-400 dark:text-amber-300">
          {token}
        </span>
      );
    }
    // Keywords
    if (keywords.has(token.toUpperCase())) {
      return (
        <span key={index} className="font-semibold text-purple-400 dark:text-purple-300">
          {token.toUpperCase()}
        </span>
      );
    }
    // Default text/symbols/whitespace
    return <span key={index}>{token}</span>;
  });
}

export function SqlBlock({ sql, isComplete = false, className }: SqlBlockProps) {
  // Collapsed by default once execution completes
  const [isOpen, setIsOpen] = useState(!isComplete);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isComplete) {
      setIsOpen(false);
    }
  }, [isComplete]);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const highlightedCode = useMemo(() => highlightSql(sql), [sql]);

  return (
    <div
      className={cn(
        "my-2 rounded-xl border border-border/80 bg-zinc-950 text-zinc-100 shadow-xs overflow-hidden",
        className
      )}
    >
      {/* Header bar */}
      <div
        onClick={() => setIsOpen((prev) => !prev)}
        className="flex cursor-pointer items-center justify-between px-3 py-2 bg-zinc-900/80 hover:bg-zinc-900 transition-colors select-none border-b border-zinc-800"
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setIsOpen((prev) => !prev);
          }
        }}
      >
        <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
          <Terminal className="size-3.5 text-zinc-400" />
          <span className="font-semibold text-zinc-300">SQL Query</span>
          <span className="text-[11px] text-zinc-500">
            {isOpen ? "(Click to collapse)" : "(Click to view)"}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="xs"
            onClick={handleCopy}
            className="h-6 gap-1 px-2 text-[11px] text-zinc-300 hover:text-white hover:bg-zinc-800"
            aria-label="Copy SQL"
            title="Copy SQL to clipboard"
          >
            {copied ? (
              <>
                <Check className="size-3 text-emerald-400" />
                <span className="text-emerald-400">Copied</span>
              </>
            ) : (
              <>
                <Copy className="size-3" />
                <span>Copy</span>
              </>
            )}
          </Button>

          <span className="text-zinc-500">
            {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </span>
        </div>
      </div>

      {/* Code content */}
      {isOpen && (
        <div className="overflow-x-auto p-3 text-xs font-mono leading-relaxed bg-zinc-950">
          <pre tabIndex={0} className="focus:outline-none">
            <code>{highlightedCode}</code>
          </pre>
        </div>
      )}
    </div>
  );
}
