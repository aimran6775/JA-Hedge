"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { Card } from "@/components/ui/Card";
import {
  IconPlay,
  IconPause,
  IconStop,
  IconRefresh,
  IconSend,
  IconCircle,
  IconShield,
  IconBrain,
  IconSettings,
  IconBook,
  IconTrading,
  IconZap,
} from "@/components/ui/Icons";
import { api, type FrankensteinStatus, type RiskSnapshot } from "@/lib/api";
import { cn } from "@/lib/utils";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type SubTab = "settings" | "risk" | "trading" | "chat" | "guide";

/* ═══════════════════════════════════════════════════════════════════════
   CONTROL TAB — Configure, tune, and interact with the system
   ═══════════════════════════════════════════════════════════════════════ */
export function ControlTab() {
  const [sub, setSub] = useState<SubTab>("settings");
  const [frank, setFrank] = useState<FrankensteinStatus | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    const s = await api.frankenstein.status().catch(() => null);
    if (s) setFrank(s);
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 15000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  const brainAction = async (action: "awaken" | "sleep" | "pause" | "resume" | "retrain") => {
    try {
      setActionMsg(`${action}...`);
      if (action === "awaken") await api.frankenstein.awaken();
      else if (action === "sleep") await api.frankenstein.sleep();
      else if (action === "pause") await api.frankenstein.pause();
      else if (action === "resume") await api.frankenstein.resume();
      else if (action === "retrain") await api.frankenstein.retrain();
      setActionMsg(`${action} done`);
      fetchStatus();
      setTimeout(() => setActionMsg(null), 3000);
    } catch (e: unknown) {
      setActionMsg(e instanceof Error ? e.message : "Failed");
      setTimeout(() => setActionMsg(null), 5000);
    }
  };

  const brainAlive = frank?.is_alive ?? false;
  const brainTrading = frank?.is_trading ?? false;
  const brainPaused = frank?.is_paused ?? false;
  const brainLabel = !brainAlive ? "Offline" : brainPaused ? "Paused" : brainTrading ? "Trading" : "Idle";
  const brainColor = !brainAlive ? "text-[var(--text-muted)]" : brainPaused ? "text-[var(--warning)]" : brainTrading ? "text-accent" : "text-[var(--info)]";

  const SUB_TABS: { id: SubTab; label: string; icon: typeof IconSettings }[] = [
    { id: "settings", label: "Settings", icon: IconSettings },
    { id: "risk", label: "Risk", icon: IconShield },
    { id: "trading", label: "Trading", icon: IconTrading },
    { id: "chat", label: "Chat", icon: IconSend },
    { id: "guide", label: "Guide", icon: IconBook },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      {/* ── Brain controls ────────────────────────────────────────────── */}
      <div className="rounded-2xl glass p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <IconBrain size={16} className={brainColor} />
            <span className={`text-sm font-semibold ${brainColor}`}>{brainLabel}</span>
            {frank && (
              <span className="text-xs text-[var(--text-muted)]">
                / Gen {frank.generation} / {frank.uptime_human}
              </span>
            )}
          </div>
          {actionMsg && (
            <span className="text-xs text-[var(--text-muted)]">{actionMsg}</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <BrainButton label="Awaken" onClick={() => brainAction("awaken")} disabled={brainAlive} />
          <BrainButton label="Sleep" onClick={() => brainAction("sleep")} disabled={!brainAlive} variant="danger" />
          <BrainButton label="Pause" onClick={() => brainAction("pause")} disabled={!brainAlive || brainPaused} variant="warning" />
          <BrainButton label="Resume" onClick={() => brainAction("resume")} disabled={!brainPaused} />
          <BrainButton label="Retrain" onClick={() => brainAction("retrain")} disabled={!brainAlive} variant="info" />
        </div>
      </div>

      {/* ── Sub tabs ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-white/[0.06]">
        {SUB_TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setSub(t.id)}
              className={cn(
                "relative flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors",
                sub === t.id
                  ? "text-[var(--text-primary)]"
                  : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
              )}
            >
              <Icon size={14} />
              {t.label}
              {sub === t.id && (
                <div className="absolute bottom-0 left-1 right-1 h-[2px] rounded-full bg-accent" />
              )}
            </button>
          );
        })}
      </div>

      {sub === "settings" && <SettingsPanel frank={frank} onUpdate={fetchStatus} />}
      {sub === "risk" && <RiskPanel />}
      {sub === "trading" && <TradingPanel />}
      {sub === "chat" && <ChatPanel />}
      {sub === "guide" && <GuidePanel />}
    </div>
  );
}

/* ── Brain button ─────────────────────────────────────────────────────── */

function BrainButton({
  label,
  onClick,
  disabled,
  variant = "default",
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: "default" | "danger" | "warning" | "info";
}) {
  const colors = {
    default: "bg-accent/10 border-accent/20 text-accent hover:bg-accent/20",
    danger: "bg-[var(--danger)]/10 border-[var(--danger)]/20 text-[var(--danger)] hover:bg-[var(--danger)]/20",
    warning: "bg-[var(--warning)]/10 border-[var(--warning)]/20 text-[var(--warning)] hover:bg-[var(--warning)]/20",
    info: "bg-[var(--info)]/10 border-[var(--info)]/20 text-[var(--info)] hover:bg-[var(--info)]/20",
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed",
        colors[variant],
      )}
    >
      {label}
    </button>
  );
}

/* ── Settings Panel ───────────────────────────────────────────────────── */

function SettingsPanel({ frank, onUpdate }: { frank: FrankensteinStatus | null; onUpdate: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);

  useEffect(() => {
    api.frankenstein.getSettings().then((s) => setSettings(s as Record<string, unknown>)).catch(() => {});
  }, []);

  const params = frank?.strategy?.current_params;

  const save = async (updates: Record<string, unknown>) => {
    setSaving(true);
    try {
      await api.frankenstein.updateSettings(updates);
      setSaveMsg("Saved");
      onUpdate();
      setTimeout(() => setSaveMsg(null), 2000);
    } catch {
      setSaveMsg("Failed to save");
      setTimeout(() => setSaveMsg(null), 3000);
    }
    setSaving(false);
  };

  const runDiagnostic = async () => {
    setDiagLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/frankenstein/debug-scan`);
      if (res.ok) setDiagnostics(await res.json());
    } catch { /* ignore */ }
    setDiagLoading(false);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Strategy params */}
        <Card title="Strategy Parameters" action={
          saveMsg ? <span className="text-xs text-accent">{saveMsg}</span> : null
        }>
          {params ? (
            <div className="space-y-3">
              <ParamSlider label="Min Confidence" value={params.min_confidence} min={0.3} max={0.95} step={0.05} unit="%" multiply={100}
                onSave={(v) => save({ strategy: { min_confidence: v } })} />
              <ParamSlider label="Min Edge" value={params.min_edge} min={0.005} max={0.10} step={0.005} unit="c" multiply={100}
                onSave={(v) => save({ strategy: { min_edge: v } })} />
              <ParamSlider label="Kelly Fraction" value={params.kelly_fraction} min={0.05} max={0.5} step={0.05}
                onSave={(v) => save({ strategy: { kelly_fraction: v } })} />
              <ParamSlider label="Max Position Size" value={params.max_position_size} min={1} max={50} step={1}
                onSave={(v) => save({ strategy: { max_position_size: v } })} />
              <ParamSlider label="Max Spread" value={params.max_spread_cents} min={1} max={20} step={1} unit="c"
                onSave={(v) => save({ strategy: { max_spread_cents: v } })} />
              <ParamSlider label="Max Daily Loss" value={params.max_daily_loss} min={5} max={200} step={5} unit="$"
                onSave={(v) => save({ strategy: { max_daily_loss: v } })} />
              <ParamSlider label="Aggression" value={params.aggression} min={0.1} max={1.0} step={0.1}
                onSave={(v) => save({ strategy: { aggression: v } })} />
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-[var(--text-muted)]">Loading...</div>
          )}
        </Card>

        {/* Brain config + sim */}
        <div className="space-y-4">
          <Card title="Brain Configuration">
            {frank ? (
              <div className="space-y-3">
                <ParamSlider label="Scan Interval" value={frank.strategy?.current_params?.scan_interval ?? 30} min={10} max={300} step={10} unit="s"
                  onSave={(v) => save({ brain: { scan_interval: v } })} />
                <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2.5">
                  <span className="text-xs text-[var(--text-muted)]">Sports Only</span>
                  <button
                    onClick={() => save({ brain: { sports_only: !frank.sports_only_mode } })}
                    className={cn(
                      "rounded px-3 py-1 text-[10px] font-semibold uppercase border transition-colors",
                      frank.sports_only_mode
                        ? "bg-accent/10 text-accent border-accent/20"
                        : "bg-white/[0.04] text-[var(--text-muted)] border-white/[0.08]",
                    )}
                  >
                    {frank.sports_only_mode ? "On" : "Off"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">Not connected</div>
            )}
          </Card>

          <Card title="Simulation">
            <div className="space-y-3">
              <div className="text-xs text-[var(--text-muted)]">
                Paper trading mode. No real funds are used.
              </div>
              <button
                onClick={async () => {
                  if (!confirm("Reset simulation? This clears all paper trading data.")) return;
                  try {
                    await api.frankenstein.resetSimulation({ clear_memory: true, restart_brain: false });
                    onUpdate();
                  } catch { /* ignore */ }
                }}
                className="rounded-lg border border-[var(--danger)]/20 bg-[var(--danger)]/5 px-4 py-2 text-xs font-medium text-[var(--danger)] hover:bg-[var(--danger)]/10 transition-colors"
              >
                Reset Simulation
              </button>
            </div>
          </Card>
        </div>
      </div>

      {/* Diagnostics */}
      <Card title="Diagnostics">
        <div className="space-y-3">
          <button
            onClick={runDiagnostic}
            disabled={diagLoading}
            className="rounded-lg bg-[var(--info)]/10 border border-[var(--info)]/20 px-4 py-1.5 text-xs font-medium text-[var(--info)] hover:bg-[var(--info)]/20 transition-colors disabled:opacity-50"
          >
            {diagLoading ? "Running..." : "Run Scan Diagnostic"}
          </button>
          {diagnostics && (
            <div className="space-y-1.5">
              {((diagnostics.steps ?? []) as Array<Record<string, unknown>>).map((step, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
                  <span className="text-xs text-[var(--text-secondary)] font-mono">{String(step.step)}</span>
                  <span className="text-xs tabular-nums text-[var(--text-muted)]">
                    {step.error ? `Error: ${step.error}` : JSON.stringify(
                      Object.fromEntries(Object.entries(step).filter(([k]) => k !== "step")),
                    ).substring(0, 80)}
                  </span>
                </div>
              ))}
              {diagnostics.exit != null && (
                <div className="text-xs text-[var(--text-muted)]">{`Exit: ${String(diagnostics.exit)}`}</div>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

/* ── Param Slider ─────────────────────────────────────────────────────── */

function ParamSlider({
  label,
  value,
  min,
  max,
  step,
  unit,
  multiply,
  onSave,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  multiply?: number;
  onSave: (v: number) => void;
}) {
  const [local, setLocal] = useState(value);
  const changed = Math.abs(local - value) > step / 10;

  useEffect(() => { setLocal(value); }, [value]);

  const displayValue = multiply ? (local * multiply).toFixed(0) : local.toFixed(step < 1 ? 2 : 0);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[var(--text-muted)]">{label}</span>
        <div className="flex items-center gap-2">
          <span className="tabular-nums text-[var(--text-primary)]">
            {displayValue}{unit ?? ""}
          </span>
          {changed && (
            <button
              onClick={() => onSave(local)}
              className="rounded bg-accent/10 border border-accent/20 px-1.5 py-0.5 text-[9px] font-medium text-accent"
            >
              Save
            </button>
          )}
        </div>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(e) => setLocal(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full bg-white/[0.08] appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-accent"
      />
    </div>
  );
}

/* ── Risk Panel ───────────────────────────────────────────────────────── */

function RiskPanel() {
  const [risk, setRisk] = useState<RiskSnapshot | null>(null);
  const [toggling, setToggling] = useState(false);

  const fetchRisk = useCallback(async () => {
    const r = await api.risk.snapshot().catch(() => null);
    if (r) setRisk(r);
  }, []);

  useEffect(() => {
    fetchRisk();
    const iv = setInterval(fetchRisk, 10000);
    return () => clearInterval(iv);
  }, [fetchRisk]);

  const toggleKill = async () => {
    if (toggling) return;
    const activate = !risk?.kill_switch_active;
    if (activate && !confirm("Activate kill switch? This stops all trading immediately.")) return;
    setToggling(true);
    try {
      await api.risk.killSwitch(activate);
      fetchRisk();
    } catch { /* ignore */ }
    setToggling(false);
  };

  return (
    <div className="space-y-4">
      <Card title="Risk Snapshot">
        {risk ? (
          <div className="space-y-2">
            <InfoRow label="Total Exposure" value={`$${(risk.total_exposure / 100).toFixed(2)}`} />
            <InfoRow label="Daily P&L" value={`$${risk.daily_pnl.toFixed(2)}`} />
            <InfoRow label="Daily Trades" value={String(risk.daily_trades)} />
            <InfoRow label="Positions" value={String(risk.position_count)} />
            <InfoRow label="Open Orders" value={String(risk.open_orders)} />
          </div>
        ) : (
          <div className="py-6 text-center text-sm text-[var(--text-muted)]">Loading...</div>
        )}
      </Card>

      <Card title="Kill Switch">
        <div className="space-y-3">
          <div className="text-xs text-[var(--text-muted)]">
            Immediately halt all trading operations. All pending orders will be cancelled.
          </div>
          <button
            onClick={toggleKill}
            disabled={toggling}
            className={cn(
              "rounded-lg border px-4 py-2.5 text-sm font-semibold transition-all w-full",
              risk?.kill_switch_active
                ? "border-accent/20 bg-accent/10 text-accent hover:bg-accent/20"
                : "border-[var(--danger)]/30 bg-[var(--danger)]/10 text-[var(--danger)] hover:bg-[var(--danger)]/20",
              toggling && "opacity-50",
            )}
          >
            {risk?.kill_switch_active ? "Deactivate Kill Switch" : "Activate Kill Switch"}
          </button>
        </div>
      </Card>
    </div>
  );
}

/* ── Trading Panel ────────────────────────────────────────────────────── */

function TradingPanel() {
  const [search, setSearch] = useState("");
  const [markets, setMarkets] = useState<Array<{ ticker: string; title: string | null; yes_bid: number | null; yes_ask: number | null }>>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [price, setPrice] = useState(50);
  const [qty, setQty] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const searchMarkets = useCallback(async () => {
    if (search.length < 2) { setMarkets([]); return; }
    try {
      const result = await api.markets.list({ search, limit: 10 });
      setMarkets((result.markets ?? []).map((m) => ({
        ticker: m.ticker,
        title: m.title,
        yes_bid: m.yes_bid,
        yes_ask: m.yes_ask,
      })));
    } catch { setMarkets([]); }
  }, [search]);

  useEffect(() => {
    const t = setTimeout(searchMarkets, 300);
    return () => clearTimeout(t);
  }, [searchMarkets]);

  const submit = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const res = await api.orders.create({
        ticker: selected,
        side,
        action: "buy",
        order_type: "limit",
        count: qty,
        price_cents: price,
      });
      setResult(`Order placed: ${(res as Record<string, unknown>).order_id ?? "ok"}`);
    } catch (e: unknown) {
      setResult(e instanceof Error ? e.message : "Order failed");
    }
    setSubmitting(false);
    setTimeout(() => setResult(null), 5000);
  };

  const cost = ((price * qty) / 100).toFixed(2);

  return (
    <div className="space-y-4">
      <Card title="Place Order">
        <div className="space-y-3">
          {/* Market search */}
          <div>
            <label className="text-xs text-[var(--text-muted)] mb-1 block">Market</label>
            <input
              type="text"
              placeholder="Search markets..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); setSelected(null); }}
              className="w-full rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)]"
            />
            {markets.length > 0 && !selected && (
              <div className="mt-1 rounded-lg border border-white/[0.08] bg-[var(--bg-secondary)] max-h-[200px] overflow-y-auto">
                {markets.map((m) => (
                  <button
                    key={m.ticker}
                    onClick={() => { setSelected(m.ticker); setSearch(m.title ?? m.ticker); setMarkets([]); }}
                    className="w-full text-left px-3 py-2 text-xs hover:bg-white/[0.04] transition-colors border-b border-white/[0.04] last:border-0"
                  >
                    <div className="text-[var(--text-primary)]">{m.title ?? m.ticker}</div>
                    <div className="text-[10px] text-[var(--text-muted)]">{m.ticker}</div>
                  </button>
                ))}
              </div>
            )}
            {selected && (
              <div className="mt-1 text-[10px] text-accent font-mono">{selected}</div>
            )}
          </div>

          {/* Side */}
          <div>
            <label className="text-xs text-[var(--text-muted)] mb-1 block">Side</label>
            <div className="flex gap-2">
              <button
                onClick={() => setSide("yes")}
                className={cn(
                  "flex-1 rounded-lg border py-2 text-xs font-semibold transition-colors",
                  side === "yes"
                    ? "bg-accent/10 border-accent/20 text-accent"
                    : "bg-white/[0.02] border-white/[0.06] text-[var(--text-muted)]",
                )}
              >
                YES
              </button>
              <button
                onClick={() => setSide("no")}
                className={cn(
                  "flex-1 rounded-lg border py-2 text-xs font-semibold transition-colors",
                  side === "no"
                    ? "bg-[var(--danger)]/10 border-[var(--danger)]/20 text-[var(--danger)]"
                    : "bg-white/[0.02] border-white/[0.06] text-[var(--text-muted)]",
                )}
              >
                NO
              </button>
            </div>
          </div>

          {/* Price + Qty */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">Price (cents)</label>
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(parseInt(e.target.value) || 0)}
                className="w-full rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-[var(--text-primary)] tabular-nums"
              />
            </div>
            <div>
              <label className="text-xs text-[var(--text-muted)] mb-1 block">Quantity</label>
              <input
                type="number"
                value={qty}
                onChange={(e) => setQty(parseInt(e.target.value) || 0)}
                className="w-full rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-[var(--text-primary)] tabular-nums"
              />
            </div>
          </div>

          {/* Cost preview */}
          <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
            <span className="text-xs text-[var(--text-muted)]">Estimated Cost</span>
            <span className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">${cost}</span>
          </div>

          {/* Submit */}
          <button
            onClick={submit}
            disabled={!selected || submitting}
            className="w-full rounded-lg bg-accent/10 border border-accent/20 py-2.5 text-sm font-medium text-accent hover:bg-accent/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {submitting ? "Submitting..." : "Place Order"}
          </button>

          {result && (
            <div className="text-xs text-center text-[var(--text-muted)]">{result}</div>
          )}
        </div>
      </Card>
    </div>
  );
}

/* ── Chat Panel ───────────────────────────────────────────────────────── */

function ChatPanel() {
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.frankenstein.chatHistory().then((h) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const history = (h as any)?.messages ?? (h as any)?.history ?? [];
      if (Array.isArray(history)) setMessages(history);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  const send = async () => {
    if (!input.trim() || sending) return;
    const msg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: msg }]);
    setSending(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res = await api.frankenstein.chat(msg) as any;
      const reply = res?.response ?? res?.message ?? res?.content ?? "No response";
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (e: unknown) {
      setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${e instanceof Error ? e.message : "Failed"}` }]);
    }
    setSending(false);
  };

  return (
    <Card title="Chat with Brain">
      <div className="space-y-3">
        <div className="text-xs text-[var(--text-muted)]">
          Commands: /status, /awaken, /sleep, /retrain
        </div>

        {/* Messages */}
        <div ref={scrollRef} className="max-h-[400px] overflow-y-auto space-y-2">
          {messages.length === 0 && (
            <div className="py-6 text-center text-sm text-[var(--text-muted)]">No messages yet</div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cn(
              "rounded-lg px-3 py-2 text-sm",
              m.role === "user"
                ? "bg-accent/5 border border-accent/10 text-[var(--text-primary)]"
                : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-secondary)]",
            )}>
              <div className="text-[10px] text-[var(--text-muted)] mb-1 uppercase">
                {m.role === "user" ? "You" : "Brain"}
              </div>
              <div className="whitespace-pre-wrap text-xs">{m.content}</div>
            </div>
          ))}
          {sending && (
            <div className="text-xs text-[var(--text-muted)] animate-pulse">Thinking...</div>
          )}
        </div>

        {/* Input */}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="Type a message..."
            className="flex-1 rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)]"
          />
          <button
            onClick={send}
            disabled={sending || !input.trim()}
            className="rounded-lg bg-accent/10 border border-accent/20 px-3 py-2 text-accent hover:bg-accent/20 transition-colors disabled:opacity-30"
          >
            <IconSend size={14} />
          </button>
        </div>
      </div>
    </Card>
  );
}

