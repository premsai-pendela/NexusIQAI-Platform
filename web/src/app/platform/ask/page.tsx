"use client";
import { useEffect, useRef, useState, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import PlatformShell from "@/components/PlatformShell";
import ChartView from "@/components/ChartView";
import DashboardView from "@/components/DashboardView";
import {
  PlatformAnswer,
  Profile,
  platformQuery,
  submitFeedback,
} from "@/lib/platform";

/* Ask Analyst — the core product surface. Role-aware conversation with the
   company brain: answers carry SQL, citations, confidence, chart, access
   notes, and the saved trace id. Refusals render as calm access notices. */

function Avatar() {
  return (
    <span style={{ width: 20, height: 20, borderRadius: "50%", background: "var(--mascot)", color: "var(--mascot-face)", fontSize: 11, fontFamily: "var(--font-display), serif", display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
      N
    </span>
  );
}

function Accordion({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: "0.5px solid var(--hairline)", borderRadius: 8, marginTop: 8, background: "var(--surface-soft)", overflow: "hidden" }}>
      <div onClick={() => setOpen((o) => !o)} style={{ padding: "8px 11px", cursor: "pointer", fontSize: 12, color: "var(--ink)", userSelect: "none" }}>
        {open ? "− " : "＋ "}{title}
      </div>
      {open && <div style={{ padding: "0 11px 11px" }}>{children}</div>}
    </div>
  );
}

function Dots() {
  return (
    <span style={{ display: "inline-flex", gap: 3 }}>
      {[0, 0.2, 0.4].map((d, i) => (
        <i key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accent)", display: "inline-block", animation: `nq-blink 1s ${d}s infinite` }} />
      ))}
    </span>
  );
}

const STARTERS: Record<string, string[]> = {
  Admin: [
    "Give me a dashboard",
    "What was total revenue in Q3 2024?",
    "What is our attrition rate by department?",
    "What are the support SLA targets?",
  ],
  CEO: [
    "Give me a dashboard",
    "Show monthly revenue as a line chart",
    "How many overdue invoices do we have?",
    "Average CSAT on resolved tickets?",
  ],
  Analyst: [
    "Give me a dashboard",
    "What was total revenue in Q3 2024?",
    "Top 5 products by revenue as a bar chart",
    "What is the discount policy?",
  ],
  HR: [
    "Give me a dashboard",
    "What is our attrition rate?",
    "How many PTO days do employees get?",
    "Terminations in 2024 by department as a bar chart",
  ],
  Finance: [
    "Give me a dashboard",
    "How many overdue invoices do we have?",
    "Total invoiced amount by month as a line chart",
    "What is the revenue recognition policy?",
  ],
  Support: [
    "Give me a dashboard",
    "Average resolution hours by priority",
    "What are the SLA targets for urgent tickets?",
    "Ticket volume by category as a bar chart",
  ],
  Ops: [
    "Give me a dashboard",
    "Order volume by month as a line chart",
    "What are the incident severity definitions?",
    "Top products by order count",
  ],
};

type Node =
  | { id: number; type: "user"; text: string }
  | { id: number; type: "thinking" }
  | { id: number; type: "answer"; payload: PlatformAnswer }
  | { id: number; type: "error"; message: string };

