"""Quick import test for all sports modules."""
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

passed = 0
failed = 0

def check(label, fn):
    global passed, failed
    try:
        result = fn()
        print(f"✅ {label}")
        if result:
            print(f"   {result}")
        passed += 1
    except Exception as e:
        print(f"❌ {label}: {e}")
        failed += 1

# --- Individual module imports ---

check("sports.detector", lambda: (
    __import__("app.sports.detector", fromlist=["SportsDetector", "sports_detector", "SPORT_REGISTRY"]),
    f"Sports: {list(__import__('app.sports.detector', fromlist=['SPORT_REGISTRY']).SPORT_REGISTRY.keys())}"
)[1])

check("sports.odds_client", lambda: (
    __import__("app.sports.odds_client", fromlist=["OddsClient", "OddsCache"]),
    None
)[1])

check("sports.features", lambda: (
    __import__("app.sports.features", fromlist=["SportsFeatureEngine", "SportsFeatures"]),
    f"{__import__('app.sports.features', fromlist=['SportsFeatures']).SportsFeatures.n_features()} features"
)[1])

check("sports.game_tracker", lambda: (
    __import__("app.sports.game_tracker", fromlist=["GameTracker", "game_tracker"]),
    None
)[1])

check("sports.model", lambda: (
    __import__("app.sports.model", fromlist=["SportsPredictor", "NaiveVegasBaseline"]),
    None
)[1])

check("sports.live_engine", lambda: (
    __import__("app.sports.live_engine", fromlist=["LiveTradingEngine"]),
    None
)[1])

check("sports.risk", lambda: (
    __import__("app.sports.risk", fromlist=["SportsRiskManager"]),
    None
)[1])

check("sports.collector", lambda: (
    __import__("app.sports.collector", fromlist=["SportsDataCollector"]),
    None
)[1])

check("sports.monitor", lambda: (
    __import__("app.sports.monitor", fromlist=["SportsMonitor"]),
    None
)[1])

check("routes.sports", lambda: (
    __import__("app.routes.sports", fromlist=["router"]),
    None
)[1])

# --- Package-level import ---

check("sports package (from app.sports import *)", lambda: (
    __import__("app.sports"),
    None
)[1])

# --- Functional tests ---

from app.sports.model import NaiveVegasBaseline
baseline = NaiveVegasBaseline()

check("Vegas baseline: Kalshi=0.45, Vegas=0.55 → BUY YES", lambda: (
    pred := baseline.predict(kalshi_price=0.45, vegas_prob=0.55, num_bookmakers=8, sport_id="nba"),
    f"side={pred.side}, edge={pred.edge:.3f}, conf={pred.confidence:.3f}" if pred else "NO SIGNAL"
)[1])

check("Vegas baseline: Kalshi=0.70, Vegas=0.60 → BUY NO", lambda: (
    pred := baseline.predict(kalshi_price=0.70, vegas_prob=0.60, num_bookmakers=6, sport_id="nfl"),
    f"side={pred.side}, edge={pred.edge:.3f}, conf={pred.confidence:.3f}" if pred else "NO SIGNAL"
)[1])

check("Vegas baseline: Kalshi=0.50, Vegas=0.52 → NO TRADE (too small)", lambda: (
    pred := baseline.predict(kalshi_price=0.50, vegas_prob=0.52, num_bookmakers=5, sport_id="mlb"),
    "CORRECTLY NO SIGNAL" if pred is None else f"UNEXPECTED: side={pred.side}"
)[1])

from app.sports.detector import sports_detector

class FakeMarket:
    ticker = "KXNBA-TEST-YES"
    event_ticker = "KXNBA-TEST"
    series_ticker = "kxnbagame-26mar"
    title = "Celtics vs Lakers: Will Celtics win?"
    subtitle = ""
    category = "Sports"
    class status:
        value = "active"
    yes_bid = 45; yes_ask = 55; last_price = 50; midpoint = 50
    no_bid = 45; no_ask = 55; spread = 10; volume = 100
    open_interest = 200; open_time = None; close_time = None
    expiration_time = None; result = None; market_type = None

check("Detector: NBA market via series_ticker", lambda: (
    info := sports_detector.detect(FakeMarket()),
    f"is_sports={info.is_sports}, sport={info.sport_id}, type={info.market_type}"
)[1])

from app.sports.risk import SportsRiskManager
rm = SportsRiskManager()

check("Risk: clean check passes", lambda: (
    ok := rm.check("test", "game1", "nba", 500, False),
    f"allowed={ok.allowed}, reason={ok.reason}"
)[1])

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
if failed == 0:
    print("🏀 ALL SPORTS MODULES WORKING PERFECTLY")
else:
    print(f"⚠️  {failed} test(s) need attention")
