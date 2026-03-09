/**
 * JA Hedge — Frontend API Client (LIVE).
 *
 * Type-safe fetch wrapper for all backend API endpoints.
 * Connects to Kalshi demo API via our FastAPI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = path.startsWith("/api") ? `${API_BASE}${path}` : `${API_BASE}/api${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.message || `API error ${res.status}`);
  }

  return res.json();
}

// ── Types ────────────────────────────────────────────────────────────────

export interface Market {
  ticker: string;
  event_ticker: string;
  title: string | null;
  subtitle: string | null;
  category: string | null;
  status: string;
  yes_bid: number | null;
  yes_ask: number | null;
  no_bid: number | null;
  no_ask: number | null;
  last_price: number | null;
  volume: number | null;
  open_interest: number | null;
  spread: number | null;
  midpoint: number | null;
  close_time: string | null;
}

export interface Balance {
  balance_dollars: string;
  balance_cents: number;
  total_exposure: number;
  position_count: number;
  open_orders: number;
}

export interface Position {
  ticker: string;
  position: number;
  market_exposure_dollars: string | null;
  realized_pnl_dollars: string | null;
  fees_paid_dollars: string | null;
}

export interface Fill {
  ticker: string;
  side: string;
  action: string;
  count: number | null;
  price_dollars: string | null;
  fee_dollars: string | null;
  created_time: string | null;
  is_taker: boolean | null;
}

export interface PnL {
  daily_pnl: number;
  daily_trades: number;
  daily_fees: number;
  total_exposure: number;
}

export interface StrategyStatus {
  running: boolean;
  strategy_id: string;
  model_name: string;
  total_signals: number;
  signals_executed: number;
  signals_filtered: number;
  signals_risk_rejected: number;
  avg_confidence: number;
  avg_edge: number;
}

export interface AgentStats {
  target_profit: number;
  current_pnl: number;
  progress_pct: number;
  balance_at_start: number;
  current_balance: number;
  markets_scanned: number;
  signals_found: number;
  orders_placed: number;
  orders_filled: number;
  orders_failed: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  total_expected_profit: number;
  avg_confidence: number;
  avg_edge: number;
  best_trade_pnl: number;
  worst_trade_pnl: number;
  start_time: string;
  elapsed_seconds: number;
  scan_count: number;
  last_scan_time: string;
  active_positions: number;
  active_exposure: number;
}

export interface AgentTrade {
  id: string;
  ticker: string;
  side: string;
  action: string;
  count: number;
  price_cents: number;
  confidence: number;
  edge: number;
  expected_profit: number;
  status: string;
  order_id: string | null;
  fill_pnl: number;
  timestamp: string;
}

export interface AgentStatus {
  status: string;
  session_id: string;
  aggressiveness: string;
  stats: AgentStats;
  recent_trades: AgentTrade[];
  config: Record<string, number | string>;
}

export interface RiskSnapshot {
  total_exposure: number;
  daily_pnl: number;
  daily_trades: number;
  position_count: number;
  open_orders: number;
  kill_switch_active: boolean;
}

export interface HealthStatus {
  status: string;
  mode: string;
  has_api_keys: boolean;
  version: string;
  components: Record<string, string>;
}

// ── API Functions ────────────────────────────────────────────────────────

export const api = {
  // Health (direct endpoint, no /api prefix)
  health: () => {
    return fetch(`${API_BASE}/health`).then(r => r.json()) as Promise<HealthStatus>;
  },

  // Markets
  markets: {
    list: (params?: { category?: string; search?: string; limit?: number }) => {
      const sp = new URLSearchParams();
      if (params?.category) sp.set("category", params.category);
      if (params?.search) sp.set("search", params.search);
      if (params?.limit) sp.set("limit", String(params.limit));
      const qs = sp.toString();
      return apiFetch<{ markets: Market[]; total: number; source: string }>(
        `/markets${qs ? `?${qs}` : ""}`,
      );
    },
    get: (ticker: string) => apiFetch<Market>(`/markets/${ticker}`),
  },

  // Portfolio
  portfolio: {
    balance: () => apiFetch<Balance>("/portfolio/balance"),
    positions: () => apiFetch<Position[]>("/portfolio/positions"),
    fills: (params?: { limit?: number; ticker?: string }) => {
      const sp = new URLSearchParams();
      if (params?.limit) sp.set("limit", String(params.limit));
      if (params?.ticker) sp.set("ticker", params.ticker);
      const qs = sp.toString();
      return apiFetch<Fill[]>(`/portfolio/fills${qs ? `?${qs}` : ""}`);
    },
    pnl: () => apiFetch<PnL>("/portfolio/pnl"),
  },

  // Orders
  orders: {
    create: (order: {
      ticker: string;
      side: string;
      action?: string;
      count?: number;
      price_cents?: number;
      order_type?: string;
    }) =>
      apiFetch<{ success: boolean; order_id?: string; error?: string }>(
        "/orders",
        { method: "POST", body: JSON.stringify(order) },
      ),
    cancel: (orderId: string) =>
      apiFetch<{ status: string }>(`/orders/${orderId}`, { method: "DELETE" }),
    cancelAll: () =>
      apiFetch<{ status: string }>("/orders", { method: "DELETE" }),
  },

  // Strategy
  strategy: {
    status: () => apiFetch<StrategyStatus>("/strategy/status"),
    start: () =>
      apiFetch<{ status: string }>("/strategy/start", { method: "POST" }),
    stop: () =>
      apiFetch<{ status: string }>("/strategy/stop", { method: "POST" }),
    updateConfig: (config: Record<string, unknown>) =>
      apiFetch<{ status: string }>("/strategy/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),
  },

  // Risk
  risk: {
    snapshot: () => apiFetch<RiskSnapshot>("/risk/snapshot"),
    killSwitch: (activate: boolean) =>
      apiFetch<{ kill_switch_active: boolean }>(
        `/risk/kill-switch?activate=${activate}`,
        { method: "POST" },
      ),
    updateLimits: (limits: Record<string, unknown>) =>
      apiFetch<{ status: string }>("/risk/limits", {
        method: "PUT",
        body: JSON.stringify(limits),
      }),
  },

  // Autonomous Agent
  agent: {
    status: () => apiFetch<AgentStatus>("/agent/status"),
    start: (target_profit: number, aggressiveness: string = "moderate") =>
      apiFetch<{ status: string; session_id?: string; target_profit?: number }>(
        "/agent/start",
        {
          method: "POST",
          body: JSON.stringify({ target_profit, aggressiveness }),
        },
      ),
    stop: () =>
      apiFetch<{ status: string; final_pnl?: number; progress_pct?: number }>(
        "/agent/stop",
        { method: "POST" },
      ),
    updateConfig: (config: Record<string, unknown>) =>
      apiFetch<{ status: string }>("/agent/config", {
        method: "PUT",
        body: JSON.stringify(config),
      }),
  },
};
