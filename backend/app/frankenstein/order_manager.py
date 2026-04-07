"""
Frankenstein — Order Manager. 🧟📦

Owns the full order lifecycle:
  • Price computation (maker / taker)
  • Trade execution (buy & sell through ExecutionEngine)
  • Pending-order tracking and stale-order cancellation
  • Fill-rate statistics

Extracted from brain.py to keep the Brain as a pure orchestrator.
"""

from __future__ import annotations

import time
from typing import Any

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction
from app.engine.execution import ExecutionEngine, ExecutionResult
from app.frankenstein.constants import (
    FILL_PROB_DECAY_SECONDS,
    FILL_PROB_MIN_STALE_SECONDS,
    MULTI_LEVEL_ENABLED,
    MULTI_LEVEL_MAX_LEVELS,
    MULTI_LEVEL_MIN_COUNT,
    MULTI_LEVEL_MIN_SPREAD_CENTS,
    MULTI_LEVEL_STEP_CENTS,
    MULTI_LEVEL_WEIGHTS,
    ORDER_STALE_SECONDS,
    POLL_REQUOTE_ENABLED,
    POLL_REQUOTE_MAX_PER_SCAN,
    POLL_REQUOTE_MIN_AGE_SECONDS,
    REQUOTE_AGGRESSION_BY_SPREAD,
    REQUOTE_EDGE_CANCEL_THRESHOLD,
    TAKER_FEE_CENTS,
    USE_MAKER_ORDERS,
)
from app.frankenstein.fill_predictor import FillObservation, FillPredictor
from app.frankenstein.event_bus import Event, EventBus, EventType
from app.frankenstein.memory import TradeMemory
from app.kalshi.models import Market, OrderAction, OrderSide, OrderType
from app.logging_config import get_logger

log = get_logger("frankenstein.order_manager")

# Minimum price change (in cents) before we bother amending
MIN_AMEND_DELTA_CENTS = 1
# Maximum amends per order to avoid exchange rate-limit issues
MAX_AMENDS_PER_ORDER = 10


