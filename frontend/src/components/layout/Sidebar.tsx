import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  UserPlus,
  Users,
  Inbox,
  BarChart3,
  Sliders,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/onboard", label: "Onboard", icon: UserPlus },
  { to: "/patients", label: "Patients", icon: Users },
  { to: "/doctor/inbox", label: "Doctor inbox", icon: Inbox },
  { to: "/insights", label: "Insights", icon: BarChart3 },
  { to: "/prompts", label: "Prompts", icon: Sliders },
];

export function Sidebar() {
  return (
    <aside
      className="hidden md:flex md:w-60 md:shrink-0 md:flex-col"
      style={{ background: "#0E1116" }}
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#5FCBA0]">
          <span className="text-sm font-bold text-[#0E1116]">C</span>
        </div>
        <span
          className="text-lg font-bold tracking-tight"
          style={{ color: "#ffffff", fontFamily: "'Manrope', 'Inter', sans-serif" }}
        >
          CareLoop
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 pb-4">
        <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest" style={{ color: "#697383" }}>
          Navigation
        </p>
        <ul className="space-y-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
                    isActive
                      ? "bg-[#5FCBA0]/20 text-[#A8E6C9]"
                      : "text-[#b0b8c5] hover:bg-white/5 hover:text-white",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      className="h-4 w-4 shrink-0"
                      style={{ color: isActive ? "#5FCBA0" : "inherit" }}
                    />
                    <span>{label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="px-5 py-4 border-t border-white/5">
        <p className="text-[11px]" style={{ color: "#697383" }}>
          Care coordination · v1.0
        </p>
      </div>
    </aside>
  );
}
