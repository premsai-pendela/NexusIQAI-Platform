"use client";
import { useCallback, useEffect, useState } from "react";
import PlatformShell from "@/components/PlatformShell";
import {
  FeedbackItem,
  HealthFinding,
  HealthReport,
  TraceSummary,
  adminEmployees,
  adminFeedback,
  adminTraces,
  fetchTraceDetail,
  runHealthCheck,
  setFeedbackStatus,
} from "@/lib/platform";

/* Admin/CEO review desk — same company only. Left: employee feedback with
   status triage. Right: employee query traces filterable by employee and
   date, expandable to the full access/routing/evidence record. */

type TraceDetail = Awaited<ReturnType<typeof fetchTraceDetail>>;
type FeedbackTab = "new-reviews" | "new-complaints" | "reviewed" | "resolved";

function StatusChip({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    new: { bg: "#FCF3DC", fg: "#8A5B10" },
    reviewed: { bg: "var(--chip-neutral-bg)", fg: "var(--chip-neutral-text)" },
    resolved: { bg: "var(--success-bg)", fg: "var(--success-text)" },
    allowed: { bg: "var(--success-bg)", fg: "var(--success-text)" },
    denied: { bg: "#FCF3DC", fg: "#8A5B10" },
  };
  const s = map[status] || map.reviewed;
  return <span className="chip" style={{ background: s.bg, color: s.fg }}>{status}</span>;
}

function TraceCard({ detail, onClose }: { detail: TraceDetail; onClose: () => void }) {
  const p = detail.payload as Record<string, unknown>;
  const policy = (p.access_policy || {}) as { allowed_tables?: string[]; allowed_departments?: string[] };
  const citations = (p.citations || []) as { filename?: string; department?: string }[];
  return (
    <div className="card" style={{ background: "var(--surface-card)", padding: "14px 16px", marginTop: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--mono-accent)" }}>{detail.id}</span>
        <StatusChip status={detail.access_decision} />
        <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "var(--muted-soft)", fontSize: 13 }}>×</button>
      </div>
      <div style={{ fontSize: 13, color: "var(--ink)", margin: "8px 0 2px", fontWeight: 500 }}>{detail.question}</div>
      {p.followup_rewritten === true && (
        <div className="mono" style={{ fontSize: 10, color: "var(--mono-accent)" }}>↳ resolved as: {String(p.resolved_question)}</div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px", fontSize: 11.5, color: "var(--body)", marginTop: 10 }}>
        <span className="label">EMPLOYEE</span><span>{detail.employee} · {detail.role}</span>
        <span className="label">WHEN</span><span>{new Date(detail.ts).toLocaleString()}</span>
        <span className="label">ROUTE</span><span className="mono" style={{ fontSize: 10.5 }}>{String(p.route ?? "—")}</span>
        <span className="label">MEMORY</span><span>{String(p.memory_turns_used ?? 0)} prior turns in session</span>
        <span className="label">TABLES</span><span className="mono" style={{ fontSize: 10.5 }}>{policy.allowed_tables?.join(", ") || "none"}</span>
        <span className="label">DOCS</span><span className="mono" style={{ fontSize: 10.5 }}>{policy.allowed_departments?.join(", ") || "none"}</span>
        {p.denied_reason ? (<><span className="label">DENIED</span><span style={{ color: "#8A5B10" }}>{String(p.denied_reason)}</span></>) : null}
        {p.chart_generated === true ? (<><span className="label">CHART</span><span>{String(p.chart_type)} chart generated</span></>) : null}
      </div>
      {typeof p.sql === "string" && p.sql && (
        <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 10, background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 6, padding: "8px 9px", lineHeight: 1.5, whiteSpace: "pre-wrap", marginTop: 10 }}>
          {p.sql}
        </div>
      )}
      {citations.length > 0 && (
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {citations.map((c, i) => (
            <span key={i} className="chip chip-neutral">{c.filename} · {c.department}</span>
          ))}
        </div>
      )}
    </div>
  );
}

const SEV_STYLE: Record<string, { bg: string; fg: string }> = {
  high: { bg: "#F9E3E3", fg: "#A32D2D" },
  medium: { bg: "#FCF3DC", fg: "#8A5B10" },
  low: { bg: "var(--chip-neutral-bg)", fg: "var(--chip-neutral-text)" },
  info: { bg: "var(--success-bg)", fg: "var(--success-text)" },
};

