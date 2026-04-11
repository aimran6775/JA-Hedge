"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useSSE } from "@/lib/useSSE";

/* ═══════════════════════════════════════════════════════════════════════
   LIVE TAB — Clean, minimal real-time trading dashboard
   Phase 1-20: Complete redesign for clarity
   ═══════════════════════════════════════════════════════════════════════ */

export function LiveTab() {
  const { data: sse, connected, lastUpdate } = useSSE();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equityData, setEquityData] = useState<EquityPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Fetch trades with P&L data
  const fetchData = useCallback(async () => {
    try {
      const [tradesRes, analyticsRes] = await Promise.all([
        api.frankenstein.recentTrades(50).catch(() => []),
        api.frankenstein.analytics().catch(() => null),
      ]);
      
      // Transform trades with proper P&L
      const transformed = (tradesRes || []).map((t: RawTrade) => ({
        id: t.trade_id || `${t.ticker}-${t.timestamp}`,
        ticker: t.ticker,
        title: t.market_title || prettifyTicker(t.ticker),
        side: t.side,
        count: t.count,
        priceCents: t.price_cents,
        pnlCents: t.pnl_cents || 0,
        outcome: t.outcome || "pending",
        confidence: t.confidence || 0,
        edge: t.edge || 0,
        timestamp: t.timestamp,
        category: t.category || "unknown",
      }));
      setTrades(transformed);

      // Build equity curve from analytics
      if (analyticsRes?.pnl_curve) {
        const curve = analyticsRes.pnl_curve.map((p: { ts?: number; timestamp?: number; pnl?: number; cumulative_pnl?: number }) => ({
          time: p.ts || p.timestamp || 0,
          value: p.pnl ?? p.cumulative_pnl ?? 0,
        }));
        setEquityData(curve);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10000);
    return () => clearInterval(iv);
  }, [fetchData]);

  // Derived values
  const frank = sse?.frankenstein;
  const isLive = frank?.is_alive && frank?.is_trading && !frank?.is_paused || false;
  const balance = sse?.balance?.balance_cents || 0;
  const dailyPnl = sse?.pnl?.daily_pnl || 0;
  const positions = sse?.positions?.length || 0;
  const winRate = frank?.performance?.win_rate || 0;
  const totalPnl = frank?.performance?.total_pnl || 0;
  
  // Separate wins/losses
  const resolvedTrades = trades.filter(t => t.outcome !== "pending");
  const wins = resolvedTrades.filter(t => t.outcome === "win");
  const losses = resolvedTrades.filter(t => t.outcome === "loss");
  const realizedPnl = resolvedTrades.reduce((sum, t) => sum + t.pnlCents, 0);
  const unrealizedPnl = dailyPnl * 100 - realizedPnl; // Approximate

  const lastUpdateAgo = lastUpdate ? Math.round((Date.now() - lastUpdate) / 1000) : null;

  return (
    <div className="space-y-4 p-1">
      {/* Status Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StatusDot active={isLive} />
          <span className={`text-sm font-semibold ${isLive ? "text-accent" : "text-muted"}`}>
            {isLive ? "Trading" : frank?.is_paused ? "Paused" : "Offline"}
          </span>
          {frank?.generation && (
            <span className="text-xs text-muted">Gen {frank.generation}</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-accent" : "bg-loss animate-pulse"}`} />
          {connected ? (lastUpdateAgo !== null ? `${lastUpdateAgo}s ago` : "Live") : "Reconnecting..."}
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-loss/30 bg-loss/10 p-3 text-sm text-loss">{error}</div>
      )}

      {/* Key Metrics - Single Row */}
      <div className="grid grid-cols-4 gap-3">
        <MetricCard label="Balance" value={`$${(balance / 100).toFixed(2)}`} />
        <MetricCard 
          label="Today's P&L" 
          value={`${dailyPnl >= 0 ? "+" : ""}$${Math.abs(dailyPnl).toFixed(2)}`}
          color={dailyPnl >= 0 ? "text-accent" : "text-loss"}
        />
        <MetricCard label="Win Rate" value={`${(winRate * 100).toFixed(0)}%`} />
        <MetricCard label="Positions" value={`${positions}`} />
      </div>

      {/* Equity Chart */}
      <div className="rounded-xl glass p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-secondary">Equity Curve</h3>
          <span className={`text-sm font-semibold tabular-nums ${totalPnl >= 0 ? "text-accent" : "text-loss"}`}>
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)} total
          </span>
        </div>
        <EquityChart data={equityData} height={180} />
      </div>

      {/* P&L Breakdown */}
      <div className="rounded-xl glass p-4">
        <h3 className="text-sm font-medium text-secondary mb-3">P&L Breakdown</h3>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <div className="text-xs text-muted uppercase tracking-wider">Realized</div>
            <div className={`text-lg font-semibold tabular-nums ${realizedPnl >= 0 ? "text-accent" : "text-loss"}`}>
              {realizedPnl >= 0 ? "+" : ""}${(realizedPnl / 100).toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase tracking-wider">Unrealized</div>
            <div className={`text-lg font-semibold tabular-nums ${unrealizedPnl >= 0 ? "text-accent" : "text-loss"}`}>
              {unrealizedPnl >= 0 ? "+" : ""}${(unrealizedPnl / 100).toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase tracking-wider">Record</div>
            <div className="text-lg font-semibold tabular-nums">
              <span className="text-accent">{wins.length}W</span>
              <span className="text-muted mx-1">/</span>
              <span className="text-loss">{losses.length}L</span>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Trades - Clean Table */}
      <div className="rounded-xl glass p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-secondary">Recent Trades</h3>
          <span className="text-xs text-muted">{trades.length} trades</span>
        </div>
        <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
          {trades.slice(0, 15).map((trade) => (
            <TradeRow key={trade.id} trade={trade} />
          ))}
          {trades.length === 0 && (
            <div className="py-8 text-center text-sm text-muted">
              {isLive ? "Scanning for opportunities..." : "Start trading to see results"}
            </div>
          )}
        </div>
      </div>

      {/* Active Positions (if any) */}
      {sse?.positions && sse.positions.length > 0 && (
        <div className="rounded-xl glass p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-secondary">Active Positions</h3>
            <span className="text-xs text-muted">{sse.positions.length} open</span>
          </div>
          <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
            {sse.positions.map((pos) => (
              <PositionRow key={pos.ticker} position={pos} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Components ────────────────────────────────────────────────────────── */

interface Trade {
  id: string;
  ticker: string;
  title: string;
  side: string;
  count: number;
  priceCents: number;
  pnlCents: number;
  outcome: string;
  confidence: number;
  edge: number;
  timestamp: string;
  category: string;
}

interface RawTrade {
  trade_id?: string;
  ticker: string;
  market_title?: string;
  side: string;
  count: number;
  price_cents: number;
  pnl_cents?: number;
  outcome?: string;
  confidence?: number;
  edge?: number;
  timestamp: string;
  category?: string;
}

interface EquityPoint {
  time: number;
  value: number;
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-2.5 w-2.5">
      {active && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-50" />
      )}
      <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${active ? "bg-accent" : "bg-muted"}`} />
    </span>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl glass p-3">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${color || "text-primary"}`}>{value}</div>
    </div>
  );
}

function TradeRow({ trade }: { trade: Trade }) {
  const isWin = trade.outcome === "win";
  const isLoss = trade.outcome === "loss";
  const isPending = trade.outcome === "pending";
  
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2 hover:bg-white/[0.04] transition-colors">
      <div className="flex items-center gap-3 min-w-0 flex-1">
        {/* Win/Loss indicator */}
        <div className={`flex h-6 w-6 items-center justify-center rounded-md flex-shrink-0 text-[10px] font-bold ${
          isWin ? "bg-accent/20 text-accent" : isLoss ? "bg-loss/20 text-loss" : "bg-white/10 text-muted"
        }`}>
          {isWin && "W"}
          {isLoss && "L"}
          {isPending && "-"}
        </div>
        
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-primary truncate">{trade.title}</div>
          <div className="text-[10px] text-muted">
            {trade.side.toUpperCase()} x{trade.count} @ {trade.priceCents}c
            <span className="mx-1">·</span>
            {timeAgo(trade.timestamp)}
          </div>
        </div>
      </div>
      
      {/* P&L */}
      <div className="text-right flex-shrink-0 ml-3">
        <div className={`text-sm font-semibold tabular-nums ${
          trade.pnlCents > 0 ? "text-accent" : trade.pnlCents < 0 ? "text-loss" : "text-muted"
        }`}>
          {trade.pnlCents > 0 ? "+" : ""}{trade.pnlCents !== 0 ? `$${(trade.pnlCents / 100).toFixed(2)}` : "--"}
        </div>
        {!isPending && (
          <div className="text-[9px] text-muted uppercase tracking-wider">
            {isWin ? "WIN" : isLoss ? "LOSS" : ""}
          </div>
        )}
      </div>
    </div>
  );
}

function PositionRow({ position }: { position: { ticker: string; position: number; market_exposure_dollars?: string | null; realized_pnl_dollars?: string | null } }) {
  const pnl = position.realized_pnl_dollars ? parseFloat(position.realized_pnl_dollars) : 0;
  
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-primary truncate">{prettifyTicker(position.ticker)}</div>
        <div className="text-[10px] text-muted">
          {position.position > 0 ? "YES" : "NO"} ×{Math.abs(position.position)}
          {position.market_exposure_dollars && <span className="ml-1">· ${position.market_exposure_dollars} at risk</span>}
        </div>
      </div>
      {pnl !== 0 && (
        <div className={`text-sm font-semibold tabular-nums ${pnl >= 0 ? "text-accent" : "text-loss"}`}>
          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
        </div>
      )}
    </div>
  );
}

function EquityChart({ data, height }: { data: EquityPoint[]; height: number }) {
  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        Not enough data for chart
      </div>
    );
  }

  // Simple SVG line chart
  const minVal = Math.min(...data.map(d => d.value));
  const maxVal = Math.max(...data.map(d => d.value));
  const range = maxVal - minVal || 1;
  const padding = 10;
  
  const points = data.map((d, i) => {
    const x = (i / (data.length - 1)) * 100;
    const y = 100 - ((d.value - minVal) / range) * 100;
    return `${x},${y}`;
  }).join(" ");

  const lastValue = data[data.length - 1]?.value || 0;
  const isPositive = lastValue >= 0;

  return (
    <svg viewBox={`-${padding} -${padding} ${100 + padding * 2} ${100 + padding * 2}`} className="w-full" style={{ height }}>
      {/* Grid lines */}
      <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(255,255,255,0.06)" strokeDasharray="2,2" />
      <line x1="0" y1="0" x2="100" y2="0" stroke="rgba(255,255,255,0.03)" />
      <line x1="0" y1="100" x2="100" y2="100" stroke="rgba(255,255,255,0.03)" />
      
      {/* Line */}
      <polyline
        fill="none"
        stroke={isPositive ? "var(--accent)" : "var(--loss)"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
      
      {/* Gradient fill */}
      <defs>
        <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={isPositive ? "var(--accent)" : "var(--loss)"} stopOpacity="0.3" />
          <stop offset="100%" stopColor={isPositive ? "var(--accent)" : "var(--loss)"} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        fill="url(#equityGradient)"
        points={`0,100 ${points} 100,100`}
      />
    </svg>
  );
}

/* ── Utilities ─────────────────────────────────────────────────────────── */

function prettifyTicker(ticker: string): string {
  return ticker
    .replace(/^KX/, "")
    .replace(/-\d{2}[A-Z]{3}\d{2}.*$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/-/g, " ")
    .slice(0, 30);
}

function timeAgo(ts: string | number): string {
  const now = Date.now();
  const then = typeof ts === "string" ? new Date(ts).getTime() : ts * 1000;
  const seconds = Math.floor((now - then) / 1000);
  
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}
