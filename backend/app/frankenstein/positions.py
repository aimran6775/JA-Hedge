"""
Frankenstein — Position Manager. 🧟📊

Manages active positions: hold-or-exit decisions, stop-loss,
take-profit, trailing stops, edge reversal, time-based exits.

MAKER MODE: Hold to settlement (early exit incurs 7¢ taker fee).
TAKER MODE: Full active management with vol-adaptive stops.

Extracted from brain.py _manage_positions().
"""

from __future__ import annotations

import time
from typing import Any

from app.ai.features import FeatureEngine, MarketFeatures
from app.ai.models import Prediction, PredictionModel
from app.engine.advanced_risk import AdvancedRiskManager
from app.frankenstein.constants import (
    TAKER_FEE_CENTS,
    USE_MAKER_ORDERS,
)
from app.frankenstein.event_bus import Event, EventBus, EventType
from app.frankenstein.order_manager import OrderManager
from app.frankenstein.strategy import AdaptiveStrategy
from app.kalshi.models import Market
from app.logging_config import get_logger

log = get_logger("frankenstein.positions")


class PositionManager:
    """
    Decides whether to hold or exit each open position.

    Holds references to the model, features, strategy, and order_manager
    for evaluation and exit execution.
    """

    def __init__(
        self,
        model: PredictionModel,
        feature_engine: FeatureEngine,
        strategy: AdaptiveStrategy,
        order_manager: OrderManager,
        adv_risk: AdvancedRiskManager,
        event_bus: EventBus | None = None,
        *,
        memory: Any | None = None,
        sports_detector: Any | None = None,
        sports_risk: Any | None = None,
    ) -> None:
        self._model = model
        self._features = feature_engine
        self._strategy = strategy
        self._order_mgr = order_manager
        self._adv_risk = adv_risk
        self._bus = event_bus
        self._memory = memory

        # Sports (injected later by brain)
        self._sports_detector = sports_detector
        self._sports_risk = sports_risk

        # Trailing stop peaks: {_peak_pnl_TICKER: float}
        self._trailing_peaks: dict[str, float] = {}

        # Phase 34: Exit cooldown — prevent re-attempting exits on same ticker.
        # Maps ticker → timestamp of last exit attempt. If an exit order is
        # resting (not yet filled), don't create another one.
        self._exit_cooldown: dict[str, float] = {}
        self._EXIT_COOLDOWN_SECONDS = 300  # 5 minutes between exit attempts

    # ── Learning-Mode Detection ───────────────────────────────────────

    def _is_in_learning_mode(self) -> bool:
        """Check if we should be in learning mode based on actual training data."""
        if self._memory is None:
            return not self._model.is_trained  # fallback
        from app.frankenstein.constants import MIN_TRAINING_SAMPLES
        usable = 0
        for t in self._memory._trades:
            if t.market_result in ("yes", "no") and t.features:
                usable += 1
                if usable >= MIN_TRAINING_SAMPLES:
                    return False
        return True

    # ── Main Entry ────────────────────────────────────────────────────

    async def manage(self, markets: list[Market]) -> int:
        """
        Active position management — decide whether to hold or exit.

        MAKER MODE: Mostly hold to settlement, but allow selective exits
        when the expected savings exceed the 7¢ taker exit fee.
        Exit triggers in maker mode:
        - Edge reversal with HIGH confidence (model flipped → pay 7¢ to avoid total loss)
        - Large stop-loss (>30% loss → 7¢ fee < continued bleeding)
        - Near-expiry uncertain (price stuck at 40-60% with <30 min left)

        TAKER MODE: Full active management with vol-adaptive stops.

        Returns the number of exits executed.
        """
        from app.pipeline.portfolio_tracker import portfolio_state

        if not portfolio_state.positions:
            return 0

        params = self._strategy.params
        markets_by_ticker = {m.ticker: m for m in markets}
        exits_executed = 0

        # Phase 34: Clean expired exit cooldowns
        _now = time.time()
        self._exit_cooldown = {
            t: ts for t, ts in self._exit_cooldown.items()
            if _now - ts < self._EXIT_COOLDOWN_SECONDS
        }

        for ticker, pos in list(portfolio_state.positions.items()):
            market = markets_by_ticker.get(ticker)
            if not market:
                continue

            position_count = abs(pos.position or 0) if hasattr(pos, "position") else 0
            if position_count == 0:
                continue

            # Phase 34: Skip tickers with recent exit attempts to prevent
            # repeated exit spam (same ticker exited 5-9x per cycle).
            if ticker in self._exit_cooldown:
                continue

            # Phase 25: MINIMUM HOLD TIME — prevent churn loop.
            # Old behavior: enter → XGBoost retrains on cold-start → contradicts
            # → exit in 5-35 seconds → repeat.  Now: must hold for MIN_HOLD_MINUTES
            # before any exit evaluation.  In learning mode, hold to settlement.
            from app.frankenstein.constants import (
                MIN_HOLD_MINUTES_MAKER,
                MIN_HOLD_MINUTES_TAKER,
                LEARNING_MODE_CATASTROPHIC_STOP,
                USE_MAKER_ORDERS,
                MIN_TRAINING_SAMPLES,
            )
            entry_time = self._order_mgr.estimate_entry_time(ticker)
            if entry_time > 0:
                minutes_held = (time.time() - entry_time) / 60.0
                min_hold = MIN_HOLD_MINUTES_MAKER if USE_MAKER_ORDERS else MIN_HOLD_MINUTES_TAKER

                # Learning mode: hold everything to settlement for clean labels.
                # Only allow catastrophic stop-loss (-50%) as emergency exit.
                _is_learning = self._is_in_learning_mode()
                if _is_learning and USE_MAKER_ORDERS:
                    our_side_check = "yes" if (pos.position or 0) > 0 else "no"
                    features_check = self._features.compute(market)
                    mid_check = float(features_check.midpoint)
                    entry_price_check = self._order_mgr.estimate_entry_price(ticker)
                    if entry_price_check > 0 and mid_check > 0:
                        half_spread = float(features_check.spread) / 2.0
                        fee_per_side = 0.07  # TAKER_FEE_CENTS / 100
                        exit_cost = half_spread + fee_per_side
                        if our_side_check == "yes":
                            cv = max(mid_check - exit_cost, 0.01)
                            pnl_pct = (cv - entry_price_check) / entry_price_check
                        else:
                            cv = max((1.0 - mid_check) - exit_cost, 0.01)
                            pnl_pct = (cv - entry_price_check) / entry_price_check
                        if pnl_pct < LEARNING_MODE_CATASTROPHIC_STOP:
                            log.warning("learning_mode_catastrophic_exit",
                                        ticker=ticker, pnl_pct=f"{pnl_pct:.1%}")
                            # Fall through to exit logic
                        else:
                            continue  # Hold to settlement — clean training data
                    else:
                        continue  # Can't compute PnL — hold

                # Normal mode: enforce minimum hold time
                elif minutes_held < min_hold:
                    continue  # Too early to evaluate exit

            our_side = "yes" if (pos.position or 0) > 0 else "no"
            features = self._features.compute(market)
            prediction = self._model.predict(features)

            mid = float(features.midpoint)
            if mid <= 0 or mid >= 1:
                continue

            entry_price = self._order_mgr.estimate_entry_price(ticker)
            if entry_price <= 0:
                continue

            # Current value — fee-aware
            half_spread = float(features.spread) / 2.0
            fee_per_side = TAKER_FEE_CENTS / 100.0  # 0.07
            exit_cost = half_spread + fee_per_side

            if our_side == "yes":
                current_value = max(mid - exit_cost, 0.01)
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0
            else:
                current_value = max((1.0 - mid) - exit_cost, 0.01)
                unrealized_pnl_pct = (current_value - entry_price) / entry_price if entry_price > 0 else 0

            if USE_MAKER_ORDERS:
                should_exit, exit_reason = self._evaluate_maker_exit(
                    ticker, market, features, prediction, our_side,
                    unrealized_pnl_pct, mid, params,
                )
            else:
                should_exit, exit_reason = self._evaluate_exit(
                    ticker, market, features, prediction, our_side,
                    unrealized_pnl_pct, mid, params,
                )

            if should_exit:
                # Clean trailing stop data
                self._trailing_peaks.pop(f"_peak_pnl_{ticker}", None)

                result = await self._order_mgr.execute_exit(
                    market=market, side=our_side,
                    count=position_count, reason=exit_reason,
                )
                # Phase 34: Always record cooldown on exit attempt, even if
                # the order rests unfilled, to prevent re-exit spam.
                self._exit_cooldown[ticker] = time.time()
                if result and result.success:
                    exits_executed += 1
                    self._adv_risk.remove_position(ticker)
                    if self._sports_risk:
                        self._sports_risk.remove_position(ticker)

        if exits_executed > 0:
            log.info("🧟📤 EXITS", count=exits_executed)

        return exits_executed

    # ── Maker Mode Exit Logic ─────────────────────────────────────────

    def _evaluate_maker_exit(
        self,
        ticker: str,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        our_side: str,
        unrealized_pnl_pct: float,
        mid: float,
        params: Any,
    ) -> tuple[bool, str]:
        """
        Selective exit logic for MAKER MODE positions.

        We mostly hold to settlement (0¢ fees) but pay the 7¢ taker fee
        to exit when the EXPECTED LOSS from holding exceeds the 7¢ cost.

        The 7¢ fee as fraction of a typical 30-50¢ position = 14-23%.
        So we only exit when expected loss > ~20%.
        """
        taker_fee_pct = TAKER_FEE_CENTS / 100.0  # 0.07

        # ── Large stop-loss: loss already > 30% ──────────
        # If we've already lost 30%+, paying 7¢ to stop the bleeding
        # is better than potentially losing 100%.
        if unrealized_pnl_pct < -0.30:
            return True, f"maker_stop_loss ({unrealized_pnl_pct:.1%} < -30%)"

        # ── Edge reversal with VERY HIGH confidence ─────────
        # Phase 25: Raised from 0.80→0.90 confidence threshold.
        # The old 0.80 threshold caused churn: untrained model would
        # reach 0.80 confidence on garbage predictions and trigger exit.
        # Now requires 0.90 + model must actually be trained on real data.
        if not self._is_in_learning_mode():
            if our_side == "yes" and prediction.side == "no" and prediction.confidence > 0.90:
                # Expected loss from holding = mid probability the YES side loses
                expected_loss = 1.0 - mid  # probability we lose entire cost
                if expected_loss > 0.65:  # >65% chance of total loss (was 60%)
                    return True, f"maker_edge_reversal (model says NO @ {prediction.confidence:.2f}, loss_prob={expected_loss:.0%})"

            if our_side == "no" and prediction.side == "yes" and prediction.confidence > 0.90:
                expected_loss = mid
                if expected_loss > 0.65:
                    return True, f"maker_edge_reversal (model says YES @ {prediction.confidence:.2f}, loss_prob={expected_loss:.0%})"

        # ── Near-expiry uncertain ─────────────────────────
        # Market expires in <20 min, price is stuck in uncertain zone.
        # Better to take 7¢ hit than gamble on a coin flip.
        if features.hours_to_expiry < 0.33:  # <20 min
            if 0.35 < mid < 0.65:
                return True, f"maker_near_expiry_uncertain ({features.hours_to_expiry:.1f}h, mid={mid:.0%})"

        # ── Winning position near expiry: lock in gains ───
        # If we're up significantly and market is nearing expiry,
        # lock in gains rather than risk reversal.
        if features.hours_to_expiry < 1.0 and unrealized_pnl_pct > 0.40:
            return True, f"maker_lock_gains ({unrealized_pnl_pct:.1%} profit, {features.hours_to_expiry:.1f}h left)"

        # ── Phase 31: Intelligence-driven exit ────────────
        # If external sources (Polymarket, Vegas, news) strongly disagree
        # with our position, pay the 7¢ fee to exit.
        try:
            from app.frankenstein.arb_engine import arb_scanner
            arb_signals = arb_scanner._last_signals
            if ticker in arb_signals:
                arb = arb_signals[ticker]
                # If arb says opposite side with large edge, exit
                if arb.side != our_side and arb.abs_edge > 0.10 and arb.confidence > 0.75:
                    return True, (
                        f"maker_intel_exit ({arb.source} says {arb.side} "
                        f"@ {arb.external_prob:.0%} vs Kalshi {arb.kalshi_prob:.0%}, "
                        f"edge={arb.edge:+.1%})"
                    )
        except Exception:
            pass

        # ── Phase 31: Momentum exit ───────────────────────
        # If price is moving strongly against us (3+ consecutive moves
        # in wrong direction), exit to prevent further loss.
        try:
            hist = self._features._histories.get(ticker)
            if hist and len(hist.prices) >= 5:
                recent = list(hist.prices)[-5:]
                if our_side == "yes":
                    # Price dropping = bad for YES
                    drops = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i-1])
                    if drops >= 4 and unrealized_pnl_pct < -0.15:
                        return True, f"maker_momentum_exit (4+ consecutive drops, pnl={unrealized_pnl_pct:.1%})"
                else:
                    # Price rising = bad for NO
                    rises = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
                    if rises >= 4 and unrealized_pnl_pct < -0.15:
                        return True, f"maker_momentum_exit (4+ consecutive rises, pnl={unrealized_pnl_pct:.1%})"
        except Exception:
            pass

        return False, ""

    # ── Exit Logic ────────────────────────────────────────────────────

    def _evaluate_exit(
        self,
        ticker: str,
        market: Market,
        features: MarketFeatures,
        prediction: Prediction,
        our_side: str,
        unrealized_pnl_pct: float,
        mid: float,
        params: Any,
    ) -> tuple[bool, str]:
        """Evaluate all exit conditions. Returns (should_exit, reason)."""

        # ── Stop-loss ─────────────────────────────────────
        stop_loss_pct = getattr(params, "stop_loss_pct", 0.15) or 0.15

        # Vol-adaptive: scale by market volatility
        vol_20 = getattr(features, "volatility_20", 0.0) or 0.0
        if vol_20 > 0.03:
            vol_scale = max(0.7, 1.0 - (vol_20 - 0.03) * 10.0)
            stop_loss_pct *= vol_scale
        elif 0 < vol_20 < 0.01:
            stop_loss_pct *= 1.3

        # Sports: tighter stop
        if self._sports_detector and self._sports_risk:
            info = self._sports_detector.detect(market)
            if info.is_sports:
                stop_loss_pct = self._sports_risk.get_stop_loss(info.is_live)

        # Tighter near expiry
        if features.hours_to_expiry < 4:
            stop_loss_pct *= 0.75

        if unrealized_pnl_pct < -stop_loss_pct:
            return True, f"stop_loss ({unrealized_pnl_pct:.1%} < -{stop_loss_pct:.1%})"

        # ── Take-profit ───────────────────────────────────
        take_profit_pct = getattr(params, "take_profit_pct", 0.20) or 0.20
        if features.hours_to_expiry < 4:
            take_profit_pct *= 0.70
        if unrealized_pnl_pct > take_profit_pct:
            return True, f"take_profit ({unrealized_pnl_pct:.1%} > {take_profit_pct:.1%})"

        # ── Trailing stop ─────────────────────────────────
        if unrealized_pnl_pct > 0.10:
            peak_key = f"_peak_pnl_{ticker}"
            prev_peak = self._trailing_peaks.get(peak_key, 0.0)
            current_peak = max(prev_peak, unrealized_pnl_pct)
            self._trailing_peaks[peak_key] = current_peak

            trailing_stop = current_peak * 0.50
            if unrealized_pnl_pct < trailing_stop:
                return True, (
                    f"trailing_stop (peak {current_peak:.1%}, "
                    f"trail {trailing_stop:.1%}, current {unrealized_pnl_pct:.1%})"
                )

        # ── Edge reversal ─────────────────────────────────
        if our_side == "yes" and prediction.side == "no" and prediction.confidence > 0.75:
            return True, f"edge_reversal (now predicts NO @ {prediction.confidence:.2f})"
        if our_side == "no" and prediction.side == "yes" and prediction.confidence > 0.75:
            return True, f"edge_reversal (now predicts YES @ {prediction.confidence:.2f})"

        # ── Near-expiry liquidation ───────────────────────
        if features.hours_to_expiry < 0.5 and 0.30 < mid < 0.70:
            return True, f"near_expiry_uncertain ({features.hours_to_expiry:.1f}h)"

        # ── Time-based exit (stale positions) ─────────────
        entry_time = self._order_mgr.estimate_entry_time(ticker)
        hours_held = (time.time() - entry_time) / 3600.0 if entry_time > 0 else 0
        if hours_held > 8.0 and 0.25 < mid < 0.75:
            return True, f"stale_position ({hours_held:.1f}h held, price uncertain at {mid:.0%})"

        return False, ""
