"use client";
import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import FooterNav from "@/components/FooterNav";
import CountUp from "@/components/CountUp";
import Reveal from "@/components/Reveal";
import { ContextMap, fetchContextMap } from "@/lib/api";

function Stat({ value, label }: { value: React.ReactNode; label: string }) {
  return (
    <div style={{ background: "var(--surface-soft)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "9px 13px" }}>
      <div className="serif" style={{ fontSize: 18, lineHeight: 1.1 }}>{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function OfflineCard() {
  return (
    <div className="card" style={{ padding: "22px 24px", marginTop: 18 }}>
      <div className="eyebrow" style={{ marginBottom: 6 }}>● backend offline</div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0, maxWidth: 560 }}>
        This page renders only live data from <span className="mono">GET /api/v1/context</span> — nothing here is
        hardcoded. Start the backend to see the real ontology:
      </p>
      <pre style={{ background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 8, padding: "10px 14px", fontSize: 12, marginTop: 12 }}>
        uvicorn api.main:app --port 8000
      </pre>
    </div>
  );
}

function GlossaryCard({ term }: { term: ContextMap["glossary"][number] }) {
  const [open, setOpen] = useState(false);
  const firstSentence = term.definition.split(/(?<=\.)\s/)[0];
  const truncated = term.definition.length > firstSentence.length + 4;
  return (
    <div className="card" style={{ padding: "13px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span className="serif" style={{ fontSize: 15 }}>{term.term}</span>
        <span className="chip chip-neutral">{term.id}</span>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--body)", margin: "6px 0 4px", lineHeight: 1.55 }}>
        {open || !truncated ? term.definition : firstSentence}
      </p>
      {truncated && (
        <span className="link-accent" style={{ fontSize: 11, cursor: "pointer" }} onClick={() => setOpen(!open)}>
          {open ? "− hide the exact SQL definition" : "＋ show the exact SQL definition"}
        </span>
      )}
      {term.aliases.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--muted-soft)", marginTop: 4 }}>also answers to: {term.aliases.join(" · ")}</div>
      )}
    </div>
  );
}

export default function ContextPage() {
  const [data, setData] = useState<ContextMap | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchContextMap().then(setData).catch(() => setFailed(true));
  }, []);

  const supersedes = data?.relationships.filter((r) => r.type === "supersedes") ?? [];
  const metricEdges = data?.relationships.filter((r) => r.type === "measured_from") ?? [];

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <TopNav crumb="BUSINESS CONTEXT" active="context" />

      <div style={{ position: "relative", paddingTop: 20 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>● 01 — The ontology Nexus reasons with</div>
        <h1 className="serif" style={{ fontSize: 29, margin: "0 0 8px" }}>What Nexus knows about the business</h1>
        <p style={{ fontSize: 13.5, color: "var(--muted)", margin: "0 0 18px", maxWidth: 620 }}>
          This is the company knowledge Nexus reasons with — its metric definitions, its live database schema, its document library, and how they all connect. Every item is read from a real source; nothing on this page is invented.
        </p>

        {failed && <OfflineCard />}

        {data && (
          <>
            {/* stats row */}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 26 }}>
              <Stat value={<CountUp value={data.stats.glossary_terms} />} label="GLOSSARY TERMS" />
              <Stat value={<CountUp value={data.stats.documents} />} label="INDEXED DOCUMENTS" />
              <Stat value={<CountUp value={Object.keys(data.stats.document_formats).length} />} label="DOCUMENT FORMATS" />
              <Stat value={<CountUp value={data.stats.tables} />} label="LIVE SQL TABLES" />
              <Stat value={<CountUp value={data.stats.business_entities ?? 0} />} label="BUSINESS ENTITIES" />
              <Stat value={<CountUp value={data.stats.relationships} />} label="RELATIONSHIPS" />
            </div>

            {/* formats + supersedence */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 26 }}>
              <div className="card" style={{ padding: "16px 18px" }}>
                <div className="label" style={{ marginBottom: 8 }}>DOCUMENT INVENTORY BY FORMAT</div>
                {Object.entries(data.stats.document_formats).map(([fmt, count]) => (
                  <div key={fmt} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "4px 0", borderBottom: "0.5px solid var(--hairline)" }}>
                    <span className="mono" style={{ fontSize: 12 }}>.{fmt}</span>
                    <span style={{ color: "var(--muted)" }}>{count} document{count === 1 ? "" : "s"}</span>
                  </div>
                ))}
                <div style={{ fontSize: 11.5, color: "var(--muted-soft)", marginTop: 10, fontStyle: "italic" }}>
                  Source: RAG ingestion manifest — what is actually embedded in the vector store.
                </div>
              </div>

              <div className="card" style={{ padding: "16px 18px" }}>
                <div className="label" style={{ marginBottom: 8 }}>FRESHNESS / SUPERSEDENCE</div>
                {supersedes.length === 0 && (
                  <p style={{ fontSize: 13, color: "var(--muted)" }}>No supersedence edges declared.</p>
                )}
                {supersedes.map((edge) => (
                  <div key={edge.from} style={{ fontSize: 13, lineHeight: 1.7 }}>
                    <span className="mono" style={{ fontSize: 12 }}>{edge.from}</span>
                    <span style={{ color: "var(--accent)", margin: "0 8px" }}>supersedes →</span>
                    <span className="mono" style={{ fontSize: 12 }}>{edge.to}</span>
                    <div style={{ fontSize: 11.5, color: "var(--muted-soft)", fontStyle: "italic" }}>
                      Declared in the document&apos;s own front matter; retrieval and answers must prefer the newer policy.
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* glossary */}
            <div className="eyebrow" style={{ marginBottom: 8 }}>● 02 — The company&apos;s own metric definitions</div>
            <Reveal>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 26 }}>
                {data.glossary.map((term) => <GlossaryCard key={term.id} term={term} />)}
              </div>
            </Reveal>

            {/* schema */}
            <div className="eyebrow" style={{ marginBottom: 8 }}>● 03 — Live schema (introspected, not assumed)</div>
            {!data.schema.available && (
              <p style={{ fontSize: 13, color: "var(--muted)" }}>
                Database unreachable right now — the API says so instead of inventing columns.
              </p>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 26 }}>
              {data.schema.tables.map((table) => (
                <div key={table.name} className="card" style={{ padding: "13px 16px" }}>
                  <div className="mono" style={{ fontSize: 13, marginBottom: 6, color: "var(--accent)" }}>{table.name}</div>
                  {table.columns.map((col) => (
                    <div key={col.name} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "2px 0" }}>
                      <span className="mono" style={{ fontSize: 11.5 }}>{col.name}</span>
                      <span style={{ color: "var(--muted-soft)", fontSize: 11 }}>{col.type.toLowerCase()}</span>
                    </div>
                  ))}
                  {metricEdges.filter((e) => e.to === table.name).length > 0 && (
                    <div style={{ fontSize: 11, color: "var(--muted-soft)", marginTop: 8, fontStyle: "italic" }}>
                      feeds: {metricEdges.filter((e) => e.to === table.name).map((e) => e.from).join(", ")}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* business entities */}
            <div className="eyebrow" style={{ marginBottom: 8 }}>● 04 — Business entities (pattern-extracted, provenance-tagged)</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 26 }}>
              {Object.entries(data.entities ?? {}).filter(([, list]) => list.length > 0).map(([kind, list]) => (
                <div key={kind} className="card" style={{ padding: "13px 16px" }}>
                  <div className="label" style={{ marginBottom: 8 }}>{kind.replace(/_/g, " ").toUpperCase()} ({list.length})</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {list.map((e) => (
                      <span key={e.id} className="chip chip-neutral" title={e.provenance}>{e.id}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* trust model + staleness */}
            <div className="eyebrow" style={{ marginBottom: 8 }}>● 05 — Why answers are trusted (or not)</div>
            <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16, marginBottom: 26 }}>
              <div className="card" style={{ padding: "14px 18px" }}>
                <div className="label" style={{ marginBottom: 8 }}>EVIDENCE CLASSES, STRONGEST FIRST</div>
                {(data.trust_model ?? []).map((t) => (
                  <div key={t.class} style={{ display: "flex", gap: 10, padding: "5px 0", borderBottom: "0.5px solid var(--hairline)", fontSize: 12.5 }}>
                    <span className="mono" style={{ color: "var(--accent)", width: 18, flex: "none" }}>{t.rank}</span>
                    <span className="mono" style={{ fontSize: 11.5, width: 170, flex: "none" }}>{t.class}</span>
                    <span style={{ color: "var(--muted)" }}>{t.meaning}</span>
                  </div>
                ))}
              </div>
              <div className="card" style={{ padding: "14px 18px" }}>
                <div className="label" style={{ marginBottom: 8 }}>STALE DOCUMENTS ({(data.staleness ?? []).length})</div>
                {(data.staleness ?? []).map((s) => (
                  <div key={s.filename} style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 8 }}>
                    <span className="mono" style={{ fontSize: 11.5 }}>{s.filename}</span>
                    <div style={{ color: "var(--muted)", fontSize: 11.5 }}>{s.reason}</div>
                  </div>
                ))}
                <div style={{ fontSize: 11, color: "var(--muted-soft)", fontStyle: "italic" }}>
                  Stale documents stay retrievable for history but never answer current-policy questions.
                </div>
              </div>
            </div>

            <p style={{ fontSize: 11.5, color: "var(--muted-soft)", fontStyle: "italic", maxWidth: 640 }}>
              {data.honesty.note}
            </p>
          </>
        )}
      </div>

      <div style={{ flex: 1 }} />
      <FooterNav prevHref="/how" prevLabel="How it works" nextHref="/reliability" nextLabel="Next: Reliability" />
    </main>
  );
}
