"use client";
import { useEffect, useRef, useState, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import TopNav from "@/components/TopNav";
import {
  API_BASE,
  AnswerPayload,
  Trace,
  fetchTrace,
  queryStream,
} from "@/lib/api";

/* ---------- small pieces ---------- */
function Avatar() {
  return (
    <span
      style={{
        width: 20,
        height: 20,
        borderRadius: "50%",
        background: "var(--mascot)",
        color: "var(--mascot-face)",
        fontSize: 11,
        fontFamily: "var(--font-display), serif",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      N
    </span>
  );
}

function Accordion({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: "0.5px solid var(--hairline)", borderRadius: 8, marginTop: 8, background: "var(--surface-soft)", overflow: "hidden" }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ padding: "8px 11px", cursor: "pointer", fontSize: 12, color: "var(--ink)", userSelect: "none" }}
      >
        {open ? "− " : "＋ "}
        {title}
      </div>
      {open && <div style={{ padding: "0 11px 11px" }}>{children}</div>}
    </div>
  );
}

function Dots() {
  return (
    <span style={{ display: "inline-flex", gap: 3 }}>
      {[0, 0.2, 0.4].map((d, i) => (
        <i
          key={i}
          style={{
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "var(--accent)",
            display: "inline-block",
            animation: `nq-blink 1s ${d}s infinite`,
          }}
        />
      ))}
    </span>
  );
}

/* The backend answer is markdown. Source-reference lines (📄 *file* — note)
   are lifted out of the prose and rendered as source cards, the way
   ChatGPT/Perplexity separate citations from the answer body. */
const SOURCE_LINE = /^\s*(?:📄|🔗)?\s*\*([^*]+\.(?:pdf|md|txt|csv|json|html))\*\s*[—–-]\s*(.+)$/;

function splitAnswer(text: string): { body: string; sources: { file: string; note: string }[] } {
  const sources: { file: string; note: string }[] = [];
  const kept: string[] = [];
  for (const line of text.split("\n")) {
    const m = line.match(SOURCE_LINE);
    if (m) sources.push({ file: m[1], note: m[2] });
    else kept.push(line);
  }
  return { body: kept.join("\n").trim(), sources };
}

