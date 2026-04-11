"use client";

import { type TabId, useDashboardStore } from "@/lib/store";

const TABS: { id: TabId; label: string }[] = [
  { id: "live", label: "Live" },
  { id: "analytics", label: "Analytics" },
  { id: "markets", label: "Markets" },
  { id: "control", label: "Control" },
];

export function TabBar() {
  const activeTab = useDashboardStore((s) => s.activeTab);
  const setActiveTab = useDashboardStore((s) => s.setActiveTab);

  return (
    <div className="flex items-center gap-0.5 border-b border-white/[0.04] bg-[var(--bg-primary)]/60 backdrop-blur-xl px-4">
      {TABS.map((tab) => {
        const active = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`relative px-4 py-2.5 text-sm font-medium transition-colors ${
              active
                ? "text-primary"
                : "text-muted hover:text-secondary"
            }`}
          >
            {tab.label}
            {active && (
              <div className="absolute bottom-0 left-1 right-1 h-[2px] rounded-full bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}
