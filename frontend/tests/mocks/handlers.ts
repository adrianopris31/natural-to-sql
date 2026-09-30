import { http, HttpResponse } from "msw";
import {
  CompactSchema,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
  AuditEntry,
  RiskReport,
  RunRequest,
  TurnQuery,
} from "@/lib/types";

export const mockConversations: ConversationSummary[] = [
  {
    id: "conv-1",
    title: "Top 10 users by total spend",
    updated_at: "2026-09-28T12:00:00Z",
  },
  {
    id: "conv-2",
    title: "Monthly revenue in 2025",
    updated_at: "2026-09-28T14:30:00Z",
  },
];

export const mockConversationDetail: ConversationDetail = {
  id: "conv-1",
  title: "Top 10 users by total spend",
  turns: [
    {
      id: "turn-1",
      question: "Top 10 users by total spend",
      sql: "SELECT u.id, u.name, SUM(p.amount) AS total_spend FROM users u JOIN orders o ON u.id = o.user_id JOIN payments p ON o.id = p.order_id GROUP BY u.id, u.name ORDER BY total_spend DESC LIMIT 10",
      columns: ["id", "name", "total_spend"],
      rows: [
        [1, "Alice Smith", 1250.5],
        [2, "Bob Jones", 980.0],
      ],
      row_count: 2,
      truncated: false,
      answer: "The top 2 users by total spend are Alice Smith ($1,250.50) and Bob Jones ($980.00).",
      status: "done",
      error: null,
      created_at: "2026-09-28T12:00:00Z",
    },
  ],
};

export const mockSchema: CompactSchema = {
  tables: [
    {
      name: "users",
      comment: "Registered users in the system",
      columns: [
        { name: "id", type: "int", is_pk: true },
        { name: "email", type: "varchar(255)" },
        { name: "name", type: "varchar(100)" },
        { name: "created_at", type: "timestamp" },
      ],
    },
    {
      name: "products",
      comment: "Catalog products",
      columns: [
        { name: "id", type: "int", is_pk: true },
        { name: "name", type: "varchar(255)" },
        { name: "price", type: "decimal(10,2)" },
        { name: "category_id", type: "int", is_fk: true, fk_target: "categories.id" },
      ],
    },
    {
      name: "orders",
      comment: "Customer orders",
      columns: [
        { name: "id", type: "int", is_pk: true },
        { name: "user_id", type: "int", is_fk: true, fk_target: "users.id" },
        { name: "status", type: "varchar(50)", sample_values: ["completed", "pending"] },
        { name: "created_at", type: "timestamp" },
      ],
    },
  ],
};

export const mockHealth: HealthResponse = {
  db: "ok",
  ollama: "ok",
  model: "qwen2.5-coder:7b",
  db_version: "9.0.1",
};

export function mockPreviewQuery(
  index: number,
  sql: string,
  purpose: string,
  blocked = false,
  risk: RiskReport = { level: "none", flags: [] }
): TurnQuery {
  return {
    index,
    purpose,
    sql,
    risk,
    explain: {
      cost: blocked ? 9_000_000 : 51.25,
      estimated_rows: blocked ? 9_000_000 : 10,
      tables: [{ table: "users", access_type: "index", key: "PRIMARY", rows_examined: 10, rows_produced: 10 }],
      warnings: [],
      blocked,
      block_reason: blocked ? "Estimated cost 9,000,000 exceeds the limit of 5,000,000" : null,
    },
    columns: null,
    rows: null,
    row_count: null,
    truncated: null,
    error: null,
  };
}

export const mockAuditEntries: AuditEntry[] = [
  {
    id: "a2",
    created_at: "2026-09-29T09:00:02Z",
    turn_id: "t1",
    conversation_id: "c1",
    question: "Show me user number one",
    stage: "executed",
    attempt: 0,
    accepted: true,
    raw_sql: "SELECT id FROM users WHERE id = 1",
    safe_sql: "SELECT id FROM users WHERE id = 1 LIMIT 501",
    reason: null,
    row_count: 1,
    elapsed_ms: 4.2,
  },
  {
    id: "a1",
    created_at: "2026-09-29T09:00:01Z",
    turn_id: "t1",
    conversation_id: "c1",
    question: "Show me user number one",
    stage: "rejected",
    attempt: 0,
    accepted: false,
    raw_sql: "DELETE FROM users WHERE id = 1",
    safe_sql: null,
    reason: "Forbidden statement type: expected SELECT, got Delete",
    row_count: null,
    elapsed_ms: null,
  },
];

/** Last body received by the /run mock, for assertions. */
export const lastRunRequest: { body: RunRequest | null } = { body: null };

function sseResponse(chunks: string[]): HttpResponse<ReadableStream<Uint8Array>> {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
}

