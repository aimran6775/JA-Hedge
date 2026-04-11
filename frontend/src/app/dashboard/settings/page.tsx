"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import {
  IconSettings, IconCircle, IconRefresh, IconAlertTriangle,
  IconZap, IconShield, IconBrain, IconRocket,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";



/* ── Types ──────────────────────────────────────────────────────────────── */

interface SystemInfo {
  backend: boolean;
  frankenstein: boolean;
}

interface Settings {
  paper_trading: {
    enabled: boolean;
    balance_cents: number;
    starting_balance_cents: number;
    pnl_cents: number;
    fee_rate_cents: number;
    slippage_cents: number;
  };
  strategy: {
    min_confidence: number;
    min_edge: number;
    kelly_fraction: number;
    max_position_size: number;
    max_simultaneous_positions: number;
    scan_interval: number;
    max_daily_loss: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    max_spread_cents: number;
    aggression: number;
  };
  brain: {
    scan_interval: number;
    retrain_interval: number;
    min_train_samples: number;
    sports_only: boolean;
    model_version: string;
    generation: number;
  };
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function formatCents(c: number): string {
  return `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* ════════════════════════════════════════════════════════════════════════
   SETTINGS PAGE — Simulation Control & Configuration
   ════════════════════════════════════════════════════════════════════════ */
export default function SettingsPage() {
  const [sysInfo, setSysInfo] = useState<SystemInfo>({ backend: false, frankenstein: false });
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<"simulation" | "strategy" | "brain" | "system" | "diagnostics">("simulation");

  // Reset dialog
  const [showReset, setShowReset] = useState(false);
  const [resetBalance, setResetBalance] = useState("10000");
  const [resetClearMemory, setResetClearMemory] = useState(true);
  const [resetRestartBrain, setResetRestartBrain] = useState(true);
  const [resetting, setResetting] = useState(false);

  // Editable strategy fields
  const [editStrat, setEditStrat] = useState<Record<string, string>>({});
  const [savingStrat, setSavingStrat] = useState(false);

  // Editable brain fields
  const [editBrain, setEditBrain] = useState<Record<string, string>>({});
  const [savingBrain, setSavingBrain] = useState(false);

  // Diagnostics
  const [rejections, setRejections] = useState<Record<string, unknown> | null>(null);
  const [schedule, setSchedule] = useState<Record<string, unknown> | null>(null);

  /* ── Fetch ───────────────────────────────────────────────────────────── */
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [backendOk, frankOk] = await Promise.all([
        fetch("/health").then(r => r.ok).catch(() => false),
        fetch("/api/frankenstein/health").then(r => r.ok).catch(() => false),
      ]);
      setSysInfo({ backend: backendOk, frankenstein: frankOk });

      const s = await api.frankenstein.getSettings().catch(() => null);
      if (s) {
        setSettings(s);
        setEditStrat({
          min_confidence: (s.strategy.min_confidence * 100).toFixed(0),
          min_edge: (s.strategy.min_edge * 100).toFixed(1),
          kelly_fraction: (s.strategy.kelly_fraction * 100).toFixed(0),
          max_position_size: String(s.strategy.max_position_size),
          max_simultaneous_positions: String(s.strategy.max_simultaneous_positions),
          scan_interval: String(s.strategy.scan_interval),
          max_daily_loss: String(s.strategy.max_daily_loss),
          stop_loss_pct: (s.strategy.stop_loss_pct * 100).toFixed(0),
          take_profit_pct: (s.strategy.take_profit_pct * 100).toFixed(0),
          max_spread_cents: String(s.strategy.max_spread_cents),
          aggression: (s.strategy.aggression * 100).toFixed(0),
        });
        setEditBrain({
          scan_interval: String(s.brain.scan_interval),
          retrain_interval: String(s.brain.retrain_interval),
          min_train_samples: String(s.brain.min_train_samples),
        });
      }

      // Diagnostics data
      const [rejRes, schedRes] = await Promise.allSettled([
        api.frankenstein.debugRejections(),
        api.frankenstein.schedule(),
      ]);
      if (rejRes.status === "fulfilled") setRejections(rejRes.value);
      if (schedRes.status === "fulfilled") setSchedule(schedRes.value);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  /* ── Actions ─────────────────────────────────────────────────────────── */
  const flash = (msg: string, isErr = false) => {
    setActionMsg(msg);
    setTimeout(() => setActionMsg(null), isErr ? 5000 : 3000);
  };

  const doReset = async () => {
    setResetting(true);
    try {
      const balCents = Math.round(parseFloat(resetBalance) * 100);
      if (isNaN(balCents) || balCents < 100) {
        flash("✗ Balance must be at least $1.00", true);
        setResetting(false);
        return;
      }
      const res = await api.frankenstein.resetSimulation({
        balance_cents: balCents,
        clear_memory: resetClearMemory,
        restart_brain: resetRestartBrain,
      });
      flash(`✓ Reset! ${res.message} — New balance: ${res.new_balance}`);
      setShowReset(false);
      refresh();
    } catch (e: unknown) {
      flash(`✗ Reset failed: ${e instanceof Error ? e.message : "unknown"}`, true);
    } finally {
      setResetting(false);
    }
  };

  const saveStrategy = async () => {
    setSavingStrat(true);
    try {
      const payload: Record<string, unknown> = {
        strategy: {
          min_confidence: parseFloat(editStrat.min_confidence) / 100,
          min_edge: parseFloat(editStrat.min_edge) / 100,
          kelly_fraction: parseFloat(editStrat.kelly_fraction) / 100,
          max_position_size: parseInt(editStrat.max_position_size),
          max_simultaneous_positions: parseInt(editStrat.max_simultaneous_positions),
          scan_interval: parseFloat(editStrat.scan_interval),
          max_daily_loss: parseFloat(editStrat.max_daily_loss),
          stop_loss_pct: parseFloat(editStrat.stop_loss_pct) / 100,
          take_profit_pct: parseFloat(editStrat.take_profit_pct) / 100,
          max_spread_cents: parseInt(editStrat.max_spread_cents),
          aggression: parseFloat(editStrat.aggression) / 100,
        },
      };
      const res = await api.frankenstein.updateSettings(payload);
      flash(`✓ ${res.message}`);
      refresh();
    } catch (e: unknown) {
      flash(`✗ Save failed: ${e instanceof Error ? e.message : "unknown"}`, true);
    } finally {
      setSavingStrat(false);
    }
  };

  const saveBrain = async () => {
    setSavingBrain(true);
    try {
      const payload: Record<string, unknown> = {
        brain: {
          scan_interval: parseFloat(editBrain.scan_interval),
          retrain_interval: parseFloat(editBrain.retrain_interval),
          min_train_samples: parseInt(editBrain.min_train_samples),
        },
      };
      const res = await api.frankenstein.updateSettings(payload);
      flash(`✓ ${res.message}`);
      refresh();
    } catch (e: unknown) {
      flash(`✗ Save failed: ${e instanceof Error ? e.message : "unknown"}`, true);
    } finally {
      setSavingBrain(false);
    }
  };

  const toggleSportsOnly = async () => {
    if (!settings) return;
    try {
      await api.frankenstein.updateSettings({ brain: { sports_only: !settings.brain.sports_only } });
      flash(`✓ Sports-only mode ${settings.brain.sports_only ? "disabled" : "enabled"}`);
      refresh();
    } catch (e: unknown) {
      flash(`✗ ${e instanceof Error ? e.message : "failed"}`, true);
    }
  };

  const cancelAllOrders = async () => {
    try {
      await api.orders.cancelAll();
      flash("✓ All orders cancelled");
    } catch {
      flash("✗ Failed to cancel orders", true);
    }
  };

  /* ── Derived ─────────────────────────────────────────────────────────── */
  const pt = settings?.paper_trading;
  const br = settings?.brain;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/20 to-violet-500/5 border border-violet-500/20">
            <IconSettings size={24} className="text-violet-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Settings & Control</h1>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">Simulation, strategy parameters, and system configuration</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {actionMsg && <span className={`text-xs mr-2 ${actionMsg.startsWith("✗") ? "text-loss" : "text-accent"}`}>{actionMsg}</span>}
          <button onClick={refresh} disabled={loading}
            className="glass rounded-xl px-3 py-2 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all">
            <IconRefresh size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Tab Nav ────────────────────────────────────────────────────── */}
      <div className="flex gap-1 rounded-2xl glass p-1">
        {(["simulation", "strategy", "brain", "system", "diagnostics"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-all
              ${tab === t ? "bg-violet-500/10 text-violet-400 border border-violet-500/20" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] border border-transparent"}`}>
            {t === "simulation" ? "💰 Sim" : t === "strategy" ? "🎯 Strategy" : t === "brain" ? "🧠 Brain" : t === "diagnostics" ? "🔍 Debug" : "⚙️ System"}
          </button>
        ))}
      </div>

      {/* ════════════ TAB: SIMULATION ════════════════════════════════════ */}
      {tab === "simulation" && (
        <div className="space-y-4">
          {/* Current Balance Card */}
          <div className="glass rounded-2xl p-6 border border-white/[0.06]">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-1">Paper Trading Balance</div>
                <div className="text-4xl font-bold text-[var(--text-primary)] tabular-nums">
                  {pt ? formatCents(pt.balance_cents) : "—"}
                </div>
                <div className="flex items-center gap-4 mt-2">
                  <span className="text-sm text-[var(--text-muted)]">
                    Started: {pt ? formatCents(pt.starting_balance_cents) : "—"}
                  </span>
                  <span className={`text-sm font-semibold ${pt && pt.pnl_cents >= 0 ? "text-accent" : "text-loss"}`}>
                    P&L: {pt ? `${pt.pnl_cents >= 0 ? "+" : ""}${formatCents(pt.pnl_cents)}` : "—"}
                  </span>
                </div>
              </div>
              <button
                onClick={() => setShowReset(true)}
                className="relative overflow-hidden rounded-2xl px-6 py-4 text-sm font-bold text-white
                  bg-gradient-to-r from-violet-600 to-purple-500 hover:from-violet-500 hover:to-purple-400
                  shadow-lg shadow-violet-500/25 hover:shadow-violet-500/40
                  transition-all duration-300 transform hover:scale-[1.02] active:scale-[0.98]
                  flex items-center gap-3"
              >
                <IconRocket size={18} />
                <span>Reset Simulation</span>
              </button>
            </div>
          </div>

          {/* Reset Dialog */}
          {showReset && (
            <div className="glass rounded-2xl p-6 border-2 border-violet-500/30 space-y-5">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10">
                  <IconRocket size={20} className="text-violet-400" />
                </div>
                <div>
                  <div className="text-base font-bold text-[var(--text-primary)]">Reset Simulation</div>
                  <div className="text-xs text-[var(--text-muted)]">Start fresh with a new balance and clean slate</div>
                </div>
              </div>

              {/* Balance Input */}
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1.5 font-medium">Starting Balance ($)</label>
                <input
                  type="number"
                  value={resetBalance}
                  onChange={e => setResetBalance(e.target.value)}
                  min="1" step="100"
                  className="w-full rounded-xl bg-white/[0.03] border border-white/[0.08] px-4 py-3 text-lg font-mono
                    text-[var(--text-primary)] placeholder:text-[var(--text-muted)]
                    focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20 transition-all"
                  placeholder="10000"
                />
                <div className="flex gap-2 mt-2">
                  {[1000, 5000, 10000, 25000, 50000, 100000].map(v => (
                    <button key={v} onClick={() => setResetBalance(String(v))}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all border
                        ${resetBalance === String(v)
                          ? "bg-violet-500/15 border-violet-500/30 text-violet-400"
                          : "bg-white/[0.02] border-white/[0.06] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"}`}>
                      ${v >= 1000 ? `${v / 1000}K` : v}
                    </button>
                  ))}
                </div>
              </div>

              {/* Options */}
              <div className="space-y-3">
                <label className="flex items-center gap-3 cursor-pointer group">
                  <input type="checkbox" checked={resetClearMemory} onChange={e => setResetClearMemory(e.target.checked)}
                    className="h-4 w-4 rounded border-white/20 bg-white/5 text-violet-500 focus:ring-violet-500/30" />
                  <div>
                    <div className="text-sm text-[var(--text-primary)] group-hover:text-violet-400 transition-colors">Clear Trade Memory</div>
                    <div className="text-xs text-[var(--text-muted)]">Erase all trade history and start learning from scratch</div>
                  </div>
                </label>
                <label className="flex items-center gap-3 cursor-pointer group">
                  <input type="checkbox" checked={resetRestartBrain} onChange={e => setResetRestartBrain(e.target.checked)}
                    className="h-4 w-4 rounded border-white/20 bg-white/5 text-violet-500 focus:ring-violet-500/30" />
                  <div>
                    <div className="text-sm text-[var(--text-primary)] group-hover:text-violet-400 transition-colors">Restart Frankenstein</div>
                    <div className="text-xs text-[var(--text-muted)]">Sleep and re-awaken the AI brain (triggers fresh bootstrap)</div>
                  </div>
                </label>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={doReset}
                  disabled={resetting}
                  className="rounded-xl px-6 py-3 text-sm font-bold bg-violet-500 text-white hover:bg-violet-400
                    transition-all disabled:opacity-50 flex items-center gap-2"
                >
                  {resetting ? "Resetting..." : "🚀 Reset & Restart"}
                </button>
                <button
                  onClick={() => setShowReset(false)}
                  className="rounded-xl px-6 py-3 text-sm font-medium glass text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Simulation Stats */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Paper Trading Config">
              <div className="space-y-2">
                <InfoRow label="Mode" value="Paper Trading (Simulated)" />
                <InfoRow label="Starting Balance" value={pt ? formatCents(pt.starting_balance_cents) : "—"} />
                <InfoRow label="Current Balance" value={pt ? formatCents(pt.balance_cents) : "—"} />
                <InfoRow label="P&L" value={pt ? `${pt.pnl_cents >= 0 ? "+" : ""}${formatCents(pt.pnl_cents)}` : "—"}
                  color={pt && pt.pnl_cents >= 0 ? "text-accent" : "text-loss"} />
                <InfoRow label="Fee Rate" value={pt ? `${pt.fee_rate_cents}¢/contract` : "—"} />
                <InfoRow label="Slippage" value={pt ? `${pt.slippage_cents}¢` : "—"} />
              </div>
            </Card>

            <Card title="Quick Actions">
              <div className="space-y-3">
                <button onClick={cancelAllOrders}
                  className="w-full rounded-xl py-3 text-sm font-bold bg-loss/20 text-loss hover:bg-loss/30
                    border border-loss/20 transition-all flex items-center justify-center gap-2">
                  <IconAlertTriangle size={16} /> Cancel All Open Orders
                </button>
                <button onClick={() => api.frankenstein.retrain().then(() => flash("✓ Retrain triggered")).catch(() => flash("✗ Retrain failed", true))}
                  className="w-full rounded-xl py-3 text-sm font-bold bg-accent/20 text-accent hover:bg-accent/30
                    border border-accent/20 transition-all flex items-center justify-center gap-2">
                  <IconRocket size={16} /> Force Model Retrain
                </button>
                <button onClick={() => api.frankenstein.bootstrap().then(() => flash("✓ Bootstrap triggered")).catch(() => flash("✗ Bootstrap failed", true))}
                  className="w-full rounded-xl py-3 text-sm font-bold bg-blue-500/20 text-blue-400 hover:bg-blue-500/30
                    border border-blue-500/20 transition-all flex items-center justify-center gap-2">
                  <IconBrain size={16} /> Re-Bootstrap Training Data
                </button>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ════════════ TAB: STRATEGY ══════════════════════════════════════ */}
      {tab === "strategy" && (
        <div className="space-y-4">
          <Card title="Strategy Parameters" action={
            <button onClick={saveStrategy} disabled={savingStrat}
              className="rounded-lg px-4 py-1.5 text-xs font-bold bg-accent text-white hover:bg-accent/90 transition-all disabled:opacity-50">
              {savingStrat ? "Saving..." : "Save Changes"}
            </button>
          }>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <EditField label="Min Confidence" value={editStrat.min_confidence} suffix="%" onChange={v => setEditStrat(p => ({ ...p, min_confidence: v }))}
                hint="Minimum model confidence to enter a trade (50-95%)" />
              <EditField label="Min Edge" value={editStrat.min_edge} suffix="%" onChange={v => setEditStrat(p => ({ ...p, min_edge: v }))}
                hint="Minimum price edge over market (1-20%)" />
              <EditField label="Kelly Fraction" value={editStrat.kelly_fraction} suffix="%" onChange={v => setEditStrat(p => ({ ...p, kelly_fraction: v }))}
                hint="Fraction of Kelly criterion for sizing (5-50%)" />
              <EditField label="Max Position Size" value={editStrat.max_position_size} suffix=" contracts" onChange={v => setEditStrat(p => ({ ...p, max_position_size: v }))}
                hint="Maximum contracts per trade" />
              <EditField label="Max Simultaneous Positions" value={editStrat.max_simultaneous_positions} onChange={v => setEditStrat(p => ({ ...p, max_simultaneous_positions: v }))}
                hint="Maximum open positions at once" />
              <EditField label="Scan Interval" value={editStrat.scan_interval} suffix="s" onChange={v => setEditStrat(p => ({ ...p, scan_interval: v }))}
                hint="Seconds between market scans (10-300s)" />
              <EditField label="Max Daily Loss" value={editStrat.max_daily_loss} suffix=" $" onChange={v => setEditStrat(p => ({ ...p, max_daily_loss: v }))}
                hint="Stop trading if daily loss exceeds this" />
              <EditField label="Stop Loss" value={editStrat.stop_loss_pct} suffix="%" onChange={v => setEditStrat(p => ({ ...p, stop_loss_pct: v }))}
                hint="Exit position at this % loss" />
              <EditField label="Take Profit" value={editStrat.take_profit_pct} suffix="%" onChange={v => setEditStrat(p => ({ ...p, take_profit_pct: v }))}
                hint="Exit position at this % profit" />
              <EditField label="Max Spread" value={editStrat.max_spread_cents} suffix="¢" onChange={v => setEditStrat(p => ({ ...p, max_spread_cents: v }))}
                hint="Skip markets with wider spread" />
              <EditField label="Aggression" value={editStrat.aggression} suffix="%" onChange={v => setEditStrat(p => ({ ...p, aggression: v }))}
                hint="Overall aggression level (10-100%)" />
            </div>
          </Card>

          {/* Presets */}
          <Card title="Strategy Presets">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <PresetButton
                name="Conservative"
                desc="Low risk, high confidence"
                icon="🛡️"
                onClick={() => setEditStrat({
                  min_confidence: "70", min_edge: "8.0", kelly_fraction: "15",
                  max_position_size: "5", max_simultaneous_positions: "10",
                  scan_interval: "60", max_daily_loss: "25", stop_loss_pct: "10",
                  take_profit_pct: "20", max_spread_cents: "25", aggression: "30",
                })}
              />
              <PresetButton
                name="Balanced"
                desc="Default parameters"
                icon="⚖️"
                onClick={() => setEditStrat({
                  min_confidence: "52", min_edge: "2.0", kelly_fraction: "25",
                  max_position_size: "10", max_simultaneous_positions: "20",
                  scan_interval: "30", max_daily_loss: "50", stop_loss_pct: "15",
                  take_profit_pct: "30", max_spread_cents: "40", aggression: "50",
                })}
              />
              <PresetButton
                name="Aggressive"
                desc="More trades, higher risk"
                icon="🔥"
                onClick={() => setEditStrat({
                  min_confidence: "52", min_edge: "1.5", kelly_fraction: "35",
                  max_position_size: "15", max_simultaneous_positions: "30",
                  scan_interval: "15", max_daily_loss: "100", stop_loss_pct: "20",
                  take_profit_pct: "40", max_spread_cents: "50", aggression: "75",
                })}
              />
              <PresetButton
                name="YOLO"
                desc="Maximum aggression"
                icon="🚀"
                onClick={() => setEditStrat({
                  min_confidence: "50", min_edge: "1.0", kelly_fraction: "45",
                  max_position_size: "25", max_simultaneous_positions: "50",
                  scan_interval: "10", max_daily_loss: "200", stop_loss_pct: "25",
                  take_profit_pct: "50", max_spread_cents: "60", aggression: "95",
                })}
              />
            </div>
          </Card>
        </div>
      )}

      {/* ════════════ TAB: BRAIN ═════════════════════════════════════════ */}
      {tab === "brain" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="Brain Configuration" action={
            <button onClick={saveBrain} disabled={savingBrain}
              className="rounded-lg px-4 py-1.5 text-xs font-bold bg-accent text-white hover:bg-accent/90 transition-all disabled:opacity-50">
              {savingBrain ? "Saving..." : "Save Brain Config"}
            </button>
          }>
            <div className="space-y-3">
              <InfoRow label="Model Version" value={br?.model_version ?? "—"} mono />
              <InfoRow label="Generation" value={`Gen ${br?.generation ?? 0}`} />
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1 font-medium">Scan Interval (seconds)</label>
                <input type="number" value={editBrain.scan_interval ?? ""} onChange={e => setEditBrain(p => ({ ...p, scan_interval: e.target.value }))}
                  className="w-full rounded-lg bg-white/[0.03] border border-white/[0.08] px-3 py-2.5 text-sm font-mono text-[var(--text-primary)] focus:border-accent/40 transition-all" />
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">How often the brain scans for trades (10-300s)</p>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1 font-medium">Retrain Interval (seconds)</label>
                <input type="number" value={editBrain.retrain_interval ?? ""} onChange={e => setEditBrain(p => ({ ...p, retrain_interval: e.target.value }))}
                  className="w-full rounded-lg bg-white/[0.03] border border-white/[0.08] px-3 py-2.5 text-sm font-mono text-[var(--text-primary)] focus:border-accent/40 transition-all" />
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">How often the model retrains (300-3600s)</p>
              </div>
              <div>
                <label className="block text-xs text-[var(--text-muted)] mb-1 font-medium">Min Training Samples</label>
                <input type="number" value={editBrain.min_train_samples ?? ""} onChange={e => setEditBrain(p => ({ ...p, min_train_samples: e.target.value }))}
                  className="w-full rounded-lg bg-white/[0.03] border border-white/[0.08] px-3 py-2.5 text-sm font-mono text-[var(--text-primary)] focus:border-accent/40 transition-all" />
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Minimum trades needed before model trains</p>
              </div>
            </div>
          </Card>

          <Card title="Market Mode">
            <div className="space-y-4">
              <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <div className="text-sm font-semibold text-[var(--text-primary)]">Sports-Only Mode</div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {br?.sports_only ? "Only trading sports markets" : "Trading ALL market categories"}
                    </div>
                  </div>
                  <button onClick={toggleSportsOnly}
                    className={`relative h-7 w-14 rounded-full transition-all ${br?.sports_only ? "bg-accent" : "bg-white/10"}`}>
                    <div className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all
                      ${br?.sports_only ? "left-[30px]" : "left-0.5"}`} />
                  </button>
                </div>
              </div>

              <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
                <div className="text-xs text-[var(--text-muted)] uppercase tracking-wider mb-2">Feature Engineering</div>
                <div className="space-y-1.5">
                  <FeaturePhase name="Phase 1-2" count={29} desc="Price, volume, time, probability" color="bg-blue-400" />
                  <FeaturePhase name="Phase 3" count={8} desc="Log-odds, convergence, overround" color="bg-violet-400" />
                  <FeaturePhase name="Phase 4" count={15} desc="Volatility, Bollinger, Hurst, VWAP" color="bg-purple-400" />
                  <FeaturePhase name="Phase 5" count={8} desc="Smart money, RSI divergence, mean-reversion" color="bg-accent" />
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <div className="h-2 flex-1 rounded-full bg-white/[0.06] overflow-hidden">
                    <div className="h-full rounded-full bg-gradient-to-r from-blue-400 via-violet-400 to-accent" style={{ width: "100%" }} />
                  </div>
                  <span className="text-xs font-bold text-accent tabular-nums">60 total</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ════════════ TAB: SYSTEM ════════════════════════════════════════ */}
      {tab === "system" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="System Status">
            <div className="space-y-2">
              <StatusRow label="Backend API" ok={sysInfo.backend} icon={<IconZap size={16} className={sysInfo.backend ? "text-accent" : "text-loss"} />} />
              <StatusRow label="Frankenstein AI" ok={sysInfo.frankenstein} icon={<IconBrain size={16} className={sysInfo.frankenstein ? "text-accent" : "text-loss"} />} />
            </div>
            <div className="mt-4 rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
              <div className="flex items-center gap-2 mb-3">
                <IconSettings size={14} className="text-[var(--text-muted)]" />
                <span className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">Configuration</span>
              </div>
              <div className="space-y-0">
                <SysRow label="API Base" value="/api (proxied)" />
                <SysRow label="Mode" value="Paper Trading (Demo)" />
                <SysRow label="Platform" value="Kalshi" />
                <SysRow label="Frontend" value="Next.js 15" />
                <SysRow label="Backend" value="FastAPI / Python" />
                <SysRow label="ML Model" value="XGBoost v2" />
                <SysRow label="Features" value="60 (Phase 5)" />
              </div>
            </div>
          </Card>

          <Card title="Platform Info">
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
                  <IconShield size={20} className="text-accent" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-[var(--text-primary)]">JA Hedge AI Trading Terminal</div>
                  <div className="text-xs text-[var(--text-muted)]">Autonomous prediction market trader</div>
                </div>
              </div>
              <div className="space-y-0">
                <SysRow label="Version" value="2.1.0" />
                <SysRow label="AI Brain" value="Frankenstein" />
                <SysRow label="ML Engine" value="XGBoost + Heuristic" />
                <SysRow label="Training" value="Time-series CV + Hyperparam Search" />
                <SysRow label="API Endpoints" value="25+" />
                <SysRow label="Build" value="Production" />
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ════════════ TAB: DIAGNOSTICS ═══════════════════════════════════ */}
      {tab === "diagnostics" && (
        <div className="space-y-4">
          {/* Scheduler */}
          <Card title="Frankenstein Scheduler">
            {schedule ? (
              <div className="space-y-2">
                {Object.entries(schedule).filter(([k]) => !k.startsWith("_")).map(([key, val]) => (
                  <div key={key} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                    <span className="text-xs text-[var(--text-muted)]">{key.replace(/_/g, " ")}</span>
                    <span className="text-xs font-mono text-[var(--text-primary)] tabular-nums truncate max-w-[250px]">
                      {typeof val === "object" ? JSON.stringify(val) : String(val)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-[var(--text-muted)]">Schedule data not available</div>
            )}
          </Card>

          {/* Trade Rejections */}
          <Card title="Trade Rejections & Debug">
            {rejections ? (
              <DiagnosticsContent rejections={rejections} />
            ) : (
              <div className="py-8 text-center text-[var(--text-muted)]">No rejection data available</div>
            )}
          </Card>

          {/* Quick Debug Actions */}
          <Card title="Debug Actions">
            <div className="grid grid-cols-2 gap-3">
              <button onClick={() => { api.frankenstein.retrain().then(() => flash("✓ Retrain triggered")).catch(() => flash("✗ Retrain failed", true)); }}
                className="rounded-xl py-3 text-sm font-bold bg-accent/20 text-accent hover:bg-accent/30 border border-accent/20 transition-all">
                🔄 Force Retrain
              </button>
              <button onClick={() => { api.frankenstein.bootstrap().then(() => flash("✓ Bootstrap triggered")).catch(() => flash("✗ Bootstrap failed", true)); }}
                className="rounded-xl py-3 text-sm font-bold bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 border border-blue-500/20 transition-all">
                📦 Re-Bootstrap Data
              </button>
              <button onClick={cancelAllOrders}
                className="rounded-xl py-3 text-sm font-bold bg-loss/20 text-loss hover:bg-loss/30 border border-loss/20 transition-all">
                ✕ Cancel All Orders
              </button>
              <button onClick={refresh}
                className="rounded-xl py-3 text-sm font-bold bg-violet-500/20 text-violet-400 hover:bg-violet-500/30 border border-violet-500/20 transition-all">
                🔃 Refresh All Data
              </button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ── Diagnostics Content (extracted to avoid TS unknown-as-ReactNode issues) ── */

function DiagnosticsContent({ rejections }: { rejections: Record<string, unknown> }) {
  const portfolioCheck = rejections.portfolio_check;
  const riskLimits = rejections.risk_limits as Record<string, unknown> | undefined;
  const candidates = rejections.recent_scan_candidates as Array<Record<string, unknown>> | undefined;

  return (
    <div className="space-y-3">
      {portfolioCheck !== undefined && (
        <div className={`rounded-xl p-3 border ${portfolioCheck ? "border-accent/20 bg-accent/5" : "border-loss/20 bg-loss/5"}`}>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${portfolioCheck ? "bg-accent" : "bg-loss"}`} />
            <span className="text-xs font-semibold text-[var(--text-primary)]">Portfolio Check</span>
            <span className={`text-xs ${portfolioCheck ? "text-accent" : "text-loss"}`}>
              {portfolioCheck ? "PASS" : "FAIL"}
            </span>
          </div>
        </div>
      )}

      {riskLimits && Object.keys(riskLimits).length > 0 && (
        <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3">
          <div className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">Risk Limits</div>
          <div className="space-y-1">
            {Object.entries(riskLimits).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between text-xs">
                <span className="text-[var(--text-muted)]">{k.replace(/_/g, " ")}</span>
                <span className="font-mono text-[var(--text-primary)]">{String(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {candidates && candidates.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">Recent Scan Candidates</div>
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {candidates.map((c, i) => (
              <div key={i} className="rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2 flex items-center justify-between">
                <div>
                  <span className="text-xs font-mono text-[var(--text-primary)]">{String(c.ticker ?? "")}</span>
                  <div className="text-[10px] text-[var(--text-muted)]">
                    {String(c.side ?? "")} · conf: {Number(c.confidence ?? 0).toFixed(2)} · edge: {Number(c.edge ?? 0).toFixed(3)}
                  </div>
                </div>
                <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
                  String(c.stage ?? "") === "executed" ? "bg-accent/10 text-accent" :
                  String(c.stage ?? "") === "risk_rejected" ? "bg-loss/10 text-loss" :
                  "bg-white/5 text-[var(--text-muted)]"
                }`}>{String(c.stage ?? "unknown")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!candidates && (
        <div className="space-y-1">
          {Object.entries(rejections)
            .filter(([k]) => !["portfolio_check", "risk_limits"].includes(k))
            .map(([key, val]) => (
              <div key={key} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                <span className="text-xs text-[var(--text-muted)]">{key.replace(/_/g, " ")}</span>
                <span className="text-xs font-mono text-[var(--text-primary)] truncate max-w-[200px]">
                  {typeof val === "object" ? JSON.stringify(val) : String(val)}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

/* ── Reusable Components ──────────────────────────────────────────────────── */

function InfoRow({ label, value, mono, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className={`text-xs font-medium tabular-nums ${mono ? "font-mono" : ""} ${color ?? "text-[var(--text-primary)]"}`}>{value}</span>
    </div>
  );
}

function SysRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/[0.04] last:border-0">
      <span className="text-sm text-[var(--text-muted)]">{label}</span>
      <span className="text-sm text-[var(--text-primary)] font-mono tabular-nums">{value}</span>
    </div>
  );
}

function StatusRow({ label, ok, icon }: { label: string; ok: boolean; icon: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 transition-colors hover:bg-white/[0.03]">
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${ok ? "bg-accent/10" : "bg-loss/10"}`}>{icon}</div>
        <span className="text-sm text-[var(--text-primary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <IconCircle size={6} className={ok ? "text-accent" : "text-loss"} />
        <span className={`text-xs font-medium ${ok ? "text-accent" : "text-loss"}`}>{ok ? "Online" : "Offline"}</span>
      </div>
    </div>
  );
}

function EditField({ label, value, suffix, onChange, hint }: {
  label: string; value: string; suffix?: string; onChange: (v: string) => void; hint?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-[var(--text-muted)] mb-1 font-medium">{label}</label>
      <div className="relative">
        <input
          type="number"
          value={value}
          onChange={e => onChange(e.target.value)}
          className="w-full rounded-lg bg-white/[0.03] border border-white/[0.08] px-3 py-2.5 text-sm font-mono
            text-[var(--text-primary)] focus:border-accent/40 focus:ring-1 focus:ring-accent/20 transition-all"
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)]">{suffix}</span>
        )}
      </div>
      {hint && <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
    </div>
  );
}

function PresetButton({ name, desc, icon, onClick }: {
  name: string; desc: string; icon: string; onClick: () => void;
}) {
  return (
    <button onClick={onClick}
      className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-4 text-left
        hover:bg-white/[0.05] hover:border-white/10 transition-all group">
      <div className="text-2xl mb-2">{icon}</div>
      <div className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-accent transition-colors">{name}</div>
      <div className="text-[10px] text-[var(--text-muted)] mt-0.5">{desc}</div>
    </button>
  );
}

function FeaturePhase({ name, count, desc, color }: { name: string; count: number; desc: string; color: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className={`h-2 w-2 rounded-full ${color} flex-shrink-0`} />
      <div className="flex-1 min-w-0">
        <span className="text-xs font-semibold text-[var(--text-primary)]">{name}</span>
        <span className="text-[10px] text-[var(--text-muted)] ml-2">{desc}</span>
      </div>
      <span className="text-xs font-mono text-accent tabular-nums">{count}</span>
    </div>
  );
}
