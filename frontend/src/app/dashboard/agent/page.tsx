"use client";

import { useCallback, useEffect, useState } from "react";
import { api, AgentStatus, AgentTrade } from "@/lib/api";

/* ── tiny helpers ───────────────────────────────────────────────── */
function fmt$(v: number) {
  return v.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });
}

function fmtPct(v: number) {
  return `${v.toFixed(1)}%`;
}

function fmtDuration(seconds: number) {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

const STATUS_COLORS: Record<string, string> = {
  idle: "text-gray-400",
  running: "text-green-400",
  paused: "text-yellow-400",
  target_hit: "text-emerald-400",
  stopped: "text-red-400",
  error: "text-red-500",
};

const STATUS_DOTS: Record<string, string> = {
  idle: "bg-gray-400",
  running: "bg-green-400 animate-pulse",
  paused: "bg-yellow-400",
  target_hit: "bg-emerald-400",
  stopped: "bg-red-400",
  error: "bg-red-500",
};

const TRADE_STATUS_COLORS: Record<string, string> = {
  filled: "text-green-400",
  pending: "text-yellow-400",
  failed: "text-red-400",
  cancelled: "text-gray-400",
};

/* ── main page ──────────────────────────────────────────────────── */

export default function AgentPage() {
  const [agentData, setAgentData] = useState<AgentStatus | null>(null);
  const [targetInput, setTargetInput] = useState("4100");
  const [aggressiveness, setAggressiveness] = useState("moderate");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  /* poll agent status */
  const fetchStatus = useCallback(async () => {
    try {
      const data = await api.agent.status();
      setAgentData(data);
      setError("");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 3000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  /* handlers */
  const handleStart = async () => {
    const target = parseFloat(targetInput);
    if (isNaN(target) || target <= 0) {
      setError("Enter a valid profit target");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.agent.start(target, aggressiveness);
      await fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start agent");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await api.agent.stop();
      await fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to stop agent");
    } finally {
      setLoading(false);
    }
  };

  const status = agentData?.status ?? "idle";
  const stats = agentData?.stats;
  const trades = agentData?.recent_trades ?? [];
  const isRunning = status === "running";
  const isTargetHit = status === "target_hit";

  /* progress ring */
  const progress = stats?.progress_pct ?? 0;
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (Math.min(progress, 100) / 100) * circumference;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">🧠 AI Trading Agent</h1>
          <p className="text-sm text-[var(--muted)]">
            Set a profit target and let AI trade autonomously
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOTS[status] || "bg-gray-400"}`} />
          <span className={`text-sm font-medium capitalize ${STATUS_COLORS[status] || ""}`}>
            {status.replace("_", " ")}
          </span>
        </div>
      </div>

      {/* Target Hit Banner */}
      {isTargetHit && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-center">
          <p className="text-2xl font-bold text-emerald-400">🎯 Target Hit!</p>
          <p className="text-sm text-emerald-300/70">
            Profit goal of {fmt$(stats?.target_profit ?? 0)} has been reached
          </p>
        </div>
      )}

      {/* Control Panel + Progress Ring */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Control Card */}
        <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card)] p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--muted)]">
            Agent Controls
          </h2>

          {/* Target Input */}
          <div className="mb-4">
            <label className="mb-1 block text-xs text-[var(--muted)]">Profit Target</label>
            <div className="flex items-center rounded-lg border border-[var(--card-border)] bg-black/30">
              <span className="px-3 text-lg text-[var(--muted)]">$</span>
              <input
                type="number"
                value={targetInput}
                onChange={(e) => setTargetInput(e.target.value)}
                disabled={isRunning}
                className="w-full bg-transparent py-3 pr-3 text-2xl font-bold text-white outline-none placeholder:text-gray-600 disabled:opacity-50"
                placeholder="4100"
                min="1"
                step="100"
              />
            </div>
          </div>

          {/* Aggressiveness */}
          <div className="mb-5">
            <label className="mb-2 block text-xs text-[var(--muted)]">Aggressiveness</label>
            <div className="grid grid-cols-3 gap-1 rounded-lg bg-black/30 p-1">
              {(["conservative", "moderate", "aggressive"] as const).map((level) => (
                <button
                  key={level}
                  onClick={() => setAggressiveness(level)}
                  disabled={isRunning}
                  className={`rounded-md px-2 py-1.5 text-xs font-medium capitalize transition-colors ${
                    aggressiveness === level
                      ? level === "conservative"
                        ? "bg-blue-500/20 text-blue-400"
                        : level === "moderate"
                          ? "bg-yellow-500/20 text-yellow-400"
                          : "bg-red-500/20 text-red-400"
                      : "text-gray-500 hover:text-gray-300"
                  } disabled:opacity-50`}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="mb-3 rounded bg-red-500/10 p-2 text-xs text-red-400">{error}</div>
          )}

          {/* Start / Stop */}
          {!isRunning ? (
            <button
              onClick={handleStart}
              disabled={loading}
              className="w-full rounded-lg bg-green-600 py-3 text-sm font-bold text-white transition-colors hover:bg-green-500 disabled:opacity-50"
            >
              {loading ? "Starting..." : "🚀 Start Agent"}
            </button>
          ) : (
            <button
              onClick={handleStop}
              disabled={loading}
              className="w-full rounded-lg bg-red-600 py-3 text-sm font-bold text-white transition-colors hover:bg-red-500 disabled:opacity-50"
            >
              {loading ? "Stopping..." : "⛔ Stop Agent"}
            </button>
          )}
        </div>

        {/* Progress Ring Card */}
        <div className="flex flex-col items-center justify-center rounded-xl border border-[var(--card-border)] bg-[var(--card)] p-6">
          <div className="relative">
            <svg width="180" height="180" className="-rotate-90">
              {/* Background circle */}
              <circle
                cx="90"
                cy="90"
                r={radius}
                fill="none"
                stroke="rgba(255,255,255,0.06)"
                strokeWidth="10"
              />
              {/* Progress arc */}
              <circle
                cx="90"
                cy="90"
                r={radius}
                fill="none"
                stroke={
                  isTargetHit
                    ? "#10b981"
                    : progress > 50
                      ? "#22c55e"
                      : progress > 20
                        ? "#eab308"
                        : "#6b7280"
                }
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                className="transition-all duration-1000"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-bold text-white">{fmtPct(progress)}</span>
              <span className="text-xs text-[var(--muted)]">of target</span>
            </div>
          </div>

          <div className="mt-4 text-center">
            <p className="text-lg font-bold text-white">{fmt$(stats?.current_pnl ?? 0)}</p>
            <p className="text-xs text-[var(--muted)]">
              of {fmt$(stats?.target_profit ?? 0)} target
            </p>
          </div>
        </div>

        {/* Quick Stats Card */}
        <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card)] p-6">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--muted)]">
            Session Stats
          </h2>
          <div className="space-y-3">
            <StatRow label="Time Running" value={fmtDuration(stats?.elapsed_seconds ?? 0)} />
            <StatRow label="Scans" value={String(stats?.scan_count ?? 0)} />
            <StatRow label="Markets Scanned" value={String(stats?.markets_scanned ?? 0)} />
            <StatRow label="Signals Found" value={String(stats?.signals_found ?? 0)} />
            <StatRow
              label="Orders"
              value={`${stats?.orders_filled ?? 0} / ${stats?.orders_placed ?? 0}`}
              sub="filled / placed"
            />
            <StatRow
              label="Active Positions"
              value={String(stats?.active_positions ?? 0)}
            />
            <StatRow
              label="Balance"
              value={fmt$(stats?.current_balance ?? 0)}
            />
            <StatRow
              label="Expected Profit"
              value={fmt$(stats?.total_expected_profit ?? 0)}
              highlight
            />
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
        <MetricCard label="Avg Confidence" value={fmtPct((stats?.avg_confidence ?? 0) * 100)} />
        <MetricCard label="Avg Edge" value={fmtPct((stats?.avg_edge ?? 0) * 100)} />
        <MetricCard
          label="Win Rate"
          value={fmtPct(stats?.win_rate ?? 0)}
          color={
            (stats?.win_rate ?? 0) > 55
              ? "text-green-400"
              : (stats?.win_rate ?? 0) > 45
                ? "text-yellow-400"
                : "text-red-400"
          }
        />
        <MetricCard label="Orders Failed" value={String(stats?.orders_failed ?? 0)} color="text-red-400" />
        <MetricCard label="Exposure" value={fmt$(stats?.active_exposure ?? 0)} />
        <MetricCard
          label="Aggressiveness"
          value={(agentData?.aggressiveness ?? aggressiveness).charAt(0).toUpperCase() +
            (agentData?.aggressiveness ?? aggressiveness).slice(1)}
          color={
            (agentData?.aggressiveness ?? aggressiveness) === "aggressive"
              ? "text-red-400"
              : (agentData?.aggressiveness ?? aggressiveness) === "moderate"
                ? "text-yellow-400"
                : "text-blue-400"
          }
        />
      </div>

      {/* Trade Log */}
      <div className="rounded-xl border border-[var(--card-border)] bg-[var(--card)] p-6">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-[var(--muted)]">
          Recent Trades ({trades.length})
        </h2>

        {trades.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--muted)]">
            {isRunning ? "Scanning for opportunities..." : "No trades yet — start the agent to begin"}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-[var(--card-border)] text-xs text-[var(--muted)]">
                  <th className="py-2 pr-4">Time</th>
                  <th className="py-2 pr-4">Ticker</th>
                  <th className="py-2 pr-4">Side</th>
                  <th className="py-2 pr-4 text-right">Qty</th>
                  <th className="py-2 pr-4 text-right">Price</th>
                  <th className="py-2 pr-4 text-right">Edge</th>
                  <th className="py-2 pr-4 text-right">Confidence</th>
                  <th className="py-2 pr-4 text-right">Exp. Profit</th>
                  <th className="py-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {[...trades].reverse().map((t) => (
                  <tr key={t.id} className="border-b border-[var(--card-border)]/50">
                    <td className="py-2 pr-4 text-xs text-[var(--muted)]">
                      {t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : "—"}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-white">{t.ticker}</td>
                    <td className="py-2 pr-4">
                      <span
                        className={`rounded px-1.5 py-0.5 text-xs font-bold ${
                          t.side === "yes"
                            ? "bg-green-500/20 text-green-400"
                            : "bg-red-500/20 text-red-400"
                        }`}
                      >
                        {t.side.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right text-white">{t.count}</td>
                    <td className="py-2 pr-4 text-right text-white">{t.price_cents}¢</td>
                    <td className="py-2 pr-4 text-right text-green-400">
                      {(t.edge * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 pr-4 text-right text-blue-400">
                      {(t.confidence * 100).toFixed(1)}%
                    </td>
                    <td className="py-2 pr-4 text-right font-medium text-white">
                      {fmt$(t.expected_profit)}
                    </td>
                    <td className="py-2">
                      <span
                        className={`text-xs font-medium capitalize ${TRADE_STATUS_COLORS[t.status] || "text-gray-400"}`}
                      >
                        {t.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── sub-components ─────────────────────────────────────────────── */

function StatRow({
  label,
  value,
  sub,
  highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[var(--muted)]">{label}</span>
      <div className="text-right">
        <span className={`text-sm font-medium ${highlight ? "text-green-400" : "text-white"}`}>
          {value}
        </span>
        {sub && <span className="ml-1 text-[10px] text-[var(--muted)]">{sub}</span>}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--card-border)] bg-[var(--card)] p-3">
      <p className="text-[10px] uppercase tracking-wider text-[var(--muted)]">{label}</p>
      <p className={`mt-1 text-lg font-bold ${color || "text-white"}`}>{value}</p>
    </div>
  );
}