/* ── Guide Panel ──────────────────────────────────────────────────────── */

function GuidePanel() {
  const [expanded, setExpanded] = useState<string | null>(null);

  const sections = [
    {
      id: "overview",
      title: "What is JA Hedge?",
      content: "JA Hedge is an AI-powered trading system for Kalshi prediction markets. It uses machine learning (XGBoost) to identify profitable opportunities and places maker orders to minimize fees. The system runs autonomously, scanning markets, evaluating probabilities, and executing trades when it finds a statistical edge.",
    },
    {
      id: "kalshi",
      title: "What is Kalshi?",
      content: "Kalshi is a regulated prediction market exchange where you can trade on the outcomes of real-world events. Markets are binary (Yes/No) and settle at either $1.00 (outcome happened) or $0.00 (didn't happen). You profit by buying contracts below their true probability and selling/holding to settlement.",
    },
    {
      id: "paper",
      title: "Paper Trading",
      content: "Paper trading simulates real trades without using real money. The system tracks a virtual balance, records all trades, and computes performance metrics. This lets you evaluate the strategy before committing real capital. Paper trading is enabled by default.",
    },
    {
      id: "brain",
      title: "The Brain (Frankenstein)",
      content: "Frankenstein is the AI orchestrator. It continuously scans markets, computes features, runs predictions through the XGBoost model, evaluates confidence through multiple gates (spread, volume, edge, uncertainty), and executes trades via maker orders. It learns from outcomes and periodically retrains the model.",
    },
    {
      id: "maker",
      title: "Maker Orders",
      content: "Maker orders (limit orders that add liquidity) have 0 cents in fees on Kalshi, compared to ~14 cents for taker orders. This fee advantage is the primary edge. The system exclusively places maker orders, which means orders may not fill immediately but save significantly on costs.",
    },
    {
      id: "tabs",
      title: "Dashboard Tabs",
      content: "Live: Real-time view of positions, trades, P&L, and brain status. Analytics: Historical performance, P&L curves, category breakdowns, and model metrics. Markets: Trade candidates, strategy signals, sports data, and alerts. Control: Brain controls, parameter tuning, manual trading, and chat.",
    },
    {
      id: "risk",
      title: "Risk Management",
      content: "The system has multiple risk controls: position limits, exposure caps, daily loss limits, and a kill switch. The kill switch immediately halts all trading. Risk parameters can be adjusted in the Control > Settings tab. The system also monitors drawdown and will auto-pause if losses exceed thresholds.",
    },
    {
      id: "faq",
      title: "FAQ",
      content: "Q: Is this real money? A: Only if paper trading is disabled. Default is paper mode.\n\nQ: How often does it trade? A: It scans every 30 seconds by default and trades when it finds opportunities meeting all criteria.\n\nQ: What's the expected return? A: The maker fee advantage provides ~3-5 cents of edge per trade. With proper risk management and 50%+ win rate, the system targets consistent small profits.",
    },
  ];

  return (
    <div className="space-y-2">
      {sections.map((s) => (
        <div key={s.id} className="rounded-lg border border-white/[0.04] overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === s.id ? null : s.id)}
            className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
          >
            <span className="text-sm font-medium text-[var(--text-primary)]">{s.title}</span>
            <span className="text-xs text-[var(--text-muted)]">{expanded === s.id ? "-" : "+"}</span>
          </button>
          {expanded === s.id && (
            <div className="px-4 pb-3 text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
              {s.content}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Small components ─────────────────────────────────────────────────── */

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className="text-xs font-medium tabular-nums text-[var(--text-primary)]">{value}</span>
    </div>
  );
}
