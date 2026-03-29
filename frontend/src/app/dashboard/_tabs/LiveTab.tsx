"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconCircle,
  IconRefresh,
  IconTrendUp,
  IconTrendDown,
  IconShield,
  IconZap,
  IconPortfolio,
  IconBrain,
  IconTarget,
} from "@/components/ui/Icons";
import {
  api,
  type Balance,
  type PnL,
  type RiskSnapshot,
  type Position,
  type FrankensteinStatus,
  type FrankensteinTrade,
} from "@/lib/api";

/* ── Helpers ──────────────────────────────────────────────────────────── */

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
  return base.replace(/\s+/g, " ").trim() || ticker;
}

function timeAgo(ts: string | null): string {
  if (!ts) return "--";
  const m = Math.round((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.round(m / 60)}h`;
  return `${Math.round(m / 1440)}d`;
}

/* ═══════════════════════════════════════════════════════════════════════
   LIVE TAB — What's happening right now
   ═══════════════════════════════════════════════════════════════════════ */
export function LiveTab() {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [pnl, setPnl] = useState<PnL | null>(null);
  const [risk, setRisk] = useState<RiskSnapshot | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [frank, setFrank] = useState<FrankensteinStatus | null>(null);
  const [trades, setTrades] = useState<FrankensteinTrade[]>([]);
  const [fills, setFills] = useState<
    Array<{
      ticker: string;
      side: string;
      action: string;
      count: number | null;
      price_dollars: string | null;
      fee_dollars: string | null;
      created_time: string | null;
    }>
  >([]);
  const [marketTitles, setMarketTitles] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const titleCache = useRef<Record<string, string>>({});

  const fetchAll = useCallback(async () => {
    try {
      const [b, p, r, pos, fs, ft, fl] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.pnl().catch(() => null),
        api.risk.snapshot().catch(() => null),
        api.portfolio.positions().catch(() => []),
        api.frankenstein.status().catch(() => null),
        api.frankenstein.recentTrades(20).catch(() => []),
        api.portfolio.fills({ limit: 15 }).catch(() => []),
      ]);
      setBalance(b);
      setPnl(p);
      setRisk(r);
      setPositions(pos);
      if (fs) setFrank(fs);
      setTrades(ft);
      setFills(fl);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 8000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // Resolve market titles
  useEffect(() => {
    const allTickers = [
      ...positions.map((p) => p.ticker),
      ...trades.map((t) => t.ticker),
      ...fills.map((f) => f.ticker),
    ];
    const unknown = [...new Set(allTickers)].filter(
      (tk) => !titleCache.current[tk],
    );
    if (unknown.length === 0) return;
    let cancelled = false;
    (async () => {
      const resolved: Record<string, string> = {};
      await Promise.all(
        unknown.map(async (tk) => {
          try {
            const m = await api.markets.get(tk);
            if (m?.title) resolved[tk] = m.title;
          } catch {
            /* stays as ticker */
          }
        }),
      );
      if (!cancelled && Object.keys(resolved).length > 0) {
        titleCache.current = { ...titleCache.current, ...resolved };
        setMarketTitles((prev) => ({ ...prev, ...resolved }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [positions, trades, fills]);

  /* ── Derived ────────────────────────────────────────────────────────── */
  const snap = frank?.performance?.snapshot;
  const mem = frank?.memory;
  const realTrades = trades.filter(
    (t) => !t.model_version?.startsWith("bootstrap"),
  );
  const brainAlive = frank?.is_alive ?? false;
  const brainTrading = frank?.is_trading ?? false;
  const brainPaused = frank?.is_paused ?? false;

  const brainLabel = !brainAlive
    ? "Offline"
    : brainPaused
      ? "Paused"
      : brainTrading
        ? "Trading"
        : "Idle";
  const brainColor = !brainAlive
    ? "text-[var(--text-muted)]"
    : brainPaused
      ? "text-[var(--warning)]"
      : brainTrading
        ? "text-accent"
        : "text-blue-400";
  const dotColor = !brainAlive
    ? "bg-[var(--text-muted)]"
    : brainPaused
      ? "bg-[var(--warning)]"
      : brainTrading
        ? "bg-accent"
        : "bg-blue-400";

  const title = (tk: string) => marketTitles[tk] || prettifyTicker(tk);

  /* ── Risk bar helper ────────────────────────────────────────────────── */
  function RiskBar({
    label,
    current,
    max,
    unit,
  }: {
    label: string;
    current: number;
    max: number;
    unit?: string;
  }) {
    const pct = max > 0 ? Math.min((current / max) * 100, 100) : 0;
    const color =
      pct > 80 ? "bg-[var(--danger)]" : pct > 50 ? "bg-[var(--warning)]" : "bg-accent";
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-[var(--text-muted)]">{label}</span>
          <span className="tabular-nums text-[var(--text-secondary)]">
            {unit === "$" ? `$${current.toFixed(0)}` : current}
            {" / "}
            {unit === "$" ? `$${max.toFixed(0)}` : max}
          </span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-white/[0.06]">
          <div
            className={`h-1.5 rounded-full transition-all ${color}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 animate-fade-in">
      {/* ── Header row ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg glass px-3 py-1.5 text-xs">
            <span className="relative flex h-2 w-2">
              {brainAlive && brainTrading && !brainPaused && (
                <span
                  className={`absolute inline-flex h-full w-full animate-ping rounded-full ${dotColor} opacity-50`}
                />
              )}
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${dotColor}`}
              />
            </span>
            <span className={`font-semibold uppercase tracking-wide ${brainColor}`}>
              {brainLabel}
            </span>
            {frank && (
              <span className="text-[var(--text-muted)]">
                / Gen {frank.generation} / {frank.total_scans} scans
              </span>
            )}
          </div>
        </div>
        <button
          onClick={fetchAll}
          className="rounded-lg glass p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
        >
          <IconRefresh size={14} />
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 p-3 text-sm text-[var(--danger)]">
          {error}
        </div>
      )}

      {/* ── Stat cards ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard
          label="Balance"
          value={balance ? `$${balance.balance_dollars}` : "--"}
          icon={<IconPortfolio size={16} />}
        />
        <StatCard
          label="P&L"
          value={pnl ? pnlSign(pnl.daily_pnl) : "--"}
          change={pnl?.daily_pnl ?? undefined}
          icon={<IconTrendUp size={16} />}
        />
        <StatCard
          label="Positions"
          value={`${positions.length}`}
          suffix=" open"
          icon={<IconTarget size={16} />}
        />
        <StatCard
          label="Trades"
          value={frank ? `${frank.total_trades_executed}` : "--"}
          suffix={
            frank ? ` / ${frank.total_trades_rejected} rej` : ""
          }
          icon={<IconZap size={16} />}
        />
        <StatCard
          label="Win Rate"
          value={
            snap && snap.real_trades > 0
              ? `${(snap.win_rate * 100).toFixed(0)}%`
              : "--"
          }
          suffix={snap ? ` (${snap.real_trades})` : ""}
          icon={<IconShield size={16} />}
        />
        <StatCard
          label="Sharpe"
          value={snap ? snap.sharpe_ratio.toFixed(2) : "--"}
          icon={<IconBrain size={16} />}
        />
      </div>

      {/* ── Main grid ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Brain status */}
        <Card
          title="Brain"
          glow={brainAlive && brainTrading && !brainPaused}
          action={
            <span className={`text-xs font-medium ${brainColor}`}>
              {brainLabel}
            </span>
          }
        >
          {frank ? (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <MiniStat
                  label="Total P&L"
                  value={snap ? pnlSign(snap.total_pnl) : "--"}
                  color={snap ? pnlColor(snap.total_pnl) : undefined}
                />
                <MiniStat
                  label="Daily P&L"
                  value={pnl ? pnlSign(pnl.daily_pnl) : "--"}
                  color={pnl ? pnlColor(pnl.daily_pnl) : undefined}
                />
                <MiniStat label="Drawdown" value={snap ? `$${snap.max_drawdown.toFixed(2)}` : "--"} />
                <MiniStat label="Profit Factor" value={snap ? snap.profit_factor.toFixed(2) : "--"} />
              </div>
              <div className="h-px bg-white/[0.06]" />
              <div className="space-y-1">
                <InfoRow label="Model" value={frank.version} mono />
                <InfoRow label="Uptime" value={frank.uptime_human} />
                <InfoRow
                  label="Memory"
                  value={`${mem?.total_recorded ?? 0} trades / ${mem?.pending ?? 0} pending`}
                />
                {mem && mem.total_resolved > 0 && (
                  <InfoRow
                    label="Memory Win Rate"
                    value={`${mem.win_rate}%`}
                    color={
                      mem.win_rate >= 50 ? "text-accent" : "text-[var(--danger)]"
                    }
                  />
                )}
                <InfoRow
                  label="Last Scan"
                  value={
                    frank.last_scan_debug
                      ? `${frank.last_scan_debug.candidates ?? 0} candidates, ${frank.last_scan_debug.exec_successes ?? 0} executed`
                      : "--"
                  }
                />
              </div>
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-[var(--text-muted)]">
              Not connected
            </div>
          )}
        </Card>

        {/* Open Positions */}
        <Card
          title="Open Positions"
          action={
            <span className="text-xs text-[var(--text-muted)]">
              {positions.length} active
            </span>
          }
        >
          {positions.length > 0 ? (
            <div className="space-y-1.5 max-h-[280px] overflow-y-auto">
              {positions.map((p) => (
                <div
                  key={p.ticker}
                  className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2.5 hover:bg-white/[0.04] transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-[var(--text-primary)] truncate">
                      {title(p.ticker)}
                    </div>
                    <div className="text-[10px] text-[var(--text-muted)]">
                      {p.position > 0 ? "YES" : "NO"} x{Math.abs(p.position)}
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0 ml-3">
                    {p.market_exposure_dollars && (
                      <div className="text-sm tabular-nums text-[var(--text-primary)]">
                        ${p.market_exposure_dollars}
                      </div>
                    )}
                    {p.realized_pnl_dollars && (
                      <div
                        className={`text-xs tabular-nums ${parseFloat(p.realized_pnl_dollars) >= 0 ? "text-accent" : "text-[var(--danger)]"}`}
                      >
                        {parseFloat(p.realized_pnl_dollars) >= 0 ? "+" : ""}$
                        {p.realized_pnl_dollars}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-[var(--text-muted)]">
              No open positions
            </div>
          )}
        </Card>

        {/* Recent Trades */}
        <Card
          title="Recent Trades"
          action={
            <span className="text-xs text-[var(--text-muted)]">
              {realTrades.length} real
            </span>
          }
        >
          {realTrades.length > 0 ? (
            <div className="space-y-1.5 max-h-[280px] overflow-y-auto">
              {realTrades.slice(0, 10).map((t, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2 hover:bg-white/[0.04] transition-colors"
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <div
                      className={`flex h-6 w-6 items-center justify-center rounded flex-shrink-0 ${t.side === "yes" ? "bg-accent/10" : "bg-[var(--danger)]/10"}`}
                    >
                      {t.side === "yes" ? (
                        <IconTrendUp size={12} className="text-accent" />
                      ) : (
                        <IconTrendDown
                          size={12}
                          className="text-[var(--danger)]"
                        />
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-[var(--text-primary)] truncate">
                        {title(t.ticker)}
                      </div>
                      <div className="text-[10px] text-[var(--text-muted)]">
                        {t.side?.toUpperCase()} x{t.count} @ {t.price_cents}c
                        / {((t.confidence ?? 0) * 100).toFixed(0)}% conf
                      </div>
                    </div>
                  </div>
                  <div className="text-right flex-shrink-0 ml-2">
                    <OutcomeBadge outcome={t.outcome} />
                    {(t.pnl_cents ?? 0) !== 0 && (
                      <div
                        className={`text-[10px] font-medium tabular-nums mt-0.5 ${pnlColor(t.pnl_cents ?? 0)}`}
                      >
                        {t.pnl_cents > 0 ? "+" : ""}
                        {(t.pnl_cents / 100).toFixed(2)}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-32 items-center justify-center text-sm text-[var(--text-muted)]">
              {frank?.is_alive
                ? "Scanning -- no trades yet"
                : "Start brain to begin trading"}
            </div>
          )}
        </Card>

        {/* Risk Monitor */}
        <Card
          title="Risk"
          action={
            risk?.kill_switch_active ? (
              <span className="text-xs font-semibold text-[var(--danger)]">
                KILL SWITCH ON
              </span>
            ) : (
              <span className="text-xs text-accent font-medium">Normal</span>
            )
          }
        >
          <div className="space-y-3">
            <RiskBar
              label="Positions"
              current={positions.length}
              max={frank?.strategy?.current_params?.max_simultaneous_positions ?? 10}
            />
            <RiskBar
              label="Exposure"
              current={(balance?.total_exposure ?? 0) / 100}
              max={500}
              unit="$"
            />
            <RiskBar
              label="Daily Loss"
              current={Math.abs(Math.min(pnl?.daily_pnl ?? 0, 0))}
              max={frank?.strategy?.current_params?.max_daily_loss ?? 50}
              unit="$"
            />
            <RiskBar
              label="Drawdown"
              current={snap?.max_drawdown ?? 0}
              max={50}
              unit="$"
            />
            <div className="h-px bg-white/[0.06]" />
            <div className="flex items-center justify-between text-xs">
              <span className="text-[var(--text-muted)]">Kill Switch</span>
              <span
                className={
                  risk?.kill_switch_active
                    ? "text-[var(--danger)] font-medium"
                    : "text-accent"
                }
              >
                {risk?.kill_switch_active ? "Active" : "Off"}
              </span>
            </div>
          </div>
        </Card>
      </div>

      {/* ── Exchange Fills ────────────────────────────────────────────── */}
      <Card
        title="Exchange Fills"
        action={
          <span className="text-xs text-[var(--text-muted)]">
            {fills.length} recent
          </span>
        }
      >
        {fills.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                  <th className="pb-2 pr-4 font-medium">Market</th>
                  <th className="pb-2 pr-4 font-medium">Side</th>
                  <th className="pb-2 pr-4 font-medium">Action</th>
                  <th className="pb-2 pr-4 text-right font-medium">Qty</th>
                  <th className="pb-2 pr-4 text-right font-medium">Price</th>
                  <th className="pb-2 text-right font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {fills.map((f, i) => (
                  <tr
                    key={i}
                    className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="py-2 pr-4 text-xs font-medium text-[var(--text-primary)] truncate max-w-[200px]">
                      {title(f.ticker)}
                    </td>
                    <td className="py-2 pr-4">
                      <span
                        className={`inline-flex rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                          f.side === "yes"
                            ? "bg-accent/10 text-accent"
                            : "bg-[var(--danger)]/10 text-[var(--danger)]"
                        }`}
                      >
                        {f.side}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-xs text-[var(--text-muted)]">
                      {f.action}
                    </td>
                    <td className="py-2 pr-4 text-right text-xs tabular-nums text-[var(--text-primary)]">
                      {f.count ?? "--"}
                    </td>
                    <td className="py-2 pr-4 text-right text-xs tabular-nums text-[var(--text-primary)]">
                      {f.price_dollars ? `$${f.price_dollars}` : "--"}
                    </td>
                    <td className="py-2 text-right text-xs tabular-nums text-[var(--text-muted)]">
                      {timeAgo(f.created_time)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-6 text-center text-sm text-[var(--text-muted)]">
            No recent fills
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── Small components ─────────────────────────────────────────────────── */

function MiniStat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-2.5">
      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
        {label}
      </div>
      <div
        className={`text-sm font-semibold tabular-nums ${color ?? "text-[var(--text-primary)]"}`}
      >
        {value}
      </div>
    </div>
  );
}

function InfoRow({
  label,
  value,
  mono,
  color,
}: {
  label: string;
  value: string;
  mono?: boolean;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span
        className={`text-xs font-medium tabular-nums ${mono ? "font-mono" : ""} ${color ?? "text-[var(--text-primary)]"}`}
      >
        {value}
      </span>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    pending: "bg-[var(--info)]/10 text-[var(--info)] border-[var(--info)]/20",
    win: "bg-accent/10 text-accent border-accent/20",
    loss: "bg-[var(--danger)]/10 text-[var(--danger)] border-[var(--danger)]/20",
    breakeven: "bg-white/5 text-[var(--text-muted)] border-white/10",
  };
  return (
    <span
      className={`inline-flex rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${styles[outcome] ?? styles.pending}`}
    >
      {outcome}
    </span>
  );
}
