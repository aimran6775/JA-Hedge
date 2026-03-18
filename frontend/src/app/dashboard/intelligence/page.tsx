"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { IconRefresh } from "@/components/ui/Icons";
import {
  api,
  type IntelligenceSource,
  type IntelligenceSignal,
  type IntelligenceAlert,
} from "@/lib/api";

/* ── Types ──────────────────────────────────────────────── */

interface DashboardData {
  initialized: boolean;
  status: string;
  sources: IntelligenceSource[];
  summary: {
    total_sources: number;
    active_sources: number;
    total_signals: number;
    signals_by_category: Record<string, number>;
    overall_quality: number;
  };
  alerts: {
    stats: Record<string, unknown>;
    recent: IntelligenceAlert[];
  };
  message?: string;
}

/* ── Page ───────────────────────────────────────────────── */

export default function IntelligencePage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [signals, setSignals] = useState<IntelligenceSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "sources" | "signals" | "alerts">("overview");

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [dashRes, sigRes] = await Promise.allSettled([
        api.intelligence.dashboard(),
        api.intelligence.signals(),
      ]);

      if (dashRes.status === "fulfilled") setData(dashRes.value);
      if (sigRes.status === "fulfilled") setSignals(sigRes.value.signals);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load intelligence data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 15000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  const sources = data?.sources ?? [];
  const summary = data?.summary;
  const alerts = data?.alerts?.recent ?? [];
  const qualityPct = summary ? Math.round(summary.overall_quality * 100) : 100;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">
            🧠 Data Intelligence
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1 flex items-center gap-2">
            <span className="tabular-nums">{summary?.total_sources ?? 0} sources</span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span className="flex items-center gap-1">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  data?.status === "active" ? "bg-accent animate-pulse" : "bg-[var(--text-muted)]"
                }`}
              />
              {data?.status ?? "loading"}
            </span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span className="tabular-nums">{summary?.total_signals ?? 0} signals</span>
          </p>
        </div>
        <button
          onClick={fetchAll}
          className="rounded-xl glass px-4 py-2 text-xs font-medium text-accent hover:bg-accent/5 transition-all"
        >
          <IconRefresh size={14} />
        </button>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        <StatCard label="Data Sources" value={summary?.total_sources ?? 0} />
        <StatCard
          label="Active"
          value={summary?.active_sources ?? 0}
          accent={summary?.active_sources === summary?.total_sources}
        />
        <StatCard label="Signals" value={summary?.total_signals ?? 0} />
        <StatCard label="Quality" value={`${qualityPct}%`} accent={qualityPct >= 80} />
        <StatCard
          label="Alerts"
          value={alerts.length}
          accent={alerts.some((a) => a.severity === "critical")}
          warn={alerts.some((a) => a.severity === "critical")}
        />
      </div>

      {error && (
        <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">{error}</div>
      )}

      {!data?.initialized && !loading && (
        <Card>
          <div className="py-12 text-center text-[var(--text-muted)]">
            <p className="text-lg mb-2">Intelligence system initializing...</p>
            <p className="text-xs">Sources will start fetching data automatically when the backend starts.</p>
          </div>
        </Card>
      )}

      {/* Tabs */}
      <div className="flex gap-2">
        {(["overview", "sources", "signals", "alerts"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-xl px-4 py-2 text-xs font-medium capitalize transition-all duration-200 ${
              activeTab === tab
                ? "bg-accent/10 text-accent border border-accent/20"
                : "glass text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.03]"
            }`}
          >
            {tab === "overview"
              ? "Overview"
              : tab === "sources"
                ? `Sources (${sources.length})`
                : tab === "signals"
                  ? `Signals (${signals.length})`
                  : `Alerts (${alerts.length})`}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && !data ? (
        <Card>
          <div className="py-16 text-center text-[var(--text-muted)] animate-shimmer">
            Loading intelligence data...
          </div>
        </Card>
      ) : activeTab === "overview" ? (
        <OverviewTab sources={sources} summary={summary} alerts={alerts} signals={signals} />
      ) : activeTab === "sources" ? (
        <SourcesTab sources={sources} />
      ) : activeTab === "signals" ? (
        <SignalsTab signals={signals} />
      ) : (
        <AlertsTab alerts={alerts} />
      )}
    </div>
  );
}

