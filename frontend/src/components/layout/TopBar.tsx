"use client";

import { useEffect, useState } from "react";
import { useSSE } from "@/lib/useSSE";

/* ═══════════════════════════════════════════════════════════════════════
   TOP BAR — Simplified header with key metrics
   ═══════════════════════════════════════════════════════════════════════ */
export function TopBar() {
  const { data: sse, connected, lastUpdate } = useSSE();
  const [toggling, setToggling] = useState(false);

  const killActive = sse?.risk?.kill_switch_active ?? false;
  const balanceCents = sse?.balance?.balance_cents ?? 0;
  const pnlCents = sse?.pnl?.daily_pnl ?? 0;
  const positionCount = sse?.positions?.length ?? 0;
  const frank = sse?.frankenstein;
  const isLive = frank?.is_alive && frank?.is_trading && !frank?.is_paused || false;

  const lastUpdateAgo = lastUpdate ? Math.round((Date.now() - lastUpdate) / 1000) : null;

  const toggleKillSwitch = async () => {
    if (toggling) return;
    const activate = !killActive;
    if (activate && !confirm("⚠️ ACTIVATE KILL SWITCH?\n\nThis will immediately halt ALL trading.")) return;
    setToggling(true);
    try {
      await fetch(`/api/risk/kill-switch?activate=${activate}`, { method: "POST" });
    } catch { /* ignore */ }
    setToggling(false);
  };

  return (
    <header className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-white/[0.04] bg-[var(--bg-primary)]/80 backdrop-blur-xl px-4">
      {/* Left: Brand + Status */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-semibold text-primary">Frankenstein</span>
        <div className="flex items-center gap-1.5">
          <StatusDot active={isLive} />
          <span className={`text-xs ${isLive ? "text-accent" : "text-muted"}`}>
            {isLive ? "Trading" : frank?.is_paused ? "Paused" : "Offline"}
          </span>
        </div>
      </div>

      {/* Center: Key Metrics */}
      <div className="hidden sm:flex items-center gap-2">
        <MetricChip label="Balance" value={`$${(balanceCents / 100).toFixed(2)}`} />
        <MetricChip 
          label="P&L" 
          value={`${pnlCents >= 0 ? "+" : ""}$${(Math.abs(pnlCents) / 100).toFixed(2)}`}
          color={pnlCents >= 0 ? "accent" : "loss"}
        />
        {positionCount > 0 && (
          <MetricChip label="Positions" value={positionCount.toString()} />
        )}
      </div>

      {/* Right: Kill Switch + Connection */}
      <div className="flex items-center gap-2">
        <button
          onClick={toggleKillSwitch}
          disabled={toggling}
          className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition-all ${
            killActive
              ? "bg-loss/20 border border-loss/40 text-loss animate-pulse"
              : "bg-loss/10 border border-loss/20 text-loss/70 hover:bg-loss/15 hover:text-loss"
          } ${toggling ? "opacity-50" : ""}`}
        >
          {killActive ? "KILL ACTIVE" : "Kill"}
        </button>

        <div className="flex items-center gap-1.5 text-xs text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-accent" : "bg-loss animate-pulse"}`} />
          {connected ? (lastUpdateAgo !== null && lastUpdateAgo > 1 ? `${lastUpdateAgo}s` : "Live") : "Offline"}
        </div>
      </div>
    </header>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-2 w-2">
      {active && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-50" />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${active ? "bg-accent" : "bg-muted"}`} />
    </span>
  );
}

function MetricChip({ label, value, color }: { label: string; value: string; color?: "accent" | "loss" }) {
  const colorClass = color === "accent" ? "text-accent" : color === "loss" ? "text-loss" : "text-primary";
  
  return (
    <div className="flex items-center gap-1.5 rounded-lg bg-white/[0.02] border border-white/[0.04] px-2 py-1">
      <span className="text-[9px] text-muted uppercase">{label}</span>
      <span className={`text-xs font-semibold tabular-nums ${colorClass}`}>{value}</span>
    </div>
  );
}
