"use client";
import { useCallback, useEffect, useState } from "react";
import PlatformShell from "@/components/PlatformShell";
import {
  FeedbackItem,
  TraceSummary,
  adminEmployees,
  adminFeedback,
  adminTraces,
  fetchTraceDetail,
  setFeedbackStatus,
} from "@/lib/platform";

/* Admin/CEO review desk — same company only. Left: employee feedback with
   status triage. Right: employee query traces filterable by employee and
   date, expandable to the full access/routing/evidence record. */

type TraceDetail = Awaited<ReturnType<typeof fetchTraceDetail>>;

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

export default function AdminReviewPage() {
  const [feedback, setFeedback] = useState<FeedbackItem[]>([]);
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

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 24, alignItems: "start" }}>
            {/* Feedback queue */}
            <div>
              <div className="label" style={{ marginBottom: 8 }}>EMPLOYEE FEEDBACK · {feedback.length}</div>
              <div style={{ display: "grid", gap: 8 }}>
                {feedback.length === 0 && <div style={{ fontSize: 12.5, color: "var(--muted)" }}>No feedback yet.</div>}
                {feedback.map((f) => (
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
                        {f.status !== "reviewed" && (
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
