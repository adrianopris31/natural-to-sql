import {
  SSEEvent,
  TurnStatus,
  SSEResultData,
  SSEPreviewData,
  SSERefusedData,
  TurnQuery,
  SSEDoneData,
  SSEClarificationData,
  SSEErrorData,
} from "./types";

/**
 * Parses raw SSE data string based on event type into a strongly-typed SSEEvent.
 * Returns null if data is invalid or unrecognized.
 */
export function parseSSEData(eventType: string, rawData: string): SSEEvent | null {
  const type = eventType.trim();

  let parsedJson: unknown = null;
  let isJson = false;
  try {
    parsedJson = JSON.parse(rawData);
    isJson = true;
  } catch {
    isJson = false;
  }

  switch (type) {
    case "status": {
      const statusVal = isJson && typeof parsedJson === "string" ? parsedJson : rawData.trim();
      return { type: "status", data: statusVal as TurnStatus };
    }
    case "sql": {
      const sqlVal = isJson && typeof parsedJson === "string" ? parsedJson : rawData;
      return { type: "sql", data: sqlVal };
    }
    case "result": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const resultData: SSEResultData = {
          columns: Array.isArray(obj.columns)
            ? (obj.columns.map((c) => String(c)))
            : [],
          rows: Array.isArray(obj.rows)
            ? (obj.rows as (string | number | boolean | null)[][])
            : [],
          row_count: typeof obj.row_count === "number" ? obj.row_count : 0,
          truncated: Boolean(obj.truncated),
          ...(typeof obj.index === "number" ? { index: obj.index } : {}),
          ...(typeof obj.sql === "string" ? { sql: obj.sql } : {}),
          ...(typeof obj.error === "string" ? { error: obj.error } : {}),
        };
        return { type: "result", data: resultData };
      }
      return null;
    }
    case "preview": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const previewData: SSEPreviewData = {
          conversation_id: String(obj.conversation_id ?? ""),
          turn_id: String(obj.turn_id ?? ""),
          queries: Array.isArray(obj.queries) ? (obj.queries as TurnQuery[]) : [],
        };
        return { type: "preview", data: previewData };
      }
      return null;
    }
    case "refused": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const refusedData: SSERefusedData = {
          conversation_id: String(obj.conversation_id ?? ""),
          turn_id: String(obj.turn_id ?? ""),
          message: String(obj.message ?? ""),
        };
        return { type: "refused", data: refusedData };
      }
      return { type: "refused", data: { conversation_id: "", turn_id: "", message: rawData } };
    }
    case "answer_delta": {
      const deltaVal = isJson && typeof parsedJson === "string" ? parsedJson : rawData;
      return { type: "answer_delta", data: deltaVal };
    }
    case "done": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const doneData: SSEDoneData = {
          conversation_id: String(obj.conversation_id ?? ""),
          turn_id: String(obj.turn_id ?? ""),
          timings:
            typeof obj.timings === "object" && obj.timings !== null
              ? (obj.timings as Record<string, number>)
              : undefined,
        };
        return { type: "done", data: doneData };
      }
      return {
        type: "done",
        data: { conversation_id: "", turn_id: "" },
      };
    }
    case "clarification": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const clarData: SSEClarificationData = {
          question: String(obj.question ?? rawData),
        };
        return { type: "clarification", data: clarData };
      }
      return {
        type: "clarification",
        data: { question: rawData },
      };
    }
    case "error": {
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        const errData: SSEErrorData = {
          message: String(obj.message ?? rawData),
          code: typeof obj.code === "string" ? obj.code : undefined,
          ...(typeof obj.index === "number" ? { index: obj.index } : {}),
        };
        return { type: "error", data: errData };
      }
      return {
        type: "error",
        data: { message: rawData },
      };
    }
    default: {
      // If eventType is empty or "message", check if rawData is a JSON event object with { type, data }
      if (isJson && typeof parsedJson === "object" && parsedJson !== null) {
        const obj = parsedJson as Record<string, unknown>;
        if (typeof obj.type === "string" && "data" in obj) {
          const innerData = typeof obj.data === "string" ? obj.data : JSON.stringify(obj.data);
          return parseSSEData(obj.type, innerData);
        }
      }
      return null;
    }
  }
}

