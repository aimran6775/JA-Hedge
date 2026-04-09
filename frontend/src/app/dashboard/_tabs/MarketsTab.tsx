"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import {
  IconTarget,
  IconMarkets,
  IconStrategy,
  IconSports,
  IconIntelligence,
  IconAlertTriangle,
  IconRefresh,
  IconSearch,
  IconCircle,
  IconChevronRight,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type SubTab = "candidates" | "strategies" | "sports" | "intelligence" | "alerts";

/* ═══════════════════════════════════════════════════════════════════════
   MARKETS TAB — What opportunities exist
   ═══════════════════════════════════════════════════════════════════════ */
export function MarketsTab() {
  const [sub, setSub] = useState<SubTab>("candidates");
  const [frankStatus, setFrankStatus] = useState<Record<string, unknown> | null>(null);
  const [rejections, setRejections] = useState<Record<string, unknown> | null>(null);
  const [strategies, setStrategies] = useState<Record<string, unknown> | null>(null);
  const [signals, setSignals] = useState<unknown[]>([]);
  const [sportsData, setSportsData] = useState<Record<string, unknown> | null>(null);
  const [sportsMarkets, setSportsMarkets] = useState<unknown[]>([]);
  const [intelDash, setIntelDash] = useState<Record<string, unknown> | null>(null);
  const [alerts, setAlerts] = useState<unknown[]>([]);
  const [alertStats, setAlertStats] = useState({ total: 0, unread: 0 });

  const fetchCore = useCallback(async () => {
    const [fs, rej] = await Promise.all([
      api.frankenstein.status().catch(() => null),
      api.frankenstein.debugRejections().catch(() => null),
    ]);
    if (fs) setFrankStatus(fs as unknown as Record<string, unknown>);
    if (rej) setRejections(rej as Record<string, unknown>);
  }, []);

  const fetchStrategies = useCallback(async () => {
    const [s, sig] = await Promise.all([
      api.strategies.status().catch(() => null),
      api.strategies.signals().catch(() => []),
    ]);
    if (s) setStrategies(s as unknown as Record<string, unknown>);
    setSignals(sig as unknown[]);
  }, []);

  const fetchSports = useCallback(async () => {
    const [s, m] = await Promise.all([
      api.sports.status().catch(() => null),
      api.sports.markets().catch(() => []),
    ]);
    if (s) setSportsData(s as Record<string, unknown>);
    if (Array.isArray(m)) setSportsMarkets(m);
  }, []);

  const fetchIntel = useCallback(async () => {
    const [d, a] = await Promise.all([
      api.intelligence.dashboard().catch(() => null),
      api.intelligence.alerts(50).catch(() => []),
    ]);
    if (d) setIntelDash(d as Record<string, unknown>);
    const alertList = Array.isArray(a) ? a : ((a as Record<string, unknown>)?.alerts as unknown[] ?? []);
    setAlerts(alertList);
    const unread = alertList.filter((x: unknown) => !(x as Record<string, boolean>).acknowledged).length;
    setAlertStats({ total: alertList.length, unread });
  }, []);

  useEffect(() => {
    fetchCore();
    const iv = setInterval(fetchCore, 15000);
    return () => clearInterval(iv);
  }, [fetchCore]);

  useEffect(() => {
    if (sub === "strategies") fetchStrategies();
    if (sub === "sports") fetchSports();
    if (sub === "intelligence" || sub === "alerts") fetchIntel();
  }, [sub, fetchStrategies, fetchSports, fetchIntel]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const candidates = (rejections as any)?.candidates ?? (rejections as any)?.markets ?? [];
  const candidateCount = Array.isArray(candidates) ? candidates.length : 0;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rejSummary = (rejections as any)?.summary ?? (rejections as any)?.rejection_reasons ?? null;

  const SUB_TABS: { id: SubTab; label: string; icon: typeof IconTarget }[] = [
    { id: "candidates", label: "Candidates", icon: IconTarget },
    { id: "strategies", label: "Strategies", icon: IconStrategy },
    { id: "sports", label: "Sports", icon: IconSports },
    { id: "intelligence", label: "Intelligence", icon: IconIntelligence },
    { id: "alerts", label: `Alerts${alertStats.unread > 0 ? ` (${alertStats.unread})` : ""}`, icon: IconAlertTriangle },
  ];

  return (
    <div className="space-y-4 animate-fade-in">
      {/* ── Stat cards ────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          label="Active Markets"
          value={
            (frankStatus as Record<string, unknown>)?.total_scans != null
              ? String((frankStatus as Record<string, unknown>).total_scans)
              : "--"
          }
          icon={<IconMarkets size={16} />}
        />
        <StatCard label="Candidates" value={String(candidateCount)} icon={<IconTarget size={16} />} />
        <StatCard
          label="Signals"
          value={String(signals.length)}
          icon={<IconStrategy size={16} />}
        />
        <StatCard
          label="Sports Markets"
          value={String(sportsMarkets.length)}
          icon={<IconSports size={16} />}
        />
        <StatCard
          label="Alerts"
          value={String(alertStats.unread)}
          suffix=" unread"
          icon={<IconAlertTriangle size={16} />}
        />
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

      {/* ── Candidates ────────────────────────────────────────────────── */}
      {sub === "candidates" && (
        <div className="space-y-4">
          {candidateCount > 0 ? (
            <Card title="Trade Candidates" action={
              <button onClick={fetchCore} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
                <IconRefresh size={14} />
              </button>
            }>
              <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-[var(--bg-primary)]">
                    <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                      <th className="pb-2 pr-4 font-medium">Market</th>
                      <th className="pb-2 pr-4 text-right font-medium">Price</th>
                      <th className="pb-2 pr-4 text-right font-medium">Edge</th>
                      <th className="pb-2 pr-4 text-right font-medium">Conf</th>
                      <th className="pb-2 pr-4 font-medium">Side</th>
                      <th className="pb-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    {(candidates as any[]).map((c: any, i: number) => (
                      <CandidateRow key={i} candidate={c} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : (
            <Card title="Trade Candidates">
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                No candidates in current scan. The brain filters markets by spread, volume, and time to expiry.
              </div>
            </Card>
          )}

          {/* Rejection summary */}
          {rejSummary && (
            <Card title="Rejection Reasons">
              <div className="space-y-1.5">
                {typeof rejSummary === "object" &&
                  Object.entries(rejSummary as Record<string, number>)
                    .sort((a, b) => (b[1] as number) - (a[1] as number))
                    .map(([reason, count]) => (
                      <div key={reason} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                        <span className="text-xs text-[var(--text-secondary)]">{reason}</span>
                        <span className="text-xs tabular-nums text-[var(--text-muted)]">{String(count)}</span>
                      </div>
                    ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ── Strategies ────────────────────────────────────────────────── */}
      {sub === "strategies" && (
        <div className="space-y-4">
          <Card title="Strategy Engines" action={
            <button onClick={fetchStrategies} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
              <IconRefresh size={14} />
            </button>
          }>
            {strategies ? (
              <StrategyList data={strategies} onToggle={fetchStrategies} />
            ) : (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">Loading strategies...</div>
            )}
          </Card>

          {signals.length > 0 && (
            <Card title="Recent Signals" action={<span className="text-xs text-[var(--text-muted)]">{signals.length} signals</span>}>
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                {(signals as any[]).slice(0, 20).map((s: any, i: number) => (
                  <div key={i} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium text-[var(--text-primary)] truncate">{s.ticker ?? s.market ?? "--"}</div>
                      <div className="text-[10px] text-[var(--text-muted)]">{s.strategy ?? s.source ?? ""}</div>
                    </div>
                    <div className="flex items-center gap-3 text-xs tabular-nums">
                      <span className={s.direction === "yes" ? "text-accent" : "text-[var(--danger)]"}>{s.direction?.toUpperCase()}</span>
                      <span className="text-[var(--text-muted)]">{s.confidence != null ? `${(s.confidence * 100).toFixed(0)}%` : ""}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ── Sports ────────────────────────────────────────────────────── */}
      {sub === "sports" && (
        <div className="space-y-4">
          {/* Sports Status Summary */}
          <Card title="🏀 Sports Module" action={
            <button onClick={fetchSports} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
              <IconRefresh size={14} />
            </button>
          }>
            {sportsData ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {(() => { const d = sportsData as any; return [
                    ["Active Games", d.active_games ?? d.live_games ?? 0],
                    ["Markets Found", sportsMarkets.length],
                    ["Odds Sources", d.odds_sources ?? d.active_sources ?? "--"],
                    ["Status", d.status ?? (d.enabled ? "Active" : "Inactive")],
                  ].map(([label, val]) => (
                    <div key={String(label)} className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-2.5">
                      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{String(label)}</div>
                      <div className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">{String(val)}</div>
                    </div>
                  )); })()}
                </div>
                {/* Key settings */}
                <div className="space-y-1">
                  {Object.entries(sportsData)
                    .filter(([k]) => !['active_games','live_games','status','enabled','odds_sources','active_sources'].includes(k))
                    .slice(0, 6).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
                      <span className="text-xs text-[var(--text-muted)] capitalize">{k.replace(/_/g, " ")}</span>
                      <span className="text-xs text-[var(--text-primary)] tabular-nums">{typeof v === 'object' ? JSON.stringify(v).slice(0, 40) : String(v ?? "--")}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">
                <div className="animate-shimmer h-20 rounded-lg" />
              </div>
            )}
          </Card>

          {/* Sports Markets */}
          <Card title="Sports Markets" action={<span className="text-xs text-[var(--text-muted)]">{sportsMarkets.length} markets</span>}>
            {sportsMarkets.length > 0 ? (
              <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-[var(--bg-primary)]">
                    <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                      <th className="pb-2 pr-4 font-medium">Market</th>
                      <th className="pb-2 pr-4 font-medium">Sport</th>
                      <th className="pb-2 pr-4 text-right font-medium">Yes Bid</th>
                      <th className="pb-2 pr-4 text-right font-medium">Yes Ask</th>
                      <th className="pb-2 text-right font-medium">Volume</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    {(sportsMarkets as any[]).slice(0, 50).map((m: any, i: number) => (
                      <tr key={i} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                        <td className="py-1.5 pr-4 text-xs font-medium text-[var(--text-primary)] truncate max-w-[250px]">
                          {m.title ?? m.ticker ?? "--"}
                        </td>
                        <td className="py-1.5 pr-4">
                          <span className="inline-flex rounded bg-white/[0.04] border border-white/[0.06] px-1.5 py-0.5 text-[9px] font-medium uppercase text-[var(--text-muted)]">
                            {m.sport ?? m.category ?? "--"}
                          </span>
                        </td>
                        <td className="py-1.5 pr-4 text-right text-xs tabular-nums text-accent">
                          {m.yes_bid != null ? `${m.yes_bid}¢` : "--"}
                        </td>
                        <td className="py-1.5 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">
                          {m.yes_ask != null ? `${m.yes_ask}¢` : "--"}
                        </td>
                        <td className="py-1.5 text-right text-xs tabular-nums text-[var(--text-muted)]">
                          {m.volume != null ? Number(m.volume).toLocaleString() : "--"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">No sports markets found</div>
            )}
          </Card>
        </div>
      )}

      {/* ── Intelligence ──────────────────────────────────────────────── */}
      {sub === "intelligence" && (
        <div className="space-y-4">
          <Card title="🧠 Intelligence Hub" action={
            <button onClick={fetchIntel} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
              <IconRefresh size={14} />
            </button>
          }>
            {intelDash ? (
              <div className="space-y-3">
                {/* Summary stats */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                  {(() => { const d = intelDash as any; return [
                    ["Active Sources", d.active_sources ?? d.sources_active ?? 0],
                    ["Total Signals", d.total_signals ?? d.signal_count ?? 0],
                    ["Avg Confidence", d.avg_confidence != null ? `${(d.avg_confidence * 100).toFixed(0)}%` : "--"],
                    ["Status", d.status ?? (d.enabled ? "Active" : "Inactive")],
                  ].map(([label, val]) => (
                    <div key={String(label)} className="rounded-lg bg-white/[0.02] border border-white/[0.04] p-2.5">
                      <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{String(label)}</div>
                      <div className="text-sm font-semibold tabular-nums text-[var(--text-primary)]">{String(val)}</div>
                    </div>
                  )); })()}
                </div>

                {/* Source list */}
                {(() => {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const d = intelDash as any;
                  const sources = d.sources ?? d.data_sources ?? d.source_status;
                  if (!sources || typeof sources !== 'object') return null;
                  const entries = Array.isArray(sources) ? sources : Object.entries(sources).map(([k, v]) => ({ name: k, ...(typeof v === 'object' && v !== null ? v as Record<string, unknown> : { status: v }) }));
                  if (entries.length === 0) return null;
                  return (
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Data Sources</div>
                      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                      {entries.slice(0, 12).map((src: any, idx: number) => {
                        const name = src.name ?? src.source ?? `Source ${idx + 1}`;
                        const status = src.status ?? src.state ?? 'unknown';
                        const isActive = ['active','ready','ok','running','connected'].includes(String(status).toLowerCase());
                        return (
                          <div key={idx} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className={`inline-block h-1.5 w-1.5 rounded-full ${isActive ? 'bg-accent' : 'bg-[var(--text-muted)]'}`} />
                              <span className="text-xs font-medium text-[var(--text-primary)] capitalize">{String(name).replace(/_/g, ' ')}</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs">
                              {src.signal_count != null && (
                                <span className="tabular-nums text-[var(--text-muted)]">{src.signal_count} signals</span>
                              )}
                              {src.last_update && (
                                <span className="tabular-nums text-[var(--text-muted)]">{String(src.last_update).slice(0, 19)}</span>
                              )}
                              <span className={isActive ? 'text-accent' : 'text-[var(--text-muted)]'}>{String(status)}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                {/* Remaining key-value data */}
                <div className="space-y-1">
                  {Object.entries(intelDash)
                    .filter(([k]) => !['sources','data_sources','source_status','active_sources','sources_active','total_signals','signal_count','avg_confidence','status','enabled'].includes(k))
                    .slice(0, 8).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-1.5">
                      <span className="text-xs text-[var(--text-muted)] capitalize">{k.replace(/_/g, ' ')}</span>
                      <span className="text-xs text-[var(--text-primary)] tabular-nums">
                        {typeof v === 'object' ? JSON.stringify(v).slice(0, 50) : String(v ?? '--')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">
                <div className="animate-shimmer h-20 rounded-lg" />
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ── Alerts ────────────────────────────────────────────────────── */}
      {sub === "alerts" && (
        <Card title="Alerts" action={
          <span className="text-xs text-[var(--text-muted)]">{alertStats.unread} unread / {alertStats.total} total</span>
        }>
          {alerts.length > 0 ? (
            <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {(alerts as any[]).map((a: any, i: number) => (
                <div key={i} className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2",
                  a.severity === "critical"
                    ? "bg-[var(--danger)]/5 border-[var(--danger)]/20"
                    : a.severity === "warning"
                      ? "bg-[var(--warning)]/5 border-[var(--warning)]/20"
                      : "bg-white/[0.02] border-white/[0.04]",
                )}>
                  <IconCircle size={6} className={
                    a.severity === "critical" ? "text-[var(--danger)]" :
                    a.severity === "warning" ? "text-[var(--warning)]" : "text-[var(--info)]"
                  } />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-[var(--text-primary)]">{a.message ?? a.title ?? "--"}</div>
                    <div className="text-[10px] text-[var(--text-muted)]">{a.source ?? ""} {a.timestamp ?? ""}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-[var(--text-muted)]">No alerts</div>
          )}
        </Card>
      )}
    </div>
  );
}

/* ── Candidate row ────────────────────────────────────────────────────── */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CandidateRow({ candidate: c }: { candidate: any }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors cursor-pointer"
      >
        <td className="py-2 pr-4 text-xs font-medium text-[var(--text-primary)] truncate max-w-[220px]">
          <div className="flex items-center gap-1.5">
            <IconChevronRight size={12} className={cn("text-[var(--text-muted)] transition-transform", expanded && "rotate-90")} />
            {c.ticker ?? c.title ?? "--"}
          </div>
        </td>
        <td className="py-2 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">
          {c.price_cents ?? c.midpoint ?? "--"}c
        </td>
        <td className="py-2 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">
          {c.edge != null ? `${(c.edge * 100).toFixed(1)}c` : "--"}
        </td>
        <td className="py-2 pr-4 text-right text-xs tabular-nums text-[var(--text-secondary)]">
          {c.confidence != null ? `${(c.confidence * 100).toFixed(0)}%` : "--"}
        </td>
        <td className="py-2 pr-4">
          <span className={`text-[10px] font-semibold uppercase ${c.side === "yes" ? "text-accent" : c.side === "no" ? "text-[var(--danger)]" : "text-[var(--text-muted)]"}`}>
            {c.side ?? "--"}
          </span>
        </td>
        <td className="py-2 text-xs text-[var(--text-muted)]">
          {c.status ?? c.stage ?? "candidate"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} className="p-3 bg-white/[0.01]">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 text-xs">
              {c.spread != null && <MiniInfo label="Spread" value={`${c.spread}c`} />}
              {c.volume != null && <MiniInfo label="Volume" value={String(c.volume)} />}
              {c.category != null && <MiniInfo label="Category" value={c.category} />}
              {c.predicted_prob != null && <MiniInfo label="Predicted" value={`${(c.predicted_prob * 100).toFixed(1)}%`} />}
              {c.error && <MiniInfo label="Error" value={c.error} />}
              {c.rejection_reason && <MiniInfo label="Rejection" value={c.rejection_reason} />}
            </div>
            {c.confidence_breakdown && (
              <div className="mt-2 space-y-1">
                <div className="text-[10px] text-[var(--text-muted)] uppercase">Confidence Factors</div>
                {(c.confidence_breakdown.factors ?? []).map((f: { name: string; score: number; reason: string }, fi: number) => (
                  <div key={fi} className="flex items-center justify-between text-[10px]">
                    <span className="text-[var(--text-secondary)]">{f.name}</span>
                    <span className="tabular-nums text-[var(--text-muted)]">{(f.score * 100).toFixed(0)}% — {f.reason}</span>
                  </div>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

/* ── Strategy list ────────────────────────────────────────────────────── */

function StrategyList({ data, onToggle }: { data: Record<string, unknown>; onToggle: () => void }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const engines = (data as any).engines ?? (data as any).strategies ?? [];
  if (!Array.isArray(engines) || engines.length === 0) {
    return <div className="py-6 text-center text-sm text-[var(--text-muted)]">No strategy engines found</div>;
  }
  return (
    <div className="space-y-1.5">
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {engines.map((e: any, i: number) => (
        <div key={i} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-[var(--text-primary)]">{e.name ?? e.id ?? `Strategy ${i + 1}`}</div>
            <div className="text-[10px] text-[var(--text-muted)]">{e.description ?? ""}</div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs tabular-nums text-[var(--text-muted)]">{e.signal_count ?? 0} signals</span>
            <button
              onClick={async () => {
                try {
                  await api.strategies.toggle(e.id ?? e.name, !(e.enabled ?? e.active));
                  onToggle();
                } catch { /* ignore */ }
              }}
              className={cn(
                "rounded px-2 py-1 text-[10px] font-semibold uppercase transition-colors",
                (e.enabled ?? e.active)
                  ? "bg-accent/10 text-accent border border-accent/20"
                  : "bg-white/[0.04] text-[var(--text-muted)] border border-white/[0.08]",
              )}
            >
              {(e.enabled ?? e.active) ? "On" : "Off"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Mini info ────────────────────────────────────────────────────────── */

function MiniInfo({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-[var(--text-muted)] uppercase">{label}</div>
      <div className="text-xs text-[var(--text-secondary)] tabular-nums">{value}</div>
    </div>
  );
}
