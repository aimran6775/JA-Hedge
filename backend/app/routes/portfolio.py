"""
JA Hedge — Portfolio API routes (LIVE Kalshi).

GET /api/portfolio/balance    — Account balance (live from Kalshi)
GET /api/portfolio/positions  — Current positions (live)
GET /api/portfolio/pnl        — P&L summary
GET /api/portfolio/fills      — Recent trade fills
"""

from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.state import state
from app.pipeline.portfolio_tracker import portfolio_state
from app.logging_config import get_logger

log = get_logger("routes.portfolio")

router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


class BalanceResponse(BaseModel):
    balance_dollars: str
    balance_cents: int
    total_exposure: float
    position_count: int
    open_orders: int


class PositionResponse(BaseModel):
    ticker: str
    position: int
    market_exposure_dollars: str | None = None
    realized_pnl_dollars: str | None = None
    fees_paid_dollars: str | None = None


class FillResponse(BaseModel):
    ticker: str
    side: str
    action: str
    count: int | None = None
    price_dollars: str | None = None
    fee_dollars: str | None = None
    created_time: str | None = None
    is_taker: bool | None = None


class PnLResponse(BaseModel):
    daily_pnl: float
    daily_trades: int
    daily_fees: float
    total_exposure: float


@router.get("/balance", response_model=BalanceResponse)
async def get_balance() -> BalanceResponse:
    """Get account balance — paper trader or live Kalshi."""
    # Paper trading mode — use simulator balance
    if state.paper_simulator:
        sim = state.paper_simulator
        bal = sim.get_balance()
        positions = sim.get_positions()
        resting = sum(1 for o in sim._orders.values() if o.status.value == "resting")
        return BalanceResponse(
            balance_dollars=bal.balance_dollars or "0.00",
            balance_cents=bal.balance or 0,
            total_exposure=float(sum(abs(p.market_exposure or 0) for p in positions)),
            position_count=len(positions),
            open_orders=resting,
        )

    if state.kalshi_api:
        try:
            bal = await state.kalshi_api.portfolio.get_balance()
            return BalanceResponse(
                balance_dollars=bal.balance_dollars or f"{(bal.balance or 0) / 100:.2f}",
                balance_cents=bal.balance or 0,
                total_exposure=float(portfolio_state.total_exposure),
                position_count=portfolio_state.position_count,
                open_orders=portfolio_state.open_order_count,
            )
        except Exception as e:
            log.error("balance_fetch_failed", error=str(e))

    return BalanceResponse(
        balance_dollars=portfolio_state.balance_dollars,
        balance_cents=portfolio_state.balance_cents,
        total_exposure=float(portfolio_state.total_exposure),
        position_count=portfolio_state.position_count,
        open_orders=portfolio_state.open_order_count,
    )


@router.get("/positions", response_model=list[PositionResponse])
async def list_positions() -> list[PositionResponse]:
    """List positions — paper trader or live Kalshi."""
    # Paper trading mode
    if state.paper_simulator:
        positions = state.paper_simulator.get_positions()
        return [
            PositionResponse(
                ticker=p.ticker,
                position=p.position or 0,
                market_exposure_dollars=p.market_exposure_dollars,
                realized_pnl_dollars=p.realized_pnl_dollars,
                fees_paid_dollars=p.fees_paid_dollars,
            )
            for p in positions
        ]

    if state.kalshi_api:
        try:
            positions = await state.kalshi_api.portfolio.get_all_positions(
                settlement_status="unsettled", count_filter="non_zero"
            )
            return [
                PositionResponse(
                    ticker=p.ticker,
                    position=p.position or 0,
                    market_exposure_dollars=p.market_exposure_dollars,
                    realized_pnl_dollars=p.realized_pnl_dollars,
                    fees_paid_dollars=p.fees_paid_dollars,
                )
                for p in positions
            ]
        except Exception as e:
            log.error("positions_fetch_failed", error=str(e))

    return [
        PositionResponse(
            ticker=p.ticker,
            position=p.position or 0,
            market_exposure_dollars=p.market_exposure_dollars,
            realized_pnl_dollars=p.realized_pnl_dollars,
            fees_paid_dollars=p.fees_paid_dollars,
        )
        for p in portfolio_state.positions.values()
    ]


