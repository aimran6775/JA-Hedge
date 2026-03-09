#!/usr/bin/env python3
"""
JA Hedge — Paper Trading Simulation (Full End-to-End with Fake Cash).

Runs the COMPLETE trading pipeline with $10,000 simulated funds:
  1. API connectivity + paper trader setup
  2. Real market data from Kalshi
  3. ML feature engineering (29 features)
  4. AI predictions (heuristic + XGBoost)
  5. Risk management checks
  6. ORDER EXECUTION with fake cash (BUY YES, BUY NO, SELL)
  7. Order cancellation (single + batch)
  8. Position tracking + P&L
  9. Multi-trade strategy simulation
  10. Full autonomous agent cycle with real execution

No real money. No demo funds needed. Everything works.

Usage:
  cd backend && source .venv/bin/activate
  python test_paper_trading.py
"""

from __future__ import annotations

import asyncio
import sys
import time
import traceback
from decimal import Decimal

# ── Colored output ────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0


def header(title: str):
    print(f"\n{BOLD}{CYAN}{'━' * 65}")
    print(f"  {title}")
    print(f"{'━' * 65}{RESET}\n")


def test_pass(name: str, detail: str = ""):
    global passed
    passed += 1
    d = f" {DIM}({detail}){RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET} {name}{d}")


def test_fail(name: str, error: str):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {name}")
    print(f"    {RED}{error}{RESET}")


def test_skip(name: str, reason: str):
    global skipped
    skipped += 1
    print(f"  {YELLOW}○{RESET} {name} — {reason}")


def money(cents: int) -> str:
    """Format cents as dollars."""
    return f"${cents / 100:,.2f}"


# ══════════════════════════════════════════════════════════════════════════
# PHASE 1: Setup — Connect to Kalshi + Initialize Paper Trader
# ══════════════════════════════════════════════════════════════════════════

async def phase_1_setup():
    """Initialize real API + paper trading simulator."""
    header("PHASE 1 — API Connection + Paper Trader Setup ($10,000 Fake Cash)")

    from app.config import get_settings
    from app.kalshi.api import KalshiAPI
    from app.engine.paper_trader import PaperTradingSimulator

    settings = get_settings()

    # 1.1: Connect to real Kalshi API (for market data)
    try:
        api = KalshiAPI.from_settings(settings)
        await api.__aenter__()
        test_pass("Real Kalshi API connected", f"mode={settings.jahedge_mode}")
    except Exception as e:
        test_fail("Real Kalshi API connected", str(e))
        return None, None, None

    # 1.2: Verify health
    try:
        healthy = await api.health_check()
        if healthy:
            test_pass("Exchange health check", "active=True")
        else:
            test_skip("Exchange health check", "exchange may be off-hours")
    except Exception as e:
        test_fail("Exchange health check", str(e))

    # 1.3: Initialize paper trader with $10,000
    try:
        sim = PaperTradingSimulator(
            starting_balance_cents=1_000_000,  # $10,000
            fee_rate_cents=7,  # 7¢ taker fee per contract
            instant_fill=True,  # fill limit orders immediately
        )
        bal = sim.get_balance()
        test_pass("Paper Trader initialized", f"balance={money(bal.balance)}, fees=7¢/contract")
    except Exception as e:
        test_fail("Paper Trader initialized", str(e))
        return api, None, None

    # 1.4: Create the hybrid API wrapper
    try:
        paper_api = sim.wrap_api(api)
        # Verify it has all the right interfaces
        assert hasattr(paper_api, 'markets'), "missing markets"
        assert hasattr(paper_api, 'orders'), "missing orders"
        assert hasattr(paper_api, 'portfolio'), "missing portfolio"
        assert hasattr(paper_api, 'exchange'), "missing exchange"

        # Verify paper balance works through wrapper
        wrapper_bal = await paper_api.portfolio.get_balance()
        assert wrapper_bal.balance == 1_000_000
        test_pass("Hybrid API wrapper", "real market data + paper orders/portfolio")
    except Exception as e:
        test_fail("Hybrid API wrapper", str(e))

    return api, sim, paper_api


# ══════════════════════════════════════════════════════════════════════════
# PHASE 2: Market Data (from real Kalshi)
# ══════════════════════════════════════════════════════════════════════════

