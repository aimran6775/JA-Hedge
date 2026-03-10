"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { IconSettings, IconCircle, IconCheck, IconRefresh, IconAlertTriangle, IconZap, IconShield, IconBrain } from "@/components/ui/Icons";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SystemInfo {
  backend: boolean;
  frankenstein: boolean;
  version?: string;
  uptime?: string;
}

export default function SettingsPage() {
  const [sysInfo, setSysInfo] = useState<SystemInfo>({ backend: false, frankenstein: false });
  const [cancelResult, setCancelResult] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    const check = async () => {
      const backendOk = await fetch(`${API_BASE}/health`).then(r => r.ok).catch(() => false);
      const frankOk = await fetch(`${API_BASE}/api/frankenstein/health`).then(r => r.ok).catch(() => false);
      setSysInfo({ backend: backendOk, frankenstein: frankOk });
    };
    check();
    const iv = setInterval(check, 15000);
    return () => clearInterval(iv);
  }, []);

  const cancelAllOrders = async () => {
    setCancelling(true);
    setCancelResult(null);
    try {
      const res = await api.orders.cancelAll();
      setCancelResult(`Orders cancelled (${res.status})`);
    } catch {
      setCancelResult("Failed to cancel orders");
    } finally {
      setCancelling(false);
    }
  };

  const StatusRow = ({ label, ok, icon }: { label: string; ok: boolean; icon: React.ReactNode }) => (
    <div className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-3 transition-colors hover:bg-white/[0.03]">
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${ok ? "bg-accent/10" : "bg-loss/10"}`}>
          {icon}
        </div>
        <span className="text-sm text-[var(--text-primary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <IconCircle size={6} className={ok ? "text-accent" : "text-loss"} />
        <span className={`text-xs font-medium ${ok ? "text-accent" : "text-loss"}`}>{ok ? "Online" : "Offline"}</span>
      </div>
    </div>
  );

  const InfoRow = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-center justify-between py-2.5 border-b border-white/[0.04] last:border-0">
      <span className="text-sm text-[var(--text-muted)]">{label}</span>
      <span className="text-sm text-[var(--text-primary)] font-mono tabular-nums">{value}</span>
    </div>
  );

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Settings</h1>
        <p className="text-xs text-[var(--text-muted)] mt-1">System status, configuration, and quick actions</p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* System Status */}
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
              <InfoRow label="API Base" value={API_BASE} />
              <InfoRow label="Mode" value="Paper Trading (Demo)" />
              <InfoRow label="Platform" value="Kalshi" />
              <InfoRow label="Frontend" value="Next.js 15" />
              <InfoRow label="Backend" value="FastAPI / Python" />
            </div>
          </div>
        </Card>

        {/* Quick Actions */}
        <Card title="Quick Actions">
          <div className="space-y-4">
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-loss/10">
                  <IconAlertTriangle size={20} className="text-loss" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-[var(--text-primary)]">Cancel All Orders</div>
                  <div className="text-xs text-[var(--text-muted)]">Immediately cancel all open orders on Kalshi</div>
                </div>
              </div>
              <button onClick={cancelAllOrders} disabled={cancelling}
                className="w-full rounded-xl py-3 text-sm font-bold bg-loss/90 text-white hover:bg-loss transition-all">
                {cancelling ? "Cancelling..." : "Cancel All Open Orders"}
              </button>
              {cancelResult && (
                <div className={`mt-3 rounded-xl p-3 text-sm text-center ${cancelResult.includes("Cancelled") ? "bg-accent/10 text-accent border border-accent/20" : "bg-loss/10 text-loss border border-loss/20"}`}>
                  {cancelResult}
                </div>
              )}
            </div>

            <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
                  <IconShield size={20} className="text-accent" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-[var(--text-primary)]">Platform Info</div>
                  <div className="text-xs text-[var(--text-muted)]">JA Hedge AI Trading Terminal</div>
                </div>
              </div>
              <div className="space-y-0">
                <InfoRow label="Version" value="2.0.0" />
                <InfoRow label="AI Modules" value="6 (Frankenstein)" />
                <InfoRow label="API Endpoints" value="20+" />
                <InfoRow label="Build" value="Production" />
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
