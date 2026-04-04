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

        # Session start time — adaptation metrics only use trades after this
        self.session_start_time: float = time.time()

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
        all_resolved = [t for t in trades if t.outcome not in (TradeOutcome.PENDING, TradeOutcome.CANCELLED, TradeOutcome.EXPIRED)]

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

        # Session-only trades — adaptation should react to THIS session, not
        # stale data from previous runs that already shaped the model
        # Also exclude expired from session — expired = unfilled maker order, NOT a prediction failure
        session_resolved = [t for t in resolved if t.timestamp >= self.session_start_time]

        # Use session trades for adaptation metrics when available.
        # If NO session trades have resolved yet (common — trades stay PENDING
        # until market settles), use NEUTRAL defaults so adaptation does nothing.
        has_session_data = len(session_resolved) >= 3

        # P&L stats (all-time for reporting)
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

        # Consecutive losses — use SESSION trades only so old loss streaks
        # don't keep triggering adaptation tightening forever
        if has_session_data:
            consecutive_losses, max_consecutive = self._compute_streaks(session_resolved)
        else:
            # No session data resolved yet — neutral (no streak)
            consecutive_losses, max_consecutive = 0, 0

        # Prediction accuracy — session trades for adaptation, not historical
        if has_session_data:
            with_outcomes = [t for t in session_resolved if t.was_correct is not None]
            accuracy = (
                sum(1 for t in with_outcomes if t.was_correct) / len(with_outcomes)
                if with_outcomes else 0.5
            )
        else:
            accuracy = 0.5  # Neutral — don't trigger poor_accuracy adaptation

        # Win rate for adaptation — use session trades
        if has_session_data:
            adapt_pnls = [t.pnl_cents / 100.0 for t in session_resolved]
            adapt_wins = [p for p in adapt_pnls if p > 0]
            adapt_win_rate = len(adapt_wins) / len(adapt_pnls) if adapt_pnls else 0.5
        else:
            adapt_win_rate = 0.5  # Neutral — don't trigger low_win_rate

        # Drawdown for adaptation — session only
        if has_session_data:
            adapt_pnls_dd = [t.pnl_cents / 100.0 for t in session_resolved]
            adapt_equity = np.cumsum(adapt_pnls_dd)
            adapt_running_max = np.maximum.accumulate(adapt_equity)
            adapt_drawdowns = adapt_equity - adapt_running_max
            adapt_current_dd = float(adapt_drawdowns[-1])
        else:
            adapt_current_dd = 0.0  # Neutral — don't trigger drawdown adaptation

        # Confidence calibration — session only
        if has_session_data:
            cal_outcomes = [t for t in session_resolved if t.was_correct is not None]
            calibration = self._compute_calibration(cal_outcomes) if cal_outcomes else 0.0
        else:
            calibration = 0.0  # Neutral

        # Confidence stats
        confs = [t.confidence for t in resolved]
        avg_conf = np.mean(confs) if confs else 0.0

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
            win_rate=adapt_win_rate,        # Session-based for adaptation
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=max(pnls) if pnls else 0.0,
            largest_loss=min(pnls) if pnls else 0.0,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            current_drawdown=adapt_current_dd,  # Session-based for adaptation
            consecutive_losses=consecutive_losses,
            max_consecutive_losses=max_consecutive,
            prediction_accuracy=accuracy,       # Session-based for adaptation
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
        """Check trading health — Phase 25: now actually pauses on catastrophic conditions.

        Previously NEVER paused. Now pauses on:
        1. Extreme daily loss (>$50 in paper trading)
        2. Extreme consecutive losses (>20 in a row)
        3. Extreme max drawdown (>$200)

        These are CATASTROPHIC thresholds — normal bad streaks don't trigger.
        The system still learns from losses, but catastrophic bleeding
        indicates a systematic problem that needs human review.
        """
        if not self._snapshots:
            return False, "ok"

        latest = self._snapshots[-1]

        # Catastrophic consecutive losses — 20+ in a row
        if latest.consecutive_losses >= 20:
            log.warning("CATASTROPHIC_HEALTH", kind="consecutive_losses",
                        value=latest.consecutive_losses)
            return True, f"catastrophic_consecutive_losses ({latest.consecutive_losses})"

        # Catastrophic daily loss — >$50 lost today
        if latest.daily_pnl < -50:
            log.warning("CATASTROPHIC_HEALTH", kind="daily_loss",
                        value=f"${abs(latest.daily_pnl):.0f}")
            return True, f"catastrophic_daily_loss (${abs(latest.daily_pnl):.0f})"

        # Catastrophic drawdown — >$200
        if latest.max_drawdown < -200:
            log.warning("CATASTROPHIC_HEALTH", kind="max_drawdown",
                        value=f"${abs(latest.max_drawdown):.0f}")
            return True, f"catastrophic_drawdown (${abs(latest.max_drawdown):.0f})"

        # Log warnings for monitoring — but don't pause for moderate issues
        if latest.consecutive_losses >= 10:
            log.warning("health_warning", kind="consecutive_losses",
                        value=latest.consecutive_losses)
        if latest.daily_pnl < -25:
            log.warning("health_warning", kind="daily_loss",
                        value=f"${abs(latest.daily_pnl):.0f}")

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
        self._snapshots.clear()
        log.info("performance_reset_for_fresh_start", msg="Snapshots cleared for fresh start")

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

    # Phase 5+16+20+24b: Category retirement — auto-disable losing categories
    # Phase 24b: Now uses rolling window so categories can recover as model improves
    _RETIREMENT_MIN_TRADES = 30      # Need 30+ trades to judge (was 20 — too trigger-happy)
    _RETIREMENT_WR_THRESHOLD = 0.22  # Win rate below 22% → retire (was 28% — too aggressive)
    _RETIREMENT_COOLDOWN_H = 4.0     # 4h cooldown — give categories time to find new signal
    _RETIREMENT_MAX_LOSS_STREAK = 10 # 10 consecutive losses → immediate cooldown (was 8)
    _RETIREMENT_MAX_LOSS_DOLLARS = -40.0  # Phase 24: Loosened from -$25 — intelligence data should help
    _RETIREMENT_ROLLING_WINDOW = 50  # Phase 24b: Only look at last 50 trades per category for retirement

    def __init_retirement(self) -> None:
        """Initialize retirement tracking (called lazily)."""
        if not hasattr(self, "_retired_categories"):
            self._retired_categories: dict[str, float] = {}  # category → cooldown_until timestamp

    def retired_categories(self) -> dict[str, float]:
        """Phase 20: Return categories currently in cooldown."""
        self.__init_retirement()
        now = time.time()
        # Purge expired cooldowns
        self._retired_categories = {
            c: t for c, t in self._retired_categories.items() if t > now
        }
        return dict(self._retired_categories)

    def is_category_retired(self, category: str) -> bool:
        """Phase 20: Check if a category is currently in retirement cooldown."""
        self.__init_retirement()
        cooldown_until = self._retired_categories.get(category, 0)
        if cooldown_until > time.time():
            return True
        # Expired — remove
        self._retired_categories.pop(category, None)
        return False

    def unretire_category(self, category: str) -> bool:
        """Phase 24b: Force-unretire a specific category. Returns True if it was retired."""
        self.__init_retirement()
        was_retired = category in self._retired_categories
        self._retired_categories.pop(category, None)
        if was_retired:
            log.info("🧟✅ CATEGORY UNRETIRED", category=category)
        return was_retired

    def unretire_all(self) -> list[str]:
        """Phase 24b: Force-unretire all categories. Returns list of previously retired."""
        self.__init_retirement()
        previously = list(self._retired_categories.keys())
        self._retired_categories.clear()
        if previously:
            log.info("🧟✅ ALL CATEGORIES UNRETIRED", categories=previously)
        return previously

    def evaluate_retirements(self) -> list[str]:
        """
        Phase 20+24b: Evaluate category performance and retire underperformers.

        Phase 24b: Uses rolling window (last N trades per category) instead of
        all-time stats. This lets categories recover as the model/intelligence
        improves, rather than being permanently poisoned by old history.

        Returns list of newly retired categories.
        """
        self.__init_retirement()
        now = time.time()
        newly_retired: list[str] = []

        by_cat = self._rolling_category_stats()
        for cat, stats in by_cat.items():
            # Never retire catch-all buckets — they're not real categories
            if cat in ("unknown", "general", ""):
                continue
            # Skip if already retired
            if self.is_category_retired(cat):
                continue

            trades = stats.get("trades", 0)
            wr = stats.get("win_rate", 0.0)

            # Need minimum trades to judge
            if trades < self._RETIREMENT_MIN_TRADES:
                continue

            total_pnl = stats.get("total_pnl", 0.0)
            reason = None

            # Check win rate threshold
            if wr < self._RETIREMENT_WR_THRESHOLD:
                reason = f"win_rate={wr:.1%} < {self._RETIREMENT_WR_THRESHOLD:.0%}"

            # Phase 16: PnL-based retirement — stop bleeding money
            if total_pnl < self._RETIREMENT_MAX_LOSS_DOLLARS:
                reason = f"pnl=${total_pnl:.2f} < ${self._RETIREMENT_MAX_LOSS_DOLLARS:.2f}"

            if reason:
                cooldown_until = now + self._RETIREMENT_COOLDOWN_H * 3600
                self._retired_categories[cat] = cooldown_until
                newly_retired.append(cat)
                log.warning(
                    "🧟💀 CATEGORY RETIRED",
                    category=cat,
                    reason=reason,
                    win_rate=f"{wr:.1%}",
                    total_pnl=f"${total_pnl:.2f}",
                    trades=trades,
                    cooldown_hours=self._RETIREMENT_COOLDOWN_H,
                    resumes_at=time.strftime("%H:%M", time.localtime(cooldown_until)),
                    window=self._RETIREMENT_ROLLING_WINDOW,
                )

        return newly_retired

    def _rolling_category_stats(self) -> dict[str, dict[str, Any]]:
        """
        Phase 24b: Category stats using only trades from the current session
        (since session_start_time), with rolling window cap.
        This prevents old-model performance from permanently blocking categories
        that might now be profitable with improved intelligence data.
        """
        trades = self.memory.get_recent_trades(n=100_000)
        categories: dict[str, list[TradeRecord]] = {}

        session_start = self.session_start_time

        for t in trades:
            if t.outcome in (TradeOutcome.PENDING, TradeOutcome.CANCELLED, TradeOutcome.EXPIRED):
                continue
            # Only consider trades from current session
            if t.timestamp < session_start:
                continue
            cat = t.category or "unknown"
            categories.setdefault(cat, []).append(t)

        result = {}
        window = self._RETIREMENT_ROLLING_WINDOW
        for cat, cat_trades in categories.items():
            # Sort by timestamp descending, take only last N
            recent = sorted(cat_trades, key=lambda t: t.timestamp, reverse=True)[:window]
            pnls = [t.pnl_cents / 100.0 for t in recent]
            wins = sum(1 for t in recent if t.outcome == TradeOutcome.WIN)
            result[cat] = {
                "trades": len(recent),
                "win_rate": wins / len(recent) if recent else 0.0,
                "total_pnl": sum(pnls),
                "avg_pnl": float(np.mean(pnls)) if pnls else 0.0,
                "best_trade": max(pnls) if pnls else 0.0,
                "worst_trade": min(pnls) if pnls else 0.0,
                "window_used": len(recent),
                "session_only": True,
            }

        return result

    def performance_by_category(self) -> dict[str, dict[str, Any]]:
        """Break down performance by market category."""
        trades = self.memory.get_recent_trades(n=100_000)
        categories: dict[str, list[TradeRecord]] = {}

        for t in trades:
            # Exclude pending, cancelled, AND expired — expired = unfilled maker order, not a prediction
            if t.outcome in (TradeOutcome.PENDING, TradeOutcome.CANCELLED, TradeOutcome.EXPIRED):
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
            "retired_categories": self.retired_categories(),
        }