function AnswerText({ text }: { text: string }) {
  const { body, sources } = splitAnswer(text);
  return (
    <div>
      <div className="answer-md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
      </div>
      {sources.length > 0 && (
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          {sources.map((s, i) => (
            <div key={i} className="source-card">
              <span className="source-num">{i + 1}</span>
              <span className="mono source-file">{s.file}</span>
              <span className="source-note">{s.note}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AnalystNotes({ analysis }: { analysis: NonNullable<AnswerPayload["analysis"]> }) {
  const region = analysis.breakdowns.find((b) => b.dimension === "region");
  return (
    <div style={{ marginTop: 10, border: "0.5px solid var(--hairline)", borderRadius: 8, background: "var(--accent-tint)", padding: "10px 12px" }}>
      <div className="label" style={{ marginBottom: 6, color: "var(--accent)" }}>ANALYST NOTES · computed from the same database</div>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {analysis.notes.map((n, i) => (
          <li key={i} style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.6 }}>{n}</li>
        ))}
      </ul>
      {region && region.rows.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {region.rows.map((r) => (
            <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 8, margin: "3px 0" }}>
              <span style={{ width: 52, fontSize: 11, color: "var(--muted)", textAlign: "right" }}>{r.label}</span>
              <div style={{ flex: 1, height: 10, background: "#ece4d4", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ width: `${Math.round(r.share * 100)}%`, height: "100%", background: "var(--accent)", borderRadius: 4, transition: "width 0.8s ease" }} />
              </div>
              <span className="mono" style={{ width: 34, fontSize: 10, color: "var(--muted)", textAlign: "right" }}>{Math.round(r.share * 100)}%</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 10, color: "var(--muted-soft)", marginTop: 6, fontStyle: "italic" }}>{analysis.method}</div>
    </div>
  );
}

function ConfidencePill({ payload }: { payload: AnswerPayload }) {
  const c = payload.confidence;
  const styles: Record<string, { bg: string; fg: string }> = {
    HIGH: { bg: "var(--success-bg)", fg: "var(--success-text)" },
    MEDIUM: { bg: "#FCF3DC", fg: "#8A5B10" },
    LOW: { bg: "#F9E3E3", fg: "#A32D2D" },
    UNKNOWN: { bg: "#F1EFE8", fg: "#5F5E5A" },
  };
  const s = styles[c] ?? styles.UNKNOWN;
  const label =
    c === "UNKNOWN"
      ? payload.evidence.sql?.success
        ? "SQL · exact"
        : payload.route.replace(/_/g, " ")
      : `${c} confidence`;
  return (
    <span className="pill" style={{ marginLeft: "auto", background: s.bg, color: s.fg }}>
      {label}
    </span>
  );
}

function ResultPreviewTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, margin: "6px 0" }}>
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c} className="mono" style={{ fontSize: 9, color: "var(--muted-soft)", textAlign: "left", padding: "4px 6px", borderBottom: "1px solid var(--hairline)" }}>
              {c.toUpperCase()}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {cols.map((c) => (
              <td key={c} style={{ padding: "4px 6px", color: "var(--body)", borderBottom: "0.5px solid #eee7d8" }}>
                {String(r[c])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TraceTimeline({ traceId }: { traceId: string }) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetchTrace(traceId)
      .then(setTrace)
      .catch(() => setErr("Trace not available (traces rotate on the server)."));
  }, [traceId]);
  if (err) return <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{err}</div>;
  if (!trace) return <div style={{ fontSize: 11.5, color: "var(--muted)" }}>Loading trace…</div>;
  const max = Math.max(...trace.spans.map((s) => s.duration_s ?? 0), 0.001);
  return (
    <div>
      {trace.spans.map((s, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span className="mono" style={{ fontSize: 9.5, width: 170, flex: "none", color: s.status === "ok" ? "var(--muted)" : "#A32D2D", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {s.name}
          </span>
          <div style={{ flex: 1, height: 8, background: "#ece4d4", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${Math.max(2, Math.round(((s.duration_s ?? 0) / max) * 100))}%`, height: "100%", background: s.status === "ok" ? "var(--accent)" : "#A32D2D", borderRadius: 3 }} />
          </div>
          <span className="mono" style={{ fontSize: 9.5, width: 44, flex: "none", textAlign: "right", color: "var(--muted-soft)" }}>
            {(s.duration_s ?? 0).toFixed(2)}s
          </span>
        </div>
      ))}
      <div className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", marginTop: 6 }}>
        trace {trace.trace_id} · {trace.spans.length} spans · {trace.duration_s?.toFixed(2)}s total
      </div>
    </div>
  );
}

/* ---------- node model ---------- */
type Node =
  | { id: number; type: "user"; text: string }
  | { id: number; type: "thinking"; phase: string }
  | { id: number; type: "answer"; payload: AnswerPayload }
  | { id: number; type: "error"; message: string };

const STARTERS = [
  "What was net revenue in Q4 2024?",
  "Validate Q4 electronics revenue against the financial report",
  "What is the electronics return window for Gold members under the current policy?",
  "What is the sell-through rate for SKU FOOD-5001?",
];

const STEP_LABELS: Record<string, string> = {
  received: "Routing your question…",
  processing: "Agents running…",
  sql: "Database checked ✓ — fusing…",
  rag: "Documents checked ✓ — fusing…",
  web: "Live web checked ✓ — fusing…",
};

function describeHow(p: AnswerPayload): string {
  const bits = [`Route: ${p.route.replace(/_/g, " + ")}`];
  if (p.query_time_s != null) bits.push(`${p.query_time_s.toFixed(1)}s`);
  if (p.usage?.llm_calls != null) bits.push(`${p.usage.llm_calls} LLM call${p.usage.llm_calls === 1 ? "" : "s"}`);
  if (p.usage?.avoided_llm_calls) bits.push(`${p.usage.avoided_llm_calls} avoided (deterministic)`);
  if (p.cached) bits.push("served from quality-gated cache");
  return bits.join(" · ");
}

export default function AskPage() {
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
    setMsgs((prev) => [...prev, { id: uid, type: "user", text: q }, { id: tid, type: "thinking", phase: STEP_LABELS.received }]);

    const setPhase = (phase: string) =>
      setMsgs((prev) => prev.map((n) => (n.id === tid && n.type === "thinking" ? { ...n, phase } : n)));

    try {
      for await (const ev of queryStream(q)) {
        if (ev.step === "answer") {
          const payload = ev.data as unknown as AnswerPayload;
          setMsgs((prev) => prev.map((n) => (n.id === tid ? { id: tid, type: "answer", payload } : n)));
        } else if (ev.step === "error") {
          const message = String(ev.data.error ?? "The backend reported an error.");
          setMsgs((prev) => prev.map((n) => (n.id === tid ? { id: tid, type: "error", message } : n)));
        } else if (STEP_LABELS[ev.step]) {
          setPhase(STEP_LABELS[ev.step]);
        }
      }
    } catch {
      setMsgs((prev) =>
        prev.map((n) =>
          n.id === tid
            ? {
                id: tid,
                type: "error",
                message: `Could not reach the NexusIQ backend at ${API_BASE}. Start it with "uvicorn api.main:app --port 8000" (see README) and try again.`,
              }
            : n
        )
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px" }}>
      <TopNav crumb="ASK" active="ask" />

      <div style={{ padding: "16px 0 20px", maxWidth: 720, marginLeft: "auto", marginRight: "auto" }}>
        {msgs.length === 0 && (
          <div style={{ textAlign: "center", padding: "34px 0 22px" }}>
            <h1 className="serif" style={{ fontSize: 26, margin: "0 0 6px" }}>Ask Nexus about the business.</h1>
            <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 18px" }}>
              Every answer comes with receipts — the SQL it ran, the documents it cited, and how sure it is. Answers take 5–12 seconds on free-tier models.
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
              {STARTERS.map((s) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  style={{ fontFamily: "var(--font-sans), sans-serif", fontSize: 12, padding: "8px 14px", borderRadius: 20, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", color: "var(--muted)", cursor: "pointer" }}
                >
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
                <div
                  key={n.id}
                  style={{ alignSelf: "flex-end", maxWidth: "80%", background: "var(--accent)", color: "var(--on-accent)", fontSize: 12.5, borderRadius: "12px 12px 3px 12px", padding: "8px 12px", margin: "14px 0 4px" }}
                >
                  {n.text}
                </div>
              );

            if (n.type === "thinking")
              return (
                <div key={n.id} className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <Avatar />
                    <span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
                    <Dots />
                    <span style={{ fontSize: 12.5, color: "var(--ink)" }}>{n.phase}</span>
                  </div>
                </div>
              );

            if (n.type === "error")
              return (
                <div key={n.id} className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px", borderLeft: "3px solid #A32D2D" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <Avatar />
                    <span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
                    <span className="pill" style={{ marginLeft: "auto", background: "#F9E3E3", color: "#A32D2D" }}>couldn&apos;t answer</span>
                  </div>
                  <div style={{ fontSize: 13, color: "var(--body)", lineHeight: 1.55, marginTop: 8 }}>{n.message}</div>
                </div>
              );

            const p = n.payload;
            const docCount = p.evidence.documents.length;
            const hasSql = !!p.evidence.sql?.query;
            const webCount = p.evidence.web.length;
            const evidenceCount = (hasSql ? 1 : 0) + (docCount ? 1 : 0) + (webCount ? 1 : 0);

            return (
              <div key={n.id} className="card" style={{ background: "var(--surface-card)", padding: "12px 15px", margin: "0 0 6px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <Avatar />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>Nexus</span>
                  <ConfidencePill payload={p} />
                </div>

                <div style={{ marginTop: 8 }}>
                  <AnswerText text={p.answer} />
                </div>

                {p.analysis && p.analysis.notes.length > 0 && <AnalystNotes analysis={p.analysis} />}

                {p.confidence_reason && (
                  <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 6, fontStyle: "italic" }}>
                    Why this confidence: {p.confidence_reason}
                  </div>
                )}

                {evidenceCount > 0 && (
                  <Accordion title={`Evidence · ${evidenceCount} source${evidenceCount === 1 ? "" : "s"}`}>
                    {hasSql && p.evidence.sql && (
                      <>
                        <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 10, background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 6, padding: "8px 9px", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                          {p.evidence.sql.query}
                        </div>
                        <div style={{ fontSize: 11.5, color: "var(--muted)", margin: "5px 0 8px" }}>
                          → {p.evidence.sql.row_count ?? "?"} row{p.evidence.sql.row_count === 1 ? "" : "s"}
                          {p.evidence.sql.repair_attempted && " · repaired once (bounded loop)"}
                        </div>
                        <ResultPreviewTable rows={p.evidence.sql.result_preview} />
                      </>
                    )}
                    {p.evidence.documents.map((d, i) => (
                      <div key={i} style={{ fontSize: 12, color: "var(--body)", borderLeft: "2px solid var(--hairline-strong)", paddingLeft: 9, marginTop: 8 }}>
                        {d.snippet && <>“{d.snippet}” — </>}
                        <span className="mono" style={{ fontSize: 10, color: "var(--mono-accent)" }}>
                          {d.filename}
                          {d.page != null && ` · p.${d.page}`}
                        </span>
                        <span className="mono" style={{ fontSize: 9.5, color: "var(--muted-soft)", marginLeft: 6 }}>
                          {d.cited_in_answer ? "cited in answer" : "supporting chunk"}
                          {d.relevance != null && ` · rerank ${d.relevance.toFixed(1)}`}
                        </span>
                      </div>
                    ))}
                    {webCount > 0 && (
                      <div style={{ fontSize: 12, color: "var(--body)", marginTop: 8 }}>
                        Live web: {p.evidence.web.map((w) => `${w.source} (${w.products ?? "?"} products${w.sample_data ? ", sample data" : ""})`).join(" · ")}
                      </div>
                    )}
                  </Accordion>
                )}

                <Accordion title="How I answered">
                  <div style={{ fontSize: 12, color: "var(--body)", lineHeight: 1.6, marginBottom: 8 }}>{describeHow(p)}</div>
                  {p.trace_id ? <TraceTimeline traceId={p.trace_id} /> : <div style={{ fontSize: 11.5, color: "var(--muted)" }}>No trace recorded for this answer.</div>}
                </Accordion>
              </div>
            );
          })}
          <div ref={endRef} />
        </div>

        {/* input pinned at foot of thread */}
        <div style={{ display: "flex", gap: 8, background: "var(--surface-soft)", border: "1px solid var(--hairline-mid)", borderRadius: 12, padding: "6px 6px 6px 14px", alignItems: "center", marginTop: 6 }}>
          <span style={{ color: "var(--mono-accent)" }}>Q</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="Ask about revenue, returns, strategy, competitor prices…"
            style={{ flex: 1, border: "none", background: "transparent", fontSize: 13.5, color: "var(--ink)", outline: "none", minWidth: 0, fontFamily: "var(--font-sans), sans-serif" }}
          />
          <button onClick={() => ask()} disabled={busy} className="btn-primary" style={{ fontSize: 13, padding: "9px 18px", opacity: busy ? 0.6 : 1 }}>
            {busy ? "Working…" : "Ask →"}
          </button>
        </div>
        <div style={{ fontSize: 10.5, color: "var(--muted-soft)", marginTop: 7 }}>
          Nothing here is scripted — each answer is produced live, with its SQL, citations, cost ledger, and trace attached.
        </div>
      </div>

      <style>{`@keyframes nq-blink{0%,100%{opacity:.22;transform:translateY(0)}50%{opacity:1;transform:translateY(-2px)}}`}</style>
    </main>
  );
}
