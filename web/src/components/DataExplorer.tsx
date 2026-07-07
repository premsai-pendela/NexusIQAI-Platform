"use client";
import { useEffect, useState } from "react";
import {
  STATS,
  SQL_SAMPLE,
  DOC_CATEGORIES,
  WEB_SAMPLE,
  REGION_REVENUE,
  WEB_AVG_PRICE,
} from "@/lib/mock";
import { Meta, fetchMeta } from "@/lib/api";

type Tab = "sql" | "docs" | "web";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ background: "var(--surface-soft)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "9px 13px" }}>
      <div className="serif" style={{ fontSize: 18, lineHeight: 1.1 }}>{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

function BarChart({ items, fmt }: { items: { label: string; value: number }[]; fmt: (v: number) => string }) {
  const max = Math.max(...items.map((i) => i.value));
  return (
    <div style={{ marginTop: 12 }}>
      {items.map((it) => (
        <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 9 }}>
          <div style={{ width: 82, flex: "none", fontSize: 12, color: "var(--muted)", textAlign: "right" }}>{it.label}</div>
          <div style={{ flex: 1, height: 16, background: "#ece4d4", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${Math.round((it.value / max) * 100)}%`, height: "100%", background: "var(--accent)", borderRadius: 4 }} />
          </div>
          <div className="mono" style={{ width: 52, flex: "none", fontSize: 11.5, color: "var(--ink)", textAlign: "right" }}>{fmt(it.value)}</div>
        </div>
      ))}
    </div>
  );
}

function ChartCard({ title, children, caption }: { title: string; children: React.ReactNode; caption: string }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div className="label" style={{ marginBottom: 2 }}>{title}</div>
      {children}
      <div style={{ fontSize: 11.5, color: "var(--muted-soft)", marginTop: 10, fontStyle: "italic" }}>{caption}</div>
    </div>
  );
}

export default function DataExplorer() {
  const [tab, setTab] = useState<Tab>("sql");
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    fetchMeta().then(setMeta).catch(() => setMeta(null));
  }, []);

  // Live values when the backend answers; documented figures otherwise.
  const live = {
    transactions: meta?.database.transactions?.toLocaleString() ?? STATS.transactions,
    docs: meta?.documents.total_documents?.toString() ?? STATS.docs,
    pdfs: meta?.documents.pdf_count?.toString() ?? STATS.docs,
    bizFiles: meta?.documents.business_file_count?.toString() ?? "0",
    chunks: meta?.documents.chunks?.toString() ?? STATS.chunks,
    retailers: meta?.web.retailers?.toString() ?? STATS.retailers,
    webCategories: meta?.web.categories?.toString() ?? STATS.categories,
  };
  const docCategories =
    meta && Object.keys(meta.documents.categories).length
      ? Object.entries(meta.documents.categories).map(([name, count]) => ({ name, count }))
      : DOC_CATEGORIES;
  const provenance = meta ? "measured live from the backend" : "documented figures — backend offline";

  const tabBtn = (k: Tab, label: string) => (
    <button
      onClick={() => setTab(k)}
      style={{
        fontFamily: "var(--font-sans), sans-serif",
        fontSize: 13,
        padding: "8px 16px",
        borderRadius: 20,
        border: "1px solid " + (tab === k ? "var(--accent)" : "var(--hairline-mid)"),
        background: tab === k ? "var(--accent)" : "var(--surface-soft)",
        color: tab === k ? "var(--on-accent)" : "var(--muted)",
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );

  const th = (h: string) => (
    <th key={h} className="mono" style={{ fontSize: 9, color: "var(--muted-soft)", textAlign: "left", padding: "6px 8px", borderBottom: "1px solid var(--hairline)" }}>{h}</th>
  );
  const td = (c: string, j: number) => (
    <td key={j} style={{ padding: "6px 8px", color: "var(--body)", borderBottom: "0.5px solid #eee7d8" }}>{c}</td>
  );

  return (
    <div style={{ display: "flex", gap: 28, alignItems: "flex-start", flexWrap: "wrap" }}>
      {/* LEFT — explorer */}
      <div style={{ flex: "1.25 1 430px", minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          {tabBtn("sql", "SQL database")}
          {tabBtn("docs", "Documents")}
          {tabBtn("web", "Live web")}
        </div>
        <div className="mono" style={{ fontSize: 9.5, color: meta ? "var(--chip-green-text)" : "var(--muted-soft)", marginBottom: 12 }}>
          ● COUNTS {provenance.toUpperCase()}
        </div>

        <div style={{ minHeight: 210 }}>
          {tab === "sql" && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                <Stat value={live.transactions} label="ROWS · FY2024" />
                <Stat value={STATS.revenue} label="TOTAL REVENUE" />
                <Stat value={STATS.regions} label="REGIONS" />
                <Stat value={STATS.months} label="MONTHS" />
              </div>
              <div className="card" style={{ padding: "10px 12px" }}>
                <div className="mono" style={{ fontSize: 10, color: "var(--mono-accent)", marginBottom: 4 }}>sales_transactions · sample</div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                  <thead><tr>{["DATE", "REGION", "PRODUCT", "PAYMENT", "REVENUE"].map(th)}</tr></thead>
                  <tbody>
                    {SQL_SAMPLE.map((r, i) => (
                      <tr key={i}>{[r.date, r.region, r.product, r.payment, r.revenue].map(td)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {tab === "docs" && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                <Stat value={live.docs} label="DOCUMENTS INDEXED" />
                <Stat value={live.pdfs} label="PDF REPORTS" />
                <Stat value={live.bizFiles} label="BUSINESS FILES · MD / CSV / JSON / HTML / TXT" />
                <Stat value={live.chunks} label="INDEXED CHUNKS" />
              </div>
              <div className="label" style={{ marginTop: 8 }}>
                RETRIEVAL · <span style={{ color: "var(--chip-green-text)" }}>hybrid BM25 + vector, then cross-encoder reranker</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10 }}>
                {docCategories.map((c) => (
                  <div key={c.name} className="card" style={{ padding: "9px 11px", fontSize: 12, color: "var(--body)", display: "flex", justifyContent: "space-between" }}>
                    {c.name}
                    <span className="mono" style={{ fontSize: 10, color: "var(--mono-accent)" }}>{c.count}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {tab === "web" && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
                <Stat value={live.retailers} label="LIVE RETAILERS" />
                <Stat value={live.webCategories} label="CATEGORIES" />
                <Stat value="24h" label="CACHE TTL" />
              </div>
              <div className="label" style={{ marginTop: 8 }}>
                SOURCES · <span style={{ color: "var(--chip-green-text)" }}>BeautifulSoup + Shopify / JSON APIs</span>
              </div>
              <div className="card" style={{ padding: "10px 12px", marginTop: 10 }}>
                <div className="mono" style={{ fontSize: 10, color: "var(--mono-accent)", marginBottom: 4 }}>competitor pricing · live sample</div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                  <thead><tr>{["RETAILER", "CATEGORY", "PRODUCT", "PRICE"].map(th)}</tr></thead>
                  <tbody>
                    {WEB_SAMPLE.map((r, i) => (
                      <tr key={i}>{[r.retailer, r.category, r.product, r.price].map(td)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>

      {/* RIGHT — a visual for the active source */}
      <div style={{ flex: "1 1 340px", minWidth: 300 }}>
        {tab === "sql" && (
          <ChartCard title="REVENUE BY REGION · $M" caption="West leads; five regions across FY2024.">
            <BarChart items={REGION_REVENUE} fmt={(v) => `$${v}M`} />
          </ChartCard>
        )}
        {tab === "docs" && (
          <ChartCard title="DOCUMENTS BY CATEGORY" caption={meta ? "Real per-category counts from the indexed corpus." : "Example breakdown — backend offline."}>
            <BarChart items={[...docCategories].sort((a, b) => b.count - a.count).map((c) => ({ label: c.name, value: c.count }))} fmt={(v) => `${v}`} />
          </ChartCard>
        )}
        {tab === "web" && (
          <ChartCard title="AVG COMPETITOR PRICE · $" caption="Electronics carry the highest competitor prices.">
            <BarChart items={WEB_AVG_PRICE} fmt={(v) => `$${v}`} />
          </ChartCard>
        )}
      </div>
    </div>
  );
}
