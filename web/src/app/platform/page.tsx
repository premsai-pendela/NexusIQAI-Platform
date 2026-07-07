"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Mascot from "@/components/Mascot";
import { getToken, login } from "@/lib/platform";

/* Platform login. Honest prototype: a demo employee registry, not SSO.
   Demo accounts are listed right on the page so reviewers can explore. */

const DEMO_ACCOUNTS = [
  { email: "admin@acmecloud.test", password: "demo-admin-2026", role: "Admin", company: "AcmeCloud Analytics" },
  { email: "analyst@acmecloud.test", password: "demo-analyst-2026", role: "Analyst", company: "AcmeCloud Analytics" },
  { email: "hr@acmecloud.test", password: "demo-hr-2026", role: "HR", company: "AcmeCloud Analytics" },
  { email: "ceo@medcore.test", password: "demo-ceo-2026", role: "CEO", company: "MedCore Systems" },
  { email: "finance@medcore.test", password: "demo-finance-2026", role: "Finance", company: "MedCore Systems" },
  { email: "ops@finpilot.test", password: "demo-ops-2026", role: "Ops", company: "FinPilot Ops" },
];

export default function PlatformLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (getToken()) router.replace("/platform/workspace");
  }, [router]);

  const doLogin = async (e?: string, p?: string) => {
    const em = e ?? email;
    const pw = p ?? password;
    if (!em || !pw || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(em, pw);
      router.push("/platform/workspace");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", position: "relative", minHeight: "100vh" }}>
      <nav className="topnav">
        <div className="left">
          <span className="wordmark">NexusIQ<span>AI</span></span>
          <span className="breadcrumb">PLATFORM · EMPLOYEE LOGIN</span>
        </div>
        <div className="doors">
          <a href="/">← NexusIQ home</a>
        </div>
      </nav>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 48, padding: "56px 0", alignItems: "start" }}>
        <div>
          <div className="eyebrow" style={{ marginBottom: 10 }}>MULTI-COMPANY AI DATA ANALYST</div>
          <h1 className="serif" style={{ fontSize: 34, lineHeight: 1.25, margin: "0 0 14px" }}>
            Sign in to your company workspace.
          </h1>
          <p style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.7, maxWidth: 460, margin: "0 0 18px" }}>
            Your company&apos;s data brain is already built. Log in with your work
            email and NexusIQ routes you to your company&apos;s workspace, where you
            can query exactly the data your role allows — with SQL, citations,
            charts, and a full trace for every answer.
          </p>
          <div className="card" style={{ padding: "12px 16px", maxWidth: 460, background: "var(--surface-soft)" }}>
            <div className="label" style={{ marginBottom: 8 }}>DEMO ACCOUNTS · SYNTHETIC COMPANIES · PROTOTYPE LOGIN, NOT SSO</div>
            <div style={{ display: "grid", gap: 5 }}>
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.email}
                  onClick={() => doLogin(a.email, a.password)}
                  style={{ display: "flex", gap: 8, alignItems: "baseline", background: "none", border: "none", cursor: "pointer", padding: "3px 0", textAlign: "left" }}
                >
                  <span className="mono" style={{ fontSize: 11, color: "var(--accent)", minWidth: 210 }}>{a.email}</span>
                  <span className="chip chip-neutral">{a.role}</span>
                  <span style={{ fontSize: 11, color: "var(--muted-soft)" }}>{a.company}</span>
                </button>
              ))}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--muted-soft)", marginTop: 8 }}>
              Click any account to sign in instantly.
            </div>
          </div>
        </div>

        <div className="card" style={{ background: "var(--surface-card)", padding: "28px 30px", maxWidth: 400, justifySelf: "end", width: "100%" }}>
          <div className="serif" style={{ fontSize: 20, marginBottom: 16 }}>Employee sign in</div>
          <label className="label">WORK EMAIL</label>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.test"
            autoComplete="username"
            style={{ width: "100%", margin: "4px 0 14px", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 13.5, color: "var(--ink)", outline: "none", fontFamily: "var(--font-sans), sans-serif" }}
          />
          <label className="label">PASSWORD</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doLogin()}
            placeholder="demo password"
            autoComplete="current-password"
            style={{ width: "100%", margin: "4px 0 18px", padding: "10px 12px", borderRadius: 8, border: "1px solid var(--hairline-mid)", background: "var(--surface-soft)", fontSize: 13.5, color: "var(--ink)", outline: "none", fontFamily: "var(--font-sans), sans-serif" }}
          />
          {error && (
            <div style={{ fontSize: 12, color: "#A32D2D", marginBottom: 12 }}>{error}</div>
          )}
          <button className="btn-primary" onClick={() => doLogin()} disabled={busy} style={{ width: "100%", opacity: busy ? 0.6 : 1 }}>
            {busy ? "Signing in…" : "Enter workspace →"}
          </button>
          <div style={{ fontSize: 10.5, color: "var(--muted-soft)", marginTop: 12, lineHeight: 1.5 }}>
            Prototype boundaries: synthetic company data, demo credentials,
            read-only analyst access. Employees see their own company only.
          </div>
        </div>
      </div>

      <Mascot
        greeting="Hi! This is the NexusIQAI platform prototype — a demo employee registry, not real SSO. Pick a demo account to see how each role gets a different slice of the company brain."
        onClickSay="Try analyst@acmecloud.test for revenue questions, hr@acmecloud.test for workforce questions — then ask each one the other's question and watch the polite refusal."
        size={72}
      />
    </main>
  );
}
