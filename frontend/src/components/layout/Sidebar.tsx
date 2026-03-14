"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  IconDashboard,
  IconBrain,
  IconMarkets,
  IconTrading,
  IconPortfolio,
  IconAgent,
  IconAI,
  IconShield,
  IconSettings,
  IconSports,
  IconStrategy,
} from "@/components/ui/Icons";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Overview", icon: IconDashboard },
  { href: "/dashboard/frankenstein", label: "Frankenstein", icon: IconBrain },
  { href: "/dashboard/strategies", label: "Strategies", icon: IconStrategy },
  { href: "/dashboard/sports", label: "Sports", icon: IconSports },
  { href: "/dashboard/markets", label: "Markets", icon: IconMarkets },
  { href: "/dashboard/trading", label: "Trading", icon: IconTrading },
  { href: "/dashboard/portfolio", label: "Portfolio", icon: IconPortfolio },
  { href: "/dashboard/agent", label: "AI Agent", icon: IconAgent },
  { href: "/dashboard/ai", label: "AI Engine", icon: IconAI },
  { href: "/dashboard/risk", label: "Risk", icon: IconShield },
  { href: "/dashboard/settings", label: "Settings", icon: IconSettings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-screen w-64 flex-col glass-strong">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 px-6">
        {/* Animated logo mark */}
        <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent/20 to-accent/5 border border-accent/20">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-accent">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" fill="currentColor" opacity="0.9" />
          </svg>
          <div className="absolute inset-0 rounded-xl animate-pulse-glow" />
        </div>
        <div>
          <span className="text-base font-bold tracking-tight text-[var(--text-primary)]">JA Hedge</span>
          <span className="ml-1.5 inline-flex items-center rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] font-semibold text-accent tracking-wider">
            AI
          </span>
        </div>
      </div>

      {/* Divider */}
      <div className="mx-5 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href ||
              (item.href !== "/dashboard" && pathname.startsWith(item.href));
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                    active
                      ? "text-accent"
                      : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
                  )}
                >
                  {/* Active background */}
                  {active && (
                    <div className="absolute inset-0 rounded-xl bg-accent/[0.08] border border-accent/[0.12]" />
                  )}
                  {/* Hover background */}
                  {!active && (
                    <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-200 bg-white/[0.02]" />
                  )}
                  {/* Active indicator bar */}
                  {active && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent" />
                  )}

                  <Icon size={18} className="relative z-10 shrink-0" />
                  <span className="relative z-10">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Divider */}
      <div className="mx-5 h-px bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />

      {/* Status footer */}
      <div className="p-4">
        <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-50" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
            </span>
            <span className="text-xs font-medium text-[var(--text-muted)]">Demo Mode</span>
          </div>
          <p className="mt-1 text-[10px] text-[var(--text-muted)]/60 leading-tight">
            Paper trading — no real funds
          </p>
        </div>
      </div>
    </aside>
  );
}