export const handlers = [
  // Health
  http.get("/api/health", () => {
    return HttpResponse.json(mockHealth);
  }),

  // Schema
  http.get("/api/schema", () => {
    return HttpResponse.json(mockSchema);
  }),

  http.post("/api/schema/refresh", () => {
    return HttpResponse.json({ tables: mockSchema.tables.length });
  }),

  // Conversations
  http.get("/api/conversations", () => {
    return HttpResponse.json(mockConversations);
  }),

  http.get("/api/conversations/:id", ({ params }) => {
    const { id } = params;
    return HttpResponse.json({
      ...mockConversationDetail,
      id: String(id),
    });
  }),

  http.delete("/api/conversations/:id", () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // Chat SSE Stream
  http.post("/api/chat", async ({ request }) => {
    const body = (await request.json()) as { message?: string; conversation_id?: string };
    const message = body.message || "";
    const conversationId = body.conversation_id || "conv-mock-123";

    const encoder = new TextEncoder();

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        if (message.toLowerCase().includes("clarify")) {
          controller.enqueue(
            encoder.encode("event: status\ndata: generating_sql\n\n")
          );
          controller.enqueue(
            encoder.encode(
              'event: clarification\ndata: {"question":"Did you mean total users or active users?"}\n\n'
            )
          );
          // Real backend sends `done` after a clarification; it must not hide it
          controller.enqueue(
            encoder.encode(
              `event: done\ndata: {"conversation_id":"${conversationId}","turn_id":"turn-clar-1"}\n\n`
            )
          );
          controller.close();
          return;
        }

        if (message.toLowerCase().startsWith("delete")) {
          controller.enqueue(
            encoder.encode(
              `event: refused\ndata: ${JSON.stringify({
                conversation_id: conversationId,
                turn_id: "turn-refused-1",
                message: "Not performed: this assistant is read-only and cannot delete, change or add data.",
              })}\n\n`
            )
          );
          controller.close();
          return;
        }

        if (message.toLowerCase().includes("error")) {
          controller.enqueue(
            encoder.encode("event: status\ndata: generating_sql\n\n")
          );
          controller.enqueue(
            encoder.encode(
              'event: error\ndata: {"message":"Failed to parse query safely","code":"VALIDATION_FAILED"}\n\n'
            )
          );
          controller.close();
          return;
        }

        if (message.toLowerCase().includes("cutoff")) {
          // Simulates a proxy closing the stream mid-generation (no terminal event)
          controller.enqueue(encoder.encode(": ping\n\n"));
          controller.enqueue(encoder.encode("event: status\ndata: generating_sql\n\n"));
          controller.close();
          return;
        }

        // Standard sequence: plan → preview (nothing executes until /run)
        const queries =
          message.toLowerCase().includes("two things")
            ? [mockPreviewQuery(0, "SELECT id, name FROM users LIMIT 10", "Users"),
               mockPreviewQuery(1, "SELECT COUNT(*) AS n FROM orders", "Order count")]
            : [mockPreviewQuery(0, "SELECT id, name FROM users LIMIT 10", "Users",
                message.toLowerCase().includes("blocked"))];
        controller.enqueue(encoder.encode(": ping\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: generating_sql\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: validating\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: explaining\n\n"));
        controller.enqueue(
          encoder.encode(
            `event: preview\ndata: ${JSON.stringify({
              conversation_id: conversationId,
              turn_id: "turn-mock-456",
              queries,
            })}\n\n`
          )
        );
        controller.close();
      },
    });

    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }),

  // Approve & run a previewed turn
  http.post("/api/chat/:turnId/run", async ({ request, params }) => {
    const body = (await request.json()) as RunRequest;
    lastRunRequest.body = body;
    const edited = body.queries?.[0];
    if (edited && edited.toUpperCase().includes("DROP")) {
      return sseResponse([
        'event: error\ndata: {"message":"Query 1: SQL rejected for safety: Forbidden statement type","code":"VALIDATION_FAILED","index":0}\n\n',
      ]);
    }
    const sql = edited ?? "SELECT id, name FROM users LIMIT 10";
    return sseResponse([
      "event: status\ndata: executing\n\n",
      `event: result\ndata: ${JSON.stringify({
        index: 0,
        sql,
        columns: ["id", "name"],
        rows: [[1, "Alice"], [2, "Bob"]],
        row_count: 2,
        truncated: false,
        error: null,
      })}\n\n`,
      "event: status\ndata: answering\n\n",
      "event: answer_delta\ndata: Found 2 \n\n",
      "event: answer_delta\ndata:users in the database.\n\n",
      `event: done\ndata: {"conversation_id":"conv-mock-123","turn_id":"${String(params.turnId)}"}\n\n`,
    ]);
  }),

  http.get("/api/audit", () => HttpResponse.json(mockAuditEntries)),

  http.post("/api/chat/:turnId/cancel", () => {
    return new HttpResponse(null, { status: 204 });
  }),
];
