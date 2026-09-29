/**
 * API Contract types mirroring PLAN.md §2 and §5 exactly.
 * No `any` allowed — strict typing with `unknown`.
 */

export type TurnStatus =
  | "generating_sql"
  | "validating"
  | "executing"
  | "repairing"
  | "answering"
  | "done"
  | "clarification"
  | "error";

export interface SSEResultData {
  columns: string[];
  rows: (string | number | boolean | null)[][];
  row_count: number;
  truncated: boolean;
}

export interface SSEDoneData {
  conversation_id: string;
  turn_id: string;
  timings?: Record<string, number>;
}

export interface SSEClarificationData {
  question: string;
}

export interface SSEErrorData {
  message: string;
  code?: string;
}

export type SSEEvent =
  | { type: "status"; data: TurnStatus }
  | { type: "sql"; data: string }
  | { type: "result"; data: SSEResultData }
  | { type: "answer_delta"; data: string }
  | { type: "done"; data: SSEDoneData }
  | { type: "clarification"; data: SSEClarificationData }
  | { type: "error"; data: SSEErrorData };

export interface ChatRequest {
  conversation_id?: string;
  message: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
}

export interface Turn {
  id: string;
  question: string;
  sql: string | null;
  columns: string[] | null;
  rows: (string | number | boolean | null)[][] | null;
  row_count: number | null;
  truncated: boolean | null;
  answer: string | null;
  status: TurnStatus;
  error: string | null;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  turns: Turn[];
}

export interface SchemaColumn {
  name: string;
  type: string;
  is_pk?: boolean;
  is_fk?: boolean;
  fk_target?: string;
  sample_values?: string[];
  comment?: string;
}

export interface SchemaTable {
  name: string;
  comment?: string;
  columns: SchemaColumn[];
}

export interface SchemaResponse {
  tables: SchemaTable[];
}

export type CompactSchema = SchemaResponse;
export type CompactTable = SchemaTable;
export type CompactColumn = SchemaColumn;

export interface SchemaRefreshResponse {
  tables: number;
}

export interface HealthResponse {
  db: "ok" | "error";
  ollama: "ok" | "error";
  model: string;
  db_version: string;
}
