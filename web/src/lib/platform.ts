/* Platform-mode API client. Session token lives in localStorage; every
   request sends it via X-NexusIQ-Session. Company and role are always
   resolved server-side from the token — the client never sends them. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1";

const TOKEN_KEY = "nexusiq_platform_token";
const SESSION_KEY = "nexusiq_platform_session";
const PROFILE_KEY = "nexusiq_platform_profile";

export type Profile = {
  email: string;
  name: string;
  title: string;
  role: string;
  is_admin: boolean;
  company: { slug: string; name: string; industry: string; description: string };
  access: {
    summary: string;
    denied_summary: string;
    tables: string[];
    departments: string[];
    read_only: boolean;
  };
};

export type ChartSpec = {
  type: "kpi" | "bar" | "line" | "table" | "pie";
  title: string;
  x: string | null;
  y: string | null;
  data: Record<string, unknown>[];
  download: { csv: boolean };
};

export type DashboardSpec = {
  company: string;
  role: string;
  kpis: { title: string; value: number | string }[];
  charts: ChartSpec[];
  sql_used: string[];
  note: string;
};

export type PlatformMeta = {
  trace_id: string;
  resolved_question: string;
  followup_rewritten: boolean;
  access_decision: "allowed" | "denied";
  refused: boolean;
  chart: ChartSpec | null;
  dashboard?: DashboardSpec | null;
  role: string;
  company: string;
  route?: string | null;
  llm_skipped?: boolean;
  model_used?: string | null;
  followups?: string[];
  clarification?: { kind: string; question: string; choices: string[] } | null;
  repeat?: {
    options: string[];
    previous: { trace_id: string; ts?: string; answer?: string; route?: string };
  } | null;
  degraded?: boolean;
  previous_trace_id?: string | null;
};

export type PlatformAnswer = {
  answer: string;
  confidence: string;
  confidence_reason?: string | null;
  route: string;
  sources: { type: string; content: string; filename?: string | null }[];
  evidence?: {
    sql?: {
      success: boolean;
      query?: string | null;
      row_count?: number | null;
      result_preview: Record<string, unknown>[];
    } | null;
    documents: {
      filename?: string | null;
      page?: unknown;
      snippet?: string | null;
      cited_in_answer?: boolean;
      relevance?: number | null;
    }[];
  };
  platform: PlatformMeta;
  latency_ms: number;
  request_id: string;
};

export type TraceSummary = {
  id: string;
  employee: string;
  role: string;
  ts: string;
  question: string;
  access_decision: string;
  source?: string;          // "real" | "simulated"
  route?: string | null;
  answer?: string | null;   // short answer text (from the memory turn)
};

export type FeedbackItem = {
  id: string;
  employee: string;
  role: string;
  ts: string;
  category: string;
  message: string;
  page?: string | null;
  trace_id?: string | null;
  status: "new" | "reviewed" | "resolved";
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getProfile(): Profile | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(PROFILE_KEY);
  return raw ? (JSON.parse(raw) as Profile) : null;
}

export function getSessionId(): string {
  let s = localStorage.getItem(SESSION_KEY);
  if (!s) {
    s = `web-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
    localStorage.setItem(SESSION_KEY, s);
  }
  return s;
}

export function setSessionId(sessionId: string) {
  localStorage.setItem(SESSION_KEY, sessionId);
}

export function createSessionId(): string {
  return `web-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(PROFILE_KEY);
  localStorage.removeItem(SESSION_KEY);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-NexusIQ-Session": token } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<Profile> {
  const out = await req<{ token: string; profile: Profile }>("/platform/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem(TOKEN_KEY, out.token);
  localStorage.setItem(PROFILE_KEY, JSON.stringify(out.profile));
  localStorage.setItem(
    SESSION_KEY,
    `web-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`
  );
  return out.profile;
}

export type Workspace = {
  profile: Profile;
  brain: {
    status: string;
    built_at?: string | null;
    changed_files?: string[];
    build_log?: Record<string, unknown>;
  };
  tables: Record<string, { columns: { name: string; type: string }[]; row_count: number }>;
  documents: { file: string; department: string; chunks: number }[];
};

export const fetchWorkspace = () => req<Workspace>("/platform/workspace");

export const platformQuery = (question: string, repeatAction?: string) =>
  req<PlatformAnswer>("/platform/query", {
    method: "POST",
    body: JSON.stringify({
      question,
      session_id: getSessionId(),
      ...(repeatAction ? { repeat_action: repeatAction } : {}),
    }),
  });

export type HealthFinding = {
  kind: string;
  classification: string;
  severity: "high" | "medium" | "low" | "info";
  summary: string;
  recommendation: string;
  evidence: string[];
  suggested_eval?: { question: string; expect: string } | null;
  self_fixable?: boolean;
};

export type HealthReport = {
  report_id?: string;
  company: string;
  window_days: number;
  generated_at: string;
  summary: string;
  stats: Record<string, unknown> & { routes?: Record<string, number> };
  findings: HealthFinding[];
  suggested_evals: { question: string; expect: string }[];
  llm_summary?: string | null;
  llm_summary_status?: string;
};

export const runHealthCheck = (windowDays = 30, llmSummary = false, source = "real") =>
  req<HealthReport>("/platform/admin/health-check", {
    method: "POST",
    body: JSON.stringify({ window_days: windowDays, llm_summary: llmSummary, source }),
  });

// ── Wave 1 trace-review report ─────────────────────────────────────────
export type ReviewTrace = {
  trace_id: string;
  employee: string;
  role: string;
  ts: string;
  question: string;
  answer: string;
  route: string | null;
  access_decision: string | null;
  verdict: string;
  tier: string;
  reason: string;
  expected: string;
  reality: string;
};
export type ReviewEmployee = {
  email: string;
  name: string;
  role: string;
  trace_count: number;
  verdict_counts: Record<string, number>;
  issues: number;
  traces: ReviewTrace[];
};
export type ReviewFix = {
  issue: string;
  severity: string;
  count: number;
  employees: string[];
  example_trace_ids: string[];
  recommendation: string;
};
export type OpenFinding = {
  summary: string;
  severity: string;
  classification: string;
  status: string;
  first_seen: string;
  last_seen: string;
  is_new: boolean;
  trace_id: string | null;
};
export type HealthReviewReport = {
  kind: string;
  company: string;
  company_name: string;
  requested_by: string;
  generated_at: string;
  report_date: string;
  window_days: number;
  incremental: boolean;
  since: string;
  previous_run_at: string | null;
  run_number: number;
  date_from: string;
  date_to: string;
  source: string;
  traces_reviewed: number;
  new_traces_reviewed: number;
  graded: number;
  summary: {
    total_traces: number;
    employees_active: number;
    verdict_counts: Record<string, number>;
    issues: number;
    llm_calls_used: number;
    needs_human_review: number;
    findings_new: number;
    findings_carried: number;
    per_employee: { name: string; role: string; email: string; traces: number; issues: number }[];
  };
  narrative: string;
  employees: ReviewEmployee[];
  fixes_needed: ReviewFix[];
  open_findings: OpenFinding[];
  report_id?: string;
};

export const runHealthReview = (windowDays = 30, source = "real", llmBudget = 25) =>
  req<HealthReviewReport>("/platform/admin/health-review", {
    method: "POST",
    body: JSON.stringify({ window_days: windowDays, source, llm_budget: llmBudget }),
  });

export const submitFeedback = (payload: {
  category: string;
  message: string;
  page?: string;
  trace_id?: string;
}) =>
  req<{ status: string; feedback_id: string }>("/platform/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const adminFeedback = (filters?: { employee?: string; status?: string; category?: string }) => {
  const qs = new URLSearchParams(
    Object.entries(filters || {}).filter(([, v]) => v) as [string, string][]
  ).toString();
  return req<{ feedback: FeedbackItem[] }>(`/platform/admin/feedback${qs ? `?${qs}` : ""}`);
};

export const setFeedbackStatus = (id: string, status: string) =>
  req(`/platform/admin/feedback/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const adminTraces = (filters?: {
  employee?: string;
  date_from?: string;
  date_to?: string;
  source?: string;
}) => {
  const qs = new URLSearchParams(
    Object.entries(filters || {}).filter(([, v]) => v) as [string, string][]
  ).toString();
  return req<{ traces: TraceSummary[] }>(`/platform/admin/traces${qs ? `?${qs}` : ""}`);
};

export const fetchTraceDetail = (id: string) =>
  req<{
    id: string;
    employee: string;
    role: string;
    ts: string;
    question: string;
    access_decision: string;
    answer?: string | null;
    source?: string;
    payload: Record<string, unknown>;
  }>(`/platform/traces/${id}`);

export const adminEmployees = () =>
  req<{ employees: { email: string; name: string; role: string; title: string }[] }>(
    "/platform/admin/employees"
  );

export async function exportXlsx(
  title: string,
  rows: Record<string, unknown>[],
  meta?: { question?: string; trace_id?: string }
) {
  const token = getToken();
  const res = await fetch(`${API_BASE}/platform/export/xlsx`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-NexusIQ-Session": token } : {}),
    },
    body: JSON.stringify({ title, rows, ...meta }),
  });
  if (!res.ok) throw new Error(`XLSX export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40)}.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}

export const rebuildBrain = () =>
  req<{ status: string; build_log: Record<string, unknown> }>("/platform/brain/rebuild", {
    method: "POST",
  });
