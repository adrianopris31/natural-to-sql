import {
  ChatRequest,
  CompactSchema,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
  SchemaRefreshResponse,
  SSEEvent,
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

export async function chatStream(
  message: string,
  conversationId?: string,
  onEvent?: (ev: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const url = `${API_BASE}/chat`;
  const body: ChatRequest = {
    message,
    ...(conversationId ? { conversation_id: conversationId } : {}),
  };

  const response = await fetch(url, {
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

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}
