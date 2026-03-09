"""
JA Hedge — Backtesting API routes.

POST /api/backtest/run     — Run a backtest with config
GET  /api/backtest/status   — Check running backtest status
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.state import state

router = APIRouter(prefix="/backtest", tags=["Backtesting"])


class BacktestRequest(BaseModel):
    tickers: list[str] = []
    days: int = 30
    starting_balance: float = 1000.0
    min_confidence: float = 0.60
    min_edge: float = 0.05
    kelly_fraction: float = 0.25
    max_position_size: int = 20
    slippage_cents: int = 1


class BacktestSummary(BaseModel):
    strategy_name: str
    net_pnl: float
    net_pnl_pct: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    duration_days: float


@router.post("/run")
async def run_backtest(body: BacktestRequest) -> dict:
    """
    Run a backtest on historical data.

    Uses the same AI model and feature engine as live trading.
    """
    if not state.prediction_model or not state.feature_engine:
        raise HTTPException(503, detail="AI engine not initialized")

    from app.backtesting import BacktestEngine, BacktestConfig, HistoricalBar

    config = BacktestConfig(
        starting_balance_cents=int(body.starting_balance * 100),
        min_confidence=body.min_confidence,
        min_edge=body.min_edge,
        kelly_fraction=body.kelly_fraction,
        max_position_size=body.max_position_size,
        slippage_cents=body.slippage_cents,
    )

    engine = BacktestEngine(
        model=state.prediction_model,
        feature_engine=state.feature_engine,
        config=config,
    )

    # Load historical data from Kalshi API (if available) or DB
    bars_by_ticker: dict[str, list[HistoricalBar]] = {}

    if state.kalshi_api and body.tickers:
        import time
        now = int(time.time())
        start = now - body.days * 86400

        for ticker in body.tickers[:10]:  # cap at 10 tickers
            try:
                candles = await state.kalshi_api.historical.get_candlesticks(
                    series_ticker=ticker,
                    market_ticker=ticker,
                    period_interval=60,  # 1 hour candles
                    start_ts=start,
                    end_ts=now,
                )
                bars = [
                    HistoricalBar(
                        ticker=ticker,
                        timestamp=c.end_period_ts,
                        open=c.price.open if c.price else 50,
                        high=c.price.high if c.price else 50,
                        low=c.price.low if c.price else 50,
                        close=c.price.close if c.price else 50,
                        volume=c.volume or 0,
                    )
                    for c in candles
                ]
                if bars:
                    bars_by_ticker[ticker] = bars
            except Exception:
                continue

    if not bars_by_ticker:
        # Generate synthetic data for demo/testing
        import time
        now = time.time()
        for ticker in (body.tickers or ["DEMO-MKT"]):
            bars = []
            price = 50
            for i in range(body.days * 24):
                import random
                delta = random.randint(-3, 3)
                price = max(5, min(95, price + delta))
                bars.append(
                    HistoricalBar(
                        ticker=ticker,
                        timestamp=now - (body.days * 24 - i) * 3600,
                        open=price,
                        high=min(price + 2, 99),
                        low=max(price - 2, 1),
                        close=price,
                        volume=random.randint(10, 500),
                    )
                )
            bars_by_ticker[ticker] = bars

    result = await engine.run(bars_by_ticker, strategy_name="dashboard_backtest")
    return result.to_dict()
