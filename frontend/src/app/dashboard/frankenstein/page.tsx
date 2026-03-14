"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconBrain, IconCircle, IconZap, IconTarget, IconShield, IconTrendUp,
  IconTrendDown, IconRefresh, IconPlay, IconPause, IconStop, IconSend,
  IconRocket, IconMarkets, IconSearch,
} from "@/components/ui/Icons";
import { api, type FrankensteinStatus, type FrankensteinTrade, type Balance, type Position } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function pnlColor(v: number) {
  return v > 0 ? "text-accent" : v < 0 ? "text-loss" : "text-[var(--text-muted)]";
}

function pnlSign(v: number) {
  return v > 0 ? `+$${v.toFixed(2)}` : v < 0 ? `-$${Math.abs(v).toFixed(2)}` : "$0.00";
}

function StatusDot({ alive, trading, paused }: { alive: boolean; trading: boolean; paused: boolean }) {
  const color = !alive ? "bg-[var(--text-muted)]" : paused ? "bg-[var(--warning)]" : trading ? "bg-accent" : "bg-loss";
  const label = !alive ? "Offline" : paused ? "Paused" : trading ? "Live Trading" : "Idle";
  return (
    <div className="flex items-center gap-2">
      <span className="relative flex h-2.5 w-2.5">
        {(alive && trading && !paused) && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${color} opacity-50`} />}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${color}`} />
      </span>
      <span className="text-xs font-semibold tracking-wide uppercase">{label}</span>
    </div>
  );
}

/* ── Inline Markdown (for chat) ──────────────────────────────────────────── */
function processInline(text: string): string {
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong class="text-[var(--text-primary)] font-semibold">$1</strong>');
  text = text.replace(/`([^`]+)`/g, '<code class="rounded bg-white/[0.06] px-1.5 py-0.5 text-xs font-mono text-accent">$1</code>');
  return text;
}
function renderMarkdown(text: string): string {
  const lines = text.split("\n");
  let html = "", inList = false;
  for (const line of lines) {
    const t = line.trim();
    if (t.startsWith("### ")) { if (inList) { html += "</ul>"; inList = false; } html += `<h3 class="text-sm font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(t.slice(4))}</h3>`; }
    else if (t.startsWith("## ")) { if (inList) { html += "</ul>"; inList = false; } html += `<h2 class="text-base font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(t.slice(3))}</h2>`; }
    else if (t.startsWith("# ")) { if (inList) { html += "</ul>"; inList = false; } html += `<h1 class="text-lg font-bold text-[var(--text-primary)] mt-3 mb-1.5">${processInline(t.slice(2))}</h1>`; }
    else if (/^[-*] /.test(t)) { if (!inList) { html += '<ul class="space-y-1 my-1.5">'; inList = true; } html += `<li class="flex items-start gap-2 text-sm text-[var(--text-secondary)]"><span class="mt-1.5 h-1 w-1 rounded-full bg-accent/60 flex-shrink-0"></span><span>${processInline(t.slice(2))}</span></li>`; }
    else if (t.startsWith("---")) { if (inList) { html += "</ul>"; inList = false; } html += '<hr class="border-white/[0.06] my-2" />'; }
    else if (t === "") { if (inList) { html += "</ul>"; inList = false; } html += "<br />"; }
    else { if (inList) { html += "</ul>"; inList = false; } html += `<p class="text-sm text-[var(--text-secondary)] leading-relaxed">${processInline(t)}</p>`; }
  }
  if (inList) html += "</ul>";
  return html;
}

/* ── Chat Message Type ────────────────────────────────────────────────────── */
interface ChatMessage { role: "user" | "assistant"; content: string; timestamp: string; }

/* ════════════════════════════════════════════════════════════════════════════
   MAIN PAGE — Frankenstein AI Command Center
   ════════════════════════════════════════════════════════════════════════════ */
