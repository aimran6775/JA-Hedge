"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: "📊" },
  { href: "/dashboard/frankenstein", label: "Frankenstein", icon: "🧟" },
  { href: "/dashboard/markets", label: "Markets", icon: "🏛️" },
  { href: "/dashboard/trading", label: "Trading", icon: "⚡" },
  { href: "/dashboard/portfolio", label: "Portfolio", icon: "💰" },
  { href: "/dashboard/agent", label: "AI Agent", icon: "🧠" },
  { href: "/dashboard/ai", label: "AI Engine", icon: "🤖" },
  { href: "/dashboard/risk", label: "Risk", icon: "🛡️" },
  { href: "/dashboard/settings", label: "Settings", icon: "⚙️" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-30 flex h-screen w-60 flex-col border-r border-[var(--card-border)] bg-[var(--card)]">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-[var(--card-border)] px-4">
        <span className="text-xl font-bold text-white">JA</span>
        <span className="text-sm text-[var(--muted)]">Hedge</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const active =
              pathname === item.href ||
              (item.href !== "/dashboard" &&
                pathname.startsWith(item.href));

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-[var(--accent)]/10 text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-white/5 hover:text-white",
                  )}
                >
                  <span className="text-base">{item.icon}</span>
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Status footer */}
      <div className="border-t border-[var(--card-border)] p-3">
        <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
          <span className="h-2 w-2 rounded-full bg-green-500" />
          Demo Mode
        </div>
      </div>
    </aside>
  );
}
