"use client";

import { useEffect, useRef, useState } from "react";

export interface SSESnapshot {
  type: string;
  ts: number;
  balance: {
    balance_dollars: string;
    balance_cents: number;
    total_exposure: number;
    position_count: number;
    open_orders: number;
  };
  pnl: {
    daily_pnl: number;
    daily_trades: number;
    daily_fees: number;
    total_exposure: number;
  };
  positions: Array<{
    ticker: string;
    position: number;
    market_exposure_dollars: string | null;
    realized_pnl_dollars: string | null;
  }>;
  risk: {
    total_exposure?: number;
    daily_pnl?: number;
    daily_trades?: number;
    position_count?: number;
    open_orders?: number;
    kill_switch_active: boolean;
  };
  frankenstein: {
    status?: string;
    is_alive?: boolean;
    is_trading?: boolean;
    is_paused?: boolean;
    total_scans?: number;
    total_signals?: number;
    total_trades_executed?: number;
    total_trades_rejected?: number;
    generation?: number;
    model_version?: string;
    uptime_seconds?: number;
    daily_trades?: number;
    daily_trade_cap?: number;
    last_scan_ms?: number;
    performance?: {
      win_rate: number;
      total_pnl: number;
      sharpe_ratio: number;
      profit_factor: number;
      max_drawdown: number;
      real_trades: number;
    };
    memory?: {
      total_recorded: number;
      pending: number;
      total_resolved: number;
      win_rate: number;
    };
    strategy?: {
      min_confidence: number;
      min_edge: number;
      kelly_fraction: number;
      aggression: number;
    };
  };
  recent_trades: Array<{
    ticker: string;
    side: string;
    action: string;
    count: number;
    price_cents: number;
    confidence: number;
    edge: number;
    outcome: string;
    pnl_cents: number;
    timestamp: string;
    category: string;
    model_version: string;
  }>;
  active_markets: number;
  total_markets: number;
}

interface UseSSEReturn {
  data: SSESnapshot | null;
  connected: boolean;
  lastUpdate: number | null;
}

/**
 * Fetch a single endpoint, return parsed JSON or null on any error.
 */
async function safeFetch<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Poll individual REST endpoints to build a SSESnapshot-compatible object.
 * Returns partial data even if some endpoints fail.
 */