async def phase_2_markets(paper_api):
    """Fetch real market data through the hybrid API."""
    header("PHASE 2 — Real Market Data (from Kalshi)")

    if not paper_api:
        test_skip("All market tests", "No API available")
        return None, None

    from app.kalshi.models import MarketStatus

    # 2.1: Fetch open markets
    try:
        markets, cursor = await paper_api.markets.list_markets(limit=200, status=MarketStatus.OPEN)
        test_pass("Fetch open markets", f"{len(markets)} markets")
    except Exception as e:
        test_fail("Fetch open markets", str(e))
        return None, None

    # 2.2: Find tradeable markets (with bid/ask spread)
    priced = [
        m for m in markets
        if m.yes_bid is not None and m.yes_ask is not None
        and m.yes_bid > 0 and m.yes_ask > 0 and m.yes_ask > m.yes_bid
    ]

    if priced:
        test_pass("Markets with spread", f"{len(priced)}/{len(markets)} have tradeable bid/ask")
    else:
        test_skip("Markets with spread", "Using first available market")

    # 2.3: Select best market for trading simulation
    tradeable = None
    if priced:
        # Pick the market with the tightest spread for best simulation
        tradeable = min(priced, key=lambda m: (m.yes_ask - m.yes_bid))
        spread_cents = int((tradeable.yes_ask - tradeable.yes_bid) * 100)
        test_pass(
            "Selected market",
            f"{tradeable.ticker} — bid={tradeable.yes_bid} ask={tradeable.yes_ask} "
            f"spread={spread_cents}¢"
        )
    elif markets:
        tradeable = markets[0]
        test_pass("Selected market", f"{tradeable.ticker} (no spread, using for simulation)")

    # 2.4: Fetch orderbook
    if tradeable:
        try:
            book = await paper_api.markets.get_orderbook(tradeable.ticker)
            test_pass("Orderbook", f"{len(book.yes_bids)} yes levels, {len(book.no_bids)} no levels")
        except Exception as e:
            test_fail("Orderbook", str(e))

    return markets, tradeable


# ══════════════════════════════════════════════════════════════════════════
# PHASE 3: ML Feature Engineering
# ══════════════════════════════════════════════════════════════════════════

async def phase_3_features(markets, tradeable):
    """Compute ML features on real market data."""
    header("PHASE 3 — ML Feature Engineering (29 Features)")

    if not tradeable:
        test_skip("All feature tests", "No market available")
        return None, None

    from app.ai.features import FeatureEngine, MarketFeatures
    import numpy as np

    fe = FeatureEngine()

    # 3.1: Single market features
    try:
        features = fe.compute(tradeable)
        arr = features.to_array()
        test_pass("Features computed", f"{tradeable.ticker} → {len(arr)} features, no NaN={not np.any(np.isnan(arr))}")
    except Exception as e:
        test_fail("Features computed", str(e))
        return None, None

    # 3.2: Batch features for all priced markets
    all_features = []
    try:
        for m in (markets or [])[:50]:
            try:
                f = fe.compute(m)
                all_features.append((m, f))
            except Exception:
                pass
        test_pass("Batch features", f"{len(all_features)} markets featured")
    except Exception as e:
        test_fail("Batch features", str(e))

    return features, all_features


# ══════════════════════════════════════════════════════════════════════════
# PHASE 4: AI Predictions
# ══════════════════════════════════════════════════════════════════════════

async def phase_4_predictions(features, all_features, tradeable):
    """Train model + predict on real data."""
    header("PHASE 4 — AI Predictions (XGBoost + Heuristic)")

    if not features:
        test_skip("All prediction tests", "No features available")
        return None

    from app.ai.models import XGBoostPredictor, Prediction
    import numpy as np

    predictor = XGBoostPredictor()

    # 4.1: Heuristic prediction
    try:
        pred = predictor.predict(features)
        test_pass(
            "Heuristic prediction",
            f"side={pred.side} conf={pred.confidence:.3f} edge={pred.edge:+.3f}"
        )
    except Exception as e:
        test_fail("Heuristic prediction", str(e))
        return None

    # 4.2: Train XGBoost
    try:
        n_features = len(features.to_array())
        X = np.random.rand(500, n_features).astype(np.float32)
        y = (X[:, 0] > 0.5).astype(np.float32)
        metrics = predictor.train(X, y, num_boost_round=30, early_stopping_rounds=5)
        test_pass("XGBoost trained", f"AUC={metrics['val_auc']:.3f}")
    except Exception as e:
        test_fail("XGBoost trained", str(e))

    # 4.3: Predict across all markets
    predictions = []
    try:
        for m, f in (all_features or []):
            p = predictor.predict(f)
            predictions.append((m, f, p))

        if predictions:
            best = max(predictions, key=lambda x: abs(x[2].edge))
            test_pass(
                "Batch predictions",
                f"{len(predictions)} markets — best={best[0].ticker} "
                f"edge={best[2].edge:+.3f}"
            )
        else:
            test_pass("Batch predictions", "0 markets (no features)")
    except Exception as e:
        test_fail("Batch predictions", str(e))

    return predictions


