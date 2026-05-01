import { useLocation, NavLink } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const ROUTE_TITLES: Array<[RegExp, string]> = [
  [/^\/dashboard/, "Population overview"],
  [/^\/onboard/, "Onboard a patient"],
  [/^\/patients\/[^/]+/, "Patient detail"],
  [/^\/patients/, "Patients"],
  [/^\/doctor\/escalations/, "Escalation detail"],
  [/^\/doctor\/inbox/, "Doctor inbox"],
  [/^\/chat/, "Chat simulator"],
  [/^\/insights/, "Insights"],
  [/^\/prompts/, "Prompts"],
];

const MOBILE_NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/onboard", label: "Onboard" },
  { to: "/patients", label: "Patients" },
  { to: "/doctor/inbox", label: "Doctor inbox" },
  { to: "/chat", label: "Chat" },
  { to: "/insights", label: "Insights" },
  { to: "/prompts", label: "Prompts" },
];

export function TopBar() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const title = ROUTE_TITLES.find(([rx]) => rx.test(pathname))?.[1] ?? "CareLoop";

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-white/90 backdrop-blur">
      <div className="flex h-14 items-center gap-3 px-4 md:px-6">
        <button
          type="button"
          className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border text-ink-60"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle navigation"
        >
          {open ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
        </button>
        <h1 className="font-display text-base font-semibold tracking-tight text-ink-DEFAULT">
          {title}
        </h1>
      </div>

      {open && (
        <nav className="md:hidden border-t border-border bg-white px-2 py-2">
          <ul className="space-y-0.5">
            {MOBILE_NAV.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      "block rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-mint-soft text-mint-ink font-semibold"
                        : "text-ink-60 hover:bg-muted hover:text-ink-DEFAULT",
                    )
                  }
                >
                  {n.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