async function pollDashboard(): Promise<SSESnapshot | null> {
  // Fire all three in parallel — each one independently catches errors
  const [bal, risk, frank] = await Promise.all([
    safeFetch<Record<string, unknown>>("/api/portfolio/balance"),
    safeFetch<Record<string, unknown>>("/api/risk/snapshot"),
    safeFetch<Record<string, unknown>>("/api/frankenstein/status"),
  ]);

  // If ALL three failed, we're truly disconnected
  if (!bal && !risk && !frank) return null;

  // Use whatever data we got (partial is fine)
  const b = bal ?? {};
  const r = risk ?? {};
  const f = frank ?? {};
  const perf = (f?.performance as Record<string, unknown>)?.snapshot as Record<string, unknown> ?? {};
  const mem = f?.memory as Record<string, unknown> ?? {};
  const strat = (f?.strategy as Record<string, unknown>)?.current_params as Record<string, unknown> ?? {};

  return {
    type: "snapshot",
    ts: Date.now() / 1000,
    balance: {
      balance_dollars: (b.balance_dollars as string) ?? "0",
      balance_cents: (b.balance_cents as number) ?? 0,
      total_exposure: (b.total_exposure as number) ?? 0,
      position_count: (b.position_count as number) ?? 0,
      open_orders: (b.open_orders as number) ?? 0,
    },
    pnl: {
      daily_pnl: (perf.daily_pnl as number) ?? 0,
      daily_trades: (f.daily_trades as number) ?? 0,
      daily_fees: 0,
      total_exposure: (b.total_exposure as number) ?? 0,
    },
    positions: [],
    risk: {
      total_exposure: (r.total_exposure as number) ?? 0,
      daily_pnl: (r.daily_pnl as number) ?? 0,
      daily_trades: (r.daily_trades as number) ?? 0,
      position_count: (r.position_count as number) ?? 0,
      open_orders: (r.open_orders as number) ?? 0,
      kill_switch_active: (r.kill_switch_active as boolean) ?? false,
    },
    frankenstein: {
      status: f.is_alive ? "alive" : "offline",
      is_alive: (f.is_alive as boolean) ?? false,
      is_trading: (f.is_trading as boolean) ?? false,
      is_paused: (f.is_paused as boolean) ?? false,
      total_scans: (f.total_scans as number) ?? 0,
      total_signals: (f.total_signals as number) ?? 0,
      total_trades_executed: (f.total_trades_executed as number) ?? 0,
      total_trades_rejected: (f.total_trades_rejected as number) ?? 0,
      generation: (f.generation as number) ?? 0,
      model_version: (f.version as string) ?? "",
      uptime_seconds: (f.uptime_seconds as number) ?? 0,
      daily_trades: (f.daily_trades as number) ?? 0,
      daily_trade_cap: (f.daily_trade_cap as number) ?? 150,
      performance: {
        win_rate: (perf.win_rate as number) ?? 0,
        total_pnl: (perf.total_pnl as number) ?? 0,
        sharpe_ratio: (perf.sharpe_ratio as number) ?? 0,
        profit_factor: (perf.profit_factor as number) ?? 0,
        max_drawdown: (perf.max_drawdown as number) ?? 0,
        real_trades: (perf.real_trades as number) ?? (perf.total_trades as number) ?? 0,
      },
      memory: {
        total_recorded: (mem.total_recorded as number) ?? 0,
        pending: (mem.pending as number) ?? 0,
        total_resolved: (mem.total_resolved as number) ?? 0,
        win_rate: parseFloat(String(mem.win_rate ?? "0").replace("%", "")) / 100 || 0,
      },
      strategy: {
        min_confidence: (strat.min_confidence as number) ?? 0,
        min_edge: (strat.min_edge as number) ?? 0,
        kelly_fraction: (strat.kelly_fraction as number) ?? 0,
        aggression: (strat.aggression as number) ?? 0,
      },
    },
    recent_trades: [],
    active_markets: 0,
    total_markets: 0,
  };
}

/* ── Shared singleton: only ONE polling loop for all useSSE() consumers ── */
type Listener = (snap: SSESnapshot) => void;
let polling = false;
let listeners: Listener[] = [];
let latestSnap: SSESnapshot | null = null;
let pollInterval: ReturnType<typeof setInterval> | null = null;

function subscribe(fn: Listener) {
  listeners.push(fn);
  // Give new subscriber the latest data immediately
  if (latestSnap) fn(latestSnap);
  startSharedPoll();
  return () => {
    listeners = listeners.filter(l => l !== fn);
    if (listeners.length === 0) stopSharedPoll();
  };
}

async function tick() {
  const snap = await pollDashboard();
  if (snap) {
    latestSnap = snap;
    listeners.forEach(fn => fn(snap));
  }
}

function startSharedPoll() {
  if (polling) return;
  polling = true;
  tick(); // immediate first poll
  pollInterval = setInterval(tick, 5_000);
}

function stopSharedPoll() {
  polling = false;
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

/**
 * Hook that polls the backend REST API every 5 seconds for dashboard data.
 * Uses a shared singleton so multiple components don't create duplicate polls.
 * SSE was removed — Railway CDN (Fastly) buffers Server-Sent Events, making
 * them unreliable. Pure REST polling is simpler and always works.
 */
export function useSSE(): UseSSEReturn {
  const [data, setData] = useState<SSESnapshot | null>(latestSnap);
  const [connected, setConnected] = useState(!!latestSnap);
  const [lastUpdate, setLastUpdate] = useState<number | null>(latestSnap ? Date.now() : null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const unsub = subscribe((snap) => {
      if (!mountedRef.current) return;
      setData(snap);
      setConnected(true);
      setLastUpdate(Date.now());
    });
    return () => {
      mountedRef.current = false;
      unsub();
    };
  }, []);

  return { data, connected, lastUpdate };
}
