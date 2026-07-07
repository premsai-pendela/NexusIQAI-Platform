"use client";
import { useRef, useState } from "react";
import { ChartSpec, exportXlsx } from "@/lib/platform";

/* Deterministic chart renderer for platform chart specs. Hand-drawn SVG in
   the NexusIQ palette — no chart library. Downloads: CSV always, PNG for
   bar/line (SVG → canvas). */

const W = 640;
const H = 260;
const PAD = { top: 18, right: 16, bottom: 58, left: 64 };

function fmt(v: unknown): string {
  if (typeof v === "number") {
    if (Math.abs(v) >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
    return String(Math.round(v * 100) / 100);
  }
  return String(v ?? "");
}

function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

function download(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ChartView({ spec }: { spec: ChartSpec }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [xlsxBusy, setXlsxBusy] = useState(false);
  const slug = spec.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);

  const downloadCsv = () =>
    download(`${slug}.csv`, new Blob([toCsv(spec.data)], { type: "text/csv" }));

  const downloadXlsx = async () => {
    setXlsxBusy(true);
    try {
      await exportXlsx(spec.title, spec.data);
    } finally {
      setXlsxBusy(false);
    }
  };

  const downloadPng = () => {
    const svg = svgRef.current;
    if (!svg) return;
    const xml = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = W * 2;
      canvas.height = H * 2;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "#fffdf9";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => b && download(`${slug}.png`, b), "image/png");
    };
    img.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(xml)))}`;
  };

  const linkStyle = { background: "none", border: "none", fontSize: 11, fontFamily: "var(--font-mono), monospace", cursor: "pointer", padding: 0 } as const;
  const controls = (withPng: boolean) => (
    <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
      <button className="link-accent" onClick={downloadCsv} style={linkStyle}>↓ CSV</button>
      <button className="link-accent" onClick={downloadXlsx} disabled={xlsxBusy}
        style={{ ...linkStyle, opacity: xlsxBusy ? 0.5 : 1 }}>
        {xlsxBusy ? "…" : "↓ XLSX"}
      </button>
      {withPng && (
        <button className="link-accent" onClick={downloadPng} style={linkStyle}>↓ PNG</button>
      )}
    </div>
  );

  if (spec.type === "kpi") {
    const row = spec.data[0] || {};
    const value = spec.y ? row[spec.y] : Object.values(row)[0];
    return (
      <div style={{ marginTop: 10, border: "0.5px solid var(--hairline)", borderRadius: 10, background: "var(--accent-tint)", padding: "14px 16px" }}>
        <div className="label" style={{ color: "var(--accent)" }}>{spec.title.toUpperCase()}</div>
        <div className="serif" style={{ fontSize: 34, color: "var(--ink)", margin: "2px 0" }}>{fmt(value)}</div>
        {controls(false)}
      </div>
    );
  }

  if (spec.type === "table" || !spec.x || !spec.y) {
    const cols = spec.data.length ? Object.keys(spec.data[0]) : [];
    return (
      <div style={{ marginTop: 10 }}>
        <div className="label" style={{ marginBottom: 4 }}>{spec.title.toUpperCase()}</div>
        <div style={{ maxHeight: 260, overflow: "auto", border: "0.5px solid var(--hairline)", borderRadius: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
            <thead>
              <tr>{cols.map((c) => (
                <th key={c} className="mono" style={{ position: "sticky", top: 0, background: "var(--surface-soft)", fontSize: 9, textAlign: "left", padding: "6px 8px", color: "var(--muted-soft)", borderBottom: "1px solid var(--hairline)" }}>{c.toUpperCase()}</th>
              ))}</tr>
            </thead>
            <tbody>
              {spec.data.map((r, i) => (
                <tr key={i}>{cols.map((c) => (
                  <td key={c} style={{ padding: "5px 8px", color: "var(--body)", borderBottom: "0.5px solid #eee7d8" }}>{fmt(r[c])}</td>
                ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
        {controls(false)}
      </div>
    );
  }

  const xKey = spec.x;
  const yKey = spec.y;
  const values = spec.data.map((d) => Number(d[yKey]) || 0);
  const maxV = Math.max(...values, 1);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const n = spec.data.length;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: PAD.top + innerH * (1 - f),
    label: fmt(maxV * f),
  }));

  return (
    <div style={{ marginTop: 10 }}>
      <div className="label" style={{ marginBottom: 4 }}>{spec.title.toUpperCase()}</div>
      <div style={{ border: "0.5px solid var(--hairline)", borderRadius: 10, background: "var(--surface-card)", padding: "8px 6px 2px" }}>
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }} xmlns="http://www.w3.org/2000/svg">
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.left} x2={W - PAD.right} y1={t.y} y2={t.y} stroke="#e4dbc9" strokeWidth={0.6} />
              <text x={PAD.left - 8} y={t.y + 3} textAnchor="end" fontSize={9} fill="#8a7f6a" fontFamily="monospace">{t.label}</text>
            </g>
          ))}
          {spec.type === "bar" &&
            spec.data.map((d, i) => {
              const bw = Math.min(46, (innerW / n) * 0.62);
              const cx = PAD.left + (innerW / n) * (i + 0.5);
              const h = (Number(d[yKey]) / maxV) * innerH || 0;
              return (
                <g key={i}>
                  <rect x={cx - bw / 2} y={PAD.top + innerH - h} width={bw} height={h} rx={3} fill="#2f5d3a" />
                  <text x={cx} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={9} fill="#6e6656" fontFamily="monospace">
                    {String(d[xKey]).slice(0, 12)}
                  </text>
                  <text x={cx} y={PAD.top + innerH - h - 4} textAnchor="middle" fontSize={8.5} fill="#9a6a3c" fontFamily="monospace">
                    {fmt(d[yKey])}
                  </text>
                </g>
              );
            })}
          {spec.type === "line" && (
            <>
              <polyline
                fill="none" stroke="#2f5d3a" strokeWidth={2}
                points={spec.data.map((d, i) => {
                  const cx = PAD.left + (innerW / Math.max(n - 1, 1)) * i;
                  const cy = PAD.top + innerH - (Number(d[yKey]) / maxV) * innerH;
                  return `${cx},${cy}`;
                }).join(" ")}
              />
              {spec.data.map((d, i) => {
                const cx = PAD.left + (innerW / Math.max(n - 1, 1)) * i;
                const cy = PAD.top + innerH - (Number(d[yKey]) / maxV) * innerH;
                const showLabel = n <= 12 || i % Math.ceil(n / 12) === 0;
                return (
                  <g key={i}>
                    <circle cx={cx} cy={cy} r={2.6} fill="#2f5d3a" />
                    {showLabel && (
                      <text x={cx} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={8.5} fill="#6e6656" fontFamily="monospace">
                        {String(d[xKey]).slice(0, 10)}
                      </text>
                    )}
                  </g>
                );
              })}
            </>
          )}
          <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top + innerH} y2={PAD.top + innerH} stroke="#cdc3ae" strokeWidth={1} />
        </svg>
      </div>
      {controls(true)}
    </div>
  );
}
