"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconBrain, IconTarget, IconZap, IconRefresh, IconCircle, IconTrendUp, IconTrendDown } from "@/components/ui/Icons";
import { api, type AIStatus, type AISignal } from "@/lib/api";

function Toggle({ label, enabled, onChange, description }: { label: string; enabled: boolean; onChange: (v: boolean) => void; description?: string }) {
  return (
    <div className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
      <div>
        <span className="text-sm text-[var(--text-primary)]">{label}</span>
        {description && <p className="text-xs text-[var(--text-muted)] mt-0.5">{description}</p>}
      </div>
      <button
        onClick={() => onChange(!enabled)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${enabled ? "bg-accent" : "bg-white/10"}`}
      >
        <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${enabled ? "translate-x-6" : "translate-x-1"}`} />
      </button>
    </div>
  );
}

export default function AIEnginePage() {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [signals, setSignals] = useState<AISignal[]>([]);
  const [featureImportance, setFeatureImportance] = useState<{ name: string; value: number }[]>([]);
  const [brainAlive, setBrainAlive] = useState(false);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [sRes, sigRes, featRes, healthRes] = await Promise.all([
        api.ai.status().catch(() => null),
        api.ai.signals({ limit: 20 }).catch(() => []),
        api.frankenstein.features().catch(() => null),
        api.frankenstein.health().catch(() => null),
      ]);
      setStatus(sRes);
      setSignals(sigRes);
      if (healthRes) setBrainAlive(healthRes.alive);

      // Build feature importance from live Frankenstein features
      if (featRes?.current && typeof featRes.current === "object") {
        const entries = Object.entries(featRes.current)
          .filter(([, v]) => typeof v === "number" && v !== 0)
          .sort((a, b) => Math.abs(b[1] as number) - Math.abs(a[1] as number))
          .slice(0, 8);
        const maxVal = Math.max(...entries.map(([, v]) => Math.abs(v as number)), 1);
        setFeatureImportance(
          entries.map(([name, v]) => ({
            name: name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
            value: Math.abs(v as number) / maxVal,
          })),
        );
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 15000);
    return () => clearInterval(iv);
  }, [refresh]);

  const toggleBrain = async () => {
    try {
      if (brainAlive) {
        await api.frankenstein.sleep();
        setBrainAlive(false);
      } else {
        await api.frankenstein.awaken();
        setBrainAlive(true);
      }
    } catch { /* ignore */ }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">AI Engine</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Machine learning pipeline & signal generation</p>
        </div>
        <button onClick={refresh} disabled={loading}
          className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all hover:border-white/10 flex items-center gap-2">
          <IconRefresh size={14} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Model Status" value={status?.model_loaded ? "Active" : "Inactive"} trend={status?.model_loaded ? "up" : "down"} icon={<IconBrain size={18} />} />
        <StatCard label="Signals" value={String(signals.length)} icon={<IconZap size={18} />} />
        <StatCard label="Avg Confidence" value={signals.length > 0 ? `${(signals.reduce((s, sig) => s + (sig.confidence ?? 0), 0) / signals.length * 100).toFixed(0)}%` : "—"} icon={<IconTarget size={18} />} />
        <StatCard label="Last Update" value={status?.last_prediction ? new Date(status.last_prediction).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—"} icon={<IconRefresh size={18} />} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Controls */}
        <Card title="Engine Configuration">
          <div className="space-y-3">
            <Toggle label="Frankenstein Brain" enabled={brainAlive} onChange={toggleBrain} description={brainAlive ? "AI brain is scanning markets" : "Brain is sleeping"} />
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <span className="text-sm text-[var(--text-secondary)]">Model: <span className="text-accent">{status?.model_name ?? "XGBoost"}</span></span>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <span className="text-sm text-[var(--text-secondary)]">Total Signals: <span className="text-accent tabular-nums">{status?.total_signals ?? 0}</span></span>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <span className="text-sm text-[var(--text-secondary)]">Executed: <span className="text-accent tabular-nums">{status?.signals_executed ?? 0}</span></span>
            </div>
          </div>
        </Card>

        {/* Signal Feed */}
        <Card title="Signal Feed" className="lg:col-span-1">
          <div className="space-y-1.5 max-h-[360px] overflow-y-auto pr-1">
            {signals.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">No signals generated yet</div>
            ) : (
              signals.map((sig, i) => (
                <div key={i} className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 transition-colors hover:bg-white/[0.04]">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm font-medium text-[var(--text-primary)]">{sig.ticker}</span>
                    <span className={`text-xs font-semibold ${sig.direction === "yes" ? "text-accent" : "text-loss"}`}>
                      {sig.direction?.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
                    <div className="flex items-center gap-2">
                      {(sig.confidence ?? 0) >= 0.7 ? <IconTrendUp size={12} className="text-accent" /> : <IconTrendDown size={12} className="text-[var(--warning)]" />}
                      <span className="tabular-nums">{((sig.confidence ?? 0) * 100).toFixed(0)}% conf</span>
                    </div>
                    <span className="tabular-nums font-mono">{sig.edge != null ? `${(sig.edge * 100).toFixed(1)}% edge` : ""}</span>
                  </div>
                  <div className="mt-2 h-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-accent to-accent/60 transition-all" style={{ width: `${(sig.confidence ?? 0) * 100}%` }} />
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* Feature Importance (Live) */}
        <Card title="Feature Importance">
          <div className="space-y-3">
            {featureImportance.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">No feature data yet</div>
            ) : (
              featureImportance.map((f) => (
                <div key={f.name}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-sm text-[var(--text-secondary)]">{f.name}</span>
                    <span className="text-xs text-accent tabular-nums font-mono">{(f.value * 100).toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-accent via-accent/80 to-accent/40 transition-all" style={{ width: `${f.value * 100}%` }} />
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
