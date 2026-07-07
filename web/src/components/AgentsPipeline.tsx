"use client";
import { useRef, useState } from "react";
import MascotSvg from "./MascotSvg";

type StageId = "q" | "router" | "sql" | "rag" | "web" | "val" | "fus";

const STOPS: { pos: StageId; lit: StageId[]; say: string }[] = [
  { pos: "q", lit: ["q"], say: "You ask in plain words." },
  { pos: "router", lit: ["router"], say: "I pick which sources to use." },
  { pos: "sql", lit: ["sql", "rag", "web"], say: "SQL, RAG and Web run in parallel." },
  { pos: "val", lit: ["val"], say: "I check the numbers agree." },
  { pos: "fus", lit: ["fus"], say: "I blend one cited answer." },
];
const STEP = 2800;

export default function AgentsPipeline() {
  const [lit, setLit] = useState<Set<StageId>>(new Set());
  const [moverTop, setMoverTop] = useState(0);
  const [say, setSay] = useState("Hit Run — I'll walk it.");
  const [answer, setAnswer] = useState(false);

  const stageRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const moverRef = useRef<HTMLDivElement | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const moveTo = (id: StageId) => {
    const el = stageRefs.current[id];
    const mv = moverRef.current;
    if (el && mv) setMoverTop(el.offsetTop + el.offsetHeight / 2 - mv.offsetHeight / 2);
  };

  const run = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setLit(new Set());
    setAnswer(false);
    setSay("Routing your question…");
    moveTo("q");
    STOPS.forEach((s, i) => {
      timers.current.push(
        setTimeout(() => {
          moveTo(s.pos);
          setLit((prev) => new Set([...prev, ...s.lit]));
          setSay(s.say);
        }, 700 + i * STEP)
      );
    });
    timers.current.push(
      setTimeout(() => {
        setAnswer(true);
        setSay("Done — up 10%, ahead of rivals.");
      }, 700 + STOPS.length * STEP)
    );
  };

  const stage = (id: StageId, title: string, sub: string, agent = false) => (
    <div
      ref={(el) => {
        stageRefs.current[id] = el;
      }}
      className={lit.has(id) ? "node-live" : undefined}
      style={{
        background: lit.has(id) ? "var(--accent-tint)" : "var(--surface-soft)",
        border: "1px solid " + (lit.has(id) ? "var(--accent)" : "var(--hairline)"),
        boxShadow: lit.has(id) ? "0 0 0 2px rgba(47,93,58,.12)" : "none",
        borderRadius: 10,
        padding: agent ? "9px 10px" : "9px 16px",
        textAlign: "center",
        fontSize: 13,
        color: "var(--ink)",
        minWidth: agent ? 84 : undefined,
        transition: "all .3s",
      }}
    >
      {title}
      <small style={{ display: "block", fontSize: 10, color: "var(--muted-soft)", marginTop: 2, fontFamily: "var(--font-mono), monospace" }}>{sub}</small>
    </div>
  );

  const arrow = (extra?: string) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <svg width="14" height="26" viewBox="0 0 14 26" aria-hidden>
        <line x1="7" y1="0" x2="7" y2="20" stroke="var(--hairline-mid)" strokeWidth="1.6" className="flow-dash" />
        <path d="M2.5 19 L7 25 L11.5 19" fill="none" stroke="var(--hairline-mid)" strokeWidth="1.6" />
      </svg>
      {extra && <span className="mono" style={{ fontSize: 9, color: "var(--muted-soft)" }}>{extra}</span>}
    </div>
  );

  return (
    <>
      <div style={{ paddingTop: 4 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>● 02 — How answers get built</div>
        <h2 className="serif" style={{ fontSize: 27, margin: "0 0 4px" }}>How an answer gets built</h2>
        <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 12px", maxWidth: 520 }}>
          One question fans out to specialist agents, gets cross-checked against the database, and comes back as a single cited answer. Press Run and Nexus will walk you through it.
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <button onClick={run} className="btn-primary" style={{ padding: "8px 18px", fontSize: 13 }}>▶ Run a question</button>
          <span style={{ fontSize: 12, color: "var(--muted-soft)", fontStyle: "italic" }}>“Compare Q4 revenue to competitors”</span>
        </div>
      </div>

      <div style={{ margin: "6px 0 14px", border: "1px dashed var(--hairline-mid)", borderRadius: 12, padding: "22px 12px 16px", position: "relative" }}>
        <span className="mono" style={{ position: "absolute", top: -9, left: 16, background: "var(--canvas)", padding: "0 8px", fontSize: 9.5, color: "var(--mono-accent)", letterSpacing: 0.4 }}>
          PRODUCTION HARNESS · bounded steps · 1-retry repair · fully traced
        </span>

        <div style={{ position: "relative", display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minHeight: 300 }}>
          {stage("q", "Question", "plain English in")}
          {arrow()}
          {stage("router", "Router", "rule-based → LLM fallback")}
          {arrow()}
          <div ref={(el) => { stageRefs.current["agents"] = el; }} style={{ display: "flex", gap: 8 }}>
            {stage("sql", "SQL agent", "our revenue", true)}
            {stage("rag", "RAG agent", "the report", true)}
            {stage("web", "Web agent", "competitors", true)}
          </div>
          {arrow("parallel")}
          {stage("val", "Cross-validate", "database number vs document number")}
          {arrow()}
          {stage("fus", "Fusion answer", "one blended response")}

          <div ref={moverRef} style={{ position: "absolute", left: 0, top: moverTop, display: "flex", alignItems: "center", gap: 5, transition: "top .7s cubic-bezier(.3,.7,.3,1)" }}>
            <div style={{ animation: "nq-bob 2.4s ease-in-out infinite", flex: "none" }}>
              <MascotSvg size={44} />
            </div>
            <div style={{ position: "relative", maxWidth: 108, background: "#fffdf8", border: "1px solid var(--hairline)", borderRadius: 12, padding: "7px 9px", fontSize: 11, lineHeight: 1.32, color: "var(--ink)", boxShadow: "0 5px 16px rgba(80,60,30,.12)" }}>
              {say}
              <div style={{ position: "absolute", left: -6, top: 14, width: 11, height: 11, background: "#fffdf8", borderLeft: "1px solid var(--hairline)", borderBottom: "1px solid var(--hairline)", transform: "rotate(45deg)" }} />
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ position: "relative", padding: 14, marginBottom: 14, visibility: answer ? "visible" : "hidden", opacity: answer ? 1 : 0, transition: "opacity .45s" }}>
        <span className="mono" style={{ position: "absolute", top: 10, right: 12, fontSize: 8, letterSpacing: 0.5, color: "#b0733e", background: "#f3e7d6", padding: "2px 6px", borderRadius: 4 }}>
          WALKTHROUGH
        </span>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", paddingRight: 96 }}>
          <div className="serif" style={{ fontSize: 24 }}>+10% YoY</div>
          <span className="pill">HIGH confidence</span>
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
          Illustrative walkthrough of the real pipeline — ask your own question live on the Ask page.
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[["100%", "RAG HIT@5 · 55-QUERY BENCH"], ["2→10", "OF 10 AMBIGUOUS-METRIC SQL EVALS"], ["5–12s", "MULTI-SOURCE"], ["258", "TESTS · EVAL-GATED CI"]].map(([v, l]) => (
          <div key={l} style={{ background: "var(--surface-soft)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "8px 14px" }}>
            <div className="serif" style={{ fontSize: 17, lineHeight: 1.1 }}>{v}</div>
            <div className="label">{l}</div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: "var(--muted-soft)", padding: "8px 0 0" }}>
        If a step fails, the harness retries once, falls back to the next engine, and records why — failures are logged, never hidden.
      </div>

      <style>{`@keyframes nq-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}`}</style>
    </>
  );
}
