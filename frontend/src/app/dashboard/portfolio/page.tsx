"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api, type Balance, type Fill } from "@/lib/api";

interface Position {
  ticker: string;
  market_title?: string;
  side: string;
  quantity: number;
  avg_price_dollars?: number;
  market_price_dollars?: number;
  pnl_dollars?: number;
}

export default function PortfolioPage() {
  const [balance, setBalance] = useState<Balance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      const [bRes, pRes, fRes] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.positions().catch(() => []),
        api.portfolio.fills({ limit: 30 }).catch(() => []),
      ]);
      setBalance(bRes);
      setPositions(Array.isArray(pRes) ? pRes : []);
      setFills(fRes);
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  const totalInvested = positions.reduce((s, p) => s + ((p.avg_price_dollars ?? 0) * (p.quantity ?? 0)), 0);
  const totalPnl = positions.reduce((s, p) => s + (p.pnl_dollars ?? 0), 0);
  const totalValue = (balance?.balance_dollars ?? 0) + totalInvested;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Portfolio</h1>
        <span className="text-xs text-[var(--muted)]">
          {loading ? "Loading..." : `${positions.length} positions • ${fills.length} fills`}
        </span>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total Value" value={`$${totalValue.toFixed(2)}`} />
        <StatCard label="Available Cash" value={`$${balance?.balance_dollars?.toFixed(2) ?? "—"}`} />
        <StatCard label="Invested" value={`$${totalInvested.toFixed(2)}`} />
        <StatCard label="Total P&L" value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`} change={totalValue > 0 ? (totalPnl / totalValue) * 100 : 0} />
      </div>

      {/* Positions Table */}
      <Card title="Open Positions" action={<span className="text-xs text-[var(--muted)]">{positions.length} positions</span>}>
        <div className="overflow-x-auto">
          {positions.length === 0 ? (
            <div className="py-12 text-center text-sm text-[var(--muted)]">
              No open positions — go to Trading to place your first order!
            </div>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/10 text-xs text-[var(--muted)]">
                  <th className="pb-2 pr-4 font-medium">Market</th>
                  <th className="pb-2 pr-4 font-medium">Side</th>
                  <th className="pb-2 pr-4 font-medium">Qty</th>
                  <th className="pb-2 pr-4 font-medium">Avg Entry</th>
                  <th className="pb-2 pr-4 font-medium">Market Price</th>
                  <th className="pb-2 font-medium">P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => {
                  const pnl = p.pnl_dollars ?? 0;
                  return (
                    <tr key={i} className="border-b border-white/5 last:border-0">
                      <td className="py-3 pr-4">
                        <div className="text-sm font-medium text-white">{p.ticker}</div>
                        {p.market_title && (
                          <div className="text-xs text-[var(--muted)] line-clamp-1">{p.market_title}</div>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                          p.side === "yes" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                        }`}>
                          {(p.side || "—").toUpperCase()}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-sm text-white tabular-nums">{p.quantity}</td>
                      <td className="py-3 pr-4 text-sm text-[var(--muted)] tabular-nums">
                        {p.avg_price_dollars != null ? `$${p.avg_price_dollars.toFixed(2)}` : "—"}
                      </td>
                      <td className="py-3 pr-4 text-sm text-white tabular-nums">
                        {p.market_price_dollars != null ? `$${p.market_price_dollars.toFixed(2)}` : "—"}
                      </td>
                      <td className={`py-3 text-sm font-medium tabular-nums ${pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* Trade History (Fills) */}
      <Card title="Trade History" action={<span className="text-xs text-[var(--muted)]">{fills.length} fills</span>}>
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {fills.length === 0 ? (
            <div className="py-8 text-center text-sm text-[var(--muted)]">
              No trades yet
            </div>
          ) : (
            fills.map((f, i) => (
              <div key={i} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-[var(--muted)]">
                    {f.created_time ? new Date(f.created_time).toLocaleString() : "—"}
                  </span>
                  <span className={`font-medium ${f.action === "buy" ? "text-green-400" : "text-red-400"}`}>
                    {(f.action || "—").toUpperCase()}
                  </span>
                  <span className="text-white">{f.ticker}</span>
                  <span className={`text-xs ${f.side === "yes" ? "text-green-400" : "text-red-400"}`}>
                    {(f.side || "—").toUpperCase()}
                  </span>
                </div>
                <div className="text-[var(--muted)] tabular-nums">
                  {f.count ?? "?"} @ {f.price_dollars ? `$${f.price_dollars}` : "mkt"}
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
