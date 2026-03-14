"""Quick test for bootstrap module."""
from app.frankenstein.bootstrap import _features_from_market
from app.kalshi.models import Market
from decimal import Decimal

print("✅ Bootstrap module imports OK")

# Use alias names or Decimal for dollar fields
m = Market(
    ticker="TEST", event_ticker="TEST-EV",
    yes_bid_dollars=Decimal("0.40"), yes_ask_dollars=Decimal("0.45"),
    last_price_dollars=Decimal("0.42"), volume=100,
)
feats = _features_from_market(m, jitter=False)
arr = feats.to_array()
print(f"✅ Features computed: {arr.shape[0]} dims, midpoint={feats.midpoint:.3f}")

# Verify Market model now has result field
m2 = Market(ticker="TEST2", event_ticker="TEST2-EV", result="yes")
print(f"✅ Market result field: {m2.result}")

# Test settled market (no bid/ask, just last price)
m3 = Market(
    ticker="SETTLED", event_ticker="SETTLED-EV",
    last_price_dollars=Decimal("0.95"), result="yes",
)
feats3 = _features_from_market(m3, jitter=False)
print(f"✅ Settled market features: mid={feats3.midpoint:.3f}, spread={feats3.spread:.3f}")

print("\n✅ All bootstrap tests passed!")
