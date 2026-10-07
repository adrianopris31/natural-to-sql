import {
  AuditEntry,
  ChatRequest,
  RunRequest,
  ConversationDetail,
  ConversationSummary,
  DatabaseItem,
  HealthResponse,
  SchemaRefreshResponse,
  SchemaResponse,
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

// Settings calls go straight to the backend, never through the Next.js /api
// rewrite: the proxy hides who is asking (every proxied request arrives from
// 127.0.0.1), so the backend refuses proxied settings requests outright.
export const SETTINGS_API_BASE =
  process.env.NEXT_PUBLIC_SETTINGS_API_BASE || "http://127.0.0.1:8000/api";

// The backend requires this on settings routes. A custom header forces a CORS
// preflight, so another website cannot fire a settings request at the backend.
const SETTINGS_HEADERS = { "X-Requested-With": "natural-to-sql" };

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

async function request<T>(
  path: string,
  init?: RequestInit,
  base: string = API_BASE
): Promise<T> {
  const url = `${base}${path}`;
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
  mode?: TurnKind,
  database?: string
): Promise<void> {
  const body: ChatRequest = {
    message,
    ...(conversationId ? { conversation_id: conversationId } : {}),
    ...(mode ? { mode } : {}),
    ...(database ? { database } : {}),
  };
  return streamSSE("/chat", body, onEvent, signal);
}

/** Convenience wrapper matching alternative argument ordering. */
export async function sendChatStream(
  message: string,
  conversationId?: string,
  mode?: string,
  database?: string,
  onEvent?: (ev: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  return chatStream(message, conversationId, onEvent, signal, mode as TurnKind, database);
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

export async function fetchDatabases(): Promise<DatabaseItem[]> {
  return request<DatabaseItem[]>("/databases");
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

export async function fetchSchema(database?: string): Promise<SchemaResponse> {
  const query = database ? `?database=${encodeURIComponent(database)}` : "";
  return request<SchemaResponse>(`/schema${query}`);
}

export async function refreshSchema(database?: string): Promise<SchemaRefreshResponse> {
  const query = database ? `?database=${encodeURIComponent(database)}` : "";
  return request<SchemaRefreshResponse>(`/schema/refresh${query}`, {
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

/** The readable reason behind a failed request: the backend's `detail` when it sent one. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.body && typeof err.body === "object") {
    const detail = (err.body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const msgs = detail
        .map((item) => (item && typeof item === "object" ? (item as { msg?: unknown }).msg : null))
        .filter((msg): msg is string => typeof msg === "string");
      if (msgs.length) return msgs.join("; ");
    }
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

function settingsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(
    `/settings${path}`,
    { ...init, headers: { ...SETTINGS_HEADERS, ...init?.headers } },
    SETTINGS_API_BASE
  );
}

export async function fetchSources(): Promise<{ sources: SourceItem[] }> {
  return settingsRequest<{ sources: SourceItem[] }>("/sources");
}

export async function saveJiraSource(body: JiraSourceForm): Promise<SourceItem> {
  return settingsRequest<SourceItem>("/sources/jira", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function saveSlackSource(body: SlackSourceForm): Promise<SourceItem> {
  return settingsRequest<SourceItem>("/sources/slack", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function testSource(
  source: SourceType,
  body?: JiraSourceForm | SlackSourceForm | Record<string, unknown>
): Promise<SourceTestResult> {
  return settingsRequest<SourceTestResult>(`/sources/${source}/test`, {
    method: "POST",
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

export async function deleteSource(source: SourceType): Promise<void> {
  return settingsRequest<void>(`/sources/${source}`, {
    method: "DELETE",
  });
}

/** knowledge-bot's refresh result: it answers once the fetch has finished. */
export interface RefreshResult {
  ok?: boolean;
  documents?: number;
  message?: string;
}

export async function refreshDocuments(): Promise<RefreshResult> {
  return settingsRequest<RefreshResult>("/refresh", {
    method: "POST",
  });
}
