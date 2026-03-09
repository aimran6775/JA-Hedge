"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api, type Balance, type Fill, type Position } from "@/lib/api";

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

  const totalPnl = positions.reduce((s, p) => s + parseFloat(p.realized_pnl_dollars ?? "0"), 0);
  const balanceDollars = parseFloat(balance?.balance_dollars ?? "0");
  const totalExposure = balance?.total_exposure ?? 0;
  const totalValue = balanceDollars + totalExposure;

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
        <StatCard label="Available Cash" value={`$${balanceDollars.toFixed(2)}`} />
        <StatCard label="Exposure" value={`$${totalExposure.toFixed(2)}`} />
        <StatCard label="Realized P&L" value={`${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`} change={totalValue > 0 ? (totalPnl / totalValue) * 100 : 0} />
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
                  <th className="pb-2 pr-4 font-medium">Position</th>
                  <th className="pb-2 pr-4 font-medium">Exposure</th>
                  <th className="pb-2 pr-4 font-medium">Realized P&L</th>
                  <th className="pb-2 font-medium">Fees</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => {
                  const pnl = parseFloat(p.realized_pnl_dollars ?? "0");
                  return (
                    <tr key={i} className="border-b border-white/5 last:border-0">
                      <td className="py-3 pr-4">
                        <div className="text-sm font-medium text-white">{p.ticker}</div>
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                          p.position > 0 ? "bg-green-500/20 text-green-400" : p.position < 0 ? "bg-red-500/20 text-red-400" : "bg-white/10 text-[var(--muted)]"
                        }`}>
                          {p.position > 0 ? `YES ×${p.position}` : p.position < 0 ? `NO ×${Math.abs(p.position)}` : "FLAT"}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-sm text-[var(--muted)] tabular-nums">
                        {p.market_exposure_dollars ? `$${p.market_exposure_dollars}` : "—"}
                      </td>
                      <td className={`py-3 pr-4 text-sm font-medium tabular-nums ${pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                      </td>
                      <td className="py-3 text-sm text-[var(--muted)] tabular-nums">
                        {p.fees_paid_dollars ? `$${p.fees_paid_dollars}` : "—"}
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
