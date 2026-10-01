"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchConversation, fetchHealth } from "@/lib/api";
import { useChat } from "@/hooks/use-chat";
import { TurnKind } from "@/lib/types";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { HealthBanner } from "./health-banner";
import { UserMessage } from "./user-message";
import { AssistantTurn } from "./assistant-turn";
import { Button } from "@/components/ui/button";
import { ArrowUp, Database, FileText, Sparkles, Square } from "lucide-react";
import { cn } from "@/lib/utils";

const SOURCE_FILTERS = [
  { id: "all", label: "All" },
  { id: "jira", label: "Jira" },
  { id: "slack", label: "Slack" },
  { id: "doc", label: "Docs" },
] as const;

type SourceFilterId = (typeof SOURCE_FILTERS)[number]["id"];

export function ChatLayout() {
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inputMessage, setInputMessage] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [mode, setModeState] = useState<TurnKind>(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem("chat_mode");
        if (saved === "sql" || saved === "docs") return saved;
      } catch {
        // Ignore localStorage access errors
      }
    }
    return "sql";
  });

  const setMode = (newMode: TurnKind) => {
    setModeState(newMode);
    try {
      localStorage.setItem("chat_mode", newMode);
    } catch {
      // Ignore localStorage access errors
    }
  };

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  });

  const kbConfigured = health?.knowledge_bot?.configured ?? false;
  const kbReachable = health?.knowledge_bot?.reachable ?? false;
  const docsDisabled = !kbConfigured || !kbReachable;
  const docsDisabledReason = !kbConfigured
    ? "Knowledge Bot is not configured"
    : !kbReachable
    ? "Knowledge Bot service is unreachable"
    : "";

  useEffect(() => {
    if (docsDisabled && mode === "docs") {
      setMode("sql");
    }
  }, [docsDisabled, mode]);

  const {
    turns,
    isStreaming,
    activeConversationId,
    sendMessage,
    stopGeneration,
    retry,
    runTurn,
    cancelTurn,
    loadConversation,
    reset,
  } = useChat();

  // Scroll to bottom when turns change or streaming updates
  useEffect(() => {
    if (typeof messagesEndRef.current?.scrollIntoView === "function") {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [turns]);

  const handleNewChat = () => {
    reset();
    setSidebarOpen(false);
  };

  const handleSelectConversation = async (id: string) => {
    setSidebarOpen(false);
    try {
      const detail = await fetchConversation(id);
      loadConversation(detail);
      const lastTurn = detail.turns[detail.turns.length - 1];
      if (lastTurn?.kind === "docs" && !docsDisabled) {
        setMode("docs");
      } else if (lastTurn?.kind === "sql") {
        setMode("sql");
      }
    } catch {
      // In case fetch fails, keep current state
    }
  };

  const handleSend = async () => {
    if (!inputMessage.trim() || isStreaming) return;
    const msg = inputMessage.trim();
    setInputMessage("");
    await sendMessage(msg, undefined, mode);
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const getActiveSourceFilter = (msg: string): SourceFilterId => {
    const trimmed = msg.trimStart().toLowerCase();
    if (trimmed.startsWith("jira:")) return "jira";
    if (trimmed.startsWith("slack:")) return "slack";
    if (trimmed.startsWith("doc:")) return "doc";
    return "all";
  };

  const currentSourceFilter = getActiveSourceFilter(inputMessage);

  const handleSourceFilterClick = (filterId: SourceFilterId) => {
    setInputMessage((prev) => {
      const stripped = prev.replace(/^\s*(jira|slack|doc):\s*/i, "");
      if (filterId === "all") return stripped;
      return `${filterId}: ${stripped}`;
    });
  };

  const examplePrompts = [
    "Top 10 users by total spend",
    "Monthly revenue in 2025",
    "Which products have never been ordered?",
    "List all orders created this week",
  ];

  const docsExamplePrompts = [
    "How do we deploy to production?",
    "What is the status of the auth migration?",
    "jira: open high priority bugs",
    "slack: discussions about database timeout",
  ];

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      {/* Desktop Sidebar */}
      <div className="hidden md:flex h-full">
        <Sidebar
          activeConversationId={activeConversationId}
          onSelectConversation={handleSelectConversation}
          onNewChat={handleNewChat}
        />
      </div>

      {/* Mobile Sidebar Overlay Sheet */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-50 flex md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation drawer"
        >
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />

          {/* Drawer content */}
          <div className="relative z-10 flex w-72 max-w-[85vw] flex-col bg-background shadow-xl">
            <Sidebar
              activeConversationId={activeConversationId}
              onSelectConversation={handleSelectConversation}
              onNewChat={handleNewChat}
              className="w-full border-r-0"
            />
          </div>
        </div>
      )}

      {/* Main Chat Area */}
      <main className="flex flex-1 flex-col h-full min-w-0">
        <Header
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
        />

        {/* Top Health Warning Banner */}
        <HealthBanner />

        {/* Scrollable Turn Area */}
        <div className="flex-1 overflow-y-auto px-4 py-6" role="log" aria-label="Chat history">
          <div className="mx-auto max-w-3xl space-y-6">
            {turns.length === 0 ? (
              <div className="flex flex-col items-center justify-center pt-16 text-center">
                <div className="rounded-full bg-primary/10 p-3 text-primary mb-4">
                  <Sparkles className="size-6" />
                </div>
                <h1 className="text-2xl font-bold tracking-tight text-foreground">
                  {mode === "docs" ? "Ask anything about your team docs" : "Ask anything about your database"}
                </h1>
                <p className="mt-2 text-sm text-muted-foreground max-w-md">
                  {mode === "docs"
                    ? "Search across Jira tickets, Slack discussions, and team runbooks to find answers with verified sources."
                    : "Natural language is converted to validated, read-only SQL, executed, and summarized with verified data."}
                </p>

                {/* Example Questions */}
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
                  {(mode === "docs" ? docsExamplePrompts : examplePrompts).map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => setInputMessage(prompt)}
                      className="rounded-lg border border-border/80 bg-card p-3 text-left text-xs font-medium text-foreground/90 transition-colors hover:bg-muted hover:border-foreground/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((turn, index) => {
                const isLastTurn = index === turns.length - 1;
                return (
                  <div key={turn.id} className="space-y-4">
                    {/* User message */}
                    <UserMessage content={turn.question} />

                    {/* Assistant turn */}
                    <AssistantTurn
                      turn={turn}
                      isStreaming={isLastTurn && isStreaming}
                      onRetry={() => retry(turn.id)}
                      onRun={async (edits) => {
                        await runTurn(turn.id, edits);
                        queryClient.invalidateQueries({ queryKey: ["conversations"] });
                      }}
                      onCancel={() => cancelTurn(turn.id)}
                    />
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Bar Area */}
        <div className="border-t border-border bg-background p-4">
          <div className="mx-auto max-w-3xl space-y-2">
            {/* Mode Toggle & Source Filter bar */}
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              {/* Segmented Control */}
              <div
                role="radiogroup"
                aria-label="Query mode"
                className="inline-flex items-center rounded-lg bg-muted p-1 text-muted-foreground"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={mode === "sql"}
                  onClick={() => setMode("sql")}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    mode === "sql"
                      ? "bg-background text-foreground shadow-xs"
                      : "hover:text-foreground"
                  )}
                  aria-label="Data mode"
                >
                  <Database className="size-3.5" />
                  <span>Data</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={mode === "docs"}
                  onClick={() => !docsDisabled && setMode("docs")}
                  disabled={docsDisabled}
                  title={docsDisabledReason || undefined}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    mode === "docs"
                      ? "bg-background text-foreground shadow-xs"
                      : "hover:text-foreground",
                    docsDisabled && "opacity-50 cursor-not-allowed hover:text-muted-foreground"
                  )}
                  aria-label={docsDisabled ? `Docs mode (${docsDisabledReason})` : "Docs mode"}
                >
                  <FileText className="size-3.5" />
                  <span>Docs</span>
                </button>
              </div>

              {/* Source filters (visible in docs mode) */}
              {mode === "docs" && (
                <div className="flex items-center gap-1 text-xs" role="group" aria-label="Source filters">
                  <span className="text-[11px] text-muted-foreground mr-1 hidden sm:inline">Source:</span>
                  {SOURCE_FILTERS.map((f) => {
                    const active = currentSourceFilter === f.id;
                    return (
                      <button
                        key={f.id}
                        type="button"
                        onClick={() => handleSourceFilterClick(f.id)}
                        className={cn(
                          "rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors border",
                          active
                            ? "bg-primary text-primary-foreground border-primary"
                            : "border-border/60 bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                        aria-pressed={active}
                      >
                        {f.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="relative rounded-xl border border-input bg-card shadow-xs focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
              <textarea
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  mode === "docs"
                    ? "Ask a question about Jira, Slack, or docs..."
                    : "Ask a question about your database (e.g. top customers by spend)..."
                }
                rows={2}
                disabled={isStreaming}
                className="w-full resize-none bg-transparent px-3.5 py-3 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-60"
                aria-label={mode === "docs" ? "Ask a question about documentation" : "Ask a question"}
              />

              <div className="flex items-center justify-between px-3 py-2 border-t border-border/40">
                <span className="text-[11px] text-muted-foreground hidden sm:flex items-center gap-1">
                  <span>Press</span>
                  <kbd className="rounded border bg-muted px-1 py-0.5 text-[10px] font-mono">
                    Enter
                  </kbd>
                  <span>to send,</span>
                  <kbd className="rounded border bg-muted px-1 py-0.5 text-[10px] font-mono">
                    Shift + Enter
                  </kbd>
                  <span>for new line</span>
                </span>
                <span className="sm:hidden" />

                {isStreaming ? (
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={stopGeneration}
                    className="gap-1.5"
                    aria-label="Stop generating response"
                  >
                    <Square className="size-3 fill-current" />
                    <span>Stop</span>
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={handleSend}
                    disabled={!inputMessage.trim()}
                    className="gap-1.5"
                    aria-label="Send message"
                  >
                    <span className="hidden sm:inline">Send</span>
                    <ArrowUp className="size-3.5" />
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
