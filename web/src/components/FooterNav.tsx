import Link from "next/link";

export default function FooterNav({
  prevHref = "/",
  prevLabel = "Home",
  nextHref,
  nextLabel,
}: {
  prevHref?: string;
  prevLabel?: string;
  nextHref?: string;
  nextLabel?: string;
}) {
  return (
    <div className="footernav">
      <Link href={prevHref} style={{ fontSize: 13, color: "var(--muted)" }}>
        ← {prevLabel}
      </Link>
      {nextHref && nextLabel && (
        <Link href={nextHref} className="btn-primary" style={{ fontSize: 13, padding: "9px 18px" }}>
          {nextLabel} →
        </Link>
      )}
    </div>
  );
}
