"use client";

import { useEffect } from "react";
import { useDashboardStore, type TabId } from "@/lib/store";
import { LiveTab } from "./_tabs/LiveTab";
import { AnalyticsTab } from "./_tabs/AnalyticsTab";
import { MarketsTab } from "./_tabs/MarketsTab";
import { ControlTab } from "./_tabs/ControlTab";

export default function DashboardPage() {
  const activeTab = useDashboardStore((s) => s.activeTab);
  const setActiveTab = useDashboardStore((s) => s.setActiveTab);

  useEffect(() => {
    const handler = (e: Event) => {
      const tab = (e as CustomEvent).detail as TabId;
      if (tab) setActiveTab(tab);
    };
    window.addEventListener("ja-switch-tab", handler);
    return () => window.removeEventListener("ja-switch-tab", handler);
  }, [setActiveTab]);

  return (
    <>
      {activeTab === "live" && <LiveTab />}
      {activeTab === "analytics" && <AnalyticsTab />}
      {activeTab === "markets" && <MarketsTab />}
      {activeTab === "control" && <ControlTab />}
    </>
  );
}

