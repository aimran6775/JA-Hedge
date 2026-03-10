"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconCircle, IconRefresh, IconTrendUp, IconShield, IconZap, IconPortfolio } from "@/components/ui/Icons";
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
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Overview</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Real-time trading intelligence</p>
        </div>
        <div className="flex items-center gap-3">
          {health ? (
            <div className="flex items-center gap-2 rounded-lg glass px-3 py-1.5 text-xs">
              <IconCircle size={6} className={health.paper_trading?.enabled ? "text-[var(--warning)]" : "text-accent"} />
              <span className={`font-medium ${health.paper_trading?.enabled ? "text-[var(--warning)]" : "text-accent"}`}>
                {health.paper_trading?.enabled ? "PAPER" : health.mode.toUpperCase()}
              </span>
              <span className="text-[var(--text-muted)]">{health.has_api_keys ? "API Connected" : "No Keys"}</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-lg glass px-3 py-1.5 text-xs">
              <IconCircle size={6} className="text-loss animate-pulse" />
              <span className="text-loss">Backend Offline</span>
            </div>
          )}
          <button onClick={fetchAll} className="rounded-lg glass p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-all">
            <IconRefresh size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Balance" value={balance ? `$${balance.balance_dollars}` : "—"} icon={<IconPortfolio size={16} />} />
        <StatCard label="Daily P&L" value={pnl ? `$${pnl.daily_pnl.toFixed(2)}` : "—"} change={pnl?.daily_pnl ?? 0} icon={<IconTrendUp size={16} />} />
        <StatCard label="Positions" value={positions.length} icon={<IconZap size={16} />} />
        <StatCard label="AI Signals" value={strategy ? `${strategy.total_signals}` : "0"} suffix=" today" icon={<IconShield size={16} />} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Open Positions" action={<span className="text-xs text-[var(--text-muted)]">{positions.length} active</span>}>
          {positions.length > 0 ? (
            <div className="space-y-2">
              {positions.map((p) => (
                <div key={p.ticker} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 hover:bg-white/[0.04] transition-colors">
                  <div>
                    <div className="text-sm font-semibold text-[var(--text-primary)]">{p.ticker}</div>
                    <div className="text-xs text-[var(--text-muted)]">{p.position > 0 ? "YES" : "NO"} × {Math.abs(p.position)}</div>
                  </div>
                  <div className="text-right">
                    {p.market_exposure_dollars && <div className="text-sm font-medium text-[var(--text-primary)] tabular-nums">${p.market_exposure_dollars}</div>}
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
            <div className="flex h-48 items-center justify-center text-sm text-[var(--text-muted)]">No open positions</div>
          )}
        </Card>

        <Card title="System Components" action={
          health ? <span className="text-xs text-accent font-medium">Operational</span>
                 : <span className="text-xs text-[var(--warning)]">Connecting...</span>
        }>
          <div className="space-y-2">
            {health ? Object.entries(health.components).map(([name, status]) => (
              <div key={name} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5">
                <span className="text-sm text-[var(--text-secondary)] capitalize">{name.replace(/_/g, " ")}</span>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--text-muted)] font-mono">{status}</span>
                  <IconCircle size={6} className={status === "ready" || status === "connected" ? "text-accent" : "text-[var(--warning)]"} />
                </div>
              </div>
            )) : (
              <div className="flex h-48 items-center justify-center text-sm text-[var(--text-muted)]">Waiting for backend...</div>
            )}
          </div>
        </Card>

        <Card title="AI Strategy" action={
          strategy?.running
            ? <span className="flex items-center gap-1.5 text-xs text-accent font-medium"><IconCircle size={6} className="text-accent" /> Running</span>
            : <span className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]"><IconCircle size={6} /> Idle</span>
        }>
          {strategy ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "Signals", value: strategy.total_signals, color: "text-[var(--text-primary)]" },
                  { label: "Executed", value: strategy.signals_executed, color: "text-accent" },
                  { label: "Filtered", value: strategy.signals_filtered, color: "text-[var(--warning)]" },
                  { label: "Rejected", value: strategy.signals_risk_rejected, color: "text-loss" },
                ].map((item) => (
                  <div key={item.label} className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3">
                    <div className="text-xs text-[var(--text-muted)]">{item.label}</div>
                    <div className={`text-lg font-bold tabular-nums ${item.color}`}>{item.value}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3">
                <div className="flex justify-between text-xs text-[var(--text-muted)]">
                  <span className="font-mono">{strategy.model_name}</span>
                  <span>Confidence: <span className="text-[var(--text-primary)] font-medium">{(strategy.avg_confidence * 100).toFixed(0)}%</span></span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-48 items-center justify-center text-sm text-[var(--text-muted)]">AI engine initializing...</div>
          )}
        </Card>

        <Card title="Risk Monitor">
          <div className="space-y-2">
            <RiskRow label="Kill Switch" value={risk?.kill_switch_active ? "ACTIVE" : "Inactive"} status={risk?.kill_switch_active ? "critical" : "ok"} />
            <RiskRow label="Daily P&L" value={`$${(risk?.daily_pnl ?? 0).toFixed(2)}`} status={(risk?.daily_pnl ?? 0) < -25 ? "critical" : (risk?.daily_pnl ?? 0) < -10 ? "warning" : "ok"} />
            <RiskRow label="Exposure" value={`$${(risk?.total_exposure ?? 0).toFixed(2)}`} status={(risk?.total_exposure ?? 0) > 400 ? "critical" : (risk?.total_exposure ?? 0) > 200 ? "warning" : "ok"} />
            <RiskRow label="Positions" value={String(risk?.position_count ?? 0)} status="ok" />
            <RiskRow label="Open Orders" value={String(risk?.open_orders ?? 0)} status="ok" />
          </div>
        </Card>
      </div>
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
