"""JA Hedge — API Routes package."""

from fastapi import APIRouter

from app.routes.markets import router as markets_router
from app.routes.portfolio import router as portfolio_router
from app.routes.orders import router as orders_router
from app.routes.strategy import router as strategy_router
from app.routes.risk import router as risk_router
from app.routes.alerts import router as alerts_router
from app.routes.backtest import router as backtest_router
from app.routes.agent import router as agent_router
from app.routes.frankenstein import router as frankenstein_router
from app.routes.sports import router as sports_router
from app.routes.dashboard import router as dashboard_router
from app.routes.strategies import router as strategies_router
from app.routes.intelligence import router as intelligence_router
from app.routes.stream import router as stream_router
from app.routes.metrics import router as metrics_router

api_router = APIRouter(prefix="/api")
api_router.include_router(markets_router)
api_router.include_router(portfolio_router)
api_router.include_router(orders_router)
api_router.include_router(strategy_router)
api_router.include_router(risk_router)
api_router.include_router(alerts_router)
api_router.include_router(backtest_router)
api_router.include_router(agent_router)
api_router.include_router(frankenstein_router)
api_router.include_router(sports_router)
api_router.include_router(dashboard_router)
api_router.include_router(strategies_router)
api_router.include_router(intelligence_router)
api_router.include_router(stream_router)
api_router.include_router(metrics_router)