function FindingRow({ f, onOpenTrace }: { f: HealthFinding; onOpenTrace: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const sev = SEV_STYLE[f.severity] || SEV_STYLE.low;
  return (
    <div className="card" style={{ background: "var(--surface-card)", padding: "9px 12px" }}>
      <div onClick={() => setOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
        <span className="chip" style={{ background: sev.bg, color: sev.fg, flex: "none" }}>{f.severity}</span>
        <span className="chip chip-neutral" style={{ flex: "none" }}>{f.classification.replace(/_/g, " ")}</span>
        <span style={{ fontSize: 12, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: open ? "normal" : "nowrap" }}>
          {f.summary}
        </span>
        <span style={{ color: "var(--muted-soft)", fontSize: 11, flex: "none" }}>{open ? "−" : "＋"}</span>
      </div>
      {open && (
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--body)", lineHeight: 1.6 }}>
          <div><span className="label">RECOMMENDATION </span>{f.recommendation}</div>
          {f.suggested_eval && (
            <div style={{ marginTop: 4 }}>
              <span className="label">SUGGESTED EVAL </span>
              <span className="mono" style={{ fontSize: 10.5 }}>
                “{f.suggested_eval.question}” → expect {f.suggested_eval.expect}
              </span>
            </div>
          )}
          {f.evidence.length > 0 && (
            <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {f.evidence.slice(0, 6).map((id) => (
                id.startsWith("tr_") || id.startsWith("gen_") ? (
                  <button key={id} onClick={() => onOpenTrace(id)}
                    style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontFamily: "var(--font-mono), monospace", fontSize: 9.5, color: "var(--accent)" }}>
                    {id}
                  </button>
                ) : (
                  <span key={id} className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)" }}>{id}</span>
                )
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HealthCheckPanel({ onOpenTrace }: { onOpenTrace: (id: string) => void }) {
  const [report, setReport] = useState<HealthReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [days, setDays] = useState(30);
  const [aiSummary, setAiSummary] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setReport(await runHealthCheck(days, aiSummary));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Health check failed");
    } finally {
      setBusy(false);
    }
  };

  const actionable = (report?.findings || []).filter((f) => f.severity === "high" || f.severity === "medium");
  const good = (report?.findings || []).filter((f) => f.severity === "info");
  const shown = showAll ? (report?.findings || []) : actionable.slice(0, 12);

  return (
    <div className="card" style={{ background: "var(--surface-soft)", padding: "14px 16px", marginBottom: 22 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 500, color: "var(--ink)" }}>Analyst Health Check</div>
          <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
            Analyzes your company&apos;s traces and feedback, then recommends what to fix — routing, SQL/RAG, charts, access policy, data gaps, or provider ops.
          </div>
        </div>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
            style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-card)", fontSize: 11.5, color: "var(--ink)", fontFamily: "var(--font-sans), sans-serif" }}>
            <option value={7}>last 7 days</option>
            <option value={30}>last 30 days</option>
            <option value={90}>last 90 days</option>
          </select>
          <label style={{ fontSize: 11, color: "var(--muted)", display: "flex", gap: 4, alignItems: "center", cursor: "pointer" }}>
            <input type="checkbox" checked={aiSummary} onChange={(e) => setAiSummary(e.target.checked)} />
            AI summary
          </label>
          <button className="btn-primary" onClick={run} disabled={busy} style={{ fontSize: 12, padding: "7px 14px", opacity: busy ? 0.6 : 1 }}>
            {busy ? "Analyzing…" : report ? "Run again" : "Run health check"}
          </button>
        </span>
      </div>
      {err && <div style={{ color: "#A32D2D", fontSize: 12, marginTop: 10 }}>{err}</div>}

      {report && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.6 }}>{report.summary}</div>
          {report.llm_summary && (
            <div style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.65, marginTop: 8, borderLeft: "2px solid var(--hairline-strong)", paddingLeft: 10 }}>
              {report.llm_summary}
              <div className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", marginTop: 3 }}>
                AI executive summary · {report.llm_summary_status}
              </div>
            </div>
          )}
          {report.llm_summary_status === "providers_unavailable" && (
            <div className="mono" style={{ fontSize: 10, color: "var(--muted-soft)", marginTop: 6 }}>
              AI summary unavailable (providers exhausted) — deterministic analysis above is complete.
            </div>
          )}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0" }}>
            {(["traces", "employees_active", "refusals", "clarifications", "degraded", "feedback"] as const).map((k) => (
              <span key={k} className="chip chip-neutral">
                {String(report.stats[k] ?? 0)} {k.replace(/_/g, " ")}
              </span>
            ))}
            <span className="chip" style={{ background: "#F9E3E3", color: "#A32D2D" }}>
              {actionable.length} to fix
            </span>
            <span className="chip" style={{ background: "var(--success-bg)", color: "var(--success-text)" }}>
              {good.length} working as designed
            </span>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {shown.map((f, i) => <FindingRow key={i} f={f} onOpenTrace={onOpenTrace} />)}
          </div>
          {report.findings.length > shown.length && (
            <button onClick={() => setShowAll(true)}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 8, fontFamily: "var(--font-mono), monospace", fontSize: 10.5, color: "var(--accent)" }}>
              show all {report.findings.length} findings (including correct-behavior signals)
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function AdminReviewPage() {
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
  const [feedbackTab, setFeedbackTab] = useState<FeedbackTab>("new-reviews");
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [employees, setEmployees] = useState<{ email: string; name: string; role: string }[]>([]);
  const [empFilter, setEmpFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [openTrace, setOpenTrace] = useState<TraceDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadFeedback = useCallback(
    () => adminFeedback().then((r) => setFeedback(r.feedback)).catch((e) => setErr(e.message)),
    []);
  const loadTraces = useCallback(() => {
    adminTraces({
      employee: empFilter || undefined,
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    }).then((r) => setTraces(r.traces)).catch((e) => setErr(e.message));
  }, [empFilter, dateFrom, dateTo]);

  useEffect(() => { loadFeedback(); adminEmployees().then((r) => setEmployees(r.employees)).catch(() => {}); }, [loadFeedback]);
  useEffect(() => { loadTraces(); }, [loadTraces]);

  const triage = async (id: string, status: string) => {
    await setFeedbackStatus(id, status).catch((e) => setErr(e.message));
    loadFeedback();
  };

  const openTraceById = (id: string) =>
    fetchTraceDetail(id).then(setOpenTrace).catch((e) => setErr(e.message));

  const isReview = (f: FeedbackItem) => f.category === "wrong-answer";
  const visibleFeedback = feedback.filter((f) => {
    if (feedbackTab === "new-reviews") return f.status === "new" && isReview(f);
    if (feedbackTab === "new-complaints") return f.status === "new" && !isReview(f);
    return f.status === feedbackTab;
  });
  const tabCounts: Record<FeedbackTab, number> = {
    "new-reviews": feedback.filter((f) => f.status === "new" && isReview(f)).length,
    "new-complaints": feedback.filter((f) => f.status === "new" && !isReview(f)).length,
    reviewed: feedback.filter((f) => f.status === "reviewed").length,
    resolved: feedback.filter((f) => f.status === "resolved").length,
  };
  const tabs: { id: FeedbackTab; label: string }[] = [
    { id: "new-reviews", label: "New reviews" },
    { id: "new-complaints", label: "New complaints" },
    { id: "reviewed", label: "Reviewed" },
    { id: "resolved", label: "Resolved" },
  ];

  return (
    <PlatformShell
      botGreeting={(p) =>
        `This is the ${p.company.name} review desk. You see feedback and query traces for your company's employees only — filter by employee or date, and open any trace to replay the access decision.`}
      botOnClick={() =>
        "Denied traces are worth a look: they show what employees are trying to reach. An access-request pattern here is how you'd decide to widen a role's policy."}
    >
      {(profile) => (
        <div style={{ padding: "26px 0 80px" }}>
          <h1 className="serif" style={{ fontSize: 26, margin: "0 0 4px" }}>Review — {profile.company.name}</h1>
          <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 20px" }}>
            Employee feedback and query traces for your company only. Other companies&apos; data is never visible here.
          </p>
          {err && <div style={{ color: "#A32D2D", fontSize: 12.5, marginBottom: 12 }}>{err}</div>}

          <HealthCheckPanel onOpenTrace={openTraceById} />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 24, alignItems: "start" }}>
            {/* Feedback queue */}
            <div>
              <div className="label" style={{ marginBottom: 8 }}>EMPLOYEE FEEDBACK · {feedback.length}</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 6, marginBottom: 10 }}>
                {tabs.map((tab) => (
                  <button key={tab.id} onClick={() => setFeedbackTab(tab.id)}
                    style={{
                      border: "1px solid var(--hairline)",
                      borderRadius: 8,
                      padding: "7px 9px",
                      background: feedbackTab === tab.id ? "var(--accent-tint)" : "var(--surface-soft)",
                      color: feedbackTab === tab.id ? "var(--accent)" : "var(--muted)",
                      cursor: "pointer",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: 11.5,
                    }}>
                    <span>{tab.label}</span>
                    <span className="mono" style={{ fontSize: 10 }}>{tabCounts[tab.id]}</span>
                  </button>
                ))}
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {visibleFeedback.length === 0 && <div style={{ fontSize: 12.5, color: "var(--muted)" }}>No items in this queue.</div>}
                {visibleFeedback.map((f) => (
                  <div key={f.id} className="card" style={{ background: "var(--surface-card)", padding: "11px 13px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                      <span className="chip chip-neutral">{f.category}</span>
                      <StatusChip status={f.status} />
                      <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", marginLeft: "auto" }}>
                        {new Date(f.ts).toLocaleDateString()} {new Date(f.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--body)", margin: "7px 0 5px", lineHeight: 1.55 }}>{f.message}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span className="mono" style={{ fontSize: 10, color: "var(--mono-accent)" }}>{f.employee} · {f.role}</span>
                      {f.trace_id && (
                        <button onClick={() => openTraceById(f.trace_id!)}
                          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontFamily: "var(--font-mono), monospace", fontSize: 10, color: "var(--accent)" }}>
                          open trace {f.trace_id}
                        </button>
                      )}
                      <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                        {f.status === "reviewed" && (
                          <button onClick={() => triage(f.id, "new")} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 10.5, color: "var(--muted)", padding: 0 }}>mark new</button>
                        )}
                        {f.status !== "reviewed" && f.status !== "resolved" && (
                          <button onClick={() => triage(f.id, "reviewed")} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 10.5, color: "var(--muted)", padding: 0 }}>mark reviewed</button>
                        )}
                        {f.status !== "resolved" && (
                          <button onClick={() => triage(f.id, "resolved")} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 10.5, color: "var(--success-text)", padding: 0 }}>resolve</button>
                        )}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Trace explorer */}
            <div>
              <div className="label" style={{ marginBottom: 8 }}>EMPLOYEE QUERY TRACES · {traces.length}</div>
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                <select value={empFilter} onChange={(e) => setEmpFilter(e.target.value)}
                  style={{ padding: "7px 9px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 12, color: "var(--ink)", fontFamily: "var(--font-sans), sans-serif" }}>
                  <option value="">All employees</option>
                  {employees.map((e) => <option key={e.email} value={e.email}>{e.name} ({e.role})</option>)}
                </select>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  style={{ padding: "6px 9px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 12, color: "var(--ink)", fontFamily: "var(--font-mono), monospace" }} />
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  style={{ padding: "6px 9px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 12, color: "var(--ink)", fontFamily: "var(--font-mono), monospace" }} />
              </div>

              <div style={{ display: "grid", gap: 6 }}>
                {traces.length === 0 && <div style={{ fontSize: 12.5, color: "var(--muted)" }}>No traces match these filters.</div>}
                {traces.map((t) => (
                  <button key={t.id} onClick={() => openTraceById(t.id)}
                    className="card"
                    style={{ background: "var(--surface-card)", padding: "9px 12px", display: "flex", alignItems: "center", gap: 9, cursor: "pointer", border: "0.5px solid var(--hairline)", textAlign: "left", width: "100%" }}>
                    <StatusChip status={t.access_decision} />
                    <span style={{ fontSize: 12, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.question}</span>
                    <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", flex: "none" }}>
                      {t.employee.split("@")[0]} · {new Date(t.ts).toLocaleDateString()} {new Date(t.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </button>
                ))}
              </div>

              {openTrace && <TraceCard detail={openTrace} onClose={() => setOpenTrace(null)} />}
            </div>
          </div>
        </div>
      )}
    </PlatformShell>
  );
}
