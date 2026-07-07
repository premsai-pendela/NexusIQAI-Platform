"use client";
import { useEffect, useState } from "react";
import TopNav from "@/components/TopNav";
import FooterNav from "@/components/FooterNav";
import { LearningLoop, RecallResult, RepairProposal, fetchLearningLoop, fetchRecall } from "@/lib/api";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ background: "var(--surface-soft)", border: "0.5px solid var(--hairline)", borderRadius: 10, padding: "9px 13px" }}>
      <div className="serif" style={{ fontSize: 18, lineHeight: 1.1 }}>{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}

const STATUS_LABELS: Record<string, string> = {
  proposed: "proposed",
  eval_pending: "awaiting eval",
  verified: "verified by eval",
  rejected: "rejected",
  adopted: "adopted (human-approved)",
};

function evalRate(evidence: Record<string, unknown> | null): string {
  const rate = evidence?.["hit_rate"];
  if (typeof rate === "number") return `${(rate * 100).toFixed(1)}%`;
  const tests = evidence?.["tests"];
  if (typeof tests === "number") return `${tests} tests`;
  return "—";
}

function evalCaption(evidence: Record<string, unknown> | null): string {
  if (evidence && typeof evidence["hit_rate"] === "number") {
    const misses = Array.isArray(evidence["misses"]) ? (evidence["misses"] as string[]).length : 0;
    return `hit rate · ${misses} miss(es)`;
  }
  const live = evidence?.["live_check"];
  return typeof live === "string" ? live : "no evidence attached";
}

