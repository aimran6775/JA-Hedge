"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconPortfolio, IconTrendUp, IconTrendDown, IconTarget, IconZap, IconRefresh } from "@/components/ui/Icons";
import { api, type Balance, type Position, type Fill, type PnL } from "@/lib/api";

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

export default function PortfolioPage() {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [pnl, setPnl] = useState<PnL | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [marketTitles, setMarketTitles] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<"positions" | "history">("positions");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [bRes, pRes, fRes, pnlRes] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.positions().catch(() => []),
        api.portfolio.fills({ limit: 50 }).catch(() => []),
        api.portfolio.pnl().catch(() => null),
      ]);
      setBalance(bRes);
      setPositions(pRes);
      setFills(fRes);
      setPnl(pnlRes);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [load]);

  // Resolve market titles
  useEffect(() => {
    const allTickers = [...positions.map(p => p.ticker), ...fills.map(f => f.ticker)];
    const unknown = [...new Set(allTickers)].filter(tk => tk && !marketTitles[tk]);
    if (unknown.length === 0) return;
    let cancelled = false;
    (async () => {
      const resolved: Record<string, string> = {};
      await Promise.all(unknown.map(async (tk) => {
        try { const m = await api.markets.get(tk); if (m?.title) resolved[tk] = m.title; } catch { /* ignore */ }
      }));
      if (!cancelled && Object.keys(resolved).length > 0) setMarketTitles(prev => ({ ...prev, ...resolved }));
    })();
    return () => { cancelled = true; };
  }, [positions, fills, marketTitles]);

  const totalExposure = balance?.total_exposure ?? 0;
  const dailyPnl = pnl?.daily_pnl ?? 0;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Portfolio</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Live positions, balance, P&amp;L, and trade history</p>
        </div>
        <button onClick={load} disabled={loading}
          className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all flex items-center gap-2">
          <IconRefresh size={14} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label="Balance" value={balance ? `$${balance.balance_dollars}` : "\u2014"} icon={<IconPortfolio size={18} />} />
        <StatCard label="Daily P&L" value={pnlSign(dailyPnl)} change={dailyPnl} icon={dailyPnl >= 0 ? <IconTrendUp size={18} /> : <IconTrendDown size={18} />} />
        <StatCard label="Positions" value={String(balance?.position_count ?? positions.length)} icon={<IconTarget size={18} />} />
        <StatCard label="Exposure" value={`$${(totalExposure / 100).toFixed(2)}`} icon={<IconTrendUp size={18} />} />
        <StatCard label="Open Orders" value={String(balance?.open_orders ?? 0)} icon={<IconZap size={18} />} />
      </div>

      {pnl && (
        <Card title="Daily Summary">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Daily P&amp;L</div>
              <div className={`text-lg font-bold tabular-nums ${pnlColor(pnl.daily_pnl)}`}>{pnlSign(pnl.daily_pnl)}</div>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Trades Today</div>
              <div className="text-lg font-bold tabular-nums text-[var(--text-primary)]">{pnl.daily_trades}</div>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Fees Today</div>
              <div className="text-lg font-bold tabular-nums text-[var(--text-muted)]">${pnl.daily_fees.toFixed(2)}</div>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
              <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Total Exposure</div>
              <div className="text-lg font-bold tabular-nums text-[var(--text-primary)]">${pnl.total_exposure.toFixed(2)}</div>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <div className="flex items-center gap-2 mb-5">
          {(["positions", "history"] as const).map((t) => (
            <button key={t} onClick={() => setActiveTab(t)}
              className={`rounded-xl px-4 py-2 text-xs font-semibold uppercase tracking-wider transition-all ${
                activeTab === t ? "bg-accent/10 text-accent border border-accent/20" : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"
              }`}>{t}</button>
          ))}
        </div>

        {activeTab === "positions" && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  {["Market", "Side", "Qty", "Exposure", "Realized PnL", "Fees"].map(h => (
                    <th key={h} className="pb-3 text-left text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.length === 0 ? (
                  <tr><td colSpan={6} className="py-10 text-center text-[var(--text-muted)]">No open positions</td></tr>
                ) : (
                  positions.map((p, i) => (
                    <tr key={i} className="group border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 pr-4">
                        <div className="text-sm font-medium text-[var(--text-primary)] group-hover:text-accent transition-colors">
                          {marketTitles[p.ticker] || prettifyTicker(p.ticker)}
                        </div>
                        <div className="text-[10px] text-[var(--text-muted)] font-mono">{p.ticker}</div>
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                          p.position > 0 ? "bg-accent/10 text-accent" : "bg-loss/10 text-loss"
                        }`}>{p.position > 0 ? "YES" : "NO"}</span>
                      </td>
                      <td className="py-3 pr-4 text-[var(--text-primary)] tabular-nums font-mono">{Math.abs(p.position)}</td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)] tabular-nums font-mono">{p.market_exposure_dollars ? `$${p.market_exposure_dollars}` : "\u2014"}</td>
                      <td className={`py-3 pr-4 tabular-nums font-mono font-medium ${pnlColor(parseFloat(p.realized_pnl_dollars ?? "0"))}`}>
                        {p.realized_pnl_dollars ? pnlSign(parseFloat(p.realized_pnl_dollars)) : "\u2014"}
                      </td>
                      <td className="py-3 text-[var(--text-muted)] tabular-nums font-mono">{p.fees_paid_dollars ? `$${p.fees_paid_dollars}` : "\u2014"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {activeTab === "history" && (
          <div className="space-y-1.5">
            {fills.length === 0 ? (
              <div className="py-10 text-center text-[var(--text-muted)]">No trade history</div>
            ) : (
              fills.map((f, i) => (
                <div key={i} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 transition-colors hover:bg-white/[0.04]">
                  <div className="flex items-center gap-3">
                    {f.action === "buy" ? <IconTrendUp size={14} className="text-accent" /> : <IconTrendDown size={14} className="text-loss" />}
                    <div>
                      <div className="text-sm text-[var(--text-primary)] font-medium">{marketTitles[f.ticker] || prettifyTicker(f.ticker)}</div>
                      <div className="text-[10px] text-[var(--text-muted)] font-mono">{f.ticker}</div>
                      <div className="text-xs text-[var(--text-muted)]">
                        <span className={f.action === "buy" ? "text-accent" : "text-loss"}>{f.action?.toUpperCase()}</span>
                        {" "}{f.side?.toUpperCase()} x {f.count ?? "?"}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-[var(--text-primary)] tabular-nums font-mono">{f.price_dollars ? `$${f.price_dollars}` : "mkt"}</div>
                    {f.fee_dollars && <div className="text-[10px] text-[var(--text-muted)]">Fee: ${f.fee_dollars}</div>}
                    <div className="text-xs text-[var(--text-muted)]">{f.created_time ? new Date(f.created_time).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
