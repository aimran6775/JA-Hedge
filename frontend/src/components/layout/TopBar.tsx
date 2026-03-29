"use client";

import { useCallback, useEffect, useState } from "react";
import { IconStop, IconCircle, IconShield, IconAlertTriangle } from "@/components/ui/Icons";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function TopBar() {
  const [connected, setConnected] = useState(false);
  const [time, setTime] = useState("");
  const [killActive, setKillActive] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [alertCount, setAlertCount] = useState(0);

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
      setConnected(res.ok);
    } catch {
      setConnected(false);
    }
  }, []);

  const checkRisk = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/risk/snapshot`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        setKillActive(data.kill_switch_active ?? false);
      }
    } catch { /* ignore */ }
  }, []);

  const checkAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/intelligence/alerts?limit=50`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const data = await res.json();
        const unread = (data.alerts ?? []).filter((a: { acknowledged: boolean }) => !a.acknowledged).length;
        setAlertCount(unread);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    checkHealth();
    checkRisk();
    checkAlerts();
    const iv = setInterval(() => { checkHealth(); checkRisk(); checkAlerts(); }, 15000);
    return () => clearInterval(iv);
  }, [checkHealth, checkRisk, checkAlerts]);

  useEffect(() => {
    const tick = () => {
      setTime(
        new Date().toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }),
      );
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, []);

  const toggleKillSwitch = async () => {
    if (toggling) return;
    const activate = !killActive;
    if (activate && !confirm("⚠️ ACTIVATE KILL SWITCH?\n\nThis will immediately halt ALL trading operations.")) return;
    setToggling(true);
    try {
      const res = await fetch(`${API_BASE}/api/risk/kill-switch?activate=${activate}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setKillActive(data.kill_switch_active ?? activate);
      }
    } catch { /* ignore */ }
    setToggling(false);
  };

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-white/[0.04] bg-[var(--bg-primary)]/60 backdrop-blur-xl px-6">
      <div className="flex items-center gap-4">
        <span className="text-xs font-mono text-[var(--text-muted)] tabular-nums tracking-wider">
          {time}
        </span>
        <div className="h-4 w-px bg-white/[0.06]" />
        <span className="text-xs font-medium text-[var(--text-muted)] tracking-wide uppercase">
          AI Trading Terminal
        </span>
      </div>

      <div className="flex items-center gap-3">
        {/* Alert bell */}
        {alertCount > 0 && (
          <button
            onClick={() => {
              window.dispatchEvent(new CustomEvent("ja-switch-tab", { detail: "markets" }));
            }}
            className="relative flex items-center gap-1.5 rounded-lg bg-[var(--warning)]/5 border border-[var(--warning)]/20 px-2.5 py-1.5 text-xs font-medium text-[var(--warning)] hover:bg-[var(--warning)]/10 transition-all"
          >
            <IconAlertTriangle size={13} />
            <span>{alertCount}</span>
          </button>
        )}

        {/* Kill switch */}
        <button
          onClick={toggleKillSwitch}
          disabled={toggling}
          className={`group flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
            killActive
              ? "border border-loss/40 bg-loss/15 text-loss animate-pulse hover:bg-loss/25"
              : "border border-loss/20 bg-loss/5 text-loss/80 hover:bg-loss/10 hover:text-loss hover:border-loss/30"
          } ${toggling ? "opacity-50 cursor-wait" : ""}`}
        >
          {killActive ? <IconShield size={14} /> : <IconStop size={14} className="group-hover:animate-pulse" />}
          <span>{killActive ? "⚠ KILL ACTIVE" : "Kill Switch"}</span>
        </button>

        {/* Connection status */}
        <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
          <IconCircle
            size={8}
            className={connected ? "text-accent" : "text-loss animate-pulse"}
          />
          <span className="text-xs font-medium text-[var(--text-muted)]">
            {connected ? "Connected" : "Offline"}
          </span>
        </div>
      </div>
    </header>
  );
}
