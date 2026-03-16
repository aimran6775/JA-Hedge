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
  const [activeTab, setActiveTab] = useState<"strategies" | "decision-engine" | "model-intelligence">("strategies");
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
          {activeTab === "strategies" && (
            <>
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
            </>
          )}
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex gap-1 p-1 rounded-xl bg-white/[0.02] border border-white/[0.06] w-fit">
        <button
          onClick={() => setActiveTab("strategies")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeTab === "strategies"
              ? "bg-accent/15 text-accent border border-accent/20"
              : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.04] border border-transparent"
          }`}
        >
          <span className="flex items-center gap-2"><IconStrategy size={14} /> Strategies</span>
        </button>
        <button
          onClick={() => setActiveTab("decision-engine")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeTab === "decision-engine"
              ? "bg-accent/15 text-accent border border-accent/20"
              : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.04] border border-transparent"
          }`}
        >
          <span className="flex items-center gap-2"><IconTarget size={14} /> Decision Engine</span>
        </button>
        <button
          onClick={() => setActiveTab("model-intelligence")}
          className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeTab === "model-intelligence"
              ? "bg-accent/15 text-accent border border-accent/20"
              : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.04] border border-transparent"
          }`}
        >
          <span className="flex items-center gap-2"><IconZap size={14} /> Model Intelligence</span>
        </button>
      </div>

      {activeTab === "strategies" ? (
        <StrategiesTab
          engineStatus={engineStatus}
          strategies={strategies}
          signals={signals}
          scanResult={scanResult}
          activeCount={activeCount}
          totalSignals={totalSignals}
          overallWinRate={overallWinRate}
          totalWins={totalWins}
          totalLosses={totalLosses}
          togglingStrategy={togglingStrategy}
          handleToggle={handleToggle}
        />
      ) : activeTab === "decision-engine" ? (
        <DecisionEngineTab />
      ) : (
        <ModelIntelligenceTab />
      )}
    </div>
  );
}

/* ── Strategies Tab (original content) ────────────────────────── */

function StrategiesTab({
  engineStatus,
  strategies,
  signals,
  scanResult,
  activeCount,
  totalSignals,
  overallWinRate,
  totalWins,
  totalLosses,
  togglingStrategy,
  handleToggle,
}: {
  engineStatus: StrategyEngineStatus | null;
  strategies: StrategyInfo[];
  signals: StrategySignalItem[];
  scanResult: { markets_scanned: number; total_signals: number; signals: StrategySignalItem[] } | null;
  activeCount: number;
  totalSignals: number;
  overallWinRate: number;
  totalWins: number;
  totalLosses: number;
  togglingStrategy: string | null;
  handleToggle: (name: string, enabled: boolean) => void;
}) {
  return (
    <>
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
    </>
  );
}

/* ── Decision Engine Tab ──────────────────────────────────────── */

interface PipelineStep {
  step: number;
  name: string;
  description: string;
  icon: string;
}
interface FactorInfo {
  name: string;
  weight: string;
  description: string;
  best_case: string;
  worst_case: string;
}
interface GradeInfo {
  grade: string;
  min_score: number;
  description: string;
}

const GRADE_BG: Record<string, string> = {
  "A+": "bg-accent/20 text-accent border-accent/30",
  "A": "bg-accent/15 text-accent border-accent/25",
  "B+": "bg-blue-500/15 text-blue-400 border-blue-400/25",
  "B": "bg-blue-500/10 text-blue-400 border-blue-400/20",
  "C+": "bg-[var(--warning)]/15 text-[var(--warning)] border-[var(--warning)]/25",
  "C": "bg-[var(--warning)]/10 text-[var(--warning)] border-[var(--warning)]/20",
  "D": "bg-orange-500/10 text-orange-400 border-orange-400/20",
  "F": "bg-loss/10 text-loss border-loss/20",
};

function DecisionEngineTab() {
  const [data, setData] = useState<{
    pipeline: PipelineStep[];
    confidence_factors: FactorInfo[];
    grade_scale: GradeInfo[];
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.frankenstein
      .decisionEngine()
      .then((res) =>
        setData(res as { pipeline: PipelineStep[]; confidence_factors: FactorInfo[]; grade_scale: GradeInfo[] }),
      )
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="py-20 text-center text-sm text-[var(--text-muted)] animate-pulse">
        Loading decision engine…
      </div>
    );
  }

  if (!data) {
    return (
      <div className="py-20 text-center text-sm text-[var(--text-muted)]">
        Decision engine data unavailable — is the backend running?
      </div>
    );
  }

  return (
    <>
      {/* Pipeline Flow */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-1">
          How Frankenstein Decides to Trade
        </h2>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Every 30 seconds, each potential trade goes through this 10-step pipeline.
        </p>
        <div className="relative">
          {/* Vertical connecting line */}
          <div className="absolute left-6 top-4 bottom-4 w-px bg-gradient-to-b from-accent/40 via-accent/20 to-transparent hidden md:block" />

          <div className="space-y-2">
            {data.pipeline.map((step, i) => (
              <div
                key={step.step}
                className="relative flex items-start gap-4 rounded-xl bg-white/[0.02] border border-white/[0.04] p-4 hover:bg-white/[0.04] transition-colors group"
              >
                {/* Step number circle */}
                <div className="relative z-10 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent/10 border border-accent/20 text-xl group-hover:scale-105 transition-transform">
                  {step.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-bold text-accent/60 tabular-nums">STEP {step.step}</span>
                    <span className="text-sm font-semibold text-[var(--text-primary)]">{step.name}</span>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] leading-relaxed">{step.description}</p>
                </div>
                {/* Arrow indicator */}
                {i < data.pipeline.length - 1 && (
                  <div className="absolute -bottom-2 left-[1.45rem] z-20 text-accent/30 text-xs hidden md:block">▼</div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Confidence Factors */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-1">
          6-Factor Confidence Scoring
        </h2>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Each trade is scored 0–100 on six weighted dimensions. The composite score produces a letter grade.
        </p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.confidence_factors.map((factor) => (
            <div
              key={factor.name}
              className="rounded-2xl glass border border-white/[0.06] p-5 hover:border-white/[0.10] transition-all"
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-bold text-[var(--text-primary)]">{factor.name}</h3>
                <span className="text-xs font-bold text-accent tabular-nums bg-accent/10 rounded-md px-2 py-0.5">
                  {factor.weight}
                </span>
              </div>
              <p className="text-xs text-[var(--text-muted)] leading-relaxed mb-3">
                {factor.description}
              </p>
              <div className="space-y-1.5">
                <div className="flex items-start gap-2">
                  <span className="text-accent text-xs mt-0.5">▲</span>
                  <span className="text-[11px] text-[var(--text-secondary)]">{factor.best_case}</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="text-loss text-xs mt-0.5">▼</span>
                  <span className="text-[11px] text-[var(--text-secondary)]">{factor.worst_case}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Grade Scale */}
      <div>
        <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-1">
          Grade Scale
        </h2>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          The weighted composite score maps to a letter grade. Only A-grade (≥ 80) and A+ trades are executed.
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
          {data.grade_scale.map((g) => {
            const colorClass = GRADE_BG[g.grade] || GRADE_BG["C"];
            return (
              <div
                key={g.grade}
                className={`rounded-xl border p-3 text-center transition-all hover:scale-[1.03] ${colorClass}`}
              >
                <div className="text-2xl font-black mb-1">{g.grade}</div>
                <div className="text-[10px] font-semibold tabular-nums mb-1">≥ {g.min_score}</div>
                <div className="text-[9px] opacity-70 leading-tight">{g.description.split("—")[0].trim()}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quick Summary */}
      <Card title="Trade Gate Summary">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 p-2">
          <div className="text-center">
            <div className="text-2xl font-black text-accent">65%</div>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mt-1">Min Confidence</div>
            <div className="text-[10px] text-[var(--text-secondary)]">Raised to 75% when ML model isn&apos;t trained</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-black text-accent">6%</div>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mt-1">Min Edge</div>
            <div className="text-[10px] text-[var(--text-secondary)]">Raised to 12% when ML model isn&apos;t trained</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-black text-accent">A</div>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mt-1">Min Grade</div>
            <div className="text-[10px] text-[var(--text-secondary)]">Only A and A+ trades execute — composite score ≥ 80</div>
          </div>
        </div>
      </Card>
    </>
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


/* ── Model Intelligence Tab ──────────────────────────────────────── */

function ModelIntelligenceTab() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await api.frankenstein.modelIntelligence();
        if (!cancelled) setData(result);
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <Card className="p-8 text-center">
        <div className="animate-pulse text-[var(--text-muted)]">
          Loading model intelligence…
        </div>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card className="p-8 text-center text-[var(--text-muted)]">
        Model intelligence data unavailable — is the backend running?
      </Card>
    );
  }

  const ensemble = (data.ensemble || {}) as Record<string, unknown>;
  const calibration = (data.calibration || {}) as Record<string, unknown>;
  const features = (data.features || {}) as Record<string, unknown>;
  const binDetails = (calibration.bin_details || []) as { range: string; count: number; actual_rate: number }[];

  return (
    <div className="space-y-6">
      {/* Model Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Model"
          value={String(data.model_name || "—")}
          suffix={`v${data.model_version || "?"}`}
        />
        <StatCard
          label="Status"
          value={data.is_trained ? "Trained" : "Untrained"}
          trend={data.is_trained ? "up" : "down"}
        />
        <StatCard
          label="Trees"
          value={Number(ensemble.num_trees) || 0}
        />
        <StatCard
          label="Features"
          value={Number(features.count) || 0}
        />
      </div>

      {/* Uncertainty Estimation */}
      <Card className="p-5">
        <h3 className="text-sm font-bold text-[var(--text-primary)] mb-3 flex items-center gap-2">
          <IconZap size={16} className="text-accent" />
          Tree-Variance Uncertainty Estimation
        </h3>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Instead of trusting a single probability, we measure how much individual trees in the XGBoost ensemble
          <strong className="text-[var(--text-secondary)]"> agree or disagree</strong>. High agreement → high confidence. Disagreement → uncertainty.
          This is sampled at ~10 checkpoints across the boosting iterations to detect instability.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
            <div className="text-[10px] text-[var(--text-muted)] mb-1">Ensemble Trees</div>
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">{String(ensemble.num_trees || 0)}</div>
          </div>
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
            <div className="text-[10px] text-[var(--text-muted)] mb-1">Checkpoint Samples</div>
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">{String(ensemble.checkpoint_sampling || 0)}</div>
          </div>
        </div>
      </Card>

      {/* Confidence Formula */}
      <Card className="p-5">
        <h3 className="text-sm font-bold text-[var(--text-primary)] mb-3 flex items-center gap-2">
          <IconTarget size={16} className="text-accent" />
          Real Confidence Formula
        </h3>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Confidence is no longer just the predicted probability. It&apos;s a weighted combination of 4 real intelligence signals:
        </p>
        <div className="space-y-2">
          {[
            { label: "Decisiveness", weight: "30%", desc: "Entropy-based: how far from 50/50 the prediction is (p=0.95 → high, p=0.52 → low)" },
            { label: "Edge Signal", weight: "30%", desc: "How large the edge is relative to uncertainty (normalized to 20% max)" },
            { label: "Tree Agreement", weight: "25%", desc: "Variance across individual XGBoost trees — do they agree on the prediction?" },
            { label: "Calibration Quality", weight: "15%", desc: "Is the model well-calibrated? Penalizes if predicted ≠ actual outcome rates" },
          ].map((item) => (
            <div key={item.label} className="flex items-start gap-3 rounded-lg bg-white/[0.02] border border-white/[0.04] p-3">
              <div className="flex-shrink-0 w-14 text-center">
                <span className="text-xs font-bold text-accent">{item.weight}</span>
              </div>
              <div>
                <div className="text-xs font-semibold text-[var(--text-primary)]">{item.label}</div>
                <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{item.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Calibration Health */}
      <Card className="p-5">
        <h3 className="text-sm font-bold text-[var(--text-primary)] mb-3 flex items-center gap-2">
          <IconShield size={16} className="text-accent" />
          Calibration Tracker
        </h3>
        <p className="text-xs text-[var(--text-muted)] mb-4">
          Tracks predicted probabilities vs actual outcomes. When enough data accumulates (30+ trades),
          future predictions are adjusted to match real hit rates — making the model honest about what it knows.
        </p>

        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-center">
            <div className="text-[10px] text-[var(--text-muted)]">Samples</div>
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">{String(calibration.total_samples || 0)}</div>
          </div>
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-center">
            <div className="text-[10px] text-[var(--text-muted)]">ECE</div>
            <div className="text-lg font-bold text-[var(--text-primary)] tabular-nums">{String(calibration.ece || "—")}</div>
          </div>
          <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-center">
            <div className="text-[10px] text-[var(--text-muted)]">Status</div>
            <div className={`text-lg font-bold tabular-nums ${calibration.is_ready ? "text-accent" : "text-[var(--warning)]"}`}>
              {calibration.is_ready ? "Active" : "Collecting"}
            </div>
          </div>
        </div>

        {/* Calibration bins */}
        {binDetails.length > 0 && (
          <div>
            <div className="text-[10px] text-[var(--text-muted)] mb-2 font-semibold">Predicted vs Actual by Bin</div>
            <div className="grid grid-cols-5 md:grid-cols-10 gap-1">
              {binDetails.map((bin) => {
                const maxCount = Math.max(...binDetails.map(b => b.count), 1);
                const height = Math.max(4, (bin.count / maxCount) * 48);
                return (
                  <div key={bin.range} className="flex flex-col items-center gap-1">
                    <div className="w-full flex flex-col items-center justify-end" style={{ height: 52 }}>
                      <div
                        className="w-full rounded-t bg-accent/30 border border-accent/20"
                        style={{ height }}
                        title={`${bin.range}: ${bin.count} trades, ${(bin.actual_rate * 100).toFixed(0)}% actual YES`}
                      />
                    </div>
                    <span className="text-[8px] text-[var(--text-muted)] tabular-nums">{bin.range}</span>
                    <span className="text-[8px] text-accent tabular-nums">{bin.count}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
