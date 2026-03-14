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
  paper_trading?: {
    enabled: boolean;
    balance?: string;
    starting_balance?: string;
    pnl?: string;
    total_trades?: number;
  };
  components: Record<string, string>;
}

// AI Engine types (derived from strategy + frankenstein data)
export interface AIStatus {
  model_loaded: boolean;
  model_name: string;
  last_prediction: string | null;
  total_signals: number;
  signals_executed: number;
  features_count: number;
}

export interface AISignal {
  ticker: string;
  direction: string;
  confidence: number | null;
  edge: number | null;
  timestamp: string | null;
}

// ── Frankenstein Types ───────────────────────────────────────────────────

export interface FrankensteinStatus {
  name: string;
  version: string;
  generation: number;
  is_alive: boolean;
  is_trading: boolean;
  is_paused: boolean;
  pause_reason: string | null;
  uptime_seconds: number;
  uptime_human: string;

  total_scans: number;
  total_signals: number;
  total_trades_executed: number;
  total_trades_rejected: number;
  last_scan_ms: string;
  last_scan_debug: {
    candidates?: number;
    trade_candidates?: number;
    exec_successes?: number;
    exec_rejections?: number;
    portfolio_rejections?: number;
    top_candidates?: Array<{
      ticker: string;
      stage: string;
      error?: string;
      order_id?: string;
    }>;
  };

  memory: {
    total_recorded: number;
    total_resolved: number;
    pending: number;
    win_rate: number;
    total_pnl: number;
    avg_pnl_per_trade: number;
    outcomes: Record<string, number>;
  };

  performance: {
    snapshot: {
      total_trades: number;
      real_trades: number;
      win_rate: number;
      prediction_accuracy: number;
      total_pnl: number;
      daily_pnl: number;
      sharpe_ratio: number;
      sortino_ratio: number;
      max_drawdown: number;
      current_drawdown: number;
      profit_factor: number;
      avg_win: number;
      avg_loss: number;
      regime: string;
    };
    should_pause: boolean;
    pause_reason: string;
  };

  learner: {
    current_version: string;
    generation: number;
    champion_auc: number;
    champion_samples: number;
    total_retrains: number;
    total_promotions: number;
    needs_retrain: boolean;
    top_features: Record<string, number>;
  };

  strategy: {
    current_params: {
      min_confidence: number;
      min_edge: number;
      kelly_fraction: number;
      max_position_size: number;
      max_simultaneous_positions: number;
      scan_interval: number;
      max_daily_loss: number;
      stop_loss_pct: number;
      take_profit_pct: number;
      max_spread_cents: number;
      min_volume: number;
      min_hours_to_expiry: number;
      aggression: number;
    };
    total_adaptations: number;
    regime: string;
  };

  scheduler: {
    tasks: number;
    next_run: string | null;
  };

  health: Record<string, unknown>;
  portfolio_risk: Record<string, unknown>;
  exchange_session: string;
  liquidity_factor: number;
  sports_only_mode: boolean;
  sports_detector: Record<string, unknown> | null;
  sports_risk: Record<string, unknown> | null;
  sports_predictor: Record<string, unknown> | null;
}

export interface FrankensteinTrade {
  trade_id: string;
  ticker: string;
  side: string;
  action: string;
  count: number;
  price_cents: number;
  confidence: number;
  edge: number;
  predicted_prob: number;
  model_version: string;
  outcome: string;
  pnl_cents: number;
  timestamp: string;
}

export interface FrankensteinHealth {
  alive: boolean;
  trading: boolean;
  paused: boolean;
  pause_reason: string | null;
  generation: number;
  model_version: string;
  total_trades: number;
  should_pause: boolean;
  should_pause_reason: string;
}

// Risk types
export interface RiskLimits {
  max_positions: number;
  max_exposure_cents: number;
  max_daily_loss_cents: number;
}

export interface RiskStatus {
  total_exposure_cents: number;
  daily_pnl_cents: number;
  open_positions: number;
  kill_switch_active: boolean;
  recent_violations: string[];
}

