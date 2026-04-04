# Copilot instructions for JA Hedge

## Architecture overview
- **Monorepo**: `backend/` (FastAPI + Python 3.11) and `frontend/` (Next.js 15 + React 19 + Tailwind).
- **Domain**: AI-powered algorithmic trading on Kalshi event contracts (politics, sports, weather, crypto, etc.).
- **Production URL**: `frankensteintrading.com`. Deployed on Railway (backend) with a Dockerfile at the repo root. Frontend is also on Railway or standalone.

### Backend startup & composition
- `backend/app/main.py` has a single `lifespan` async context manager that wires **all** runtime components in order: DB → KalshiAPI → RiskManager → PaperTradingSimulator → ExecutionEngine → AI stack (FeatureEngine, EnsemblePredictor, TradingStrategy, AutonomousAgent) → **Frankenstein** brain → StrategyEngine → Sports module → MarketDataPipeline → PortfolioTracker → Intelligence system → auto-awaken Frankenstein.
- `backend/app/state.py` is a singleton `AppState` dataclass. All route handlers read from `state` rather than constructing services. When adding a new subsystem, add the attribute here and populate it in `main.py` lifespan.
- `TradingStrategy` and `AutonomousAgent` are legacy — kept for backward-compatible routes/UI. Don't remove them unless you update the dependent routes and dashboard tabs.

### Data flow (live path)
```
KalshiAPI (kalshi/api.py)
  → MarketDataPipeline (pipeline/__init__.py)  — polling + WS
  → MarketCache (in-memory dict, sub-ms lookups)
  → FeatureEngine (ai/features.py)  — technical indicators per ticker
  → Frankenstein.scan_loop → Scanner → OrderManager → ExecutionEngine
  → PaperTradingSimulator or live Kalshi API
  → API routes (routes/) → frontend (lib/api.ts)
```

### Frankenstein brain architecture (`backend/app/frankenstein/`)
Frankenstein is a modular orchestrator (~965 LOC in `brain.py`). After Phase 1 split, the Brain delegates to:
| Module | Responsibility |
|---|---|
| `scanner.py` (~1640 LOC) | Market scanning, feature computation, signal evaluation, trade selection |
| `order_manager.py` (~1331 LOC) | Order placement (maker/taker), pricing, requoting, stale-order cleanup |
| `positions.py` | Active position management, exit logic |
| `resolver.py` | Outcome resolution, calibration, category stats |
| `learner.py` | Online retraining (XGBoost), champion/challenger model promotion |
| `memory.py` (~717 LOC) | Trade memory buffer, persistence to JSON, experience replay |
| `performance.py` | Win rate, Sharpe, drawdown, regime detection |
| `strategy.py` | Adaptive parameters (confidence, edge, Kelly, aggression) |
| `ws_bridge.py` | WebSocket bridge: real-time Kalshi data → EventBus |
| `event_bus.py` | Async pub/sub (TICKER_UPDATE, FILL_RECEIVED, BOOK_CHANGED, CAPITAL_FREED) |
| `constants.py` | All tunable constants (fees, caps, circuit breaker, diversification limits) |
| `capital_allocator.py` | Capital tracking and recycling across positions |
| `fill_predictor.py` | Fill-rate prediction for maker orders |
| `confidence.py` | Multi-factor confidence scoring with grade system |
| `categories.py` | Per-category strategy specialization |

**Key design**: Frankenstein uses **maker orders** (`USE_MAKER_ORDERS = True` in `constants.py`) — 0¢ fees vs 7¢/contract taker fees. This is the core profitability strategy. The hold-to-settlement approach avoids sell-side fees entirely.

### Sports module (`backend/app/sports/`)
- `detector.py` — Parses Kalshi tickers to identify sport, market type, teams (e.g., `kxnbagame-26mar11cleorl` → NBA, CLE vs ORL)
- `odds_client.py` — The Odds API v4 integration for Vegas lines
- `live_engine.py` — In-game trading signals (score arbitrage, momentum scalping, garbage time detection)
- `collector.py` / `monitor.py` — Background data collection and game state monitoring
- Sports components are injected into Frankenstein via `main.py` after both are created, using `frankenstein._sports_*` attributes

### Intelligence system (`backend/app/intelligence/`)
- `hub.py` — DataSourceHub: central registry polling 9 sources on independent intervals
- `base.py` — `DataSource` ABC + `SourceSignal` dataclass (normalized −1.0 to +1.0 signal values)
- Sources in `sources/`: sports_odds, news_sentiment, social_reddit, weather, crypto, polymarket, economic, political, google_trends
- `fusion.py` — Merges multi-source signals into feature vectors
- `confidence.py` / `correlation.py` / `quality.py` — Source reliability tracking
- Entire system is optional — gated by `intelligence_enabled` setting; startup continues if it fails

