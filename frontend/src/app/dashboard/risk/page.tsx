"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconShield, IconAlertTriangle, IconTarget, IconStop, IconRefresh, IconCircle, IconCheck } from "@/components/ui/Icons";
import { api, type RiskLimits, type RiskStatus } from "@/lib/api";

function RiskGauge({ label, value, max, danger }: { label: string; value: number; max: number; danger: number }) {
  const pct = Math.min((value / max) * 100, 100);
  const isDanger = value >= danger;
  const isWarn = value >= danger * 0.7;
  const color = isDanger ? "from-loss to-loss/60" : isWarn ? "from-[var(--warning)] to-[var(--warning)]/60" : "from-accent to-accent/60";

  return (
    <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-[var(--text-secondary)]">{label}</span>
        <span className={`text-sm tabular-nums font-mono font-medium ${isDanger ? "text-loss" : isWarn ? "text-[var(--warning)]" : "text-accent"}`}>
          {value} / {max}
        </span>
      </div>
      <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden">
        <div className={`h-full rounded-full bg-gradient-to-r ${color} transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between mt-1.5 text-xs text-[var(--text-muted)]">
        <span>0</span>
        <span className="text-loss/60">{danger} limit</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

export default function RiskPage() {
  const [limits, setLimits] = useState<RiskLimits | null>(null);
  const [status, setStatus] = useState<RiskStatus | null>(null);
  const [killActive, setKillActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rejections, setRejections] = useState<Record<string, unknown> | null>(null);

  // Editable limits
  const [maxPositions, setMaxPositions] = useState(10);
  const [maxExposure, setMaxExposure] = useState(5000);
  const [maxLossDaily, setMaxLossDaily] = useState(500);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [limRes, stRes, rejRes] = await Promise.all([
        api.risk.limits().catch(() => null),
        api.risk.status().catch(() => null),
        api.frankenstein.debugRejections().catch(() => null),
      ]);
      setLimits(limRes);
      setStatus(stRes);
      setRejections(rejRes);
      if (limRes) {
        setMaxPositions(limRes.max_positions ?? 10);
        setMaxExposure(limRes.max_exposure_cents ?? 5000);
        setMaxLossDaily(limRes.max_daily_loss_cents ?? 500);
      }
      if (stRes) {
        setKillActive(stRes.kill_switch_active ?? false);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 10000);
    return () => clearInterval(iv);
  }, [refresh]);

  const toggleKillSwitch = async () => {
    try {
      if (killActive) {
        await api.risk.resetKillSwitch();
        setKillActive(false);
      } else {
        await api.risk.activateKillSwitch();
        setKillActive(true);
      }
    } catch { /* ignore */ }
  };

  const saveLimits = async () => {
    setSaving(true);
    setSaveResult(null);
    try {
      await api.risk.updateLimits({ max_positions: maxPositions, max_exposure_cents: maxExposure, max_daily_loss_cents: maxLossDaily });
      setSaveResult("Limits saved");
      refresh();
    } catch {
      setSaveResult("Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const openPositions = status?.open_positions ?? 0;
  const currentExposure = status?.total_exposure_cents ?? 0;
  const dailyLoss = status?.daily_pnl_cents ?? 0;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Risk Management</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Position limits, exposure controls, and kill switch</p>
        </div>
        <button onClick={refresh} disabled={loading}
          className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all flex items-center gap-2">
          <IconRefresh size={14} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Kill Switch" value={killActive ? "ACTIVE" : "OFF"} trend={killActive ? "down" : "up"} icon={<IconStop size={18} />} />
        <StatCard label="Open Positions" value={String(openPositions)} icon={<IconTarget size={18} />} />
        <StatCard label="Total Exposure" value={`$${(currentExposure / 100).toFixed(2)}`} icon={<IconShield size={18} />} />
        <StatCard label="Daily P&L" value={`$${(dailyLoss / 100).toFixed(2)}`} trend={dailyLoss >= 0 ? "up" : "down"} icon={<IconAlertTriangle size={18} />} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Kill Switch */}
        <Card title="Emergency Kill Switch">
          <div className="space-y-4">
            <div className={`rounded-xl p-6 text-center border ${killActive ? "bg-loss/10 border-loss/25" : "bg-white/[0.02] border-white/[0.04]"}`}>
              <div className={`mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl ${killActive ? "bg-loss/20" : "bg-accent/10"}`}>
                {killActive ? <IconStop size={32} className="text-loss" /> : <IconShield size={32} className="text-accent" />}
              </div>
              <div className={`text-lg font-bold ${killActive ? "text-loss" : "text-accent"}`}>
                {killActive ? "KILL SWITCH ACTIVE" : "System Normal"}
              </div>
              <p className="text-xs text-[var(--text-muted)] mt-1.5">
                {killActive ? "All trading has been halted" : "Trading operations are running normally"}
              </p>
            </div>
            <button onClick={toggleKillSwitch}
              className={`w-full rounded-xl py-3.5 text-sm font-bold tracking-wide transition-all ${
                killActive ? "bg-accent text-white hover:bg-accent/90" : "bg-loss/90 text-white hover:bg-loss"
              }`}>
              {killActive ? "RESET KILL SWITCH" : "ACTIVATE KILL SWITCH"}
            </button>
          </div>
        </Card>

        {/* Risk Limits Editor */}
        <Card title="Risk Limits">
          <div className="space-y-4">
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm text-[var(--text-secondary)]">Max Positions</span>
                <input type="number" value={maxPositions} onChange={(e) => setMaxPositions(Number(e.target.value))} min={1} max={50}
                  className="w-20 rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-1.5 text-sm text-[var(--text-primary)] tabular-nums text-right focus:border-accent/30 transition-all" />
              </div>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm text-[var(--text-secondary)]">Max Exposure (cents)</span>
                <input type="number" value={maxExposure} onChange={(e) => setMaxExposure(Number(e.target.value))} min={100} max={100000} step={100}
                  className="w-24 rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-1.5 text-sm text-[var(--text-primary)] tabular-nums text-right focus:border-accent/30 transition-all" />
              </div>
            </div>
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm text-[var(--text-secondary)]">Max Daily Loss (cents)</span>
                <input type="number" value={maxLossDaily} onChange={(e) => setMaxLossDaily(Number(e.target.value))} min={50} max={10000} step={50}
                  className="w-24 rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-1.5 text-sm text-[var(--text-primary)] tabular-nums text-right focus:border-accent/30 transition-all" />
              </div>
            </div>
            <button onClick={saveLimits} disabled={saving}
              className="w-full rounded-xl py-3 text-sm font-semibold bg-accent text-white hover:bg-accent/90 transition-all flex items-center justify-center gap-2">
              <IconCheck size={14} /> {saving ? "Saving..." : "Save Limits"}
            </button>
            {saveResult && (
              <div className={`rounded-xl p-3 text-sm text-center ${saveResult.includes("saved") ? "bg-accent/10 text-accent border border-accent/20" : "bg-loss/10 text-loss border border-loss/20"}`}>
                {saveResult}
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Risk Gauges */}
      <Card title="Exposure Gauges">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <RiskGauge label="Open Positions" value={openPositions} max={maxPositions * 2} danger={maxPositions} />
          <RiskGauge label="Total Exposure" value={currentExposure} max={maxExposure * 2} danger={maxExposure} />
          <RiskGauge label="Daily Loss" value={Math.abs(dailyLoss)} max={maxLossDaily * 2} danger={maxLossDaily} />
        </div>
      </Card>

      {/* Violations / Rejections Log */}
      <Card title="Trade Rejections & Risk Events">
        <div className="space-y-1.5">
          {rejections ? (
            <>
              {/* Portfolio check */}
              {rejections.portfolio_check && (
                <div className={`flex items-center gap-3 rounded-xl px-4 py-3 ${
                  (rejections.portfolio_check as { passed: boolean }).passed
                    ? "bg-accent/[0.04] border border-accent/10"
                    : "bg-loss/[0.04] border border-loss/10"
                }`}>
                  {(rejections.portfolio_check as { passed: boolean }).passed
                    ? <IconCheck size={14} className="text-accent flex-shrink-0" />
                    : <IconAlertTriangle size={14} className="text-loss flex-shrink-0" />}
                  <span className="text-sm text-[var(--text-secondary)]">
                    Portfolio Check: {(rejections.portfolio_check as { passed: boolean }).passed ? "Passing" : (rejections.portfolio_check as { reason: string }).reason || "Failed"}
                  </span>
                </div>
              )}
              {/* Risk limits from debug */}
              {rejections.risk_limits && typeof rejections.risk_limits === "object" && (
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
                  <div className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">Risk Limits State</div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {Object.entries(rejections.risk_limits as Record<string, unknown>).map(([k, v]) => (
                      <div key={k} className="flex justify-between">
                        <span className="text-[var(--text-muted)]">{k.replace(/_/g, " ")}</span>
                        <span className="text-[var(--text-primary)] tabular-nums font-mono">{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {/* Recent scan candidates */}
              {rejections.recent_scan_results && Array.isArray((rejections.recent_scan_results as { top_candidates?: unknown[] }).top_candidates) && (
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3">
                  <div className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">Recent Scan Candidates</div>
                  {((rejections.recent_scan_results as { top_candidates: Array<{ ticker: string; stage: string; error?: string; order_id?: string }> }).top_candidates).map((c, i) => (
                    <div key={i} className="flex items-center gap-2 py-1 text-xs">
                      <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${
                        c.stage === "executed" ? "bg-accent/10 text-accent" : c.stage === "rejected" ? "bg-loss/10 text-loss" : "bg-white/5 text-[var(--text-muted)]"
                      }`}>{c.stage}</span>
                      <span className="text-[var(--text-primary)] font-mono">{c.ticker}</span>
                      {c.error && <span className="text-loss truncate">{c.error}</span>}
                      {c.order_id && <span className="text-[var(--text-muted)] font-mono truncate">{c.order_id.slice(0, 8)}...</span>}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (status?.recent_violations ?? []).length === 0 ? (
            <div className="py-6 text-center">
              <IconCheck size={20} className="mx-auto text-accent mb-2" />
              <div className="text-sm text-[var(--text-muted)]">No violations recorded</div>
            </div>
          ) : (
            (status?.recent_violations ?? []).map((v: string, i: number) => (
              <div key={i} className="flex items-center gap-3 rounded-xl bg-loss/[0.04] border border-loss/10 px-4 py-3">
                <IconAlertTriangle size={14} className="text-loss flex-shrink-0" />
                <span className="text-sm text-[var(--text-secondary)]">{v}</span>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
