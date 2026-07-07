// Typed client for the NexusIQ FastAPI backend.
// Nothing in the UI invents data: everything rendered comes from these
// payloads, and callers must handle the offline/error paths honestly.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Optional public demo key (rate-limited server-side). Never a real secret.
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) h["X-API-Key"] = API_KEY;
  return h;
}

/* ---------- payload types (mirror api/models/schemas.py) ---------- */

export type SqlEvidence = {
  success: boolean;
  query: string | null;
  row_count: number | null;
  result_preview: Record<string, unknown>[];
  answer_mode: string | null;
  repair_attempted: boolean;
  error: string | null;
  time_s: number | null;
};

export type DocumentEvidence = {
  filename: string | null;
  page: string | number | null;
  relevance: number | null;
  cited_in_answer: boolean;
  snippet: string | null;
};

export type WebEvidence = {
  source: string | null;
  category: string | null;
  products: number | null;
  sample_data: boolean;
};

export type Analysis = {
  kind: string;
  unit: string;
  period_label: string;
  breakdowns: { dimension: string; rows: { label: string; value: number; share: number }[] }[];
  trend: { current: number; previous: number; previous_label: string; delta_pct: number } | null;
  notes: string[];
  method: string;
};

export type Usage = {
  llm_calls: number | null;
  avoided_llm_calls: number | null;
  avoided_estimated_tokens: number | null;
  estimated_tokens: number | null;
  actual_tokens: number | null;
  answer_mode: string | null;
};

export type AnswerPayload = {
  answer: string;
  confidence: "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN";
  confidence_reason: string | null;
  route: string;
  evidence: {
    sql: SqlEvidence | null;
    documents: DocumentEvidence[];
    web: WebEvidence[];
  };
  analysis?: Analysis | null;
  usage: Usage | null;
  query_time_s: number | null;
  cached: boolean;
  trace_id: string | null;
  done?: boolean;
};

export type StreamEvent = {
  step: string; // received | processing | sql | rag | web | answer | error
  status: string;
  data: Record<string, unknown>;
  elapsed_ms: number;
};

export type Meta = {
  database: { table: string; transactions: number | null; status: string };
  documents: {
    pdf_count: number | null;
    business_file_count?: number;
    business_files_by_format?: Record<string, number>;
    total_documents?: number | null;
    chunks: number | null;
    categories: Record<string, number>;
    status: string;
  };
  web: { retailers: number; categories: number; sources: Record<string, string[]> };
  business_context: { glossary_entries: number | null };
};

export type TraceSpan = {
  name: string;
  started_at: string | null;
  duration_s: number | null;
  status: string | null;
  metadata: Record<string, unknown>;
};

export type Trace = {
  trace_id: string;
  duration_s: number | null;
  spans: TraceSpan[];
  final: {
    source_type: string | null;
    routing_model: string | null;
    from_cache: boolean | null;
    validation: { confidence: string | null; confidence_reason: string | null } | null;
    llm_usage: {
      successful_calls: number | null;
      avoided_calls: number | null;
      estimated_tokens: number | null;
      avoided_estimated_tokens: number | null;
    } | null;
  };
};

/* ---------- calls ---------- */

export async function fetchMeta(): Promise<Meta> {
  const res = await fetch(`${API_BASE}/api/v1/meta`, { headers: headers() });
  if (!res.ok) throw new Error(`meta ${res.status}`);
  return res.json();
}

export async function fetchTrace(traceId: string): Promise<Trace> {
  const res = await fetch(`${API_BASE}/api/v1/trace/${traceId}`, { headers: headers() });
  if (!res.ok) throw new Error(`trace ${res.status}`);
  return res.json();
}

/**
 * POST /api/v1/query/stream and yield each SSE event.
 * The final event has step="answer" (payload in data) or step="error".
 */
export async function* queryStream(
  question: string,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_BASE}/api/v1/query/stream`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        yield JSON.parse(line.slice("data: ".length)) as StreamEvent;
      } catch {
        // skip malformed frame
      }
    }
  }
}

/* ---------- context map (GET /api/v1/context) ---------- */

export type GlossaryTerm = {
  id: string;
  term: string;
  definition: string;
  aliases: string[];
  provenance: string;
};

export type SchemaTable = {
  name: string;
  columns: { name: string; type: string }[];
  provenance: string;
};

export type ContextDocument = {
  id: string;
  filename: string | null;
  category: string | null;
  format: string;
  provenance: string;
};

export type ContextRelationship = {
  from: string;
  to: string;
  type: string;
  provenance: string;
};

export type BusinessEntity = { id: string; provenance: string };

export type ContextMap = {
  glossary: GlossaryTerm[];
  schema: { available: boolean; tables: SchemaTable[]; error?: string };
  documents: ContextDocument[];
  entities: Record<string, BusinessEntity[]>;
  staleness: { filename: string; stale: boolean; reason: string; provenance: string }[];
  trust_model: { class: string; rank: number; meaning: string }[];
  relationships: ContextRelationship[];
  stats: {
    glossary_terms: number;
    documents: number;
    document_categories: Record<string, number>;
    document_formats: Record<string, number>;
    tables: number;
    business_entities: number;
    stale_documents: number;
    relationships: number;
  };
  honesty: { sources: string[]; note: string };
};

export async function fetchContextMap(): Promise<ContextMap> {
  const res = await fetch(`${API_BASE}/api/v1/context`, { headers: headers() });
  if (!res.ok) throw new Error(`context ${res.status}`);
  return res.json();
}

/* ---------- learning loop (GET /api/v1/learning) ---------- */

export type FailureRecord = {
  failure_id: string;
  detected_at: string;
  source: string;
  failure_kind: string;
  question: string;
  evidence: Record<string, unknown>;
  severity: string;
  trace_id: string | null;
  suggested_repair: string | null;
};

export type RepairProposal = {
  proposal_id: string;
  created_at: string;
  title: string;
  description: string;
  repair_type: string;
  failure_ids: string[];
  status: string;
  eval_before: Record<string, unknown> | null;
  eval_after: Record<string, unknown> | null;
  human_approved: boolean;
  approved_by: string | null;
  history: { at: string; from: string; to: string; note: string }[];
};

export type LearningLoop = {
  governance: { classification: string; verification: string; adoption: string };
  stats: {
    failure_records: number;
    failures_by_kind: Record<string, number>;
    repair_proposals: number;
    proposals_by_status: Record<string, number>;
  };
  failure_records: FailureRecord[];
  repair_queue: RepairProposal[];
};

export async function fetchLearningLoop(): Promise<LearningLoop> {
  const res = await fetch(`${API_BASE}/api/v1/learning`, { headers: headers() });
  if (!res.ok) throw new Error(`learning ${res.status}`);
  return res.json();
}

export type RecallMatch = {
  failure_id: string;
  failure_kind: string;
  question: string;
  shared_terms: string[];
  overlap: number;
  repairs: { proposal_id: string; title: string; status: string; human_approved: boolean }[];
};

export type RecallResult = { question: string; matches: RecallMatch[]; note: string };

export async function fetchRecall(q: string): Promise<RecallResult> {
  const res = await fetch(`${API_BASE}/api/v1/learning/recall?q=${encodeURIComponent(q)}`, { headers: headers() });
  if (!res.ok) throw new Error(`recall ${res.status}`);
  return res.json();
}