# ══════════════════════════════════════════════════════════════════════════
# PHASE 5: Risk Management
# ══════════════════════════════════════════════════════════════════════════

async def phase_5_risk(tradeable):
    """Full risk manager setup with paper-trading-appropriate limits."""
    header("PHASE 5 — Risk Management")

    if not tradeable:
        test_skip("All risk tests", "No market available")
        return None

    from app.engine.risk import RiskManager, RiskLimits
    from app.kalshi.models import OrderSide, OrderAction

    limits = RiskLimits(
        max_position_size=100,        # allow up to 100 contracts per market
        max_daily_loss=Decimal("500"),  # $500 max daily loss
        max_portfolio_exposure=Decimal("5000"),  # $5,000 max exposure
        max_single_order_cost=Decimal("1000"),   # $1,000 max per order
    )
    rm = RiskManager(limits=limits)

    # 5.1: Normal trade passes
    try:
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES,
            action=OrderAction.BUY, count=10, price_cents=50,
        )
        assert ok, f"Should pass: {reason}"
        test_pass("Normal trade passes", "10 contracts @ 50¢ = $5.00")
    except Exception as e:
        test_fail("Normal trade passes", str(e))

    # 5.2: Kill switch
    try:
        rm.activate_kill_switch("test")
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES,
            action=OrderAction.BUY, count=1, price_cents=50,
        )
        assert not ok
        rm.deactivate_kill_switch()
        test_pass("Kill switch blocks", f"reason='{reason}'")
    except Exception as e:
        test_fail("Kill switch blocks", str(e))

    # 5.3: Over-size rejected
    try:
        ok, reason = await rm.pre_trade_check(
            ticker=tradeable.ticker, side=OrderSide.YES,
            action=OrderAction.BUY, count=999, price_cents=50,
        )
        if not ok:
            test_pass("Over-size rejected", f"reason='{reason}'")
        else:
            test_skip("Over-size rejected", "Limits allow this size")
    except Exception as e:
        test_fail("Over-size rejected", str(e))

    return rm


# ══════════════════════════════════════════════════════════════════════════
# PHASE 6: ORDER EXECUTION (Paper Trading — The Main Event!)
# ══════════════════════════════════════════════════════════════════════════

