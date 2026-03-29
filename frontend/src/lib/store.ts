"use client";

import { create } from "zustand";

export type TabId = "live" | "analytics" | "markets" | "control";

interface DashboardState {
  activeTab: TabId;
  setActiveTab: (tab: TabId) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  activeTab: "live",
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
