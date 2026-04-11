"use client";

import { type TabId, useDashboardStore } from "@/lib/store";

const TABS: { id: TabId; label: string; emoji: string }[] = [
  { id: "live", label: "Live", emoji: "📊" },
  { id: "analytics", label: "Analytics", emoji: "📈" },
  { id: "markets", label: "Markets", emoji: "🎯" },
  { id: "control", label: "Control", emoji: "⚙️" },
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
            className={`relative flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors ${
              active
                ? "text-primary"
                : "text-muted hover:text-secondary"
            }`}
          >
            <span className="text-base">{tab.emoji}</span>
            <span>{tab.label}</span>
            {active && (
              <div className="absolute bottom-0 left-1 right-1 h-[2px] rounded-full bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}
