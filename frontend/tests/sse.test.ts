import { describe, expect, it } from "vitest";
import { consumeSSEStream, parseSSEStream, parseSSEText } from "@/lib/sse";
import { SSEEvent } from "@/lib/types";

// Helper to create a ReadableStream from an array of chunks (strings or Uint8Arrays)
function createStream(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        if (typeof chunk === "string") {
          controller.enqueue(encoder.encode(chunk));
        } else {
          controller.enqueue(chunk);
        }
      }
      controller.close();
    },
  });
}

describe("SSE Parser (lib/sse.ts)", () => {
  describe("parseSSEText", () => {
    it("parses full standard SSE lifecycle sequence", () => {
      const ssePayload = [
        "event: status",
        "data: generating_sql",
        "",
        "event: status",
        "data: validating",
        "",
        "event: sql",
        'data: SELECT id, name FROM users WHERE role = "admin" LIMIT 500',
        "",
        "event: result",
        'data: {"columns":["id","name"],"rows":[[1,"Alice"],[2,"Bob"]],"row_count":2,"truncated":false}',
        "",
        "event: answer_delta",
        "data: There are 2 ",
        "",
        "event: answer_delta",
        "data:admin users.",
        "",
        "event: done",
        'data: {"conversation_id":"c123","turn_id":"t456","timings":{"sql_ms":120}}',
        "",
      ].join("\n");

      const events = parseSSEText(ssePayload);
      expect(events).toHaveLength(7);
      expect(events[0]).toEqual({ type: "status", data: "generating_sql" });
      expect(events[1]).toEqual({ type: "status", data: "validating" });
      expect(events[2]).toEqual({
        type: "sql",
        data: 'SELECT id, name FROM users WHERE role = "admin" LIMIT 500',
      });
      expect(events[3]).toEqual({
        type: "result",
        data: {
          columns: ["id", "name"],
          rows: [
            [1, "Alice"],
            [2, "Bob"],
          ],
          row_count: 2,
          truncated: false,
        },
      });
      expect(events[4]).toEqual({ type: "answer_delta", data: "There are 2 " });
      expect(events[5]).toEqual({ type: "answer_delta", data: "admin users." });
      expect(events[6]).toEqual({
        type: "done",
        data: {
          conversation_id: "c123",
          turn_id: "t456",
          timings: { sql_ms: 120 },
        },
      });
    });

    it("parses clarification and error events", () => {
      const payload = [
        "event: clarification",
        'data: {"question":"Did you mean users or orders?"}',
        "",
        "event: error",
        'data: {"message":"Table does not exist","code":"E_TABLE_NOT_FOUND"}',
        "",
      ].join("\n");

      const events = parseSSEText(payload);
      expect(events).toEqual([
        {
          type: "clarification",
          data: { question: "Did you mean users or orders?" },
        },
        {
          type: "error",
          data: {
            message: "Table does not exist",
            code: "E_TABLE_NOT_FOUND",
          },
        },
      ]);
    });

    it("ignores comment lines and empty heartbeats", () => {
      const payload = [
        ": keep-alive",
        "",
        ": heartbeat",
        "event: status",
        "data: executing",
        "",
        ": ping",
        "",
      ].join("\n");

      const events = parseSSEText(payload);
      expect(events).toEqual([{ type: "status", data: "executing" }]);
    });

    it("handles multi-line data correctly", () => {
      const payload = [
        "event: sql",
        "data: SELECT *",
        "data: FROM products",
        "data: LIMIT 10",
        "",
      ].join("\n");

      const events = parseSSEText(payload);
      expect(events).toEqual([
        {
          type: "sql",
          data: "SELECT *\nFROM products\nLIMIT 10",
        },
      ]);
    });
  });

  describe("parseSSEStream", () => {
    it("handles chunk fragmentation across field names, values, and newlines", async () => {
      const chunks = [
        "eve",
        "nt: sta",
        "tus\ndata: gen",
        "erating_sql\n",
        "\n",
        "event: sql\nda",
        "ta: SELECT 1\n\n",
      ];

      const stream = createStream(chunks);
      const events: SSEEvent[] = [];
      for await (const ev of parseSSEStream(stream)) {
        events.push(ev);
      }

      expect(events).toEqual([
        { type: "status", data: "generating_sql" },
        { type: "sql", data: "SELECT 1" },
      ]);
    });

    it("handles single-byte streaming without corruption", async () => {
      const fullText = "event: status\ndata: done\n\n";
      const encoder = new TextEncoder();
      const encoded = encoder.encode(fullText);

      // Split into 1-byte chunks
      const chunks: Uint8Array[] = [];
      for (let i = 0; i < encoded.length; i++) {
        chunks.push(encoded.subarray(i, i + 1));
      }

      const stream = createStream(chunks);
      const events: SSEEvent[] = [];
      for await (const ev of parseSSEStream(stream)) {
        events.push(ev);
      }

      expect(events).toEqual([{ type: "status", data: "done" }]);
    });

    it("handles multi-byte UTF-8 split across byte boundaries", async () => {
      // "🎉 Database: 数据库 €100" contains:
      // 🎉: 4 bytes (0xf0, 0x9f, 0x8e, 0x89)
      // 数: 3 bytes
      // 据: 3 bytes
      // 库: 3 bytes
      // €: 3 bytes
      const text = "event: answer_delta\ndata: 🎉 数据库 €100\n\n";
      const bytes = new TextEncoder().encode(text);

      // Intentionally slice in the middle of a multi-byte character
      const splitIndex = 25; // inside the unicode bytes
      const chunk1 = bytes.subarray(0, splitIndex);
      const chunk2 = bytes.subarray(splitIndex);

      const stream = createStream([chunk1, chunk2]);
      const events: SSEEvent[] = [];
      for await (const ev of parseSSEStream(stream)) {
        events.push(ev);
      }

      expect(events).toEqual([
        {
          type: "answer_delta",
          data: "🎉 数据库 €100",
        },
      ]);
    });

    it("stops streaming when AbortSignal is triggered", async () => {
      const abortController = new AbortController();

      const chunks = [
        "event: status\ndata: generating_sql\n\n",
        "event: status\ndata: executing\n\n",
        "event: answer_delta\ndata: Partial response\n\n",
      ];

      const stream = createStream(chunks);
      const events: SSEEvent[] = [];

      await consumeSSEStream(
        stream,
        (ev) => {
          events.push(ev);
          if (ev.type === "status" && ev.data === "executing") {
            abortController.abort();
          }
        },
        abortController.signal
      );

      expect(events).toHaveLength(2);
      expect(events[0]).toEqual({ type: "status", data: "generating_sql" });
      expect(events[1]).toEqual({ type: "status", data: "executing" });
    });
  });
});

