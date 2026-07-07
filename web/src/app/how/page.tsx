import TopNav from "@/components/TopNav";
import FooterNav from "@/components/FooterNav";
import DataExplorer from "@/components/DataExplorer";
import AgentsPipeline from "@/components/AgentsPipeline";

export default function HowPage() {
  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <TopNav crumb="HOW IT WORKS" active="how" />

      <div style={{ position: "relative", paddingTop: 20 }}>
        {/* section 01 — the data */}
        <div className="eyebrow" style={{ marginBottom: 8 }}>● 01 — What Nexus knows</div>
        <h1 className="serif" style={{ fontSize: 29, margin: "0 0 8px" }}>What Nexus knows</h1>
        <p style={{ fontSize: 13.5, color: "var(--muted)", margin: "0 0 18px", maxWidth: 520 }}>
          Every answer starts from real, inspectable data — a live database, a document
          library in six formats, and the open web. Click a source to look inside.
        </p>
        <DataExplorer />

        {/* section 02 — the agents */}
        <div id="agents" style={{ borderTop: "1px solid var(--hairline-strong)", marginTop: 40, paddingTop: 24, scrollMarginTop: 20 }}>
          <AgentsPipeline />
        </div>
      </div>

      <div style={{ flex: 1 }} />
      <FooterNav prevHref="/" prevLabel="Home" nextHref="/ask" nextLabel="Next: Ask Nexus" />
    </main>
  );
}
