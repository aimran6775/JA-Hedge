"use client";

import { useEffect, useState } from "react";

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
 * Poll individual REST endpoints to build a SSESnapshot-compatible object.
 * Used as fallback when SSE stream is unavailable (e.g. Railway CDN buffering).
 */
async function pollDashboard(): Promise<SSESnapshot | null> {
  try {
    const [balanceRes, riskRes, statusRes] = await Promise.all([
      fetch("/api/portfolio/balance").then(r => r.ok ? r.json() : null).catch(() => null),
      fetch("/api/risk/snapshot").then(r => r.ok ? r.json() : null).catch(() => null),
      fetch("/api/frankenstein/status").then(r => r.ok ? r.json() : null).catch(() => null),
    ]);

    // Build snapshot from individual responses
    const bal = balanceRes ?? {};
    const risk = riskRes ?? {};
    const frank = statusRes ?? {};
    const perf = frank?.performance?.snapshot ?? {};
    const mem = frank?.memory ?? {};
    const strat = frank?.strategy?.current_params ?? {};

    return {
      type: "snapshot",
      ts: Date.now() / 1000,
      balance: {
        balance_dollars: bal.balance_dollars ?? "0",
        balance_cents: bal.balance_cents ?? 0,
        total_exposure: bal.total_exposure ?? 0,
        position_count: bal.position_count ?? 0,
        open_orders: bal.open_orders ?? 0,
      },
      pnl: {
        daily_pnl: perf.daily_pnl ?? 0,
        daily_trades: frank.daily_trades ?? 0,
        daily_fees: 0,
        total_exposure: bal.total_exposure ?? 0,
      },
      positions: [],
      risk: {
        total_exposure: risk.total_exposure ?? 0,
        daily_pnl: risk.daily_pnl ?? 0,
        daily_trades: risk.daily_trades ?? 0,
        position_count: risk.position_count ?? 0,
        open_orders: risk.open_orders ?? 0,
        kill_switch_active: risk.kill_switch_active ?? false,
      },
      frankenstein: {
        status: frank.is_alive ? "alive" : "offline",
        is_alive: frank.is_alive ?? false,
        is_trading: frank.is_trading ?? false,
        is_paused: frank.is_paused ?? false,
        total_scans: frank.total_scans ?? 0,
        total_signals: frank.total_signals ?? 0,
        total_trades_executed: frank.total_trades_executed ?? 0,
        total_trades_rejected: frank.total_trades_rejected ?? 0,
        generation: frank.generation ?? 0,
        model_version: frank.version ?? "",
        uptime_seconds: frank.uptime_seconds ?? 0,
        daily_trades: frank.daily_trades ?? 0,
        daily_trade_cap: frank.daily_trade_cap ?? 150,
        performance: {
          win_rate: perf.win_rate ?? 0,
          total_pnl: perf.total_pnl ?? 0,
          sharpe_ratio: perf.sharpe_ratio ?? 0,
          profit_factor: perf.profit_factor ?? 0,
          max_drawdown: perf.max_drawdown ?? 0,
          real_trades: perf.real_trades ?? perf.total_trades ?? 0,
        },
        memory: {
          total_recorded: mem.total_recorded ?? 0,
          pending: mem.pending ?? 0,
          total_resolved: mem.total_resolved ?? 0,
          win_rate: parseFloat(String(mem.win_rate ?? "0").replace("%", "")) / 100 || 0,
        },
        strategy: {
          min_confidence: strat.min_confidence ?? 0,
          min_edge: strat.min_edge ?? 0,
          kelly_fraction: strat.kelly_fraction ?? 0,
          aggression: strat.aggression ?? 0,
        },
      },
      recent_trades: [],
      active_markets: 0,
      total_markets: 0,
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

  useEffect(() => {
    let esRef: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let sseAlive = false;
    let cancelled = false;

    function stopPolling() {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    async function doPoll() {
      if (cancelled) return;
      const snapshot = await pollDashboard();
      if (cancelled) return;
      if (snapshot) {
        setData(snapshot);
        setLastUpdate(Date.now());
        setConnected(true);
      }
    }

    function startPolling() {
      if (pollTimer || cancelled) return;
      doPoll(); // immediate first
      pollTimer = setInterval(doPoll, 5000);
    }

    function connect() {
      if (cancelled) return;
      if (esRef) esRef.close();

      const es = new EventSource("/api/stream");
      esRef = es;

      es.addEventListener("connected", () => {
        if (!cancelled) setConnected(true);
      });

      es.addEventListener("snapshot", (event) => {
        if (cancelled) return;
        try {
          const parsed = JSON.parse(event.data) as SSESnapshot;
          setData(parsed);
          setLastUpdate(Date.now());
          setConnected(true);
          sseAlive = true;
          stopPolling();
        } catch { /* ignore */ }
      });

      es.onerror = () => {
        if (cancelled) return;
        setConnected(false);
        es.close();
        esRef = null;
        startPolling();
        retryTimer = setTimeout(connect, 30_000);
      };

      // If SSE hasn't delivered data in 6s, start polling
      setTimeout(() => {
        if (!sseAlive && !cancelled) startPolling();
      }, 6000);
    }

    connect();

    return () => {
      cancelled = true;
      if (esRef) esRef.close();
      if (retryTimer) clearTimeout(retryTimer);
      stopPolling();
    };
  }, []); // no deps — stable effect

  return { data, connected, lastUpdate };
}
