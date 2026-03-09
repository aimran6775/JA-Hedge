# JA HEDGE — 20-Phase Implementation Plan
## AI-Powered Kalshi Trading Platform with Sub-Second Execution

---

## Architecture Principles
- **Latency-first**: Async everywhere, connection pooling, pre-signed auth, in-memory caches
- **Build without keys**: Everything built against demo API + mock layer, keys injected at the end
- **Modular**: Each phase produces working, testable code
- **Safety**: Kill switches, circuit breakers, and risk limits baked in from day one

---

## PHASE 1: Project Scaffolding & Core Config
**Goal**: Monorepo structure, dependency management, environment config

**Deliverables**:
- Monorepo layout: `/backend` (Python/FastAPI), `/frontend` (Next.js), `/shared`
- Python: `pyproject.toml` with all deps (fastapi, httpx, websockets, cryptography, pydantic, sqlalchemy, redis, celery, scikit-learn, xgboost, pandas, numpy)
- Next.js: `package.json` with deps (shadcn/ui, tailwind, lightweight-charts, zustand, react-query, zod, react-hook-form, tanstack-table, socket.io-client)
- `.env.example` with all config keys (API keys, DB URLs, Redis URL, etc.)
- `docker-compose.yml` — PostgreSQL + TimescaleDB, Redis, backend, frontend
- Logging config (structured JSON logs with `structlog`)
- Shared constants: Kalshi base URLs, WebSocket URLs, rate limit configs

