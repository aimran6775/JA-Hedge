"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { api, type StrategyStatus } from "@/lib/api";

function Toggle({
  label,
  enabled,
  onToggle,
  disabled,
}: {
  label: string;
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-white">{label}</span>
      <button
        onClick={onToggle}
        disabled={disabled}
        className={`relative h-6 w-11 rounded-full transition-colors ${
          enabled ? "bg-[var(--accent)]" : "bg-white/10"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
            enabled ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}

function SliderInput({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-[var(--muted)]">{label}</span>
        <span className="tabular-nums text-white">
          {value}
          {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--accent)]"
      />
    </div>
  );
}

export default function AIPage() {
  const [status, setStatus] = useState<StrategyStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // Config state
  const [minConfidence, setMinConfidence] = useState(0.65);
  const [minEdge, setMinEdge] = useState(0.03);
  const [maxKelly, setMaxKelly] = useState(0.15);
  const [scanInterval, setScanInterval] = useState(30);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.strategy.status();
      setStatus(s);
    } catch {
      // strategy endpoint may not be running yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 10000);
    return () => clearInterval(interval);
  }, [loadStatus]);

  const toggleStrategy = async () => {
    setToggling(true);
    try {
      if (status?.running) {
        await api.strategy.stop();
      } else {
        await api.strategy.start();
      }
      await loadStatus();
    } catch {
      // ignore
    } finally {
      setToggling(false);
    }
  };

  const saveConfig = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      await api.strategy.updateConfig({
        min_confidence: minConfidence,
        min_edge: minEdge,
        max_kelly_fraction: maxKelly,
        scan_interval_seconds: scanInterval,
      });
      setSaveMsg("✅ Config saved");
    } catch {
      setSaveMsg("❌ Failed to save");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(""), 3000);
    }
  };

  const isRunning = status?.running ?? false;
  const winRate = status ? (status.total_signals > 0 ? ((status.signals_executed / status.total_signals) * 100) : 0) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AI Engine</h1>
          <p className="text-xs text-[var(--muted)] mt-1">
            {loading ? "Loading..." : `Model: ${status?.model_name ?? "unknown"} • Strategy: ${status?.strategy_id ?? "—"}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-[var(--muted)]">
            {isRunning ? "🟢 Running" : "⏸ Paused"}
          </span>
          <button
            onClick={toggleStrategy}
            disabled={toggling}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              isRunning
                ? "bg-red-500/20 text-red-400 hover:bg-red-500/30"
                : "bg-green-500/20 text-green-400 hover:bg-green-500/30"
            } ${toggling ? "opacity-50" : ""}`}
          >
            {toggling ? "..." : isRunning ? "Stop Strategy" : "Start Strategy"}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Total Signals" value={String(status?.total_signals ?? 0)} />
        <StatCard label="Executed" value={String(status?.signals_executed ?? 0)} />
        <StatCard label="Execution Rate" value={`${winRate.toFixed(0)}%`} />
        <StatCard label="Avg Confidence" value={`${((status?.avg_confidence ?? 0) * 100).toFixed(1)}%`} />
        <StatCard label="Avg Edge" value={`${((status?.avg_edge ?? 0) * 100).toFixed(1)}%`} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Strategy Config */}
        <Card title="Strategy Configuration" className="lg:col-span-1">
          <div className="space-y-4">
            <Toggle
              label="Auto-Trade"
              enabled={isRunning}
              onToggle={toggleStrategy}
              disabled={toggling}
            />

            <SliderInput
              label="Min Confidence"
              value={minConfidence}
              min={0.5}
              max={0.95}
              step={0.05}
              unit=""
              onChange={setMinConfidence}
            />

            <SliderInput
              label="Min Edge"
              value={minEdge}
              min={0.01}
              max={0.15}
              step={0.01}
              unit=""
              onChange={setMinEdge}
            />

            <SliderInput
              label="Max Kelly Fraction"
              value={maxKelly}
              min={0.05}
              max={0.5}
              step={0.05}
              unit=""
              onChange={setMaxKelly}
            />

            <SliderInput
              label="Scan Interval"
              value={scanInterval}
              min={10}
              max={120}
              step={5}
              unit="s"
              onChange={setScanInterval}
            />

            <div className="border-t border-white/10 pt-4">
              <label className="text-xs text-[var(--muted)]">Model</label>
              <div className="mt-1 rounded-md bg-white/5 px-3 py-2 text-sm text-white">
                {status?.model_name ?? "XGBoost"}
              </div>
            </div>

            <button
              onClick={saveConfig}
              disabled={saving}
              className={`w-full rounded-md bg-[var(--accent)] py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 ${saving ? "opacity-50" : ""}`}
            >
              {saving ? "Saving..." : "Save Configuration"}
            </button>
            {saveMsg && <p className="text-xs text-center">{saveMsg}</p>}
          </div>
        </Card>

        {/* Signal Stats */}
        <Card title="Signal Breakdown" className="lg:col-span-2">
          <div className="space-y-4">
            {[
              { label: "Signals Executed", value: status?.signals_executed ?? 0, color: "bg-green-500" },
              { label: "Risk Rejected", value: status?.signals_risk_rejected ?? 0, color: "bg-red-500" },
              { label: "Filtered Out", value: status?.signals_filtered ?? 0, color: "bg-yellow-500" },
            ].map((item) => {
              const total = status?.total_signals || 1;
              const pct = (item.value / total) * 100;
              return (
                <div key={item.label} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--muted)]">{item.label}</span>
                    <span className="tabular-nums text-white">{item.value} ({pct.toFixed(0)}%)</span>
                  </div>
                  <div className="h-2 rounded-full bg-white/10">
                    <div className={`h-2 rounded-full ${item.color}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}

            <div className="mt-6 border-t border-white/10 pt-4">
              <h4 className="text-sm font-medium text-white mb-3">Feature Importance</h4>
              <div className="space-y-2">
                {[
                  { name: "yes_price", importance: 0.18 },
                  { name: "rsi_14", importance: 0.14 },
                  { name: "ema_12", importance: 0.12 },
                  { name: "spread", importance: 0.10 },
                  { name: "macd_signal", importance: 0.09 },
                  { name: "volume_ratio", importance: 0.08 },
                  { name: "time_decay", importance: 0.07 },
                ].map((f) => (
                  <div key={f.name} className="flex items-center gap-3">
                    <span className="w-28 text-xs text-[var(--muted)] tabular-nums font-mono">
                      {f.name}
                    </span>
                    <div className="flex-1">
                      <div
                        className="h-2 rounded-full bg-[var(--accent)]"
                        style={{ width: `${(f.importance / 0.18) * 100}%` }}
                      />
                    </div>
                    <span className="w-12 text-right text-xs tabular-nums text-white">
                      {(f.importance * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
