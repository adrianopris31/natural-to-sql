"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Menu, Moon, Sun, X, Activity, ScrollText, Settings } from "lucide-react";
import { SqlLogPanel } from "./sql-log-panel";
import { SettingsDialog } from "./settings-dialog";

interface HeaderProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

export function Header({ sidebarOpen, onToggleSidebar }: HeaderProps) {
  const [isDark, setIsDark] = useState(false);
  const [sqlLogOpen, setSqlLogOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    // Check initial preference from document or system
    const isDarkMode =
      document.documentElement.classList.contains("dark") ||
      (typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    setIsDark(isDarkMode);
    if (isDarkMode) {
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggleTheme = () => {
    const nextDark = !isDark;
    setIsDark(nextDark);
    if (nextDark) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("theme", "light");
    }
  };

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });

  const isHealthy = health?.db === "ok" && health?.ollama === "ok";
  const showSettings = health?.settings_ui_enabled !== false;

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-background px-4">
      <div className="flex items-center gap-3">
        {/* Mobile toggle button */}
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          onClick={onToggleSidebar}
          aria-label={sidebarOpen ? "Close menu" : "Open menu"}
        >
          {sidebarOpen ? <X className="size-4" /> : <Menu className="size-4" />}
        </Button>

        <div className="flex items-center gap-2">
          <span className="font-semibold tracking-tight text-foreground">
            Natural to SQL
          </span>
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            v1.0
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Health status badge */}
        <div
          className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs"
          role="status"
          aria-live="polite"
        >
          <span
            className={`size-2 rounded-full ${
              healthLoading
                ? "bg-amber-400 animate-pulse"
                : isHealthy
                ? "bg-emerald-500"
                : "bg-destructive animate-pulse"
            }`}
          />
          <span className="text-muted-foreground text-[11px] hidden sm:inline">
            {healthLoading
              ? "Checking status..."
              : isHealthy
              ? `Connected (${health?.model || "ollama"})`
              : "Backend unavailable"}
          </span>
          <Activity className="size-3 text-muted-foreground sm:hidden" />
        </div>

        {/* SQL audit log */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setSqlLogOpen(true)}
          aria-label="Open SQL log"
          title="Every SQL query generated, edited, blocked or executed"
        >
          <ScrollText className="size-4" />
          <span className="hidden sm:inline">SQL log</span>
        </Button>

        {/* Integration Settings */}
        {showSettings && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setSettingsOpen(true)}
            aria-label="Integration Settings"
            title="Integration Settings"
          >
            <Settings className="size-4" />
          </Button>
        )}

        {/* Theme Toggle Button */}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={toggleTheme}
          aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
          title={isDark ? "Switch to light theme" : "Switch to dark theme"}
        >
          {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
      </div>
      <SqlLogPanel open={sqlLogOpen} onClose={() => setSqlLogOpen(false)} />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  );
}
