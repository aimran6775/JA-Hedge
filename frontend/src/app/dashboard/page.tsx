"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api, type Balance, type PnL, type RiskSnapshot, type StrategyStatus, type HealthStatus, type Position } from "@/lib/api";

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [pnl, setPnl] = useState<PnL | null>(null);
  const [risk, setRisk] = useState<RiskSnapshot | null>(null);
  const [strategy, setStrategy] = useState<StrategyStatus | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = async () => {
    try {
      const [h, b, p, r, s, pos] = await Promise.all([
        api.health().catch(() => null),
        api.portfolio.balance().catch(() => null),
        api.portfolio.pnl().catch(() => null),
        api.risk.snapshot().catch(() => null),
        api.strategy.status().catch(() => null),
        api.portfolio.positions().catch(() => []),
      ]);
      setHealth(h);
      setBalance(b);
      setPnl(p);
      setRisk(r);
      setStrategy(s);
      setPositions(pos);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Connection failed");
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <div className="flex items-center gap-3">
          {health ? (
            <div className="flex items-center gap-2 text-xs">
              <span className="h-2 w-2 rounded-full bg-green-500" />
              <span className="text-green-400">
                {health.mode.toUpperCase()} • {health.has_api_keys ? "API Connected" : "No Keys"}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-red-400">Backend Offline</span>
            </div>
          )}
          <button onClick={fetchAll} className="rounded-md bg-white/5 px-3 py-1.5 text-xs text-[var(--muted)] hover:bg-white/10 transition-colors">
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Key Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Balance"
          value={balance ? `$${balance.balance_dollars}` : "—"}
        />
        <StatCard
          label="Daily P&L"
          value={pnl ? `$${pnl.daily_pnl.toFixed(2)}` : "—"}
          change={pnl?.daily_pnl ?? 0}
        />
        <StatCard
          label="Positions"
          value={positions.length}
        />
        <StatCard
          label="AI Signals"
          value={strategy ? `${strategy.total_signals}` : "0"}
          suffix=" today"
        />
      </div>

      {/* Panels */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Open Positions" action={<span className="text-xs text-[var(--muted)]">{positions.length} active</span>}>
          {positions.length > 0 ? (
            <div className="space-y-2">
              {positions.map((p) => (
                <div key={p.ticker} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2.5">
                  <div>
                    <div className="text-sm font-medium text-white">{p.ticker}</div>
                    <div className="text-xs text-[var(--muted)]">
                      {p.position > 0 ? "YES" : "NO"} × {Math.abs(p.position)}
                    </div>
                  </div>
                  <div className="text-right">
                    {p.market_exposure_dollars && (
                      <div className="text-sm text-white tabular-nums">${p.market_exposure_dollars}</div>
                    )}
                    {p.realized_pnl_dollars && (
                      <div className={`text-xs tabular-nums ${parseFloat(p.realized_pnl_dollars) >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {parseFloat(p.realized_pnl_dollars) >= 0 ? "+" : ""}${p.realized_pnl_dollars}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-[var(--muted)]">
              No open positions — go to Trading to place orders
            </div>
          )}
        </Card>

        <Card title="System Components" action={
          health ? <span className="text-xs text-green-400">All Systems Go</span>
                 : <span className="text-xs text-yellow-400">Connecting...</span>
        }>
          <div className="space-y-2">
            {health ? Object.entries(health.components).map(([name, status]) => (
              <div key={name} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2">
                <span className="text-sm text-white capitalize">{name.replace(/_/g, " ")}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--muted)]">{status}</span>
                  <span className={`h-2 w-2 rounded-full ${status === "ready" || status === "connected" ? "bg-green-500" : "bg-yellow-500"}`} />
                </div>
              </div>
            )) : (
              <div className="flex h-48 items-center justify-center text-sm text-[var(--muted)]">
                Waiting for backend connection...
              </div>
            )}
          </div>
        </Card>

        <Card title="AI Strategy" action={
          strategy?.running
            ? <span className="text-xs text-green-400">● Running</span>
            : <span className="text-xs text-yellow-400">● Idle</span>
        }>
          {strategy ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md bg-white/5 p-3">
                  <div className="text-xs text-[var(--muted)]">Signals</div>
                  <div className="text-lg font-bold text-white tabular-nums">{strategy.total_signals}</div>
                </div>
                <div className="rounded-md bg-white/5 p-3">
                  <div className="text-xs text-[var(--muted)]">Executed</div>
                  <div className="text-lg font-bold text-green-400 tabular-nums">{strategy.signals_executed}</div>
                </div>
                <div className="rounded-md bg-white/5 p-3">
                  <div className="text-xs text-[var(--muted)]">Filtered</div>
                  <div className="text-lg font-bold text-yellow-400 tabular-nums">{strategy.signals_filtered}</div>
                </div>
                <div className="rounded-md bg-white/5 p-3">
                  <div className="text-xs text-[var(--muted)]">Risk Rejected</div>
                  <div className="text-lg font-bold text-red-400 tabular-nums">{strategy.signals_risk_rejected}</div>
                </div>
              </div>
              <div className="rounded-md bg-white/5 p-3">
                <div className="flex justify-between text-xs text-[var(--muted)]">
                  <span>Model: {strategy.model_name}</span>
                  <span>Avg Confidence: {(strategy.avg_confidence * 100).toFixed(0)}%</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-[var(--muted)]">
              AI engine initializing...
            </div>
          )}
        </Card>

        <Card title="Risk Monitor">
          <div className="space-y-3">
            <RiskRow label="Kill Switch" value={risk?.kill_switch_active ? "ACTIVE" : "Inactive"} status={risk?.kill_switch_active ? "critical" : "ok"} />
            <RiskRow label="Daily P&L" value={`$${(risk?.daily_pnl ?? 0).toFixed(2)}`} status={
              (risk?.daily_pnl ?? 0) < -25 ? "critical" : (risk?.daily_pnl ?? 0) < -10 ? "warning" : "ok"
            } />
            <RiskRow label="Exposure" value={`$${(risk?.total_exposure ?? 0).toFixed(2)}`} status={
              (risk?.total_exposure ?? 0) > 400 ? "critical" : (risk?.total_exposure ?? 0) > 200 ? "warning" : "ok"
            } />
            <RiskRow label="Positions" value={String(risk?.position_count ?? 0)} status="ok" />
            <RiskRow label="Open Orders" value={String(risk?.open_orders ?? 0)} status="ok" />
          </div>
        </Card>
      </div>
    </div>
  );
}

function RiskRow({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status: "ok" | "warning" | "critical";
}) {
  const colors = {
    ok: "bg-green-500",
    warning: "bg-yellow-500",
    critical: "bg-red-500",
  };
  return (
    <div className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${colors[status]}`} />
        <span className="text-sm text-[var(--muted)]">{label}</span>
      </div>
      <span className="text-sm tabular-nums text-white">{value}</span>
    </div>
  );
}
