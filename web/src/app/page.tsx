import Link from "next/link";
import Mascot from "@/components/Mascot";
import { CHAPTERS } from "@/lib/mock";

export default function Home() {
  return (
    <main
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        padding: "20px 40px 40px",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* home nav */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 40,
        }}
      >
        <span className="wordmark">
          Nexus<span>IQ</span>
        </span>
        <div style={{ display: "flex", gap: 20, fontSize: 13, color: "var(--muted)" }}>
          <Link href="/how">How it works</Link>
          <span>API</span>
          <span>GitHub</span>
        </div>
      </div>

      {/* hero */}
      <section
        style={{
          position: "relative",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          paddingBottom: 40,
        }}
      >
        <div style={{ display: "flex", gap: 32, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: "1.1 1 340px" }}>
            <div className="eyebrow" style={{ marginBottom: 16 }}>
              ● Multi-agent business intelligence
            </div>
            <h1
              className="serif"
              style={{ fontSize: "clamp(2.2rem, 4.2vw, 3.4rem)", lineHeight: 1.08, margin: "0 0 16px" }}
            >
              Business answers, with the receipts attached.
            </h1>
            <p
              style={{
                fontSize: 15,
                lineHeight: 1.6,
                color: "var(--muted)",
                margin: "0 0 22px",
                maxWidth: 420,
              }}
            >
              Ask in plain English. Nexus works the question across a live
              database, company documents, and the web — then shows the SQL,
              the citations, and how confident it is, so you can check its work.
            </p>
            <div style={{ marginBottom: 16 }}>
              <Link href="/how" className="btn-primary">
                Explore the data →
              </Link>
            </div>
            <div className="label" style={{ letterSpacing: 0.5 }}>
              100,000 TRANSACTIONS · 52 DOCS IN 6 FORMATS · 9 LIVE SOURCES
            </div>
          </div>

          {/* example answer card */}
          <div style={{ width: 268 }}>
            <div className="card" style={{ padding: 16, position: "relative" }}>
              <span
                className="mono"
                style={{
                  position: "absolute",
                  top: 12,
                  right: 12,
                  fontSize: 8,
                  letterSpacing: 0.5,
                  color: "#b0733e",
                  background: "#f3e7d6",
                  padding: "2px 6px",
                  borderRadius: 4,
                }}
              >
                EXAMPLE
              </span>
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10, paddingRight: 52 }}>
                <span style={{ color: "var(--mono-accent)" }}>Q ·</span> What was net
                revenue in Q4 2024?
              </div>
              <div style={{ display: "flex", gap: 5, marginBottom: 10 }}>
                <span className="chip">SQL</span>
                <span className="chip">RAG</span>
                <span className="chip chip-neutral">→ fusion</span>
              </div>
              <div className="serif" style={{ fontSize: 28 }}>
                $58.25M
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", margin: "3px 0 12px" }}>
                Database and financial report agree within 1.11%.
              </div>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  borderTop: "0.5px solid var(--hairline)",
                  paddingTop: 10,
                }}
              >
                <span className="pill">HIGH confidence</span>
                <span style={{ fontSize: 10, color: "var(--muted-soft)" }}>SQL + 3 documents</span>
              </div>
            </div>
            <div
              style={{
                textAlign: "center",
                fontSize: 10.5,
                color: "var(--muted-soft)",
                marginTop: 7,
                fontStyle: "italic",
              }}
            >
              a real validated answer, rendered
            </div>
          </div>
        </div>

        {/* chapters 01/02/03 */}
        <div style={{ borderTop: "1px solid var(--hairline-strong)", display: "flex", marginTop: 26 }}>
          {CHAPTERS.map((c, i) => (
            <Link
              key={c.n}
              href={c.href}
              style={{
                flex: 1,
                padding: "16px 18px 4px 0",
                paddingLeft: i === 0 ? 0 : 20,
                borderRight: i < CHAPTERS.length - 1 ? "1px solid var(--hairline-strong)" : "none",
              }}
            >
              <div className="mono" style={{ fontSize: 11, color: "var(--mono-accent)" }}>
                {c.n}
              </div>
              <div className="serif" style={{ fontSize: 17, margin: "3px 0 1px" }}>
                {c.title}
              </div>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>{c.sub} →</div>
            </Link>
          ))}
        </div>

        <Mascot
          greeting="Hi — I'm Nexus 👋 Start with ‘The data’ and I'll show you around."
          onClickSay="Three steps: see the data, meet the agents, then ask me anything."
        />
      </section>
    </main>
  );
}