function ProposalCard({ proposal }: { proposal: RepairProposal }) {
  return (
    <div className="card" style={{ padding: "16px 18px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
        <span className="serif" style={{ fontSize: 15 }}>{proposal.title}</span>
        <span className={proposal.status === "verified" || proposal.status === "adopted" ? "chip" : "chip chip-neutral"}>
          {STATUS_LABELS[proposal.status] ?? proposal.status}
        </span>
      </div>
      <p style={{ fontSize: 12.5, color: "var(--body)", margin: "8px 0", lineHeight: 1.6 }}>{proposal.description}</p>

      {(proposal.eval_before || proposal.eval_after) && (
        <div style={{ display: "flex", gap: 10, margin: "10px 0" }}>
          <div style={{ flex: 1, background: "var(--chip-neutral-bg)", borderRadius: 8, padding: "8px 12px" }}>
            <div className="label">EVAL BEFORE</div>
            <div className="mono" style={{ fontSize: 15 }}>{evalRate(proposal.eval_before)}</div>
            <div style={{ fontSize: 11, color: "var(--muted-soft)" }}>
              {evalCaption(proposal.eval_before)}
            </div>
          </div>
          <div style={{ flex: 1, background: "var(--success-bg)", borderRadius: 8, padding: "8px 12px" }}>
            <div className="label">EVAL AFTER</div>
            <div className="mono" style={{ fontSize: 15, color: "var(--success-text)" }}>{evalRate(proposal.eval_after)}</div>
            <div style={{ fontSize: 11, color: "var(--muted-soft)" }}>
              {evalCaption(proposal.eval_after)}
            </div>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: "var(--muted-soft)" }}>
        {proposal.proposal_id} · fixes {proposal.failure_ids.join(", ")} ·{" "}
        {proposal.human_approved ? `approved by ${proposal.approved_by}` : "adoption requires human approval"}
      </div>

      {proposal.history.length > 0 && (
        <div style={{ marginTop: 10, borderTop: "0.5px solid var(--hairline)", paddingTop: 8 }}>
          {proposal.history.map((h, i) => (
            <div key={i} style={{ fontSize: 11.5, color: "var(--muted)", lineHeight: 1.7 }}>
              <span className="mono" style={{ fontSize: 10.5 }}>{h.at}</span>
              {" "}{h.from} → <span style={{ color: "var(--accent)" }}>{h.to}</span>
              {h.note && <span style={{ fontStyle: "italic" }}> — {h.note}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


function RecallBox() {
  const [q, setQ] = useState("Which SKUs have a high sell-through rate?");
  const [result, setResult] = useState<RecallResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try { setResult(await fetchRecall(q)); } catch { setResult(null); }
    setBusy(false);
  };

  return (
    <div className="card" style={{ padding: "16px 18px", marginBottom: 26 }}>
      <div className="label" style={{ marginBottom: 8 }}>FAILURE MEMORY — HAS A QUESTION LIKE THIS FAILED BEFORE?</div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, padding: "8px 12px", border: "1px solid var(--hairline-mid)", borderRadius: 8, background: "var(--surface-soft)", fontSize: 13 }}
        />
        <button className="btn-primary" style={{ fontSize: 13, padding: "8px 16px" }} onClick={run} disabled={busy}>
          {busy ? "…" : "Recall"}
        </button>
      </div>
      {result && result.matches.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "10px 0 0" }}>No similar past failure on record.</p>
      )}
      {result && result.matches.map((m) => (
        <div key={m.failure_id} style={{ marginTop: 10, borderTop: "0.5px solid var(--hairline)", paddingTop: 8, fontSize: 12.5 }}>
          <span className="mono" style={{ fontSize: 11.5, color: "var(--accent)" }}>{m.failure_kind}</span>
          {" "}&ldquo;{m.question}&rdquo;
          <span style={{ color: "var(--muted-soft)" }}> · shares: {m.shared_terms.join(", ")}</span>
          {m.repairs.map((r) => (
            <div key={r.proposal_id} style={{ fontSize: 11.5, color: "var(--muted)" }}>
              ↳ repair <span className="mono">{r.proposal_id}</span> — {r.title} · <b>{r.status}</b>
            </div>
          ))}
        </div>
      ))}
      <p style={{ fontSize: 11, color: "var(--muted-soft)", fontStyle: "italic", margin: "10px 0 0" }}>
        Deterministic keyword recall over the live failure store — no similarity model, no LLM.
      </p>
    </div>
  );
}

function OfflineCard() {
  return (
    <div className="card" style={{ padding: "22px 24px", marginTop: 18 }}>
      <div className="eyebrow" style={{ marginBottom: 6 }}>● backend offline</div>
      <p style={{ fontSize: 13.5, color: "var(--muted)", margin: 0, maxWidth: 560 }}>
        This page renders only live data from <span className="mono">GET /api/v1/learning</span>.
        Start the backend to see the real loop state:
      </p>
      <pre style={{ background: "var(--code-bg)", color: "var(--code-text)", borderRadius: 8, padding: "10px 14px", fontSize: 12, marginTop: 12 }}>
        uvicorn api.main:app --port 8000
      </pre>
    </div>
  );
}

export default function ReliabilityPage() {
  const [data, setData] = useState<LearningLoop | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchLearningLoop().then(setData).catch(() => setFailed(true));
  }, []);

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <TopNav crumb="RELIABILITY" active="reliability" />

      <div style={{ position: "relative", paddingTop: 20 }}>
        <div className="eyebrow" style={{ marginBottom: 8 }}>● 01 — Agents that learn from failures, under evals</div>
        <h1 className="serif" style={{ fontSize: 29, margin: "0 0 8px" }}>When Nexus gets something wrong, it learns</h1>
        <p style={{ fontSize: 13.5, color: "var(--muted)", margin: "0 0 18px", maxWidth: 640 }}>
          Every miss is kept, not hidden. A failed answer becomes a record, the record becomes a repair
          proposal, and a proposal only counts as <em>verified</em> once the benchmark proves the fix —
          then a human signs off before it is adopted. Everything below is the live state of that loop.
        </p>

        {failed && <OfflineCard />}

        {data && (
          <>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 22 }}>
              <Stat value={String(data.stats.failure_records)} label="FAILURE RECORDS" />
              <Stat value={String(data.stats.repair_proposals)} label="REPAIR PROPOSALS" />
              <Stat value={String(data.stats.proposals_by_status["verified"] ?? 0)} label="VERIFIED BY EVAL" />
              <Stat value={String(data.stats.proposals_by_status["adopted"] ?? 0)} label="ADOPTED (HUMAN-APPROVED)" />
            </div>

            <RecallBox />

            {/* governance */}
            <div className="card" style={{ padding: "14px 18px", marginBottom: 26 }}>
              <div className="label" style={{ marginBottom: 6 }}>GOVERNANCE — WHAT KEEPS THIS HONEST</div>
              <div style={{ fontSize: 12.5, color: "var(--body)", lineHeight: 1.7 }}>
                <div><span style={{ color: "var(--accent)" }}>classification</span> — {data.governance.classification}</div>
                <div><span style={{ color: "var(--accent)" }}>verification</span> — {data.governance.verification}</div>
                <div><span style={{ color: "var(--accent)" }}>adoption</span> — {data.governance.adoption}</div>
              </div>
            </div>

            <div className="eyebrow" style={{ marginBottom: 8 }}>● 02 — Repair queue</div>
            <div style={{ display: "grid", gap: 12, marginBottom: 26 }}>
              {data.repair_queue.length === 0 && (
                <p style={{ fontSize: 13, color: "var(--muted)" }}>Queue is empty.</p>
              )}
              {data.repair_queue.map((p) => <ProposalCard key={p.proposal_id} proposal={p} />)}
            </div>

            <div className="eyebrow" style={{ marginBottom: 8 }}>● 03 — Failure records (from real traces and eval runs)</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 26 }}>
              {data.failure_records.map((f) => (
                <div key={f.failure_id} className="card" style={{ padding: "13px 16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span className="mono" style={{ fontSize: 12, color: "var(--accent)" }}>{f.failure_kind}</span>
                    <span className="chip chip-neutral">{f.source}</span>
                  </div>
                  <p style={{ fontSize: 12.5, color: "var(--body)", margin: "6px 0 4px" }}>&ldquo;{f.question}&rdquo;</p>
                  {f.suggested_repair && (
                    <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "4px 0", fontStyle: "italic" }}>
                      suggested: {f.suggested_repair}
                    </p>
                  )}
                  <div style={{ fontSize: 10.5, color: "var(--muted-soft)" }} className="mono">
                    {f.failure_id}{f.trace_id ? ` · trace ${f.trace_id}` : ""} · {f.detected_at}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <div style={{ flex: 1 }} />
      <FooterNav prevHref="/context" prevLabel="Context" nextHref="/ask" nextLabel="Next: Ask Nexus" />
    </main>
  );
}