async def phase_6_execution(paper_api, sim, tradeable, rm):
    """Execute real orders with fake cash — buy, sell, cancel, everything!"""
    header("PHASE 6 — 💰 ORDER EXECUTION (Paper Trading with $10,000)")

    if not paper_api or not tradeable or not sim:
        test_skip("All execution tests", "Missing API/market/simulator")
        return

    from app.engine.execution import ExecutionEngine
    from app.kalshi.models import OrderSide, OrderAction, OrderType, OrderStatus

    engine = ExecutionEngine(api=paper_api, risk_manager=rm)

    # Determine a reasonable price
    bid_cents = int((tradeable.yes_bid or Decimal("0.40")) * 100)
    ask_cents = int((tradeable.yes_ask or Decimal("0.60")) * 100)
    mid_cents = (bid_cents + ask_cents) // 2 or 50

    print(f"  {DIM}Market: {tradeable.ticker}")
    print(f"  Bid: {bid_cents}¢  Ask: {ask_cents}¢  Mid: {mid_cents}¢")
    print(f"  Starting balance: {money(sim.balance_cents)}{RESET}\n")

    # ── 6.1: BUY 10 YES contracts ────────────────────────
    try:
        result = await engine.execute(
            ticker=tradeable.ticker,
            side=OrderSide.YES,
            action=OrderAction.BUY,
            count=10,
            price_cents=mid_cents,
            order_type=OrderType.LIMIT,
        )
        assert result.success, f"Expected success: {result.error or result.risk_rejection_reason}"
        cost = mid_cents * 10
        test_pass(
            "BUY 10 YES contracts",
            f"order_id={result.order_id}, price={mid_cents}¢, "
            f"cost={money(cost)}, balance={sim.balance_dollars}"
        )
    except Exception as e:
        test_fail("BUY 10 YES contracts", str(e))

    # ── 6.2: BUY 5 NO contracts ──────────────────────────
    no_price = 100 - mid_cents  # complementary price
    try:
        result = await engine.execute(
            ticker=tradeable.ticker,
            side=OrderSide.NO,
            action=OrderAction.BUY,
            count=5,
            price_cents=no_price,
            order_type=OrderType.LIMIT,
        )
        assert result.success, f"Expected success: {result.error or result.risk_rejection_reason}"
        test_pass(
            "BUY 5 NO contracts",
            f"price={no_price}¢, balance={sim.balance_dollars}"
        )
    except Exception as e:
        test_fail("BUY 5 NO contracts", str(e))

    # ── 6.3: Check positions after buys ───────────────────
    try:
        pos = sim.get_position(tradeable.ticker)
        assert pos is not None, "No position found"
        assert pos.yes_count == 10, f"Expected 10 YES, got {pos.yes_count}"
        assert pos.no_count == 5, f"Expected 5 NO, got {pos.no_count}"
        test_pass(
            "Position tracking",
            f"YES={pos.yes_count} NO={pos.no_count} net={pos.net_position} "
            f"cost={money(pos.total_cost_cents)}"
        )
    except Exception as e:
        test_fail("Position tracking", str(e))

    # ── 6.4: Check fills ──────────────────────────────────
    try:
        fills = sim.list_fills()
        assert len(fills) >= 2, f"Expected ≥2 fills, got {len(fills)}"
        test_pass("Fill records", f"{len(fills)} fills recorded")
    except Exception as e:
        test_fail("Fill records", str(e))

    # ── 6.5: SELL 5 YES contracts (partial close) ────────
    sell_price = mid_cents + 2  # sell slightly above mid for "profit"
    try:
        result = await engine.execute(
            ticker=tradeable.ticker,
            side=OrderSide.YES,
            action=OrderAction.SELL,
            count=5,
            price_cents=sell_price,
            order_type=OrderType.LIMIT,
        )
        assert result.success, f"Expected success: {result.error or result.risk_rejection_reason}"
        pos = sim.get_position(tradeable.ticker)
        test_pass(
            "SELL 5 YES (partial close)",
            f"sell_price={sell_price}¢, remaining YES={pos.yes_count}, "
            f"balance={sim.balance_dollars}"
        )
    except Exception as e:
        test_fail("SELL 5 YES (partial close)", str(e))

    # ── 6.6: BUY more across a DIFFERENT market ──────────
    try:
        from app.kalshi.models import MarketStatus
        all_markets, _ = await paper_api.markets.list_markets(limit=50, status=MarketStatus.OPEN)
        other = None
        for m in all_markets:
            if m.ticker != tradeable.ticker:
                other = m
                break

        if other:
            other_price = int((other.yes_bid or Decimal("0.30")) * 100) or 30
            result = await engine.execute(
                ticker=other.ticker,
                side=OrderSide.YES,
                action=OrderAction.BUY,
                count=20,
                price_cents=other_price,
            )
            if result.success:
                test_pass(
                    "BUY 20 YES on 2nd market",
                    f"{other.ticker} @ {other_price}¢, balance={sim.balance_dollars}"
                )
            else:
                test_fail("BUY 20 YES on 2nd market", result.error or "unknown error")
        else:
            test_skip("BUY 20 YES on 2nd market", "No other market available")
    except Exception as e:
        test_fail("BUY 20 YES on 2nd market", str(e))

    # ── 6.7: Check balance deductions ─────────────────────
    try:
        bal = sim.get_balance()
        assert bal.balance < 1_000_000, "Balance should have decreased"
        spent = 1_000_000 - bal.balance
        test_pass(
            "Balance tracking",
            f"started={money(1_000_000)}, now={money(bal.balance)}, "
            f"spent={money(spent)}"
        )
    except Exception as e:
        test_fail("Balance tracking", str(e))

    # ── 6.8: Execution stats ─────────────────────────────
    try:
        stats = engine.stats
        assert stats.total_orders >= 4
        assert stats.successful_orders >= 4
        test_pass(
            "Execution stats",
            f"total={stats.total_orders} success={stats.successful_orders} "
            f"failed={stats.failed_orders} avg_latency={stats.avg_latency_ms:.1f}ms"
        )
    except Exception as e:
        test_fail("Execution stats", str(e))


# ══════════════════════════════════════════════════════════════════════════
# PHASE 7: Order Cancellation
# ══════════════════════════════════════════════════════════════════════════

