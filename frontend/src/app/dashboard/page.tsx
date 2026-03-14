"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconCircle, IconRefresh, IconTrendUp, IconTrendDown, IconShield, IconZap,
  IconPortfolio, IconBrain, IconTarget,
} from "@/components/ui/Icons";
import {
  api,
  type Balance,
  type PnL,
  type RiskSnapshot,
  type HealthStatus,
  type Position,
  type FrankensteinStatus,
  type FrankensteinTrade,
} from "@/lib/api";

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function pnlColor(v: number) {
  return v > 0 ? "text-accent" : v < 0 ? "text-loss" : "text-[var(--text-muted)]";
}
function pnlSign(v: number) {
  return v > 0 ? `+$${v.toFixed(2)}` : v < 0 ? `-$${Math.abs(v).toFixed(2)}` : "$0.00";
}

function prettifyTicker(ticker: string): string {
  let base = ticker.split("-")[0] ?? ticker;
  base = base.replace(/^(KX|INX|CPI|GDP|FED|NFL|NBA|MLB|NHL|NCAA)/, "$1 ");
  base = base.replace(/([a-z])([A-Z])/g, "$1 $2");
  base = base
    .replace(/SPORTS/g, " Sports").replace(/MULTI/g, " Multi").replace(/GAME/g, " Game")
    .replace(/EXTENDED/g, " Extended").replace(/OVER/g, " Over").replace(/UNDER/g, " Under")
    .replace(/TOTAL/g, " Total").replace(/SPREAD/g, " Spread").replace(/WINNER/g, " Winner")
    .replace(/POINTS/g, " Points").replace(/SCORE/g, " Score").replace(/MATCH/g, " Match")
    .replace(/PLAYER/g, " Player").replace(/TEAM/g, " Team").replace(/SERIES/g, " Series")
    .replace(/ROUND/g, " Round").replace(/MVP/g, " MVP").replace(/CHAMP/g, " Champ")
    .replace(/WORLD/g, " World").replace(/ELECTION/g, " Election").replace(/PRICE/g, " Price")
    .replace(/BITCOIN/g, " Bitcoin").replace(/ABOVE/g, " Above").replace(/BELOW/g, " Below")
    .replace(/WEATHER/g, " Weather").replace(/TEMP/g, " Temp").replace(/HIGH/g, " High")
    .replace(/LOW/g, " Low");
  return base.replace(/\s+/g, " ").trim() || ticker;
}

/* ════════════════════════════════════════════════════════════════════════════
   OVERVIEW DASHBOARD — Unified view connected to Frankenstein
   ════════════════════════════════════════════════════════════════════════════ */