class OrderManager:
    """Manages order placement, pricing, lifecycle, and fill tracking."""

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        feature_engine: FeatureEngine,
        memory: TradeMemory,
        event_bus: EventBus | None = None,
        capital_allocator: Any | None = None,
        fill_predictor: FillPredictor | None = None,
    ) -> None:
        self._execution = execution_engine
        self._features = feature_engine
        self.memory = memory
        self._bus = event_bus
        self._capital = capital_allocator  # Phase 3+4: capital gating
        self._fill_pred = fill_predictor   # Phase 5: fill rate prediction

        # {order_id: {"ticker": str, "placed_at": float, "price_cents": int,
        #             "side": str, "amend_count": int, "count": int}}
        self.pending_orders: dict[str, dict[str, Any]] = {}
        self.fill_rate_stats: dict[str, int] = {
            "placed": 0,
            "filled": 0,
            "cancelled": 0,
            "amended": 0,
            "edge_cancelled": 0,   # Phase 3: cancelled due to edge evaporation
            "decay_cancelled": 0,  # Phase 3: cancelled due to fill prob decay
        }
        # Phase 3: requote metrics
        self._requote_stats: dict[str, int] = {
            "requotes_attempted": 0,
            "requotes_succeeded": 0,
            "requotes_skipped_edge": 0,
            "requotes_skipped_delta": 0,
            "requotes_cancelled_edge": 0,
        }
        # Phase 6: multi-level quoting metrics
        self._multi_level_stats: dict[str, int] = {
            "multi_level_trades": 0,
            "single_level_trades": 0,
            "total_levels_placed": 0,
            "multi_level_fallback": 0,  # fell back to single due to spread/count
        }

    # ── Phase 7: Confidence-to-Price Skew ────────────────────────────

    def _confidence_skew_cents(
        self, confidence: float, spread_cents: int,
    ) -> int:
        """
        Phase 7+4: Map prediction confidence to a price offset (cents).

        High confidence → more aggressive (bid + N¢) to improve fill rate.
        Low confidence  → passive (bid + 1¢) to maximise edge.
        Skew is bounded by the available spread room to NEVER cross ask.

        Phase 4 upgrade: Bumped all tiers by 1¢ to reduce expired orders.
        With 0¢ maker fees, being 1¢ more aggressive costs nothing
        but dramatically improves fill probability.

        Returns additional cents above bid (0 = at bid, 1 = bid+1¢, etc.)
        """
        if spread_cents <= 1:
            return 1  # Phase 4: even at 1¢ spread, try bid+1¢ (= at ask − still maker)

        # Available maker room: spread - 1 (must stay strictly below ask)
        max_skew = max(spread_cents - 1, 0)

        # Phase 27: AGGRESSIVE pricing — get close to ask for better fills.
        # With 0¢ maker fees, being 2-3¢ more aggressive is essentially free.
        # The fill rate improvement from better queue position far outweighs
        # the tiny price concession.
        if confidence >= 0.80:
            raw = 6  # Phase 27: bid+6¢ (was 4) — near-ask for best signals
        elif confidence >= 0.70:
            raw = 5  # Phase 27: bid+5¢ (was 3)
        elif confidence >= 0.55:
            raw = 4  # Phase 27: bid+4¢ (was 2)
        else:
            raw = 2  # Phase 27: bid+2¢ (was 1) — never sit at raw bid

        # Phase 27: Spread-adaptive bonus — wider spreads get more aggressive
        if spread_cents >= 10:
            raw += 2  # Extra 2¢ in wide-spread markets
        elif spread_cents >= 6:
            raw += 1  # Extra 1¢ in medium-spread markets

        return min(raw, max_skew)

    # ── Phase 8: Inventory-Aware Pricing ──────────────────────────────

    def _inventory_skew_cents(
        self, ticker: str, side: str, spread_cents: int,
    ) -> int:
        """
        Phase 8: Adjust price based on existing inventory.

        If we already hold a position on this ticker on the SAME side,
        skew price DOWN (more passive) to discourage adding to inventory.
        If we are reducing / no position, no penalty.

        Returns cents to SUBTRACT from the computed price (0 = no adjustment).
        """
        from app.pipeline.portfolio_tracker import portfolio_state

        pos = portfolio_state.positions.get(ticker)
        if pos is None:
            return 0  # No existing position — no skew

        qty = pos.position or 0
        # MarketPosition doesn't have a 'side' field — infer from position sign
        pos_side = "yes" if qty > 0 else ("no" if qty < 0 else "")

        # Same side as existing position → discourage piling on
        same_side = (
            (side == "yes" and qty > 0 and pos_side in ("yes", ""))
            or (side == "no" and qty < 0 and pos_side in ("no", ""))
        )
        if not same_side:
            return 0

        # Scale penalty by position size: 1¢ per existing contract, max 3¢
        penalty = min(abs(qty), 3)
        # But never more than half the spread
        return min(penalty, max(spread_cents // 2, 0))

    # ── Price Computation ─────────────────────────────────────────────

    def compute_price(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market: Market | None = None,
    ) -> int:
        """
        Compute optimal order price — spread-aware placement.

        MAKER MODE (USE_MAKER_ORDERS=True):
        - Phase 7: Confidence skew — high confidence → bid+N¢ (aggressive)
        - Phase 8: Inventory skew — existing position → bid-N¢ (passive)
        - NEVER cross the spread — that makes us a taker (7¢ fee)
        - Lower fill rate (~50-70%) but 0¢ fees makes up for it
        - Hold to settlement: no early exit (avoids sell-side taker fees)

        TAKER MODE (original):
        - Confidence-aware: high confidence → cross spread for fill
        - Low confidence → post passive limit for better fill price
        """
        mid = features.midpoint
        spread_cents = max(int(features.spread * 100), 1)
        confidence = prediction.confidence

        # Extract real bid/ask when market data is available
        if market:
            real_yes_bid = float(market.yes_bid) if market.yes_bid is not None else None
            real_yes_ask = float(market.yes_ask) if market.yes_ask is not None else None
            real_no_bid = float(market.no_bid) if market.no_bid is not None else None
            real_no_ask = float(market.no_ask) if market.no_ask is not None else None
        else:
            real_yes_bid = real_yes_ask = real_no_bid = real_no_ask = None

        # Phase 7: confidence-based price skew (cents above bid)
        conf_skew = self._confidence_skew_cents(confidence, spread_cents)
        # Phase 8: inventory-based price penalty (cents to subtract)
        inv_penalty = self._inventory_skew_cents(
            market.ticker if market else "", prediction.side, spread_cents,
        )

        if USE_MAKER_ORDERS:
            # ── MAKER PRICING: place at bid + confidence skew ──
            if prediction.side == "yes":
                bid = real_yes_bid if real_yes_bid and real_yes_bid > 0 else (mid - features.spread / 2)
                ask = real_yes_ask if real_yes_ask and real_yes_ask > 0 else (mid + features.spread / 2)
                if spread_cents <= 1:
                    price_frac = max(bid, 0.01)
                else:
                    # Phase 7: skew by confidence (was always bid+1¢)
                    skew_frac = conf_skew * 0.01
                    price_frac = min(bid + skew_frac, ask - 0.01)
                    # Phase 8: inventory penalty
                    price_frac -= inv_penalty * 0.01
                    price_frac = max(price_frac, bid, 0.01)
            else:
                # NO contracts
                if real_no_bid is not None and real_no_ask is not None and real_no_ask > 0:
                    no_bid = real_no_bid if real_no_bid > 0 else 0.01
                    no_ask = real_no_ask
                else:
                    no_bid = 1.0 - (mid + features.spread / 2)
                    no_ask = 1.0 - (mid - features.spread / 2)

                if spread_cents <= 1:
                    price_frac = max(no_bid, 0.01)
                else:
                    skew_frac = conf_skew * 0.01
                    price_frac = min(no_bid + skew_frac, no_ask - 0.01)
                    price_frac -= inv_penalty * 0.01
                    price_frac = max(price_frac, no_bid, 0.01)
        else:
            # ── TAKER PRICING (original logic) ──
            if prediction.side == "yes":
                bid = real_yes_bid if real_yes_bid and real_yes_bid > 0 else (mid - features.spread / 2)
                ask = real_yes_ask if real_yes_ask and real_yes_ask > 0 else (mid + features.spread / 2)

                if spread_cents <= 2:
                    price_frac = min(ask, 0.99)
                elif confidence >= 0.75:
                    price_frac = min(ask, 0.99)
                elif confidence >= 0.60:
                    price_frac = min(bid + 0.01, ask)
                else:
                    price_frac = max(bid + 0.01, 0.01)
            else:
                if real_no_bid is not None and real_no_ask is not None and real_no_ask > 0:
                    no_bid = real_no_bid if real_no_bid > 0 else 0.01
                    no_ask = real_no_ask
                else:
                    no_bid = 1.0 - (mid + features.spread / 2)
                    no_ask = 1.0 - (mid - features.spread / 2)

                if spread_cents <= 2:
                    price_frac = min(no_ask, 0.99)
                elif confidence >= 0.75:
                    price_frac = min(no_ask, 0.99)
                elif confidence >= 0.60:
                    price_frac = min(no_bid + 0.01, no_ask)
                else:
                    price_frac = max(no_bid + 0.01, 0.01)

        return max(1, min(99, int(price_frac * 100)))

    # ── Trade Execution ───────────────────────────────────────────────

    async def execute_trade(
        self,
        market: Market,
        prediction: Prediction,
        features: MarketFeatures,
        count: int,
        price_cents: int,
    ) -> ExecutionResult | None:
        """Execute a BUY order through the execution engine."""
        try:
            side = OrderSide.YES if prediction.side == "yes" else OrderSide.NO

            result = await self._execution.execute(
                ticker=market.ticker,
                side=side,
                action=OrderAction.BUY,
                count=count,
                price_cents=price_cents,
                order_type=OrderType.LIMIT,
                strategy_id="frankenstein",
                signal_id=None,
            )

            if result and result.success:
                self.fill_rate_stats["placed"] += 1

                # Phase 24: Paper fills are instant — count them so
                # fill_rate doesn't show 0% in paper mode.
                if result.order and getattr(result.order, "remaining_count", -1) == 0:
                    self.fill_rate_stats["filled"] += 1
                    # Phase 31: Record fill observation for fill predictor
                    # Paper fills are instant, but we still need to train the
                    # fill model so it can predict real-market fill rates.
                    _instant_info = {
                        "ticker": market.ticker,
                        "price_cents": price_cents,
                        "mid_cents": int(features.midpoint * 100) if features.midpoint else 50,
                        "spread_cents": max(int(features.spread * 100), 1) if features.spread else 3,
                        "side": prediction.side,
                        "volume": int(getattr(market, "volume", 0) or 0),
                        "open_interest": int(getattr(market, "open_interest", 0) or 0),
                        "amend_count": 0,
                        "expiration_ts": getattr(market, "close_time", None) or getattr(market, "expiration_time", None),
                    }
                    self._record_fill_observation(_instant_info, filled=True)

                if result.order_id:
                    # Phase 5: store book context for fill prediction
                    _spread = int(features.spread * 100) if features.spread else 1
                    _mid = int(features.midpoint * 100) if features.midpoint else 50
                    _vol = getattr(market, "volume", 0) or 0
                    _oi = getattr(market, "open_interest", 0) or 0
                    _exp = getattr(market, "close_time", None) or getattr(market, "expiration_time", None)

                    self.pending_orders[result.order_id] = {
                        "ticker": market.ticker,
                        "placed_at": time.time(),
                        "price_cents": price_cents,
                        "side": prediction.side,
                        "amend_count": 0,
                        "count": count,
                        # Phase 5: book snapshot for fill observation
                        "spread_cents": max(_spread, 1),
                        "mid_cents": _mid,
                        "volume": int(_vol),
                        "open_interest": int(_oi),
                        "expiration_ts": _exp,
                    }
                    # Phase 3+4: reserve capital
                    if self._capital:
                        self._capital.on_order_placed(
                            result.order_id, cost_cents=count * price_cents,
                        )

                # Publish event
                if self._bus:
                    await self._bus.publish(Event(
                        type=EventType.TRADE_EXECUTED,
                        data={
                            "ticker": market.ticker,
                            "side": prediction.side,
                            "count": count,
                            "price_cents": price_cents,
                            "order_id": result.order_id,
                        },
                        source="order_manager",
                    ))

            return result
        except Exception as e:
            log.error("execution_failed", ticker=market.ticker, error=str(e))
            return None

    # ── Phase 6: Multi-Level Quoting ──────────────────────────────────

    def compute_multi_level_prices(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market: Market | None = None,
    ) -> list[int]:
        """
        Compute multiple maker price levels for laddering orders.

        Returns a list of price_cents values from most aggressive (highest
        fill probability, lowest edge) to most passive (lowest fill prob,
        highest edge).

        Example for YES side, bid=42¢, ask=47¢ (5¢ spread):
          Level 0: 44¢  (bid+2¢, aggressive)
          Level 1: 43¢  (bid+1¢, standard)
          Level 2: 42¢  (bid,     passive)

        All prices are guaranteed to stay strictly below the ask (maker).
        Only returns multiple levels if spread >= MULTI_LEVEL_MIN_SPREAD_CENTS.
        """
        # Start with the standard single price
        base_price = self.compute_price(prediction, features, market=market)

        if not USE_MAKER_ORDERS or not MULTI_LEVEL_ENABLED:
            return [base_price]

        spread_cents = max(int(features.spread * 100), 1)
        if spread_cents < MULTI_LEVEL_MIN_SPREAD_CENTS:
            return [base_price]

        # Determine the bid and ask boundaries
        if market:
            if prediction.side == "yes":
                bid_c = int(float(market.yes_bid or 0) * 100) if market.yes_bid else 0
                ask_c = int(float(market.yes_ask or 0) * 100) if market.yes_ask else 99
            else:
                if market.no_bid is not None and market.no_ask is not None:
                    bid_c = int(float(market.no_bid or 0) * 100)
                    ask_c = int(float(market.no_ask or 0) * 100)
                else:
                    ya = float(market.yes_ask or 0)
                    yb = float(market.yes_bid or 0)
                    bid_c = max(1, int((1.0 - ya) * 100)) if ya > 0 else 1
                    ask_c = min(99, int((1.0 - yb) * 100)) if yb > 0 else 99
        else:
            mid = features.midpoint
            half = features.spread / 2.0
            bid_c = max(1, int((mid - half) * 100))
            ask_c = min(99, int((mid + half) * 100))

        if bid_c <= 0:
            bid_c = 1
        if ask_c <= bid_c:
            return [base_price]

        # Available room inside the spread (between bid and ask, exclusive)
        room = ask_c - bid_c - 1  # cents of room for maker orders
        if room < 1:
            return [base_price]

        # Determine how many levels fit
        n_levels = min(MULTI_LEVEL_MAX_LEVELS, room)
        n_levels = max(1, n_levels)

        # Build prices from aggressive (near ask) to passive (near bid)
        # Start from bid + room/2 (or ask-1, whichever is lower) and
        # step down by MULTI_LEVEL_STEP_CENTS toward bid.
        #
        # Example: bid=45, ask=55 (10¢ spread), 3 levels, step=1¢
        #   aggressive_top = min(ask-1, bid + room) = min(54, 54) = 54
        #   But we want to stay near our edge → cap at base_price + (n_levels-1)*step/2
        #   Level 0: base+1 = 47  (most aggressive)
        #   Level 1: base   = 46  (standard)
        #   Level 2: base-1 = 45  (passive, at bid)
        aggressive_top = min(
            base_price + (n_levels - 1) * MULTI_LEVEL_STEP_CENTS,
            ask_c - 1,
        )

        prices: list[int] = []
        for i in range(n_levels):
            p = aggressive_top - i * MULTI_LEVEL_STEP_CENTS
            # Clamp: never below bid, never at or above ask
            p = max(p, bid_c)
            p = min(p, ask_c - 1)
            p = max(1, min(99, p))
            if p not in prices:
                prices.append(p)

        return prices if prices else [base_price]

    def split_count_across_levels(
        self,
        total_count: int,
        n_levels: int,
    ) -> list[int]:
        """
        Distribute contracts across price levels using MULTI_LEVEL_WEIGHTS.

        Guarantees: every level gets >= 1 contract, total equals total_count.
        """
        if n_levels <= 1 or total_count <= 1:
            return [total_count]

        weights = MULTI_LEVEL_WEIGHTS[:n_levels]
        wsum = sum(weights)
        if wsum <= 0:
            weights = [1.0 / n_levels] * n_levels
            wsum = 1.0

        # Weighted allocation (fractional)
        raw = [(w / wsum) * total_count for w in weights]

        # Round down, then distribute remainders
        counts = [max(1, int(r)) for r in raw]
        remainder = total_count - sum(counts)

        # Give remainders to the most aggressive levels first
        for i in range(abs(remainder)):
            if remainder > 0:
                counts[i % n_levels] += 1
            elif remainder < 0:
                # Over-allocated — take from least aggressive levels
                idx = n_levels - 1 - (i % n_levels)
                if counts[idx] > 1:
                    counts[idx] -= 1

        return counts

    async def execute_multi_level_trade(
        self,
        market: Market,
        prediction: Prediction,
        features: MarketFeatures,
        count: int,
        price_cents: int,
    ) -> ExecutionResult | None:
        """
        Phase 6: Execute a trade split across multiple price levels.

        If the spread is wide enough and count >= MULTI_LEVEL_MIN_COUNT,
        places separate orders at each level.  Otherwise falls back to
        a single execute_trade().

        Returns the result from the most aggressive (first) level,
        or the single-order result on fallback.
        """
        # Check multi-level eligibility
        spread_cents = max(int(features.spread * 100), 1)
        if (
            not MULTI_LEVEL_ENABLED
            or not USE_MAKER_ORDERS
            or spread_cents < MULTI_LEVEL_MIN_SPREAD_CENTS
            or count < MULTI_LEVEL_MIN_COUNT
        ):
            self._multi_level_stats["single_level_trades"] += 1
            return await self.execute_trade(
                market=market, prediction=prediction,
                features=features, count=count, price_cents=price_cents,
            )

        # Compute multi-level prices
        prices = self.compute_multi_level_prices(prediction, features, market=market)
        if len(prices) <= 1:
            self._multi_level_stats["multi_level_fallback"] += 1
            return await self.execute_trade(
                market=market, prediction=prediction,
                features=features, count=count, price_cents=price_cents,
            )

        # Split contracts across levels
        counts = self.split_count_across_levels(count, len(prices))

        # Place orders at each level
        first_result: ExecutionResult | None = None
        levels_placed = 0

        for level_idx, (lvl_price, lvl_count) in enumerate(zip(prices, counts)):
            if lvl_count <= 0:
                continue

            # Capital check for each level
            if self._capital:
                cost = lvl_count * lvl_price
                can_afford, _ = self._capital.can_afford(cost)
                if not can_afford:
                    break  # Stop placing levels if capital runs out

            result = await self.execute_trade(
                market=market, prediction=prediction,
                features=features, count=lvl_count, price_cents=lvl_price,
            )

            if result and result.success:
                levels_placed += 1
                if first_result is None:
                    first_result = result

                log.info("🧟📊 MULTI-LEVEL ORDER",
                         ticker=market.ticker,
                         level=level_idx,
                         price=f"{lvl_price}¢",
                         count=lvl_count,
                         total_levels=len(prices))

        if levels_placed > 0:
            self._multi_level_stats["multi_level_trades"] += 1
            self._multi_level_stats["total_levels_placed"] += levels_placed
        else:
            self._multi_level_stats["multi_level_fallback"] += 1

        return first_result

    async def execute_exit(
        self,
        market: Market,
        side: str,
        count: int,
        reason: str,
    ) -> ExecutionResult | None:
        """Execute a SELL order to exit a position."""
        try:
            order_side = OrderSide.YES if side == "yes" else OrderSide.NO
            mid = (
                float(market.midpoint or market.last_price or 50) / 100
                if isinstance(market.midpoint, int)
                else float(market.midpoint or market.last_price or 0.50)
            )

            # Price at or slightly below mid for quick execution
            if side == "yes":
                exit_price = max(int(mid * 100) - 1, 1)
            else:
                exit_price = max(int((1.0 - mid) * 100) - 1, 1)

            result = await self._execution.execute(
                ticker=market.ticker,
                side=order_side,
                action=OrderAction.SELL,
                count=count,
                price_cents=exit_price,
                order_type=OrderType.LIMIT,
                strategy_id="frankenstein_exit",
                signal_id=None,
            )

            if result and result.success:
                log.info(
                    "🧟📤 EXIT_EXECUTED",
                    ticker=market.ticker,
                    side=side,
                    count=count,
                    price=f"{exit_price}¢",
                    reason=reason,
                )

                # Record exit in memory
                self.memory.record_trade(
                    ticker=market.ticker,
                    prediction=Prediction(
                        side=side, confidence=0.0, predicted_prob=0.5,
                        edge=0.0, model_name="exit", model_version="exit",
                    ),
                    features=self._features.compute(market),
                    action="sell",
                    count=count,
                    price_cents=exit_price,
                    order_id=result.order_id or "",
                    latency_ms=result.latency_ms,
                )

                # Publish event
                if self._bus:
                    await self._bus.publish(Event(
                        type=EventType.POSITION_CLOSED,
                        data={
                            "ticker": market.ticker,
                            "side": side,
                            "count": count,
                            "price_cents": exit_price,
                            "reason": reason,
                        },
                        source="order_manager",
                    ))

            return result
        except Exception as e:
            log.error("exit_failed", ticker=market.ticker, error=str(e))
            return None

    # ── Phase 28: Hybrid Taker Execution ──────────────────────────────

    async def execute_taker_trade(
        self,
        market: Market,
        prediction: Prediction,
        features: MarketFeatures,
        count: int,
        price_cents: int,
    ) -> ExecutionResult | None:
        """
        Phase 28: Execute a taker (IOC/market) order for immediate fill.

        Used for A/A+ grade trades with strong edge where 100% fill rate
        is more important than saving the 7¢/contract taker fee.

        Prices at the ask (for YES) or no_ask (for NO) to guarantee fill.
        """
        try:
            side = OrderSide.YES if prediction.side == "yes" else OrderSide.NO

            # Price at the ask for guaranteed fill
            if prediction.side == "yes":
                ask = float(market.yes_ask or 0) if market.yes_ask else 0
                if ask > 0:
                    taker_price = min(int(ask * 100), 99)
                else:
                    taker_price = min(price_cents + 2, 99)  # bid + 2¢ as fallback
            else:
                no_ask = float(market.no_ask or 0) if market.no_ask else 0
                if no_ask > 0:
                    taker_price = min(int(no_ask * 100), 99)
                else:
                    taker_price = min(price_cents + 2, 99)

            taker_price = max(1, taker_price)

            result = await self._execution.execute(
                ticker=market.ticker,
                side=side,
                action=OrderAction.BUY,
                count=count,
                price_cents=taker_price,
                order_type=OrderType.LIMIT,  # Limit at ask = instant fill
                strategy_id="frankenstein_taker",
                signal_id=None,
            )

            if result and result.success:
                self.fill_rate_stats["placed"] += 1
                self.fill_rate_stats["filled"] += 1  # Taker = instant fill

                # Phase 3+4: reserve capital
                if self._capital:
                    if result.order_id:
                        self._capital.on_order_placed(
                            result.order_id, cost_cents=count * taker_price,
                        )
                        # Immediately mark as filled since taker fills instantly
                        self._capital.on_order_filled(result.order_id)

                log.info("🧟⚡ TAKER TRADE",
                         ticker=market.ticker,
                         side=prediction.side,
                         price=f"{taker_price}¢",
                         count=count,
                         edge=f"{prediction.edge:.3f}")

                if self._bus:
                    await self._bus.publish(Event(
                        type=EventType.TRADE_EXECUTED,
                        data={
                            "ticker": market.ticker,
                            "side": prediction.side,
                            "count": count,
                            "price_cents": taker_price,
                            "order_id": result.order_id,
                            "execution_type": "taker",
                        },
                        source="order_manager",
                    ))

            return result
        except Exception as e:
            log.error("taker_execution_failed", ticker=market.ticker, error=str(e))
            return None

    # ── Phase 28: Poll-Based Requoting ────────────────────────────────

    async def requote_pending_orders(self) -> dict[str, int]:
        """
        Phase 28: Poll-based requoting — amend stale orders to current market prices.

        Since WebSocket is unreliable, this runs each scan cycle and checks
        all pending orders against current market data. If the best bid has
        moved, we amend our resting orders to stay competitive.

        Returns stats dict with requote counts.
        """
        if not POLL_REQUOTE_ENABLED or not self.pending_orders or not USE_MAKER_ORDERS:
            return {"checked": 0, "requoted": 0, "skipped": 0}

        now = time.time()
        requoted = 0
        skipped = 0
        checked = 0

        # Sort by age (oldest first — most likely to be stale)
        order_items = sorted(
            self.pending_orders.items(),
            key=lambda x: x[1].get("placed_at", now),
        )

        for order_id, info in order_items[:POLL_REQUOTE_MAX_PER_SCAN]:
            age = now - info.get("placed_at", now)

            # Skip too-young orders
            if age < POLL_REQUOTE_MIN_AGE_SECONDS:
                skipped += 1
                continue

            # Skip already heavily amended
            if info.get("amend_count", 0) >= MAX_AMENDS_PER_ORDER:
                skipped += 1
                continue

            ticker = info.get("ticker", "")
            if not ticker:
                continue

            checked += 1

            # Get current market data from cache
            from app.pipeline import market_cache as _mc28
            cached = _mc28.get(ticker)
            if not cached:
                continue

            side = info.get("side", "yes")
            old_price = info.get("price_cents", 0)

            # Compute new optimal price from current book
            if side == "yes":
                new_bid = float(cached.yes_bid or 0)
                new_ask = float(cached.yes_ask or 0)
                if new_bid <= 0 or new_ask <= 0:
                    continue
                spread_cents = max(1, int((new_ask - new_bid) * 100))
            else:
                # NO side
                if cached.no_bid is not None and cached.no_ask is not None:
                    new_bid = float(cached.no_bid or 0)
                    new_ask = float(cached.no_ask or 0)
                else:
                    ya = float(cached.yes_ask or 0)
                    yb = float(cached.yes_bid or 0)
                    new_bid = max(0.01, 1.0 - ya) if ya > 0 else 0.01
                    new_ask = min(0.99, 1.0 - yb) if yb > 0 else 0.99
                if new_bid <= 0 or new_ask <= 0:
                    continue
                spread_cents = max(1, int((new_ask - new_bid) * 100))

            # Compute smart requote price using spread-adaptive aggression
            new_price = self._compute_smart_requote_price(
                side,
                float(cached.yes_bid or 0),
                float(cached.yes_ask or 0),
                float(cached.no_bid or 0) if cached.no_bid is not None else 0.0,
                float(cached.no_ask or 0) if cached.no_ask is not None else 0.0,
                spread_cents,
            )

            if new_price <= 0 or new_price >= 100:
                continue

            delta = abs(new_price - old_price)
            if delta < MIN_AMEND_DELTA_CENTS:
                skipped += 1
                continue

            # Amend the order
            self._requote_stats["requotes_attempted"] += 1
            success = await self._amend_order(order_id, side, new_price)
            if success:
                old_count = info.get("count", 1)
                info["price_cents"] = new_price
                info["amend_count"] = info.get("amend_count", 0) + 1
                self.fill_rate_stats["amended"] += 1
                self._requote_stats["requotes_succeeded"] += 1
                requoted += 1

                # Update capital reservation
                if self._capital:
                    self._capital.on_order_amended(
                        order_id, new_cost_cents=old_count * new_price,
                    )

        if requoted > 0:
            log.info("🧟📝 POLL REQUOTE",
                     checked=checked, requoted=requoted, skipped=skipped)

        return {"checked": checked, "requoted": requoted, "skipped": skipped}

    # ── Stale Order Cleanup ───────────────────────────────────────────

    async def cleanup_stale_orders(self) -> None:
        """Cancel orders that haven't filled within timeout.

        Phase 3: Fill probability decay — orders that have been resting
        for FILL_PROB_DECAY_SECONDS get their stale timeout halved.
        Old orders that still haven't filled are likely at stale prices
        and waste reserved capital.
        """
        if not self.pending_orders:
            return

        now = time.time()
        stale_ids: list[str] = []
        decay_ids: list[str] = []

        for oid, info in self.pending_orders.items():
            age = now - info.get("placed_at", now)

            # Phase 3: Fill probability decay — older orders get cancelled sooner
            if age > FILL_PROB_DECAY_SECONDS:
                # After decay threshold, use accelerated stale timeout
                effective_stale = max(
                    FILL_PROB_MIN_STALE_SECONDS,
                    ORDER_STALE_SECONDS * 0.5,  # halved timeout
                )
                if age > effective_stale:
                    decay_ids.append(oid)
                    continue

            # Standard stale timeout
            if age > ORDER_STALE_SECONDS:
                stale_ids.append(oid)

        all_cancel = stale_ids + decay_ids
        if not all_cancel:
            return

        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return
            for oid in all_cancel:
                try:
                    await _st.kalshi_api.orders.cancel_order(oid)

                    is_decay = oid in decay_ids
                    if is_decay:
                        self.fill_rate_stats["decay_cancelled"] += 1
                    else:
                        self.fill_rate_stats["cancelled"] += 1

                    # Phase 3+4: release reserved capital
                    if self._capital:
                        self._capital.on_order_cancelled(oid)

                    # Phase 5: record cancel observation
                    info = self.pending_orders.get(oid, {})
                    self._record_fill_observation(info, filled=False)

                    log.info(
                        "stale_order_cancelled",
                        order_id=oid,
                        age_s=f"{now - self.pending_orders[oid].get('placed_at', now):.0f}",
                        reason="fill_decay" if is_decay else "stale",
                    )
                except Exception:
                    pass  # order may have already filled
                self.pending_orders.pop(oid, None)

            # Publish event
            if self._bus and all_cancel:
                await self._bus.publish(Event(
                    type=EventType.ORDER_CANCELLED,
                    data={
                        "cancelled_count": len(all_cancel),
                        "stale_count": len(stale_ids),
                        "decay_count": len(decay_ids),
                    },
                    source="order_manager",
                ))
        except Exception as e:
            log.debug("cleanup_stale_orders_error", error=str(e))

    # ── Helpers ───────────────────────────────────────────────────────

    def estimate_entry_price(self, ticker: str) -> float:
        """Estimate average entry price for a ticker from memory."""
        trades = self.memory.get_recent_trades(n=1000, ticker=ticker)
        buy_trades = [t for t in trades if t.action == "buy"]
        if not buy_trades:
            return 0.0
        total_cost = sum(t.price_cents for t in buy_trades)
        return (total_cost / len(buy_trades)) / 100.0

    def estimate_entry_time(self, ticker: str) -> float:
        """Get the earliest entry timestamp for a ticker position."""
        trades = self.memory.get_recent_trades(n=1000, ticker=ticker)
        buy_trades = [t for t in trades if t.action == "buy"]
        if not buy_trades:
            return 0.0
        return min(t.timestamp for t in buy_trades)

    # ── Phase 5: Fill Prediction Helpers ─────────────────────────────

    def _record_fill_observation(self, info: dict[str, Any], filled: bool) -> None:
        """Build a FillObservation from pending order context and record it."""
        if not self._fill_pred:
            return
        try:
            import datetime as _dt

            price_cents = info.get("price_cents", 50)
            mid_cents = info.get("mid_cents", 50)
            spread_cents = info.get("spread_cents", 3)
            side = info.get("side", "yes")
            volume = info.get("volume", 0)
            oi = info.get("open_interest", 0)
            amend_count = info.get("amend_count", 0)

            # Hours to expiry (rough estimate)
            exp_ts = info.get("expiration_ts")
            if exp_ts:
                if isinstance(exp_ts, str):
                    try:
                        exp_dt = _dt.datetime.fromisoformat(exp_ts.replace("Z", "+00:00"))
                        hours_to_exp = max(0.1, (exp_dt.timestamp() - time.time()) / 3600)
                    except Exception:
                        hours_to_exp = 24.0
                elif isinstance(exp_ts, (int, float)):
                    hours_to_exp = max(0.1, (exp_ts - time.time()) / 3600)
                else:
                    hours_to_exp = 24.0
            else:
                hours_to_exp = 24.0

            obs = FillObservation(
                spread_cents=spread_cents,
                price_vs_mid_cents=price_cents - mid_cents,
                side=side,
                volume=volume,
                open_interest=oi,
                hour_of_day=_dt.datetime.now().hour,
                hours_to_expiry=hours_to_exp,
                amend_count=amend_count,
            )

            if filled:
                self._fill_pred.record_fill(obs)
            else:
                self._fill_pred.record_cancel(obs)
        except Exception:
            pass  # Never block order lifecycle for prediction bookkeeping

    def get_fill_probability(
        self,
        side: str,
        price_cents: int,
        spread_cents: int = 3,
        mid_cents: int = 50,
        volume: int = 0,
        open_interest: int = 0,
        hours_to_expiry: float = 24.0,
        amend_count: int = 0,
    ) -> float:
        """Public method to query predicted fill probability for a new order."""
        if not self._fill_pred:
            return 0.60  # default assumption
        import datetime as _dt
        return self._fill_pred.predict_fill_probability(
            spread_cents=spread_cents,
            price_vs_mid_cents=price_cents - mid_cents,
            side=side,
            volume=volume,
            open_interest=open_interest,
            hour_of_day=_dt.datetime.now().hour,
            hours_to_expiry=hours_to_expiry,
            amend_count=amend_count,
        )

    def stats(self) -> dict[str, Any]:
        """Order manager statistics."""
        base = {
            "pending_orders": len(self.pending_orders),
            "fill_rate_stats": dict(self.fill_rate_stats),
            "fill_rate": (
                self.fill_rate_stats["filled"] / max(self.fill_rate_stats["placed"], 1)
            ),
            "requote_stats": dict(self._requote_stats),
            # Phase 6: multi-level quoting
            "multi_level_stats": dict(self._multi_level_stats),
        }
        # Phase 5: include fill predictor stats
        if self._fill_pred:
            base["fill_predictor"] = self._fill_pred.stats()
        return base

    # ── Phase 2: Real-time Requoting ──────────────────────────────────

    async def handle_fill(self, event: Event) -> None:
        """
        React to FILL_RECEIVED events from the WS bridge.

        Updates pending_orders, fill_rate_stats, and publishes
        ORDER_FILLED + CAPITAL_FREED events.
        """
        data = event.data
        order_id = data.get("order_id", "")
        ticker = data.get("ticker", "")
        count = data.get("count", 0)
        price_cents = data.get("price_cents", 0)
        action = data.get("action", "")

        if order_id and order_id in self.pending_orders:
            info = self.pending_orders.pop(order_id)
            self.fill_rate_stats["filled"] += 1

            # Phase 3+4: release capital reservation
            if self._capital:
                self._capital.on_order_filled(order_id)

            # Phase 5: record fill observation for fill rate model
            self._record_fill_observation(info, filled=True)

            log.info("🧟✅ ORDER FILLED (WS)",
                     order_id=order_id, ticker=ticker,
                     price=f"{price_cents}¢", count=count)

            # Publish ORDER_FILLED
            if self._bus:
                await self._bus.publish(Event(
                    type=EventType.ORDER_FILLED,
                    data={
                        "order_id": order_id,
                        "ticker": ticker,
                        "price_cents": price_cents,
                        "count": count,
                        "action": action,
                    },
                    source="order_manager",
                ))

                # If a BUY fill, capital is now deployed — no freed event.
                # If a SELL fill (exit/settlement), capital is freed.
                if action == "sell":
                    await self._bus.publish(Event(
                        type=EventType.CAPITAL_FREED,
                        data={
                            "ticker": ticker,
                            "freed_cents": count * price_cents,
                        },
                        source="order_manager",
                    ))

    async def handle_book_changed(self, event: Event) -> None:
        """
        React to BOOK_CHANGED events — SMART requoting engine (Phase 3).

        When the best bid/ask moves, we either:
        1. AMEND: requote at the new optimal price (spread-adaptive aggression)
        2. CANCEL: kill the order if the edge has evaporated

        Smart requoting improvements over Phase 2 basic:
        - Edge-aware cancel: if the new book implies our edge is gone, cancel
        - Spread-adaptive aggression: wider spreads → more aggressive improvement
        - Fill probability aware: skip requoting near-stale orders (let them cancel)
        - Detailed metrics tracking for every decision
        """
        data = event.data
        ticker = data.get("ticker", "")
        new_yes_bid = data.get("yes_bid", 0.0)
        new_yes_ask = data.get("yes_ask", 0.0)
        new_no_bid = data.get("no_bid", 0.0)
        new_no_ask = data.get("no_ask", 0.0)

        if not ticker or not USE_MAKER_ORDERS:
            return

        # Find resting orders for this ticker
        orders_for_ticker = [
            (oid, info) for oid, info in self.pending_orders.items()
            if info.get("ticker") == ticker
        ]
        if not orders_for_ticker:
            return

        # Compute the current spread in cents for aggression lookup
        if new_yes_ask > 0 and new_yes_bid > 0:
            spread_cents = max(1, int((new_yes_ask - new_yes_bid) * 100))
        else:
            spread_cents = 5  # default assumption

        for order_id, info in orders_for_ticker:
            old_price = info.get("price_cents", 0)
            side = info.get("side", "yes")
            amend_count = info.get("amend_count", 0)
            placed_at = info.get("placed_at", 0)
            age_seconds = time.time() - placed_at if placed_at else 0

            # ── Phase 3: Edge-aware cancel ────────────────────────
            # If the book moved such that our predicted edge is now
            # below the cancel threshold, kill the order entirely.
            edge_ok = self._check_edge_still_valid(
                ticker, side, new_yes_bid, new_yes_ask, new_no_bid, new_no_ask,
            )
            if not edge_ok:
                # Edge evaporated — cancel the order
                await self._cancel_order_for_edge(order_id, ticker, side, old_price)
                continue

            # ── Phase 3: Skip near-stale orders ──────────────────
            # Don't waste amend API calls on orders about to be cancelled
            if age_seconds > FILL_PROB_DECAY_SECONDS:
                self._requote_stats["requotes_skipped_edge"] += 1
                continue

            if amend_count >= MAX_AMENDS_PER_ORDER:
                continue  # Don't over-amend

            # ── Phase 5: Fill probability gating ──────────────────
            # Query the fill predictor for this order's current context.
            # Very low fill prob → cancel early to free capital.
            # Moderate fill prob → be more aggressive with price improvement.
            fill_prob_boost = 0
            if self._fill_pred and self._fill_pred.total_observations >= 30:
                fp = self.get_fill_probability(
                    side=side,
                    price_cents=old_price,
                    spread_cents=spread_cents,
                    mid_cents=info.get("mid_cents", 50),
                    volume=info.get("volume", 0),
                    open_interest=info.get("open_interest", 0),
                    hours_to_expiry=max(0.1, info.get("hours_to_expiry", 24.0)),
                    amend_count=amend_count,
                )
                if fp < 0.15:
                    # Very low fill probability — cancel early
                    await self._cancel_order_for_edge(order_id, ticker, side, old_price)
                    continue
                elif fp < 0.35:
                    # Low fill prob — boost aggression by 1¢
                    fill_prob_boost = 1

            # ── Phase 3: Spread-adaptive requote price ────────────
            new_price = self._compute_smart_requote_price(
                side, new_yes_bid, new_yes_ask, new_no_bid, new_no_ask,
                spread_cents,
            )
            # Phase 5: apply fill-prob aggression boost
            if fill_prob_boost and new_price > 0 and new_price < 99:
                if side == "yes":
                    ask_cents = int(new_yes_ask * 100) if new_yes_ask > 0 else 99
                    new_price = min(new_price + fill_prob_boost, ask_cents - 1)
                else:
                    na_cents = int(new_no_ask * 100) if new_no_ask > 0 else 99
                    new_price = min(new_price + fill_prob_boost, na_cents - 1)

            if new_price <= 0 or new_price >= 100:
                continue

            delta = abs(new_price - old_price)
            if delta < MIN_AMEND_DELTA_CENTS:
                self._requote_stats["requotes_skipped_delta"] += 1
                continue  # Not worth amending

            # Amend the order
            self._requote_stats["requotes_attempted"] += 1
            success = await self._amend_order(order_id, side, new_price)
            if success:
                old_count = info.get("count", 1)
                info["price_cents"] = new_price
                info["amend_count"] = amend_count + 1
                self.fill_rate_stats["amended"] += 1
                self._requote_stats["requotes_succeeded"] += 1

                # Phase 3+4: update capital reservation
                if self._capital:
                    self._capital.on_order_amended(
                        order_id, new_cost_cents=old_count * new_price,
                    )

                if self._bus:
                    await self._bus.publish(Event(
                        type=EventType.ORDER_AMENDED,
                        data={
                            "order_id": order_id,
                            "ticker": ticker,
                            "old_price_cents": old_price,
                            "new_price_cents": new_price,
                            "side": side,
                            "amend_count": info["amend_count"],
                            "spread_cents": spread_cents,
                        },
                        source="order_manager",
                    ))

    def _check_edge_still_valid(
        self,
        ticker: str,
        side: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float,
        no_ask: float,
    ) -> bool:
        """
        Check if the model's edge is still valid given the new book.

        Uses the FeatureEngine + cached market data to re-evaluate
        the signal. If edge is below the cancel threshold, return False.

        This avoids holding orders when the market has moved against us.
        """
        try:
            from app.pipeline import market_cache
            market = market_cache.get(ticker)
            if not market:
                return True  # Can't evaluate — keep the order

            features = self._features.compute(market)
            mid = features.midpoint
            if mid <= 0 or mid >= 1:
                return True

            # Quick edge estimation from the new book prices
            if side == "yes":
                our_price = yes_bid + 0.01 if yes_bid > 0 else mid
                # Edge = P(yes) - cost. If cost exceeds midpoint, edge is likely gone.
                implied_edge = mid - our_price
            else:
                our_price = no_bid + 0.01 if no_bid > 0 else (1.0 - mid)
                implied_edge = (1.0 - mid) - our_price

            # If the implied edge from the new book is below threshold → cancel
            if implied_edge < REQUOTE_EDGE_CANCEL_THRESHOLD:
                return False

            return True
        except Exception:
            return True  # On any error, keep the order (conservative)

    async def _cancel_order_for_edge(
        self,
        order_id: str,
        ticker: str,
        side: str,
        old_price: int,
    ) -> None:
        """Cancel an order because the edge has evaporated."""
        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return
            await _st.kalshi_api.orders.cancel_order(order_id)

            self.fill_rate_stats["edge_cancelled"] += 1
            self._requote_stats["requotes_cancelled_edge"] += 1

            # Phase 5: record cancel observation before removing
            info = self.pending_orders.get(order_id, {})
            self._record_fill_observation(info, filled=False)

            self.pending_orders.pop(order_id, None)

            # Phase 3+4: release reserved capital
            if self._capital:
                self._capital.on_order_cancelled(order_id)

            log.info("🧟❌ EDGE CANCEL",
                     order_id=order_id, ticker=ticker,
                     side=side, old_price=f"{old_price}¢")

            if self._bus:
                await self._bus.publish(Event(
                    type=EventType.ORDER_CANCELLED,
                    data={
                        "order_id": order_id,
                        "ticker": ticker,
                        "reason": "edge_evaporated",
                        "cancelled_count": 1,
                    },
                    source="order_manager",
                ))
        except Exception as e:
            log.debug("edge_cancel_failed", order_id=order_id, error=str(e))

    async def _amend_order(
        self,
        order_id: str,
        side: str,
        new_price_cents: int,
    ) -> bool:
        """
        Call Kalshi amend_order API to update a resting order's price.

        Returns True on success.
        """
        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return False

            if side == "yes":
                await _st.kalshi_api.orders.amend_order(
                    order_id, yes_price=new_price_cents,
                )
            else:
                await _st.kalshi_api.orders.amend_order(
                    order_id, no_price=new_price_cents,
                )

            log.info("🧟📝 ORDER AMENDED",
                     order_id=order_id, side=side,
                     new_price=f"{new_price_cents}¢")
            return True
        except Exception as e:
            log.debug("amend_order_failed",
                      order_id=order_id, error=str(e))
            return False

    @staticmethod
    def _compute_requote_price(
        side: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float,
        no_ask: float,
    ) -> int:
        """
        Compute new maker price given updated L1 book.

        Strategy: bid+1¢ (improve queue position while staying maker).
        Never cross the spread (that would make us a taker = 7¢ fee).
        """
        if side == "yes":
            bid = yes_bid if yes_bid > 0 else 0.01
            ask = yes_ask if yes_ask > 0 else 0.99
            # Place at bid+1¢, but never at or above ask
            price_frac = min(bid + 0.01, ask - 0.01)
        else:
            nb = no_bid if no_bid > 0 else 0.01
            na = no_ask if no_ask > 0 else 0.99
            price_frac = min(nb + 0.01, na - 0.01)

        return max(1, min(99, int(price_frac * 100)))

    @staticmethod
    def _compute_smart_requote_price(
        side: str,
        yes_bid: float,
        yes_ask: float,
        no_bid: float,
        no_ask: float,
        spread_cents: int,
    ) -> int:
        """
        Phase 3: Spread-adaptive requote pricing.

        Unlike the basic _compute_requote_price (bid+1¢ always), this
        adapts aggression based on the spread width:

        - Tight spread (1-2¢): conservative (bid+0/+1¢)
        - Medium spread (3-5¢): moderate (bid+1-2¢)
        - Wide spread (6+¢): aggressive (bid+2-3¢) to improve fill rate

        The key insight: wider spreads mean more room to improve queue
        position while still staying well inside the ask (maker).
        """
        # Look up aggression level from spread
        aggression = 1  # default: bid+1¢
        for threshold in sorted(REQUOTE_AGGRESSION_BY_SPREAD.keys(), reverse=True):
            if spread_cents >= threshold:
                aggression = REQUOTE_AGGRESSION_BY_SPREAD[threshold]
                break

        if side == "yes":
            bid = yes_bid if yes_bid > 0 else 0.01
            ask = yes_ask if yes_ask > 0 else 0.99
            # Improve by aggression cents, but NEVER cross the ask
            price_frac = min(bid + aggression * 0.01, ask - 0.01)
        else:
            nb = no_bid if no_bid > 0 else 0.01
            na = no_ask if no_ask > 0 else 0.99
            price_frac = min(nb + aggression * 0.01, na - 0.01)

        return max(1, min(99, int(price_frac * 100)))

    # ── Phase 4: Fill Reconciliation ──────────────────────────────────

    async def reconcile_fills(self) -> dict[str, Any]:
        """
        Reconcile pending_orders with the exchange to detect missed fills.

        The WS bridge should catch most fills in real time, but WS
        disconnections or race conditions can cause misses. This method
        queries the Kalshi API for order status and updates our state.

        Returns a summary of reconciliation actions taken.
        """
        if not self.pending_orders:
            return {"checked": 0, "missed_fills": 0, "stale_removed": 0}

        try:
            from app.state import state as _st
            if not _st.kalshi_api:
                return {"checked": 0, "error": "no_api"}

            checked = 0
            missed_fills = 0
            stale_removed = 0
            order_ids = list(self.pending_orders.keys())

            for oid in order_ids:
                if oid not in self.pending_orders:
                    continue  # May have been removed during iteration

                try:
                    order = await _st.kalshi_api.orders.get_order(oid)
                    checked += 1

                    if not order:
                        # Order not found — likely already filled or cancelled
                        info = self.pending_orders.pop(oid, {})
                        stale_removed += 1
                        if self._capital:
                            self._capital.on_order_cancelled(oid)
                        continue

                    status = getattr(order, "status", "").lower()

                    if status in ("executed", "filled"):
                        # Missed fill! Update our state
                        info = self.pending_orders.pop(oid, {})
                        self.fill_rate_stats["filled"] += 1
                        missed_fills += 1

                        if self._capital:
                            self._capital.on_order_filled(oid)

                        log.warning("🧟🔍 MISSED FILL DETECTED",
                                    order_id=oid,
                                    ticker=info.get("ticker", "?"),
                                    price=f"{info.get('price_cents', 0)}¢")

                        if self._bus:
                            await self._bus.publish(Event(
                                type=EventType.ORDER_FILLED,
                                data={
                                    "order_id": oid,
                                    "ticker": info.get("ticker", ""),
                                    "price_cents": info.get("price_cents", 0),
                                    "count": info.get("count", 1),
                                    "source": "reconciliation",
                                },
                                source="order_manager",
                            ))

                    elif status in ("canceled", "cancelled", "expired"):
                        info = self.pending_orders.pop(oid, {})
                        stale_removed += 1
                        self.fill_rate_stats["cancelled"] += 1
                        if self._capital:
                            self._capital.on_order_cancelled(oid)

                except Exception:
                    pass  # Individual order lookup failure — skip

            if missed_fills > 0:
                log.warning("🧟🔍 RECONCILIATION COMPLETE",
                            checked=checked, missed_fills=missed_fills,
                            stale_removed=stale_removed)

            return {
                "checked": checked,
                "missed_fills": missed_fills,
                "stale_removed": stale_removed,
            }
        except Exception as e:
            log.error("reconcile_fills_error", error=str(e))
            return {"checked": 0, "error": str(e)}