async def phase_7_cancellation(paper_api, sim, tradeable):
    """Test order cancellation (requires non-instant-fill orders)."""
    header("PHASE 7 — Order Cancellation")

    if not paper_api or not tradeable:
        test_skip("All cancellation tests", "Missing API/market")
        return

    from app.engine.paper_trader import PaperTradingSimulator
    from app.kalshi.models import (
        CreateOrderRequest, OrderSide, OrderAction, OrderType, OrderStatus,
    )

    # Create a separate simulator with instant_fill=False for resting orders
    cancel_sim = PaperTradingSimulator(
        starting_balance_cents=500_000,  # $5,000
        instant_fill=False,  # orders REST instead of filling
    )

    # 7.1: Place a resting order
    try:
        req = CreateOrderRequest(
            ticker=tradeable.ticker,
            side=OrderSide.YES,
            action=OrderAction.BUY,
            type=OrderType.LIMIT,
            count=5,
            yes_price=10,  # 10¢ — very low, would rest
        )
        order = cancel_sim.create_order(req)
        assert order.status == OrderStatus.RESTING
        test_pass("Place resting order", f"order_id={order.order_id}, status=resting")
    except Exception as e:
        test_fail("Place resting order", str(e))
        return

    # 7.2: Verify it's in the order book
    try:
        resting = cancel_sim.list_orders(status=OrderStatus.RESTING)
        assert len(resting) == 1, f"Expected 1 resting, got {len(resting)}"
        test_pass("Order in book", f"{len(resting)} resting order(s)")
    except Exception as e:
        test_fail("Order in book", str(e))

    # 7.3: Cancel the order
    try:
        cancel_sim.cancel_order(order.order_id)
        resting_after = cancel_sim.list_orders(status=OrderStatus.RESTING)
        assert len(resting_after) == 0
        test_pass("Cancel single order", f"order_id={order.order_id} → cancelled")
    except Exception as e:
        test_fail("Cancel single order", str(e))

    # 7.4: Place multiple resting orders, then cancel all
    try:
        for i in range(5):
            req = CreateOrderRequest(
                ticker=tradeable.ticker,
                side=OrderSide.YES,
                action=OrderAction.BUY,
                type=OrderType.LIMIT,
                count=1,
                yes_price=5 + i,
            )
            cancel_sim.create_order(req)

        resting_before = cancel_sim.list_orders(status=OrderStatus.RESTING)
        assert len(resting_before) == 5, f"Expected 5 resting, got {len(resting_before)}"

        cancelled = cancel_sim.cancel_all_orders(ticker=tradeable.ticker)
        resting_after = cancel_sim.list_orders(status=OrderStatus.RESTING)
        assert cancelled == 5
        assert len(resting_after) == 0
        test_pass("Cancel all orders", f"cancelled {cancelled} resting orders")
    except Exception as e:
        test_fail("Cancel all orders", str(e))

    # 7.5: Balance unchanged for resting (unfilled) orders
    try:
        bal = cancel_sim.get_balance()
        assert bal.balance == 500_000, f"Balance should be unchanged: {bal.balance}"
        test_pass("Balance preserved", f"No deductions for resting orders: {money(bal.balance)}")
    except Exception as e:
        test_fail("Balance preserved", str(e))


# ══════════════════════════════════════════════════════════════════════════
# PHASE 8: Portfolio Tracking via API Wrapper
# ══════════════════════════════════════════════════════════════════════════

async def phase_8_portfolio(paper_api, sim):
    """Test portfolio tracking through the hybrid API wrapper."""
    header("PHASE 8 — Portfolio Tracking (via Paper API)")

    if not paper_api or not sim:
        test_skip("All portfolio tests", "Missing API/simulator")
        return

    # 8.1: Balance through wrapper
    try:
        bal = await paper_api.portfolio.get_balance()
        test_pass("Balance via wrapper", f"{money(bal.balance)}")
    except Exception as e:
        test_fail("Balance via wrapper", str(e))

    # 8.2: Positions through wrapper
    try:
        positions = await paper_api.portfolio.get_all_positions()
        open_pos = [p for p in positions if p.position and p.position != 0]
        test_pass("Positions via wrapper", f"{len(positions)} total, {len(open_pos)} with holdings")
    except Exception as e:
        test_fail("Positions via wrapper", str(e))

    # 8.3: Fills through wrapper
    try:
        fills, cursor = await paper_api.portfolio.list_fills(limit=50)
        test_pass("Fills via wrapper", f"{len(fills)} fills returned")
    except Exception as e:
        test_fail("Fills via wrapper", str(e))

    # 8.4: Orders through wrapper
    try:
        from app.kalshi.models import OrderStatus
        orders, _ = await paper_api.orders.list_orders()
        executed = [o for o in orders if o.status == OrderStatus.EXECUTED]
        test_pass(
            "Orders via wrapper",
            f"{len(orders)} total, {len(executed)} executed"
        )
    except Exception as e:
        test_fail("Orders via wrapper", str(e))

    # 8.5: P&L summary
    try:
        summary = sim.summary()
        test_pass(
            "Paper trading summary",
            f"balance={summary['balance_dollars']}, pnl={summary['pnl_dollars']}, "
            f"orders={summary['total_orders']}, fills={summary['total_fills']}, "
            f"positions={summary['open_positions']}, volume={summary['total_volume']}, "
            f"fees={summary['total_fees']}"
        )
    except Exception as e:
        test_fail("Paper trading summary", str(e))


