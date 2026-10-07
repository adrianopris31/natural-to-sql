"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteConversation, fetchConversations } from "@/lib/api";
import { ConversationSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { SchemaBrowser } from "./schema-browser";
import { Database, FileText, Plus, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface SidebarProps {
  activeConversationId?: string;
  onSelectConversation: (id: string) => void;
  onNewChat: () => void;
  currentDatabase?: string | null;
  onSelectDatabase?: (databaseId: string) => void;
  className?: string;
}

export function Sidebar({
  activeConversationId,
  onSelectConversation,
  onNewChat,
  currentDatabase,
  className,
}: SidebarProps) {
  const queryClient = useQueryClient();

  const {
    data: conversations,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["conversations"],
    queryFn: fetchConversations,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (activeConversationId === deletedId) {
        onNewChat();
      }
    },
  });

  return (
    <aside
      className={cn(
        "flex h-full w-72 flex-col border-r border-border bg-sidebar p-3 text-sidebar-foreground",
        className
      )}
      aria-label="Sidebar navigation"
    >
      {/* New Chat Button */}
      <div className="mb-4">
        <Button
          onClick={onNewChat}
          className="w-full justify-start gap-2 bg-primary text-primary-foreground shadow-sm hover:bg-primary/90"
          aria-label="New chat"
        >
          <Plus className="size-4" />
          <span>New Chat</span>
        </Button>
      </div>

      {/* Conversations Section */}
      <div className="flex-1 overflow-y-auto min-h-0 space-y-1">
        <h2 className="px-2 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Conversations
        </h2>

        {isLoading && (
          <div className="p-3 text-center text-xs text-muted-foreground">
            Loading conversations...
          </div>
        )}

        {error && (
          <div className="p-3 text-center text-xs text-destructive">
            Failed to load conversations
          </div>
        )}

        {conversations && conversations.length === 0 && (
          <div className="p-3 text-center text-xs text-muted-foreground">
            No conversations yet
          </div>
        )}

        {conversations && conversations.length > 0 && (
          <div className="space-y-0.5" role="list">
            {conversations.map((conv: ConversationSummary) => {
              const isActive = activeConversationId === conv.id;
              const isDocs = conv.last_kind === "docs";
              return (
                <div
                  key={conv.id}
                  role="listitem"
                  className={cn(
                    "group relative flex items-center justify-between rounded-lg px-2.5 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground font-medium"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelectConversation(conv.id)}
                    className="flex flex-1 items-center gap-2 truncate text-left focus-visible:outline-none"
                    aria-current={isActive ? "page" : undefined}
                    data-kind={conv.last_kind || "sql"}
                  >
                    {isDocs ? (
                      <FileText className="size-3.5 shrink-0 opacity-70 text-blue-500" aria-label="Docs conversation" />
                    ) : (
                      <Database className="size-3.5 shrink-0 opacity-70" aria-label="Data conversation" />
                    )}
                    <span className="truncate">{conv.title}</span>
                  </button>

                  <Button
                    variant="ghost"
                    size="icon-xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteMutation.mutate(conv.id);
                    }}
                    disabled={deleteMutation.isPending}
                    className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity ml-1 hover:text-destructive"
                    aria-label={`Delete conversation ${conv.title}`}
                    title="Delete conversation"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Schema Browser Section */}
      <SchemaBrowser currentDatabase={currentDatabase} />
    </aside>
  );
}
