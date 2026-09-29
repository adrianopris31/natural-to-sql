"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchConversation } from "@/lib/api";
import { useChat } from "@/hooks/use-chat";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { HealthBanner } from "./health-banner";
import { UserMessage } from "./user-message";
import { AssistantTurn } from "./assistant-turn";
import { Button } from "@/components/ui/button";
import { ArrowUp, Sparkles, Square } from "lucide-react";

export function ChatLayout() {
  const queryClient = useQueryClient();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inputMessage, setInputMessage] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const {
    turns,
    isStreaming,
    activeConversationId,
    sendMessage,
    stopGeneration,
    retry,
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
    } catch {
      // In case fetch fails, keep current state
    }
  };

  const handleSend = async () => {
    if (!inputMessage.trim() || isStreaming) return;
    const msg = inputMessage.trim();
    setInputMessage("");
    await sendMessage(msg);
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const examplePrompts = [
    "Top 10 users by total spend",
    "Monthly revenue in 2025",
    "Which products have never been ordered?",
    "List all orders created this week",
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
                  Ask anything about your database
                </h1>
                <p className="mt-2 text-sm text-muted-foreground max-w-md">
                  Natural language is converted to validated, read-only SQL, executed,
                  and summarized with verified data.
                </p>

                {/* Example Questions */}
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-lg">
                  {examplePrompts.map((prompt) => (
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
          <div className="mx-auto max-w-3xl">
            <div className="relative rounded-xl border border-input bg-card shadow-xs focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
              <textarea
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask a question about your database (e.g. top customers by spend)..."
                rows={2}
                disabled={isStreaming}
                className="w-full resize-none bg-transparent px-3.5 py-3 text-sm placeholder:text-muted-foreground focus:outline-none disabled:opacity-60"
                aria-label="Ask a question"
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
