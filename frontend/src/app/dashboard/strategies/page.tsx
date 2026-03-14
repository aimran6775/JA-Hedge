"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconStrategy,
  IconTarget,
  IconZap,
  IconRefresh,
  IconTrendUp,
  IconTrendDown,
  IconShield,
  IconPlay,
  IconPause,
} from "@/components/ui/Icons";
import {
  api,
  type StrategyEngineStatus,
  type StrategyInfo,
  type StrategySignalItem,
} from "@/lib/api";

const RISK_COLORS: Record<string, string> = {
  low: "text-accent",
  medium: "text-[var(--warning)]",
  high: "text-loss",
};

const RISK_BG: Record<string, string> = {
  low: "bg-accent/10 border-accent/20",
  medium: "bg-[var(--warning)]/10 border-[var(--warning)]/20",
  high: "bg-loss/10 border-loss/20",
};

const STRATEGY_DESCRIPTIONS: Record<string, string> = {
  momentum_chaser: "Follow recent price momentum near resolution windows",
  contrarian_fade: "Fade extreme prices (>80¢ or <20¢) far from expiry",
  spread_capture: "Market-make inside wide bid-ask spreads for consistent gains",
  expiry_convergence: "Trade convergence to 0/100 as contracts near expiry",
  volume_breakout: "Enter on 2x+ volume spikes with directional confirmation",
  mean_reversion: "Bet against overreactions on low volume",
  sharp_money: "Follow aligned model + momentum + volume signals",
  kelly_optimal: "Pure Kelly criterion sizing on any detected edge",
};