```
ja-hedge/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Pydantic Settings
│   │   └── logging_config.py
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   └── app/                 # Next.js App Router
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

---

## PHASE 2: Kalshi API Client — Auth & Core REST
**Goal**: Blazing-fast authenticated HTTP client with connection reuse

**Deliverables**:
- `kalshi/auth.py` — RSA-PSS key loading, signature generation (cached private key in memory)
- `kalshi/client.py` — Async `httpx.AsyncClient` with:
  - Persistent connection pool (HTTP/2 where supported)
  - Auto-signing middleware (injects headers on every request)
  - Automatic retry with exponential backoff (429, 5xx)
  - Response parsing into Pydantic models
- `kalshi/rate_limiter.py` — Token bucket rate limiter (configurable per tier)
- `kalshi/exceptions.py` — Typed exceptions (`RateLimitError`, `AuthError`, `OrderError`, etc.)
- Unit tests with mocked responses

**Latency target**: Auth header generation < 1ms (key pre-loaded, signature cached per timestamp)

---

## PHASE 3: Kalshi API Client — Full Endpoint Coverage
**Goal**: Complete typed wrapper for every Kalshi REST endpoint

**Deliverables**:
- `kalshi/endpoints/markets.py` — GetMarkets, GetMarket, GetOrderbook, GetTrades, GetCandlesticks
- `kalshi/endpoints/events.py` — GetEvents, GetEvent, GetEventMetadata
- `kalshi/endpoints/series.py` — GetSeries, GetSeriesMarkets
- `kalshi/endpoints/portfolio.py` — GetBalance, GetPositions, GetFills, GetSettlements
- `kalshi/endpoints/orders.py` — CreateOrder, CancelOrder, AmendOrder, BatchCreate, BatchCancel, DecreaseOrder
- `kalshi/endpoints/order_groups.py` — Create, Delete, Reset, Trigger, UpdateLimit
- `kalshi/endpoints/exchange.py` — GetStatus, GetSchedule, GetAnnouncements
- `kalshi/endpoints/historical.py` — All historical data endpoints
- `kalshi/models.py` — Full Pydantic v2 models matching OpenAPI schema:
  - `Market`, `Event`, `Series`, `Order`, `Fill`, `Position`, `Settlement`, `Candlestick`, `OrderbookLevel`, etc.
  - All using `FixedPointDollars` (Decimal) and `FixedPointCount` (Decimal) types

---

## PHASE 4: Kalshi WebSocket Client — Real-Time Data
**Goal**: Persistent, auto-reconnecting WebSocket with sub-100ms message processing

**Deliverables**:
- `kalshi/ws_client.py`:
  - Auto-reconnect with exponential backoff
  - Channel subscription management (subscribe/unsubscribe)
  - Message parsing into typed events
  - Heartbeat/ping-pong handling
  - Connection state machine (connecting → authenticated → subscribed → active)
- `kalshi/ws_channels.py` — Channel definitions:
  - Public: `ticker`, `trade`, `market_lifecycle_v2`, `multivariate`
  - Private: `orderbook_delta`, `fill`, `market_positions`, `order_group_updates`
- `kalshi/ws_models.py` — WebSocket message Pydantic models
- Event dispatcher — async callbacks per channel type
- Connection health monitor with auto-recovery

**Latency target**: Message receive → parsed event < 5ms

---

## PHASE 5: Database Layer & Data Models
**Goal**: PostgreSQL + TimescaleDB schema, async ORM, migrations

**Deliverables**:
- `db/engine.py` — SQLAlchemy async engine with connection pooling
- `db/models/` — SQLAlchemy ORM models:
  - `markets.py` — Market cache table
  - `candlesticks.py` — TimescaleDB hypertable
  - `orders.py` — Order records with strategy attribution
  - `positions.py` — Real-time positions
  - `fills.py` — Trade fills
  - `strategies.py` — Strategy configs (JSONB params)
  - `signals.py` — AI signal log
  - `trade_journal.py` — Full trade journal
  - `alerts.py` — User alert configs
  - `risk_rules.py` — User-defined risk rules
- `db/migrations/` — Alembic migrations
- `db/repositories/` — Repository pattern for each model (async CRUD)
- Redis schema design for hot data (current prices, positions, orderbook snapshots)

---

## PHASE 6: Data Ingestion Pipeline
**Goal**: Continuous market data sync from Kalshi into local DB + Redis cache

**Deliverables**:
- `data/market_sync.py` — Periodic full market list sync (every 60s)
- `data/price_feed.py` — WebSocket ticker channel → Redis pub/sub + DB write
- `data/orderbook_feed.py` — WebSocket orderbook_delta → in-memory orderbook reconstruction
- `data/trade_feed.py` — WebSocket trade channel → DB + analytics
- `data/candlestick_sync.py` — REST poll for candlestick data → TimescaleDB
- `data/historical_backfill.py` — One-time historical data download for backtesting
- Redis cache layer:
  - `market:{ticker}` — Latest market data (hash)
  - `orderbook:{ticker}` — Current orderbook snapshot (sorted set)
  - `price:{ticker}` — Latest price (string, < 1ms read)
  - `positions` — Current portfolio positions (hash)
- Data freshness monitoring (alert if data > 5s stale)

**Latency target**: Kalshi WS message → Redis cache update < 10ms

---

## PHASE 7: Order Management System (OMS)
**Goal**: Fast, reliable order lifecycle management with safety checks

**Deliverables**:
- `trading/oms.py` — Order Management System:
  - `place_order()` — Pre-flight validation → risk check → API call → confirm
  - `cancel_order()` — Immediate cancel with confirmation
  - `amend_order()` — Atomic amend (price/size change)
  - `batch_place()` — Batch up to 20 orders in single API call
  - `batch_cancel()` — Batch cancel
- `trading/order_validator.py` — Pre-flight checks:
  - Price within valid `price_ranges`
  - Sufficient balance for order cost
  - Position limit not exceeded
  - Rate limit headroom check
  - Market is active and open
- `trading/fill_tracker.py` — WebSocket fill channel → order state updates
- `trading/order_state_machine.py` — State transitions: pending → sent → resting → (partial_fill) → filled/cancelled
- Client order ID generation (UUID v4) for deduplication
- Order queue with priority (strategy orders vs. risk-triggered orders)

**Latency target**: Decision-to-order-sent < 50ms

---

## PHASE 8: Position Tracker & Portfolio Manager
**Goal**: Real-time portfolio state with P&L calculations

**Deliverables**:
- `trading/position_tracker.py`:
  - In-memory position state (updated from WS fills + REST sync)
  - Per-market: quantity, avg entry price, current price, unrealized P&L, realized P&L
  - Event-level aggregation (total exposure per event)
  - Category-level aggregation
- `trading/portfolio.py`:
  - Total portfolio value (balance + position values)
  - Total exposure (sum of max possible losses)
  - Daily P&L, weekly P&L, all-time P&L
  - Equity curve generation
  - Fee tracking (total taker + maker fees)
- `trading/pnl_calculator.py`:
  - Mark-to-market P&L (using live bid/ask midpoint)
  - Realized P&L (from fills and settlements)
  - Fee-adjusted returns
- Redis-backed for sub-ms reads from dashboard

---

## PHASE 9: Risk Management Engine
**Goal**: Multi-layered risk controls that can halt trading in milliseconds

**Deliverables**:
- `risk/risk_engine.py` — Central risk manager (runs every tick):
  - **Pre-trade checks** (before order sent):
    - Max position size per market
    - Max position size per event
    - Max total portfolio exposure
    - Max single order cost
    - Kelly fraction ceiling
  - **Real-time monitors** (continuous):
    - Portfolio drawdown monitor (daily + max)
    - Per-strategy loss limit
    - Consecutive loss counter
    - Exposure concentration limits
  - **Circuit breakers**:
    - Daily loss limit → pause all strategies
    - Max drawdown → close all positions + cancel all orders
    - API error spike → pause trading
    - Stale data → pause trading
- `risk/kill_switch.py`:
  - `emergency_stop()` — Cancel ALL orders, close ALL positions, disable ALL strategies
  - Can be triggered: manually (dashboard button), automatically (circuit breaker), via API
  - Logs everything for audit trail
- `risk/rules_engine.py`:
  - User-defined rules (stored in DB as JSON):
    ```json
    {
      "rule": "if portfolio_drawdown > 5% then pause_all",
      "rule": "if position_loss > $50 on ticker X then close_position",
      "rule": "if daily_pnl < -$200 then emergency_stop"
    }
    ```
  - Rule evaluation engine (simple DSL or condition tree)
- `risk/stop_loss.py`:
  - Per-position stop-loss (price-based, trailing, time-based)
  - Portfolio-level stop-loss
  - Auto-execution when triggered

---

## PHASE 10: Feature Engineering Pipeline
**Goal**: Real-time feature computation for ML models

**Deliverables**:
- `ai/features/price_features.py`:
  - Moving averages (5, 10, 20, 50 period)
  - RSI (14 period)
  - Bollinger Bands (20 period, 2 std)
  - Price velocity and acceleration
  - Bid-ask spread width
  - Price distance from strike
- `ai/features/volume_features.py`:
  - Volume moving average
  - Volume spikes (z-score)
  - Open interest change rate
  - Trade count per period
  - Buy/sell volume ratio
- `ai/features/market_features.py`:
  - Time to expiry (seconds, normalized)
  - Market age (since creation)
  - Cross-market correlation (within event)
  - Event-level aggregate price
  - Category momentum
- `ai/features/orderbook_features.py`:
  - Bid-ask imbalance
  - Depth at each level
  - Order flow imbalance
  - Queue position (if available)
- `ai/feature_store.py`:
  - Redis-backed real-time feature cache
  - Batch feature computation for backtesting
  - Feature versioning (schema changes)

**Latency target**: Full feature vector computation < 20ms per market

---

## PHASE 11: AI Model — Probability Calibration
**Goal**: ML model that estimates true event probabilities better than the market

**Deliverables**:
- `ai/models/calibration_model.py`:
  - XGBoost classifier: P(YES outcome) given features
  - Training pipeline:
    1. Historical markets + outcomes from Kalshi historical API
    2. Feature extraction at multiple timepoints before settlement
    3. Label: actual outcome (1=YES, 0=NO)
    4. Train/validation/test split (time-based, no lookahead)
  - Calibration: Platt scaling or isotonic regression post-hoc
  - Output: calibrated probability estimate
- `ai/models/model_registry.py`:
  - Model versioning and storage
  - A/B model comparison
  - Performance tracking per model version
- `ai/evaluation/`:
  - Brier score (calibration accuracy)
  - Log loss
  - Calibration curves
  - Profit simulation on historical data
- Scheduled retraining pipeline (weekly on new settlement data)

---

## PHASE 12: AI Model — Sentiment & News Analysis
**Goal**: NLP pipeline that extracts trading signals from news and social media

**Deliverables**:
- `ai/sentiment/news_ingestion.py`:
  - RSS feed parser (major news outlets)
  - NewsAPI integration (configurable sources)
  - Polling scheduler (every 30s–60s)
- `ai/sentiment/text_processor.py`:
  - Entity extraction (match news to Kalshi markets)
  - Keyword matching for market categories
  - Deduplication (same story from multiple sources)
- `ai/sentiment/sentiment_model.py`:
  - FinBERT for financial sentiment (positive/negative/neutral)
  - Confidence scoring
  - Batch inference for efficiency
- `ai/sentiment/signal_generator.py`:
  - Aggregate sentiment per market/event
  - Sentiment change detection (spike = potential signal)
  - Cooldown periods (don't re-trade same news)
- Cache: recent sentiment scores per market in Redis

---

## PHASE 13: Strategy Framework & Signal Aggregation
**Goal**: Pluggable strategy system with combined signal output

**Deliverables**:
- `strategies/base.py` — Abstract strategy interface:
  ```python
  class BaseStrategy(ABC):
      async def generate_signals(self, market: Market) -> list[Signal]
      async def on_fill(self, fill: Fill)
      async def on_market_update(self, update: MarketUpdate)
      def get_parameters(self) -> dict
      def set_parameters(self, params: dict)
  ```
- `strategies/calibration_strategy.py` — Trade when model_prob vs market_price diverges
- `strategies/mean_reversion_strategy.py` — Trade on price mean reversion
- `strategies/sentiment_strategy.py` — Trade on news sentiment signals
- `strategies/market_maker_strategy.py` — Place two-sided limit orders for spread
- `strategies/arbitrage_strategy.py` — Cross-market pricing inconsistencies
- `strategies/time_decay_strategy.py` — Sell far-from-money contracts near expiry
- `strategies/custom_rules_strategy.py` — Execute user-defined conditional rules
- `ai/signal_aggregator.py`:
  - Weighted ensemble of strategy signals
  - Conflict resolution (strategy A says buy, strategy B says sell)
  - Confidence-weighted voting
  - Final signal: {ticker, direction, confidence, suggested_size}
- `ai/kelly.py` — Kelly criterion position sizing:
  - Input: signal confidence (as probability edge)
  - Output: fraction of bankroll to allocate
  - Configurable fractional Kelly (default: half-Kelly)
  - Portfolio-level Kelly (multi-position)

---

## PHASE 14: Backtesting Engine
**Goal**: Historical strategy testing with realistic simulation

**Deliverables**:
- `backtest/engine.py`:
  - Event-driven backtester (process historical data chronologically)
  - Simulated order matching (against historical orderbook/trades)
  - Slippage model (configurable: zero, fixed, proportional)
  - Fee model (matches Kalshi fee structure per market)
  - Position tracking through backtest
- `backtest/data_loader.py`:
  - Load historical candlesticks from TimescaleDB
  - Load historical trades
  - Load historical market metadata
  - Support date range selection
- `backtest/metrics.py`:
  - Total return, annualized return
  - Sharpe ratio, Sortino ratio
  - Max drawdown, avg drawdown
  - Win rate, avg win/loss
  - Profit factor
  - Number of trades
  - Fee-adjusted returns
- `backtest/report.py`:
  - Generate backtest report (JSON + charts data)
  - Equity curve
  - Drawdown chart
  - Trade-by-trade log
  - Strategy comparison (side-by-side)
- API endpoint: `POST /api/backtest/run` — trigger backtest from dashboard

---

## PHASE 15: Execution Engine — The Core Loop
**Goal**: The main trading loop that ties everything together with minimal latency

**Deliverables**:
- `engine/trading_loop.py` — The central async loop:
  ```
  Every tick (WebSocket update or timer):
    1. Update market data in memory          (< 1ms)
    2. Update features                       (< 20ms)
    3. Run active strategies → signals       (< 30ms)
    4. Aggregate signals                     (< 5ms)
    5. Risk check signals                    (< 5ms)
    6. Size positions (Kelly)                (< 2ms)
    7. Generate orders                       (< 2ms)
    8. Submit to OMS                         (< 50ms API call)
    ─────────────────────────────────────────
    Total target: < 150ms decision-to-execution
  ```
- `engine/scheduler.py`:
  - Strategy scheduling (which strategies run on which events/intervals)
  - Market-hours aware (respect exchange schedule)
  - Maintenance window handling
- `engine/state_manager.py`:
  - Global state: current mode (live/paper/paused/stopped)
  - Strategy states: per-strategy enable/disable
  - Graceful shutdown (finish pending orders, then stop)
- `engine/health_monitor.py`:
  - API connectivity check
  - WebSocket health
  - Database connectivity
  - Redis connectivity
  - Data freshness
  - Publish health status to dashboard

**Latency budget**:
| Step | Target |
|------|--------|
| WS message → memory | 5ms |
| Feature computation | 20ms |
| Strategy signals | 30ms |
| Risk checks | 5ms |
| Kelly sizing | 2ms |
| Order generation | 2ms |
| API call (network) | 50-100ms |
| **Total** | **~150ms** |

---

## PHASE 16: FastAPI Backend — API Layer
**Goal**: REST + WebSocket API serving the frontend dashboard

**Deliverables**:
- `api/routes/`:
  - `markets.py` — Proxied market data (from Redis cache, not Kalshi direct)
  - `portfolio.py` — Positions, balance, P&L, equity curve
  - `orders.py` — Place/cancel/amend orders (manual + AI)
  - `strategies.py` — CRUD strategy configs, enable/disable, update params
  - `backtest.py` — Run backtest, get results
  - `risk.py` — Risk settings, kill switch, stop-loss configs
  - `signals.py` — Current AI signals, signal history
  - `alerts.py` — CRUD alert rules
  - `system.py` — Health, system status, exchange schedule
- `api/websocket.py`:
  - Dashboard WS endpoint for real-time pushes:
    - Price updates (relayed from Kalshi WS)
    - Position changes
    - Order fills
    - AI signals
    - Risk alerts
    - System health
- `api/middleware.py`:
  - CORS (frontend origin)
  - Request logging
  - Error handling
- `api/auth.py`:
  - Simple auth for dashboard (JWT or session-based)
  - Admin vs. viewer roles

---

## PHASE 17: Frontend — Dashboard Core
**Goal**: Next.js dashboard with market explorer, trading view, and portfolio

**Deliverables**:
- `frontend/src/app/` — Next.js App Router pages:
  - `/` — Dashboard home (summary cards, quick stats)
  - `/markets` — Market explorer (categories, search, filters)
  - `/markets/[ticker]` — Single market trading view
  - `/portfolio` — Positions, P&L, equity curve
  - `/orders` — Order history and management
- Components:
  - `MarketCard` — Compact market display (price, volume, change)
  - `PriceChart` — TradingView Lightweight Charts (candlestick + line)
  - `OrderBook` — Visual orderbook (bid/ask depth)
  - `OrderTicket` — Buy YES / Buy NO form (price, qty, type, TIF)
  - `PositionsTable` — TanStack Table with sorting, filtering
  - `EquityCurve` — Portfolio value over time chart
  - `SummaryCards` — Balance, exposure, day P&L, open orders count
  - `MarketHeatmap` — Category heatmap view
- Real-time:
  - WebSocket connection to backend
  - Live price updates via Zustand store
  - Toast notifications for fills/alerts
- State management:
  - Zustand stores: `useMarketStore`, `usePortfolioStore`, `useOrderStore`
  - React Query for REST data fetching with cache

---

## PHASE 18: Frontend — AI Control Panel & Risk Management
**Goal**: Strategy configuration, signal monitoring, risk management UI

**Deliverables**:
- Pages:
  - `/ai` — AI control panel
  - `/ai/strategies/[id]` — Individual strategy config
  - `/ai/signals` — Signal feed (live)
  - `/ai/backtest` — Backtest runner and results
  - `/risk` — Risk management dashboard
  - `/settings` — System settings, API config placeholder
- AI Control Panel components:
  - `StrategyList` — All strategies with enable/disable toggles
  - `StrategyConfig` — Parameter sliders/inputs per strategy:
    - Kelly fraction slider (0.1 — 1.0)
    - Edge threshold slider
    - Max position per market
    - Markets filter (which markets to trade)
  - `SignalFeed` — Live scrolling signal list with confidence bars
  - `SignalChart` — Signal history overlaid on price chart
  - `BacktestForm` — Strategy + date range + params → run
  - `BacktestResults` — Equity curve, metrics table, trade log
- Risk Management components:
  - `RiskDashboard` — Exposure heatmap, drawdown gauge, concentration chart
  - `StopLossConfig` — Per-position and portfolio stop-loss settings
  - `KillSwitchButton` — Big red emergency stop (with confirmation modal)
  - `RiskRulesEditor` — Create/edit custom risk rules
  - `CircuitBreakerStatus` — Current state of all circuit breakers
  - `AlertsManager` — Create/manage price/volume/P&L alerts

---

## PHASE 19: Integration Testing, Paper Trading & Optimization
**Goal**: End-to-end testing, paper trading mode, performance tuning

**Deliverables**:
- `tests/integration/`:
  - Full flow: market data → features → strategy → signal → order → fill
  - WebSocket reconnection testing
  - Rate limit compliance testing
  - Concurrent strategy execution testing
  - Kill switch response time testing (target: < 500ms to cancel all)
- Paper trading mode:
  - `engine/paper_trader.py`:
    - Simulated order matching against real live prices
    - Virtual balance tracking
    - Same risk engine, same signals — just no real orders
    - Side-by-side comparison: paper vs. live results
  - Toggle in dashboard: Live / Paper / Paused
- Performance optimization:
  - Profile hot paths (feature computation, signal generation)
  - Connection pool tuning (httpx, asyncpg, redis)
  - Memory usage optimization (limit in-memory orderbook depth)
  - Batch DB writes (buffer + flush every 100ms vs. per-event)
  - Redis pipeline commands (batch reads/writes)
- Load testing:
  - Simulate 100+ market subscriptions
  - Measure end-to-end latency under load
  - Identify bottlenecks
- Monitoring setup:
  - Prometheus metrics: order latency, signal count, error rates, WS health
  - Grafana dashboards for ops monitoring
  - Alert rules for anomalies

---

## PHASE 20: Production Deployment & API Key Integration
**Goal**: Deploy to production, inject real API keys, go live with safeguards

**Deliverables**:
- Deployment:
  - Docker production images (multi-stage builds, slim)
  - `docker-compose.prod.yml` with production configs
  - Environment variable injection (secrets management)
  - Health check endpoints for all services
  - Auto-restart policies
- API key integration:
  - Secure key storage (encrypted at rest, never in code/logs)
  - Key rotation support
  - Separate demo vs. production key configs
  - Connection verification on startup
- Go-live checklist:
  ```
  □ All tests passing
  □ Paper trading profitable for 1+ week
  □ Kill switch tested and verified
  □ Circuit breakers configured with conservative limits
  □ Max daily loss set (recommend: $50 initially)
  □ Max position size set (recommend: 10 contracts initially)
  □ Kelly fraction set to quarter-Kelly (0.25)
  □ Only 1-2 strategies enabled initially
  □ Monitoring dashboards active
  □ Alert notifications configured (email/SMS/Discord)
  □ Demo environment verified working
  □ Production API keys injected
  □ Start with smallest possible positions
  □ Monitor first 24 hours manually
  ```
- Documentation:
  - `README.md` — Setup, config, running instructions
  - `OPERATIONS.md` — Monitoring, troubleshooting, scaling
  - `STRATEGIES.md` — Each strategy explained with parameters
  - API documentation (auto-generated from FastAPI)

---

## PHASE DEPENDENCY MAP

```
Phase 1 (Scaffolding)
  ├── Phase 2 (Auth + REST Client)
  │     └── Phase 3 (Full Endpoints)
  │           ├── Phase 6 (Data Ingestion)
  │           │     ├── Phase 10 (Features)
  │           │     │     ├── Phase 11 (Calibration Model)
  │           │     │     └── Phase 12 (Sentiment Model)
  │           │     │           └── Phase 13 (Strategy Framework)
  │           │     │                 ├── Phase 14 (Backtesting)
  │           │     │                 └── Phase 15 (Execution Engine) ← CORE
  │           │     └── Phase 8 (Portfolio Tracker)
  │           └── Phase 7 (OMS)
  │                 └── Phase 9 (Risk Engine)
  ├── Phase 4 (WebSocket Client)
  │     └── Phase 6 (Data Ingestion) ↑ merges above
  ├── Phase 5 (Database Layer)
  │     └── Phase 6 (Data Ingestion) ↑ merges above
  └── Phase 16 (Backend API)
        └── Phase 17 (Frontend Core)
              └── Phase 18 (Frontend AI + Risk)
                    └── Phase 19 (Testing + Paper Trading)
                          └── Phase 20 (Deploy + Go Live)
