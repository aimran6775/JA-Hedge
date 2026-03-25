"""
Frankenstein — Performance Tracker.

Tracks every metric that matters: Sharpe ratio, drawdown,
win rate by category, confidence calibration, model accuracy
over time. This is Frankenstein's self-awareness system.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.frankenstein.memory import TradeMemory, TradeOutcome, TradeRecord
from app.logging_config import get_logger

log = get_logger("frankenstein.performance")


@dataclass
class PerformanceSnapshot:
    """Point-in-time performance metrics."""
    timestamp: float = field(default_factory=time.time)

    # Returns
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    hourly_pnl: float = 0.0

    # Rates
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross_profit / gross_loss
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # Risk
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0

    # Model quality
    prediction_accuracy: float = 0.0
    avg_confidence: float = 0.0
    confidence_calibration: float = 0.0  # How well confidence matches reality
    edge_capture: float = 0.0           # Actual edge / predicted edge

    # Volume
    total_trades: int = 0
    real_trades: int = 0            # Excludes bootstrap/synthetic trades
    bootstrap_trades: int = 0       # Synthetic trades (training data only)
    trades_today: int = 0
    trades_this_hour: int = 0
    unique_markets: int = 0

    # Regime
    regime: str = "unknown"  # "trending", "mean_reverting", "volatile", "quiet"
    model_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class PerformanceTracker:
    """
    Frankenstein's self-awareness: tracks performance over time
    and detects when the model is degrading or thriving.
    """

    def __init__(self, memory: TradeMemory, snapshot_interval: int = 300):
        self.memory = memory
        self.snapshot_interval = snapshot_interval  # seconds

        # History
        self._snapshots: deque[PerformanceSnapshot] = deque(maxlen=10_000)
        self._pnl_history: deque[float] = deque(maxlen=50_000)
        self._daily_returns: deque[float] = deque(maxlen=365)

        # Drawdown tracking
        self._peak_equity: float = 0.0
        self._equity_curve: deque[float] = deque(maxlen=50_000)

        # Consecutive loss tracking
        self._current_streak: int = 0      # negative = losses, positive = wins
        self._max_loss_streak: int = 0

        # Confidence calibration buckets
        self._calibration_buckets: dict[str, dict[str, int]] = {
            f"{i/10:.1f}-{(i+1)/10:.1f}": {"total": 0, "correct": 0}
            for i in range(10)
        }

        # Category performance
        self._by_category: dict[str, dict[str, float]] = {}

        log.info("performance_tracker_initialized")

    # ── Core Metrics ──────────────────────────────────────────────────

    def compute_snapshot(self) -> PerformanceSnapshot:
        """Compute a full performance snapshot from current memory."""
        now = time.time()
        trades = self.memory.get_recent_trades(n=100_000)
        all_resolved = [t for t in trades if t.outcome not in (TradeOutcome.PENDING, TradeOutcome.CANCELLED)]

        # Separate bootstrap/synthetic trades from real ones — bootstrap data
        # is only useful for initial model training, not performance tracking
        resolved = [t for t in all_resolved if not t.model_version.startswith("bootstrap")]

        if not resolved:
            snap = PerformanceSnapshot(
                timestamp=now,
                total_trades=len(all_resolved),  # includes bootstrap (for reference)
                real_trades=0,
                bootstrap_trades=len(all_resolved),
            )
            self._snapshots.append(snap)
            return snap

        # P&L stats
        pnls = [t.pnl_cents / 100.0 for t in resolved]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe & Sortino (annualized, assuming ~6.5 trading hours/day)
        if len(pnls) > 1:
            returns = np.array(pnls)
            mean_r = np.mean(returns)
            std_r = np.std(returns)
            downside = returns[returns < 0]
            downside_std = np.std(downside) if len(downside) > 1 else 1.0

            sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
            sortino = (mean_r / downside_std) * math.sqrt(252) if downside_std > 0 else 0.0
        else:
            sharpe = sortino = 0.0

        # Drawdown
        equity_curve = np.cumsum(pnls)
        if len(equity_curve) > 0:
            running_max = np.maximum.accumulate(equity_curve)
            drawdowns = equity_curve - running_max
            max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
            current_drawdown = float(drawdowns[-1]) if len(drawdowns) > 0 else 0.0
        else:
            max_drawdown = current_drawdown = 0.0

        # Consecutive losses
        consecutive_losses, max_consecutive = self._compute_streaks(resolved)

        # Prediction accuracy (bootstrap already excluded from resolved)
        with_outcomes = [t for t in resolved if t.was_correct is not None]
        accuracy = (
            sum(1 for t in with_outcomes if t.was_correct) / len(with_outcomes)
            if with_outcomes else 0.0
        )

        # Confidence stats
        confs = [t.confidence for t in resolved]
        avg_conf = np.mean(confs) if confs else 0.0

        # Confidence calibration
        calibration = self._compute_calibration(with_outcomes)

        # Edge capture
        edge_capture = self._compute_edge_capture(resolved)

        # Time-based stats
        one_day = 86400
        one_hour = 3600
        today_trades = [t for t in resolved if now - t.timestamp < one_day]
        hour_trades = [t for t in resolved if now - t.timestamp < one_hour]
        daily_pnl = sum(t.pnl_cents / 100.0 for t in today_trades)
        hourly_pnl = sum(t.pnl_cents / 100.0 for t in hour_trades)

        # Unique markets
        unique_markets = len(set(t.ticker for t in resolved))

        snap = PerformanceSnapshot(
            timestamp=now,
            total_pnl=total_pnl,
            daily_pnl=daily_pnl,
            hourly_pnl=hourly_pnl,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=max(pnls) if pnls else 0.0,
            largest_loss=min(pnls) if pnls else 0.0,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            consecutive_losses=consecutive_losses,
            max_consecutive_losses=max_consecutive,
            prediction_accuracy=accuracy,
            avg_confidence=avg_conf,
            confidence_calibration=calibration,
            edge_capture=edge_capture,
            total_trades=len(all_resolved),
            real_trades=len(resolved),
            bootstrap_trades=len(all_resolved) - len(resolved),
            trades_today=len(today_trades),
            trades_this_hour=len(hour_trades),
            unique_markets=unique_markets,
            regime=self.detect_regime(resolved),
        )

        self._snapshots.append(snap)
        return snap

    # ── Regime Detection ──────────────────────────────────────────────

    def detect_regime(self, trades: list[TradeRecord] | None = None) -> str:
        """
        Detect current market regime from actual MARKET DATA,
        not from P&L (Phase 15).

        Uses the market snapshot buffer (midpoints, spreads, volumes)
        recorded during each scan cycle.  This gives an objective view
        of market conditions rather than conflating model performance
        with market dynamics.

        Regimes:
        - "trending": directional price moves across markets
        - "mean_reverting": prices bouncing, low autocorrelation
        - "volatile": large price swings across markets
        - "quiet": low volatility, tight ranges
        """
        # Use market snapshots for regime detection (not P&L)
        snapshots = list(self.memory._snapshots)
        if len(snapshots) < 20:
            return "unknown"

        # Take last 100 snapshots
        recent = snapshots[-100:]
        midpoints = np.array([s.midpoint for s in recent], dtype=np.float32)
        spreads = np.array([s.spread for s in recent], dtype=np.float32)

        if len(midpoints) < 10:
            return "unknown"

        # Price returns (changes between consecutive snapshots)
        returns = np.diff(midpoints)
        if len(returns) < 5:
            return "unknown"

        volatility = float(np.std(returns))
        avg_spread = float(np.mean(spreads))

        # Autocorrelation of price returns
        # (positive = trending, negative = mean-reverting)
        if len(returns) > 2:
            autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1])
            if np.isnan(autocorr):
                autocorr = 0.0
        else:
            autocorr = 0.0

        # Classify based on market-level metrics
        if volatility > 0.02 or avg_spread > 0.06:
            return "volatile"
        elif volatility < 0.005 and avg_spread < 0.03:
            return "quiet"
        elif autocorr > 0.15:
            return "trending"
        elif autocorr < -0.15:
            return "mean_reverting"
        else:
            return "mixed"

    # ── Health Checks ─────────────────────────────────────────────────

    def is_model_degrading(self, lookback: int = 5) -> bool:
        """Check if recent performance shows model degradation."""
        if len(self._snapshots) < lookback + 1:
            return False

        recent = list(self._snapshots)[-lookback:]
        older = list(self._snapshots)[-(lookback * 2):-lookback]

        if not older:
            return False

        recent_acc = np.mean([s.prediction_accuracy for s in recent])
        older_acc = np.mean([s.prediction_accuracy for s in older])

        recent_pnl = np.mean([s.hourly_pnl for s in recent])
        older_pnl = np.mean([s.hourly_pnl for s in older])

        # Degradation: accuracy dropped >10% OR P&L significantly worse
        acc_degraded = recent_acc < older_acc * 0.9 if older_acc > 0 else False
        pnl_degraded = recent_pnl < older_pnl - 5.0  # $5 worse

        if acc_degraded or pnl_degraded:
            log.warning(
                "model_degradation_detected",
                recent_acc=f"{recent_acc:.3f}",
                older_acc=f"{older_acc:.3f}",
                recent_pnl=f"${recent_pnl:.2f}",
                older_pnl=f"${older_pnl:.2f}",
            )
            return True
        return False

    def should_pause_trading(self) -> tuple[bool, str]:
        """Determine if Frankenstein should pause trading.
        
        LEARNING MODE: For the first 100 real trades, we NEVER pause
        on accuracy — the system needs time to learn from real outcomes.
        We only pause on hard loss limits during learning mode.
        """
        if not self._snapshots:
            return False, "no_data"

        latest = self._snapshots[-1]
        in_learning_mode = latest.real_trades < 100

        # Rule 1: Consecutive losses — relaxed during learning mode
        # During learning, tiny paper trades losing a few cents each
        # should NOT pause the system.  Allow up to 25 consecutive losses.
        # After learning, tighten to 8.
        max_consec = 100 if in_learning_mode else 50
        if latest.consecutive_losses >= max_consec:
            return True, f"consecutive_losses_{latest.consecutive_losses}"

        # Rule 2: Daily loss limit — always enforced but relaxed in learning
        daily_limit = -200 if in_learning_mode else -150
        if latest.daily_pnl < daily_limit:
            return True, f"daily_loss_${abs(latest.daily_pnl):.0f}"

        # Rule 3: Max drawdown — always enforced
        if latest.max_drawdown < -1500:
            return True, f"max_drawdown_${abs(latest.max_drawdown):.0f}"

        # Rule 4: Model accuracy — ONLY after 100+ real trades
        # During learning mode, we let Frankenstein trade freely
        # so it can gather enough data to actually learn
        # Phase 5: Much lower threshold — agents handle their own gating
        if not in_learning_mode and latest.prediction_accuracy < 0.08:
            return True, f"low_accuracy_{latest.prediction_accuracy:.1%}"

        return False, "ok"

    # ── Confidence Calibration ────────────────────────────────────────

    def _compute_calibration(self, trades: list[TradeRecord]) -> float:
        """
        Compute confidence calibration error.

        Perfect calibration = 0.0 (e.g., 70% confidence trades win 70%).
        Higher = worse calibration.
        """
        if not trades:
            return 0.0

        buckets: dict[int, list[bool]] = {}
        for t in trades:
            bucket = min(int(t.confidence * 10), 9)
            buckets.setdefault(bucket, []).append(bool(t.was_correct))

        total_error = 0.0
        n_buckets = 0
        for bucket, outcomes in buckets.items():
            if len(outcomes) < 3:
                continue
            expected = (bucket + 0.5) / 10.0
            actual = sum(outcomes) / len(outcomes)
            total_error += abs(expected - actual)
            n_buckets += 1

            # Update persistent calibration
            key = f"{bucket/10:.1f}-{(bucket+1)/10:.1f}"
            if key in self._calibration_buckets:
                self._calibration_buckets[key]["total"] += len(outcomes)
                self._calibration_buckets[key]["correct"] += sum(outcomes)

        return total_error / n_buckets if n_buckets > 0 else 0.0

    def _compute_edge_capture(self, trades: list[TradeRecord]) -> float:
        """How much of our predicted edge we actually captured."""
        if not trades:
            return 0.0

        predicted_edges = []
        actual_returns = []

        for t in trades:
            if t.edge != 0 and t.pnl_cents != 0:
                predicted_edges.append(abs(t.edge))
                actual_returns.append(t.pnl_cents / max(t.total_cost_cents, 1))

        if not predicted_edges:
            return 0.0

        avg_predicted = np.mean(predicted_edges)
        avg_actual = np.mean(actual_returns)

        return float(avg_actual / avg_predicted) if avg_predicted > 0 else 0.0

    def reset_for_fresh_start(self) -> None:
        """Reset performance state for a fresh start after resume.
        
        This prevents old history from immediately re-pausing the system.
        """
        self.snapshots.clear()
        self._trade_outcomes.clear()
        print("[Performance] Reset for fresh start — old history cleared")

    def _compute_streaks(self, trades: list[TradeRecord]) -> tuple[int, int]:
        """Compute current and max consecutive loss streaks."""
        current = 0
        max_streak = 0

        for t in sorted(trades, key=lambda x: x.timestamp):
            if t.outcome == TradeOutcome.LOSS:
                current += 1
                max_streak = max(max_streak, current)
            elif t.outcome == TradeOutcome.WIN:
                current = 0

        return current, max_streak

    # ── Category Breakdown ────────────────────────────────────────────

    def performance_by_category(self) -> dict[str, dict[str, Any]]:
        """Break down performance by market category."""
        trades = self.memory.get_recent_trades(n=100_000)
        categories: dict[str, list[TradeRecord]] = {}

        for t in trades:
            if t.outcome == TradeOutcome.PENDING:
                continue
            cat = t.category or "unknown"
            categories.setdefault(cat, []).append(t)

        result = {}
        for cat, cat_trades in categories.items():
            pnls = [t.pnl_cents / 100.0 for t in cat_trades]
            wins = sum(1 for t in cat_trades if t.outcome == TradeOutcome.WIN)
            result[cat] = {
                "trades": len(cat_trades),
                "win_rate": wins / len(cat_trades) if cat_trades else 0.0,
                "total_pnl": sum(pnls),
                "avg_pnl": np.mean(pnls) if pnls else 0.0,
                "best_trade": max(pnls) if pnls else 0.0,
                "worst_trade": min(pnls) if pnls else 0.0,
            }

        return result

    # ── Summary ───────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Full performance summary for API/dashboard."""
        snap = self.compute_snapshot()
        should_pause, pause_reason = self.should_pause_trading()

        return {
            "snapshot": snap.to_dict(),
            "model_degrading": self.is_model_degrading(),
            "should_pause": should_pause,
            "pause_reason": pause_reason,
            "regime": snap.regime,
            "calibration_buckets": self._calibration_buckets,
            "by_category": self.performance_by_category(),
            "snapshots_recorded": len(self._snapshots),
        }
