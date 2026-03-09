"use client";

import { useEffect, useState, useCallback } from "react";
import { Card } from "@/components/ui/Card";
import { api, type Market } from "@/lib/api";

export default function MarketsPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [total, setTotal] = useState(0);
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | null>(null);

  const categories = ["All", "Politics", "Economics", "Crypto", "Climate", "Sports", "Tech", "Science"];

  const fetchMarkets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.markets.list({
        category: category || undefined,
        search: search || undefined,
        limit: 100,
      });
      setMarkets(res.markets);
      setTotal(res.total);
      setSource(res.source);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load markets");
    } finally {
      setLoading(false);
    }
  }, [category, search]);

  useEffect(() => {
    fetchMarkets();
    const interval = setInterval(fetchMarkets, 30000);
    return () => clearInterval(interval);
  }, [fetchMarkets]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(fetchMarkets, 500);
    return () => clearTimeout(timer);
  }, [search, fetchMarkets]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Markets</h1>
          <p className="text-xs text-[var(--muted)] mt-1">
            {total} markets • {source === "live" ? "🟢 Live from Kalshi" : "📦 Cached"} • Auto-refresh 30s
          </p>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Search markets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-md border border-[var(--card-border)] bg-[var(--card)] px-3 py-1.5 text-sm text-white placeholder:text-[var(--muted)] focus:border-[var(--accent)] focus:outline-none w-64"
          />
          <button onClick={fetchMarkets} className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs text-white hover:opacity-90 transition-opacity">
            Refresh
          </button>
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex gap-2 flex-wrap">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setCategory(cat === "All" ? null : cat.toLowerCase())}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              (cat === "All" && !category) || category === cat.toLowerCase()
                ? "bg-[var(--accent)] text-white"
                : "bg-white/5 text-[var(--muted)] hover:bg-white/10"
            }`}
          >
            {cat}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      {/* Markets table */}
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--card-border)] text-left text-xs text-[var(--muted)]">
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
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[var(--muted)]">
                    <div className="animate-pulse">Loading live markets from Kalshi...</div>
                  </td>
                </tr>
              ) : markets.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[var(--muted)]">
                    No markets found {search ? `matching "${search}"` : ""}
                  </td>
                </tr>
              ) : (
                markets.map((m) => (
                  <tr
                    key={m.ticker}
                    className="border-b border-white/5 hover:bg-white/[0.02] transition-colors cursor-pointer"
                  >
                    <td className="py-3 pr-4">
                      <div className="text-sm font-medium text-white">{m.title || m.ticker}</div>
                      <div className="text-xs text-[var(--muted)]">{m.ticker}</div>
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums">
                      {m.yes_bid != null ? (
                        <span className="text-green-400">{(m.yes_bid * 100).toFixed(0)}¢</span>
                      ) : <span className="text-[var(--muted)]">—</span>}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums">
                      {m.yes_ask != null ? (
                        <span className="text-red-400">{(m.yes_ask * 100).toFixed(0)}¢</span>
                      ) : <span className="text-[var(--muted)]">—</span>}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums text-white">
                      {m.last_price != null ? `${(m.last_price * 100).toFixed(0)}¢` : "—"}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums">
                      {m.spread != null ? (
                        <span className={m.spread < 0.05 ? "text-green-400" : m.spread < 0.10 ? "text-yellow-400" : "text-red-400"}>
                          {(m.spread * 100).toFixed(0)}¢
                        </span>
                      ) : <span className="text-[var(--muted)]">—</span>}
                    </td>
                    <td className="py-3 pr-4 text-right tabular-nums text-[var(--muted)]">
                      {m.volume != null ? formatVolume(m.volume) : "—"}
                    </td>
                    <td className="py-3 text-right">
                      <span className={`inline-block rounded-full px-2 py-0.5 text-xs ${
                        m.status === "active"
                          ? "bg-green-500/20 text-green-400"
                          : m.status === "closed"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-yellow-500/20 text-yellow-400"
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
