// The Nexus mascot artwork (v1 placeholder — see DESIGN.md).
export default function MascotSvg({ size = 80 }: { size?: number }) {
  const h = Math.round((size * 110) / 96);
  return (
    <svg width={size} height={h} viewBox="0 0 96 110" aria-label="Nexus mascot">
      <ellipse cx="48" cy="104" rx="24" ry="5" fill="#000" opacity="0.08" />
      <line x1="48" y1="20" x2="48" y2="8" stroke="var(--mascot-deep)" strokeWidth="3" />
      <circle cx="48" cy="6" r="5" fill="var(--mascot-antenna)" />
      <rect x="14" y="20" width="68" height="72" rx="26" fill="var(--mascot)" />
      <rect x="24" y="34" width="48" height="34" rx="17" fill="var(--mascot-face)" />
      <circle cx="38" cy="50" r="6" fill="var(--ink)" />
      <circle cx="58" cy="50" r="6" fill="var(--ink)" />
      <circle cx="40" cy="48" r="2" fill="#fff" />
      <circle cx="60" cy="48" r="2" fill="#fff" />
      <path d="M40 60 Q48 66 56 60" stroke="var(--mascot-deep)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <ellipse cx="10" cy="54" rx="6" ry="9" fill="var(--mascot)" />
      <ellipse cx="86" cy="54" rx="6" ry="9" fill="var(--mascot)" />
      <ellipse cx="37" cy="98" rx="7" ry="9" fill="var(--mascot-deep)" />
      <ellipse cx="59" cy="98" rx="7" ry="9" fill="var(--mascot-deep)" />
    </svg>
  );
}
