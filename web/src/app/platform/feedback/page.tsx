"use client";
import { useState } from "react";
import PlatformShell from "@/components/PlatformShell";
import { submitFeedback } from "@/lib/platform";

/* Employee feedback: complaints, wrong answers, access requests,
   suggestions. Saved with company/employee/role/timestamp; reviewed by the
   company's Admin/CEO in Review. */

const CATEGORIES = [
  { value: "issue", label: "Issue / complaint" },
  { value: "wrong-answer", label: "Wrong answer report" },
  { value: "access-request", label: "Missing data / access request" },
  { value: "confusing-output", label: "Confusing chart or report" },
  { value: "suggestion", label: "Improvement suggestion" },
];

export default function FeedbackPage() {
  const [category, setCategory] = useState(CATEGORIES[0].value);
  const [message, setMessage] = useState("");
  const [traceId, setTraceId] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (message.trim().length < 3 || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const out = await submitFeedback({
        category,
        message: message.trim(),
        page: "feedback",
        trace_id: traceId.trim() || undefined,
      });
      setDone(out.feedback_id);
      setMessage("");
      setTraceId("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not submit feedback");
    } finally {
      setBusy(false);
    }
  };

  return (
    <PlatformShell
      botGreeting={() =>
        "Something wrong, missing, or confusing? Tell your company's Admin here. If it's about a specific answer, paste the trace id from the Access & trace panel so they can replay exactly what happened."}
    >
      {(profile) => (
        <div style={{ padding: "30px 0 80px", maxWidth: 560 }}>
          <h1 className="serif" style={{ fontSize: 26, margin: "0 0 6px" }}>Feedback & requests</h1>
          <p style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.65, margin: "0 0 20px" }}>
            Goes to {profile.company.name}&apos;s Admin/CEO review queue with your
            name, role, and timestamp — and the linked trace if you include one.
          </p>

          <div className="card" style={{ background: "var(--surface-card)", padding: "20px 22px" }}>
            <label className="label">CATEGORY</label>
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              style={{ display: "block", width: "100%", margin: "4px 0 14px", padding: "9px 10px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 13, color: "var(--ink)", fontFamily: "var(--font-sans), sans-serif" }}>
              {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>

            <label className="label">WHAT HAPPENED?</label>
            <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5}
              placeholder="Describe the issue, the answer that looked wrong, or the data you need access to…"
              style={{ display: "block", width: "100%", margin: "4px 0 14px", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 13, color: "var(--ink)", outline: "none", resize: "vertical", fontFamily: "var(--font-sans), sans-serif", lineHeight: 1.5 }} />

            <label className="label">RELATED TRACE ID · OPTIONAL</label>
            <input value={traceId} onChange={(e) => setTraceId(e.target.value)} placeholder="tr_…"
              style={{ display: "block", width: "100%", margin: "4px 0 18px", padding: "9px 12px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 12.5, color: "var(--ink)", outline: "none", fontFamily: "var(--font-mono), monospace" }} />

            {err && <div style={{ fontSize: 12, color: "#A32D2D", marginBottom: 10 }}>{err}</div>}
            {done && (
              <div style={{ fontSize: 12, color: "var(--success-text)", marginBottom: 10 }}>
                ✓ Submitted as <span className="mono">{done}</span> — your Admin will see it in Review.
              </div>
            )}
            <button className="btn-primary" onClick={submit} disabled={busy || message.trim().length < 3}
              style={{ opacity: busy || message.trim().length < 3 ? 0.6 : 1 }}>
              {busy ? "Sending…" : "Submit to Admin →"}
            </button>
          </div>
        </div>
      )}
    </PlatformShell>
  );
}
