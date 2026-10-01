/**
 * API Contract types mirroring PLAN.md §2 and §5 exactly.
 * No `any` allowed — strict typing with `unknown`.
 */

export type TurnKind = "sql" | "docs";

export interface DocsSource {
  id: string;
  source_type: string;
  title: string;
  url: string;
  score: number;
}

export interface DocsAnswerPayload {
  answer: string;
  sources: DocsSource[];
  refused: boolean;
  model: string;
}

export type TurnStatus =
  | "generating_sql"
  | "searching_docs"
  | "validating"
  | "explaining"
  | "awaiting_approval"
  | "cancelled"
  | "refused"
  | "executing"
  | "repairing"
  | "answering"
  | "done"
  | "clarification"
  | "error";

export type Cell = string | number | boolean | null;

export interface ExplainTableAccess {
  table: string;
  access_type: string;
  key: string | null;
  rows_examined: number;
  rows_produced: number;
}

/** Summary of MySQL `EXPLAIN FORMAT=JSON` plus the backend's cost-gate decision. */
export interface ExplainSummary {
  cost: number | null;
  estimated_rows: number;
  tables: ExplainTableAccess[];
  warnings: string[];
  blocked: boolean;
  block_reason: string | null;
}

export interface RiskFlag {
  code: string;
  severity: "high" | "medium" | "info";
  message: string;
}

/** Advisory red flags for a previewed query (hard stops are the validator + EXPLAIN gate). */
export interface RiskReport {
  level: "none" | "info" | "medium" | "high";
  flags: RiskFlag[];
}

/** One planned query in a turn: previewed first, results filled in after approval. */
export interface TurnQuery {
  index: number;
  purpose: string;
  sql: string;
  explain: ExplainSummary | null;
  risk?: RiskReport | null;
  columns: string[] | null;
  rows: Cell[][] | null;
  row_count: number | null;
  truncated: boolean | null;
  error: string | null;
}

export interface SSEResultData {
  index?: number;
  sql?: string;
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  error?: string | null;
}

/** A data-changing request the read-only app refused (nothing was run). */
export interface SSERefusedData {
  conversation_id: string;
  turn_id: string;
  message: string;
}

/** One SQL lifecycle event from GET /api/audit. */
export interface AuditEntry {
  id: string;
  created_at: string;
  turn_id: string | null;
  conversation_id: string | null;
  question: string | null;
  stage:
    | "validated"
    | "rejected"
    | "explain_failed"
    | "blocked"
    | "edited"
    | "executed"
    | "execution_failed"
    | "refused"
    | string;
  attempt: number;
  accepted: boolean;
  raw_sql: string | null;
  safe_sql: string | null;
  reason: string | null;
  row_count: number | null;
  elapsed_ms: number | null;
}

export interface SSEPreviewData {
  conversation_id: string;
  turn_id: string;
  queries: TurnQuery[];
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
  /** Set when the error concerns a specific query (e.g. an edited query was rejected). */
  index?: number;
}

export type SSEEvent =
  | { type: "status"; data: TurnStatus }
  | { type: "sql"; data: string }
  | { type: "result"; data: SSEResultData }
  | { type: "preview"; data: SSEPreviewData }
  | { type: "refused"; data: SSERefusedData }
  | { type: "answer_delta"; data: string }
  | { type: "docs_answer"; data: DocsAnswerPayload }
  | { type: "done"; data: SSEDoneData }
  | { type: "clarification"; data: SSEClarificationData }
  | { type: "error"; data: SSEErrorData };

export interface ChatRequest {
  conversation_id?: string;
  message: string;
  mode?: TurnKind;
}

/** Approve a previewed turn; `queries[i]` optionally replaces query i's SQL. */
export interface RunRequest {
  queries?: (string | null)[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  last_kind?: TurnKind;
}

export interface Turn {
  id: string;
  kind?: TurnKind;
  question: string;
  sql: string | null;
  columns: string[] | null;
  rows: (string | number | boolean | null)[][] | null;
  row_count: number | null;
  truncated: boolean | null;
  /** Present for turns created with the preview/approval flow. */
  queries?: TurnQuery[] | null;
  answer: string | null;
  sources?: DocsSource[] | null;
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

export interface KnowledgeBotHealth {
  configured: boolean;
  reachable: boolean;
}

export interface HealthResponse {
  db: "ok" | "error";
  ollama: "ok" | "error";
  model: string;
  db_version: string;
  knowledge_bot?: KnowledgeBotHealth;
}