export default function StrategiesPage() {
  const [engineStatus, setEngineStatus] = useState<StrategyEngineStatus | null>(null);
  const [signals, setSignals] = useState<StrategySignalItem[]>([]);
  const [scanResult, setScanResult] = useState<{ markets_scanned: number; total_signals: number; signals: StrategySignalItem[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [togglingStrategy, setTogglingStrategy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [status, sigs] = await Promise.all([
        api.strategies.status().catch(() => null),
        api.strategies.signals(50).catch(() => ({ total_signals: 0, signals: [] })),
      ]);
      if (status) setEngineStatus(status);
      setSignals(sigs.signals || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 15000);
    return () => clearInterval(iv);
  }, [refresh]);

  const handleToggle = async (name: string, enabled: boolean) => {
    setTogglingStrategy(name);
    try {
      await api.strategies.toggle(name, enabled);
      await refresh();
    } catch (err) {
      console.error("Toggle failed:", err);
    } finally {
      setTogglingStrategy(null);
    }
  };

  const handleScan = async () => {
    setScanning(true);
    try {
      const result = await api.strategies.scan();
      setScanResult(result);
      await refresh();
    } catch (err) {
      console.error("Scan failed:", err);
    } finally {
      setScanning(false);
    }
  };

  const strategies: StrategyInfo[] = engineStatus?.strategies ?? [];

  const activeCount = strategies.filter((s) => s.enabled).length;
  const totalSignals = engineStatus?.total_signals_generated ?? 0;
  const totalWins = strategies.reduce((sum, s) => sum + (s.stats?.wins ?? 0), 0);
  const totalLosses = strategies.reduce((sum, s) => sum + (s.stats?.losses ?? 0), 0);
  const overallWinRate = totalWins + totalLosses > 0 ? (totalWins / (totalWins + totalLosses) * 100) : 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">
            Trading Strategies
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Pre-built prediction market strategies with confidence-based signals
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleScan}
            disabled={scanning}
            className="glass rounded-xl px-4 py-2 text-xs font-medium text-accent hover:bg-accent/10 transition-all border border-accent/20 flex items-center gap-2"
          >
            <IconZap size={14} className={scanning ? "animate-pulse" : ""} />
            {scanning ? "Scanning..." : "Manual Scan"}
          </button>
          <button
            onClick={refresh}
            disabled={loading}
            className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all hover:border-white/10 flex items-center gap-2"
          >
            <IconRefresh size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Active Strategies"
          value={`${activeCount}/${strategies.length}`}
          icon={<IconStrategy size={18} />}
        />
        <StatCard
          label="Total Signals"
          value={String(totalSignals)}
          icon={<IconZap size={18} />}
        />
        <StatCard
          label="Win Rate"
          value={overallWinRate > 0 ? `${overallWinRate.toFixed(1)}%` : "—"}
          trend={overallWinRate >= 50 ? "up" : overallWinRate > 0 ? "down" : undefined}
          icon={<IconTarget size={18} />}
        />
        <StatCard
          label="Win/Loss"
          value={`${totalWins}W / ${totalLosses}L`}
          icon={<IconShield size={18} />}
        />
      </div>

      {/* Strategies Grid */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-3">
          Strategy Engine
        </h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {strategies.length === 0 ? (
            <div className="col-span-full py-12 text-center text-sm text-[var(--text-muted)]">
              Strategy engine not initialized
            </div>
          ) : (
            strategies.map((strat) => (
              <StrategyCard
                key={strat.name}
                name={strat.name}
                info={strat}
                toggling={togglingStrategy === strat.name}
                onToggle={(enabled) => handleToggle(strat.name, enabled)}
              />
            ))
          )}
        </div>
      </div>

      {/* Two-column: Scan Results & Signal Feed */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Scan Results */}
        <Card title={scanResult ? `Scan Results — ${scanResult.markets_scanned} markets, ${scanResult.total_signals} signals` : "Scan Results"}>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
            {!scanResult ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                Click &quot;Manual Scan&quot; to find opportunities
              </div>
            ) : scanResult.signals.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                No signals found — strategies may need active markets with data
              </div>
            ) : (
              scanResult.signals.map((sig, i) => (
                <SignalRow key={`scan-${i}`} signal={sig} />
              ))
            )}
          </div>
        </Card>

        {/* Recent Signal Feed */}
        <Card title="Recent Signals">
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto pr-1">
            {signals.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                No signals generated yet — strategies will fire during Frankenstein scans
              </div>
            ) : (
              signals.map((sig, i) => (
                <SignalRow key={`sig-${i}`} signal={sig} />
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ── Strategy Card ──────────────────────────────────────────────── */

function StrategyCard({
  name,
  info,
  toggling,
  onToggle,
}: {
  name: string;
  info: StrategyInfo;
  toggling: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const risk = (info.risk_level || "medium").toLowerCase();
  const riskColor = RISK_COLORS[risk] || RISK_COLORS.medium;
  const riskBg = RISK_BG[risk] || RISK_BG.medium;
  const description = STRATEGY_DESCRIPTIONS[name] || info.description || "";
  const winRate = (info.stats?.wins ?? 0) + (info.stats?.losses ?? 0) > 0
    ? ((info.stats?.wins ?? 0) / ((info.stats?.wins ?? 0) + (info.stats?.losses ?? 0)) * 100)
    : 0;

  return (
    <div className={`rounded-2xl border transition-all duration-200 ${
      info.enabled
        ? "glass border-white/[0.08] hover:border-white/[0.12]"
        : "bg-white/[0.01] border-white/[0.03] opacity-60"
    }`}>
      <div className="p-4">
        {/* Header */}
        <div className="flex items-start justify-between mb-2">
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
            </h3>
            <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold mt-1 border ${riskBg} ${riskColor}`}>
              {risk.toUpperCase()} RISK
            </span>
          </div>
          <button
            onClick={() => onToggle(!info.enabled)}
            disabled={toggling}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ml-2 ${
              info.enabled ? "bg-accent" : "bg-white/10"
            } ${toggling ? "opacity-50" : ""}`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                info.enabled ? "translate-x-4.5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        {/* Description */}
        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed mb-3 line-clamp-2">
          {description}
        </p>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg bg-white/[0.02] px-2 py-1.5">
            <div className="text-[10px] text-[var(--text-muted)]">Signals</div>
            <div className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">
              {info.stats?.signals ?? 0}
            </div>
          </div>
          <div className="rounded-lg bg-white/[0.02] px-2 py-1.5">
            <div className="text-[10px] text-[var(--text-muted)]">Win Rate</div>
            <div className={`text-xs font-semibold tabular-nums ${
              winRate >= 50 ? "text-accent" : winRate > 0 ? "text-loss" : "text-[var(--text-muted)]"
            }`}>
              {winRate > 0 ? `${winRate.toFixed(0)}%` : "—"}
            </div>
          </div>
          <div className="rounded-lg bg-white/[0.02] px-2 py-1.5">
            <div className="text-[10px] text-[var(--text-muted)]">Min Conf</div>
            <div className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">
              {((info.config?.min_confidence ?? 0) * 100).toFixed(0)}%
            </div>
          </div>
          <div className="rounded-lg bg-white/[0.02] px-2 py-1.5">
            <div className="text-[10px] text-[var(--text-muted)]">Min Edge</div>
            <div className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">
              {((info.config?.min_edge ?? 0) * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Signal Row ─────────────────────────────────────────────────── */

function SignalRow({ signal }: { signal: StrategySignalItem }) {
  const confPct = (signal.confidence * 100).toFixed(0);
  const edgePct = (signal.edge * 100).toFixed(1);
  const isBuy = signal.side === "yes";

  return (
    <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 transition-colors hover:bg-white/[0.04]">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-[var(--text-primary)] truncate">
            {signal.ticker}
          </span>
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${
            isBuy ? "bg-accent/10 text-accent" : "bg-loss/10 text-loss"
          }`}>
            {signal.side?.toUpperCase()}
          </span>
        </div>
        <span className="text-[10px] font-medium text-[var(--text-muted)] bg-white/[0.03] px-1.5 py-0.5 rounded-md">
          {signal.strategy?.replace(/_/g, " ")}
        </span>
      </div>

      <div className="flex items-center justify-between text-xs text-[var(--text-muted)] mt-1">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            {Number(confPct) >= 60 ? (
              <IconTrendUp size={12} className="text-accent" />
            ) : (
              <IconTrendDown size={12} className="text-[var(--warning)]" />
            )}
            <span className="tabular-nums">{confPct}% conf</span>
          </span>
          <span className="tabular-nums font-mono">{edgePct}% edge</span>
        </div>
        <span className="tabular-nums">size: {signal.recommended_count}</span>
      </div>

      {/* Confidence bar */}
      <div className="mt-2 h-1 rounded-full bg-white/[0.06] overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent to-accent/60 transition-all"
          style={{ width: `${signal.confidence * 100}%` }}
        />
      </div>

      {signal.reasoning && (
        <p className="mt-1.5 text-[10px] text-[var(--text-muted)]/70 line-clamp-1">
          {signal.reasoning}
        </p>
      )}
    </div>
  );
}