### Kalshi API client (`backend/app/kalshi/`)
- `api.py` — Unified facade: `.markets`, `.portfolio`, `.orders`, `.exchange`, `.historical`
- `auth.py` — RSA-PSS signing (`KalshiAuth`) or `NoAuth` for unauthenticated mode
- `client.py` — httpx async client with `RateLimiter` (read/write per-second limits)
- `models.py` — Pydantic models for all API types (Market, Order, Position, etc.)
- `ws_client.py` — WebSocket client for real-time ticker/orderbook data
- `from_settings()` factory auto-selects demo vs production endpoints based on `JAHEDGE_MODE`

## Backend patterns
- **Thin routes**: Follow `routes/orders.py` and `routes/markets.py` — validate with Pydantic, delegate to `state` services. Route helpers like `_get_frank()` raise 503 if component is missing.
- **Cache-first reads**: `market_cache` (in `pipeline/__init__.py`) is the fast path. Routes fall through to live Kalshi only when cache misses.
- **Graceful degradation**: DB init failures are logged and startup continues (`state.db_available` flag). Sports, Intelligence, WebSocket — all wrapped in try/except at startup. Never make optional infrastructure mandatory.
- **Structured logging**: Use `from app.logging_config import get_logger`; emit event-style logs with keyword fields, e.g. `log.info("trade_executed", ticker=t, edge=e)`. No `print()`.
- **Request tracking**: `middleware.py` adds `x-request-id` and `x-response-time` headers to every response. Slow requests (>2s) auto-logged as warnings.
- **Money values**: Always `*_cents` (int) for internal math, `*_dollars` (string/Decimal) for display. Never normalize to floats for money.
- **Production persistence**: `production.py` provides `SQLiteStore` for Frankenstein's trade/performance data (no external DB needed), `ExchangeSchedule` for Kalshi hours, `HealthMonitor` for uptime metrics.

