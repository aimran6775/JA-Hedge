"use client";

import { useEffect, useRef, useState, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
 * Hook that connects to the backend SSE stream for real-time data.
 * Falls back to nothing (callers can poll as backup).
 */
export function useSSE(): UseSSEReturn {
  const [data, setData] = useState<SSESnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }

    const es = new EventSource(`${API_BASE}/api/stream`);
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
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener("error", (event) => {
      // Try to parse error data if available
      try {
        const me = event as MessageEvent;
        if (me.data) {
          console.warn("[SSE] error event:", me.data);
        }
      } catch {
        // ignore
      }
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
      esRef.current = null;
      // Reconnect after 5s
      retryRef.current = setTimeout(connect, 5000);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (esRef.current) esRef.current.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [connect]);

  return { data, connected, lastUpdate };
}
