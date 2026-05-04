"""Quick behavioural test: heuristic should not produce structural YES bias."""
import statistics
import random
from datetime import datetime, timezone
from app.ai.models import XGBoostPredictor
from app.ai.features import MarketFeatures


def main() -> None:
    p = XGBoostPredictor()
    sides: list[str] = []
    edges: list[float] = []
    random.seed(0)
    for _ in range(500):
        mid = max(0.05, min(0.95, random.betavariate(3, 2)))  # skewed positive
        f = MarketFeatures(ticker="TEST", timestamp=datetime.now(timezone.utc))
        f.midpoint = mid
        f.spread = 0.02
        f.spread_pct = 0.04
        f.last_price = mid
        f.volume = 100.0
        f.volume_ratio = 1.0
        f.open_interest = 500.0
        f.price_change_1m = random.uniform(-0.01, 0.01)
        f.price_change_5m = random.uniform(-0.02, 0.02)
        f.price_change_15m = 0.0
        f.rsi_14 = random.uniform(30, 70)
        f.macd = random.uniform(-0.01, 0.01)
        f.hours_to_expiry = random.uniform(1, 100)
        pred = p._heuristic_predict(f)
        sides.append(pred.side)
        edges.append(pred.edge)
    yes = sides.count("yes")
    no = sides.count("no")
    print(f"YES: {yes} ({yes / len(sides):.1%})  NO: {no} ({no / len(sides):.1%})")
    print(
        f"mean edge: {statistics.mean(edges):+.5f}  "
        f"abs mean: {statistics.mean(abs(e) for e in edges):.5f}"
    )
    print(
        f"|edge| < 0.005 (skip): {sum(1 for e in edges if abs(e) < 0.005)} / {len(edges)}"
    )


if __name__ == "__main__":
    main()
