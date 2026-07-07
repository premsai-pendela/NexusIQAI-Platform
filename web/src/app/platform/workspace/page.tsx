"use client";
import { useEffect, useState } from "react";
import PlatformShell from "@/components/PlatformShell";
import { Workspace, fetchWorkspace, rebuildBrain } from "@/lib/platform";

/* Company workspace home: role/access summary, brain status, accessible
   tables and documents. Admin/CEO additionally get data management with the
   build/rebuild control and the visible build log. */

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    ready: { bg: "var(--success-bg)", fg: "var(--success-text)", label: "workspace ready" },
    needs_rebuild: { bg: "#FCF3DC", fg: "#8A5B10", label: "needs rebuild" },
    not_built: { bg: "#F9E3E3", fg: "#A32D2D", label: "not built" },
  };
  const s = map[status] || map.not_built;
  return <span className="pill" style={{ background: s.bg, color: s.fg }}>{s.label}</span>;
}

export default function WorkspacePage() {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildLog, setRebuildLog] = useState<Record<string, unknown> | null>(null);

  const load = () => fetchWorkspace().then(setWs).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const doRebuild = async () => {
    setRebuilding(true);
    try {
      const out = await rebuildBrain();
      setRebuildLog(out.build_log);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Rebuild failed");
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <PlatformShell
      botGreeting={(p) =>
        `Welcome back, ${p.name.split(" ")[0]}. You're in the ${p.company.name} workspace as ${p.role}. Your access covers: ${p.access.summary}`}
      botOnClick={(p) =>
        p.is_admin
          ? "As Admin you can rebuild the company brain when source data changes, and review employee feedback and traces under Review."
          : "Head to Ask Analyst to query your company data. If you hit an access limit, the refusal will explain exactly what your role covers."}
    >
      {(profile) => (
        <div style={{ padding: "26px 0 80px" }}>
          {err && <div style={{ color: "#A32D2D", fontSize: 13, marginBottom: 12 }}>{err}</div>}

          <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginBottom: 4 }}>
            <h1 className="serif" style={{ fontSize: 28, margin: 0 }}>{profile.company.name}</h1>
            {ws && <StatusPill status={ws.brain.status} />}
          </div>
          <p style={{ fontSize: 13.5, color: "var(--muted)", maxWidth: 640, margin: "4px 0 6px", lineHeight: 1.65 }}>
            {profile.company.description}
          </p>
          <div className="mono" style={{ fontSize: 10.5, color: "var(--muted-soft)", marginBottom: 24 }}>
            {profile.company.industry} · fiscal 2024 data · synthetic demo company
            {ws?.brain.built_at && ` · brain built ${new Date(ws.brain.built_at).toLocaleString()}`}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.15fr 1fr", gap: 22, alignItems: "start" }}>
            <div style={{ display: "grid", gap: 18 }}>
              {/* Access card */}
              <div className="card" style={{ background: "var(--surface-card)", padding: "16px 18px" }}>
                <div className="label" style={{ marginBottom: 8 }}>YOUR ACCESS · {profile.role.toUpperCase()} · READ-ONLY</div>
                <div style={{ fontSize: 13, color: "var(--body)", lineHeight: 1.65 }}>{profile.access.summary}</div>
                {profile.access.denied_summary && (
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6, lineHeight: 1.6 }}>
                    Outside your role: {profile.access.denied_summary}
                  </div>
                )}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
                  {profile.access.departments.map((d) => (
                    <span key={d} className="chip">{d} docs</span>
                  ))}
                </div>
              </div>

              {/* Tables */}
              <div className="card" style={{ background: "var(--surface-card)", padding: "16px 18px" }}>
                <div className="label" style={{ marginBottom: 10 }}>DATA AREAS YOU CAN QUERY</div>
                {ws ? (
                  <div style={{ display: "grid", gap: 8 }}>
                    {Object.entries(ws.tables).map(([name, t]) => (
                      <div key={name} style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                        <span className="mono" style={{ fontSize: 11.5, color: "var(--accent)", minWidth: 130 }}>{name}</span>
                        <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
                          {t.row_count.toLocaleString()} rows · {t.columns.length} columns
                        </span>
                        <span style={{ fontSize: 10.5, color: "var(--muted-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {t.columns.slice(0, 5).map((c) => c.name).join(", ")}{t.columns.length > 5 ? "…" : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : <div style={{ fontSize: 12, color: "var(--muted)" }}>Loading…</div>}
              </div>

              {/* Documents */}
              <div className="card" style={{ background: "var(--surface-card)", padding: "16px 18px" }}>
                <div className="label" style={{ marginBottom: 10 }}>DOCUMENTS IN YOUR VIEW OF THE COMPANY BRAIN</div>
                {ws ? (
                  <div style={{ display: "grid", gap: 6 }}>
                    {ws.documents.map((d) => (
                      <div key={d.file} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                        <span className="chip chip-neutral" style={{ minWidth: 54, textAlign: "center" }}>{d.department}</span>
                        <span className="mono" style={{ fontSize: 11, color: "var(--body)" }}>{d.file.replace("docs/", "")}</span>
                        <span style={{ fontSize: 10, color: "var(--muted-soft)" }}>{d.chunks} chunks indexed</span>
                      </div>
                    ))}
                  </div>
                ) : <div style={{ fontSize: 12, color: "var(--muted)" }}>Loading…</div>}
              </div>
            </div>

            <div style={{ display: "grid", gap: 18 }}>
              {/* Ask CTA */}
              <div className="card" style={{ background: "var(--accent-tint)", padding: "18px 20px" }}>
                <div className="serif" style={{ fontSize: 18, marginBottom: 6 }}>Ask the analyst</div>
                <p style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.6, margin: "0 0 12px" }}>
                  Natural-language questions over your company&apos;s data. Every
                  answer ships with its SQL, citations, confidence, and trace.
                </p>
                <a href="/platform/ask" className="btn-primary" style={{ fontSize: 13 }}>Open Ask Analyst →</a>
              </div>

              {/* Admin data management */}
              {profile.is_admin && ws && (
                <div className="card" style={{ background: "var(--surface-card)", padding: "16px 18px" }}>
                  <div className="label" style={{ marginBottom: 8 }}>DATA MANAGEMENT · ADMIN/CEO ONLY</div>
                  <div style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.6 }}>
                    Connected folder: <span className="mono" style={{ fontSize: 11 }}>data/demo_companies/{profile.company.slug}/</span>
                  </div>
                  {ws.brain.changed_files && ws.brain.changed_files.length > 0 && (
                    <div style={{ fontSize: 11.5, color: "#8A5B10", marginTop: 6 }}>
                      {ws.brain.changed_files.length} source file(s) changed since last build.
                    </div>
                  )}
                  <button className="btn-ghost" onClick={doRebuild} disabled={rebuilding}
                    style={{ marginTop: 12, fontSize: 12.5, opacity: rebuilding ? 0.6 : 1 }}>
                    {rebuilding ? "Rebuilding brain…" : "⟳ Rebuild company brain"}
                  </button>
                  {rebuildLog && (
                    <div style={{ marginTop: 10, fontFamily: "var(--font-mono), monospace", fontSize: 10, background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 6, padding: "8px 10px", lineHeight: 1.6 }}>
                      {(rebuildLog.steps as { step: string; detail: unknown }[])?.map((s, i) => (
                        <div key={i}>✓ {s.step} — {typeof s.detail === "string" ? s.detail : JSON.stringify(s.detail)}</div>
                      ))}
                      <div style={{ color: "#9fd4a8" }}>workspace ready · {String(rebuildLog.duration_s)}s</div>
                    </div>
                  )}
                </div>
              )}

              {/* Honest limits */}
              <div className="card" style={{ background: "var(--surface-soft)", padding: "14px 16px" }}>
                <div className="label" style={{ marginBottom: 6 }}>PROTOTYPE BOUNDARIES</div>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: "var(--muted)", lineHeight: 1.7 }}>
                  <li>Synthetic companies and data — no real customers.</li>
                  <li>Demo registry login — not production SSO.</li>
                  <li>Company isolation enforced in one app — not full enterprise tenancy.</li>
                  <li>All employee access is read-only.</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </PlatformShell>
  );
}
