"use client";

import { cn } from "@/lib/utils";
import { type TabId, useDashboardStore } from "@/lib/store";
import {
  IconDashboard,
  IconStrategy,
  IconMarkets,
  IconSettings,
} from "@/components/ui/Icons";

const TABS: { id: TabId; label: string; icon: typeof IconDashboard }[] = [
  { id: "live", label: "Live", icon: IconDashboard },
  { id: "analytics", label: "Analytics", icon: IconStrategy },
  { id: "markets", label: "Markets", icon: IconMarkets },
  { id: "control", label: "Control", icon: IconSettings },
];

export function TabBar() {
  const activeTab = useDashboardStore((s) => s.activeTab);
  const setActiveTab = useDashboardStore((s) => s.setActiveTab);

  return (
    <div className="flex items-center gap-1 border-b border-white/[0.06] bg-[var(--bg-primary)]/80 backdrop-blur-xl px-6">
      {TABS.map((tab) => {
        const active = activeTab === tab.id;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors",
              active
                ? "text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
            )}
          >
            <Icon size={16} />
            <span>{tab.label}</span>
            {active && (
              <div className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}
