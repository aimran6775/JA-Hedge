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
    """Get account balance — live from Kalshi demo API."""
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
    """List positions — live from Kalshi."""
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
    return PnLResponse(
        daily_pnl=float(portfolio_state.daily_pnl),
        daily_trades=portfolio_state.daily_trades,
        daily_fees=float(portfolio_state.daily_fees),
        total_exposure=float(portfolio_state.total_exposure),
    )