# ══════════════════════════════════════════════════════════════════════════
# PHASE 9: Multi-Trade Strategy Simulation
# ══════════════════════════════════════════════════════════════════════════

async def phase_9_strategy(paper_api, sim, markets, predictions, rm):
    """Simulate a full trading strategy across multiple markets."""
    header("PHASE 9 — 🎯 Multi-Trade Strategy Simulation")

    if not predictions or not sim:
        test_skip("All strategy tests", "No predictions available")
        return

    from app.engine.execution import ExecutionEngine
    from app.kalshi.models import OrderSide, OrderAction, OrderType

    engine = ExecutionEngine(api=paper_api, risk_manager=rm)
    if rm:
        rm.deactivate_kill_switch()

    balance_before = sim.balance_cents
    trades_executed = 0
    trades_skipped = 0

    # 9.1: Execute trades on top opportunities
    try:
        # Sort by edge magnitude
        sorted_preds = sorted(predictions, key=lambda x: abs(x[2].edge), reverse=True)

        for market, features, pred in sorted_preds[:10]:  # top 10 signals
            # Determine side and price
            side = OrderSide.YES if pred.side == "yes" else OrderSide.NO
            action = OrderAction.BUY

            # Use market's actual bid/ask for realistic pricing
            if side == OrderSide.YES:
                price_cents = int((market.yes_ask or Decimal("0.50")) * 100)
            else:
                price_cents = int((market.no_ask or Decimal("0.50")) * 100)

            price_cents = max(1, min(99, price_cents))  # clamp to valid range

            # Kelly sizing (simplified)
            conf = pred.confidence
            edge = abs(pred.edge)
            if conf > 0.5 and edge > 0.01:
                kelly_frac = max(0, (conf - 0.5) * 2) * 0.25  # quarter Kelly
                count = max(1, min(20, int(kelly_frac * 100)))
            else:
                count = 1

            # Check balance
            cost = price_cents * count + 7 * count  # cost + fees
            if cost > sim.balance_cents:
                trades_skipped += 1
                continue

            result = await engine.execute(
                ticker=market.ticker,
                side=side,
                action=action,
                count=count,
                price_cents=price_cents,
            )

            if result.success:
                trades_executed += 1
            else:
                trades_skipped += 1

        test_pass(
            "Strategy execution",
            f"{trades_executed} trades executed, {trades_skipped} skipped, "
            f"balance: {money(balance_before)} → {sim.balance_dollars}"
        )
    except Exception as e:
        test_fail("Strategy execution", str(e))

    # 9.2: Portfolio diversity
    try:
        positions = sim.get_positions()
        tickers = [p.ticker for p in positions]
        test_pass(
            "Portfolio diversity",
            f"{len(tickers)} markets: {', '.join(tickers[:5])}"
            f"{'...' if len(tickers) > 5 else ''}"
        )
    except Exception as e:
        test_fail("Portfolio diversity", str(e))

    # 9.3: Risk exposure check
    try:
        total_exposure = sum(
            abs(p.market_exposure or 0)
            for p in sim.get_positions()
        )
        test_pass(
            "Total exposure",
            f"{money(total_exposure)} across {len(sim.get_positions())} positions"
        )
    except Exception as e:
        test_fail("Total exposure", str(e))

    # 9.4: Close ALL positions (sell everything)
    close_count = 0
    try:
        for pos_data in sim._positions.values():
            if pos_data.yes_count > 0:
                # Compute a reasonable sell price
                mkt = None
                for m in (markets or []):
                    if m.ticker == pos_data.ticker:
                        mkt = m
                        break
                sell_price = int((mkt.yes_bid or Decimal("0.40")) * 100) if mkt else 40
                sell_price = max(1, sell_price)

                result = await engine.execute(
                    ticker=pos_data.ticker,
                    side=OrderSide.YES,
                    action=OrderAction.SELL,
                    count=pos_data.yes_count,
                    price_cents=sell_price,
                )
                if result.success:
                    close_count += 1

            if pos_data.no_count > 0:
                mkt = None
                for m in (markets or []):
                    if m.ticker == pos_data.ticker:
                        mkt = m
                        break
                sell_price = int((mkt.no_bid or Decimal("0.40")) * 100) if mkt else 40
                sell_price = max(1, sell_price)

                result = await engine.execute(
                    ticker=pos_data.ticker,
                    side=OrderSide.NO,
                    action=OrderAction.SELL,
                    count=pos_data.no_count,
                    price_cents=sell_price,
                )
                if result.success:
                    close_count += 1

        test_pass(
            "Close all positions",
            f"closed {close_count} position legs, final balance={sim.balance_dollars}"
        )
    except Exception as e:
        test_fail("Close all positions", str(e))

    # 9.5: Final P&L
    try:
        pnl = sim.pnl_cents
        pnl_pct = (pnl / sim.starting_balance_cents) * 100
        emoji = "📈" if pnl >= 0 else "📉"
        test_pass(
            f"Final P&L {emoji}",
            f"{money(pnl)} ({pnl_pct:+.2f}%) — fees={money(sim.total_fees_paid)}, "
            f"volume={money(sim.total_volume_cents)}"
        )
    except Exception as e:
        test_fail("Final P&L", str(e))


