import Link from "next/link";

type Door = "how" | "ask" | "context" | "reliability";

export default function TopNav({
  crumb,
  active,
}: {
  crumb?: string;
  active?: Door;
}) {
  return (
    <nav className="topnav">
      <div className="left">
        <Link href="/" className="link-accent" style={{ fontSize: 13 }}>
          ← Home
        </Link>
        <span style={{ color: "var(--hairline-mid)" }}>/</span>
        <Link href="/" className="wordmark" style={{ fontSize: 15 }}>
          Nexus<span>IQ</span>
        </Link>
        {crumb && <span className="breadcrumb">· {crumb}</span>}
      </div>
      <div className="doors">
        <Link href="/how" className={active === "how" ? "active" : ""}>
          How it works
        </Link>
        <Link href="/context" className={active === "context" ? "active" : ""}>
          Context
        </Link>
        <Link href="/reliability" className={active === "reliability" ? "active" : ""}>
          Reliability
        </Link>
        <Link href="/ask" className={active === "ask" ? "active" : ""}>
          Ask Nexus
        </Link>
      </div>
    </nav>
  );
}
