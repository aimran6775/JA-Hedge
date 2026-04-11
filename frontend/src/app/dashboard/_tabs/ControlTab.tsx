"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, type FrankensteinStatus, type RiskSnapshot } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/* ═══════════════════════════════════════════════════════════════════════
   CONTROL TAB — Simplified brain controls
   ═══════════════════════════════════════════════════════════════════════ */
export function ControlTab() {
  const [frank, setFrank] = useState<FrankensteinStatus | null>(null);
  const [risk, setRisk] = useState<RiskSnapshot | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    const [s, r] = await Promise.all([
      api.frankenstein.status().catch(() => null),
      api.risk.snapshot().catch(() => null),
    ]);
    if (s) setFrank(s);
    if (r) setRisk(r);
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
      setActionMsg(`${action} ✓`);
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

  const sendChat = async () => {
    if (!chatInput.trim()) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", content: userMsg }]);
    setChatLoading(true);
    
    try {
      const res = await fetch(`${API_BASE}/api/frankenstein/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg }),
      });
      const data = await res.json();
      setChatMessages(prev => [...prev, { role: "assistant", content: data.response || "No response" }]);
    } catch {
      setChatMessages(prev => [...prev, { role: "assistant", content: "Error communicating with brain." }]);
    }
    setChatLoading(false);
  };

  return (
    <div className="space-y-4 p-1">
      {/* Brain Status & Controls */}
      <div className="rounded-xl glass p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <StatusDot active={brainTrading && !brainPaused} />
            <div>
              <div className="text-sm font-semibold text-primary">{brainLabel}</div>
              {frank && (
                <div className="text-[10px] text-muted">
                  Gen {frank.generation} · {frank.uptime_human || "0s"} uptime
                </div>
              )}
            </div>
          </div>
          {actionMsg && (
            <span className="text-xs text-accent">{actionMsg}</span>
          )}
        </div>
        
        <div className="grid grid-cols-5 gap-2">
          <ActionButton 
            label="Awaken" 
            onClick={() => brainAction("awaken")} 
            disabled={brainAlive}
            variant="accent"
          />
          <ActionButton 
            label="Sleep" 
            onClick={() => brainAction("sleep")} 
            disabled={!brainAlive}
            variant="danger"
          />
          <ActionButton 
            label="Pause" 
            onClick={() => brainAction("pause")} 
            disabled={!brainAlive || brainPaused}
            variant="warning"
          />
          <ActionButton 
            label="Resume" 
            onClick={() => brainAction("resume")} 
            disabled={!brainPaused}
            variant="accent"
          />
          <ActionButton 
            label="Retrain" 
            onClick={() => brainAction("retrain")} 
            disabled={!brainAlive}
            variant="info"
          />
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 gap-3">
        <StatBox 
          label="Model Version" 
          value={frank?.learner?.current_version || "N/A"}
        />
        <StatBox 
          label="Total Trades" 
          value={frank?.total_trades_executed?.toString() || "0"}
        />
        <StatBox 
          label="Win Rate" 
          value={frank?.performance?.snapshot?.win_rate ? `${(frank.performance.snapshot.win_rate * 100).toFixed(0)}%` : "N/A"}
        />
      </div>

      {/* Risk Status */}
      {risk && (
        <div className="rounded-xl glass p-4">
          <h3 className="text-sm font-medium text-secondary mb-3">Risk Status</h3>
          <div className="space-y-3">
            <RiskBar 
              label="Daily P&L" 
              current={Math.abs(risk.daily_pnl || 0)} 
              max={150}
              danger
            />
            <RiskBar 
              label="Exposure" 
              current={risk.total_exposure || 0} 
              max={1500}
            />
            {risk.kill_switch_active && (
              <div className="rounded-lg bg-loss/20 border border-loss/30 p-2 text-xs text-loss text-center">
                ⚠️ Kill Switch Active
              </div>
            )}
          </div>
        </div>
      )}

      {/* Chat Interface */}
      <div className="rounded-xl glass p-4">
        <h3 className="text-sm font-medium text-secondary mb-3">Chat with Brain</h3>
        <div className="space-y-2 max-h-[200px] overflow-y-auto mb-3">
          {chatMessages.length === 0 && (
            <div className="text-xs text-muted text-center py-4">
              Ask the brain about its decisions, strategy, or status
            </div>
          )}
          {chatMessages.map((msg, i) => (
            <div 
              key={i}
              className={`text-sm p-2 rounded-lg ${
                msg.role === "user" 
                  ? "bg-accent/10 text-primary ml-8" 
                  : "bg-white/[0.03] text-secondary mr-8"
              }`}
            >
              {msg.content}
            </div>
          ))}
          {chatLoading && (
            <div className="text-xs text-muted animate-pulse">Thinking...</div>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendChat()}
            placeholder="Ask the brain..."
            className="flex-1 rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2 text-sm text-primary placeholder:text-muted focus:outline-none focus:border-accent/50"
          />
          <button
            onClick={sendChat}
            disabled={chatLoading || !chatInput.trim()}
            className="px-4 py-2 rounded-lg bg-accent/20 text-accent text-sm font-medium hover:bg-accent/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </div>
      </div>

      {/* Strategy Params (collapsed) */}
      {frank?.strategy?.current_params && (
        <details className="rounded-xl glass p-4">
          <summary className="text-sm font-medium text-secondary cursor-pointer hover:text-primary">
            Strategy Parameters
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <ParamRow label="Min Confidence" value={`${(frank.strategy.current_params.min_confidence || 0.6) * 100}%`} />
            <ParamRow label="Min Edge" value={`${(frank.strategy.current_params.min_edge || 0.05) * 100}%`} />
            <ParamRow label="Kelly Fraction" value={`${(frank.strategy.current_params.kelly_fraction || 0.25) * 100}%`} />
            <ParamRow label="Aggression" value={`${(frank.strategy.current_params.aggression || 1) * 100}%`} />
          </div>
        </details>
      )}
    </div>
  );
}

/* ── Components ────────────────────────────────────────────────────────── */

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className="relative flex h-3 w-3">
      {active && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-50" />
      )}
      <span className={`relative inline-flex h-3 w-3 rounded-full ${active ? "bg-accent" : "bg-muted"}`} />
    </span>
  );
}

function ActionButton({ 
  label, 
  onClick, 
  disabled,
  variant 
}: { 
  label: string; 
  onClick: () => void; 
  disabled?: boolean;
  variant: "accent" | "danger" | "warning" | "info";
}) {
  const colors = {
    accent: "bg-accent/20 text-accent hover:bg-accent/30 border-accent/30",
    danger: "bg-loss/20 text-loss hover:bg-loss/30 border-loss/30",
    warning: "bg-amber-500/20 text-amber-400 hover:bg-amber-500/30 border-amber-500/30",
    info: "bg-sky-500/20 text-sky-400 hover:bg-sky-500/30 border-sky-500/30",
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-2 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${colors[variant]}`}
    >
      {label}
    </button>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl glass p-3">
      <div className="text-[10px] text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className="text-sm font-medium text-primary truncate">{value}</div>
    </div>
  );
}

function RiskBar({ label, current, max, danger }: { label: string; current: number; max: number; danger?: boolean }) {
  const pct = Math.min((current / max) * 100, 100);
  const isHigh = pct > 75;
  
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-muted">{label}</span>
        <span className={`tabular-nums ${isHigh && danger ? "text-loss" : "text-primary"}`}>
          ${current.toFixed(2)} / ${max}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <div 
          className={`h-full rounded-full transition-all ${
            isHigh && danger ? "bg-loss" : isHigh ? "bg-amber-500" : "bg-accent"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function ParamRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-muted">{label}</span>
      <span className="text-primary tabular-nums">{value}</span>
    </div>
  );
}