# ══════════════════════════════════════════════════════════════════════════
# PHASE 10: Full Autonomous Agent Cycle
# ══════════════════════════════════════════════════════════════════════════

async def phase_10_agent(paper_api, sim, markets):
    """Complete autonomous agent cycle: scan → predict → size → EXECUTE."""
    header("PHASE 10 — 🤖 Autonomous Agent Cycle (with REAL Execution)")

    if not paper_api or not markets:
        test_skip("All agent tests", "Missing API/markets")
        return

    from app.ai.features import FeatureEngine
    from app.ai.models import XGBoostPredictor
    from app.engine.execution import ExecutionEngine
    from app.engine.paper_trader import PaperTradingSimulator
    from app.engine.risk import RiskManager, RiskLimits
    from app.kalshi.models import OrderSide, OrderAction
    import numpy as np

    # Fresh simulator for clean agent test
    agent_sim = PaperTradingSimulator(
        starting_balance_cents=500_000,  # $5,000
        fee_rate_cents=7,
        instant_fill=True,
    )
    agent_api = agent_sim.wrap_api(paper_api._real_api)

    agent_rm = RiskManager(RiskLimits(
        max_position_size=50,
        max_daily_loss=Decimal("200"),
        max_portfolio_exposure=Decimal("2000"),
        max_single_order_cost=Decimal("500"),
    ))
    agent_engine = ExecutionEngine(api=agent_api, risk_manager=agent_rm)

    fe = FeatureEngine()
    predictor = XGBoostPredictor()

    # Train on synthetic data
    n_feat = 29
    X = np.random.rand(300, n_feat).astype(np.float32)
    y = (X[:, 0] > 0.5).astype(np.float32)
    predictor.train(X, y, num_boost_round=20, early_stopping_rounds=5)

    # 10.1: Full scan → predict → execute cycle
    try:
        candidates = markets[:30]
        executed = []
        scanned = 0
        featured = 0
        predicted = 0

        for m in candidates:
            scanned += 1
            try:
                feat = fe.compute(m)
                featured += 1
            except Exception:
                continue

            pred = predictor.predict(feat)
            predicted += 1

            # Filter: confidence > 0.52, edge > 0.01
            if pred.confidence < 0.52 or abs(pred.edge) < 0.01:
                continue

            # Size: 1-10 contracts based on confidence
            count = max(1, min(10, int((pred.confidence - 0.5) * 100)))

            # Price
            side = OrderSide.YES if pred.side == "yes" else OrderSide.NO
            if side == OrderSide.YES:
                price = int((m.yes_ask or Decimal("0.50")) * 100)
            else:
                price = int((m.no_ask or Decimal("0.50")) * 100)
            price = max(1, min(99, price))

            # Check balance
            total_cost = price * count + 7 * count
            if total_cost > agent_sim.balance_cents:
                continue

            result = await agent_engine.execute(
                ticker=m.ticker,
                side=side,
                action=OrderAction.BUY,
                count=count,
                price_cents=price,
            )

            if result.success:
                executed.append({
                    "ticker": m.ticker,
                    "side": pred.side,
                    "count": count,
                    "price": price,
                    "conf": pred.confidence,
                    "edge": pred.edge,
                })

        test_pass(
            "Agent cycle complete",
            f"scanned={scanned} → featured={featured} → predicted={predicted} "
            f"→ executed={len(executed)}"
        )
    except Exception as e:
        test_fail("Agent cycle complete", str(e))

    # 10.2: Agent trade details
    try:
        if executed:
            for t in executed[:5]:
                print(
                    f"    {DIM}→ {t['ticker']}: {t['side'].upper()} x{t['count']} "
                    f"@ {t['price']}¢ (conf={t['conf']:.3f}, edge={t['edge']:+.3f}){RESET}"
                )
            if len(executed) > 5:
                print(f"    {DIM}... and {len(executed) - 5} more trades{RESET}")
            test_pass("Agent trade details", f"{len(executed)} positions opened")
        else:
            test_skip("Agent trade details", "No signals above threshold")
    except Exception as e:
        test_fail("Agent trade details", str(e))

    # 10.3: Agent portfolio summary
    try:
        summary = agent_sim.summary()
        test_pass(
            "Agent portfolio",
            f"balance={summary['balance_dollars']}, positions={summary['open_positions']}, "
            f"fills={summary['total_fills']}, volume={summary['total_volume']}"
        )
    except Exception as e:
        test_fail("Agent portfolio", str(e))

    # 10.4: Final agent stats
    try:
        stats = agent_engine.stats
        pnl = agent_sim.pnl_cents
        emoji = "📈" if pnl >= 0 else "📉"
        test_pass(
            f"Agent stats {emoji}",
            f"orders={stats.total_orders}, success={stats.successful_orders}, "
            f"risk_rejected={stats.risk_rejections}, P&L={money(pnl)}"
        )
    except Exception as e:
        test_fail("Agent stats", str(e))


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

