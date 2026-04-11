"use client";

import { useEffect, useRef, useState, useCallback } from "react";

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
 * Poll /api/dashboard to build a SSESnapshot-compatible object.
 * Used as fallback when SSE stream is unavailable (e.g. Railway CDN).
 */
async function pollDashboard(): Promise<SSESnapshot | null> {
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) return null;
    const d = await res.json();
    return {
      type: "snapshot",
      ts: Date.now() / 1000,
      balance: d.balance ?? { balance_dollars: "0", balance_cents: 0, total_exposure: 0, position_count: 0, open_orders: 0 },
      pnl: d.pnl ?? { daily_pnl: 0, daily_trades: 0, daily_fees: 0, total_exposure: 0 },
      positions: d.positions ?? [],
      risk: d.risk ?? { kill_switch_active: false },
      frankenstein: d.frankenstein ?? {},
      recent_trades: [],
      active_markets: d.active_markets_count ?? 0,
      total_markets: d.total_cached_markets ?? 0,
    };
  } catch {
    return null;
  }
}

/**
 * Hook that connects to the backend SSE stream for real-time data.
 * Automatically falls back to REST polling when SSE is unavailable.
 */
export function useSSE(): UseSSEReturn {
  const [data, setData] = useState<SSESnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sseAlive = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const doPoll = useCallback(async () => {
    const snapshot = await pollDashboard();
    if (snapshot) {
      setData(snapshot);
      setLastUpdate(Date.now());
      setConnected(true);
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollingRef.current) return; // already running
    doPoll(); // immediate first poll
    pollingRef.current = setInterval(doPoll, 5000);
  }, [doPoll]);

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close();

    // Use relative URL — Next.js rewrites proxy to backend
    const es = new EventSource("/api/stream");
    esRef.current = es;

    es.addEventListener("connected", () => {
      setConnected(true);
    });

    es.addEventListener("snapshot", (event) => {
      try {
        const parsed = JSON.parse(event.data) as SSESnapshot;
        setData(parsed);
        setLastUpdate(Date.now());
        setConnected(true);
        sseAlive.current = true;
        stopPolling(); // SSE works — no need to poll
      } catch {
        // ignore parse errors
      }
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
      esRef.current = null;
      startPolling(); // SSE failed — poll instead
      // Retry SSE connection after 30s
      retryRef.current = setTimeout(connect, 30_000);
    };

    // If SSE hasn't delivered data within 6s, start polling as backup
    setTimeout(() => {
      if (!sseAlive.current) startPolling();
    }, 6000);
  }, [startPolling, stopPolling]);

  useEffect(() => {
    connect();
    return () => {
      if (esRef.current) esRef.current.close();
      if (retryRef.current) clearTimeout(retryRef.current);
      stopPolling();
    };
  }, [connect, stopPolling]);

  return { data, connected, lastUpdate };
}