## Configuration (`backend/app/config.py`)
- Pydantic Settings loaded from `.env` (auto-finds in CWD or parent dir).
- `JAHEDGE_MODE=demo|production` — auto-selects Kalshi API URLs (demo-api vs api.elections).
- `paper_trading=True` by default — orders go through `PaperTradingSimulator`. Starting balance: $10,000 (1,000,000 cents).
- Kalshi keys optional locally — `NoAuth` fallback allows read-only market browsing.
- Key env vars: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`, `THE_ODDS_API_KEY`, `NEWSAPI_KEY`, `INTELLIGENCE_ENABLED`, `SPORTS_ONLY_MODE`, `PERSIST_DIR`.
- Risk defaults: `risk_max_daily_loss=150`, `risk_max_position_size=10`, `risk_max_portfolio_exposure=1500`.
- Strategy defaults: `strategy_min_confidence=0.60`, `strategy_min_edge=0.05`, `strategy_kelly_fraction=0.25`, `strategy_scan_interval=30s`.

## Frontend (`frontend/`)
- Next.js 15 App Router with Turbopack dev server. Dark theme, Inter + JetBrains Mono fonts.
- **State**: Zustand store in `lib/store.ts` (currently just tab state: `live | analytics | markets | control`).
- **API layer**: `lib/api.ts` (~950 LOC) — typed `apiFetch<T>()` wrapper + comprehensive TypeScript interfaces for every backend response. Organized as `api.frankenstein.*`, `api.sports.*`, `api.intelligence.*`, etc. **All new API calls must go through this file.**
- **Dashboard**: `app/dashboard/page.tsx` renders 4 tabs via `_tabs/` folder: `LiveTab`, `AnalyticsTab`, `MarketsTab`, `ControlTab`. Sub-pages exist under `dashboard/` for deeper views (frankenstein, sports, intelligence, strategies, etc.).
- **UI stack**: Tailwind CSS + `clsx`/`tailwind-merge` via `cn()` utility, `lucide-react` icons, `lightweight-charts` for price charts, `@tanstack/react-query` + `react-table`, `sonner` for toasts, `zod` + `react-hook-form` for forms.
- **Utilities**: `lib/utils.ts` — `cn()`, `centsToDollars()`, `formatProb()`, `formatCompact()`.
- **Layout**: `components/layout/TopBar.tsx` + `TabBar.tsx` wrap the dashboard.

## API route map
All routes under `/api` via `routes/__init__.py`. Health at root level.
| Prefix | File | Purpose |
|---|---|---|
| `/health`, `/health/auth` | `main.py` | System + Kalshi auth health |
| `/api/markets` | `routes/markets.py` | Market listing + detail |
| `/api/portfolio` | `routes/portfolio.py` | Balance, positions, fills, PnL |
| `/api/orders` | `routes/orders.py` | Manual order placement/cancel |
| `/api/strategy` | `routes/strategy.py` | Legacy TradingStrategy controls |
| `/api/risk` | `routes/risk.py` | Risk snapshot, limits, kill switch |
| `/api/alerts` | `routes/alerts.py` | Alert management |
| `/api/backtest` | `routes/backtest.py` | Backtesting |
| `/api/agent` | `routes/agent.py` | Legacy AutonomousAgent |
| `/api/frankenstein` | `routes/frankenstein.py` (~1077 LOC) | Brain status, controls (awaken/sleep/pause/resume), trades, settings, debug, chat |
| `/api/sports` | `routes/sports.py` | Sports markets, odds, live games, signals |
| `/api/dashboard` | `routes/dashboard.py` | Aggregated overview (single call for dashboard) |
| `/api/strategies` | `routes/strategies.py` | Pre-built strategy engine |
| `/api/intelligence` | `routes/intelligence.py` | Multi-source intelligence dashboard, signals, alerts |

## Workflows

### Local development
- **Backend**: `cd backend && source .venv/bin/activate && python run_server.py` (or use `start.sh` / `start_bg.sh`). Note: `start.sh` uses `~/.jahedge-venv/bin/python`; `start_bg.sh` uses `backend/.venv`.
- **Frontend**: `cd frontend && npm run dev` (Turbopack). Or use `frontend/start-dev.sh`.
- **Infrastructure**: `docker-compose up db redis` for Postgres (TimescaleDB) + Redis. Both optional for dev — app degrades gracefully.
- **Import check**: After changes, verify `cd backend && python -c "from app.main import app; print('OK')"`.

### Testing
- **Integration tests**: `backend/test_all.sh` — expects backend on `:8000` and frontend on `:3000`, probes all major endpoints.
- **Ad hoc scripts**: `backend/smoke_test.py`, `test_api.py`, `test_endpoints.py`, `integration_test.py` — favor these over raw curl.
- **Pytest suite**: `backend/tests/` with `conftest.py` providing fixtures for CalibrationTracker, Prediction, TradeMemory, StrategyParams. Run: `cd backend && pytest tests/`.
- **Ruff lint**: `ruff check --target-version py311` (configured in `pyproject.toml`).

### Deployment (Railway)
- `Dockerfile` at repo root: builds from `python:3.11-slim`, copies `backend/`, installs deps via `pyproject.toml`.
- `entrypoint.sh` decodes `KALSHI_PRIVATE_KEY_BASE64` env var → `/app/keys/kalshi.pem`, then runs uvicorn.
- `railway.toml` sets healthcheck on `/health`, restart on failure.
- Persist Frankenstein state: mount a Railway volume at `/data` and set `PERSIST_DIR=/data`.
- CORS origins: hardcoded for `localhost:3000` + `frankensteintrading.com` + `CORS_ORIGINS` env var for extras.

## Frankenstein-specific conventions
- **Lifecycle**: `awaken()` starts scan loop + WS bridge + scheduler. `sleep()` saves memory + stops everything. `pause()/resume()` control trading without full shutdown.
- **Circuit breaker**: Auto-pauses if accuracy < 35% over last 15 trades. 2-hour cooldown (`constants.py`).
- **Daily trade cap**: 150 trades/day (`MAX_DAILY_TRADES`). Resets at midnight.
- **Edge caps per category**: Defined in `CATEGORY_EDGE_CAPS` — sports/finance capped at 8%, entertainment/social_media up to 12-14%.
- **Constants live in `constants.py`**: Fee rates, maker mode, trade caps, price floors, diversification limits, requote params. Tune there, not scattered across modules.
- **EventBus**: Async pub/sub between modules. Key events: `TICKER_UPDATE` (WS price change → reactive scan), `FILL_RECEIVED` (order filled), `BOOK_CHANGED` (orderbook update → requote), `CAPITAL_FREED` (position closed → re-scan).
- **Settings endpoint**: `PUT /api/frankenstein/settings` allows runtime tuning of strategy params, scan interval, sports-only mode — without restart.

## Copilot workflow rules

### Terminal & scripts
- **Never run raw multi-line terminal commands.** Always create or edit a `.sh` / `.py` script first, then run that single script.
- When a task needs more than one terminal command, put them in a script (e.g. `backend/scripts/do_thing.sh`).
- Prefer existing helper scripts (`start.sh`, `start_bg.sh`, `test_all.sh`) over ad-hoc commands.

### Editing
- Always read enough context before editing. Never guess at indentation or surrounding code.
- When multiple independent edits are needed, batch them in one call instead of doing them one at a time.
- Never create a summary/changelog markdown file unless explicitly asked.

### Deploying
- After code changes, verify the import chain locally (`python -c "from app.main import app; print('OK')"`) before pushing.
- Use `git add -A && git commit -m "<msg>" && git push origin main` as a single script step, not three separate terminal calls.
- After `railway up`, wait at least 90 seconds before hitting the health endpoint to confirm the deploy.

### Debugging
- When something isn't working after deploy, check the **deployed** endpoint output first (e.g. `/health`, `/api/frankenstein/status`, `/api/frankenstein/debug/rejections`) before re-reading local code.
- Include actual API response snippets when reporting status to the user—don't just say "it's deployed."

### Communication
- Be concise. Lead with what changed and what the result was.
- If a deploy or test fails, state the exact error and proposed fix, don't just retry blindly.
- Never say "I'll use tool X"—just do it.