/* ── Stat Card ────────────────────────────────────────────── */

function StatCard({
  label,
  value,
  accent,
  warn,
}: {
  label: string;
  value: number | string;
  accent?: boolean;
  warn?: boolean;
}) {
  return (
    <Card>
      <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">{label}</p>
      <p
        className={`text-2xl font-bold mt-1 tabular-nums ${
          warn ? "text-loss" : accent ? "text-accent" : "text-[var(--text-primary)]"
        }`}
      >
        {value}
      </p>
    </Card>
  );
}

/* ── Source type icons & labels ────────────────────────────── */

const SOURCE_META: Record<string, { emoji: string; label: string; color: string }> = {
  sports_odds: { emoji: "🏀", label: "Sports Odds", color: "text-orange-400" },
  news: { emoji: "📰", label: "News", color: "text-blue-400" },
  social: { emoji: "🐦", label: "Social", color: "text-sky-400" },
  weather: { emoji: "🌤️", label: "Weather", color: "text-cyan-400" },
  crypto: { emoji: "₿", label: "Crypto", color: "text-yellow-400" },
  prediction_market: { emoji: "📊", label: "Polymarket", color: "text-purple-400" },
  economic: { emoji: "📈", label: "Economic", color: "text-green-400" },
  political: { emoji: "🏛️", label: "Political", color: "text-red-400" },
  trends: { emoji: "🔍", label: "Trends", color: "text-pink-400" },
};

function getSourceMeta(type: string) {
  return SOURCE_META[type] ?? { emoji: "📡", label: type, color: "text-[var(--text-muted)]" };
}

/* ── Overview Tab ─────────────────────────────────────────── */

