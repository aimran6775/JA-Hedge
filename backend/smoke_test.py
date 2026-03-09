"""Quick smoke test: can all components initialise?"""
import sys
sys.path.insert(0, ".")

from app.config import get_settings

s = get_settings()
print(f"Mode: {s.jahedge_mode.value}")
print(f"Has keys: {s.has_api_keys}")
print(f"Key path: {s.kalshi_private_key_path}")
print(f"DB URL: {s.database_url}")
print()

from app.kalshi.api import KalshiAPI
api = KalshiAPI.from_settings(s)
print("✅ Kalshi API created")

from app.engine.risk import RiskManager, RiskLimits
risk = RiskManager(limits=RiskLimits())
print("✅ Risk manager created")

from app.engine.execution import ExecutionEngine
engine = ExecutionEngine(api=api, risk_manager=risk)
print("✅ Execution engine created")

from app.ai.features import FeatureEngine
from app.ai.models import XGBoostPredictor
fe = FeatureEngine()
model = XGBoostPredictor()
print(f"✅ AI model created: {model.name}")

from app.ai.strategy import TradingStrategy
strat = TradingStrategy(
    model=model, feature_engine=fe,
    execution_engine=engine, risk_manager=risk,
)
print("✅ Trading strategy created")

from app.pipeline import MarketDataPipeline
pipeline = MarketDataPipeline(api=api)
print("✅ Market data pipeline created")

from app.pipeline.portfolio_tracker import PortfolioTracker
tracker = PortfolioTracker(api=api)
print("✅ Portfolio tracker created")

from app.alerts import alert_manager
print("✅ Alert manager ready")

print()
print("🟢 ALL COMPONENTS INITIALISE SUCCESSFULLY")
