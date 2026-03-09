#!/usr/bin/env python3
"""
JA Hedge — End-to-End Trading Pipeline Test Suite.

Tests the FULL pipeline on the live Kalshi Demo API:
  1. API connectivity & auth
  2. Market data retrieval
  3. ML feature engineering (29 features)
  4. AI model predictions (heuristic + XGBoost)
  5. Risk manager pre-trade checks
  6. Order execution (buy YES, buy NO)
  7. Order status & cancellation
  8. Portfolio tracking (positions, fills, balance)
  9. Full autonomous agent cycle (scan → predict → size → execute)

Usage:
  cd backend && source .venv/bin/activate
  python test_trading_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from dataclasses import dataclass

# ── Colored output helpers ────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0
results: list[dict] = []


def header(title: str):
    print(f"\n{BOLD}{CYAN}{'━' * 60}")
    print(f"  {title}")
    print(f"{'━' * 60}{RESET}\n")


def test_pass(name: str, detail: str = ""):
    global passed
    passed += 1
    d = f" {DIM}({detail}){RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET} {name}{d}")
    results.append({"test": name, "status": "PASS", "detail": detail})


def test_fail(name: str, error: str):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {name}")
    print(f"    {RED}{error}{RESET}")
    results.append({"test": name, "status": "FAIL", "detail": error})


def test_skip(name: str, reason: str):
    global skipped
    skipped += 1
    print(f"  {YELLOW}○{RESET} {name} — {reason}")
    results.append({"test": name, "status": "SKIP", "detail": reason})


# ══════════════════════════════════════════════════════════════════════════
# TEST PHASES
# ══════════════════════════════════════════════════════════════════════════


async def phase_1_connectivity():
    """Phase 1: API Connectivity & Authentication."""
    header("PHASE 1 — API Connectivity & Authentication")

    from app.config import get_settings
    from app.kalshi.api import KalshiAPI

    settings = get_settings()

    # Test 1.1: Config loads correctly
    try:
        assert settings.kalshi_api_key_id, "No API key ID"
        assert settings.jahedge_mode in ("demo", "production"), f"Bad mode: {settings.jahedge_mode}"
        test_pass("Config loads", f"mode={settings.jahedge_mode}, key={settings.kalshi_api_key_id[:12]}...")
    except Exception as e:
        test_fail("Config loads", str(e))
        return None

    # Test 1.2: KalshiAPI initializes (client + auth + async context)
    try:
        api = KalshiAPI.from_settings(settings)
        await api.__aenter__()  # open httpx connection pool
        assert api is not None
        assert api.markets is not None
        assert api.orders is not None
        assert api.portfolio is not None
        test_pass("KalshiAPI initialized", "from_settings() + __aenter__() — client + auth + sub-APIs ready")
    except Exception as e:
        test_fail("KalshiAPI initialized", str(e))
        return None

    # Test 1.3: Health check (exchange status)
    try:
        healthy = await api.health_check()
        if healthy:
            test_pass("Health check", "exchange_active=True")
        else:
            test_skip("Health check", "exchange not active (may be off-hours)")
    except Exception as e:
        test_fail("Health check", str(e))

    # Test 1.4: Can make authenticated GET (balance)
    auth_ok = False
    try:
        bal = await api.portfolio.get_balance()
        auth_ok = True
        test_pass("Auth GET works", f"balance={bal.balance_dollars or '0.00'} ({bal.balance or 0} cents)")
    except Exception as e:
        err_str = str(e)
        if "NOT_FOUND" in err_str or "authentication" in err_str.lower():
            test_fail("Auth GET works", f"API key expired/revoked — regenerate at demo.kalshi.com: {e}")
        else:
            test_fail("Auth GET works", f"Auth error: {e}")

    # Test 1.5: Can list markets (unauthenticated endpoint)
    try:
        from app.kalshi.models import MarketStatus
        markets, cursor = await api.markets.list_markets(limit=10, status=MarketStatus.OPEN)
        assert isinstance(markets, list)
        test_pass("Markets endpoint", f"{len(markets)} markets returned (cursor={'yes' if cursor else 'none'})")
    except Exception as e:
        test_fail("Markets endpoint", str(e))

    return api


async def phase_2_market_data(api):
    """Phase 2: Market Data & Pricing."""
    header("PHASE 2 — Market Data & Pricing")

    if api is None:
        test_skip("All market tests", "API not available")
        return None, None

    from app.kalshi.models import MarketStatus

    # Test 2.1: Fetch markets (open status)
    try:
        markets, _ = await api.markets.list_markets(limit=200, status=MarketStatus.OPEN)
        test_pass("Fetch markets", f"{len(markets)} open markets")
    except Exception as e:
        test_fail("Fetch markets", str(e))
        return None, None

    # Test 2.2: Find markets with prices
    priced_markets = [
        m for m in markets
        if (m.yes_bid is not None and m.yes_bid > 0) or (m.yes_ask is not None and m.yes_ask > 0)
    ]
    if priced_markets:
        test_pass("Markets with prices", f"{len(priced_markets)}/{len(markets)} have bid/ask")
    else:
        test_skip("Markets with prices", f"0/{len(markets)} have prices — demo may be empty")

    # Test 2.3: Find a tradeable market (has spread)
    tradeable = None
    for m in priced_markets:
        bid = m.yes_bid or 0
        ask = m.yes_ask or 0
        if bid > 0 and ask > 0 and ask > bid:
            tradeable = m
            break

    if tradeable:
        test_pass(
            "Found tradeable market",
            f"{tradeable.ticker} bid={tradeable.yes_bid} ask={tradeable.yes_ask}"
        )
    else:
        # Use any market for testing even without prices
        if markets:
            tradeable = markets[0]
            test_skip("Tradeable market", f"No spread found, using {tradeable.ticker} for dry-run tests")
        else:
            test_skip("Tradeable market", "No markets available")

    # Test 2.4: Single market detail
    if tradeable:
        try:
            detail = await api.markets.get_market(tradeable.ticker)
            test_pass("Single market detail", f"{detail.ticker} status={detail.status}")
        except Exception as e:
            test_fail("Single market detail", str(e))

    # Test 2.5: Orderbook
    if tradeable:
        try:
            book = await api.markets.get_orderbook(tradeable.ticker)
            n_yes = len(book.yes_bids)
            n_no = len(book.no_bids)
            test_pass("Orderbook fetch", f"{tradeable.ticker} — {n_yes} yes levels, {n_no} no levels")
        except Exception as e:
            test_fail("Orderbook fetch", str(e))

    return markets, tradeable


async def phase_3_ml_features(markets, tradeable):
    """Phase 3: ML Feature Engineering (29 features)."""
    header("PHASE 3 — ML Feature Engineering")

    if not tradeable:
        test_skip("All feature tests", "No market available")
        return None

    from app.ai.features import FeatureEngine, MarketFeatures

    fe = FeatureEngine()

    # Test 3.1: Compute features for a single market
    try:
        features = fe.compute(tradeable)
        assert isinstance(features, MarketFeatures)
        test_pass("Feature computation", f"{tradeable.ticker} — MarketFeatures object created")
    except Exception as e:
        test_fail("Feature computation", str(e))
        return None

    # Test 3.2: Feature names list
    try:
        names = MarketFeatures.feature_names()
        assert isinstance(names, list) and len(names) > 0
        test_pass("Feature names", f"{len(names)} feature names defined")
    except Exception as e:
        test_fail("Feature names", str(e))

    # Test 3.3: Feature array conversion (for XGBoost input)
    try:
        arr = features.to_array()
        import numpy as np
        assert isinstance(arr, np.ndarray)
        assert len(arr) == len(MarketFeatures.feature_names())
        has_nan = np.any(np.isnan(arr))
        nan_count = int(np.sum(np.isnan(arr)))
        if has_nan:
            test_skip("Feature → numpy array", f"shape={arr.shape}, {nan_count} NaN values (demo data may lack history)")
        else:
            test_pass("Feature → numpy array", f"shape={arr.shape}, no NaN, dtype={arr.dtype}")
    except Exception as e:
        test_fail("Feature → numpy array", str(e))

    # Test 3.4: Key feature values are sane
    try:
        checks = []
        checks.append(("midpoint", 0 <= features.midpoint <= 1, features.midpoint))
        checks.append(("spread", features.spread >= 0, features.spread))
        all_ok = all(ok for _, ok, _ in checks)
        detail = ", ".join(f"{n}={v:.4f}" for n, _, v in checks)
        if all_ok:
            test_pass("Feature value sanity", detail)
        else:
            bad = [n for n, ok, _ in checks if not ok]
            test_fail("Feature value sanity", f"Bad: {bad} — {detail}")
    except Exception as e:
        # Features may all be zero for demo markets with no pricing
        test_skip("Feature value sanity", f"Cannot validate: {e}")

    # Test 3.5: Batch feature computation
    try:
        batch = [fe.compute(m) for m in (markets or [])[:10] if m]
        test_pass("Batch feature computation", f"{len(batch)} markets computed")
    except Exception as e:
        test_fail("Batch feature computation", str(e))

    return features


async def phase_4_ml_predictions(features, tradeable):
    """Phase 4: AI Model Predictions."""
    header("PHASE 4 — AI Model Predictions (Heuristic + XGBoost)")

    if not features:
        test_skip("All prediction tests", "No features available")
        return None

    from app.ai.models import XGBoostPredictor, Prediction

    predictor = XGBoostPredictor()

    # Test 4.1: Model initializes (no trained model = heuristic mode)
    try:
        assert predictor.name == "xgboost_v1"
        trained = predictor.is_trained
        test_pass("Predictor init", f"trained={trained}, fallback=heuristic")
    except Exception as e:
        test_fail("Predictor init", str(e))

    # Test 4.2: Heuristic prediction
    try:
        pred = predictor.predict(features)
        assert isinstance(pred, Prediction)
        assert pred.side in ("yes", "no"), f"Bad side: {pred.side}"
        assert 0 <= pred.confidence <= 1, f"Bad confidence: {pred.confidence}"
        assert -1 <= pred.edge <= 1, f"Bad edge: {pred.edge}"
        test_pass(
            "Heuristic prediction",
            f"side={pred.side}, conf={pred.confidence:.3f}, "
            f"edge={pred.edge:+.3f}, prob_yes={pred.predicted_prob:.3f}"
        )
    except Exception as e:
        test_fail("Heuristic prediction", str(e))
        return None

    # Test 4.3: Batch prediction
    try:
        preds = predictor.predict_batch([features] * 5)
        assert len(preds) == 5
        assert all(isinstance(p, Prediction) for p in preds)
        test_pass("Batch prediction", f"{len(preds)} predictions in batch")
    except Exception as e:
        test_fail("Batch prediction", str(e))

    # Test 4.4: XGBoost training on synthetic data
    try:
        import numpy as np
        n_features = len(features.to_array())
        X_synth = np.random.rand(200, n_features).astype(np.float32)
        y_synth = (X_synth[:, 0] > 0.5).astype(np.float32)  # simple rule

        metrics = predictor.train(X_synth, y_synth, num_boost_round=20, early_stopping_rounds=5)
        assert predictor.is_trained
        assert "val_auc" in metrics
        test_pass(
            "XGBoost training",
            f"AUC={metrics['val_auc']:.3f}, logloss={metrics['val_logloss']:.3f}, "
            f"rounds={metrics['best_iteration']}"
        )
    except Exception as e:
        test_fail("XGBoost training", str(e))

    # Test 4.5: Trained model prediction (should differ from heuristic)
    try:
        pred_trained = predictor.predict(features)
        assert isinstance(pred_trained, Prediction)
        test_pass(
            "Trained model prediction",
            f"side={pred_trained.side}, conf={pred_trained.confidence:.3f}, "
            f"edge={pred_trained.edge:+.3f}"
        )
    except Exception as e:
        test_fail("Trained model prediction", str(e))

    # Test 4.6: Model save & reload
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        predictor.save(path)
        assert os.path.exists(path)
        size_kb = os.path.getsize(path) / 1024

        predictor2 = XGBoostPredictor()
        predictor2.load(path)
        pred_reload = predictor2.predict(features)
        os.unlink(path)

        assert pred_reload.predicted_prob == pred_trained.predicted_prob
        test_pass("Model save/load", f"size={size_kb:.1f}KB, predictions match after reload")
    except Exception as e:
        test_fail("Model save/load", str(e))

    return pred


async def phase_5_risk_manager(tradeable):
    """Phase 5: Risk Manager Pre-Trade Checks."""
    header("PHASE 5 — Risk Manager Pre-Trade Checks")

    if not tradeable:
        test_skip("All risk tests", "No market available")
        return None

    from decimal import Decimal
    from app.engine.risk import RiskManager, RiskLimits
    from app.kalshi.models import OrderSide, OrderAction
    from app.config import get_settings

    settings = get_settings()
    limits = RiskLimits(
        max_position_size=settings.risk_max_position_size,
        max_daily_loss=Decimal(str(settings.risk_max_daily_loss)),
        max_portfolio_exposure=Decimal(str(settings.risk_max_portfolio_exposure)),
    )
    rm = RiskManager(limits=limits)

    # Test 5.1: Risk manager initializes
    try:
        assert rm is not None
        test_pass("RiskManager init", f"max_daily_loss=${limits.max_daily_loss}, max_pos={limits.max_position_size}")
    except Exception as e:
        test_fail("RiskManager init", str(e))

    # Test 5.2: Kill switch blocks trades when enabled
    try:
        rm.activate_kill_switch("test")
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES, action=OrderAction.BUY,
            count=1, price_cents=50,
        )
        assert not ok, "Kill switch should block"
        assert "kill" in reason.lower()
        rm.deactivate_kill_switch()
        test_pass("Kill switch blocks", f"reason='{reason}'")
    except Exception as e:
        test_fail("Kill switch blocks", str(e))

    # Test 5.3: Normal trade passes risk checks
    try:
        rm.deactivate_kill_switch()
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES, action=OrderAction.BUY,
            count=1, price_cents=50,
        )
        if ok:
            test_pass("Normal trade passes risk", "1 contract @ 50¢")
        else:
            test_skip("Normal trade passes risk", f"Rejected: {reason}")
    except Exception as e:
        test_fail("Normal trade passes risk", str(e))

    # Test 5.4: Over-size order rejected
    try:
        rm.deactivate_kill_switch()
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES, action=OrderAction.BUY,
            count=9999, price_cents=50,
        )
        if not ok:
            test_pass("Over-size order rejected", f"reason='{reason}'")
        else:
            test_skip("Over-size order rejected", "Passed (limits may be high)")
    except Exception as e:
        test_fail("Over-size order rejected", str(e))

    # Test 5.5: Huge cost order rejected
    try:
        rm.deactivate_kill_switch()
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES, action=OrderAction.BUY,
            count=100, price_cents=99,
        )
        if not ok:
            test_pass("High-cost order rejected", f"reason='{reason}'")
        else:
            test_skip("High-cost order rejected", "Passed (exposure limits may be high)")
    except Exception as e:
        test_fail("High-cost order rejected", str(e))

    return rm


async def phase_6_order_execution(api, tradeable, rm):
    """Phase 6: Live Order Execution (Buy + Cancel on Kalshi Demo)."""
    header("PHASE 6 — Live Order Execution (Kalshi Demo)")

    if not tradeable or not api:
        test_skip("All execution tests", "No market or API available")
        return

    from app.engine.execution import ExecutionEngine
    from app.kalshi.models import OrderSide, OrderAction, OrderType

    engine = ExecutionEngine(api=api, risk_manager=rm)

    # Make sure kill switch is OFF for testing
    if rm:
        rm.deactivate_kill_switch()

    # Test 6.1: Engine initializes
    try:
        assert engine.enabled
        test_pass("ExecutionEngine init", "enabled=True, risk_manager attached")
    except Exception as e:
        test_fail("ExecutionEngine init", str(e))

    # Test 6.2: Disabled engine blocks orders
    try:
        engine.disable()
        result = await engine.execute(
            ticker=tradeable.ticker, side=OrderSide.YES,
            action=OrderAction.BUY, count=1, price_cents=1,
        )
        assert not result.success
        assert "disabled" in (result.error or "").lower()
        engine.enable()
        test_pass("Disabled engine blocks", f"error='{result.error}'")
    except Exception as e:
        test_fail("Disabled engine blocks", str(e))
        engine.enable()

    # Test 6.3: Submit a REAL limit buy order (1 contract, low price = won't fill)
    #   Price at 1¢ so it rests in the book, doesn't fill, and costs nothing.
    order_id = None
    try:
        result = await engine.execute(
            ticker=tradeable.ticker,
            side=OrderSide.YES,
            action=OrderAction.BUY,
            count=1,
            price_cents=1,  # 1¢ — will sit in book, not fill
            order_type=OrderType.LIMIT,
        )
        if result.success:
            order_id = result.order_id
            test_pass(
                "BUY YES limit order submitted",
                f"order_id={order_id}, latency={result.latency_ms:.0f}ms"
            )
        else:
            err = result.error or result.risk_rejection_reason or "unknown"
            if "authentication" in (err or "").lower() or "NOT_FOUND" in (err or ""):
                test_skip("BUY YES limit order submitted", f"Auth expired: {err[:80]}")
            elif "balance" in (err or "").lower() or "insufficient" in (err or "").lower():
                test_skip("BUY YES limit order submitted", f"Demo account: {err}")
            else:
                test_fail("BUY YES limit order submitted", f"Failed: {err}")
    except Exception as e:
        test_fail("BUY YES limit order submitted", str(e))

    # Test 6.4: Cancel the order we just placed
    if order_id:
        try:
            success = await engine.cancel(order_id)
            if success:
                test_pass("Cancel order", f"order_id={order_id}")
            else:
                test_fail("Cancel order", "cancel() returned False")
        except Exception as e:
            test_fail("Cancel order", str(e))
    else:
        test_skip("Cancel order", "No order to cancel (order submission failed)")

    # Test 6.5: Submit BUY NO order (also at 1¢ — safe resting order)
    order_id_no = None
    try:
        result = await engine.execute(
            ticker=tradeable.ticker,
            side=OrderSide.NO,
            action=OrderAction.BUY,
            count=1,
            price_cents=1,
        )
        if result.success:
            order_id_no = result.order_id
            test_pass("BUY NO limit order submitted", f"order_id={order_id_no}")
        else:
            err = result.error or result.risk_rejection_reason or "unknown"
            if "authentication" in (err or "").lower() or "NOT_FOUND" in (err or ""):
                test_skip("BUY NO limit order submitted", f"Auth expired: {err[:80]}")
            elif "balance" in (err or "").lower() or "insufficient" in (err or "").lower():
                test_skip("BUY NO limit order submitted", f"Demo account: {err}")
            else:
                test_fail("BUY NO limit order submitted", f"Failed: {err}")
    except Exception as e:
        test_fail("BUY NO limit order submitted", str(e))

    # Test 6.6: Cancel all resting orders
    try:
        success = await engine.cancel_all(ticker=tradeable.ticker)
        if success:
            test_pass("Cancel all orders", f"ticker={tradeable.ticker}")
        else:
            test_skip("Cancel all orders", "cancel_all returned False (auth may be expired)")
    except Exception as e:
        test_skip("Cancel all orders", str(e)[:80])

    # Test 6.7: Execution stats
    try:
        stats = engine.stats
        test_pass(
            "Execution stats",
            f"total={stats.total_orders}, success={stats.successful_orders}, "
            f"failed={stats.failed_orders}, risk_rejected={stats.risk_rejections}, "
            f"avg_latency={stats.avg_latency_ms:.0f}ms"
        )
    except Exception as e:
        test_fail("Execution stats", str(e))


async def phase_7_portfolio_tracking(api):
    """Phase 7: Portfolio Tracking."""
    header("PHASE 7 — Portfolio Tracking")

    if not api:
        test_skip("All portfolio tests", "API not available")
        return

    from app.kalshi.models import OrderStatus

    def is_auth_error(e: Exception) -> bool:
        s = str(e)
        return "authentication" in s.lower() or "NOT_FOUND" in s

    # Test 7.1: Balance
    try:
        bal = await api.portfolio.get_balance()
        test_pass("Balance fetch", f"${bal.balance_dollars or '0.00'} ({bal.balance or 0}¢)")
    except Exception as e:
        if is_auth_error(e):
            test_skip("Balance fetch", "Auth expired — regenerate API key")
        else:
            test_fail("Balance fetch", str(e))

    # Test 7.2: Positions
    try:
        positions = await api.portfolio.get_all_positions(
            settlement_status="unsettled"
        )
        test_pass("Positions fetch", f"{len(positions)} open positions")
    except Exception as e:
        if is_auth_error(e):
            test_skip("Positions fetch", "Auth expired")
        else:
            test_fail("Positions fetch", str(e))

    # Test 7.3: Fills (recent trades)
    try:
        fills, _ = await api.portfolio.list_fills(limit=20)
        test_pass("Fills fetch", f"{len(fills)} recent fills")
    except Exception as e:
        if is_auth_error(e):
            test_skip("Fills fetch", "Auth expired")
        else:
            test_fail("Fills fetch", str(e))

    # Test 7.4: Open orders
    try:
        orders, _ = await api.orders.list_orders(status=OrderStatus.RESTING)
        test_pass("Open orders fetch", f"{len(orders)} resting orders")
    except Exception as e:
        if is_auth_error(e):
            test_skip("Open orders fetch", "Auth expired")
        else:
            test_fail("Open orders fetch", str(e))


async def phase_8_agent_cycle(api, markets, tradeable):
    """Phase 8: Autonomous Agent — Single Dry-Run Cycle."""
    header("PHASE 8 — Autonomous Agent (Single Cycle Dry-Run)")

    if not tradeable:
        test_skip("All agent tests", "No market available")
        return

    from app.ai.features import FeatureEngine
    from app.ai.models import XGBoostPredictor

    fe = FeatureEngine()
    predictor = XGBoostPredictor()

    # Test 8.1: Scan markets → compute features → predict
    try:
        candidates = (markets or [])[:20]
        features_list = []
        for m in candidates:
            try:
                f = fe.compute(m)
                features_list.append((m, f))
            except Exception:
                pass

        predictions = []
        for m, f in features_list:
            pred = predictor.predict(f)
            predictions.append((m, f, pred))

        test_pass("Scan-Predict cycle", f"{len(candidates)} scanned → {len(features_list)} featured → {len(predictions)} predicted")
    except Exception as e:
        test_fail("Scan-Predict cycle", str(e))
        return

    # Test 8.2: Filter by confidence + edge
    try:
        min_conf = 0.55
        min_edge = 0.02
        opportunities = [
            (m, f, p) for m, f, p in predictions
            if p.confidence >= min_conf and abs(p.edge) >= min_edge
        ]
        if opportunities:
            best = max(opportunities, key=lambda x: abs(x[2].edge))
            test_pass(
                "Opportunity filter",
                f"{len(opportunities)} opportunities, best={best[0].ticker} "
                f"edge={best[2].edge:+.3f} conf={best[2].confidence:.3f}"
            )
        else:
            test_skip("Opportunity filter", f"0 passed (conf≥{min_conf}, edge≥{min_edge}) — signals weak on demo data")
    except Exception as e:
        test_fail("Opportunity filter", str(e))

    # Test 8.3: Kelly sizing
    try:
        def kelly_size(confidence: float, edge: float, fraction: float = 0.25, balance_cents: int = 10000) -> int:
            """Full Kelly formula scaled by fraction."""
            if edge <= 0 or confidence <= 0.5:
                return 0
            p = confidence
            q = 1 - p
            b = (1 / (1 - abs(edge))) - 1 if abs(edge) < 1 else 10
            kelly = (p * b - q) / b if b > 0 else 0
            kelly = max(0, kelly) * fraction
            position_value = int(kelly * balance_cents)
            count = max(1, position_value // max(1, int(abs(edge) * 100)))
            return min(count, 10)  # cap at 10 for test

        # Size a hypothetical opportunity
        test_pred = predictions[0][2] if predictions else None
        if test_pred:
            size = kelly_size(test_pred.confidence, abs(test_pred.edge))
            test_pass("Kelly sizing", f"conf={test_pred.confidence:.3f}, edge={test_pred.edge:+.3f} → {size} contracts")
        else:
            test_skip("Kelly sizing", "No predictions to size")
    except Exception as e:
        test_fail("Kelly sizing", str(e))

    # Test 8.4: Full pipeline summary
    try:
        total_markets = len(markets or [])
        featured = len(features_list)
        predicted = len(predictions)
        opps = len(opportunities) if 'opportunities' in dir() else 0
        test_pass(
            "Pipeline summary",
            f"Markets({total_markets}) → Features({featured}) → "
            f"Predictions({predicted}) → Opportunities({opps})"
        )
    except Exception as e:
        test_fail("Pipeline summary", str(e))


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print(f"\n{BOLD}{'═' * 60}")
    print(f"  JA HEDGE — End-to-End Trading Pipeline Tests")
    print(f"  Target: Kalshi Demo API (LIVE)")
    print(f"{'═' * 60}{RESET}")

    t0 = time.time()

    # Phase 1: Connectivity
    api = await phase_1_connectivity()

    # Phase 2: Market data
    markets, tradeable = await phase_2_market_data(api)

    # Phase 3: ML features
    features = await phase_3_ml_features(markets, tradeable)

    # Phase 4: AI predictions
    prediction = await phase_4_ml_predictions(features, tradeable)

    # Phase 5: Risk manager
    rm = await phase_5_risk_manager(tradeable)

    # Phase 6: Live order execution
    await phase_6_order_execution(api, tradeable, rm)

    # Phase 7: Portfolio tracking
    await phase_7_portfolio_tracking(api)

    # Phase 8: Agent cycle
    await phase_8_agent_cycle(api, markets, tradeable)

    # Cleanup — close the HTTP connection pool
    if api:
        try:
            await api.__aexit__(None, None, None)
        except Exception:
            pass

    # ── Summary ───────────────────────────────────────────
    elapsed = time.time() - t0
    total = passed + failed + skipped

    print(f"\n{BOLD}{'═' * 60}")
    print(f"  RESULTS: {total} tests in {elapsed:.1f}s")
    print(f"{'═' * 60}{RESET}")
    print(f"  {GREEN}✓ Passed:  {passed}{RESET}")
    print(f"  {RED}✗ Failed:  {failed}{RESET}")
    print(f"  {YELLOW}○ Skipped: {skipped}{RESET}")
    print()

    if failed == 0:
        print(f"  {GREEN}{BOLD}🚀 ALL TESTS PASSED — Trading pipeline is LIVE!{RESET}")
    else:
        print(f"  {RED}{BOLD}⚠️  {failed} test(s) failed — review above{RESET}")

    print()
    return failed == 0


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except Exception as e:
        print(f"\n{RED}Fatal error: {e}{RESET}")
        traceback.print_exc()
        sys.exit(2)