export default function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [pnl, setPnl] = useState<PnL | null>(null);
  const [risk, setRisk] = useState<RiskSnapshot | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [frank, setFrank] = useState<FrankensteinStatus | null>(null);
  const [trades, setTrades] = useState<FrankensteinTrade[]>([]);
  const [marketTitles, setMarketTitles] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [h, b, p, r, pos, fs, ft] = await Promise.all([
        api.health().catch(() => null),
        api.portfolio.balance().catch(() => null),
        api.portfolio.pnl().catch(() => null),
        api.risk.snapshot().catch(() => null),
        api.portfolio.positions().catch(() => []),
        api.frankenstein.status().catch(() => null),
        api.frankenstein.recentTrades(10).catch(() => []),
      ]);
      setHealth(h);
      setBalance(b);
      setPnl(p);
      setRisk(r);
      setPositions(pos);
      if (fs) setFrank(fs);
      setTrades(ft);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  // Resolve market titles for positions & trades
  useEffect(() => {
    const allTickers = [
      ...positions.map(p => p.ticker),
      ...trades.map(t => t.ticker),
    ];
    const unknown = [...new Set(allTickers)].filter(tk => !marketTitles[tk]);
    if (unknown.length === 0) return;
    let cancelled = false;
    (async () => {
      const resolved: Record<string, string> = {};
      await Promise.all(
        unknown.map(async (tk) => {
          try {
            const m = await api.markets.get(tk);
            if (m?.title) resolved[tk] = m.title;
          } catch { /* title stays as ticker */ }
        })
      );
      if (!cancelled && Object.keys(resolved).length > 0) {
        setMarketTitles(prev => ({ ...prev, ...resolved }));
      }
    })();
    return () => { cancelled = true; };
  }, [positions, trades, marketTitles]);

  /* ── Derived values ────────────────────────────────────────────────── */
  const snap = frank?.performance?.snapshot;
  const mem = frank?.memory;
  const realTrades = trades.filter(t => !t.model_version?.startsWith("bootstrap"));
  const brainAlive = frank?.is_alive ?? false;
  const brainTrading = frank?.is_trading ?? false;
  const brainPaused = frank?.is_paused ?? false;

  const brainLabel = !brainAlive ? "Offline" : brainPaused ? "Paused" : brainTrading ? "Trading" : "Idle";
  const brainColor = !brainAlive ? "text-[var(--text-muted)]" : brainPaused ? "text-[var(--warning)]" : brainTrading ? "text-accent" : "text-blue-400";
  const brainDot = !brainAlive ? "bg-[var(--text-muted)]" : brainPaused ? "bg-[var(--warning)]" : brainTrading ? "bg-accent" : "bg-blue-400";

  return (
    <div className="space-y-5 animate-fade-in">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Overview</h1>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            All data synced from Frankenstein · Paper Trading Simulator
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Brain Status Pill */}
          <div className="flex items-center gap-2 rounded-xl glass px-3 py-2 text-xs">
            <span className="relative flex h-2.5 w-2.5">
              {brainAlive && brainTrading && !brainPaused && (
                <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${brainDot} opacity-50`} />
              )}
              <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${brainDot}`} />
            </span>
            <span className={`font-semibold uppercase tracking-wide ${brainColor}`}>
              {brainLabel}
            </span>
            {frank && (
              <span className="text-[var(--text-muted)]">
                · Gen {frank.generation} · {frank.total_scans} scans
              </span>
            )}
          </div>

          {health ? (
            <div className="flex items-center gap-2 rounded-xl glass px-3 py-2 text-xs">
              <IconCircle size={6} className={health.paper_trading?.enabled ? "text-[var(--warning)]" : "text-accent"} />
              <span className={`font-medium ${health.paper_trading?.enabled ? "text-[var(--warning)]" : "text-accent"}`}>
                {health.paper_trading?.enabled ? "PAPER" : health.mode.toUpperCase()}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-xl glass px-3 py-2 text-xs">
              <IconCircle size={6} className="text-loss animate-pulse" />
              <span className="text-loss">Offline</span>
            </div>
          )}
          <button onClick={fetchAll} className="rounded-xl glass p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all">
            <IconRefresh size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">{error}</div>
      )}

      {/* ── Top Stat Cards — same data source as Frankenstein page ──── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Balance" value={balance ? `$${balance.balance_dollars}` : "—"} icon={<IconPortfolio size={16} />} />
        <StatCard
          label="P&L"
          value={pnl ? pnlSign(pnl.daily_pnl) : "—"}
          change={pnl?.daily_pnl ?? 0}
          icon={<IconTrendUp size={16} />}
        />
        <StatCard label="Positions" value={`${positions.length}`} suffix=" open" icon={<IconTarget size={16} />} />
        <StatCard label="Trades" value={frank ? `${frank.total_trades_executed}` : "—"} suffix={frank ? ` / ${frank.total_trades_rejected} rej` : ""} icon={<IconZap size={16} />} />
        <StatCard label="Win Rate" value={snap && snap.real_trades > 0 ? `${(snap.win_rate * 100).toFixed(0)}%` : "—"} suffix={snap ? ` (${snap.real_trades})` : ""} icon={<IconShield size={16} />} />
        <StatCard label="Signals" value={frank ? `${frank.total_signals}` : "0"} icon={<IconBrain size={16} />} />
      </div>

      {/* ── Main Grid ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">

        {/* ── Frankenstein Brain ────────────────────────────────────────── */}
        <Card title="Frankenstein AI" glow={brainAlive && brainTrading && !brainPaused} action={
          <div className="flex items-center gap-1.5">
            <span className={`relative flex h-2 w-2`}>
              <span className={`relative inline-flex h-2 w-2 rounded-full ${brainDot}`} />
            </span>
            <span className={`text-xs font-semibold ${brainColor}`}>{brainLabel}</span>
          </div>
        }>
          {frank ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-3">
                <MiniStat label="Total P&L" value={snap ? pnlSign(snap.total_pnl) : "—"} color={snap ? pnlColor(snap.total_pnl) : undefined} />
                <MiniStat label="Daily P&L" value={pnl ? pnlSign(pnl.daily_pnl) : "—"} color={pnl ? pnlColor(pnl.daily_pnl) : undefined} />
                <MiniStat label="Sharpe" value={snap ? snap.sharpe_ratio.toFixed(2) : "—"} />
                <MiniStat label="Max Drawdown" value={snap ? `$${snap.max_drawdown.toFixed(2)}` : "—"} />
              </div>
              <div className="h-px bg-white/[0.06]" />
              <div className="space-y-1.5">
                <InfoRow label="Model" value={frank.version} mono />
                <InfoRow label="Generation" value={`Gen ${frank.generation}`} />
                <InfoRow label="Scans" value={`${frank.total_scans}`} />
                <InfoRow label="Uptime" value={frank.uptime_human} />
                <InfoRow label="Memory" value={`${mem?.total_recorded ?? 0} recorded · ${mem?.pending ?? 0} pending`} />
                {mem && mem.total_resolved > 0 && (
                  <InfoRow label="Memory Win Rate" value={`${mem.win_rate}%`} color={mem.win_rate >= 50 ? "text-accent" : "text-loss"} />
                )}
              </div>
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">
              Frankenstein not connected
            </div>
          )}
        </Card>

        {/* ── Open Positions ───────────────────────────────────────────── */}
        <Card title="Open Positions" action={<span className="text-xs text-[var(--text-muted)]">{positions.length} active</span>}>
          {positions.length > 0 ? (
            <div className="space-y-1.5 max-h-[320px] overflow-y-auto">
              {positions.map((p) => (
                <div key={p.ticker} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 hover:bg-white/[0.04] transition-colors">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {marketTitles[p.ticker] || prettifyTicker(p.ticker)}
                    </div>
                    <div className="text-[10px] text-[var(--text-muted)]">
                      {p.position > 0 ? "YES" : "NO"} × {Math.abs(p.position)}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0 ml-3">
                    {p.market_exposure_dollars && (
                      <div className="text-sm font-medium text-[var(--text-primary)] tabular-nums">${p.market_exposure_dollars}</div>
                    )}
                    {p.realized_pnl_dollars && (
                      <div className={`text-xs tabular-nums ${parseFloat(p.realized_pnl_dollars) >= 0 ? "text-accent" : "text-loss"}`}>
                        {parseFloat(p.realized_pnl_dollars) >= 0 ? "+" : ""}${p.realized_pnl_dollars}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">No open positions</div>
          )}
        </Card>

        {/* ── Recent Frankenstein Trades ────────────────────────────────── */}
        <Card title="Recent AI Trades" action={<span className="text-xs text-[var(--text-muted)]">{realTrades.length} real trades</span>}>
          {realTrades.length > 0 ? (
            <div className="space-y-1.5 max-h-[320px] overflow-y-auto">
              {realTrades.slice(0, 8).map((t, i) => (
                <div key={i} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5 hover:bg-white/[0.04] transition-colors">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className={`flex h-7 w-7 items-center justify-center rounded-lg flex-shrink-0 ${t.side === "yes" ? "bg-accent/10" : "bg-loss/10"}`}>
                      {t.side === "yes" ? <IconTrendUp size={14} className="text-accent" /> : <IconTrendDown size={14} className="text-loss" />}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-[var(--text-primary)] truncate">
                        {marketTitles[t.ticker] || prettifyTicker(t.ticker)}
                      </div>
                      <div className="text-[10px] text-[var(--text-muted)]">
                        {t.side?.toUpperCase()} × {t.count} @ {t.price_cents}¢ · {((t.confidence ?? 0) * 100).toFixed(0)}% conf
                      </div>
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0 ml-3">
                    <OutcomeBadge outcome={t.outcome} />
                    {(t.pnl_cents ?? 0) !== 0 && (
                      <div className={`text-[10px] font-bold tabular-nums mt-0.5 ${pnlColor(t.pnl_cents ?? 0)}`}>
                        {t.pnl_cents > 0 ? "+" : ""}{(t.pnl_cents / 100).toFixed(2)}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">
              {frank?.is_alive ? "Frankenstein is scanning — no trades yet" : "Start Frankenstein to begin trading"}
            </div>
          )}
        </Card>

        {/* ── Risk Monitor ─────────────────────────────────────────────── */}
        <Card title="Risk Monitor" action={
          risk?.kill_switch_active
            ? <span className="text-xs font-bold text-loss">⚠ KILL SWITCH</span>
            : <span className="text-xs text-accent font-medium">Normal</span>
        }>
          <div className="space-y-2">
            <RiskRow label="Kill Switch" value={risk?.kill_switch_active ? "ACTIVE" : "Inactive"} status={risk?.kill_switch_active ? "critical" : "ok"} />
            <RiskRow label="P&L" value={pnl ? pnlSign(pnl.daily_pnl) : "$0.00"} status={(pnl?.daily_pnl ?? 0) < -25 ? "critical" : (pnl?.daily_pnl ?? 0) < -10 ? "warning" : "ok"} />
            <RiskRow label="Exposure" value={`$${((balance?.total_exposure ?? 0) / 100).toFixed(2)}`} status={(balance?.total_exposure ?? 0) > 40000 ? "critical" : (balance?.total_exposure ?? 0) > 20000 ? "warning" : "ok"} />
            <RiskRow label="Positions" value={`${positions.length}`} status="ok" />
            <RiskRow label="Open Orders" value={String(balance?.open_orders ?? 0)} status="ok" />
            {snap && <RiskRow label="Max Drawdown" value={`$${snap.max_drawdown.toFixed(2)}`} status={snap.max_drawdown > 50 ? "critical" : snap.max_drawdown > 20 ? "warning" : "ok"} />}
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ── Small UI Components ──────────────────────────────────────────────────── */

function MiniStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3">
      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{label}</div>
      <div className={`text-base font-bold tabular-nums ${color ?? "text-[var(--text-primary)]"}`}>{value}</div>
    </div>
  );
}

function InfoRow({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className={`text-xs font-medium tabular-nums ${mono ? "font-mono" : ""} ${color ?? "text-[var(--text-primary)]"}`}>{value}</span>
    </div>
  );
}

function RiskRow({ label, value, status }: { label: string; value: string; status: "ok" | "warning" | "critical" }) {
  const colors = { ok: "text-accent", warning: "text-[var(--warning)]", critical: "text-loss" };
  return (
    <div className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5">
      <div className="flex items-center gap-2">
        <IconCircle size={6} className={colors[status]} />
        <span className="text-sm text-[var(--text-muted)]">{label}</span>
      </div>
      <span className="text-sm tabular-nums font-medium text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    pending: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    win: "bg-accent/10 text-accent border-accent/20",
    loss: "bg-loss/10 text-loss border-loss/20",
    breakeven: "bg-white/5 text-[var(--text-muted)] border-white/10",
  };
  return (
    <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles[outcome] ?? styles.pending}`}>
      {outcome}
    </span>
  );
}
