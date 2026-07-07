"use client";
import { useState } from "react";
import ChartView from "./ChartView";
import { DashboardSpec } from "@/lib/platform";

/* Multi-chart dashboard answer: KPI row + chart grid, all deterministic
   role-filtered SQL. SQL is inspectable under the fold. */

function fmt(v: number | string): string {
  if (typeof v === "number" && Math.abs(v) >= 1000)
    return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return String(v);
}

export default function DashboardView({ spec, exportMeta }: {
  spec: DashboardSpec;
  exportMeta?: { question?: string; trace_id?: string };
}) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(spec.kpis.length, 4)}, 1fr)`, gap: 10 }}>
        {spec.kpis.map((k) => (
          <div key={k.title} style={{ border: "0.5px solid var(--hairline)", borderRadius: 10, background: "var(--accent-tint)", padding: "10px 13px" }}>
            <div className="label" style={{ color: "var(--accent)" }}>{k.title.toUpperCase()}</div>
            <div className="serif" style={{ fontSize: 25, color: "var(--ink)", marginTop: 2 }}>{fmt(k.value)}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
        {spec.charts.map((c) => (
          <div key={c.title}>
            <ChartView spec={c} exportMeta={exportMeta} />
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: "var(--muted-soft)", marginTop: 10, fontStyle: "italic" }}>
        {spec.note}{" "}
        <button onClick={() => setShowSql((s) => !s)}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontFamily: "var(--font-mono), monospace", fontSize: 10, color: "var(--accent)" }}>
          {showSql ? "hide SQL" : `show the ${spec.sql_used.length} queries`}
        </button>
      </div>
      {showSql && (
        <div style={{ fontFamily: "var(--font-mono), monospace", fontSize: 9.5, background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 6, padding: "8px 10px", lineHeight: 1.7, marginTop: 6, whiteSpace: "pre-wrap" }}>
          {spec.sql_used.join("\n\n")}
        </div>
      )}
    </div>
  );
}
