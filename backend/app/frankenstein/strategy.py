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

    # Signal filters (lowered for heuristic/untrained model to generate trades)
    min_confidence: float = 0.52
    min_edge: float = 0.02

    # Position sizing
    kelly_fraction: float = 0.25
    max_position_size: int = 10
    max_simultaneous_positions: int = 20

    # Timing
    scan_interval: float = 30.0  # seconds between scans

    # Risk overrides
    max_daily_loss: float = 50.0
    stop_loss_pct: float = 0.15
    take_profit_pct: float = 0.30

    # Model thresholds
    max_spread_cents: int = 15   # Allow wider spreads in paper mode
    min_volume: float = 10.0     # Allow lower-volume markets too
    min_hours_to_expiry: float = 0.5

    # Aggression level (0.0 = ultra conservative, 1.0 = maximum aggression)
    aggression: float = 0.5

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

        # Defaults (never go below/above these)
        self._MIN_CONFIDENCE = 0.50
        self._MAX_CONFIDENCE = 0.85
        self._MIN_EDGE = 0.02
        self._MAX_EDGE = 0.15
        self._MIN_KELLY = 0.05
        self._MAX_KELLY = 0.50
        self._MIN_AGGRESSION = 0.1
        self._MAX_AGGRESSION = 0.9

        # History
        self._adaptations: list[AdaptationEvent] = []
        self._last_adaptation: float = 0.0
        self._total_adaptations: int = 0

        log.info("adaptive_strategy_initialized", params=self.params.to_dict())

    # ── Main Adaptation Loop ──────────────────────────────────────────

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
            # High vol: widen thresholds, reduce size
            events.extend(self._adjust("min_confidence", 0.70, "volatile_regime"))
            events.extend(self._adjust("min_edge", 0.08, "volatile_regime"))
            events.extend(self._adjust("kelly_fraction", 0.15, "volatile_regime"))
            events.extend(self._adjust("max_position_size", 5, "volatile_regime"))

        elif regime == "quiet":
            # Low vol: tighten entry, can be more aggressive on size
            events.extend(self._adjust("min_confidence", 0.55, "quiet_regime"))
            events.extend(self._adjust("min_edge", 0.04, "quiet_regime"))
            events.extend(self._adjust("kelly_fraction", 0.35, "quiet_regime"))
            events.extend(self._adjust("max_position_size", 15, "quiet_regime"))

        elif regime == "trending":
            # Trending: follow momentum, moderate sizing
            events.extend(self._adjust("min_confidence", 0.58, "trending_regime"))
            events.extend(self._adjust("min_edge", 0.05, "trending_regime"))
            events.extend(self._adjust("kelly_fraction", 0.30, "trending_regime"))

        elif regime == "mean_reverting":
            # Mean-revert: tighter entry, higher confidence required
            events.extend(self._adjust("min_confidence", 0.65, "mean_reverting_regime"))
            events.extend(self._adjust("min_edge", 0.06, "mean_reverting_regime"))
            events.extend(self._adjust("kelly_fraction", 0.20, "mean_reverting_regime"))

        return [e for e in events if e is not None]

    # ── Win Rate Adaptation ───────────────────────────────────────────

    def _adapt_to_win_rate(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Get more aggressive when winning, conservative when losing."""
        events = []

        if snap.total_trades < 10:
            return events  # Not enough data

        if snap.win_rate > 0.65:
            # Winning streak: loosen entry, increase size
            events.extend(self._adjust("min_confidence", max(self.params.min_confidence - 0.02, self._MIN_CONFIDENCE), "high_win_rate"))
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.03, self._MAX_KELLY), "high_win_rate"))

        elif snap.win_rate < 0.40:
            # Losing: tighten everything
            events.extend(self._adjust("min_confidence", min(self.params.min_confidence + 0.03, self._MAX_CONFIDENCE), "low_win_rate"))
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.01, self._MAX_EDGE), "low_win_rate"))
            events.extend(self._adjust("kelly_fraction", max(self.params.kelly_fraction - 0.05, self._MIN_KELLY), "low_win_rate"))

        return [e for e in events if e is not None]

    # ── Drawdown Adaptation ───────────────────────────────────────────

    def _adapt_to_drawdown(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Reduce exposure during drawdowns."""
        events = []

        if snap.current_drawdown < -20:  # > $20 drawdown
            severity = min(abs(snap.current_drawdown) / 100.0, 0.5)  # 0-0.5 scale
            new_kelly = max(self.params.kelly_fraction * (1.0 - severity), self._MIN_KELLY)
            new_positions = max(int(self.params.max_simultaneous_positions * (1.0 - severity)), 3)

            events.extend(self._adjust("kelly_fraction", new_kelly, f"drawdown_${abs(snap.current_drawdown):.0f}"))
            events.extend(self._adjust("max_simultaneous_positions", new_positions, f"drawdown_${abs(snap.current_drawdown):.0f}"))

        elif snap.current_drawdown > -5:  # Small or no drawdown
            # Slowly restore defaults
            events.extend(self._adjust("kelly_fraction", min(self.params.kelly_fraction + 0.01, 0.25), "recovery"))
            events.extend(self._adjust("max_simultaneous_positions", min(self.params.max_simultaneous_positions + 1, 20), "recovery"))

        return [e for e in events if e is not None]

    # ── Model Quality Adaptation ──────────────────────────────────────

    def _adapt_to_model_quality(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """Adjust based on model's prediction accuracy."""
        events = []

        if snap.total_trades < 20:
            return events

        if snap.prediction_accuracy < 0.45:
            # Model is barely better than coin flip — be very careful
            events.extend(self._adjust("min_confidence", 0.75, "poor_accuracy"))
            events.extend(self._adjust("min_edge", 0.10, "poor_accuracy"))
            events.extend(self._adjust("kelly_fraction", 0.10, "poor_accuracy"))

        elif snap.prediction_accuracy > 0.60:
            # Model is good — trust it more
            events.extend(self._adjust("min_confidence", 0.55, "good_accuracy"))
            events.extend(self._adjust("min_edge", 0.04, "good_accuracy"))

        # Confidence calibration: if model is overconfident, require more edge
        if snap.confidence_calibration > 0.15:
            events.extend(self._adjust("min_edge", min(self.params.min_edge + 0.02, self._MAX_EDGE), "poor_calibration"))

        return [e for e in events if e is not None]

    # ── Streak Adaptation ─────────────────────────────────────────────

    def _adapt_to_streaks(self, snap: PerformanceSnapshot) -> list[AdaptationEvent]:
        """React to consecutive wins/losses."""
        events = []

        if snap.consecutive_losses >= 3:
            # Scale back proportionally to streak length
            reduction = 0.05 * snap.consecutive_losses
            new_kelly = max(self.params.kelly_fraction - reduction, self._MIN_KELLY)
            events.extend(self._adjust("kelly_fraction", new_kelly, f"loss_streak_{snap.consecutive_losses}"))

            if snap.consecutive_losses >= 5:
                events.extend(self._adjust("min_confidence", 0.80, "major_loss_streak"))
                events.extend(self._adjust("scan_interval", 120.0, "major_loss_streak"))

        return [e for e in events if e is not None]

    # ── Aggression Score ──────────────────────────────────────────────

    def _compute_aggression(self, snap: PerformanceSnapshot) -> None:
        """Compute overall aggression level (0=conservative, 1=aggressive)."""
        score = 0.5  # Neutral

        # Win rate factor
        if snap.total_trades >= 10:
            score += (snap.win_rate - 0.5) * 0.3  # ±0.15

        # Drawdown factor
        if snap.current_drawdown < -20:
            score -= min(abs(snap.current_drawdown) / 200.0, 0.3)

        # Model accuracy factor
        if snap.total_trades >= 20:
            score += (snap.prediction_accuracy - 0.5) * 0.2  # ±0.10

        # Profit factor
        if snap.profit_factor > 2.0:
            score += 0.1
        elif snap.profit_factor < 0.5 and snap.total_trades >= 10:
            score -= 0.15

        # Clamp
        self.params.aggression = max(self._MIN_AGGRESSION, min(self._MAX_AGGRESSION, score))

    # ── Helpers ───────────────────────────────────────────────────────

    def _adjust(self, param: str, new_value: Any, reason: str) -> list[AdaptationEvent]:
        """Adjust a parameter and record the change."""
        old_value = getattr(self.params, param, None)
        if old_value is None:
            return []

        # Only record if actually changed (with tolerance)
        if isinstance(new_value, float) and isinstance(old_value, float):
            if abs(new_value - old_value) < 0.001:
                return []
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