@router.get("/fills", response_model=list[FillResponse])
async def list_fills(
    limit: int = Query(50, le=200),
    ticker: str | None = Query(None),
) -> list[FillResponse]:
    """List recent trade fills from Kalshi."""
    # Paper trading mode
    if state.paper_simulator:
        fills = state.paper_simulator.list_fills(limit=limit)
        return [
            FillResponse(
                ticker=f.ticker,
                side=f.side.value,
                action=f.action.value,
                count=f.count,
                price_dollars=f"{(f.yes_price or f.no_price or 0) / 100:.2f}" if (f.yes_price or f.no_price) else None,
                fee_dollars=f"{(f.fee_cost or 0) / 100:.2f}" if f.fee_cost else None,
                created_time=f.created_time.isoformat() if f.created_time else None,
                is_taker=f.is_taker,
            )
            for f in fills
        ]

    if state.kalshi_api:
        try:
            fills, _ = await state.kalshi_api.portfolio.list_fills(
                limit=limit, ticker=ticker
            )
            return [
                FillResponse(
                    ticker=f.ticker,
                    side=f.side.value,
                    action=f.action.value,
                    count=f.count,
                    price_dollars=f.yes_price_dollars or f.no_price_dollars,
                    fee_dollars=f.fee_cost_dollars,
                    created_time=f.created_time.isoformat() if f.created_time else None,
                    is_taker=f.is_taker,
                )
                for f in fills
            ]
        except Exception as e:
            log.error("fills_fetch_failed", error=str(e))
    return []


@router.get("/pnl", response_model=PnLResponse)
async def get_pnl() -> PnLResponse:
    """Get daily P&L summary."""
    # Paper trading — derive from simulator
    if state.paper_simulator:
        sim = state.paper_simulator
        return PnLResponse(
            daily_pnl=sim.pnl_cents / 100.0,
            daily_trades=sim.total_fills,
            daily_fees=sim.total_fees_paid / 100.0,
            total_exposure=sim.total_volume_cents / 100.0,
        )

    return PnLResponse(
        daily_pnl=float(portfolio_state.daily_pnl),
        daily_trades=portfolio_state.daily_trades,
        daily_fees=float(portfolio_state.daily_fees),
        total_exposure=float(portfolio_state.total_exposure),
    )


# ── Paper Trading Endpoints ──────────────────────────────────────────────────


class PaperTradingStatus(BaseModel):
    enabled: bool
    balance_dollars: str
    starting_balance: str
    pnl_dollars: str
    total_orders: int
    total_fills: int
    resting_orders: int
    open_positions: int
    total_volume: str
    total_fees: str


@router.get("/paper", response_model=PaperTradingStatus)
async def paper_trading_status() -> PaperTradingStatus:
    """Get paper trading simulator status."""
    if not state.paper_simulator:
        return PaperTradingStatus(
            enabled=False,
            balance_dollars="0.00",
            starting_balance="0.00",
            pnl_dollars="0.00",
            total_orders=0,
            total_fills=0,
            resting_orders=0,
            open_positions=0,
            total_volume="0.00",
            total_fees="0.00",
        )

    summary = state.paper_simulator.summary()
    return PaperTradingStatus(
        enabled=True,
        balance_dollars=summary["balance_dollars"],
        starting_balance=summary["starting_balance"],
        pnl_dollars=summary["pnl_dollars"],
        total_orders=summary["total_orders"],
        total_fills=summary["total_fills"],
        resting_orders=summary["resting_orders"],
        open_positions=summary["open_positions"],
        total_volume=summary["total_volume"],
        total_fees=summary["total_fees"],
    )


@router.post("/paper/reset")
async def paper_trading_reset(
    balance_cents: int | None = None,
) -> dict:
    """Reset the paper trading simulator with optional new balance."""
    if not state.paper_simulator:
        return {"error": "paper trading not enabled"}

    from app.engine.paper_trader import PaperTradingSimulator
    from app.config import get_settings

    new_balance = balance_cents or get_settings().paper_trading_balance
    new_sim = PaperTradingSimulator(starting_balance_cents=new_balance)

    # Re-wrap the real Kalshi API
    if state.kalshi_api:
        wrapped = new_sim.wrap_api(state.kalshi_api)
        if state.execution_engine:
            state.execution_engine._api = wrapped

    state.paper_simulator = new_sim
    return {
        "status": "reset",
        "balance_dollars": new_sim.balance_dollars,
    }
