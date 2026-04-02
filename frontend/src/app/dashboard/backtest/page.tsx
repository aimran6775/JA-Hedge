"use client";

import { useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconTarget, IconTrendUp, IconTrendDown, IconZap, IconShield } from "@/components/ui/Icons";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface BacktestResult {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  sharpe_ratio: number;
  max_drawdown: number;
  profit_factor: number;
  trades: Array<{
    ticker: string;
    side: string;
    confidence: number;
    edge: number;
    pnl: number;
    outcome: string;
    timestamp: string;
  }>;
}

function pnlColor(v: number) {
  return v > 0 ? "text-accent" : v < 0 ? "text-loss" : "text-[var(--text-muted)]";
}
function pnlSign(v: number) {
  return v > 0 ? `+$${v.toFixed(2)}` : v < 0 ? `-$${Math.abs(v).toFixed(2)}` : "$0.00";
}

export default function BacktestPage() {
  const [strategy, setStrategy] = useState("frankenstein");
  const [days, setDays] = useState(7);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runBacktest = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/api/backtest/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy, days }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || body.message || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    }
    setRunning(false);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Backtest</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">Run historical backtests on trading strategies</p>
      </div>

      {/* Config */}
      <Card title="Backtest Configuration">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Strategy</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
              className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] focus:border-accent/30 transition-all">
              <option value="frankenstein">Frankenstein AI</option>
              <option value="momentum">Momentum</option>
              <option value="mean_reversion">Mean Reversion</option>
              <option value="sports">Sports Predictor</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Lookback (days)</label>
            <input type="number" value={days} onChange={(e) => setDays(Number(e.target.value))} min={1} max={90}
              className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] tabular-nums focus:border-accent/30 transition-all" />
          </div>
          <div className="flex items-end">
            <button onClick={runBacktest} disabled={running}
              className={`w-full rounded-xl py-2.5 text-sm font-bold tracking-wide transition-all bg-accent text-white hover:bg-accent/90 ${running ? "opacity-50 cursor-wait" : ""}`}>
              {running ? "Running..." : "Run Backtest"}
            </button>
          </div>
        </div>
      </Card>

      {error && (
        <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">{error}</div>
      )}

      {/* Results */}
      {result && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Total P&L" value={pnlSign(result.total_pnl)} change={result.total_pnl} icon={result.total_pnl >= 0 ? <IconTrendUp size={18} /> : <IconTrendDown size={18} />} />
            <StatCard label="Win Rate" value={`${(result.win_rate * 100).toFixed(1)}%`} icon={<IconTarget size={18} />} />
            <StatCard label="Trades" value={String(result.total_trades)} icon={<IconZap size={18} />} />
            <StatCard label="Profit Factor" value={`${result.profit_factor.toFixed(2)}x`} icon={<IconShield size={18} />} />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Performance Summary">
              <div className="space-y-2">
                <div className="flex justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                  <span className="text-xs text-[var(--text-muted)]">Total Trades</span>
                  <span className="text-xs font-medium text-[var(--text-primary)]">{result.total_trades}</span>
                </div>
                <div className="flex justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                  <span className="text-xs text-[var(--text-muted)]">Wins / Losses</span>
                  <span className="text-xs font-medium"><span className="text-accent">{result.wins}</span> / <span className="text-loss">{result.losses}</span></span>
                </div>
                <div className="flex justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                  <span className="text-xs text-[var(--text-muted)]">Sharpe Ratio</span>
                  <span className="text-xs font-medium text-[var(--text-primary)]">{result.sharpe_ratio.toFixed(2)}</span>
                </div>
                <div className="flex justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                  <span className="text-xs text-[var(--text-muted)]">Max Drawdown</span>
                  <span className="text-xs font-medium text-loss">${result.max_drawdown.toFixed(2)}</span>
                </div>
              </div>
            </Card>

            <Card title="Backtest Trades" action={<span className="text-xs text-[var(--text-muted)]">{result.trades.length} trades</span>}>
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                {result.trades.map((t, i) => (
                  <div key={i} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                    <div>
                      <div className="text-xs font-mono text-[var(--text-primary)]">{t.ticker}</div>
                      <div className="text-[10px] text-[var(--text-muted)]">{t.side.toUpperCase()} · {(t.confidence * 100).toFixed(0)}% conf</div>
                    </div>
                    <div className="text-right">
                      <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                        t.outcome === "win" ? "bg-accent/10 text-accent" : t.outcome === "loss" ? "bg-loss/10 text-loss" : "bg-white/5 text-[var(--text-muted)]"
                      }`}>{t.outcome}</span>
                      <div className={`text-[10px] tabular-nums font-mono mt-0.5 ${pnlColor(t.pnl)}`}>
                        {pnlSign(t.pnl)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}

      {!result && !error && !running && (
        <Card>
          <div className="py-16 text-center">
            <div className="text-4xl mb-4">📊</div>
            <div className="text-lg font-semibold text-[var(--text-primary)]">Configure &amp; Run a Backtest</div>
            <p className="text-sm text-[var(--text-muted)] mt-2 max-w-md mx-auto">
              Select a strategy, set the lookback period, and run to see historical performance simulation.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}
