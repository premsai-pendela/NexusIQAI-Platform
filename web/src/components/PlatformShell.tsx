"use client";
import { useEffect, useMemo, useSyncExternalStore, ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import Mascot from "./Mascot";
import { Profile, logout } from "@/lib/platform";

/* Session state via useSyncExternalStore: server snapshot is empty (page
   renders nothing during prerender), client snapshot reads localStorage. */
function subscribeStorage(cb: () => void) {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}
const readToken = () => localStorage.getItem("nexusiq_platform_token") ?? "";
const readProfile = () => localStorage.getItem("nexusiq_platform_profile") ?? "";
const empty = () => "";

/* Shared chrome for platform pages: workspace nav, role chip, page-aware
   Nexus bot. Redirects to login when no session exists. */

const NAV = [
  { href: "/platform/workspace", label: "Workspace" },
  { href: "/platform/ask", label: "Ask Analyst" },
  { href: "/platform/feedback", label: "Feedback" },
];

const ADMIN_NAV = [{ href: "/platform/admin", label: "Review" }];

export default function PlatformShell({
  children,
  botGreeting,
  botOnClick,
  botTips,
}: {
  children: ReactNode | ((profile: Profile) => ReactNode);
  botGreeting: (p: Profile) => string;
  botOnClick?: (p: Profile) => string;
  botTips?: (p: Profile) => string[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const token = useSyncExternalStore(subscribeStorage, readToken, empty);
  const profileJson = useSyncExternalStore(subscribeStorage, readProfile, empty);
  const profile = useMemo<Profile | null>(
    () => (profileJson ? (JSON.parse(profileJson) as Profile) : null),
    [profileJson]
  );

  useEffect(() => {
    // Read localStorage directly: during hydration the store still returns
    // the (empty) server snapshot, which must not trigger a redirect.
    if (!localStorage.getItem("nexusiq_platform_token")) router.replace("/platform");
  }, [token, router]);

  if (!token || !profile) return null;

  const links = [...NAV, ...(profile.is_admin ? ADMIN_NAV : [])];

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "0 40px", position: "relative", minHeight: "100vh" }}>
      <nav className="topnav">
        <div className="left">
          <span className="wordmark">
            NexusIQ<span>AI</span>
          </span>
          <span className="breadcrumb">PLATFORM · {profile.company.name.toUpperCase()}</span>
        </div>
        <div className="doors">
          {links.map((l) => (
            <a key={l.href} href={l.href} className={pathname === l.href ? "active" : ""}>
              {l.label}
            </a>
          ))}
          <span className="chip chip-neutral" style={{ alignSelf: "center", fontSize: 10 }}>
            {profile.name} · {profile.role}
          </span>
          <a
            href="/platform"
            onClick={(e) => {
              e.preventDefault();
              logout();
              router.replace("/platform");
            }}
            style={{ color: "var(--mono-accent)" }}
          >
            Sign out
          </a>
        </div>
      </nav>

      {typeof children === "function" ? children(profile) : children}

      <Mascot
        greeting={botGreeting(profile)}
        onClickSay={botOnClick ? botOnClick(profile) : undefined}
        tips={botTips ? botTips(profile) : undefined}
        size={70}
      />
    </main>
  );
}
