"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Card } from "@/components/ui/Card";
import { IconSearch, IconCircle, IconRefresh, IconStop } from "@/components/ui/Icons";
import { api, type Market, type Fill, type Balance } from "@/lib/api";

/* ── helpers ─────────────────────────────────────────────────────────── */

function fmtCents(v: number | null | undefined): string {
  return v != null ? `${(v * 100).toFixed(0)}\u00a2` : "\u2014";
}

function fmtDollars(v: number): string {
  return `$${(v / 100).toFixed(2)}`;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "\u2014";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/* ── inner component (needs useSearchParams inside Suspense) ────────── */

function TradingInner() {
  const searchParams = useSearchParams();
  const tickerParam = searchParams.get("ticker");

  /* ── state ───────────────────────────────────────────────────────── */
  const [markets, setMarkets] = useState<Market[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [fills, setFills] = useState<Fill[]>([]);
  const [search, setSearch] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Order form
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [action, setAction] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"limit" | "market">("limit");
  const [priceCents, setPriceCents] = useState(50);
  const [quantity, setQuantity] = useState(1);

  // Submission
  const [submitting, setSubmitting] = useState(false);
  const [orderResult, setOrderResult] = useState<{ success: boolean; message: string } | null>(null);
  const [cancellingAll, setCancellingAll] = useState(false);

  /* ── derived ─────────────────────────────────────────────────────── */
  const cost =
    orderType === "limit"
      ? action === "buy"
        ? priceCents * quantity
        : (100 - priceCents) * quantity
      : 0;
  const maxProfit =
    orderType === "limit"
      ? action === "buy"
        ? (100 - priceCents) * quantity
        : priceCents * quantity
      : 0;

  /* ── data loading ────────────────────────────────────────────────── */
  const loadData = useCallback(async () => {
    const [mRes, bRes, fRes] = await Promise.all([
      api.markets.list({ limit: 60 }).catch(() => ({ markets: [] as Market[], total: 0, source: "" })),
      api.portfolio.balance().catch(() => null),
      api.portfolio.fills({ limit: 30 }).catch(() => [] as Fill[]),
    ]);
    setMarkets(mRes.markets);
    setBalance(bRes);
    setFills(fRes);
    return mRes.markets;
  }, []);

  // Initial load + auto-select from ?ticker=
  useEffect(() => {
    loadData().then((mList) => {
      if (tickerParam && !selectedMarket) {
        const match = mList.find(
          (m) => m.ticker.toLowerCase() === tickerParam.toLowerCase(),
        );
        if (match) {
          setSelectedMarket(match);
          setSearch(match.ticker);
        }
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickerParam]);

  // Polling
  useEffect(() => {
    const iv = setInterval(loadData, 15_000);
    return () => clearInterval(iv);
  }, [loadData]);

  /* ── filtered markets for dropdown ───────────────────────────────── */
  const filteredMarkets = search
    ? markets.filter(
        (m) =>
          m.title?.toLowerCase().includes(search.toLowerCase()) ||
          m.ticker.toLowerCase().includes(search.toLowerCase()),
      )
    : markets;

  /* ── select market helper ────────────────────────────────────────── */
  const pickMarket = (m: Market) => {
    setSelectedMarket(m);
    setSearch(m.ticker);
    setDropdownOpen(false);
    setOrderResult(null);
  };

  /* ── submit order ────────────────────────────────────────────────── */
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
        message: res.success
          ? `Order placed: ${res.order_id?.slice(0, 8)}...`
          : res.error || "Order failed",
      });
      // Refresh balance + fills
      const [bRes, fRes] = await Promise.all([
        api.portfolio.balance().catch(() => null),
        api.portfolio.fills({ limit: 30 }).catch(() => [] as Fill[]),
      ]);
      if (bRes) setBalance(bRes);
      setFills(fRes);
    } catch (e: unknown) {
      setOrderResult({
        success: false,
        message: e instanceof Error ? e.message : "Order failed",
      });
    } finally {
      setSubmitting(false);
    }
  };

  /* ── cancel all orders ───────────────────────────────────────────── */
  const cancelAllOrders = async () => {
    setCancellingAll(true);
    try {
      await api.orders.cancelAll();
      setOrderResult({ success: true, message: "All orders cancelled" });
      const bRes = await api.portfolio.balance().catch(() => null);
      if (bRes) setBalance(bRes);
    } catch (e: unknown) {
      setOrderResult({
        success: false,
        message: e instanceof Error ? e.message : "Cancel failed",
      });
    } finally {
      setCancellingAll(false);
    }
  };

  /* ── action label for button ─────────────────────────────────────── */
  const actionLabel =
    action === "buy"
      ? `BUY ${side.toUpperCase()} \u00d7 ${quantity}`
      : `SELL ${side.toUpperCase()} \u00d7 ${quantity}`;

  /* ── render ──────────────────────────────────────────────────────── */
  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] tracking-tight">
            Trading
          </h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Paper trading on Kalshi Demo API
            <span className="mx-1.5 text-[var(--text-muted)]/30">|</span>
            Balance:{" "}
            <span className="text-[var(--text-primary)] font-medium">
              ${balance?.balance_dollars ?? "\u2014"}
            </span>
            <span className="mx-1.5 text-[var(--text-muted)]/30">|</span>
            Open orders:{" "}
            <span className="text-[var(--text-primary)] font-medium">
              {balance?.open_orders ?? 0}
            </span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            className="flex items-center gap-1.5 rounded-xl bg-white/[0.03] border border-white/[0.06] px-3 py-2 text-xs font-medium text-[var(--text-muted)] hover:bg-white/[0.06] transition-all"
          >
            <IconRefresh size={13} />
            Refresh
          </button>
          <button
            onClick={cancelAllOrders}
            disabled={cancellingAll}
            className="flex items-center gap-1.5 rounded-xl bg-loss/10 border border-loss/20 px-3 py-2 text-xs font-semibold text-loss hover:bg-loss/20 transition-all disabled:opacity-50"
          >
            <IconStop size={13} />
            {cancellingAll ? "Cancelling..." : "Cancel All Orders"}
          </button>
        </div>
      </div>

      {/* ── 3-column grid ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* ─────────────── ORDER FORM ─────────────── */}
        <Card
          title={selectedMarket ? `Order: ${selectedMarket.ticker}` : "Place Order"}
          className="lg:col-span-1"
        >
          <div className="space-y-4">
            {/* Market search */}
            <div className="relative">
              <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                Market
              </label>
              <div className="relative mt-1.5">
                <IconSearch
                  size={14}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
                />
                <input
                  type="text"
                  placeholder="Search & select..."
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setDropdownOpen(true);
                    if (selectedMarket && e.target.value !== selectedMarket.ticker) {
                      setSelectedMarket(null);
                    }
                  }}
                  onFocus={() => setDropdownOpen(true)}
                  className="w-full rounded-xl bg-white/[0.03] border border-white/[0.06] pl-9 pr-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-accent/30 transition-all"
                />
              </div>
              {dropdownOpen && search && filteredMarkets.length > 0 && !selectedMarket && (
                <div className="absolute z-20 mt-1 w-full max-h-48 overflow-y-auto rounded-xl glass shadow-2xl border border-white/[0.06]">
                  {filteredMarkets.slice(0, 10).map((m) => (
                    <button
                      key={m.ticker}
                      onClick={() => pickMarket(m)}
                      className="w-full px-4 py-2.5 text-left text-sm text-[var(--text-primary)] hover:bg-white/[0.04] border-b border-white/[0.04] transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{m.ticker}</span>
                        <span className="text-xs tabular-nums text-[var(--text-muted)] font-mono">
                          {fmtCents(m.last_price)}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--text-muted)] truncate mt-0.5">
                        {m.title}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selectedMarket && (
              <>
                {/* Market info strip */}
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
                  <div className="text-xs text-[var(--text-muted)] truncate">
                    {selectedMarket.title}
                  </div>
                  <div className="mt-2 flex items-center gap-4 text-sm flex-wrap">
                    <span className="text-accent tabular-nums">
                      Bid: {fmtCents(selectedMarket.yes_bid)}
                    </span>
                    <span className="text-loss tabular-nums">
                      Ask: {fmtCents(selectedMarket.yes_ask)}
                    </span>
                    <span className="text-[var(--text-primary)] tabular-nums font-medium">
                      Last: {fmtCents(selectedMarket.last_price)}
                    </span>
                    {selectedMarket.volume != null && (
                      <span className="text-[var(--text-muted)] tabular-nums text-xs">
                        Vol: {selectedMarket.volume.toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>

                {/* ── Side toggle: YES / NO ─────────────────────────── */}
                <div>
                  <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                    Side
                  </label>
                  <div className="grid grid-cols-2 gap-3 mt-1.5">
                    <button
                      type="button"
                      onClick={() => setSide("yes")}
                      className={`rounded-xl py-3 text-sm font-semibold transition-all ${
                        side === "yes"
                          ? "bg-accent/15 text-accent border border-accent/25 glow-accent"
                          : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"
                      }`}
                    >
                      YES
                    </button>
                    <button
                      type="button"
                      onClick={() => setSide("no")}
                      className={`rounded-xl py-3 text-sm font-semibold transition-all ${
                        side === "no"
                          ? "bg-loss/15 text-loss border border-loss/25 glow-danger"
                          : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"
                      }`}
                    >
                      NO
                    </button>
                  </div>
                </div>

                {/* ── Action toggle: BUY / SELL ─────────────────────── */}
                <div>
                  <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                    Action
                  </label>
                  <div className="grid grid-cols-2 gap-3 mt-1.5">
                    <button
                      type="button"
                      onClick={() => setAction("buy")}
                      className={`rounded-xl py-2.5 text-sm font-semibold transition-all ${
                        action === "buy"
                          ? "bg-accent/15 text-accent border border-accent/25"
                          : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"
                      }`}
                    >
                      BUY
                    </button>
                    <button
                      type="button"
                      onClick={() => setAction("sell")}
                      className={`rounded-xl py-2.5 text-sm font-semibold transition-all ${
                        action === "sell"
                          ? "bg-loss/15 text-loss border border-loss/25"
                          : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)] hover:bg-white/[0.04]"
                      }`}
                    >
                      SELL
                    </button>
                  </div>
                </div>

                {/* ── Order type: limit / market ────────────────────── */}
                <div>
                  <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                    Order Type
                  </label>
                  <div className="flex gap-2 mt-1.5">
                    {(["limit", "market"] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setOrderType(t)}
                        className={`flex-1 rounded-xl py-2 text-xs font-semibold uppercase tracking-wider transition-all ${
                          orderType === t
                            ? "bg-accent/10 text-accent border border-accent/20"
                            : "bg-white/[0.02] border border-white/[0.04] text-[var(--text-muted)]"
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>

                {/* ── Price + Quantity inputs ────────────────────────── */}
                <div className="grid grid-cols-2 gap-3">
                  {orderType === "limit" && (
                    <div>
                      <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                        Price (\u00a2)
                      </label>
                      <input
                        type="number"
                        min={1}
                        max={99}
                        value={priceCents}
                        onChange={(e) => setPriceCents(Number(e.target.value))}
                        className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] tabular-nums focus:border-accent/30 transition-all"
                      />
                    </div>
                  )}
                  <div className={orderType === "market" ? "col-span-2" : ""}>
                    <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                      Quantity
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={quantity}
                      onChange={(e) => setQuantity(Number(e.target.value))}
                      className="mt-1.5 w-full rounded-xl bg-white/[0.03] border border-white/[0.06] px-4 py-2.5 text-sm text-[var(--text-primary)] tabular-nums focus:border-accent/30 transition-all"
                    />
                  </div>
                </div>

                {/* ── Cost estimation ────────────────────────────────── */}
                {orderType === "limit" && (
                  <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-4 text-xs text-[var(--text-muted)] space-y-1.5">
                    <div className="flex justify-between">
                      <span>Action</span>
                      <span
                        className={`font-semibold ${action === "buy" ? "text-accent" : "text-loss"}`}
                      >
                        {action.toUpperCase()} {side.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Est. Cost</span>
                      <span className="text-[var(--text-primary)] tabular-nums font-medium">
                        {fmtDollars(cost)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Max Profit</span>
                      <span className="text-accent tabular-nums font-medium">
                        {fmtDollars(maxProfit)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Max Loss</span>
                      <span className="text-loss tabular-nums font-medium">
                        {fmtDollars(cost)}
                      </span>
                    </div>
                  </div>
                )}

                {/* ── Submit button ──────────────────────────────────── */}
                <button
                  onClick={submitOrder}
                  disabled={submitting}
                  className={`w-full rounded-xl py-3 text-sm font-bold tracking-wide transition-all ${
                    action === "buy"
                      ? side === "yes"
                        ? "bg-accent text-white hover:bg-accent/90"
                        : "bg-loss text-white hover:bg-loss/90"
                      : "bg-orange-500 text-white hover:bg-orange-500/90"
                  } ${submitting ? "opacity-50 cursor-not-allowed" : ""}`}
                >
                  {submitting ? "Submitting..." : actionLabel}
                </button>

                {/* ── Order result feedback ──────────────────────────── */}
                {orderResult && (
                  <div
                    className={`rounded-xl p-3 text-sm ${
                      orderResult.success
                        ? "bg-accent/10 text-accent border border-accent/20"
                        : "bg-loss/10 text-loss border border-loss/20"
                    }`}
                  >
                    {orderResult.message}
                  </div>
                )}
              </>
            )}

            {!selectedMarket && (
              <div className="py-6 text-center text-sm text-[var(--text-muted)]">
                Search and select a market above to start trading
              </div>
            )}
          </div>
        </Card>

        {/* ─────────────── ACTIVE MARKETS ─────────────── */}
        <Card title="Active Markets" className="lg:col-span-1">
          <div className="space-y-1 max-h-[540px] overflow-y-auto pr-1 scrollbar-thin">
            {markets.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                Loading markets...
              </div>
            ) : (
              markets.slice(0, 40).map((m) => (
                <button
                  key={m.ticker}
                  onClick={() => pickMarket(m)}
                  className={`w-full rounded-xl px-4 py-2.5 text-left transition-all ${
                    selectedMarket?.ticker === m.ticker
                      ? "bg-accent/[0.08] border border-accent/20"
                      : "hover:bg-white/[0.03] border border-transparent"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-medium text-[var(--text-primary)] truncate max-w-[55%]">
                      {m.title || m.ticker}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs tabular-nums text-[var(--text-muted)] font-mono">
                        {fmtCents(m.last_price)}
                      </span>
                      {m.volume != null && m.volume > 0 && (
                        <span className="text-[10px] tabular-nums text-[var(--text-muted)]/60 font-mono">
                          {m.volume > 999
                            ? `${(m.volume / 1000).toFixed(1)}k`
                            : m.volume}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] truncate mt-0.5">
                    {m.ticker}
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>

        {/* ─────────────── RECENT FILLS ─────────────── */}
        <Card
          title="Recent Trades"
          action={
            <span className="text-xs text-[var(--text-muted)] tabular-nums">
              {fills.length} fill{fills.length !== 1 ? "s" : ""}
            </span>
          }
        >
          <div className="space-y-1 max-h-[540px] overflow-y-auto pr-1 scrollbar-thin">
            {fills.length === 0 ? (
              <div className="py-8 text-center text-sm text-[var(--text-muted)]">
                No trades yet
              </div>
            ) : (
              fills.map((f, i) => (
                <div
                  key={`${f.ticker}-${f.created_time}-${i}`}
                  className="flex items-center justify-between rounded-xl bg-white/[0.02] border border-white/[0.04] px-4 py-2.5 text-sm"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <IconCircle
                      size={6}
                      className={f.action === "buy" ? "text-accent" : "text-loss"}
                    />
                    <span
                      className={`font-semibold text-xs ${
                        f.action === "buy" ? "text-accent" : "text-loss"
                      }`}
                    >
                      {f.action.toUpperCase()}
                    </span>
                    <span className="text-[var(--text-primary)] truncate">
                      {f.ticker}
                    </span>
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded-md ${
                        f.side === "yes"
                          ? "bg-accent/10 text-accent"
                          : "bg-loss/10 text-loss"
                      }`}
                    >
                      {f.side.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-right shrink-0 ml-2">
                    <div className="text-xs text-[var(--text-muted)] tabular-nums font-mono">
                      {f.count ?? "?"} @ {f.price_dollars ? `$${f.price_dollars}` : "mkt"}
                    </div>
                    <div className="text-[10px] text-[var(--text-muted)]/60">
                      {timeAgo(f.created_time)}
                    </div>
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

/* ── page export (wraps in Suspense for useSearchParams) ──────────── */

export default function TradingPage() {
  return (
    <Suspense
      fallback={
        <div className="py-20 text-center text-sm text-[var(--text-muted)] animate-pulse">
          Loading trading...
        </div>
      }
    >
      <TradingInner />
    </Suspense>
  );
}
