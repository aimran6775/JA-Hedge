"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { IconAlertTriangle, IconRefresh, IconCheck, IconCircle } from "@/components/ui/Icons";
import { api, type IntelligenceAlert } from "@/lib/api";

function severityColor(s: string) {
  if (s === "critical") return "text-loss";
  if (s === "high") return "text-[var(--warning)]";
  if (s === "medium") return "text-blue-400";
  return "text-[var(--text-muted)]";
}
function severityBg(s: string) {
  if (s === "critical") return "bg-loss/10 border-loss/20";
  if (s === "high") return "bg-[var(--warning)]/10 border-[var(--warning)]/20";
  if (s === "medium") return "bg-blue-500/10 border-blue-500/20";
  return "bg-white/[0.02] border-white/[0.04]";
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<IntelligenceAlert[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.intelligence.alerts(100);
      setAlerts(res.alerts ?? []);
      setStats(res.stats ?? null);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  const acknowledgeAll = async () => {
    try {
      await api.intelligence.acknowledgeAlerts();
      load();
    } catch { /* ignore */ }
  };

  const unread = alerts.filter(a => !a.acknowledged).length;
  const critical = alerts.filter(a => a.severity === "critical").length;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Alerts</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Intelligence alerts, risk events, and system notifications</p>
        </div>
        <div className="flex items-center gap-2">
          {unread > 0 && (
            <button onClick={acknowledgeAll}
              className="glass rounded-xl px-4 py-2 text-xs font-medium text-accent hover:bg-accent/5 transition-all flex items-center gap-2">
              <IconCheck size={14} /> Mark All Read
            </button>
          )}
          <button onClick={load} disabled={loading}
            className="glass rounded-xl px-4 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-all flex items-center gap-2">
            <IconRefresh size={14} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <StatCard label="Total Alerts" value={String(alerts.length)} icon={<IconAlertTriangle size={18} />} />
        <StatCard label="Unread" value={String(unread)} icon={<IconCircle size={18} />} />
        <StatCard label="Critical" value={String(critical)} trend={critical > 0 ? "down" : "up"} icon={<IconAlertTriangle size={18} />} />
        <StatCard label="Sources" value={stats ? String((stats as Record<string, unknown>).total_sources ?? 0) : "—"} icon={<IconCircle size={18} />} />
      </div>

      <Card title="Alert Feed">
        <div className="space-y-2">
          {alerts.length === 0 ? (
            <div className="py-12 text-center">
              <IconCheck size={24} className="mx-auto text-accent mb-3" />
              <div className="text-sm text-[var(--text-muted)]">No alerts — all clear</div>
            </div>
          ) : (
            alerts.map((a, i) => (
              <div key={i} className={`rounded-xl border px-4 py-3 transition-colors ${severityBg(a.severity)} ${!a.acknowledged ? "ring-1 ring-white/5" : "opacity-60"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <IconAlertTriangle size={16} className={`mt-0.5 flex-shrink-0 ${severityColor(a.severity)}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-sm font-semibold ${severityColor(a.severity)}`}>{a.title}</span>
                        <span className={`inline-flex rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${severityBg(a.severity)}`}>
                          {a.severity}
                        </span>
                        {!a.acknowledged && (
                          <span className="inline-flex rounded-md bg-accent/10 text-accent px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider">NEW</span>
                        )}
                      </div>
                      <p className="text-xs text-[var(--text-secondary)] mt-1">{a.message}</p>
                      <div className="flex items-center gap-3 mt-1.5 text-[10px] text-[var(--text-muted)]">
                        <span>{a.source_name}</span>
                        <span>{a.category}</span>
                        {a.ticker && <span className="font-mono">{a.ticker}</span>}
                        <span>{a.timestamp ? new Date(a.timestamp * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
