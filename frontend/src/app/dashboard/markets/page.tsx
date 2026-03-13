"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { IconSearch, IconRefresh, IconCircle } from "@/components/ui/Icons";
import { api, type Market } from "@/lib/api";

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>("sports");

  const categories = ["Sports", "All", "Politics", "Economics", "Crypto", "Climate", "Tech", "Science"];

  const fetchMarkets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.markets.list({ category: category || undefined, search: search || undefined, limit: 100 });
      // Sort by volume (most active first) so users see relevant markets
      const sorted = [...res.markets].sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0));
      setMarkets(sorted);
      setTotal(res.total);
      setSource(res.source);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load markets");
    } finally {
      setLoading(false);
    }
  }, [category, search]);

  useEffect(() => { fetchMarkets(); const iv = setInterval(fetchMarkets, 30000); return () => clearInterval(iv); }, [fetchMarkets]);
  useEffect(() => { const t = setTimeout(fetchMarkets, 500); return () => clearTimeout(t); }, [search, fetchMarkets]);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Markets</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1 flex items-center gap-2">
            <span className="tabular-nums">{total} markets</span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span className="flex items-center gap-1">
              <IconCircle size={5} className={source === "live" ? "text-accent" : "text-[var(--warning)]"} />
              {source === "live" ? "Live" : "Cached"}
            </span>
            <span className="h-1 w-1 rounded-full bg-[var(--text-muted)]/50" />
            <span>Auto-refresh 30s</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              type="text"
              placeholder="Search markets..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="rounded-xl glass pl-9 pr-4 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] w-64 focus:border-accent/30 transition-all"
            />
          </div>
          <button onClick={fetchMarkets} className="rounded-xl glass px-4 py-2 text-xs font-medium text-accent hover:bg-accent/5 transition-all">
            <IconRefresh size={14} />
          </button>
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex gap-2 flex-wrap">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat === "All" ? null : cat.toLowerCase())}
            className={`rounded-xl px-4 py-2 text-xs font-medium transition-all duration-200 ${
              (cat === "All" && !category) || category === cat.toLowerCase()
                ? "bg-accent/10 text-accent border border-accent/20"
                : "glass text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-white/[0.03]"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {error && <div className="rounded-xl border border-loss/20 bg-loss/5 p-4 text-sm text-loss">{error}</div>}

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] text-left text-xs text-[var(--text-muted)] uppercase tracking-wider">
                <th className="pb-3 pr-4 font-medium">Market</th>
                <th className="pb-3 pr-4 text-right font-medium">Yes Bid</th>
                <th className="pb-3 pr-4 text-right font-medium">Yes Ask</th>
                <th className="pb-3 pr-4 text-right font-medium">Last</th>
                <th className="pb-3 pr-4 text-right font-medium">Spread</th>
                <th className="pb-3 pr-4 text-right font-medium">Volume</th>
                <th className="pb-3 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && markets.length === 0 ? (
                <tr><td colSpan={7} className="py-16 text-center text-[var(--text-muted)]"><div className="animate-shimmer rounded-lg p-4">Loading live markets from Kalshi...</div></td></tr>
              ) : markets.length === 0 ? (
                <tr><td colSpan={7} className="py-16 text-center text-[var(--text-muted)]">No markets found {search ? `matching "${search}"` : ""}</td></tr>
              ) : (
                markets.map((m) => (
                  <tr key={m.ticker} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors cursor-pointer group">
                    <td className="py-3.5 pr-4">
                      <div className="text-sm font-medium text-[var(--text-primary)] group-hover:text-accent transition-colors">{m.title || m.ticker}</div>
                      <div className="text-xs text-[var(--text-muted)] font-mono">{m.ticker}</div>
                    </td>
                    <td className="py-3.5 pr-4 text-right tabular-nums">
                      {m.yes_bid != null ? <span className="text-accent">{(m.yes_bid * 100).toFixed(0)}¢</span> : <span className="text-[var(--text-muted)]">—</span>}
                    </td>
                    <td className="py-3.5 pr-4 text-right tabular-nums">
                      {m.yes_ask != null ? <span className="text-loss">{(m.yes_ask * 100).toFixed(0)}¢</span> : <span className="text-[var(--text-muted)]">—</span>}
                    </td>
                    <td className="py-3.5 pr-4 text-right tabular-nums text-[var(--text-primary)] font-medium">
                      {m.last_price != null ? `${(m.last_price * 100).toFixed(0)}¢` : "—"}
                    </td>
                    <td className="py-3.5 pr-4 text-right tabular-nums">
                      {m.spread != null ? (
                        <span className={m.spread < 0.05 ? "text-accent" : m.spread < 0.10 ? "text-[var(--warning)]" : "text-loss"}>
                          {(m.spread * 100).toFixed(0)}¢
                        </span>
                      ) : <span className="text-[var(--text-muted)]">—</span>}
                    </td>
                    <td className="py-3.5 pr-4 text-right tabular-nums text-[var(--text-muted)]">
                      {m.volume != null ? formatVolume(m.volume) : "—"}
                    </td>
                    <td className="py-3.5 text-right">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${
                        m.status === "active" ? "bg-accent/10 text-accent" : m.status === "closed" ? "bg-loss/10 text-loss" : "bg-[var(--warning)]/10 text-[var(--warning)]"
                      }`}>
                        {m.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}