/**
 * Parses raw SSE text into an array of SSEEvent items.
 */
export function parseSSEText(text: string): SSEEvent[] {
  const events: SSEEvent[] = [];
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");

  let currentEventType = "";
  let currentDataLines: string[] = [];

  const dispatchCurrentEvent = () => {
    if (currentDataLines.length > 0 || currentEventType) {
      const rawData = currentDataLines.join("\n");
      const ev = parseSSEData(currentEventType || "message", rawData);
      if (ev) events.push(ev);
      currentEventType = "";
      currentDataLines = [];
    }
  };

  for (const line of lines) {
    if (line.startsWith(":")) {
      continue;
    }
    if (line === "") {
      dispatchCurrentEvent();
    } else {
      const colonIdx = line.indexOf(":");
      if (colonIdx !== -1) {
        const field = line.slice(0, colonIdx);
        let val = line.slice(colonIdx + 1);
        if (val.startsWith(" ")) val = val.slice(1);

        if (field === "event") {
          currentEventType = val;
        } else if (field === "data") {
          currentDataLines.push(val);
        }
      }
    }
  }
  dispatchCurrentEvent();

  return events;
}

/**
 * Asynchronously parses a ReadableStream of Uint8Array chunks into SSEEvent items.
 * Robust against arbitrary chunk boundaries, multi-line data, multi-byte UTF-8,
 * empty heartbeats, and abort signals.
 */
export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal
): AsyncGenerator<SSEEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8");

  let buffer = "";
  let currentEventType = "";
  let currentDataLines: string[] = [];

  const dispatchCurrentEvent = (): SSEEvent | null => {
    if (currentDataLines.length === 0 && !currentEventType) {
      return null;
    }
    const rawData = currentDataLines.join("\n");
    const event = parseSSEData(currentEventType || "message", rawData);
    currentEventType = "";
    currentDataLines = [];
    return event;
  };

  try {
    while (true) {
      if (signal?.aborted) {
        break;
      }

      const { done, value } = await reader.read();

      if (done) {
        buffer += decoder.decode();
        if (buffer.length > 0) {
          const lines = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
          for (const line of lines) {
            if (line.startsWith(":")) {
              continue;
            }
            if (line === "") {
              const ev = dispatchCurrentEvent();
              if (ev) yield ev;
            } else if (line.includes(":")) {
              const colonIdx = line.indexOf(":");
              const field = line.slice(0, colonIdx);
              let val = line.slice(colonIdx + 1);
              if (val.startsWith(" ")) val = val.slice(1);

              if (field === "event") {
                currentEventType = val;
              } else if (field === "data") {
                currentDataLines.push(val);
              }
            }
          }
          const finalEv = dispatchCurrentEvent();
          if (finalEv) yield finalEv;
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      let sliceEnd = buffer.length;
      if (buffer.endsWith("\r")) {
        sliceEnd -= 1;
      }

      const textToProcess = buffer.slice(0, sliceEnd);
      const lastNewlineIdx = Math.max(textToProcess.lastIndexOf("\n"), textToProcess.lastIndexOf("\r"));

      if (lastNewlineIdx === -1) {
        continue;
      }

      const readyChunk = textToProcess.slice(0, lastNewlineIdx + 1);
      buffer = textToProcess.slice(lastNewlineIdx + 1) + buffer.slice(sliceEnd);

      const normalized = readyChunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      const lines = normalized.split("\n");
      for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i];
        if (line.startsWith(":")) {
          continue;
        }
        if (line === "") {
          const ev = dispatchCurrentEvent();
          if (ev) yield ev;
        } else {
          const colonIdx = line.indexOf(":");
          if (colonIdx !== -1) {
            const field = line.slice(0, colonIdx);
            let val = line.slice(colonIdx + 1);
            if (val.startsWith(" ")) val = val.slice(1);

            if (field === "event") {
              currentEventType = val;
            } else if (field === "data") {
              currentDataLines.push(val);
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Consumes a ReadableStream using parseSSEStream and invokes onEvent for each parsed event.
 */
export async function consumeSSEStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  for await (const event of parseSSEStream(stream, signal)) {
    if (signal?.aborted) {
      break;
    }
    onEvent(event);
  }
}
