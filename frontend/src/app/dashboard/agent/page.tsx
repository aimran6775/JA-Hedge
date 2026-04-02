"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconRocket, IconTarget, IconZap, IconPlay, IconPause, IconStop, IconRefresh, IconCircle, IconTrendUp } from "@/components/ui/Icons";
import { api, type AgentStatus } from "@/lib/api";

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
      <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">{label}</div>
      <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">{value}</div>
      {sub && <div className="text-xs text-[var(--text-muted)] mt-0.5">{sub}</div>}
    </div>
  );
}

export default function AgentPage() {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [profitTarget, setProfitTarget] = useState(5);
  const [aggressiveness, setAggressiveness] = useState<"conservative" | "moderate" | "aggressive">("moderate");
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.agent.status().catch(() => null);
      setStatus(s);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 8000);
    return () => clearInterval(iv);
  }, [refresh]);

  const startAgent = async () => {
    setActionMsg(null);
    try {
      await api.agent.start(profitTarget, aggressiveness);
      setActionMsg("Agent started");
      refresh();
    } catch {
      setActionMsg("Failed to start agent");
    }
  };

  const stopAgent = async () => {
    setActionMsg(null);
    try {
      await api.agent.stop();
      setActionMsg("Agent stopped");
      refresh();
    } catch {
      setActionMsg("Failed to stop agent");
    }
  };

  const isRunning = status?.status === "running";
  const sessionPnl = status?.stats?.current_pnl ?? 0;
  const targetCents = (profitTarget * 100);
  const progress = targetCents > 0 ? Math.min(Math.max((sessionPnl * 100) / targetCents, 0), 1) : 0;

  // SVG Progress Ring
  const ringSize = 160;
  const strokeWidth = 8;
  const radius = (ringSize - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - progress * circumference;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">AI Agent</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Autonomous trading agent with profit targeting</p>
        </div>
        <button onClick={refresh} disabled={loading}
          className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all flex items-center gap-2">
          <IconRefresh size={14} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Status" value={isRunning ? "Running" : "Stopped"} trend={isRunning ? "up" : "down"} icon={<IconRocket size={18} />} />
        <StatCard label="Session P&L" value={`$${(sessionPnl).toFixed(2)}`} trend={sessionPnl >= 0 ? "up" : "down"} icon={<IconTrendUp size={18} />} />
        <StatCard label="Trades" value={String(status?.stats?.orders_placed ?? 0)} icon={<IconZap size={18} />} />
        <StatCard label="Win Rate" value={status?.stats?.win_rate != null ? `${(status.stats.win_rate * 100).toFixed(0)}%` : "—"} icon={<IconTarget size={18} />} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Progress Ring */}
        <Card title="Profit Target Progress" className="flex flex-col items-center">
          <div className="relative flex items-center justify-center py-4">
            <svg width={ringSize} height={ringSize} className="-rotate-90">
              <circle cx={ringSize / 2} cy={ringSize / 2} r={radius} stroke="rgba(255,255,255,0.06)" strokeWidth={strokeWidth} fill="none" />
              <circle cx={ringSize / 2} cy={ringSize / 2} r={radius}
                stroke="url(#progressGradient)" strokeWidth={strokeWidth} fill="none"
                strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
                className="transition-all duration-1000" />
              <defs>
                <linearGradient id="progressGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="var(--accent)" />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.4" />
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <div className="text-2xl font-bold text-[var(--text-primary)] tabular-nums">{(progress * 100).toFixed(0)}%</div>
              <div className="text-xs text-[var(--text-muted)]">${(sessionPnl).toFixed(2)} / ${profitTarget.toFixed(2)}</div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 w-full mt-2">
            <MetricCard label="Elapsed" value={status?.stats?.elapsed_seconds != null ? `${Math.round(status.stats.elapsed_seconds / 60)}m` : "—"} />
            <MetricCard label="Scans" value={String(status?.stats?.scan_count ?? 0)} />
          </div>
        </Card>

        {/* Controls */}
        <Card title="Agent Configuration">
          <div className="space-y-4">
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm text-[var(--text-secondary)]">Profit Target ($)</span>
                <input type="number" value={profitTarget} onChange={(e) => setProfitTarget(Number(e.target.value))} min={1} max={100} step={1}
                  className="w-20 rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-1.5 text-sm text-[var(--text-primary)] tabular-nums text-right focus:border-accent/30 transition-all" />
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Aggressiveness</label>
              <div className="grid grid-cols-3 gap-2 mt-2">
                {(["conservative", "moderate", "aggressive"] as const).map((a) => (
                  <button key={a} onClick={() => setAggressiveness(a)}
                    className={`rounded-xl py-2.5 text-xs font-semibold uppercase tracking-wider transition-all ${
                      aggressiveness === a
                        ? a === "aggressive" ? "bg-loss/15 text-loss border border-loss/25"
                          : a === "moderate" ? "bg-[var(--warning)]/15 text-[var(--warning)] border border-[var(--warning)]/25"
                          : "bg-accent/15 text-accent border border-accent/25"
                        : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)]"
                    }`}>
                    {a.slice(0, 5)}.
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-3">
              <button onClick={startAgent} disabled={isRunning}
                className={`flex-1 rounded-xl py-3 text-sm font-bold tracking-wide flex items-center justify-center gap-2 transition-all ${
                  isRunning ? "bg-white/[0.03] text-[var(--text-muted)] cursor-not-allowed" : "bg-accent text-white hover:bg-accent/90"
                }`}>
                <IconPlay size={14} /> Start
              </button>
              <button onClick={stopAgent} disabled={!isRunning}
                className={`flex-1 rounded-xl py-3 text-sm font-bold tracking-wide flex items-center justify-center gap-2 transition-all ${
                  !isRunning ? "bg-white/[0.03] text-[var(--text-muted)] cursor-not-allowed" : "bg-loss text-white hover:bg-loss/90"
                }`}>
                <IconStop size={14} /> Stop
              </button>
            </div>

            {actionMsg && (
              <div className={`rounded-xl p-3 text-sm text-center ${actionMsg.includes("started") ? "bg-accent/10 text-accent border border-accent/20" : actionMsg.includes("stopped") ? "bg-[var(--warning)]/10 text-[var(--warning)] border border-[var(--warning)]/20" : "bg-loss/10 text-loss border border-loss/20"}`}>
                {actionMsg}
              </div>
            )}
          </div>
        </Card>

        {/* Trade Log */}
        <Card title="Trade Log">
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
            {(status?.recent_trades ?? []).length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">No trades in this session</div>
            ) : (
              (status?.recent_trades ?? []).map((t, i: number) => (
                <div key={i} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5 transition-colors hover:bg-white/[0.04]">
                  <div className="flex items-center gap-2.5">
                    <IconCircle size={6} className={t.action === "buy" ? "text-accent" : "text-loss"} />
                    <div>
                      <div className="text-sm text-[var(--text-primary)] font-medium">{t.ticker}</div>
                      <div className="text-xs text-[var(--text-muted)]">{t.action.toUpperCase()} {t.side.toUpperCase()}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    {t.fill_pnl != null && (
                      <div className={`text-sm tabular-nums font-mono ${t.fill_pnl >= 0 ? "text-accent" : "text-loss"}`}>
                        {t.fill_pnl >= 0 ? "+" : ""}${(t.fill_pnl / 100).toFixed(2)}
                      </div>
                    )}
                    {t.timestamp && <div className="text-xs text-[var(--text-muted)]">{new Date(t.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</div>}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
