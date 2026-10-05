import {
  AuditEntry,
  ChatRequest,
  RunRequest,
  CompactSchema,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
  SchemaRefreshResponse,
  SSEEvent,
  TurnKind,
  SourceItem,
  SourceTestResult,
  SourceType,
  JiraSourceForm,
  SlackSourceForm,
} from "./types";
import { consumeSSEStream } from "./sse";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let errBody: unknown;
    try {
      errBody = await response.json();
    } catch {
      errBody = await response.text();
    }
    throw new ApiError(
      `API request to ${path} failed with status ${response.status}`,
      response.status,
      errBody
    );
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}

async function streamSSE(
  path: string,
  body: unknown,
  onEvent?: (ev: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    let errBody: unknown;
    try {
      errBody = await response.json();
    } catch {
      errBody = await response.text();
    }
    throw new ApiError(
      `Chat stream request failed with status ${response.status}`,
      response.status,
      errBody
    );
  }

  if (!response.body) {
    throw new Error("Chat response body is not readable");
  }

  if (onEvent) {
    await consumeSSEStream(response.body, onEvent, signal);
  }
}

/** Phase 1: ask a question. Streams status events and ends with `preview` (nothing runs). */
export async function chatStream(
  message: string,
  conversationId?: string,
  onEvent?: (ev: SSEEvent) => void,
  signal?: AbortSignal,
  mode?: TurnKind
): Promise<void> {
  const body: ChatRequest = {
    message,
    ...(conversationId ? { conversation_id: conversationId } : {}),
    ...(mode ? { mode } : {}),
  };
  return streamSSE("/chat", body, onEvent, signal);
}

/** Phase 2: approve a previewed turn (optionally with edited SQL) and stream results. */
export async function runTurnStream(
  turnId: string,
  queries: (string | null)[] | undefined,
  onEvent?: (ev: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const body: RunRequest = queries ? { queries } : {};
  return streamSSE(`/chat/${encodeURIComponent(turnId)}/run`, body, onEvent, signal);
}

export async function cancelTurn(turnId: string): Promise<void> {
  return request<void>(`/chat/${encodeURIComponent(turnId)}/cancel`, { method: "POST" });
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  return request<ConversationSummary[]>("/conversations");
}

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}`);
}

export async function deleteConversation(id: string): Promise<void> {
  return request<void>(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function fetchSchema(): Promise<CompactSchema> {
  return request<CompactSchema>("/schema");
}

export async function refreshSchema(): Promise<SchemaRefreshResponse> {
  return request<SchemaRefreshResponse>("/schema/refresh", {
    method: "POST",
  });
}

/** Newest-first SQL audit log (every generated, edited, blocked and executed query). */
export async function fetchAuditLog(limit = 200, turnId?: string): Promise<AuditEntry[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (turnId) params.set("turn_id", turnId);
  return request<AuditEntry[]>(`/audit?${params.toString()}`);
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

export async function fetchSources(): Promise<{ sources: SourceItem[] }> {
  return request<{ sources: SourceItem[] }>("/settings/sources");
}

export async function saveJiraSource(body: JiraSourceForm): Promise<SourceItem> {
  return request<SourceItem>("/settings/sources/jira", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function saveSlackSource(body: SlackSourceForm): Promise<SourceItem> {
  return request<SourceItem>("/settings/sources/slack", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function testSource(
  source: SourceType,
  body?: JiraSourceForm | SlackSourceForm | Record<string, unknown>
): Promise<SourceTestResult> {
  return request<SourceTestResult>(`/settings/sources/${source}/test`, {
    method: "POST",
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

export async function deleteSource(source: SourceType): Promise<void> {
  return request<void>(`/settings/sources/${source}`, {
    method: "DELETE",
  });
}

export async function refreshDocuments(): Promise<{ message?: string }> {
  return request<{ message?: string }>("/settings/refresh", {
    method: "POST",
  });
}
