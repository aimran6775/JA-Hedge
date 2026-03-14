"""Test bootstrap with active markets simulation."""
import asyncio
from app.frankenstein.bootstrap import _features_from_market, bootstrap_from_active_markets
from app.frankenstein.memory import TradeMemory
from app.kalshi.models import Market
from app.pipeline import market_cache
from decimal import Decimal

# Create a few fake markets in cache
for i in range(100):
    price = Decimal(str(round(0.1 + (i * 0.008), 3)))
    m = Market(
        ticker=f"TEST-{i:03d}",
        event_ticker=f"TEST-EV-{i:03d}",
        yes_bid_dollars=max(Decimal("0.01"), price - Decimal("0.02")),
        yes_ask_dollars=min(Decimal("0.99"), price + Decimal("0.02")),
        last_price_dollars=price,
        volume=Decimal(str(50 + i)),
    )
    market_cache._markets[m.ticker] = m

print(f"Cached {len(market_cache._markets)} markets")

# Test bootstrap
memory = TradeMemory(max_trades=10000)
result = asyncio.run(bootstrap_from_active_markets(memory, count=80))
print(f"Bootstrap result: {result}")
print(f"Memory resolved: {memory.total_resolved}")
print(f"Memory recorded: {memory.total_recorded}")

# Check training data
data = memory.get_training_data(min_trades=50)
if data:
    X, y = data
    print(f"✅ Training data ready: X={X.shape}, y={y.shape}, positive_rate={y.mean():.3f}")
else:
    print("❌ Not enough training data")
