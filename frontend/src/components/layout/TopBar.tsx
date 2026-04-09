"use client";

import { useEffect, useState } from "react";
import { IconStop, IconCircle, IconShield, IconAlertTriangle } from "@/components/ui/Icons";
import { useSSE } from "@/lib/useSSE";
import { pnlColor, pnlSign, centsToDollars } from "@/lib/dashboard-utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function TopBar() {
  const { data: sse, connected, lastUpdate } = useSSE();
  const [time, setTime] = useState("");
  const [toggling, setToggling] = useState(false);
  const [alertCount, setAlertCount] = useState(0);

  /* ── Derived from SSE ─────────────────────────────────── */
  const killActive = sse?.risk?.kill_switch_active ?? false;
  const balanceCents = sse?.balance?.balance_cents ?? 0;
  const pnlCents = sse?.pnl?.daily_pnl ?? 0;
  const positionCount = sse?.positions?.length ?? 0;

  /* ── Alerts (still polled — not in SSE snapshot) ─────── */
  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/intelligence/alerts?limit=50`, { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
          const data = await res.json();
          const unread = (data.alerts ?? []).filter((a: { acknowledged: boolean }) => !a.acknowledged).length;
          setAlertCount(unread);
        }
      } catch { /* ignore */ }
    };
    fetchAlerts();
    const iv = setInterval(fetchAlerts, 30000);
    return () => clearInterval(iv);
  }, []);

  /* ── Clock ──────────────────────────────────────────── */
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

  /* ── Last update ago ────────────────────────────────── */
  const [ago, setAgo] = useState("");
  useEffect(() => {
    if (!lastUpdate) return;
    const tick = () => {
      const s = Math.round((Date.now() - (lastUpdate ?? Date.now())) / 1000);
      setAgo(s < 2 ? "now" : `${s}s ago`);
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [lastUpdate]);

  const toggleKillSwitch = async () => {
    if (toggling) return;
    const activate = !killActive;
    if (activate && !confirm("⚠️ ACTIVATE KILL SWITCH?\n\nThis will immediately halt ALL trading operations.")) return;
    setToggling(true);
    try {
      await fetch(`${API_BASE}/api/risk/kill-switch?activate=${activate}`, { method: "POST" });
    } catch { /* ignore */ }
    setToggling(false);
  };

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-white/[0.04] bg-[var(--bg-primary)]/60 backdrop-blur-xl px-6">
      {/* ── Left: clock + label ──────────────────────── */}
      <div className="flex items-center gap-4">
        <span className="text-xs font-mono text-[var(--text-muted)] tabular-nums tracking-wider">
          {time}
        </span>
        <div className="h-4 w-px bg-white/[0.06]" />
        <span className="text-xs font-medium text-[var(--text-muted)] tracking-wide uppercase">
          AI Trading Terminal
        </span>
      </div>

      {/* ── Center: balance + P&L chip ───────────────── */}
      <div className="hidden sm:flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Balance</span>
          <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">
            ${centsToDollars(balanceCents)}
          </span>
        </div>

        <div className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 ${
          pnlCents >= 0
            ? "bg-accent/5 border-accent/20"
            : "bg-loss/5 border-loss/20"
        }`}>
          <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">P&L</span>
          <span className={`text-sm font-semibold tabular-nums ${pnlColor(pnlCents)}`}>
            {pnlSign(pnlCents)}${centsToDollars(Math.abs(pnlCents))}
          </span>
        </div>

        {positionCount > 0 && (
          <div className="flex items-center gap-1.5 rounded-lg bg-white/[0.02] border border-white/[0.04] px-2.5 py-1.5">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Pos</span>
            <span className="text-xs font-semibold tabular-nums text-[var(--text-primary)]">{positionCount}</span>
          </div>
        )}
      </div>

      {/* ── Right: alerts + kill switch + connection ── */}
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

        {/* Connection status with last-update */}
        <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
          <IconCircle
            size={8}
            className={connected ? "text-accent" : "text-loss animate-pulse"}
          />
          <span className="text-xs font-medium text-[var(--text-muted)]">
            {connected ? (ago ? `Live · ${ago}` : "Live") : "Offline"}
          </span>
        </div>
      </div>
    </header>
  );
}
