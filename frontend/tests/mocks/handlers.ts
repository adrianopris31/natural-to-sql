import { http, HttpResponse } from "msw";
import {
  CompactSchema,
  ConversationDetail,
  ConversationSummary,
  HealthResponse,
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

        // Standard sequence
        controller.enqueue(encoder.encode("event: status\ndata: generating_sql\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: validating\n\n"));
        controller.enqueue(encoder.encode("event: status\ndata: executing\n\n"));
        controller.enqueue(
          encoder.encode("event: sql\ndata: SELECT id, name FROM users LIMIT 10\n\n")
        );
        controller.enqueue(
          encoder.encode(
            'event: result\ndata: {"columns":["id","name"],"rows":[[1,"Alice"],[2,"Bob"]],"row_count":2,"truncated":false}\n\n'
          )
        );
        controller.enqueue(encoder.encode("event: status\ndata: answering\n\n"));
        controller.enqueue(encoder.encode("event: answer_delta\ndata: Found 2 \n\n"));
        controller.enqueue(encoder.encode("event: answer_delta\ndata:users in the database.\n\n"));
        controller.enqueue(
          encoder.encode(
            `event: done\ndata: {"conversation_id":"${conversationId}","turn_id":"turn-mock-456"}\n\n`
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
];
