"use client";

import { useEffect, useState, useCallback } from "react";
import { api, type FrankensteinTrade } from "@/lib/api";

/* ═══════════════════════════════════════════════════════════════════════
   ANALYTICS TAB — Simplified performance analytics
   ═══════════════════════════════════════════════════════════════════════ */
export function AnalyticsTab() {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [trades, setTrades] = useState<FrankensteinTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [a, t] = await Promise.all([
        api.frankenstein.analytics().catch(() => null),
        api.frankenstein.recentTrades(100).catch(() => []),
      ]);
      if (a) setAnalytics(a as AnalyticsData);
      setTrades(t);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 30000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // Overview stats
  const overview = analytics?.overview;
  const byCategory = analytics?.by_category;
  
  // Process trades
  const resolvedTrades = trades.filter(t => t.outcome && t.outcome !== "pending");
  const wins = resolvedTrades.filter(t => t.outcome === "win");
  const losses = resolvedTrades.filter(t => t.outcome === "loss");
  const winRate = resolvedTrades.length > 0 ? wins.length / resolvedTrades.length : 0;
  const totalPnl = resolvedTrades.reduce((sum, t) => sum + (t.pnl_cents || 0), 0);
  const avgWin = wins.length > 0 ? wins.reduce((sum, t) => sum + (t.pnl_cents || 0), 0) / wins.length : 0;
  const avgLoss = losses.length > 0 ? losses.reduce((sum, t) => sum + (t.pnl_cents || 0), 0) / losses.length : 0;

  // Filtered trades
  const displayTrades = selectedCategory 
    ? resolvedTrades.filter(t => t.category === selectedCategory)
    : resolvedTrades;

  if (loading && !analytics) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-1">
      {error && (
        <div className="rounded-lg border border-loss/30 bg-loss/10 p-3 text-sm text-loss">{error}</div>
      )}

      {/* Performance Summary */}
      <div className="rounded-xl glass p-4">
        <h3 className="text-sm font-medium text-secondary mb-4">Performance Summary</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatBox 
            label="Total P&L" 
            value={`${totalPnl >= 0 ? "+" : ""}$${(totalPnl / 100).toFixed(2)}`}
            color={totalPnl >= 0 ? "accent" : "loss"}
          />
          <StatBox 
            label="Win Rate" 
            value={`${(winRate * 100).toFixed(1)}%`}
            color={winRate >= 0.5 ? "accent" : "loss"}
          />
          <StatBox 
            label="Total Trades" 
            value={resolvedTrades.length.toString()}
          />
          <StatBox 
            label="W/L" 
            value={`${wins.length}/${losses.length}`}
            color={wins.length >= losses.length ? "accent" : "loss"}
          />
        </div>
      </div>

      {/* Avg Win/Loss */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl glass p-4">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Avg Win</div>
          <div className="text-xl font-semibold text-accent tabular-nums">
            +${(avgWin / 100).toFixed(2)}
          </div>
        </div>
        <div className="rounded-xl glass p-4">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Avg Loss</div>
          <div className="text-xl font-semibold text-loss tabular-nums">
            ${(avgLoss / 100).toFixed(2)}
          </div>
        </div>
      </div>

      {/* Category Breakdown */}
      {byCategory && Object.keys(byCategory).length > 0 && (
        <div className="rounded-xl glass p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-secondary">By Category</h3>
            {selectedCategory && (
              <button 
                onClick={() => setSelectedCategory(null)}
                className="text-xs text-accent hover:underline"
              >
                Clear filter
              </button>
            )}
          </div>
          <div className="space-y-2">
            {Object.entries(byCategory).map(([cat, stats]) => (
              <CategoryRow 
                key={cat} 
                category={cat} 
                stats={stats}
                selected={selectedCategory === cat}
                onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Trade History */}
      <div className="rounded-xl glass p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-secondary">
            {selectedCategory ? `${selectedCategory} Trades` : "All Resolved Trades"}
          </h3>
          <span className="text-xs text-muted">{displayTrades.length} trades</span>
        </div>
        <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
          {displayTrades.slice(0, 50).map((trade, i) => (
            <TradeHistoryRow key={trade.trade_id || i} trade={trade} />
          ))}
          {displayTrades.length === 0 && (
            <div className="py-8 text-center text-sm text-muted">No trades to display</div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Components ────────────────────────────────────────────────────────── */

interface AnalyticsData {
  overview?: {
    total_trades?: number;
    win_rate?: number;
    total_pnl?: number;
    avg_confidence?: number;
  };
  by_category?: Record<string, CategoryStats>;
  pnl_curve?: Array<{ ts?: number; timestamp?: number; pnl?: number }>;
}

interface CategoryStats {
  trades: number;
  wins: number;
  losses: number;
  pnl_cents: number;
  pnl_dollars?: number;
  win_rate?: number;
  roi_pct?: number;
}

function StatBox({ label, value, color }: { label: string; value: string; color?: "accent" | "loss" }) {
  const colorClass = color === "accent" ? "text-accent" : color === "loss" ? "text-loss" : "text-primary";
  return (
    <div>
      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${colorClass}`}>{value}</div>
    </div>
  );
}

function CategoryRow({ 
  category, 
  stats, 
  selected,
  onClick 
}: { 
  category: string; 
  stats: CategoryStats;
  selected: boolean;
  onClick: () => void;
}) {
  const winRate = stats.trades > 0 ? (stats.wins / stats.trades) * 100 : 0;
  const pnl = stats.pnl_cents || 0;

  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between rounded-lg px-3 py-2 transition-colors ${
        selected 
          ? "bg-accent/10 border border-accent/30" 
          : "bg-white/[0.02] border border-white/[0.04] hover:bg-white/[0.04]"
      }`}
    >
      <div className="text-left">
        <div className="text-sm font-medium text-primary capitalize">{category.replace(/_/g, " ")}</div>
        <div className="text-[10px] text-muted">
          {stats.wins}W / {stats.losses}L · {stats.trades} trades
        </div>
      </div>
      <div className="text-right">
        <div className={`text-sm font-semibold tabular-nums ${pnl >= 0 ? "text-accent" : "text-loss"}`}>
          {pnl >= 0 ? "+" : ""}${(pnl / 100).toFixed(2)}
        </div>
        <div className="text-[10px] text-muted">{winRate.toFixed(0)}% WR</div>
      </div>
    </button>
  );
}

function TradeHistoryRow({ trade }: { trade: FrankensteinTrade }) {
  const isWin = trade.outcome === "win";
  const isLoss = trade.outcome === "loss";
  const pnl = trade.pnl_cents || 0;

  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <div className="flex items-center gap-3 min-w-0 flex-1">
        <div className={`flex h-5 w-5 items-center justify-center rounded flex-shrink-0 text-[9px] font-bold ${
          isWin ? "bg-accent/20 text-accent" : isLoss ? "bg-loss/20 text-loss" : "bg-white/10 text-muted"
        }`}>
          {isWin && "W"}
          {isLoss && "L"}
          {!isWin && !isLoss && "-"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-primary truncate">{prettifyTicker(trade.ticker)}</div>
          <div className="text-[10px] text-muted">
            {trade.side?.toUpperCase()} ×{trade.count} @ {trade.price_cents}¢
            <span className="mx-1">·</span>
            {trade.category || "unknown"}
          </div>
        </div>
      </div>
      <div className={`text-sm font-semibold tabular-nums flex-shrink-0 ${
        pnl > 0 ? "text-accent" : pnl < 0 ? "text-loss" : "text-muted"
      }`}>
        {pnl > 0 ? "+" : ""}{pnl !== 0 ? `$${(pnl / 100).toFixed(2)}` : "--"}
      </div>
    </div>
  );
}

/* ── Utilities ─────────────────────────────────────────────────────────── */

function prettifyTicker(ticker: string): string {
  return ticker
    .replace(/^KX/, "")
    .replace(/-\d{2}[A-Z]{3}\d{2}.*$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/-/g, " ")
    .slice(0, 35);
}