function OverviewTab({
  sources,
  summary,
  alerts,
  signals,
}: {
  sources: IntelligenceSource[];
  summary: DashboardData["summary"] | undefined;
  alerts: IntelligenceAlert[];
  signals: IntelligenceSignal[];
}) {
  const categories = summary?.signals_by_category ?? {};

  return (
    <div className="space-y-6">
      {/* Data Flow Visualization */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Data Flow — Where Intelligence Comes From</h3>
        <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
          {sources.map((src) => {
            const meta = getSourceMeta(src.type);
            return (
              <div
                key={src.name}
                className={`relative rounded-xl border p-3 text-center transition-all ${
                  src.healthy
                    ? "border-accent/20 bg-accent/[0.03]"
                    : "border-loss/20 bg-loss/[0.03]"
                }`}
              >
                <div className="text-2xl mb-1">{meta.emoji}</div>
                <p className="text-[10px] font-semibold text-[var(--text-primary)] truncate">{meta.label}</p>
                <p className="text-[9px] text-[var(--text-muted)] tabular-nums mt-0.5">
                  {src.signal_count} signals
                </p>
                <div
                  className={`absolute top-1.5 right-1.5 h-2 w-2 rounded-full ${
                    src.healthy ? "bg-accent" : "bg-loss animate-pulse"
                  }`}
                />
                {/* Quality bar */}
                <div className="mt-2 h-1 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      src.quality_score >= 0.8
                        ? "bg-accent"
                        : src.quality_score >= 0.5
                          ? "bg-[var(--warning)]"
                          : "bg-loss"
                    }`}
                    style={{ width: `${Math.round(src.quality_score * 100)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* Arrow → Model */}
        <div className="flex items-center justify-center gap-3 my-4">
          <div className="h-px flex-1 bg-gradient-to-r from-transparent via-accent/20 to-transparent" />
          <span className="text-xs text-accent font-medium px-3">→ ML Model ←</span>
          <div className="h-px flex-1 bg-gradient-to-r from-transparent via-accent/20 to-transparent" />
        </div>

        {/* Category breakdown */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {Object.entries(categories)
            .sort((a, b) => b[1] - a[1])
            .map(([cat, count]) => (
              <div key={cat} className="flex items-center justify-between rounded-lg bg-white/[0.02] px-3 py-2">
                <span className="text-xs text-[var(--text-secondary)] capitalize">{cat}</span>
                <span className="text-xs font-bold text-[var(--text-primary)] tabular-nums">{count}</span>
              </div>
            ))}
        </div>
      </Card>

      {/* Top Signals */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Strongest Signals</h3>
        {signals.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)] py-4 text-center">Waiting for signals...</p>
        ) : (
          <div className="space-y-2">
            {signals.slice(0, 8).map((sig, i) => (
              <SignalRow key={`${sig.source}-${sig.ticker}-${i}`} signal={sig} />
            ))}
          </div>
        )}
      </Card>

      {/* Recent Alerts */}
      {alerts.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Recent Alerts</h3>
          <div className="space-y-2">
            {alerts.slice(0, 5).map((alert, i) => (
              <AlertRow key={i} alert={alert} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

/* ── Sources Tab ──────────────────────────────────────────── */

function SourcesTab({ sources }: { sources: IntelligenceSource[] }) {
  return (
    <div className="space-y-4">
      {sources.length === 0 ? (
        <Card>
          <div className="py-12 text-center text-[var(--text-muted)]">No sources registered</div>
        </Card>
      ) : (
        sources.map((src) => <SourceCard key={src.name} source={src} />)
      )}
    </div>
  );
}

function SourceCard({ source: src }: { source: IntelligenceSource }) {
  const meta = getSourceMeta(src.type);
  const latencyColor =
    src.avg_latency_ms < 1000 ? "text-accent" : src.avg_latency_ms < 5000 ? "text-[var(--warning)]" : "text-loss";
  const errorRate = src.fetch_count > 0 ? ((src.error_count / src.fetch_count) * 100).toFixed(1) : "0.0";

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="text-2xl">{meta.emoji}</div>
          <div>
            <h4 className="text-sm font-semibold text-[var(--text-primary)]">{src.name}</h4>
            <p className={`text-[10px] font-medium ${meta.color}`}>{meta.label}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              src.healthy
                ? "bg-accent/10 text-accent"
                : "bg-loss/10 text-loss"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${src.healthy ? "bg-accent" : "bg-loss"}`} />
            {src.healthy ? "Healthy" : "Unhealthy"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4">
        <MiniStat label="Signals" value={src.signal_count} />
        <MiniStat label="Fetches" value={src.fetch_count} />
        <MiniStat label="Error Rate" value={`${errorRate}%`} warn={parseFloat(errorRate) > 20} />
        <MiniStat label="Latency" value={`${Math.round(src.avg_latency_ms)}ms`} className={latencyColor} />
        <MiniStat label="Quality" value={`${Math.round(src.quality_score * 100)}%`} accent={src.quality_score >= 0.8} />
      </div>

      {/* Weight + reliability */}
      <div className="mt-3 flex items-center gap-4">
        <span className="text-[10px] text-[var(--text-muted)]">
          Weight: <span className="font-bold text-[var(--text-primary)]">{src.weight?.toFixed(2) ?? "1.00"}×</span>
        </span>
        {Object.entries(src.reliability || {}).length > 0 && (
          <span className="text-[10px] text-[var(--text-muted)]">
            Reliability:{" "}
            {Object.entries(src.reliability)
              .map(([cat, val]) => `${cat}: ${Math.round(val * 100)}%`)
              .join(" · ")}
          </span>
        )}
      </div>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  accent,
  warn,
  className,
}: {
  label: string;
  value: string | number;
  accent?: boolean;
  warn?: boolean;
  className?: string;
}) {
  return (
    <div>
      <p className="text-[9px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p
        className={`text-sm font-bold tabular-nums ${
          className ?? (warn ? "text-loss" : accent ? "text-accent" : "text-[var(--text-primary)]")
        }`}
      >
        {value}
      </p>
    </div>
  );
}

/* ── Signals Tab ──────────────────────────────────────────── */

function SignalsTab({ signals }: { signals: IntelligenceSignal[] }) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? signals.filter(
        (s) =>
          s.source.toLowerCase().includes(filter.toLowerCase()) ||
          s.category.toLowerCase().includes(filter.toLowerCase()) ||
          s.ticker.toLowerCase().includes(filter.toLowerCase()),
      )
    : signals;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          type="text"
          placeholder="Filter by source, category, or ticker..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="flex-1 rounded-xl glass px-4 py-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-accent/30"
        />
        <span className="text-xs text-[var(--text-muted)] tabular-nums">{filtered.length} signals</span>
      </div>

      {filtered.length === 0 ? (
        <Card>
          <div className="py-12 text-center text-[var(--text-muted)]">
            {signals.length === 0 ? "No signals yet — sources are warming up" : "No matching signals"}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="space-y-1">
            {filtered.slice(0, 50).map((sig, i) => (
              <SignalRow key={`${sig.source}-${sig.ticker}-${i}`} signal={sig} expanded />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function SignalRow({ signal: sig, expanded }: { signal: IntelligenceSignal; expanded?: boolean }) {
  const meta = getSourceMeta(sig.type);
  const isPositive = sig.signal_value > 0;
  const magnitude = Math.abs(sig.signal_value);
  const barWidth = Math.min(100, magnitude * 100);

  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-white/[0.02] transition-colors">
      <span className="text-sm shrink-0">{meta.emoji}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--text-primary)] truncate">
            {sig.ticker || sig.category}
          </span>
          {sig.headline && (
            <span className="text-[10px] text-[var(--text-muted)] truncate">{sig.headline}</span>
          )}
        </div>
        {expanded && (
          <span className="text-[10px] text-[var(--text-muted)]">
            {sig.source} · {sig.category} · conf {(sig.confidence * 100).toFixed(0)}%
          </span>
        )}
      </div>
      {/* Signal bar */}
      <div className="w-20 flex items-center gap-1">
        <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${isPositive ? "bg-accent" : "bg-loss"}`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
        <span
          className={`text-[10px] font-bold tabular-nums w-10 text-right ${
            isPositive ? "text-accent" : "text-loss"
          }`}
        >
          {sig.signal_value > 0 ? "+" : ""}
          {sig.signal_value.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

/* ── Alerts Tab ───────────────────────────────────────────── */

function AlertsTab({ alerts }: { alerts: IntelligenceAlert[] }) {
  return (
    <div className="space-y-4">
      {alerts.length === 0 ? (
        <Card>
          <div className="py-12 text-center text-[var(--text-muted)]">No alerts — everything is quiet</div>
        </Card>
      ) : (
        <Card>
          <div className="space-y-2">
            {alerts.map((alert, i) => (
              <AlertRow key={i} alert={alert} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: IntelligenceAlert }) {
  const severityStyles: Record<string, string> = {
    info: "border-blue-500/20 bg-blue-500/5 text-blue-400",
    warning: "border-[var(--warning)]/20 bg-[var(--warning)]/5 text-[var(--warning)]",
    critical: "border-loss/20 bg-loss/5 text-loss",
  };
  const severityDot: Record<string, string> = {
    info: "bg-blue-400",
    warning: "bg-[var(--warning)]",
    critical: "bg-loss animate-pulse",
  };
  const style = severityStyles[alert.severity] ?? severityStyles.info;
  const dot = severityDot[alert.severity] ?? severityDot.info;

  const timeAgo = Math.round((Date.now() / 1000 - alert.timestamp) / 60);
  const timeLabel = timeAgo < 1 ? "just now" : timeAgo < 60 ? `${timeAgo}m ago` : `${Math.round(timeAgo / 60)}h ago`;

  return (
    <div className={`rounded-lg border p-3 ${style}`}>
      <div className="flex items-start gap-2">
        <span className={`mt-1 h-2 w-2 rounded-full shrink-0 ${dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">{alert.title}</span>
            <span className="text-[10px] opacity-60 shrink-0">{timeLabel}</span>
          </div>
          <p className="text-[10px] opacity-80 mt-0.5">{alert.message}</p>
        </div>
      </div>
    </div>
  );
}