// Strategy Engine types
export interface StrategyInfo {
  name: string;
  display_name: string;
  description: string;
  risk_level: string;
  enabled: boolean;
  config: {
    min_confidence: number;
    min_edge: number;
    max_position_pct: number;
    kelly_fraction: number;
    max_positions: number;
    enabled: boolean;
    description: string;
  };
  stats: {
    scans: number;
    signals: number;
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
  };
}

export interface StrategyEngineStatus {
  enabled_strategies: number;
  total_strategies: number;
  total_signals_generated: number;
  strategies: StrategyInfo[];
  recent_signals: StrategySignalItem[];
}

export interface StrategySignalItem {
  ticker: string;
  side: string;
  confidence: number;
  edge: number;
  strategy: string;
  reasoning: string;
  recommended_count: number;
  expected_profit: number;
  predicted_prob: number;
  price_cents: number;
  urgency: number;
  timestamp: number;
}

// Sports types
export interface SportsMarket {
  ticker: string;
  event_ticker: string;
  title: string | null;
  subtitle: string | null;
  sport: string;
  market_type: string;
  is_live: boolean;
  home_team: string;
  away_team: string;
  yes_bid: number;
  yes_ask: number;
  midpoint: number;
  volume: number;
  open_interest: number;
  vegas_home_prob?: number;
  vegas_away_prob?: number;
  num_bookmakers?: number;
  kalshi_vs_vegas?: number;
}

export interface VegasGame {
  game_id: string;
  sport: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  consensus_home_prob: number;
  consensus_away_prob: number;
  consensus_spread: number | null;
  consensus_total: number | null;
  num_bookmakers: number;
}

export interface SportsSignal {
  type: string;
  ticker: string;
  side: string;
  strength: number;
  urgency: number;
  reason: string;
  age_seconds: number;
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
    status: async (): Promise<RiskStatus> => {
      const snap = await apiFetch<RiskSnapshot>("/risk/snapshot");
      return {
        total_exposure_cents: Math.round(snap.total_exposure * 100),
        daily_pnl_cents: Math.round(snap.daily_pnl * 100),
        open_positions: snap.position_count,
        kill_switch_active: snap.kill_switch_active,
        recent_violations: [],
      };
    },
    limits: async (): Promise<RiskLimits> => {
      // No GET endpoint exists; return defaults
      return { max_positions: 10, max_exposure_cents: 5000, max_daily_loss_cents: 500 };
    },
    activateKillSwitch: () =>
      apiFetch<{ kill_switch_active: boolean }>(
        "/risk/kill-switch?activate=true",
        { method: "POST" },
      ),
    resetKillSwitch: () =>
      apiFetch<{ kill_switch_active: boolean }>(
        "/risk/kill-switch?activate=false",
        { method: "POST" },
      ),
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

