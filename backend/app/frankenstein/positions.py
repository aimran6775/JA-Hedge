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
        sports_detector: Any | None = None,
        sports_risk: Any | None = None,
    ) -> None:
        self._model = model
        self._features = feature_engine
        self._strategy = strategy
        self._order_mgr = order_manager
        self._adv_risk = adv_risk
        self._bus = event_bus

        # Sports (injected later by brain)
        self._sports_detector = sports_detector
        self._sports_risk = sports_risk

        # Trailing stop peaks: {_peak_pnl_TICKER: float}
        self._trailing_peaks: dict[str, float] = {}

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

        for ticker, pos in list(portfolio_state.positions.items()):
            market = markets_by_ticker.get(ticker)
            if not market:
                continue

            position_count = abs(pos.position or 0) if hasattr(pos, "position") else 0
            if position_count == 0:
                continue

            our_side = "yes" if (pos.position or 0) > 0 else "no"
            features = self._features.compute(market)
            prediction = self._model.predict(features)

            mid = features.midpoint
            if mid <= 0 or mid >= 1:
                continue

            entry_price = self._order_mgr.estimate_entry_price(ticker)
            if entry_price <= 0:
                continue

            # Current value — fee-aware
            half_spread = features.spread / 2.0
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

        # ── Edge reversal with HIGH confidence ────────────
        # If the model has FLIPPED with very high confidence,
        # our original thesis is dead. Pay 7¢ to exit.
        if our_side == "yes" and prediction.side == "no" and prediction.confidence > 0.80:
            # Expected loss from holding = mid probability the YES side loses
            expected_loss = 1.0 - mid  # probability we lose entire cost
            if expected_loss > 0.60:  # >60% chance of total loss
                return True, f"maker_edge_reversal (model says NO @ {prediction.confidence:.2f}, loss_prob={expected_loss:.0%})"

        if our_side == "no" and prediction.side == "yes" and prediction.confidence > 0.80:
            expected_loss = mid
            if expected_loss > 0.60:
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
