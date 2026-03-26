"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { IconRefresh, IconCircle, IconTrendUp, IconTrendDown } from "@/components/ui/Icons";
import { api, type SportsMarket, type VegasGame } from "@/lib/api";

type SportsStatus = Record<string, unknown>;

export default function SportsPage() {
  const [status, setStatus] = useState<SportsStatus | null>(null);
  const [marketsBySport, setMarketsBySport] = useState<Record<string, SportsMarket[]>>({});
  const [totalSports, setTotalSports] = useState(0);
  const [vegasGames, setVegasGames] = useState<VegasGame[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"markets" | "odds" | "live" | "performance">("markets");
  const [performance, setPerformance] = useState<Record<string, unknown> | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [statusRes, marketsRes, oddsRes, perfRes] = await Promise.allSettled([
        api.sports.status(),
        api.sports.markets(),
        api.sports.odds(),
        api.sports.performance(),
      ]);

      if (statusRes.status === "fulfilled") setStatus(statusRes.value);
      if (marketsRes.status === "fulfilled") {
        setMarketsBySport(marketsRes.value.by_sport);
        setTotalSports(marketsRes.value.total_sports_markets);
      }
      if (oddsRes.status === "fulfilled") setVegasGames(oddsRes.value.games);
      if (perfRes.status === "fulfilled") setPerformance(perfRes.value);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load sports data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 30000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  const allMarkets = Object.values(marketsBySport).flat();
  const sportNames = Object.keys(marketsBySport);
  const components = (status?.components ?? {}) as Record<string, string>;
  const componentCount = Object.values(components).filter((v) => v === "ready").length;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">🏀 Sports Trading</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1 flex items-center gap-2">
            <span className="tabular-nums">{totalSports} sports markets</span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span className="flex items-center gap-1">
              <IconCircle size={5} className={componentCount >= 5 ? "text-accent" : "text-[var(--warning)]"} />
              {componentCount}/{Object.keys(components).length} components
            </span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span>{vegasGames.length} Vegas lines</span>
          </p>
        </div>
        <button onClick={fetchAll} className="rounded-xl glass px-4 py-2 text-xs font-medium text-accent hover:bg-accent/5 transition-all">
          <IconRefresh size={14} />
        </button>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Sports Markets" value={totalSports} />
        <StatCard label="Vegas Lines" value={vegasGames.length} />
        <StatCard label="Sports" value={sportNames.length} />
        <StatCard
          label="System Health"
          value={`${componentCount}/${Object.keys(components).length}`}
          accent={componentCount >= 5}
        />
      </div>

      {error && <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">{error}</div>}

      {/* Tabs */}
      <div className="flex gap-2">
        {(["markets", "odds", "live", "performance"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-xl px-4 py-2 text-xs font-medium capitalize transition-all duration-200 ${
              activeTab === tab
                ? "bg-accent/10 text-accent border border-accent/20"
                : "glass text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.03]"
            }`}
          >
            {tab === "markets" ? "Sports Markets" : tab === "odds" ? "Vegas Odds" : tab === "performance" ? "📊 Performance" : "Live Games"}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading && !allMarkets.length ? (
        <Card><div className="py-16 text-center text-[var(--text-muted)] animate-shimmer">Loading sports data...</div></Card>
      ) : activeTab === "markets" ? (
        <MarketsTab marketsBySport={marketsBySport} />
      ) : activeTab === "odds" ? (
        <OddsTab games={vegasGames} />
      ) : activeTab === "performance" ? (
        <PerformanceTab data={performance} />
      ) : (
        <LiveTab />
      )}
    </div>
  );
}

/* ── Stat Card ────────────────────────────────────────────── */

function StatCard({ label, value, accent }: { label: string; value: number | string; accent?: boolean }) {
  return (
    <Card>
      <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] font-medium">{label}</p>
      <p className={`text-2xl font-bold mt-1 tabular-nums ${accent ? "text-accent" : "text-[var(--text-primary)]"}`}>
        {value}
      </p>
    </Card>
  );
}

/* ── Markets Tab ──────────────────────────────────────────── */

function MarketsTab({ marketsBySport }: { marketsBySport: Record<string, SportsMarket[]> }) {
  const sportLabels: Record<string, string> = {
    nba: "🏀 NBA",
    nfl: "🏈 NFL",
    nhl: "🏒 NHL",
    mlb: "⚾ MLB",
    ncaab: "🏀 NCAAB",
    soccer: "⚽ Soccer",
    mma: "🥊 MMA",
    unknown: "❓ Other",
  };

  if (!Object.keys(marketsBySport).length) {
    return <Card><div className="py-12 text-center text-[var(--text-muted)]">No sports markets active right now</div></Card>;
  }

  return (
    <div className="space-y-6">
      {Object.entries(marketsBySport).map(([sport, markets]) => (
        <Card key={sport} title={sportLabels[sport] || `🎯 ${sport.toUpperCase()}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                  <th className="pb-3 pr-4 font-medium">Market</th>
                  <th className="pb-3 pr-4 text-right font-medium">Kalshi Mid</th>
                  <th className="pb-3 pr-4 text-right font-medium">Vegas</th>
                  <th className="pb-3 pr-4 text-right font-medium">Edge</th>
                  <th className="pb-3 pr-4 text-right font-medium">Volume</th>
                  <th className="pb-3 text-right font-medium">Type</th>
                </tr>
              </thead>
              <tbody>
                {markets.map((m) => {
                  const edge = m.kalshi_vs_vegas;
                  return (
                    <tr key={m.ticker} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                      <td className="py-3 pr-4">
                        <div className="text-sm font-medium text-[var(--text-primary)]">{m.title || m.ticker}</div>
                        <div className="text-xs text-[var(--text-muted)] font-mono flex items-center gap-2">
                          {m.ticker}
                          {m.is_live && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-loss/10 px-1.5 py-0.5 text-[9px] font-bold text-loss uppercase">
                              <IconCircle size={4} className="text-loss animate-pulse" />
                              Live
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums text-[var(--text-primary)]">
                        {m.midpoint > 0 ? `${(m.midpoint * 100).toFixed(0)}¢` : "—"}
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums">
                        {m.vegas_home_prob != null ? (
                          <span className="text-[var(--text-secondary)]">{(m.vegas_home_prob * 100).toFixed(0)}%</span>
                        ) : (
                          <span className="text-[var(--text-muted)]">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums">
                        {edge != null ? (
                          <span className={`flex items-center justify-end gap-1 ${edge > 0 ? "text-accent" : "text-loss"}`}>
                            {edge > 0 ? <IconTrendUp size={12} /> : <IconTrendDown size={12} />}
                            {(Math.abs(edge) * 100).toFixed(1)}%
                          </span>
                        ) : (
                          <span className="text-[var(--text-muted)]">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums text-[var(--text-muted)]">
                        {m.volume > 0 ? formatVolume(m.volume) : "—"}
                      </td>
                      <td className="py-3 text-right">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                          m.market_type === "MONEYLINE"
                            ? "bg-accent/10 text-accent"
                            : m.market_type === "SPREAD"
                            ? "bg-[var(--warning)]/10 text-[var(--warning)]"
                            : m.market_type === "TOTAL"
                            ? "bg-blue-500/10 text-blue-400"
                            : m.market_type === "PROP"
                            ? "bg-purple-500/10 text-purple-400"
                            : "bg-white/5 text-[var(--text-muted)]"
                        }`}>
                          {m.market_type || "?"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ── Odds Tab ─────────────────────────────────────────────── */

function OddsTab({ games }: { games: VegasGame[] }) {
  if (!games.length) {
    return <Card><div className="py-12 text-center text-[var(--text-muted)]">No Vegas odds cached. Odds refresh automatically.</div></Card>;
  }

  // Group by sport
  const bySport: Record<string, VegasGame[]> = {};
  for (const g of games) {
    const sport = g.sport.split("_")[1]?.toUpperCase() || g.sport;
    bySport[sport] = bySport[sport] || [];
    bySport[sport].push(g);
  }

  return (
    <div className="space-y-6">
      {Object.entries(bySport).map(([sport, sportGames]) => (
        <Card key={sport} title={`Vegas Lines — ${sport}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                  <th className="pb-3 pr-4 font-medium">Matchup</th>
                  <th className="pb-3 pr-4 text-right font-medium">Home Win</th>
                  <th className="pb-3 pr-4 text-right font-medium">Away Win</th>
                  <th className="pb-3 pr-4 text-right font-medium">Spread</th>
                  <th className="pb-3 pr-4 text-right font-medium">Total</th>
                  <th className="pb-3 text-right font-medium">Books</th>
                </tr>
              </thead>
              <tbody>
                {sportGames.map((g) => (
                  <tr key={g.game_id} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 pr-4">
                      <div className="text-sm font-medium text-[var(--text-primary)]">{g.home_team} vs {g.away_team}</div>
                      <div className="text-xs text-[var(--text-muted)]">{formatTime(g.commence_time)}</div>
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums">
                      <span className={g.consensus_home_prob > 0.5 ? "text-accent font-medium" : "text-[var(--text-secondary)]"}>
                        {(g.consensus_home_prob * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums">
                      <span className={g.consensus_away_prob > 0.5 ? "text-accent font-medium" : "text-[var(--text-secondary)]"}>
                        {(g.consensus_away_prob * 100).toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums text-[var(--text-muted)]">
                      {g.consensus_spread != null ? (g.consensus_spread > 0 ? `+${g.consensus_spread}` : g.consensus_spread) : "—"}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums text-[var(--text-muted)]">
                      {g.consensus_total != null ? `O/U ${g.consensus_total}` : "—"}
                    </td>
                    <td className="py-3 text-right tabular-nums text-[var(--text-muted)]">{g.num_bookmakers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ── Live Tab ─────────────────────────────────────────────── */

function LiveTab() {
  const [liveData, setLiveData] = useState<Record<string, unknown> | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [signals, setSignals] = useState<any>(null);

  useEffect(() => {
    async function fetch() {
      const [l, s] = await Promise.allSettled([api.sports.live(), api.sports.signals()]);
      if (l.status === "fulfilled") setLiveData(l.value);
      if (s.status === "fulfilled") setSignals(s.value);
    }
    fetch();
    const iv = setInterval(fetch, 15000);
    return () => clearInterval(iv);
  }, []);

  const games = (liveData?.games ?? []) as Array<Record<string, unknown>>;
  const sigList = signals?.signals ?? [];

  return (
    <div className="space-y-6">
      {/* Live Games */}
      <Card title="Live Games">
        {games.length === 0 ? (
          <div className="py-8 text-center text-[var(--text-muted)]">No live games right now</div>
        ) : (
          <div className="grid gap-3">
            {games.map((g, i) => (
              <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-[var(--text-primary)]">
                    {String(g.home_team || "Home")} vs {String(g.away_team || "Away")}
                  </div>
                  <div className="text-xs text-[var(--text-muted)] mt-1">
                    {String(g.sport_key || "")} · Score: {String(g.home_score ?? "?")}–{String(g.away_score ?? "?")}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-[var(--text-muted)]">Progress</div>
                  <div className="text-sm font-bold text-accent tabular-nums">{String(g.progress_pct ?? "0")}%</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Active Signals */}
      <Card title="Trading Signals">
        {sigList.length === 0 ? (
          <div className="py-8 text-center text-[var(--text-muted)]">No active trading signals</div>
        ) : (
          <div className="space-y-2">
            {sigList.map((s: Record<string, unknown>, i: number) => (
              <div key={i} className="rounded-xl border border-accent/10 bg-accent/5 p-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-accent">{String(s.ticker)}</div>
                  <div className="text-xs text-[var(--text-muted)]">{String(s.reason)}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-[var(--text-muted)]">{String(s.side)} · Str: {Number(s.strength).toFixed(2)}</div>
                  <div className="text-xs text-[var(--text-muted)]">{Number(s.age_seconds).toFixed(0)}s ago</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ── Performance Tab ──────────────────────────────────────── */

function PerformanceTab({ data }: { data: Record<string, unknown> | null }) {
  if (!data) {
    return (
      <Card>
        <div className="py-12 text-center text-[var(--text-muted)]">
          Sports performance data not available — monitor may not be initialized.
        </div>
      </Card>
    );
  }

  const entries = Object.entries(data).filter(([k]) => !k.startsWith("_"));

  // Try to extract common performance fields
  const totalTrades = Number(data.total_trades ?? data.trades ?? 0);
  const wins = Number(data.wins ?? 0);
  const losses = Number(data.losses ?? 0);
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : "0.0";
  const pnl = Number(data.total_pnl ?? data.pnl ?? 0);
  const bySport = (data.by_sport ?? data.sport_breakdown ?? {}) as Record<string, Record<string, unknown>>;

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard label="Total Trades" value={totalTrades} />
        <StatCard label="Win Rate" value={`${winRate}%`} accent={Number(winRate) >= 50} />
        <StatCard label="Wins / Losses" value={`${wins} / ${losses}`} />
        <StatCard label="P&L" value={pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`} accent={pnl >= 0} />
      </div>

      {/* By-Sport Breakdown */}
      {Object.keys(bySport).length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Performance by Sport</h3>
          <div className="space-y-2">
            {Object.entries(bySport).map(([sport, stats]) => (
              <div key={sport} className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3 flex items-center justify-between">
                <div>
                  <span className="text-sm font-semibold text-[var(--text-primary)] uppercase">{sport}</span>
                  <div className="text-xs text-[var(--text-muted)]">
                    {String(stats.trades ?? stats.total ?? 0)} trades
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-sm font-bold tabular-nums ${Number(stats.pnl ?? 0) >= 0 ? "text-accent" : "text-loss"}`}>
                    {Number(stats.pnl ?? 0) >= 0 ? "+" : ""}${Number(stats.pnl ?? 0).toFixed(2)}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {String(stats.win_rate ?? "?")}% WR
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Raw Performance Data */}
      <Card>
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Full Performance Data</h3>
        <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
          {entries.map(([key, val]) => (
            <div key={key} className="flex items-center justify-between rounded-lg bg-white/[0.02] border border-white/[0.04] px-3 py-2">
              <span className="text-xs text-[var(--text-muted)]">{key.replace(/_/g, " ")}</span>
              <span className="text-xs font-mono text-[var(--text-primary)] tabular-nums truncate max-w-[200px]">
                {typeof val === "object" ? JSON.stringify(val) : String(val)}
              </span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── Helpers ──────────────────────────────────────────────── */

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
      " " +
      d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}
