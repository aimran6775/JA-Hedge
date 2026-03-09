"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/Card";
import { api, type Market, type Fill, type Balance } from "@/lib/api";

export default function TradingPage() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [fills, setFills] = useState<Fill[]>([]);
  const [search, setSearch] = useState("");

  // Order form
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
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  const filteredMarkets = search
    ? markets.filter(m =>
        (m.title?.toLowerCase().includes(search.toLowerCase())) ||
        m.ticker.toLowerCase().includes(search.toLowerCase())
      )
    : markets;

  const submitOrder = async () => {
    if (!selectedMarket) return;
    setSubmitting(true);
    setOrderResult(null);
    try {
      const res = await api.orders.create({
        ticker: selectedMarket.ticker,
        side,
        action,
        count: quantity,
        price_cents: orderType === "limit" ? priceCents : undefined,
        order_type: orderType,
      });
      setOrderResult({
        success: res.success,
        message: res.success ? `Order placed! ID: ${res.order_id?.slice(0, 8)}...` : (res.error || "Order failed"),
      });
      // Refresh balance & fills
      const [bRes, fRes] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.fills({ limit: 20 }).catch(() => []),
      ]);
      if (bRes) setBalance(bRes);
      setFills(fRes);
    } catch (e: unknown) {
      setOrderResult({ success: false, message: e instanceof Error ? e.message : "Order failed" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Trading</h1>
          <p className="text-xs text-[var(--muted)] mt-1">
            Paper Trading on Kalshi Demo API • Balance: ${balance?.balance_dollars ?? "—"}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Order Form */}
        <Card title={selectedMarket ? `Order: ${selectedMarket.ticker}` : "Place Order"} className="lg:col-span-1">
          <div className="space-y-4">
            {/* Market selector */}
            <div>
              <label className="text-xs text-[var(--muted)]">Market</label>
              <input
                type="text"
                placeholder="Search & select a market..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white focus:border-[var(--accent)] focus:outline-none"
              />
              {search && filteredMarkets.length > 0 && !selectedMarket && (
                <div className="mt-1 max-h-40 overflow-y-auto rounded-md border border-[var(--card-border)] bg-[var(--card)]">
                  {filteredMarkets.slice(0, 8).map(m => (
                    <button
                      key={m.ticker}
                      onClick={() => { setSelectedMarket(m); setSearch(m.ticker); }}
                      className="w-full px-3 py-2 text-left text-sm text-white hover:bg-white/10 border-b border-white/5"
                    >
                      <div className="font-medium">{m.ticker}</div>
                      <div className="text-xs text-[var(--muted)] truncate">{m.title}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedMarket && (
              <>
                {/* Current price display */}
                <div className="rounded-md bg-white/5 p-3">
                  <div className="text-xs text-[var(--muted)] truncate">{selectedMarket.title}</div>
                  <div className="mt-1 flex items-center gap-4 text-sm">
                    <span className="text-green-400 tabular-nums">Bid: {selectedMarket.yes_bid != null ? `${(selectedMarket.yes_bid * 100).toFixed(0)}¢` : "—"}</span>
                    <span className="text-red-400 tabular-nums">Ask: {selectedMarket.yes_ask != null ? `${(selectedMarket.yes_ask * 100).toFixed(0)}¢` : "—"}</span>
                    <span className="text-white tabular-nums">Last: {selectedMarket.last_price != null ? `${(selectedMarket.last_price * 100).toFixed(0)}¢` : "—"}</span>
                  </div>
                </div>

                {/* Side selection */}
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setSide("yes")}
                    className={`rounded-md py-2.5 text-sm font-medium transition-colors ${
                      side === "yes" ? "bg-green-500/30 text-green-400 ring-1 ring-green-500/50" : "bg-white/5 text-[var(--muted)] hover:bg-white/10"
                    }`}
                  >
                    YES ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => setSide("no")}
                    className={`rounded-md py-2.5 text-sm font-medium transition-colors ${
                      side === "no" ? "bg-red-500/30 text-red-400 ring-1 ring-red-500/50" : "bg-white/5 text-[var(--muted)] hover:bg-white/10"
                    }`}
                  >
                    NO ↓
                  </button>
                </div>

                {/* Order type */}
                <div className="flex gap-2">
                  <button
                    onClick={() => setOrderType("limit")}
                    className={`flex-1 rounded-md py-1.5 text-xs font-medium ${orderType === "limit" ? "bg-[var(--accent)] text-white" : "bg-white/5 text-[var(--muted)]"}`}
                  >
                    Limit
                  </button>
                  <button
                    onClick={() => setOrderType("market")}
                    className={`flex-1 rounded-md py-1.5 text-xs font-medium ${orderType === "market" ? "bg-[var(--accent)] text-white" : "bg-white/5 text-[var(--muted)]"}`}
                  >
                    Market
                  </button>
                </div>

                {/* Price + Qty */}
                <div className="grid grid-cols-2 gap-3">
                  {orderType === "limit" && (
                    <div>
                      <label className="text-xs text-[var(--muted)]">Price (¢)</label>
                      <input
                        type="number"
                        min={1}
                        max={99}
                        value={priceCents}
                        onChange={(e) => setPriceCents(Number(e.target.value))}
                        className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white tabular-nums focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                  )}
                  <div className={orderType === "market" ? "col-span-2" : ""}>
                    <label className="text-xs text-[var(--muted)]">Quantity</label>
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={quantity}
                      onChange={(e) => setQuantity(Number(e.target.value))}
                      className="mt-1 w-full rounded-md border border-[var(--card-border)] bg-[var(--background)] px-3 py-2 text-sm text-white tabular-nums focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                </div>

                {/* Cost summary */}
                {orderType === "limit" && (
                  <div className="rounded-md bg-white/5 p-3 text-xs text-[var(--muted)]">
                    <div className="flex justify-between">
                      <span>Est. Cost</span>
                      <span className="text-white tabular-nums">${(cost / 100).toFixed(2)}</span>
                    </div>
                    <div className="mt-1 flex justify-between">
                      <span>Max Profit</span>
                      <span className="text-green-400 tabular-nums">${(maxProfit / 100).toFixed(2)}</span>
                    </div>
                  </div>
                )}

                {/* Submit */}
                <button
                  onClick={submitOrder}
                  disabled={submitting}
                  className={`w-full rounded-md py-2.5 text-sm font-medium text-white transition-all ${
                    side === "yes" ? "bg-green-600 hover:bg-green-500" : "bg-red-600 hover:bg-red-500"
                  } ${submitting ? "opacity-50" : ""}`}
                >
                  {submitting ? "Submitting..." : `BUY ${side.toUpperCase()} × ${quantity}`}
                </button>

                {orderResult && (
                  <div className={`rounded-md p-3 text-sm ${orderResult.success ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>
                    {orderResult.message}
                  </div>
                )}
              </>
            )}
          </div>
        </Card>

        {/* Market List (mini) */}
        <Card title="Active Markets" className="lg:col-span-1">
          <div className="space-y-1 max-h-[500px] overflow-y-auto">
            {markets.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--muted)]">Loading markets...</div>
            ) : (
              markets.slice(0, 30).map(m => (
                <button
                  key={m.ticker}
                  onClick={() => { setSelectedMarket(m); setSearch(m.ticker); }}
                  className={`w-full rounded-md px-3 py-2 text-left transition-colors ${
                    selectedMarket?.ticker === m.ticker ? "bg-[var(--accent)]/10 border border-[var(--accent)]/30" : "hover:bg-white/5"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-medium text-white truncate max-w-[60%]">{m.title || m.ticker}</div>
                    <div className="text-xs tabular-nums text-[var(--muted)]">
                      {m.last_price != null ? `${(m.last_price * 100).toFixed(0)}¢` : "—"}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* Recent Fills */}
        <Card title="Recent Trades" className="lg:col-span-1" action={<span className="text-xs text-[var(--muted)]">{fills.length} fills</span>}>
          <div className="space-y-1 max-h-[500px] overflow-y-auto">
            {fills.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--muted)]">
                No trades yet — place your first order!
              </div>
            ) : (
              fills.map((f, i) => (
                <div key={i} className="flex items-center justify-between rounded-md bg-white/5 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className={`font-medium ${f.action === "buy" ? "text-green-400" : "text-red-400"}`}>
                      {f.action.toUpperCase()}
                    </span>
                    <span className="text-white">{f.ticker}</span>
                    <span className={`text-xs ${f.side === "yes" ? "text-green-400" : "text-red-400"}`}>
                      {f.side.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-xs text-[var(--muted)] tabular-nums">
                    {f.count ?? "?"} @ {f.price_dollars ? `$${f.price_dollars}` : "mkt"}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
