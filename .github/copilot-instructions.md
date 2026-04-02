# Copilot instructions for JA Hedge

## Big picture
- JA Hedge is a two-app monorepo: `backend/` is a FastAPI trading backend and `frontend/` is a Next.js App Router dashboard.
- The backend is composed at startup in `backend/app/main.py` via one FastAPI lifespan. That file wires the Kalshi API facade, risk manager, execution engine, AI feature/model stack, the legacy `AutonomousAgent`, and the primary `Frankenstein` brain.
- Shared runtime objects live in the singleton `backend/app/state.py`. Route handlers are intentionally thin and usually read from `state` instead of constructing services per request.
- The main live data path is: `KalshiAPI` (`backend/app/kalshi/api.py`) → `MarketDataPipeline` / `PortfolioTracker` (`backend/app/pipeline/`) → in-memory caches + DB persistence → API routes in `backend/app/routes/` → frontend fetches in `frontend/src/lib/api.ts`.
- `Frankenstein` is the current unified AI orchestrator (`backend/app/frankenstein/brain.py`). `TradingStrategy` and `AutonomousAgent` are still initialized for compatibility, so avoid removing them unless the surrounding routes/UI are updated too.

## Backend patterns
- Keep routes thin. Follow `backend/app/routes/orders.py` and `backend/app/routes/markets.py`: validate request/response shapes with Pydantic, then delegate to `state` services.
- Prefer cache-first reads for market data. `market_cache` in `backend/app/pipeline/__init__.py` is the fast path; routes only hit live Kalshi when cache is empty or missing a ticker.
- The app is designed to degrade gracefully when infrastructure is absent. `init_db()` failures are logged and startup continues, so do not make DB availability mandatory unless the feature truly requires it.
- Use the structured logger from `backend/app/logging_config.py`; emit event-style logs with fields rather than ad hoc prints.
- Preserve the request-tracking pattern in `backend/app/middleware.py`: request IDs and latency headers are part of the debugging flow.

## Configuration and environments
- Settings are centralized in `backend/app/config.py` and loaded from the repo root `.env` or the parent directory when running inside `backend/`.
- Demo mode and paper trading are the default local experience. `paper_trading=True` by default, so order flows often execute against `PaperTradingSimulator` rather than the live API.
- Kalshi keys are optional in local/demo flows. `KalshiAPI.from_settings()` falls back to `NoAuth` when keys are absent.
- Important env vars live in `.env.example`, especially `NEXT_PUBLIC_API_URL`, Kalshi key paths, DB/Redis URLs, and risk/strategy thresholds.

## Workflows that matter here
- Backend local run paths are script-driven, not standardized around one command: `backend/start.sh`, `backend/start_bg.sh`, and `backend/run_server.py` are the main entry points.
- `backend/start.sh` uses `~/.jahedge-venv/bin/python`, while `backend/start_bg.sh` uses `backend/.venv`. Check existing scripts before changing environment assumptions.
- The most representative integration check is `backend/test_all.sh`: it expects backend on `localhost:8000` and frontend on `localhost:3000`, then probes health, markets, portfolio, orders, strategy, risk, and dashboard routes.
- There are several ad hoc verification scripts in `backend/` (`smoke_test.py`, `test_api.py`, `test_endpoints.py`, `integration_test.py`) rather than a conventional `tests/` package. Prefer the existing scripts unless you are explicitly introducing a real pytest suite.
- Frontend development is standard Next.js: `frontend/package.json` provides `dev`, `build`, `start`, and `lint`; the helper script is `frontend/start-dev.sh`.

## Cross-component conventions
- Frontend network calls should usually go through `frontend/src/lib/api.ts`; keep new dashboard pages aligned with those typed wrappers instead of scattering raw `fetch` calls.
- Backend API routes are mounted under `/api` in `backend/app/routes/__init__.py`, but health/auth checks live at `/health` and `/health/auth`.
- When adding new trading or AI behavior, consider whether the data should update both live in-memory state and DB persistence. `MarketDataPipeline` and `PortfolioTracker` both do in-memory updates first, then attempt async DB writes.
- Many backend models expose money values as strings/Decimals or `*_cents` integers. Preserve the existing unit conventions instead of normalizing everything to floats.
- If you touch Frankenstein endpoints, keep the operational controls (`/frankenstein/awaken`, `/sleep`, `/pause`, `/resume`, retraining, memory, chat) consistent with the brain state they expose in `backend/app/routes/frankenstein.py`.

## Copilot workflow rules (how the AI assistant should behave)

### Terminal & scripts
- **Never run raw multi-line terminal commands.** They get jumbled and break. Always create or edit a `.sh` / `.py` script first, then run that single script.
- When a task needs more than one terminal command, put them in a script (e.g. `backend/scripts/do_thing.sh`) and execute the script.
- Prefer existing helper scripts (`start.sh`, `start_bg.sh`, `test_all.sh`) over ad-hoc commands.

### Editing
- Always read enough context before editing. Never guess at indentation or surrounding code.
- When multiple independent edits are needed, batch them in one call instead of doing them one at a time.
- Never create a summary/changelog markdown file unless explicitly asked.

### Deploying
- After code changes, always verify the import chain locally (`python -c "from app.main import app; print('OK')"`) before pushing.
- Use `git add -A && git commit -m "<msg>" && git push origin main` as a single script step, not three separate terminal calls.
- After `railway up`, wait at least 90 seconds before hitting the health endpoint to confirm the deploy.

### Debugging
- When something isn't working after deploy, check the **deployed** endpoint output first (e.g. `/health`, `/api/frankenstein/status`, `/api/frankenstein/debug/rejections`) before re-reading local code.
- Include actual API response snippets when reporting status to the user—don't just say "it's deployed."

### Communication
- Be concise. Lead with what changed and what the result was.
- If a deploy or test fails, state the exact error and proposed fix, don't just retry blindly.
- Never say "I'll use tool X"—just do it.