```

---

## ESTIMATED TIMELINE

| Phase | Name | Est. Effort | Cumulative |
|-------|------|-------------|------------|
| 1 | Scaffolding & Config | 1 session | Day 1 |
| 2 | Auth & Core REST | 1 session | Day 1 |
| 3 | Full Endpoint Coverage | 1-2 sessions | Day 2 |
| 4 | WebSocket Client | 1 session | Day 2 |
| 5 | Database Layer | 1 session | Day 3 |
| 6 | Data Ingestion | 1-2 sessions | Day 3-4 |
| 7 | Order Management | 1-2 sessions | Day 4-5 |
| 8 | Portfolio Tracker | 1 session | Day 5 |
| 9 | Risk Engine | 1-2 sessions | Day 6 |
| 10 | Feature Engineering | 1-2 sessions | Day 7 |
| 11 | Calibration Model | 1-2 sessions | Day 8 |
| 12 | Sentiment Model | 1-2 sessions | Day 9 |
| 13 | Strategy Framework | 1-2 sessions | Day 10 |
| 14 | Backtesting Engine | 1-2 sessions | Day 11 |
| 15 | Execution Engine | 1-2 sessions | Day 12 |
| 16 | Backend API | 1-2 sessions | Day 13 |
| 17 | Frontend Core | 2-3 sessions | Day 14-15 |
| 18 | Frontend AI + Risk | 2-3 sessions | Day 16-17 |
| 19 | Testing + Paper Trade | 2-3 sessions | Day 18-19 |
| 20 | Deploy + Go Live | 1 session | Day 20 |

---

## LATENCY TARGETS SUMMARY

| Metric | Target |
|--------|--------|
| Auth header generation | < 1ms |
| REST API call (network) | 50-100ms |
| WebSocket message → parsed | < 5ms |
| WS → Redis cache update | < 10ms |
| Feature vector computation | < 20ms |
| Strategy signal generation | < 30ms |
| Risk check | < 5ms |
| Kelly sizing | < 2ms |
| **Full loop: data → decision → order sent** | **< 150ms** |
| Kill switch: trigger → all cancelled | < 500ms |
| Dashboard price update | < 200ms end-to-end |

---

*20 phases planned. Ready to build Phase 1 on your command.*