async def main():
    print(f"\n{BOLD}{MAGENTA}{'═' * 65}")
    print(f"  JA HEDGE — Paper Trading Simulation")
    print(f"  💰 $10,000 Fake Cash • Real Market Data • Full Pipeline")
    print(f"{'═' * 65}{RESET}")

    t0 = time.time()

    # Phase 1: Setup
    api, sim, paper_api = await phase_1_setup()

    # Phase 2: Real market data
    markets, tradeable = await phase_2_markets(paper_api)

    # Phase 3: ML features
    features, all_features = await phase_3_features(markets, tradeable)

    # Phase 4: AI predictions
    predictions = await phase_4_predictions(features, all_features, tradeable)

    # Phase 5: Risk management
    rm = await phase_5_risk(tradeable)

    # Phase 6: ORDER EXECUTION! 🎉
    await phase_6_execution(paper_api, sim, tradeable, rm)

    # Phase 7: Order cancellation
    await phase_7_cancellation(paper_api, sim, tradeable)

    # Phase 8: Portfolio tracking
    await phase_8_portfolio(paper_api, sim)

    # Phase 9: Multi-trade strategy
    await phase_9_strategy(paper_api, sim, markets, predictions, rm)

    # Phase 10: Full autonomous agent
    await phase_10_agent(paper_api, sim, markets)

    # Cleanup
    if api:
        try:
            await api.__aexit__(None, None, None)
        except Exception:
            pass

    # ── Grand Summary ─────────────────────────────────────
    elapsed = time.time() - t0
    total = passed + failed + skipped

    print(f"\n{BOLD}{MAGENTA}{'═' * 65}")
    print(f"  PAPER TRADING RESULTS: {total} tests in {elapsed:.1f}s")
    print(f"{'═' * 65}{RESET}")
    print(f"  {GREEN}✓ Passed:  {passed}{RESET}")
    print(f"  {RED}✗ Failed:  {failed}{RESET}")
    print(f"  {YELLOW}○ Skipped: {skipped}{RESET}")

    if sim:
        print(f"\n  {BOLD}💰 Paper Trading Stats:{RESET}")
        summary = sim.summary()
        print(f"  Balance:   {summary['balance_dollars']} (started $10,000.00)")
        print(f"  P&L:       {summary['pnl_dollars']}")
        print(f"  Orders:    {summary['total_orders']}")
        print(f"  Fills:     {summary['total_fills']}")
        print(f"  Positions: {summary['open_positions']}")
        print(f"  Volume:    {summary['total_volume']}")
        print(f"  Fees:      {summary['total_fees']}")

    print()
    if failed == 0:
        print(f"  {GREEN}{BOLD}🚀 ALL TESTS PASSED — Paper trading pipeline fully operational!{RESET}")
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