describe("preview and indexed result events", () => {
  it("parses preview events with queries and explain", () => {
    const events = parseSSEText(
      'event: preview\ndata: {"conversation_id":"c","turn_id":"t","queries":[{"index":0,"purpose":"p","sql":"SELECT 1","explain":{"cost":1,"estimated_rows":1,"tables":[],"warnings":[],"blocked":false,"block_reason":null},"columns":null,"rows":null,"row_count":null,"truncated":null,"error":null}]}\n\n'
    );
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("preview");
    if (events[0].type === "preview") {
      expect(events[0].data.turn_id).toBe("t");
      expect(events[0].data.queries[0].sql).toBe("SELECT 1");
    }
  });

  it("keeps index/sql/error on result and index on error events", () => {
    const events = parseSSEText(
      'event: result\ndata: {"index":1,"sql":"SELECT 2","columns":[],"rows":[],"row_count":0,"truncated":false,"error":"boom"}\n\n' +
        'event: error\ndata: {"message":"m","code":"BLOCKED_BY_EXPLAIN","index":2}\n\n'
    );
    expect(events[0]).toMatchObject({ type: "result", data: { index: 1, sql: "SELECT 2", error: "boom" } });
    expect(events[1]).toMatchObject({ type: "error", data: { code: "BLOCKED_BY_EXPLAIN", index: 2 } });
  });
});
