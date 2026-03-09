"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api, type RiskSnapshot } from "@/lib/api";

function RiskGauge({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  const danger = pct > 80;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[var(--muted)]">{label}</span>
        <span className={`tabular-nums ${danger ? "text-red-400 font-medium" : "text-white"}`}>
          ${value.toFixed(2)} / ${max.toFixed(2)}
        </span>
      </div>
      <div className="h-2 rounded-full bg-white/10">
        <div
          className={`h-2 rounded-full transition-all ${danger ? "bg-red-500" : color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function RiskPage() {
  const [snapshot, setSnapshot] = useState<RiskSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Editable limits
  const [dailyLossLimit, setDailyLossLimit] = useState(50);
  const [maxPositionSize, setMaxPositionSize] = useState(25);
  const [maxExposure, setMaxExposure] = useState(200);
  const [maxOrderCost, setMaxOrderCost] = useState(25);

  const loadSnapshot = useCallback(async () => {
    try {
      const s = await api.risk.snapshot();
      setSnapshot(s);
    } catch {
      // risk endpoint may fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
    const interval = setInterval(loadSnapshot, 10000);
    return () => clearInterval(interval);
  }, [loadSnapshot]);

  const toggleKillSwitch = async () => {
    setToggling(true);
    try {
      const newState = !(snapshot?.kill_switch_active ?? false);
      const res = await api.risk.killSwitch(newState);
      setSnapshot(prev => prev ? { ...prev, kill_switch_active: res.kill_switch_active } : prev);
    } catch {
      // ignore
    } finally {
      setToggling(false);
    }
  };

  const saveLimits = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      await api.risk.updateLimits({
        daily_loss_limit: dailyLossLimit,
        max_position_size: maxPositionSize,
        max_exposure: maxExposure,
        max_order_cost: maxOrderCost,
      });
      setSaveMsg("✅ Limits saved");
    } catch {
      setSaveMsg("❌ Failed to save");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(""), 3000);
    }
  };

  const killActive = snapshot?.kill_switch_active ?? false;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Risk Management</h1>
          <p className="text-xs text-[var(--muted)] mt-1">
            {loading ? "Loading..." : "Live risk monitoring from Kalshi demo account"}
          </p>
        </div>
        <button
          onClick={toggleKillSwitch}
          disabled={toggling}
          className={`rounded-md px-6 py-2.5 text-sm font-bold uppercase tracking-wider transition-all ${
            killActive
              ? "animate-pulse bg-red-600 text-white shadow-lg shadow-red-600/30"
              : "bg-red-500/20 text-red-400 hover:bg-red-500/30"
          } ${toggling ? "opacity-50" : ""}`}
        >
          {toggling ? "..." : killActive ? "⛔ KILL SWITCH ACTIVE" : "🔴 Kill Switch"}
        </button>
      </div>

      {killActive && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <strong>Kill switch is active.</strong> All trading has been halted. No new orders will be placed. Click again to deactivate.
        </div>
      )}

      {/* Risk Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Daily P&L" value={`$${(snapshot?.daily_pnl ?? 0).toFixed(2)}`} />
        <StatCard label="Open Exposure" value={`$${(snapshot?.total_exposure ?? 0).toFixed(2)}`} />
        <StatCard label="Positions" value={String(snapshot?.position_count ?? 0)} />
        <StatCard label="Open Orders" value={String(snapshot?.open_orders ?? 0)} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Risk Limits Editor */}
        <Card title="Risk Limits" className="lg:col-span-1">
          <div className="space-y-4">
            <div>
              <label className="text-xs text-[var(--muted)]">Daily Loss Limit ($)</label>
              <input
                type="number"
                value={dailyLossLimit}
                onChange={(e) => setDailyLossLimit(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white focus:border-[var(--accent)] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs text-[var(--muted)]">Max Position Size (contracts)</label>
              <input
                type="number"
                value={maxPositionSize}
                onChange={(e) => setMaxPositionSize(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white focus:border-[var(--accent)] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs text-[var(--muted)]">Max Portfolio Exposure ($)</label>
              <input
                type="number"
                value={maxExposure}
                onChange={(e) => setMaxExposure(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white focus:border-[var(--accent)] focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs text-[var(--muted)]">Max Single Order Cost ($)</label>
              <input
                type="number"
                value={maxOrderCost}
                onChange={(e) => setMaxOrderCost(Number(e.target.value))}
                className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white focus:border-[var(--accent)] focus:outline-none"
              />
            </div>

            <button
              onClick={saveLimits}
              disabled={saving}
              className={`w-full rounded-md bg-[var(--accent)] py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 ${saving ? "opacity-50" : ""}`}
            >
              {saving ? "Saving..." : "Save Risk Limits"}
            </button>
            {saveMsg && <p className="text-xs text-center">{saveMsg}</p>}
          </div>
        </Card>

        {/* Gauges + Status */}
        <div className="space-y-4 lg:col-span-2">
          <Card title="Exposure Gauges">
            <div className="space-y-4">
              <RiskGauge label="Daily P&L" value={Math.abs(snapshot?.daily_pnl ?? 0)} max={dailyLossLimit} color="bg-yellow-400" />
              <RiskGauge label="Portfolio Exposure" value={snapshot?.total_exposure ?? 0} max={maxExposure} color="bg-blue-400" />
              <RiskGauge label="Daily Trades" value={snapshot?.daily_trades ?? 0} max={50} color="bg-[var(--accent)]" />
            </div>
          </Card>

          <Card title="System Status">
            <div className="space-y-2">
              {[
                { label: "Kill Switch", value: killActive ? "ACTIVE" : "Off", danger: killActive },
                { label: "Positions Open", value: String(snapshot?.position_count ?? 0), danger: false },
                { label: "Open Orders", value: String(snapshot?.open_orders ?? 0), danger: false },
                { label: "Daily Trades", value: String(snapshot?.daily_trades ?? 0), danger: (snapshot?.daily_trades ?? 0) > 40 },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                  <span className="text-[var(--muted)]">{item.label}</span>
                  <span className={item.danger ? "text-red-400 font-medium" : "text-white"}>
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
