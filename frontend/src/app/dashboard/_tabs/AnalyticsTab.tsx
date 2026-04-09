"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconTrendUp,
  IconTrendDown,
  IconTarget,
  IconShield,
  IconBrain,
  IconStrategy,
  IconRefresh,
} from "@/components/ui/Icons";
import { api, type FrankensteinTrade } from "@/lib/api";
import { cn } from "@/lib/utils";
import { pnlColor, pnlSign, prettifyTicker, timeAgo, categoryEmoji } from "@/lib/dashboard-utils";
import { EquityCurve } from "@/components/charts/EquityCurve";

type SubTab = "overview" | "categories" | "confidence" | "model" | "backtest";

/* ═══════════════════════════════════════════════════════════════════════
   ANALYTICS TAB — Performance analysis with proper charts
   ═══════════════════════════════════════════════════════════════════════ */
export function AnalyticsTab() {
  const [sub, setSub] = useState<SubTab>("overview");
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [perfSnap, setPerfSnap] = useState<Record<string, unknown> | null>(null);
  const [modelInfo, setModelInfo] = useState<Record<string, unknown> | null>(null);
  const [features, setFeatures] = useState<Record<string, number> | null>(null);
  const [calibration, setCalibration] = useState<Record<string, unknown> | null>(null);
  const [trades, setTrades] = useState<FrankensteinTrade[]>([]);
  const [backtestResult, setBacktestResult] = useState<Record<string, unknown> | null>(null);
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [backtestDays, setBacktestDays] = useState(30);

  const fetchAnalytics = useCallback(async () => {
    const [a, p, t] = await Promise.all([
      api.frankenstein.analytics().catch(() => null),
      api.frankenstein.performanceSnapshot().catch(() => null),
      api.frankenstein.recentTrades(200).catch(() => []),
    ]);
    if (a) setAnalytics(a as Record<string, unknown>);
    if (p) setPerfSnap(p as Record<string, unknown>);
    setTrades(t);
  }, []);

  const fetchModel = useCallback(async () => {
    const [m, f, c] = await Promise.all([
      api.frankenstein.modelIntelligence().catch(() => null),
      api.frankenstein.features().catch(() => null),
      api.frankenstein.modelCalibration().catch(() => null),
    ]);
    if (m) setModelInfo(m as Record<string, unknown>);
    if (f && typeof f === "object") {
      const feats = (f as Record<string, unknown>).top_features ?? (f as Record<string, unknown>).features ?? f;
      if (typeof feats === "object") setFeatures(feats as Record<string, number>);
    }
    if (c) setCalibration(c as Record<string, unknown>);
  }, []);

  useEffect(() => {
    fetchAnalytics();
    fetchModel();
    const iv = setInterval(fetchAnalytics, 30000);
    return () => clearInterval(iv);
  }, [fetchAnalytics, fetchModel]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const overview = analytics?.overview as Record<string, any> | undefined;
  const byCategory = analytics?.by_category as Record<string, Record<string, number>> | undefined;
  const byConfidence = analytics?.by_confidence as Record<string, Record<string, number>> | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pnlCurve = analytics?.pnl_curve as Array<Record<string, any>> | undefined;
  const realTrades = trades.filter((t) => !t.model_version?.startsWith("bootstrap"));

  const SUB_TABS: { id: SubTab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "categories", label: "Categories" },
    { id: "confidence", label: "Confidence" },
    { id: "model", label: "Model" },
    { id: "backtest", label: "Backtest" },
  ];

  const runBacktest = async () => {
    setBacktestRunning(true);
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${API_BASE}/api/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy: "frankenstein", days: backtestDays }),
      });
      if (res.ok) setBacktestResult(await res.json());
    } catch { /* ignore */ }
    setBacktestRunning(false);
  };

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Total Trades" value={overview?.total_trades ?? "--"} icon={<IconTarget size={16} />} />
        <StatCard label="Win Rate" value={overview?.win_rate != null ? `${(overview.win_rate * 100).toFixed(0)}%` : "--"} icon={<IconShield size={16} />} />
        <StatCard label="Total P&L" value={overview?.total_pnl != null ? pnlSign(overview.total_pnl) : "--"} change={overview?.total_pnl} icon={<IconTrendUp size={16} />} />
        <StatCard label="Sharpe" value={overview?.sharpe_ratio?.toFixed(2) ?? "--"} icon={<IconStrategy size={16} />} />
        <StatCard label="Profit Factor" value={overview?.profit_factor?.toFixed(2) ?? "--"} icon={<IconBrain size={16} />} />
        <StatCard label="Max Drawdown" value={overview?.max_drawdown != null ? `$${overview.max_drawdown.toFixed(2)}` : "--"} icon={<IconTrendDown size={16} />} />
      </div>

      {/* Sub tabs */}
      <div className="flex items-center gap-1 border-b border-white/[0.06]">
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setSub(t.id)}
            className={cn(
              "relative px-3 py-2 text-sm font-medium transition-colors",
              sub === t.id ? "text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
            )}
          >
            {t.label}
            {sub === t.id && <div className="absolute bottom-0 left-1 right-1 h-[2px] rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      {/* ── Overview ──────────────────────────────────────────────────── */}
      {sub === "overview" && (
        <div className="space-y-4">
          {/* Interactive Equity Curve */}
          <Card title="Cumulative P&L" action={
            pnlCurve && pnlCurve.length > 0 ? (
              <span className="text-xs text-[var(--text-muted)] tabular-nums">{pnlCurve.length} data points</span>
            ) : null
          }>
            {pnlCurve && pnlCurve.length > 2 ? (
              <EquityCurve data={pnlCurve} height={260} />
            ) : (
              <div className="flex h-48 items-center justify-center text-sm text-[var(--text-muted)]">
                Not enough trades for a chart
              </div>
            )}
          </Card>

          {/* Category + Confidence side by side */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="By Category">
              {byCategory && Object.keys(byCategory).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(byCategory)
                    .sort((a, b) => (b[1].total_pnl ?? 0) - (a[1].total_pnl ?? 0))
                    .map(([cat, stats]) => (
                      <CategoryRow key={cat} category={cat} stats={stats} />
                    ))}
                </div>
              ) : (
                <div className="py-6 text-center text-sm text-[var(--text-muted)]">No category data</div>
              )}
            </Card>

            <Card title="By Confidence Band">
              {byConfidence && Object.keys(byConfidence).length > 0 ? (
                <div className="space-y-2">
                  {Object.entries(byConfidence)
                    .sort((a, b) => b[0].localeCompare(a[0]))
                    .map(([band, stats]) => (
                      <ConfidenceRow key={band} band={band} stats={stats} />
                    ))}
                </div>
              ) : (
                <div className="py-6 text-center text-sm text-[var(--text-muted)]">No confidence data</div>
              )}
            </Card>
          </div>

          {/* Trade log */}
          <Card title="Trade Log" action={<span className="text-xs text-[var(--text-muted)]">{realTrades.length} trades</span>}>
            <TradeTable trades={realTrades} />
          </Card>
        </div>
      )}

      {/* ── Categories ────────────────────────────────────────────────── */}
      {sub === "categories" && (
        <Card title="Performance by Category">
          {byCategory && Object.keys(byCategory).length > 0 ? (
            <div className="space-y-3">
              {Object.entries(byCategory)
                .sort((a, b) => (b[1].total_pnl ?? 0) - (a[1].total_pnl ?? 0))
                .map(([cat, stats]) => (
                  <CategoryDetailRow key={cat} category={cat} stats={stats} />
                ))}
            </div>
          ) : (
            <div className="py-8 text-center text-sm text-[var(--text-muted)]">No category data available</div>
          )}
        </Card>
      )}

      {/* ── Confidence ────────────────────────────────────────────────── */}
      {sub === "confidence" && (
        <Card title="Performance by Confidence Band">
          {byConfidence && Object.keys(byConfidence).length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                    <th className="pb-2 pr-4 font-medium">Band</th>
                    <th className="pb-2 pr-4 text-right font-medium">Trades</th>
                    <th className="pb-2 pr-4 text-right font-medium">Win Rate</th>
                    <th className="pb-2 pr-4 text-right font-medium">P&L</th>
                    <th className="pb-2 text-right font-medium">Avg Edge</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(byConfidence)
                    .sort((a, b) => b[0].localeCompare(a[0]))
                    .map(([band, stats]) => (
                      <tr key={band} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                        <td className="py-2 pr-4 text-sm font-medium text-[var(--text-primary)]">{band}</td>
                        <td className="py-2 pr-4 text-right tabular-nums text-[var(--text-secondary)]">{stats.count ?? 0}</td>
                        <td className="py-2 pr-4 text-right tabular-nums text-[var(--text-secondary)]">
                          {stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(0)}%` : "--"}
                        </td>
                        <td className={`py-2 pr-4 text-right tabular-nums font-medium ${pnlColor(stats.total_pnl ?? 0)}`}>
                          {pnlSign(stats.total_pnl ?? 0)}
                        </td>
                        <td className="py-2 text-right tabular-nums text-[var(--text-secondary)]">
                          {stats.avg_edge != null ? `${(stats.avg_edge * 100).toFixed(1)}c` : "--"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-8 text-center text-sm text-[var(--text-muted)]">No confidence data</div>
          )}
        </Card>
      )}

      {/* ── Model ─────────────────────────────────────────────────────── */}
      {sub === "model" && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Model Intelligence">
              {modelInfo ? (
                <div className="space-y-1.5">
                  <InfoRow label="Name" value={String(modelInfo.model_name ?? "unknown")} mono />
                  <InfoRow label="Version" value={String(modelInfo.model_version ?? "unknown")} mono />
                  <InfoRow label="Trained" value={modelInfo.is_trained ? "Yes" : "No"} />
                  <InfoRow label="Generation" value={String(modelInfo.generation ?? 0)} />
                  {(modelInfo.ensemble as Record<string, unknown>)?.num_trees != null && (
                    <InfoRow label="Trees" value={String((modelInfo.ensemble as Record<string, unknown>).num_trees)} />
                  )}
                  {(modelInfo.features as Record<string, unknown>)?.count != null && (
                    <InfoRow label="Features" value={String((modelInfo.features as Record<string, unknown>).count)} />
                  )}
                </div>
              ) : (
                <div className="py-6 text-center text-sm text-[var(--text-muted)]">No model data</div>
              )}
            </Card>

            <Card title="Calibration">
              {calibration && calibration.available ? (
                <div className="space-y-1.5">
                  {Object.entries(calibration)
                    .filter(([k]) => k !== "available")
                    .map(([k, v]) => (
                      <InfoRow key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? v.toFixed(4) : String(v)} />
                    ))}
                </div>
              ) : (
                <div className="py-6 text-center text-sm text-[var(--text-muted)]">Calibration not available</div>
              )}
            </Card>
          </div>

          <Card title="Top Features">
            {features && Object.keys(features).length > 0 ? (
              <div className="space-y-2">
                {Object.entries(features)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 15)
                  .map(([name, importance]) => {
                    const maxVal = Math.max(...Object.values(features));
                    const pct = maxVal > 0 ? (importance / maxVal) * 100 : 0;
                    return (
                      <div key={name} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-[var(--text-secondary)] font-mono">{name}</span>
                          <span className="text-[var(--text-muted)] tabular-nums">{importance.toFixed(4)}</span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-white/[0.06]">
                          <div className="h-1.5 rounded-full bg-accent/60 transition-all" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">No feature data</div>
            )}
          </Card>
        </div>
      )}

      {/* ── Backtest ──────────────────────────────────────────────────── */}
      {sub === "backtest" && (
        <Card title="Run Backtest">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <label className="text-sm text-[var(--text-muted)]">Days:</label>
              <input
                type="number"
                value={backtestDays}
                onChange={(e) => setBacktestDays(parseInt(e.target.value) || 30)}
                className="w-20 rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-1.5 text-sm text-[var(--text-primary)] tabular-nums"
              />
              <button
                onClick={runBacktest}
                disabled={backtestRunning}
                className="rounded-lg bg-accent/10 border border-accent/20 px-4 py-1.5 text-sm font-medium text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
              >
                {backtestRunning ? "Running..." : "Run"}
              </button>
            </div>
            {backtestResult && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {([
                  ["Trades", String(backtestResult.total_trades ?? "--")],
                  ["Win Rate", backtestResult.win_rate != null ? `${((backtestResult.win_rate as number) * 100).toFixed(0)}%` : "--"],
                  ["P&L", backtestResult.total_pnl != null ? pnlSign(backtestResult.total_pnl as number) : "--"],
                  ["Sharpe", (backtestResult.sharpe_ratio as number)?.toFixed(2) ?? "--"],
                ] as [string, string][]).map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-3">
                    <div className="text-[10px] text-[var(--text-muted)] uppercase">{label}</div>
                    <div className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">{value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Category row ─────────────────────────────────────────────────────── */

function CategoryRow({ category, stats }: { category: string; stats: Record<string, number> }) {
  const wrPct = stats.win_rate != null ? stats.win_rate * 100 : 0;
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-sm">{categoryEmoji(category)}</span>
        <span className="text-sm text-[var(--text-primary)] capitalize">{category}</span>
      </div>
      <div className="flex items-center gap-4 text-xs tabular-nums">
        <span className="text-[var(--text-muted)]">{stats.count ?? 0} trades</span>
        <span className={wrPct >= 50 ? "text-accent" : wrPct > 0 ? "text-[var(--warning)]" : "text-[var(--text-muted)]"}>
          {stats.win_rate != null ? `${wrPct.toFixed(0)}% WR` : ""}
        </span>
        <span className={`font-medium ${pnlColor(stats.total_pnl ?? 0)}`}>{pnlSign(stats.total_pnl ?? 0)}</span>
      </div>
    </div>
  );
}

function CategoryDetailRow({ category, stats }: { category: string; stats: Record<string, number> }) {
  return (
    <div className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span>{categoryEmoji(category)}</span>
          <span className="text-sm font-medium text-[var(--text-primary)] capitalize">{category}</span>
        </div>
        <span className={`text-sm font-semibold tabular-nums ${pnlColor(stats.total_pnl ?? 0)}`}>
          {pnlSign(stats.total_pnl ?? 0)}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-[var(--text-muted)]">Trades</div>
          <div className="tabular-nums text-[var(--text-secondary)]">{stats.count ?? 0}</div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Win Rate</div>
          <div className="tabular-nums text-[var(--text-secondary)]">
            {stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(0)}%` : "--"}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Avg Edge</div>
          <div className="tabular-nums text-[var(--text-secondary)]">
            {stats.avg_edge != null ? `${(stats.avg_edge * 100).toFixed(1)}c` : "--"}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)]">Avg P&L</div>
          <div className={`tabular-nums ${pnlColor(stats.avg_pnl ?? 0)}`}>
            {stats.avg_pnl != null ? pnlSign(stats.avg_pnl) : "--"}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Confidence row ───────────────────────────────────────────────────── */

function ConfidenceRow({ band, stats }: { band: string; stats: Record<string, number> }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <span className="text-sm text-[var(--text-primary)] font-mono">{band}</span>
      <div className="flex items-center gap-4 text-xs tabular-nums">
        <span className="text-[var(--text-muted)]">{stats.count ?? 0} trades</span>
        <span className="text-[var(--text-muted)]">
          {stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(0)}% WR` : ""}
        </span>
        <span className={`font-medium ${pnlColor(stats.total_pnl ?? 0)}`}>{pnlSign(stats.total_pnl ?? 0)}</span>
      </div>
    </div>
  );
}

/* ── Trade table ──────────────────────────────────────────────────────── */

function TradeTable({ trades }: { trades: FrankensteinTrade[] }) {
  if (trades.length === 0) {
    return <div className="py-6 text-center text-sm text-[var(--text-muted)]">No trades recorded</div>;
  }
  return (
    <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-[var(--bg-primary)]">
          <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
            <th className="pb-2 pr-4 font-medium">Time</th>
            <th className="pb-2 pr-4 font-medium">Market</th>
            <th className="pb-2 pr-4 font-medium">Side</th>
            <th className="pb-2 pr-4 text-right font-medium">Price</th>
            <th className="pb-2 pr-4 text-right font-medium">Conf</th>
            <th className="pb-2 pr-4 text-right font-medium">Edge</th>
            <th className="pb-2 pr-4 font-medium">Outcome</th>
            <th className="pb-2 text-right font-medium">P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.slice(0, 50).map((t, i) => (
            <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
              <td className="py-1.5 pr-4 text-xs tabular-nums text-[var(--text-muted)]">{timeAgo(t.timestamp)}</td>
              <td className="py-1.5 pr-4 text-xs text-[var(--text-primary)] truncate max-w-[180px]">{prettifyTicker(t.ticker)}</td>
              <td className="py-1.5 pr-4">
                <span className={`text-[10px] font-semibold uppercase ${t.side === "yes" ? "text-accent" : "text-[var(--danger)]"}`}>{t.side}</span>
              </td>
              <td className="py-1.5 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">{t.price_cents}c</td>
              <td className="py-1.5 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">{((t.confidence ?? 0) * 100).toFixed(0)}%</td>
              <td className="py-1.5 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">{((t.edge ?? 0) * 100).toFixed(1)}c</td>
              <td className="py-1.5 pr-4">
                <span className={`text-[10px] font-semibold uppercase ${
                  t.outcome === "win" ? "text-accent" : t.outcome === "loss" ? "text-[var(--danger)]" : "text-[var(--text-muted)]"
                }`}>{t.outcome}</span>
              </td>
              <td className={`py-1.5 text-right text-xs tabular-nums font-medium ${pnlColor(t.pnl_cents ?? 0)}`}>
                {(t.pnl_cents ?? 0) !== 0 ? `${t.pnl_cents > 0 ? "+" : ""}${(t.pnl_cents / 100).toFixed(2)}` : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Small components ─────────────────────────────────────────────────── */

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
      <span className="text-xs text-[var(--text-muted)] capitalize">{label}</span>
      <span className={`text-xs font-medium tabular-nums text-[var(--text-primary)] ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}