function AnswerCard({ p, profile, onAsk }: { p: PlatformAnswer; profile: Profile; onAsk: (q: string) => void }) {
  const meta = p.platform;
  const [reported, setReported] = useState(false);
  const refused = meta.refused;
  const sql = p.evidence?.sql;
  const docs = p.evidence?.documents || [];

  const report = async () => {
    try {
      await submitFeedback({
        category: refused ? "access-request" : "wrong-answer",
        message: `Flagged from Ask Analyst: "${meta.resolved_question}"`,
        page: "ask",
        trace_id: meta.trace_id,
      });
      setReported(true);
    } catch { /* non-blocking */ }
  };

  return (
    <div className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px", borderLeft: refused ? "3px solid #C08A2D" : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Avatar />
        <span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
        {refused ? (
          <span className="pill" style={{ marginLeft: "auto", background: "#FCF3DC", color: "#8A5B10" }}>access boundary</span>
        ) : (
          <span className="pill" style={{ marginLeft: "auto" }}>
            {p.confidence && p.confidence !== "UNKNOWN" ? `${p.confidence} confidence` : (p.route || "answered").replace(/_/g, " ")}
          </span>
        )}
      </div>

      {meta.followup_rewritten && (
        <div className="mono" style={{ fontSize: 10, color: "var(--mono-accent)", marginTop: 6 }}>
          ↳ understood as: “{meta.resolved_question}”
        </div>
      )}

      <div className="answer-md" style={{ marginTop: 8 }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{p.answer}</ReactMarkdown>
      </div>

      {refused && (
        <div style={{ marginTop: 10 }}>
          <div className="label" style={{ marginBottom: 6 }}>WITHIN YOUR ACCESS INSTEAD</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {(STARTERS[profile.role] || STARTERS.Analyst).slice(0, 3).map((s) => (
              <button key={s} onClick={() => onAsk(s)}
                style={{ fontFamily: "var(--font-sans), sans-serif", fontSize: 11.5, padding: "6px 12px", borderRadius: 16, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", color: "var(--muted)", cursor: "pointer" }}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {meta.dashboard && !refused && <DashboardView spec={meta.dashboard} />}
      {meta.chart && !refused && <ChartView spec={meta.chart} />}

      {!refused && (sql?.query || docs.length > 0) && (
        <Accordion title={`Evidence · ${(sql?.query ? 1 : 0) + docs.length} source${(sql?.query ? 1 : 0) + docs.length === 1 ? "" : "s"}`}>
          {sql?.query && (
            <>
              <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 10, background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 6, padding: "8px 9px", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                {sql.query}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--muted)", margin: "5px 0" }}>
                → {sql.row_count ?? "?"} row{sql.row_count === 1 ? "" : "s"} from your company workspace database
              </div>
            </>
          )}
          {docs.map((d, i) => (
            <div key={i} style={{ fontSize: 12, color: "var(--body)", borderLeft: "2px solid var(--hairline-strong)", paddingLeft: 9, marginTop: 8 }}>
              {d.snippet && <>“{d.snippet}” — </>}
              <span className="mono" style={{ fontSize: 10, color: "var(--mono-accent)" }}>{d.filename}</span>
              <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", marginLeft: 6 }}>
                {d.cited_in_answer ? "cited in answer" : "supporting chunk"}
              </span>
            </div>
          ))}
        </Accordion>
      )}

      <Accordion title="Access & trace">
        <div style={{ fontSize: 12, color: "var(--body)", lineHeight: 1.7 }}>
          <div>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-soft)" }}>DECISION </span>
            <span className="chip" style={refused ? { background: "#FCF3DC", color: "#8A5B10" } : {}}>
              {meta.access_decision}
            </span>
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-soft)", marginLeft: 12 }}>ROLE </span>
            {meta.role}
            <span className="mono" style={{ fontSize: 10, color: "var(--muted-soft)", marginLeft: 12 }}>WORKSPACE </span>
            {meta.company}
          </div>
          <div style={{ marginTop: 4 }}>
            Queryable areas for your role: <span className="mono" style={{ fontSize: 10.5 }}>{profile.access.tables.join(", ") || "none"}</span>
          </div>
          <div className="mono" style={{ fontSize: 10, color: "var(--muted-soft)", marginTop: 6 }}>
            trace {meta.trace_id} · saved to your company workspace · reviewable by your Admin
          </div>
        </div>
      </Accordion>

      <div style={{ marginTop: 8 }}>
        {reported ? (
          <span className="mono" style={{ fontSize: 10, color: "var(--success-text)" }}>✓ sent to your Admin with this trace attached</span>
        ) : (
          <button onClick={report} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontFamily: "var(--font-mono), monospace", fontSize: 10, color: "var(--muted-soft)" }}>
            {refused ? "⚑ request access to this data" : "⚑ report this answer"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function AskAnalystPage() {
  const [msgs, setMsgs] = useState<Node[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const idc = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (msgs.length) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs]);

  const ask = async (question?: string) => {
    const q = (question ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    const uid = idc.current++;
    const tid = idc.current++;
    setMsgs((prev) => [...prev, { id: uid, type: "user", text: q }, { id: tid, type: "thinking" }]);
    try {
      const payload = await platformQuery(q);
      setMsgs((prev) => prev.map((n) => (n.id === tid ? { id: tid, type: "answer", payload } : n)));
    } catch (e) {
      setMsgs((prev) => prev.map((n) => (n.id === tid ? { id: tid, type: "error", message: e instanceof Error ? e.message : "Query failed" } : n)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <PlatformShell
      botGreeting={(p) =>
        `This is your analyst desk for ${p.company.name}. Ask in plain English — I remember the conversation, so follow-ups like "what about Q4?" just work.`}
      botOnClick={(p) =>
        `If a question is outside your ${p.role} access, I'll refuse politely and say why — and you can request access with one click. Nothing restricted ever reaches the answer, citations, or charts.`}
      botTips={() => [
        'Try "Give me a dashboard" — instant KPIs and charts from deterministic SQL, no model in the loop.',
        'Every chart downloads as CSV, XLSX, or PNG — look under the chart.',
        "Open Access & trace on any answer to see the exact access decision and the saved trace id.",
        'Follow-ups work: after a revenue question, just ask "what about Q4?"',
      ]}
    >
      {(profile) => {
        const starters = STARTERS[profile.role] || STARTERS.Analyst;
        return (
          <div style={{ padding: "16px 0 90px", maxWidth: 760, marginLeft: "auto", marginRight: "auto" }}>
            {msgs.length === 0 && (
              <div style={{ textAlign: "center", padding: "34px 0 22px" }}>
                <h1 className="serif" style={{ fontSize: 26, margin: "0 0 6px" }}>
                  Ask about {profile.company.name}.
                </h1>
                <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 18px", lineHeight: 1.6 }}>
                  Answers come from your company&apos;s brain, scoped to your {profile.role} access —
                  with the SQL, citations, chart, and trace attached.
                </p>
                <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
                  {starters.map((s) => (
                    <button key={s} onClick={() => ask(s)}
                      style={{ fontFamily: "var(--font-sans), sans-serif", fontSize: 12, padding: "8px 14px", borderRadius: 20, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", color: "var(--muted)", cursor: "pointer" }}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", flexDirection: "column" }}>
              {msgs.map((n) => {
                if (n.type === "user")
                  return (
                    <div key={n.id} style={{ alignSelf: "flex-end", maxWidth: "80%", background: "var(--accent)", color: "var(--on-accent)", fontSize: 12.5, borderRadius: "12px 12px 3px 12px", padding: "8px 12px", margin: "14px 0 4px" }}>
                      {n.text}
                    </div>
                  );
                if (n.type === "thinking")
                  return (
                    <div key={n.id} className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <Avatar /><span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                        <Dots /><span style={{ fontSize: 12.5, color: "var(--ink)" }}>Checking your access, querying the company brain…</span>
                      </div>
                    </div>
                  );
                if (n.type === "error")
                  return (
                    <div key={n.id} className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px", borderLeft: "3px solid #A32D2D" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                        <Avatar /><span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
                        <span className="pill" style={{ marginLeft: "auto", background: "#F9E3E3", color: "#A32D2D" }}>couldn&apos;t answer</span>
                      </div>
                      <div style={{ fontSize: 13, color: "var(--body)", lineHeight: 1.55, marginTop: 8 }}>{n.message}</div>
                    </div>
                  );
                return <AnswerCard key={n.id} p={n.payload} profile={profile} onAsk={ask} />;
              })}
              <div ref={endRef} />
            </div>

            <div style={{ display: "flex", gap: 8, background: "var(--surface-soft)", border: "1px solid var(--hairline-mid)", borderRadius: 12, padding: "6px 6px 6px 14px", alignItems: "center", marginTop: 6 }}>
              <span style={{ color: "var(--mono-accent)" }}>Q</span>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask()}
                placeholder={`Ask about ${profile.company.name}'s data…`}
                style={{ flex: 1, border: "none", background: "transparent", fontSize: 13.5, color: "var(--ink)", outline: "none", minWidth: 0, fontFamily: "var(--font-sans), sans-serif" }}
              />
              <button onClick={() => ask()} disabled={busy} className="btn-primary" style={{ fontSize: 13, padding: "9px 18px", opacity: busy ? 0.6 : 1 }}>
                {busy ? "Working…" : "Ask →"}
              </button>
            </div>
            <div style={{ fontSize: 10.5, color: "var(--muted-soft)", marginTop: 7 }}>
              Live answers from your company workspace · role-scoped · every query traced with your name, role, and access decision.
            </div>
            <style>{`@keyframes nq-blink{0%,100%{opacity:.22;transform:translateY(0)}50%{opacity:1;transform:translateY(-2px)}}`}</style>
          </div>
        );
      }}
    </PlatformShell>
  );
}