  // AI Engine (synthesized from strategy + frankenstein)
  ai: {
    status: async (): Promise<AIStatus> => {
      try {
        const strat = await apiFetch<StrategyStatus>("/strategy/status");
        return {
          model_loaded: strat.running,
          model_name: strat.model_name,
          last_prediction: null,
          total_signals: strat.total_signals,
          signals_executed: strat.signals_executed,
          features_count: 29,
        };
      } catch {
        return { model_loaded: false, model_name: "XGBoost", last_prediction: null, total_signals: 0, signals_executed: 0, features_count: 29 };
      }
    },
    signals: async (_params?: { limit?: number }): Promise<AISignal[]> => {
      // No dedicated signals endpoint — return empty
      return [];
    },
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

  // Frankenstein AI Brain
  frankenstein: {
    status: () => apiFetch<FrankensteinStatus>("/frankenstein/status"),
    health: () => apiFetch<FrankensteinHealth>("/frankenstein/health"),
    awaken: () =>
      apiFetch<{ status: string; message: string }>("/frankenstein/awaken", {
        method: "POST",
      }),
    sleep: () =>
      apiFetch<{ status: string; message: string }>("/frankenstein/sleep", {
        method: "POST",
      }),
    pause: (reason?: string) =>
      apiFetch<{ status: string; reason: string }>(`/frankenstein/pause${reason ? `?reason=${encodeURIComponent(reason)}` : ""}`, {
        method: "POST",
      }),
    resume: () =>
      apiFetch<{ status: string }>("/frankenstein/resume", {
        method: "POST",
      }),
    retrain: () =>
      apiFetch<Record<string, unknown>>("/frankenstein/retrain", {
        method: "POST",
      }),
    bootstrap: () =>
      apiFetch<Record<string, unknown>>("/frankenstein/bootstrap", {
        method: "POST",
      }),
    performance: () => apiFetch<Record<string, unknown>>("/frankenstein/performance"),
    performanceSnapshot: () => apiFetch<Record<string, unknown>>("/frankenstein/performance/snapshot"),
    memory: () => apiFetch<Record<string, unknown>>("/frankenstein/memory"),
    recentTrades: (n?: number) =>
      apiFetch<FrankensteinTrade[]>(
        `/frankenstein/memory/recent${n ? `?n=${n}` : ""}`,
      ),
    pendingTrades: () => apiFetch<FrankensteinTrade[]>("/frankenstein/memory/pending"),
    features: () => apiFetch<{ current: Record<string, number>; trends: Record<string, unknown> }>("/frankenstein/features"),
    learner: () => apiFetch<Record<string, unknown>>("/frankenstein/learner"),
    strategy: () => apiFetch<Record<string, unknown>>("/frankenstein/strategy"),
    chatWelcome: () => apiFetch<Record<string, unknown>>("/frankenstein/chat/welcome"),
    chat: (message: string) =>
      apiFetch<Record<string, unknown>>("/frankenstein/chat", {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
    chatHistory: (n?: number) =>
      apiFetch<Record<string, unknown>[]>(
        `/frankenstein/chat/history${n ? `?n=${n}` : ""}`,
      ),
  },

  // Strategy Engine (pre-built trading strategies)
  strategies: {
    status: () => apiFetch<StrategyEngineStatus>("/strategies/status"),
    signals: (n?: number) =>
      apiFetch<{ total_signals: number; signals: StrategySignalItem[] }>(
        `/strategies/signals${n ? `?n=${n}` : ""}`,
      ),
    toggle: (strategy: string, enabled: boolean) =>
      apiFetch<{ status: string; strategy: string; enabled: boolean }>(
        "/strategies/toggle",
        { method: "POST", body: JSON.stringify({ strategy, enabled }) },
      ),
    config: (strategy: string, config: Record<string, unknown>) =>
      apiFetch<{ status: string }>("/strategies/config", {
        method: "POST",
        body: JSON.stringify({ strategy, ...config }),
      }),
    scan: () =>
      apiFetch<{ markets_scanned: number; total_signals: number; signals: StrategySignalItem[] }>(
        "/strategies/scan",
        { method: "POST" },
      ),
  },

  // Sports Trading
  sports: {
    status: () => apiFetch<Record<string, unknown>>("/sports/status"),
    markets: () =>
      apiFetch<{
        total_sports_markets: number;
        total_all_markets: number;
        sports_pct: string;
        by_sport: Record<string, SportsMarket[]>;
      }>("/sports/markets"),
    odds: () =>
      apiFetch<{
        total_games: number;
        games: VegasGame[];
        api_stats: Record<string, unknown>;
      }>("/sports/odds"),
    live: () =>
      apiFetch<{
        live_games: number;
        games: Record<string, unknown>[];
        tracker_stats: Record<string, unknown>;
      }>("/sports/live"),
    performance: () => apiFetch<Record<string, unknown>>("/sports/performance"),
    signals: () =>
      apiFetch<{
        pending_signals: number;
        signals: SportsSignal[];
        engine_stats: Record<string, unknown>;
      }>("/sports/signals"),
    refreshOdds: () =>
      apiFetch<Record<string, unknown>>("/sports/odds/refresh", {
        method: "POST",
      }),
  },
};
