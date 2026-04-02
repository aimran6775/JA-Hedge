"""
Frankenstein — Adaptive Strategy Engine.

Self-tuning trading parameters that adapt based on:
- Recent performance (win rate, Sharpe)
- Market regime (trending, mean-reverting, volatile, quiet)
- Model confidence calibration
- Risk conditions (drawdown, consecutive losses)

The strategy becomes more aggressive when winning and
more conservative when losing — like a sentient trader.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.frankenstein.memory import TradeMemory
from app.frankenstein.performance import PerformanceTracker, PerformanceSnapshot
from app.logging_config import get_logger

log = get_logger("frankenstein.strategy")


@dataclass
class StrategyParams:
    """Tunable strategy parameters — Frankenstein adjusts these live."""

    # Signal filters — MAKER-AWARE: edge only needs to beat spread (no fees)
    min_confidence: float = 0.45     # Slightly lower for maker (more volume)
    min_edge: float = 0.05           # 5% min edge — just beat spread (no 14¢ fee overhead)

    # Position sizing — small and cautious
    kelly_fraction: float = 0.15     # Conservative Kelly
    max_position_size: int = 5       # Slightly larger ok with 0 fees
    max_simultaneous_positions: int = 50   # Raised from 30 — position wall was blocking all new trades

    # Timing
    scan_interval: float = 30.0  # scan every 30s (was 45)

    # Risk overrides
    max_daily_loss: float = 150.0    # Higher cap — maker losses are just cost, no fee multiplier
    stop_loss_pct: float = 0.15      # Not used in maker mode (hold to settlement)
    take_profit_pct: float = 0.20    # Not used in maker mode (hold to settlement)

    # Model thresholds
    max_spread_cents: int = 15   # Tight spreads only
    min_volume: float = 15.0    # Need liquidity for maker fills
    min_hours_to_expiry: float = 1.0  # 1h minimum (maker orders need time to fill)

    # Aggression level (0.0 = ultra conservative, 1.0 = maximum aggression)
    aggression: float = 0.35         # Moderate (maker risk is lower)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class AdaptationEvent:
    """Record of a parameter adaptation."""
    timestamp: float = field(default_factory=time.time)
    parameter: str = ""
    old_value: float = 0.0
    new_value: float = 0.0
    reason: str = ""
    regime: str = ""


class AdaptiveStrategy:
    """
    Frankenstein's self-tuning strategy engine.

    Adjusts trading parameters based on:
    - Recent performance metrics
    - Market regime classification
    - Risk conditions
    - Model quality indicators
    """

    def __init__(
        self,
        memory: TradeMemory,
        performance: PerformanceTracker,
        *,
        base_params: StrategyParams | None = None,
        adaptation_interval: float = 900.0,  # 15 minutes
    ):
        self.memory = memory
        self.performance = performance
        self.params = base_params or StrategyParams()
        self.adaptation_interval = adaptation_interval

        # Defaults (never go below/above these) — MAKER-AWARE bounds
        self._MIN_CONFIDENCE = 0.35    # Lower floor — maker risk is lower
        self._MAX_CONFIDENCE = 0.58    # Tighter cap — 0.65 chokes trade volume
        self._MIN_EDGE = 0.03          # 3% min edge — maker has no fees
        self._MAX_EDGE = 0.10          # Cap at 10% — 0.15 was strangling trades
        self._MIN_KELLY = 0.06         # Floor at 6% — 5% starves sizing
        self._MAX_KELLY = 0.20         # Cap kelly at 20%
        self._MIN_AGGRESSION = 0.15    # Don't go too conservative
        self._MAX_AGGRESSION = 0.55    # Allow more aggression for maker

        # History
        self._adaptations: list[AdaptationEvent] = []
        self._last_adaptation: float = 0.0
        self._total_adaptations: int = 0

        # Enforce bounds on initial params (protects against stale persisted values)
        self._clamp_all_params()

        log.info("adaptive_strategy_initialized", params=self.params.to_dict())

    # ── Main Adaptation Loop ──────────────────────────────────────────

    def _clamp_all_params(self) -> None:
        """Enforce hard bounds on all tunable parameters.

        Called at init and after every adaptation cycle to guarantee
        no parameter ever escapes its declared min/max.
        """
        p = self.params
        p.min_confidence = max(self._MIN_CONFIDENCE, min(p.min_confidence, self._MAX_CONFIDENCE))
        p.min_edge = max(self._MIN_EDGE, min(p.min_edge, self._MAX_EDGE))
        p.kelly_fraction = max(self._MIN_KELLY, min(p.kelly_fraction, self._MAX_KELLY))
        p.aggression = max(self._MIN_AGGRESSION, min(p.aggression, self._MAX_AGGRESSION))

    def adapt(self, snapshot: PerformanceSnapshot | None = None) -> list[AdaptationEvent]:
        """
        Adapt strategy parameters based on current performance.

        Returns list of parameter changes made.
        """
        now = time.time()
        if now - self._last_adaptation < self.adaptation_interval:
            return []

        if snapshot is None:
            snapshot = self.performance.compute_snapshot()

        events: list[AdaptationEvent] = []

        # ── LEARNING MODE GUARD ──────────────────────────────────────
        # During the first 100 real trades, we have NO statistical basis
        # to adapt parameters.  Keep defaults and just trade.
        if snapshot.real_trades < 100:
            log.info(
                "strategy_learning_mode_skip_adaptation",
                real_trades=snapshot.real_trades,
                remaining=100 - snapshot.real_trades,
            )
            # Only compute aggression (cosmetic) — no param changes
            self._compute_aggression(snapshot)
            self._last_adaptation = now
            self._total_adaptations += 1
            return events
        # ─────────────────────────────────────────────────────────────

        # 1. Adapt based on regime
        events.extend(self._adapt_to_regime(snapshot))

        # 2. Adapt based on win rate
        events.extend(self._adapt_to_win_rate(snapshot))

        # 3. Adapt based on drawdown
        events.extend(self._adapt_to_drawdown(snapshot))

        # 4. Adapt based on model quality
        events.extend(self._adapt_to_model_quality(snapshot))

        # 5. Adapt based on consecutive losses
        events.extend(self._adapt_to_streaks(snapshot))

        # 6. Compute overall aggression
        self._compute_aggression(snapshot)

        self._last_adaptation = now
        self._total_adaptations += 1

        # Hard-clamp after all adaptations — belt + suspenders
        self._clamp_all_params()

        if events:
            self._adaptations.extend(events)
            log.info(
                "🧟 FRANKENSTEIN ADAPTED",
                changes=len(events),
                aggression=f"{self.params.aggression:.2f}",
                regime=snapshot.regime,
                params={e.parameter: e.new_value for e in events},
            )

        return events

    # ── Regime Adaptation ─────────────────────────────────────────────

    def _adapt_to_regime(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust parameters based on detected market regime."""
        events = []
        regime = snap.regime

        if regime == "volatile":
            # MAKER MODE: 0 fees, so volatile only needs slightly more edge.
            # Still reduce sizing — vol means more uncertainty.
            events.extend(self._adjust("min_confidence", 0.50, "volatile_regime"))
            events.extend(self._adjust("min_edge", 0.07, "volatile_regime"))
            events.extend(self._adjust("kelly_fraction", 0.08, "volatile_regime"))
            events.extend(self._adjust("max_position_size", 3, "volatile_regime"))

        elif regime == "quiet":
            # Quiet: loosen up, lean into volume. Maker = free trades.
            events.extend(self._adjust("min_confidence", 0.42, "quiet_regime"))
            events.extend(self._adjust("min_edge", 0.04, "quiet_regime"))
            events.extend(self._adjust("kelly_fraction", 0.15, "quiet_regime"))
            events.extend(self._adjust("max_position_size", 5, "quiet_regime"))

        elif regime == "trending":
            # Trending: ride the move. Maker = no fee drag.
            events.extend(self._adjust("min_confidence", 0.45, "trending_regime"))
            events.extend(self._adjust("min_edge", 0.05, "trending_regime"))
            events.extend(self._adjust("kelly_fraction", 0.12, "trending_regime"))

        elif regime == "mean_reverting":
            # Mean-revert: quick grabs. Small edge OK with maker fees=0.
            events.extend(self._adjust("min_confidence", 0.48, "mean_reverting_regime"))
            events.extend(self._adjust("min_edge", 0.05, "mean_reverting_regime"))
            events.extend(self._adjust("kelly_fraction", 0.10, "mean_reverting_regime"))

        return [e for e in events if e is not None]

    # ── Win Rate Adaptation ───────────────────────────────────────────

    def _adapt_to_win_rate(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Get more aggressive when winning, conservative when losing."""
        events = []

        if snap.real_trades < 30:
            return events  # Not enough data — learning mode

        if snap.win_rate > 0.55:
            # Winning: loosen entry, grow size
            events.extend(self._adjust("min_confidence", max(self.params.min_confidence - 0.02, self._MIN_CONFIDENCE), "high_win_rate"))
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.02, self._MAX_KELLY), "high_win_rate"))

        elif snap.win_rate < 0.25:
            # Only tighten on truly terrible win rate (<25%), not just below average
            # Smaller steps: 0.005 confidence, 0.002 edge, 0.005 kelly
            events.extend(self._adjust("min_confidence", min(self.params.min_confidence + 0.005, self._MAX_CONFIDENCE), "low_win_rate"))
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.002, self._MAX_EDGE), "low_win_rate"))
            events.extend(self._adjust("kelly_fraction", max(self.params.kelly_fraction - 0.005, self._MIN_KELLY), "low_win_rate"))

        return [e for e in events if e is not None]

    # ── Drawdown Adaptation ───────────────────────────────────────────

    def _adapt_to_drawdown(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Reduce exposure during drawdowns."""
        events = []

        if snap.current_drawdown < -15:  # Only react to meaningful drawdowns (>$15)
            severity = min(abs(snap.current_drawdown) / 100.0, 0.4)  # Gentler: max 40% reduction, scale over $100
            new_kelly = max(self.params.kelly_fraction * (1.0 - severity), self._MIN_KELLY)
            # NEVER reduce max_positions below 40 — otherwise open positions block all new trades
            new_positions = max(int(self.params.max_simultaneous_positions * (1.0 - severity)), 40)

            events.extend(self._adjust("kelly_fraction", new_kelly, f"drawdown_${abs(snap.current_drawdown):.0f}"))
            events.extend(self._adjust("max_simultaneous_positions", new_positions, f"drawdown_${abs(snap.current_drawdown):.0f}"))

        elif snap.current_drawdown > -5:
            # Restore defaults
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.02, 0.15), "recovery"))
            events.extend(self._adjust("max_simultaneous_positions", min(self.params.max_simultaneous_positions + 2, 50), "recovery"))

        return [e for e in events if e is not None]

    # ── Model Quality Adaptation ──────────────────────────────────────

    def _adapt_to_model_quality(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust based on model's prediction accuracy."""
        events = []

        if snap.real_trades < 100:
            return events  # Need substantial data before judging accuracy

        if snap.prediction_accuracy < 0.30:
            # Model is truly bad (<30%) — tighten slightly but not aggressively
            events.extend(self._adjust("min_confidence", 0.50, "poor_accuracy"))
            events.extend(self._adjust("min_edge", 0.06, "poor_accuracy"))
            events.extend(self._adjust("kelly_fraction", 0.10, "poor_accuracy"))

        elif snap.prediction_accuracy > 0.55:
            # Model is good — open up
            events.extend(self._adjust("min_confidence", 0.38, "good_accuracy"))
            events.extend(self._adjust("min_edge", 0.04, "good_accuracy"))

        # Confidence calibration: nudge edge slightly if overconfident
        if snap.confidence_calibration > 0.20:
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.005, self._MAX_EDGE), "poor_calibration"))

        return [e for e in events if e is not None]

    # ── Streak Adaptation ─────────────────────────────────────────────

    def _adapt_to_streaks(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """React to consecutive wins/losses.
        
        NOTE: This only fires AFTER learning mode (100+ real trades)
        because the main adapt() method returns early during learning.
        Even post-learning, we use bounded adjustments — never nuke params.
        """
        events = []

        if snap.consecutive_losses >= 5:
            # Scale back kelly gently — 0.01 per loss in streak
            reduction = 0.01 * (snap.consecutive_losses - 4)
            new_kelly = max(self.params.kelly_fraction - reduction, self._MIN_KELLY)
            events.extend(self._adjust("kelly_fraction", new_kelly, f"loss_streak_{snap.consecutive_losses}"))

            if snap.consecutive_losses >= 8:
                # Only tighten confidence after a long streak
                new_conf = min(self.params.min_confidence + 0.02, self._MAX_CONFIDENCE)
                events.extend(self._adjust("min_confidence", new_conf, "loss_streak_tighten"))

        # Always restore scan_interval toward baseline (don't let it bloat)
        if self.params.scan_interval > 30.0:
            new_scan = max(self.params.scan_interval - 3.0, 30.0)
            events.extend(self._adjust("scan_interval", new_scan, "scan_restore"))

        return [e for e in events if e is not None]

    # ── Aggression Score ──────────────────────────────────────────────

    def _compute_aggression(self, snap: PerformanceSnapshot) -> None:
        """Compute overall aggression level (0=conservative, 1=aggressive)."""
        score = 0.5  # Neutral

        # Win rate factor
        if snap.real_trades >= 10:
            score += (snap.win_rate - 0.5) * 0.3  # ±0.15

        # Drawdown factor
        if snap.current_drawdown < -20:
            score -= min(abs(snap.current_drawdown) / 200.0, 0.3)

        # Model accuracy factor
        if snap.real_trades >= 20:
            score += (snap.prediction_accuracy - 0.5) * 0.2  # ±0.10

        # Profit factor
        if snap.profit_factor > 2.0:
            score += 0.1
        elif snap.profit_factor < 0.5 and snap.real_trades >= 10:
            score -= 0.15

        # Clamp
        self.params.aggression = max(self._MIN_AGGRESSION, min(self._MAX_AGGRESSION, score))

    # ── Helpers ───────────────────────────────────────────────────────

    def _adjust(self, param: str, new_value: Any, reason: str) -> list[AdaptationEvent]:
        """Adjust a parameter and record the change.

        Phase 16: EMA-smooth changes to prevent oscillation.
        Instead of jumping directly to new_value, blend current → target
        with an EMA factor (alpha=0.3).  This means it takes ~3 adaptation
        cycles to converge on a new target, preventing whiplash between
        regime detections.
        """
        old_value = getattr(self.params, param, None)
        if old_value is None:
            return []

        # EMA smoothing for numeric parameters
        EMA_ALPHA = 0.3
        if isinstance(new_value, float) and isinstance(old_value, float):
            smoothed = old_value + EMA_ALPHA * (new_value - old_value)
            # Only record if actually changed (with tolerance)
            if abs(smoothed - old_value) < 0.001:
                return []
            new_value = smoothed
        elif isinstance(new_value, int) and isinstance(old_value, int):
            # For integers, use EMA then round
            smoothed = old_value + EMA_ALPHA * (new_value - old_value)
            smoothed_int = round(smoothed)
            if smoothed_int == old_value:
                return []
            new_value = smoothed_int
        elif new_value == old_value:
            return []

        setattr(self.params, param, new_value)

        event = AdaptationEvent(
            parameter=param,
            old_value=float(old_value) if isinstance(old_value, (int, float)) else 0.0,
            new_value=float(new_value) if isinstance(new_value, (int, float)) else 0.0,
            reason=reason,
        )

        return [event]

    def get_params(self) -> StrategyParams:
        """Get current strategy parameters."""
        return self.params

    def reset_to_defaults(self) -> None:
        """Reset all parameters to conservative defaults."""
        self.params = StrategyParams()
        self._adaptations.append(AdaptationEvent(
            parameter="ALL",
            reason="manual_reset",
        ))
        log.info("strategy_params_reset_to_defaults")

    # ── Statistics ────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Full adaptive strategy statistics."""
        return {
            "current_params": self.params.to_dict(),
            "aggression": f"{self.params.aggression:.2f}",
            "total_adaptations": self._total_adaptations,
            "recent_adaptations": [
                {
                    "time": a.timestamp,
                    "param": a.parameter,
                    "old": a.old_value,
                    "new": a.new_value,
                    "reason": a.reason,
                }
                for a in self._adaptations[-20:]
            ],
        }
