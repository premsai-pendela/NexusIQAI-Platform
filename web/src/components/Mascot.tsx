"use client";
import { useEffect, useRef, useState } from "react";
import MascotSvg from "./MascotSvg";

// Floating Nexus guide. Flies in, greets once, then rests. Anti-Clippy:
// dismissable, mutable, click to re-speak. Clicking cycles through page tips
// so the bot stays useful without ever interrupting. See DESIGN.md.
export default function Mascot({
  greeting,
  onClickSay,
  tips,
  size = 78,
}: {
  greeting: string;
  onClickSay?: string;
  tips?: string[];
  size?: number;
}) {
  const [flown, setFlown] = useState(false);
  const [bubble, setBubble] = useState(false);
  const [muted, setMuted] = useState(false);
  const [text, setText] = useState(greeting);
  const tipIndex = useRef(0);
  const sayings = [...(onClickSay ? [onClickSay] : []), ...(tips || [])];
  const t1 = useRef<ReturnType<typeof setTimeout> | null>(null);
  const t2 = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    t1.current = setTimeout(() => setFlown(true), 450);
    t2.current = setTimeout(() => setBubble(true), 1050);
    return () => {
      if (t1.current) clearTimeout(t1.current);
      if (t2.current) clearTimeout(t2.current);
    };
  }, []);

  return (
    <div style={{ position: "absolute", right: 24, bottom: 20, zIndex: 5 }}>
      {bubble && !muted && (
        <div
          style={{
            position: "absolute",
            right: 62,
            bottom: 40,
            width: 180,
            background: "#fffdf8",
            border: "1px solid var(--hairline)",
            borderRadius: 14,
            padding: "11px 13px",
            fontSize: 12.5,
            lineHeight: 1.45,
            color: "var(--ink)",
            boxShadow: "0 6px 20px rgba(80,60,30,.12)",
          }}
        >
          <button
            aria-label="dismiss Nexus"
            onClick={() => setBubble(false)}
            style={{
              position: "absolute",
              top: 5,
              right: 7,
              background: "none",
              border: "none",
              color: "#b8ae98",
              fontSize: 14,
              cursor: "pointer",
              lineHeight: 1,
            }}
          >
            ×
          </button>
          {text}
          <div
            style={{
              position: "absolute",
              right: 22,
              bottom: -7,
              width: 14,
              height: 14,
              background: "#fffdf8",
              borderRight: "1px solid var(--hairline)",
              borderBottom: "1px solid var(--hairline)",
              transform: "rotate(45deg)",
            }}
          />
        </div>
      )}

      <button
        onClick={() => {
          if (muted) setMuted(false);
          if (sayings.length > 0) {
            setText(sayings[tipIndex.current % sayings.length]);
            tipIndex.current += 1;
          } else {
            setText(greeting);
          }
          setBubble(true);
        }}
        aria-label="Nexus — click to speak"
        style={{
          background: "none",
          border: "none",
          padding: 0,
          cursor: "pointer",
          opacity: flown ? 1 : 0,
          transform: flown ? "translate(0,0)" : "translate(60px,60px)",
          transition: "all .6s cubic-bezier(.2,.8,.25,1)",
          animation: flown ? "nq-bob 2.8s ease-in-out infinite" : "none",
        }}
      >
        <MascotSvg size={size} />
      </button>

      <button
        onClick={() => {
          setMuted((m) => !m);
          if (!muted) setBubble(false);
        }}
        style={{
          position: "absolute",
          right: 0,
          bottom: -18,
          background: "none",
          border: "none",
          fontFamily: "var(--font-mono), monospace",
          fontSize: 9,
          color: "var(--muted-soft)",
          cursor: "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {muted ? "wake Nexus" : "mute Nexus"}
      </button>

      <style>{`@keyframes nq-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}`}</style>
    </div>
  );
}