export default function FrankensteinPage() {
  const [status, setStatus] = useState<FrankensteinStatus | null>(null);
  const [trades, setTrades] = useState<FrankensteinTrade[]>([]);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<"overview" | "trades" | "model" | "chat">("overview");

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  /* ── Data fetching ─────────────────────────────────────────────────────── */
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [s, t, b, p] = await Promise.all([
        api.frankenstein.status().catch(() => null),
        api.frankenstein.recentTrades(30).catch(() => []),
        api.portfolio.balance().catch(() => null),
        api.portfolio.positions().catch(() => []),
      ]);
      if (s) setStatus(s);
      setTrades(t);
      if (b) setBalance(b);
      setPositions(p);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const iv = setInterval(refresh, 12000);
    return () => clearInterval(iv);
  }, [refresh]);

  // Chat scroll
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  /* ── Controls ──────────────────────────────────────────────────────────── */
  const doAction = async (fn: () => Promise<unknown>, label: string) => {
    try {
      await fn();
      setActionMsg(`✓ ${label}`);
      setTimeout(() => setActionMsg(null), 3000);
      refresh();
    } catch (e: unknown) {
      setActionMsg(`✗ ${label}: ${e instanceof Error ? e.message : "failed"}`);
      setTimeout(() => setActionMsg(null), 5000);
    }
  };

  const sendChat = useCallback(async (text: string) => {
    if (!text.trim() || sending) return;
    const userMsg: ChatMessage = { role: "user", content: text.trim(), timestamp: new Date().toISOString() };
    setMessages(prev => [...prev, userMsg]);
    setChatInput("");
    setSending(true);
    try {
      const body: Record<string, unknown> = { message: text.trim() };
      if (sessionId) body.session_id = sessionId;
      const res = await fetch(`${API_BASE}/api/frankenstein/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.session_id) setSessionId(data.session_id);
      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.content || data.response || data.message || "No response received",
        timestamp: new Date().toISOString(),
      }]);
    } catch (e: unknown) {
      setMessages(prev => [...prev, {
        role: "assistant",
        content: `Connection error: ${e instanceof Error ? e.message : "Unknown"}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setSending(false);
    }
  }, [sending, sessionId]);

  /* ── Derived values ────────────────────────────────────────────────────── */
  const s = status;
  const snap = s?.performance?.snapshot;
  const mem = s?.memory;
  const learn = s?.learner;
  const params = s?.strategy?.current_params;
  const debug = s?.last_scan_debug;
  const realTrades = trades.filter(t => !t.model_version?.startsWith("bootstrap"));

  return (
    <div className="space-y-5 animate-fade-in">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-4">
          <div className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-accent/20 to-accent/5 border border-accent/20">
            <IconBrain size={24} className="text-accent" />
            {s?.is_alive && <div className="absolute inset-0 rounded-2xl animate-pulse-glow" />}
          </div>
          <div>
            <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Frankenstein AI</h1>
            <div className="flex items-center gap-3 mt-0.5">
              {s ? <StatusDot alive={s.is_alive} trading={s.is_trading} paused={s.is_paused} /> : <span className="text-xs text-[var(--text-muted)]">Connecting...</span>}
              {s && <span className="text-xs text-[var(--text-muted)]">v{s.version} · Gen {s.generation} · Up {s.uptime_human}</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {actionMsg && <span className="text-xs text-accent mr-2">{actionMsg}</span>}
          <button onClick={refresh} disabled={loading}
            className="glass rounded-xl px-3 py-2 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all">
            <IconRefresh size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── MASTER CONTROL PANEL ───────────────────────────────────────────── */}
      <div className="glass rounded-2xl p-4 border border-white/[0.06]">
        <div className="flex items-center justify-between flex-wrap gap-4">
          {/* Big Start/Stop Toggle */}
          <div className="flex items-center gap-4">
            {s && !s.is_alive ? (
              <button
                onClick={() => doAction(() => api.frankenstein.awaken(), "Awoken — Trading 24/7")}
                className="relative overflow-hidden rounded-2xl px-8 py-4 text-base font-bold text-white
                  bg-gradient-to-r from-green-600 to-emerald-500 hover:from-green-500 hover:to-emerald-400
                  shadow-lg shadow-green-500/25 hover:shadow-green-500/40
                  transition-all duration-300 transform hover:scale-[1.02] active:scale-[0.98]
                  flex items-center gap-3 min-w-[180px] justify-center"
              >
                <IconPlay size={22} />
                <span>START</span>
                <div className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/10 to-white/0 animate-shimmer" />
              </button>
            ) : s?.is_alive ? (
              <button
                onClick={() => doAction(() => api.frankenstein.sleep(), "Sleeping — Trading Stopped")}
                className="relative overflow-hidden rounded-2xl px-8 py-4 text-base font-bold text-white
                  bg-gradient-to-r from-red-600 to-rose-500 hover:from-red-500 hover:to-rose-400
                  shadow-lg shadow-red-500/25 hover:shadow-red-500/40
                  transition-all duration-300 transform hover:scale-[1.02] active:scale-[0.98]
                  flex items-center gap-3 min-w-[180px] justify-center"
              >
                <IconStop size={22} />
                <span>STOP</span>
              </button>
            ) : (
              <div className="rounded-2xl px-8 py-4 text-base font-bold text-[var(--text-muted)] glass flex items-center gap-3">
                <IconCircle size={22} />
                <span>Loading...</span>
              </div>
            )}

            {/* Status indicator */}
            <div className="flex flex-col">
              <span className={`text-sm font-bold ${s?.is_alive ? (s.is_paused ? "text-[var(--warning)]" : "text-accent") : "text-[var(--text-muted)]"}`}>
                {s?.is_alive ? (s.is_paused ? "⏸ PAUSED" : "🟢 RUNNING 24/7") : "⏹ STOPPED"}
              </span>
              <span className="text-xs text-[var(--text-muted)]">
                {s?.is_alive ? `${s.total_scans} scans · ${s.total_trades_executed} trades` : "Click START to begin trading"}
              </span>
            </div>
          </div>

          {/* Secondary Controls */}
          <div className="flex items-center gap-2">
            {s?.is_alive && !s.is_paused && (
              <button onClick={() => doAction(() => api.frankenstein.pause(), "Paused")}
                className="glass rounded-xl px-4 py-2.5 text-xs font-semibold text-[var(--warning)] hover:bg-[var(--warning)]/10
                  border border-[var(--warning)]/20 transition-all flex items-center gap-2">
                <IconPause size={14} /> Pause
              </button>
            )}
            {s?.is_paused && (
              <button onClick={() => doAction(() => api.frankenstein.resume(), "Resumed")}
                className="glass rounded-xl px-4 py-2.5 text-xs font-semibold text-accent hover:bg-accent/10
                  border border-accent/20 transition-all flex items-center gap-2">
                <IconPlay size={14} /> Resume
              </button>
            )}
            <button onClick={() => doAction(() => api.frankenstein.retrain(), "Retrained")}
              className="glass rounded-xl px-4 py-2.5 text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)]
                border border-white/[0.06] transition-all flex items-center gap-2">
              <IconRocket size={14} /> Retrain Model
            </button>
          </div>
        </div>
      </div>

      {/* ── Top Stats Row ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Balance" value={balance ? `$${balance.balance_dollars}` : "—"} icon={<IconShield size={16} />} />
        <StatCard label="Trades" value={s ? `${s.total_trades_executed}` : "—"} suffix={s ? ` / ${s.total_trades_rejected} rej` : ""} icon={<IconZap size={16} />} />
        <StatCard label="Signals" value={s ? `${s.total_signals}` : "—"} icon={<IconMarkets size={16} />} />
        <StatCard label="Positions" value={`${positions.length}`} suffix=" open" icon={<IconTarget size={16} />} />
        <StatCard label="P&L" value={snap ? pnlSign(snap.total_pnl) : "—"} icon={<IconTrendUp size={16} />} />
        <StatCard label="Win Rate" value={snap && snap.real_trades > 0 ? `${(snap.win_rate * 100).toFixed(0)}%` : "—"} suffix={snap ? ` (${snap.real_trades} resolved)` : ""} icon={<IconTarget size={16} />} />
      </div>

      {/* ── Tab Navigation ─────────────────────────────────────────────────── */}
      <div className="flex gap-1 rounded-2xl glass p-1">
        {(["overview", "trades", "model", "chat"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-semibold uppercase tracking-wider transition-all
              ${tab === t ? "bg-accent/10 text-accent border border-accent/20" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)] border border-transparent"}`}>
            {t === "overview" ? "🧠 Overview" : t === "trades" ? "📊 Trades" : t === "model" ? "🧬 Model" : "💬 Chat"}
          </button>
        ))}
      </div>

      {/* ════════════════ TAB: OVERVIEW ═══════════════════════════════════════ */}
      {tab === "overview" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Brain State */}
          <Card title="Brain State" glow={s?.is_alive && s?.is_trading && !s?.is_paused}>
            <div className="space-y-2">
              <StateRow label="Status" value={s?.is_alive ? (s.is_paused ? "⏸ Paused" : s.is_trading ? "🟢 Live Trading" : "🔵 Idle") : "🔴 Offline"} />
              {s?.pause_reason && <StateRow label="Pause Reason" value={s.pause_reason} warn />}
              <StateRow label="Generation" value={`Gen ${s?.generation ?? 0}`} />
              <StateRow label="Model" value={s?.version ?? "—"} mono />
              <StateRow label="Uptime" value={s?.uptime_human ?? "—"} />
              <StateRow label="Scans" value={`${s?.total_scans ?? 0}`} />
              <StateRow label="Last Scan" value={s?.last_scan_ms ? `${s.last_scan_ms}ms` : "—"} />
              <StateRow label="Exchange" value={s?.exchange_session ?? "—"} />
              <StateRow label="Liquidity" value={s ? `${(s.liquidity_factor * 100).toFixed(0)}%` : "—"} />
              <StateRow label="Sports Only" value={s?.sports_only_mode ? "Yes" : "No"} />
            </div>
          </Card>

          {/* Performance Snapshot */}
          <Card title="Performance">
            <div className="space-y-2">
              <StateRow label="Total P&L" value={snap ? pnlSign(snap.total_pnl) : "—"} color={snap ? pnlColor(snap.total_pnl) : undefined} />
              <StateRow label="Daily P&L" value={snap ? pnlSign(snap.daily_pnl) : "—"} color={snap ? pnlColor(snap.daily_pnl) : undefined} />
              <StateRow label="Win Rate" value={snap && snap.real_trades > 0 ? `${(snap.win_rate * 100).toFixed(1)}%` : "Pending"} />
              <StateRow label="Accuracy" value={snap && snap.real_trades > 0 ? `${(snap.prediction_accuracy * 100).toFixed(1)}%` : "Pending"} />
              <StateRow label="Sharpe" value={snap ? snap.sharpe_ratio.toFixed(2) : "—"} />
              <StateRow label="Max Drawdown" value={snap ? `$${snap.max_drawdown.toFixed(2)}` : "—"} />
              <StateRow label="Profit Factor" value={snap ? snap.profit_factor.toFixed(2) : "—"} />
              <StateRow label="Avg Win" value={snap ? `$${snap.avg_win.toFixed(2)}` : "—"} />
              <StateRow label="Avg Loss" value={snap ? `$${snap.avg_loss.toFixed(2)}` : "—"} />
              <StateRow label="Regime" value={snap?.regime ?? "unknown"} />
              <StateRow label="Real Trades" value={`${snap?.real_trades ?? 0} resolved`} />
            </div>
          </Card>

          {/* Last Scan Debug */}
          <Card title="Last Scan Pipeline">
            {debug?.candidates != null ? (
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <FunnelRow label="Markets Scanned" value={debug.candidates ?? 0} total={debug.candidates ?? 1} color="bg-blue-400" />
                  <FunnelRow label="Trade Candidates" value={debug.trade_candidates ?? 0} total={debug.candidates ?? 1} color="bg-violet-400" />
                  <FunnelRow label="Executed" value={debug.exec_successes ?? 0} total={debug.candidates ?? 1} color="bg-accent" />
                  <FunnelRow label="Exec Rejected" value={debug.exec_rejections ?? 0} total={debug.candidates ?? 1} color="bg-[var(--warning)]" />
                  <FunnelRow label="Portfolio Rejected" value={debug.portfolio_rejections ?? 0} total={debug.candidates ?? 1} color="bg-loss" />
                </div>
                {debug.top_candidates && debug.top_candidates.length > 0 && (
                  <div className="mt-3 space-y-1">
                    <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-1.5">Recent Candidates</div>
                    {debug.top_candidates.map((c, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                        <StageIcon stage={c.stage} />
                        <div className="flex-1 min-w-0">
                          <div className="text-[11px] font-mono text-[var(--text-primary)] truncate">{c.ticker}</div>
                          <div className="text-[10px] text-[var(--text-muted)] truncate">{c.error || c.order_id || c.stage}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">No scan data yet</div>
            )}
          </Card>

          {/* Open Positions */}
          <Card title="Open Positions" action={<span className="text-xs text-[var(--text-muted)]">{positions.length} active</span>}>
            {positions.length > 0 ? (
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                {positions.map(p => (
                  <div key={p.ticker} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5 hover:bg-white/[0.04] transition-colors">
                    <div className="min-w-0">
                      <div className="text-xs font-mono font-semibold text-[var(--text-primary)] truncate">{p.ticker}</div>
                      <div className="text-[10px] text-[var(--text-muted)]">{p.position > 0 ? "YES" : "NO"} × {Math.abs(p.position)}</div>
                    </div>
                    <div className="text-right flex-shrink-0">
                      {p.market_exposure_dollars && <div className="text-xs font-medium text-[var(--text-primary)] tabular-nums">${p.market_exposure_dollars}</div>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-[var(--text-muted)]">No positions</div>
            )}
          </Card>

          {/* Memory Stats */}
          <Card title="Trade Memory">
            <div className="space-y-2">
              <StateRow label="Recorded" value={`${mem?.total_recorded ?? 0}`} />
              <StateRow label="Resolved" value={`${mem?.total_resolved ?? 0}`} />
              <StateRow label="Pending" value={`${mem?.pending ?? 0}`} />
              {mem?.outcomes && (
                <>
                  <div className="h-px bg-white/[0.06] my-1" />
                  <StateRow label="Wins" value={`${mem.outcomes.win ?? 0}`} color="text-accent" />
                  <StateRow label="Losses" value={`${mem.outcomes.loss ?? 0}`} color="text-loss" />
                  <StateRow label="Breakeven" value={`${mem.outcomes.breakeven ?? 0}`} />
                </>
              )}
              <div className="h-px bg-white/[0.06] my-1" />
              <StateRow label="Memory Win Rate" value={mem ? `${mem.win_rate}%` : "—"} />
              <StateRow label="Memory P&L" value={mem ? `$${mem.total_pnl}` : "—"} color={mem ? pnlColor(mem.total_pnl) : undefined} />
            </div>
          </Card>

          {/* Strategy Parameters */}
          <Card title="Strategy Parameters">
            {params ? (
              <div className="space-y-1.5">
                <ParamRow label="Min Confidence" value={`${(params.min_confidence * 100).toFixed(0)}%`} />
                <ParamRow label="Min Edge" value={`${(params.min_edge * 100).toFixed(1)}%`} />
                <ParamRow label="Kelly Fraction" value={`${(params.kelly_fraction * 100).toFixed(0)}%`} />
                <ParamRow label="Max Position" value={`${params.max_position_size} contracts`} />
                <ParamRow label="Max Positions" value={`${params.max_simultaneous_positions}`} />
                <ParamRow label="Scan Interval" value={`${params.scan_interval}s`} />
                <ParamRow label="Max Daily Loss" value={`$${params.max_daily_loss}`} />
                <ParamRow label="Stop Loss" value={`${(params.stop_loss_pct * 100).toFixed(0)}%`} />
                <ParamRow label="Take Profit" value={`${(params.take_profit_pct * 100).toFixed(0)}%`} />
                <ParamRow label="Max Spread" value={`${params.max_spread_cents}¢`} />
                <ParamRow label="Aggression" value={`${(params.aggression * 100).toFixed(0)}%`} />
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-[var(--text-muted)]">Loading...</div>
            )}
          </Card>
        </div>
      )}

      {/* ════════════════ TAB: TRADES ════════════════════════════════════════ */}
      {tab === "trades" && (
        <div className="space-y-4">
          <Card title="Recent Trades" action={<span className="text-xs text-[var(--text-muted)]">{realTrades.length} real / {trades.length} total</span>}>
            {trades.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06] text-[var(--text-muted)]">
                      <th className="text-left pb-2 font-medium">Ticker</th>
                      <th className="text-left pb-2 font-medium">Side</th>
                      <th className="text-right pb-2 font-medium">Qty</th>
                      <th className="text-right pb-2 font-medium">Price</th>
                      <th className="text-right pb-2 font-medium">Conf</th>
                      <th className="text-right pb-2 font-medium">Edge</th>
                      <th className="text-center pb-2 font-medium">Outcome</th>
                      <th className="text-right pb-2 font-medium">P&L</th>
                      <th className="text-right pb-2 font-medium">Time</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {trades.map((t, i) => {
                      const isBootstrap = t.model_version?.startsWith("bootstrap");
                      return (
                        <tr key={i} className={`hover:bg-white/[0.03] ${isBootstrap ? "opacity-40" : ""}`}>
                          <td className="py-2.5 font-mono text-[var(--text-primary)] max-w-[200px] truncate">{t.ticker}</td>
                          <td className={`py-2.5 font-semibold ${t.side === "yes" ? "text-accent" : "text-loss"}`}>{t.side?.toUpperCase()}</td>
                          <td className="py-2.5 text-right tabular-nums text-[var(--text-secondary)]">{t.count}</td>
                          <td className="py-2.5 text-right tabular-nums text-[var(--text-secondary)]">{t.price_cents}¢</td>
                          <td className="py-2.5 text-right tabular-nums text-[var(--text-secondary)]">{((t.confidence ?? 0) * 100).toFixed(0)}%</td>
                          <td className="py-2.5 text-right tabular-nums text-[var(--text-secondary)]">{((t.edge ?? 0) * 100).toFixed(1)}%</td>
                          <td className="py-2.5 text-center">
                            <OutcomeBadge outcome={t.outcome} />
                          </td>
                          <td className={`py-2.5 text-right tabular-nums font-medium ${pnlColor(t.pnl_cents ?? 0)}`}>
                            {(t.pnl_cents ?? 0) !== 0 ? `${t.pnl_cents > 0 ? "+" : ""}${(t.pnl_cents / 100).toFixed(2)}` : "—"}
                          </td>
                          <td className="py-2.5 text-right text-[var(--text-muted)]">
                            {t.timestamp ? new Date(t.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex h-48 items-center justify-center text-sm text-[var(--text-muted)]">No trades recorded yet</div>
            )}
          </Card>

          {/* Trade Statistics */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="Trade Distribution">
              <div className="space-y-3">
                {realTrades.length > 0 ? (
                  <>
                    <DistRow label="YES Trades" count={realTrades.filter(t => t.side === "yes").length} total={realTrades.length} color="bg-accent" />
                    <DistRow label="NO Trades" count={realTrades.filter(t => t.side === "no").length} total={realTrades.length} color="bg-loss" />
                    <div className="h-px bg-white/[0.06]" />
                    <DistRow label="Pending" count={realTrades.filter(t => t.outcome === "pending").length} total={realTrades.length} color="bg-blue-400" />
                    <DistRow label="Won" count={realTrades.filter(t => t.outcome === "win").length} total={realTrades.length} color="bg-accent" />
                    <DistRow label="Lost" count={realTrades.filter(t => t.outcome === "loss").length} total={realTrades.length} color="bg-loss" />
                  </>
                ) : (
                  <div className="flex h-24 items-center justify-center text-sm text-[var(--text-muted)]">Awaiting real trades</div>
                )}
              </div>
            </Card>

            <Card title="Confidence Histogram">
              <div className="space-y-2">
                {realTrades.length > 0 ? (
                  [
                    { range: "90-100%", min: 0.9, max: 1.01 },
                    { range: "80-90%", min: 0.8, max: 0.9 },
                    { range: "70-80%", min: 0.7, max: 0.8 },
                    { range: "60-70%", min: 0.6, max: 0.7 },
                    { range: "50-60%", min: 0.5, max: 0.6 },
                  ].map(b => {
                    const c = realTrades.filter(t => (t.confidence ?? 0) >= b.min && (t.confidence ?? 0) < b.max).length;
                    return <DistRow key={b.range} label={b.range} count={c} total={realTrades.length} color="bg-accent" />;
                  })
                ) : (
                  <div className="flex h-24 items-center justify-center text-sm text-[var(--text-muted)]">Awaiting real trades</div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ════════════════ TAB: MODEL ═════════════════════════════════════════ */}
      {tab === "model" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Model Info */}
          <Card title="XGBoost Model">
            <div className="space-y-2">
              <StateRow label="Version" value={learn?.current_version ?? "—"} mono />
              <StateRow label="Champion AUC" value={learn ? learn.champion_auc.toFixed(4) : "—"} />
              <StateRow label="Training Samples" value={`${learn?.champion_samples ?? 0}`} />
              <StateRow label="Generations" value={`${learn?.generation ?? 0}`} />
              <StateRow label="Retrains" value={`${learn?.total_retrains ?? 0}`} />
              <StateRow label="Promotions" value={`${learn?.total_promotions ?? 0}`} />
              <StateRow label="Regime" value={s?.strategy?.regime ?? "unknown"} />
              <StateRow label="Adaptations" value={`${s?.strategy?.total_adaptations ?? 0}`} />
            </div>
          </Card>

          {/* Feature Importance */}
          <Card title="Feature Importance (Live)">
            {learn?.top_features && Object.keys(learn.top_features).length > 0 ? (
              <div className="space-y-2.5">
                {Object.entries(learn.top_features)
                  .sort(([, a], [, b]) => b - a)
                  .map(([name, value]) => (
                    <div key={name}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-[var(--text-secondary)] font-mono">{name}</span>
                        <span className="text-xs text-accent tabular-nums font-mono">{(value * 100).toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                        <div className="h-full rounded-full bg-gradient-to-r from-accent via-accent/80 to-accent/40 transition-all" style={{ width: `${Math.min(value * 300, 100)}%` }} />
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="flex h-40 items-center justify-center text-sm text-[var(--text-muted)]">Model not yet trained</div>
            )}
          </Card>

          {/* Scheduler */}
          <Card title="Background Scheduler">
            <div className="space-y-2">
              <StateRow label="Active Tasks" value={`${s?.scheduler?.tasks ?? 0}`} />
              <StateRow label="Sports Mode" value={s?.sports_only_mode ? "Active" : "Inactive"} />
              {s?.sports_predictor && (
                <>
                  <div className="h-px bg-white/[0.06] my-1" />
                  <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Sports Predictor</div>
                  {Object.entries(s.sports_predictor).slice(0, 5).map(([k, v]) => (
                    <StateRow key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                  ))}
                </>
              )}
            </div>
          </Card>

          {/* Portfolio Risk */}
          <Card title="Portfolio Risk Engine">
            {s?.portfolio_risk ? (
              <div className="space-y-2">
                {Object.entries(s.portfolio_risk).map(([k, v]) => (
                  <StateRow key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? (k.includes("pct") || k.includes("ratio") ? `${(v * 100).toFixed(1)}%` : v.toFixed(2)) : String(v)} />
                ))}
              </div>
            ) : (
              <div className="flex h-24 items-center justify-center text-sm text-[var(--text-muted)]">Loading...</div>
            )}
          </Card>
        </div>
      )}

      {/* ════════════════ TAB: CHAT ══════════════════════════════════════════ */}
      {tab === "chat" && (
        <div className="flex flex-col h-[calc(100vh-22rem)]">
          <div className="flex-1 glass rounded-2xl flex flex-col overflow-hidden">
            <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full space-y-6">
                  <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-accent/15 to-accent/5 border border-accent/15">
                    <IconBrain size={32} className="text-accent" />
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-bold text-[var(--text-primary)]">Talk to Frankenstein</div>
                    <p className="text-sm text-[var(--text-muted)] mt-1 max-w-sm">Ask about markets, portfolio, signals, risk, or anything about the system.</p>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-w-lg">
                    {[
                      { label: "System Status", query: "How is the system doing?" },
                      { label: "Portfolio", query: "Show me my portfolio" },
                      { label: "Market Analysis", query: "What markets look promising?" },
                      { label: "Risk Report", query: "Give me a risk assessment" },
                      { label: "Top Signals", query: "What are the top AI signals?" },
                      { label: "Strategy", query: "Explain current strategy params" },
                    ].map(qa => (
                      <button key={qa.label} onClick={() => sendChat(qa.query)}
                        className="rounded-xl bg-white/[0.02] border border-white/[0.04] px-3 py-2.5 text-left transition-all hover:bg-white/[0.05] hover:border-white/[0.08] group">
                        <span className="text-xs text-[var(--text-secondary)] group-hover:text-[var(--text-primary)]">{qa.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className="max-w-[80%]">
                      {msg.role === "assistant" && (
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <IconBrain size={12} className="text-accent" />
                          <span className="text-xs text-[var(--text-muted)] font-medium">Frankenstein</span>
                        </div>
                      )}
                      <div className={`rounded-2xl px-4 py-3 ${msg.role === "user" ? "bg-accent/15 border border-accent/20 text-[var(--text-primary)]" : "bg-white/[0.03] border border-white/[0.06]"}`}>
                        {msg.role === "user" ? (
                          <p className="text-sm">{msg.content}</p>
                        ) : (
                          <div className="prose-chat" dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
                        )}
                      </div>
                      <div className="text-xs text-[var(--text-muted)]/50 mt-1 px-1">
                        {new Date(msg.timestamp).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      </div>
                    </div>
                  </div>
                ))
              )}
              {sending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl bg-white/[0.03] border border-white/[0.06] px-4 py-3">
                    <div className="flex items-center gap-2">
                      <IconBrain size={12} className="text-accent animate-pulse" />
                      <div className="flex gap-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "0ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "150ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-accent/60 animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="border-t border-white/[0.06] p-4">
              <form onSubmit={(e) => { e.preventDefault(); sendChat(chatInput); }} className="flex items-center gap-3">
                <input type="text" value={chatInput} onChange={(e) => setChatInput(e.target.value)} placeholder="Ask Frankenstein anything..." disabled={sending}
                  className="flex-1 rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-accent/30 focus:ring-1 focus:ring-accent/10 transition-all disabled:opacity-50" />
                <button type="submit" disabled={sending || !chatInput.trim()}
                  className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent text-white hover:bg-accent/90 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                  <IconSend size={16} />
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Small UI Components ──────────────────────────────────────────────────── */

function StateRow({ label, value, mono, color, warn }: { label: string; value: string; mono?: boolean; color?: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className={`text-xs font-medium tabular-nums ${mono ? "font-mono" : ""} ${color ?? (warn ? "text-[var(--warning)]" : "text-[var(--text-primary)]")}`}>{value}</span>
    </div>
  );
}

function ParamRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
      <span className="text-xs text-[var(--text-muted)]">{label}</span>
      <span className="text-xs font-mono text-accent tabular-nums">{value}</span>
    </div>
  );
}

function FunnelRow({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-[var(--text-secondary)]">{label}</span>
        <span className="text-xs tabular-nums font-mono text-[var(--text-primary)]">{value}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${Math.max(pct, value > 0 ? 2 : 0)}%` }} />
      </div>
    </div>
  );
}

function DistRow({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-[var(--text-secondary)]">{label}</span>
        <span className="text-xs tabular-nums text-[var(--text-primary)]">{count} <span className="text-[var(--text-muted)]">({pct.toFixed(0)}%)</span></span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const styles: Record<string, string> = {
    pending: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    win: "bg-accent/10 text-accent border-accent/20",
    loss: "bg-loss/10 text-loss border-loss/20",
    breakeven: "bg-white/5 text-[var(--text-muted)] border-white/10",
    expired: "bg-white/5 text-[var(--text-muted)] border-white/10",
    cancelled: "bg-white/5 text-[var(--text-muted)] border-white/10",
  };
  return (
    <span className={`inline-flex rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${styles[outcome] ?? styles.pending}`}>
      {outcome}
    </span>
  );
}

function StageIcon({ stage }: { stage: string }) {
  if (stage === "executed") return <IconCircle size={6} className="text-accent flex-shrink-0" />;
  if (stage === "exec_rejected") return <IconCircle size={6} className="text-[var(--warning)] flex-shrink-0" />;
  if (stage === "portfolio_rejected") return <IconCircle size={6} className="text-loss flex-shrink-0" />;
  return <IconCircle size={6} className="text-[var(--text-muted)] flex-shrink-0" />;
}
