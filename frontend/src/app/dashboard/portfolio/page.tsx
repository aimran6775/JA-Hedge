"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconPortfolio, IconTrendUp, IconTrendDown, IconCircle, IconTarget, IconZap } from "@/components/ui/Icons";
import { api, type Balance, type Position, type Fill } from "@/lib/api";
import { pnlColor } from "@/lib/utils";

export default function PortfolioPage() {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [activeTab, setActiveTab] = useState<"positions" | "history">("positions");

  useEffect(() => {
    const load = async () => {
      const [bRes, pRes, fRes] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.positions().catch(() => []),
        api.portfolio.fills({ limit: 50 }).catch(() => []),
      ]);
      setBalance(bRes);
      setPositions(pRes);
      setFills(fRes);
    };
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, []);

  const totalPnl = positions.reduce((s, p) => s + (p.market_exposure ?? 0), 0);
  const pnlPercent = balance?.balance_cents && balance.balance_cents > 0 ? ((totalPnl / balance.balance_cents) * 100) : 0;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Portfolio</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">Live positions, balance, and trade history</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Balance" value={balance ? `$${balance.balance_dollars.toFixed(2)}` : "—"} icon={<IconPortfolio size={18} />} />
        <StatCard label="Available" value={balance ? `$${balance.available_dollars.toFixed(2)}` : "—"} icon={<IconTarget size={18} />} />
        <StatCard label="Exposure" value={`$${(totalPnl / 100).toFixed(2)}`} trend={totalPnl >= 0 ? "up" : "down"} icon={<IconTrendUp size={18} />} />
        <StatCard label="P&L %" value={`${pnlPercent >= 0 ? "+" : ""}${pnlPercent.toFixed(2)}%`} trend={pnlPercent >= 0 ? "up" : "down"} icon={<IconZap size={18} />} />
      </div>

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
                  {["Market", "Side", "Qty", "Avg Cost", "Mkt Value", "Exposure"].map(h => (
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
                        <span className="text-[var(--text-primary)] group-hover:text-accent transition-colors font-medium">{p.ticker}</span>
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                          p.side === "yes" ? "bg-accent/10 text-accent" : "bg-loss/10 text-loss"
                        }`}>
                          <IconCircle size={5} className={p.side === "yes" ? "text-accent" : "text-loss"} />
                          {p.side?.toUpperCase() ?? "—"}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-[var(--text-primary)] tabular-nums font-mono">{p.quantity ?? "—"}</td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)] tabular-nums font-mono">{p.avg_price_cents != null ? `${p.avg_price_cents}¢` : "—"}</td>
                      <td className="py-3 pr-4 text-[var(--text-secondary)] tabular-nums font-mono">{p.market_value_cents != null ? `${p.market_value_cents}¢` : "—"}</td>
                      <td className={`py-3 tabular-nums font-mono font-medium ${pnlColor(p.market_exposure ?? 0)}`}>
                        {p.market_exposure != null ? `$${(p.market_exposure / 100).toFixed(2)}` : "—"}
                      </td>
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
                      <div className="text-sm text-[var(--text-primary)] font-medium">{f.ticker}</div>
                      <div className="text-xs text-[var(--text-muted)]">{f.action.toUpperCase()} {f.side?.toUpperCase()} x{f.count ?? "?"}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-[var(--text-primary)] tabular-nums font-mono">{f.price_dollars ? `$${f.price_dollars}` : "mkt"}</div>
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
