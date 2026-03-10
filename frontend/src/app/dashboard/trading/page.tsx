"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { IconSearch, IconCircle } from "@/components/ui/Icons";
import { api, type Market, type Fill, type Balance } from "@/lib/api";

export default function TradingPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [fills, setFills] = useState<Fill[]>([]);
  const [search, setSearch] = useState("");
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [action] = useState<"buy">("buy");
  const [priceCents, setPriceCents] = useState(50);
  const [quantity, setQuantity] = useState(1);
  const [orderType, setOrderType] = useState<"limit" | "market">("limit");
  const [submitting, setSubmitting] = useState(false);
  const [orderResult, setOrderResult] = useState<{ success: boolean; message: string } | null>(null);

  const cost = orderType === "limit" ? (priceCents * quantity) : 0;
  const maxProfit = orderType === "limit" ? ((100 - priceCents) * quantity) : 0;

  useEffect(() => {
    const load = async () => {
      const [mRes, bRes, fRes] = await Promise.all([
        api.markets.list({ limit: 50 }).catch(() => ({ markets: [], total: 0, source: "" })),
        api.portfolio.balance().catch(() => null),
        api.portfolio.fills({ limit: 20 }).catch(() => []),
      ]);
      setMarkets(mRes.markets);
      setBalance(bRes);
      setFills(fRes);
    };
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, []);

  const filteredMarkets = search
    ? markets.filter(m => (m.title?.toLowerCase().includes(search.toLowerCase())) || m.ticker.toLowerCase().includes(search.toLowerCase()))
    : markets;

  const submitOrder = async () => {
    if (!selectedMarket) return;
    setSubmitting(true);
    setOrderResult(null);
    try {
      const res = await api.orders.create({ ticker: selectedMarket.ticker, side, action, count: quantity, price_cents: orderType === "limit" ? priceCents : undefined, order_type: orderType });
      setOrderResult({ success: res.success, message: res.success ? `Order placed: ${res.order_id?.slice(0, 8)}...` : (res.error || "Order failed") });
      const [bRes, fRes] = await Promise.all([api.portfolio.balance().catch(() => null), api.portfolio.fills({ limit: 20 }).catch(() => [])]);
      if (bRes) setBalance(bRes);
      setFills(fRes);
    } catch (e: unknown) {
      setOrderResult({ success: false, message: e instanceof Error ? e.message : "Order failed" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">Trading</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Paper trading on Kalshi Demo API <span className="mx-1.5 text-[var(--text-muted)]/30">|</span> Balance: <span className="text-[var(--text-primary)] font-medium">${balance?.balance_dollars ?? "—"}</span>
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Order Form */}
        <Card title={selectedMarket ? `Order: ${selectedMarket.ticker}` : "Place Order"} className="lg:col-span-1">
          <div className="space-y-4">
            <div className="relative">
              <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Market</label>
              <div className="relative mt-1.5">
                <IconSearch size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  type="text"
                  placeholder="Search & select..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded-xl bg-white/[0.03] border border-white/[0.06] pl-9 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-accent/30 transition-all"
                />
              </div>
              {search && filteredMarkets.length > 0 && !selectedMarket && (
                <div className="absolute z-10 mt-1 w-full max-h-40 overflow-y-auto rounded-xl glass-strong shadow-xl">
                  {filteredMarkets.slice(0, 8).map(m => (
                    <button key={m.ticker} onClick={() => { setSelectedMarket(m); setSearch(m.ticker); }}
                      className="w-full px-4 py-2.5 text-left text-sm text-[var(--text-primary)] hover:bg-white/[0.04] border-b border-white/[0.04] transition-colors">
                      <div className="font-medium">{m.ticker}</div>
                      <div className="text-xs text-[var(--text-muted)] truncate">{m.title}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedMarket && (
              <>
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
                  <div className="text-xs text-[var(--text-muted)] truncate">{selectedMarket.title}</div>
                  <div className="mt-2 flex items-center gap-4 text-sm">
                    <span className="text-accent tabular-nums">Bid: {selectedMarket.yes_bid != null ? `${(selectedMarket.yes_bid * 100).toFixed(0)}¢` : "—"}</span>
                    <span className="text-loss tabular-nums">Ask: {selectedMarket.yes_ask != null ? `${(selectedMarket.yes_ask * 100).toFixed(0)}¢` : "—"}</span>
                    <span className="text-[var(--text-primary)] tabular-nums font-medium">Last: {selectedMarket.last_price != null ? `${(selectedMarket.last_price * 100).toFixed(0)}¢` : "—"}</span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <button type="button" onClick={() => setSide("yes")}
                    className={`rounded-xl py-3 text-sm font-semibold transition-all ${side === "yes" ? "bg-accent/15 text-accent border border-accent/25 glow-accent" : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"}`}>
                    YES
                  </button>
                  <button type="button" onClick={() => setSide("no")}
                    className={`rounded-xl py-3 text-sm font-semibold transition-all ${side === "no" ? "bg-loss/15 text-loss border border-loss/25 glow-danger" : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"}`}>
                    NO
                  </button>
                </div>

                <div className="flex gap-2">
                  {(["limit", "market"] as const).map((t) => (
                    <button key={t} onClick={() => setOrderType(t)}
                      className={`flex-1 rounded-xl py-2 text-xs font-semibold uppercase tracking-wider transition-all ${orderType === t ? "bg-accent/10 text-accent border border-accent/20" : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)]"}`}>
                      {t}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {orderType === "limit" && (
                    <div>
                      <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Price (¢)</label>
                      <input type="number" min={1} max={99} value={priceCents} onChange={(e) => setPriceCents(Number(e.target.value))}
                        className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] tabular-nums focus:border-accent/30 transition-all" />
                    </div>
                  )}
                  <div className={orderType === "market" ? "col-span-2" : ""}>
                    <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Quantity</label>
                    <input type="number" min={1} max={100} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))}
                      className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] tabular-nums focus:border-accent/30 transition-all" />
                  </div>
                </div>

                {orderType === "limit" && (
                  <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4 text-xs text-[var(--text-muted)] space-y-1.5">
                    <div className="flex justify-between"><span>Est. Cost</span><span className="text-[var(--text-primary)] tabular-nums font-medium">${(cost / 100).toFixed(2)}</span></div>
                    <div className="flex justify-between"><span>Max Profit</span><span className="text-accent tabular-nums font-medium">${(maxProfit / 100).toFixed(2)}</span></div>
                  </div>
                )}

                <button onClick={submitOrder} disabled={submitting}
                  className={`w-full rounded-xl py-3 text-sm font-bold tracking-wide transition-all ${side === "yes" ? "bg-accent text-white hover:bg-accent/90" : "bg-loss text-white hover:bg-loss/90"} ${submitting ? "opacity-50" : ""}`}>
                  {submitting ? "Submitting..." : `BUY ${side.toUpperCase()} × ${quantity}`}
                </button>

                {orderResult && (
                  <div className={`rounded-xl p-3 text-sm ${orderResult.success ? "bg-accent/10 text-accent border border-accent/20" : "bg-loss/10 text-loss border border-loss/20"}`}>
                    {orderResult.message}
                  </div>
                )}
              </>
            )}
          </div>
        </Card>

        {/* Market List */}
        <Card title="Active Markets" className="lg:col-span-1">
          <div className="space-y-1 max-h-[500px] overflow-y-auto pr-1">
            {markets.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">Loading markets...</div>
            ) : (
              markets.slice(0, 30).map(m => (
                <button key={m.ticker} onClick={() => { setSelectedMarket(m); setSearch(m.ticker); }}
                  className={`w-full rounded-xl px-4 py-2.5 text-left transition-all ${
                    selectedMarket?.ticker === m.ticker ? "bg-accent/[0.08] border border-accent/20" : "hover:bg-white/[0.03] border border-transparent"
                  }`}>
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-medium text-[var(--text-primary)] truncate max-w-[60%]">{m.title || m.ticker}</div>
                    <div className="text-xs tabular-nums text-[var(--text-muted)] font-mono">{m.last_price != null ? `${(m.last_price * 100).toFixed(0)}¢` : "—"}</div>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* Recent Fills */}
        <Card title="Recent Trades" action={<span className="text-xs text-[var(--text-muted)]">{fills.length} fills</span>}>
          <div className="space-y-1 max-h-[500px] overflow-y-auto pr-1">
            {fills.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">No trades yet</div>
            ) : (
              fills.map((f, i) => (
                <div key={i} className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5 text-sm">
                  <div className="flex items-center gap-2">
                    <IconCircle size={6} className={f.action === "buy" ? "text-accent" : "text-loss"} />
                    <span className={`font-medium ${f.action === "buy" ? "text-accent" : "text-loss"}`}>{f.action.toUpperCase()}</span>
                    <span className="text-[var(--text-primary)]">{f.ticker}</span>
                    <span className={`text-xs ${f.side === "yes" ? "text-accent" : "text-loss"}`}>{f.side.toUpperCase()}</span>
                  </div>
                  <div className="text-xs text-[var(--text-muted)] tabular-nums font-mono">{f.count ?? "?"} @ {f.price_dollars ? `$${f.price_dollars}` : "mkt"}</div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
